/**
 * Start the deterministic admin fixture and Next.js, run Playwright, and
 * always terminate both process trees.
 *
 * Playwright's built-in webServer is the ordinary choice, but Next dev leaves
 * its worker alive during teardown on Windows. Owning every child here keeps
 * one command for CI and local development, including cancellation and spawn
 * failures rather than only the successful path.
 *
 * The browser drives a production build by default, not `next dev`. Dev mode
 * was what the tests originally ran against, and it made them assert around
 * artefacts that never ship: an off-screen development-overlay alert, and a
 * redirect deadline sized for a cold compile rather than for the application.
 * It also cannot exercise anything decided at build time — `NEXT_PUBLIC_*`
 * inlining and the absence of React StrictMode's double-invoked effects are
 * both properties of the build, and the deployed image is a build. `--dev`
 * keeps the hot-reloading loop for local iteration, which is what `test:e2e:ui`
 * uses.
 *
 * The e2e build writes to its own `NEXT_DIST_DIR` because it is not the
 * artefact that ships: it has a test CSRF cookie name inlined into the client
 * bundle. Sharing `.next` with `pnpm build` would let that value escape into
 * something a person could mistake for a deployable build.
 *
 * `--full-stack` swaps the deterministic admin fixture for the real admin
 * entrance, the real gateway and a Postgres this run rebuilds, and runs only
 * the paths under `e2e/full-stack`. It is a separate mode rather than an
 * addition because the default run must stay runnable with no database: making
 * every path depend on one is how the browser-to-gateway join went untested for
 * as long as it did. See `e2e/support/full-stack.mjs`.
 */

import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { startAdminTestServer } from '../e2e/support/admin-server.mjs';
import { startFullStack } from '../e2e/support/full-stack.mjs';
import {
  availablePort,
  delay,
  isWindows,
  resultOf,
  spawnTracked,
  stopProcessTree,
  withTimeout,
} from '../e2e/support/processes.mjs';

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(frontendDir, '..');

const runnerArgs = process.argv.slice(2);
if (runnerArgs[0] === '--') runnerArgs.shift();
const devMode = runnerArgs.includes('--dev');
const fullStackMode = runnerArgs.includes('--full-stack');
const testArgs = runnerArgs.filter(
  (argument) => argument !== '--dev' && argument !== '--full-stack',
);

async function serverAddress() {
  const requested = process.env.PLAYWRIGHT_BASE_URL;
  if (!requested) {
    const port = await availablePort('127.0.0.1');
    return new URL(`http://127.0.0.1:${port}`);
  }

  const url = new URL(requested);
  if (
    url.protocol !== 'http:' ||
    !['127.0.0.1', 'localhost'].includes(url.hostname)
  ) {
    throw new Error('PLAYWRIGHT_BASE_URL must be an http:// loopback address.');
  }
  if (url.pathname !== '/' || url.search || url.hash) {
    throw new Error('PLAYWRIGHT_BASE_URL must contain only an origin.');
  }
  const port = Number(url.port || '80');
  await availablePort(url.hostname, port);
  return url;
}

const serverURL = await serverAddress();
const baseURL = serverURL.origin;

// Two mutually exclusive worlds behind one command. The default run proves the
// browser's own contracts against a deterministic fixture; `--full-stack` runs
// the paths that only mean something with a real backend behind them, and gives
// Next a real admin entrance to proxy to. Mixing them would make every default
// run depend on a Postgres, which is what kept the join untested for so long.
const adminServer = fullStackMode ? null : await startAdminTestServer();
const fullStack = fullStackMode
  ? await startFullStack({
      repoRoot,
      databaseUrl: process.env.E2E_DATABASE_URL,
    })
  : null;

const childEnv = {
  ...process.env,
  ADMIN_API_URL: fullStack ? fullStack.adminUrl : adminServer.url,
  E2E_ADMIN_API_URL: fullStack ? fullStack.adminUrl : adminServer.url,
  ...(fullStack
    ? {
        E2E_FULL_STACK: '1',
        E2E_GATEWAY_URL: fullStack.gatewayUrl,
        E2E_GATEWAY_KEY: fullStack.gatewayKey,
        E2E_RUNTIME_URL: fullStack.runtimeUrl,
        E2E_INITIAL_ALIAS: fullStack.initialAlias,
        E2E_MODEL_REFS: JSON.stringify(fullStack.refs),
      }
    : {}),
  // Inlined into the client bundle at build time. The shipped default is
  // `__Host-nexus_csrf`, which requires Secure and is therefore dropped over
  // the loopback http origin these tests use.
  NEXT_PUBLIC_CSRF_COOKIE: 'nexus_csrf',
  // Dev mode keeps the ordinary `.next` so its compile cache survives between
  // runs; a production e2e build must not land there. See the file header.
  ...(devMode ? {} : { NEXT_DIST_DIR: '.next-e2e' }),
};

