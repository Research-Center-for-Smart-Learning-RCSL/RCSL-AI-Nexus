/**
 * The browser-to-Postgres harness: one Postgres, the real admin entrance, the
 * real gateway, and a controllable runtime, all sharing state.
 *
 * Every other Playwright path here stops at the browser's network boundary and
 * says so. That is the right bound for a form's contract, and it cannot answer
 * the question ROADMAP has carried since the policy editor shipped: does
 * editing a routing policy change which model the *gateway* serves? Persistence
 * is proven by the backend integration suite and the form's PUT is proven by
 * `routing-policies.spec.ts`; nothing joined the two, so both could be right
 * while the join was broken.
 *
 * Nothing is stubbed inside the applications. The admin entrance runs in
 * `AUTH_MODE=dev`, which substitutes the header `tailscale serve` injects and
 * leaves every downstream step -- the users lookup, the role, the scopes, CSRF
 * -- exactly as deployed. The runtime is real HTTP to a fake Ollama, so the ref
 * the assertion reads comes off a socket rather than from a double.
 *
 * `CACHE_BACKEND=memory` is the one deployment difference. Redis holds sessions
 * and rate-limit counters; the tailnet entrance uses neither, and configuration
 * refuses `memory` under `ENV=production`, so the substitution cannot leak into
 * a deployment.
 */

import { join } from 'node:path';

import { startFakeOllama } from './fake-ollama.mjs';
import {
  availablePort,
  isWindows,
  resultOf,
  spawnTracked,
  stopProcessTree,
  waitForHttp,
  withTimeout,
} from './processes.mjs';

const PEPPER = 'e2e-harness-pepper';

/**
 * The gateway's own ceiling on a request body is derived from this, and both
 * applications refuse to start if the two disagree with the registered models'
 * context length. Small and explicit, so a default moving does not silently
 * change what the harness proves.
 */
const MAX_CONTEXT_LENGTH = '32768';

function backendEnv(repoRoot, { databaseUrl, ollamaUrl }) {
  return {
    ...process.env,
    ENV: 'development',
    AUTH_MODE: 'dev',
    DATABASE_URL: databaseUrl,
    API_KEY_PEPPER: PEPPER,
    CACHE_BACKEND: 'memory',
    COOKIE_SECURE: 'false',
    OLLAMA_BASE_URL: ollamaUrl,
    MAX_CONTEXT_LENGTH,
    // uv resolves the project from the working directory, which is `backend`
    // for every child here; PYTHONPATH is what lets the seeder import `app`
    // and `tests` while living in the repository's own scripts directory.
    PYTHONPATH: join(repoRoot, 'backend'),
  };
}

async function seedDatabase(repoRoot, env, register) {
  const seeder = spawnTracked(
    'uv',
    ['run', 'python', join(repoRoot, 'scripts', 'e2e_seed_stack.py')],
    {
      cwd: join(repoRoot, 'backend'),
      env,
      // stdout is the only copy of the API key; stderr goes to the console so a
      // migration failure is readable rather than swallowed into a timeout.
      stdio: ['ignore', 'pipe', 'inherit'],
      shell: isWindows,
      detached: !isWindows,
    },
    'the E2E database seeder',
  );
  // Registered before it is awaited, so a run that gives up on the deadline
  // below still takes the process down. Left alive it keeps asyncpg connections
  // and an Alembic advisory lock against the very database the next attempt has
  // to drop and rebuild.
  register(() => stopProcessTree(seeder, 'the E2E database seeder'));

  let output = '';
  seeder.stdout.setEncoding('utf8');
  seeder.stdout.on('data', (chunk) => {
    output += chunk;
  });
  // `exit` fires when the process ends; the pipes can still be undrained at
  // that point, so waiting on it alone can read an empty or truncated summary
  // from a seeder that succeeded. This is the one place in the run where stdout
  // carries something load-bearing, and the failure would be intermittent.
  const drained = new Promise((resolve) => seeder.stdout.once('end', resolve));

  const outcome = await withTimeout(
    Promise.all([resultOf(seeder), drained]).then(([result]) => result),
    Number(process.env.E2E_SEED_TIMEOUT_MS ?? 3 * 60_000),
    'Seeding the E2E database exceeded its 3-minute deadline.',
  );
  if (outcome.error) throw outcome.error;
  if (outcome.code !== 0) {
    throw new Error(`The E2E database seeder failed with exit code ${outcome.code}.`);
  }

  try {
    return JSON.parse(output.trim());
  } catch (cause) {
    throw new Error('The E2E database seeder did not print a JSON summary.', { cause });
  }
}

