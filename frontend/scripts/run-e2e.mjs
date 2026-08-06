/**
 * Start the deterministic admin fixture and Next.js, run Playwright, and
 * always terminate both process trees.
 *
 * Playwright's built-in webServer is the ordinary choice, but Next dev leaves
 * its worker alive during teardown on Windows. Owning every child here keeps
 * one command for CI and local development, including cancellation and spawn
 * failures rather than only the successful path.
 */

import { spawn } from 'node:child_process';
import { createServer as createPortProbe } from 'node:net';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { startAdminTestServer } from '../e2e/support/admin-server.mjs';

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const isWindows = process.platform === 'win32';
const children = new WeakMap();

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function withTimeout(promise, milliseconds, message) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(message)), milliseconds);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

function spawnTracked(command, args, options, label) {
  const child = spawn(command, args, options);
  const result = new Promise((resolve) => {
    child.once('error', (cause) =>
      resolve({
        code: 1,
        signal: null,
        error: new Error(`Could not start ${label}.`, { cause }),
      }),
    );
    child.once('exit', (code, signal) => resolve({ code: code ?? 1, signal }));
  });
  children.set(child, result);
  return child;
}

function resultOf(child) {
  return children.get(child);
}

async function availablePort(host, requestedPort = 0) {
  return new Promise((resolve, reject) => {
    const probe = createPortProbe();
    probe.once('error', reject);
    probe.listen({ host, port: requestedPort, exclusive: true }, () => {
      const address = probe.address();
      if (!address || typeof address === 'string') {
        probe.close();
        reject(new Error('Could not reserve a loopback port for Next.js.'));
        return;
      }
      probe.close((error) => (error ? reject(error) : resolve(address.port)));
    });
  });
}

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

async function stopProcessTree(child, label) {
  if (!child?.pid || child.exitCode !== null) return;

  if (isWindows) {
    const killer = spawnTracked(
      'taskkill',
      ['/PID', String(child.pid), '/T', '/F'],
      { stdio: 'ignore', windowsHide: true },
      `taskkill for ${label}`,
    );
    try {
      const result = await withTimeout(
        resultOf(killer),
        10_000,
        `Timed out terminating the ${label} process tree.`,
      );
      if (result.error || (result.code !== 0 && child.exitCode === null)) {
        console.warn(`Could not confirm that the ${label} process tree stopped.`);
      }
    } catch (error) {
      console.warn(error instanceof Error ? error.message : String(error));
      killer.kill();
    }
    child.unref();
    return;
  }

  try {
    process.kill(-child.pid, 'SIGTERM');
  } catch {
    return;
  }
  await Promise.race([resultOf(child), delay(2_000)]);

  // The group can outlive its leader. Probe the group rather than relying on
  // child.exitCode, then force down any worker that ignored SIGTERM.
  try {
    process.kill(-child.pid, 0);
    process.kill(-child.pid, 'SIGKILL');
  } catch {
    // The process group is already gone.
  }
}

const serverURL = await serverAddress();
const baseURL = serverURL.origin;
const adminServer = await startAdminTestServer();
const childEnv = {
  ...process.env,
  ADMIN_API_URL: adminServer.url,
  E2E_ADMIN_API_URL: adminServer.url,
  NEXT_PUBLIC_CSRF_COOKIE: 'nexus_csrf',
};

const nextBin = join(frontendDir, 'node_modules', 'next', 'dist', 'bin', 'next');
const playwrightBin = join(
  frontendDir,
  'node_modules',
  '@playwright',
  'test',
  'cli.js',
);

let nextServer = null;
let tests = null;
let shutdownPromise = null;

function stopServers() {
  if (!shutdownPromise) {
    shutdownPromise = (async () => {
      await stopProcessTree(tests, 'Playwright');
      await stopProcessTree(nextServer, 'Next.js');
      await adminServer.close();
    })();
  }
  return shutdownPromise;
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
  nextServer = spawnTracked(
    process.execPath,
    [
      nextBin,
      'dev',
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

  const testArgs = process.argv.slice(2);
  if (testArgs[0] === '--') testArgs.shift();
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