const nextBin = join(frontendDir, 'node_modules', 'next', 'dist', 'bin', 'next');
const playwrightBin = join(
  frontendDir,
  'node_modules',
  '@playwright',
  'test',
  'cli.js',
);

let builder = null;
let nextServer = null;
let tests = null;
let shutdownPromise = null;

function stopServers() {
  if (!shutdownPromise) {
    shutdownPromise = (async () => {
      await stopProcessTree(tests, 'Playwright');
      await stopProcessTree(nextServer, 'Next.js');
      await stopProcessTree(builder, 'the Next.js build');
      await adminServer?.close();
      await fullStack?.close();
    })();
  }
  return shutdownPromise;
}

/**
 * Build the application the way the browser will meet it, and fail loudly.
 *
 * A build is also a check: a server/client boundary violation cannot be
 * observed from a dev-mode run, and the tests below would report green while
 * the deployed image refused to build at all.
 */
async function buildApplication() {
  builder = spawnTracked(
    process.execPath,
    [nextBin, 'build'],
    { cwd: frontendDir, env: childEnv, stdio: 'inherit', detached: !isWindows },
    'the Next.js build',
  );

  const outcome = await withTimeout(
    resultOf(builder),
    Number(process.env.E2E_BUILD_TIMEOUT_MS ?? 5 * 60_000),
    'The Next.js build exceeded the 5-minute runner deadline.',
  );
  if (outcome.error) {
    throw new Error('Could not start the Next.js build.', { cause: outcome.error });
  }
  if (outcome.code !== 0) {
    throw new Error(`The Next.js build failed with exit code ${outcome.code}.`);
  }
}

async function waitUntilReady() {
  const deadline = Date.now() + 120_000;
  const loginURL = new URL('/login', baseURL);

  while (Date.now() < deadline) {
    const outcome = nextServer
      ? await Promise.race([resultOf(nextServer), delay(0)])
      : null;
    if (outcome) {
      const detail = outcome.error?.message ?? outcome.signal ?? outcome.code;
      throw new Error(`Next.js exited before it became ready (${detail}).`);
    }
    try {
      const response = await fetch(loginURL, {
        signal: AbortSignal.timeout(2_000),
      });
      if (response.status < 500) {
        await delay(100);
        if (nextServer.exitCode === null) return;
      }
    } catch {
      // The socket is not listening yet.
    }
    await delay(250);
  }
  throw new Error(`Next.js did not become ready at ${loginURL} within 120 seconds.`);
}

let handlingSignal = false;
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => {
    if (handlingSignal) return;
    handlingSignal = true;
    void stopServers().finally(() => process.exit(1));
  });
}

let exitCode = 1;
try {
  if (!devMode) await buildApplication();

  nextServer = spawnTracked(
    process.execPath,
    [
      nextBin,
      devMode ? 'dev' : 'start',
      '--hostname',
      serverURL.hostname,
      '--port',
      serverURL.port || '80',
    ],
    {
      cwd: frontendDir,
      env: childEnv,
      stdio: 'inherit',
      detached: !isWindows,
    },
    'Next.js',
  );

  await waitUntilReady();

  tests = spawnTracked(
    process.execPath,
    [playwrightBin, 'test', ...testArgs],
    {
      cwd: frontendDir,
      env: { ...childEnv, PLAYWRIGHT_BASE_URL: baseURL },
      stdio: 'inherit',
      detached: !isWindows,
    },
    'Playwright',
  );

  const outcome = await withTimeout(
    resultOf(tests),
    Number(process.env.PLAYWRIGHT_RUN_TIMEOUT_MS ?? 10 * 60_000),
    'Playwright exceeded the 10-minute runner deadline.',
  );
  if (outcome.error) {
    throw new Error('Could not start Playwright.', { cause: outcome.error });
  }
  exitCode = outcome.code;
} catch (error) {
  console.error(error);
  exitCode = 1;
} finally {
  await stopServers();
}

process.exitCode = exitCode;