function startUvicorn(repoRoot, env, { module: moduleName, port, label }) {
  return spawnTracked(
    'uv',
    [
      'run',
      'uvicorn',
      `${moduleName}:app`,
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
      // `info` rather than `warning`, which is what turns uvicorn's access log
      // on. It is noise on a green run and it is the only server-side record
      // that exists on a red one: when `routing-selection.spec.ts` failed on
      // 2026-08-18 with the admin entrance answering a GET from before a PUT
      // it had already acknowledged, the browser's trace could show both
      // requests and nothing could show what the server thought it was doing.
      // A few hundred lines in a job log is a cheap price for not having to
      // reproduce an intermittent failure to find out.
      '--log-level',
      'info',
    ],
    {
      cwd: join(repoRoot, 'backend'),
      env,
      stdio: 'inherit',
      detached: !isWindows,
      shell: isWindows,
    },
    label,
  );
}

export async function startFullStack({ repoRoot, databaseUrl }) {
  if (!databaseUrl) {
    throw new Error(
      'E2E_DATABASE_URL is required for the full-stack harness. ' +
        'Point it at a Postgres this run may drop and rebuild.',
    );
  }

  const started = [];
  const ollama = await startFakeOllama({ refs: [] });
  started.push(() => ollama.close());

  try {
    const env = backendEnv(repoRoot, { databaseUrl, ollamaUrl: ollama.url });
    const seeded = await seedDatabase(repoRoot, env, (stop) => started.push(stop));

    // The runtime can only claim the models once the seeder has decided what
    // they are, which is why it starts empty and is told afterwards.
    ollama.setRefs(Object.values(seeded.refs));

    const adminPort = await availablePort('127.0.0.1');
    const gatewayPort = await availablePort('127.0.0.1');

    const admin = startUvicorn(repoRoot, env, {
      module: 'app.infrastructure.main_admin_tailnet',
      port: adminPort,
      label: 'the admin entrance',
    });
    started.push(() => stopProcessTree(admin, 'the admin entrance'));

    const gateway = startUvicorn(repoRoot, env, {
      module: 'app.infrastructure.main_gateway',
      port: gatewayPort,
      label: 'the gateway',
    });
    started.push(() => stopProcessTree(gateway, 'the gateway'));

    const adminUrl = `http://127.0.0.1:${adminPort}`;
    const gatewayUrl = `http://127.0.0.1:${gatewayPort}`;

    await waitForHttp(`${adminUrl}/healthz`, {
      child: admin,
      label: 'The admin entrance',
      timeoutMs: Number(process.env.E2E_BACKEND_TIMEOUT_MS ?? 120_000),
    });
    await waitForHttp(`${gatewayUrl}/healthz`, {
      child: gateway,
      label: 'The gateway',
      timeoutMs: Number(process.env.E2E_BACKEND_TIMEOUT_MS ?? 120_000),
    });

    return {
      adminUrl,
      gatewayUrl,
      runtimeUrl: ollama.url,
      gatewayKey: seeded.gateway_key,
      initialAlias: seeded.initial_alias,
      aliases: seeded.aliases,
      refs: seeded.refs,
      async close() {
        for (const stop of started.reverse()) await stop();
      },
    };
  } catch (error) {
    for (const stop of started.reverse()) await stop();
    throw error;
  }
}
