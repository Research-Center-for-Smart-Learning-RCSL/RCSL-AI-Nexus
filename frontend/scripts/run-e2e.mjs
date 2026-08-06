/**
 * Start Next.js, run Playwright, and always terminate the whole server tree.
 *
 * Playwright's built-in webServer is the ordinary choice, but Next dev leaves
 * its worker alive during teardown on Windows. The tests finish and the runner
 * never exits. Owning the process here keeps the same one-command workflow and
 * gives Windows the process-tree termination it needs; POSIX receives signals
 * through a detached process group.
 */

import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3100';
const serverURL = new URL(baseURL);
const isWindows = process.platform === 'win32';

const nextBin = join(frontendDir, 'node_modules', 'next', 'dist', 'bin', 'next');
const playwrightBin = join(
  frontendDir,
  'node_modules',
  '@playwright',
  'test',
  'cli.js',
);

const server = spawn(
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
    env: process.env,
    stdio: 'inherit',
    detached: !isWindows,
  },
);

let stopped = false;

async function stopServer() {
  if (stopped || !server.pid || server.exitCode !== null) return;
  stopped = true;

  if (isWindows) {
    const killer = spawn('taskkill', ['/PID', String(server.pid), '/T', '/F'], {
      stdio: 'ignore',
      windowsHide: true,
    });
    await Promise.race([
      new Promise((resolve) => killer.once('exit', resolve)),
      new Promise((resolve) => setTimeout(resolve, 3_000)),
    ]);
    // `taskkill` can outlive the server it has already terminated. Neither its
    // handle nor the dead Next child should keep this coordinator open.
    killer.unref();
    server.unref();
    return;
  }

  try {
    process.kill(-server.pid, 'SIGTERM');
  } catch {
    return;
  }

  await Promise.race([
    new Promise((resolve) => server.once('exit', resolve)),
    new Promise((resolve) => setTimeout(resolve, 2_000)),
  ]);
  if (server.exitCode === null) {
    try {
      process.kill(-server.pid, 'SIGKILL');
    } catch {
      // The group exited between the check and the signal.
    }
  }
}

async function waitUntilReady() {
  const deadline = Date.now() + 120_000;
  const loginURL = new URL('/login', baseURL);

  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`Next.js exited before it became ready (${server.exitCode}).`);
    }
    try {
      const response = await fetch(loginURL, {
        signal: AbortSignal.timeout(2_000),
      });
      if (response.status < 500) return;
    } catch {
      // The socket is not listening yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Next.js did not become ready at ${loginURL} within 120 seconds.`);
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, async () => {
    await stopServer();
    process.exit(1);
  });
}

let exitCode = 1;
try {
  await waitUntilReady();
  const tests = spawn(process.execPath, [playwrightBin, 'test', ...process.argv.slice(2)], {
    cwd: frontendDir,
    env: { ...process.env, PLAYWRIGHT_BASE_URL: baseURL },
    stdio: 'inherit',
  });
  exitCode = await new Promise((resolve) => {
    tests.once('exit', (code) => resolve(code ?? 1));
  });
} finally {
  await stopServer();
}

process.exitCode = exitCode;
