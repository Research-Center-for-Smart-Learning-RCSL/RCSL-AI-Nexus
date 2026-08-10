import { createServer } from 'node:http';

const JSON_HEADERS = { 'content-type': 'application/json' };

function sendJson(response, status, body) {
  response.writeHead(status, JSON_HEADERS);
  response.end(JSON.stringify(body));
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

/**
 * A controllable runtime, speaking enough of Ollama's HTTP API to be reached by
 * the real OllamaAdapter.
 *
 * The gateway under test is unmodified: no stub is injected into it, and
 * `OLLAMA_BASE_URL` is the only thing that points it here. What that buys is the
 * one observation the harness is built for -- the `model` field of `/api/chat`
 * is the ref routing selected, taken off the wire rather than from a test double
 * the application was handed.
 *
 * `/api/tags` and `/api/ps` report both seeded models as present and resident,
 * so the admin entrance's residency read-back agrees with the registry's intent.
 * Left empty they would contradict it, and routing ranks an observation above
 * intent, so every request would be refused for a reason belonging to the
 * fixture rather than to the policy.
 */
export async function startFakeOllama({ refs = [] } = {}) {
  const generations = [];
  // Mutable, because the seeder decides what the models are and the runtime has
  // to be listening before the seeder can run against a gateway that points at
  // it. Reporting the wrong set is not a cosmetic problem: residency outranks
  // registry intent in routing, so a model this claims not to hold is a model
  // no policy can select.
  let claimed = [...refs];

  const server = createServer(async (request, response) => {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1');

    if (url.pathname === '/api/chat' && request.method === 'POST') {
      let body;
      try {
        body = await readJson(request);
      } catch {
        sendJson(response, 400, { error: 'expected a JSON chat request' });
        return;
      }

      generations.push({ model: body.model, messages: body.messages ?? [] });

      // NDJSON, one object per line, terminated by an event carrying `done`.
      // The adapter raises StreamInterruptedError on a stream that stops
      // without one, so the terminal event is what makes this a completion
      // rather than a failure the test would have to interpret.
      response.writeHead(200, { 'content-type': 'application/x-ndjson' });
      response.write(
        `${JSON.stringify({ model: body.model, message: { role: 'assistant', content: `served by ${body.model}` } })}\n`,
      );
      response.end(
        `${JSON.stringify({
          model: body.model,
          message: { role: 'assistant', content: '' },
          done: true,
          done_reason: 'stop',
          eval_count: 4,
          prompt_eval_count: 7,
        })}\n`,
      );
      return;
    }

    if (url.pathname === '/api/tags' && request.method === 'GET') {
      sendJson(response, 200, { models: claimed.map((name) => ({ name, size: 0 })) });
      return;
    }

    if (url.pathname === '/api/ps' && request.method === 'GET') {
      sendJson(response, 200, {
        models: claimed.map((name) => ({ name, size: 8 * 1024 ** 3 })),
      });
      return;
    }

    // Load and unload. The adapter only checks the status.
    if (
      (url.pathname === '/api/generate' || url.pathname === '/api/embed') &&
      request.method === 'POST'
    ) {
      await readJson(request).catch(() => ({}));
      sendJson(response, 200, { done: true });
      return;
    }

    if (url.pathname === '/__e2e__/generations' && request.method === 'GET') {
      sendJson(response, 200, { generations });
      return;
    }

    if (url.pathname === '/__e2e__/reset' && request.method === 'POST') {
      generations.length = 0;
      sendJson(response, 200, { generations });
      return;
    }

    sendJson(response, 404, { error: `unhandled runtime route: ${url.pathname}` });
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });

  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('The fake Ollama did not acquire a TCP port.');
  }

  return {
    url: `http://127.0.0.1:${address.port}`,
    setRefs(next) {
      claimed = [...next];
    },
    async close() {
      await new Promise((resolve) => {
        server.close(resolve);
        server.closeAllConnections();
      });
    },
  };
}
