import { createServer } from 'node:http';

const JSON_HEADERS = { 'content-type': 'application/json' };
const CSRF_TOKEN = 'csrf-e2e-chat';

function sendJson(response, status, body, headers = {}) {
  response.writeHead(status, { ...JSON_HEADERS, ...headers });
  response.end(JSON.stringify(body));
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

/**
 * A real HTTP boundary for browser behaviours that route.fulfill cannot model.
 *
 * Playwright interception is ideal for finite JSON responses. It cannot keep
 * an SSE response open while a test clicks Stop, so this server provides only
 * the two endpoints that path needs and exposes its observations to the test
 * runner. It deliberately remains an E2E fixture rather than an application
 * route: no test-only endpoint is compiled into the shipped frontend.
 */
export async function startAdminTestServer() {
  const states = new Map();
  const openStreams = new Map();
  const suppressedDisconnects = new WeakSet();
  let closing = false;

  function stateFor(caseId) {
    let state = states.get(caseId);
    if (!state) {
      state = { chatRequests: [], disconnectedStreams: 0 };
      states.set(caseId, state);
    }
    return state;
  }

  function caseIdFor(request, url) {
    const query = url.searchParams.get('case');
    if (query) return query;
    const cookies = request.headers.cookie?.split(';') ?? [];
    for (const cookie of cookies) {
      const [name, ...parts] = cookie.trim().split('=');
      if (name === 'e2e_case') return decodeURIComponent(parts.join('='));
    }
    return 'default';
  }

  const server = createServer(async (request, response) => {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1');

    if (url.pathname === '/admin/me' && request.method === 'GET') {
      sendJson(
        response,
        200,
        {
          id: '22222222-2222-2222-2222-222222222222',
          auth_mode: 'local',
          login: 'chat-user@example.org',
          display_name: 'Chat User',
          role: 'user',
          scopes: ['chat:use', 'usage:read_own'],
          session_expires_at: '2099-01-01T00:00:00Z',
        },
        { 'set-cookie': `nexus_csrf=${CSRF_TOKEN}; Path=/; SameSite=Lax` },
      );
      return;
    }

    if (url.pathname === '/admin/chat' && request.method === 'POST') {
      if (request.headers['x-csrf-token'] !== CSRF_TOKEN) {
        sendJson(response, 403, { message: 'Missing or invalid CSRF token.' });
        return;
      }
      const caseId = caseIdFor(request, url);
      const state = stateFor(caseId);
      try {
        state.chatRequests.push(await readJson(request));
      } catch {
        sendJson(response, 400, { message: 'Expected a JSON chat request.' });
        return;
      }

      response.writeHead(200, {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache, no-transform',
        connection: 'keep-alive',
      });
      response.flushHeaders();
      response.write(
        `data: ${JSON.stringify({ choices: [{ delta: { content: 'Partial reply' } }] })}\n\n`,
      );

      openStreams.set(response, caseId);
      const heartbeat = setInterval(() => {
        if (!response.destroyed) response.write(': keepalive\n\n');
      }, 250);
      heartbeat.unref();

      response.once('close', () => {
        clearInterval(heartbeat);
        openStreams.delete(response);
        if (!closing && !suppressedDisconnects.has(response)) {
          state.disconnectedStreams += 1;
        }
      });
      return;
    }

    if (url.pathname === '/__e2e__/state' && request.method === 'GET') {
      sendJson(response, 200, stateFor(caseIdFor(request, url)));
      return;
    }

    if (url.pathname === '/__e2e__/reset' && request.method === 'POST') {
      const caseId = caseIdFor(request, url);
      const state = stateFor(caseId);
      // A failed attempt may leave its stream open when Playwright retries the
      // test. Close it without counting it as the retry's user cancellation.
      for (const [stream, streamCaseId] of openStreams) {
        if (streamCaseId !== caseId) continue;
        suppressedDisconnects.add(stream);
        stream.destroy();
        openStreams.delete(stream);
      }
      state.chatRequests.length = 0;
      state.disconnectedStreams = 0;
      sendJson(response, 200, state);
      return;
    }

    sendJson(response, 404, { message: `Unhandled test route: ${url.pathname}` });
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });

  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('The E2E admin server did not acquire a TCP port.');
  }
  const url = `http://127.0.0.1:${address.port}`;

  return {
    url,
    async close() {
      closing = true;
      for (const response of openStreams.keys()) response.destroy();
      openStreams.clear();
      await new Promise((resolve) => {
        server.close(resolve);
        server.closeAllConnections();
      });
    },
  };
}
