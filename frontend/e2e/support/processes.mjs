/**
 * Child processes and loopback ports, owned rather than merely started.
 *
 * Extracted from `scripts/run-e2e.mjs` when the browser-to-gateway harness
 * needed the same guarantees for uvicorn that the runner already had for Next:
 * a process tree that is terminated whole, a spawn failure that resolves like
 * an exit instead of hanging, and a port reserved before anything is told to
 * listen on it. Duplicating those would have meant two answers to "did the
 * child really stop", and the Windows teardown defect that produced the
 * original is exactly the kind that reappears in a copy.
 */

import { spawn } from 'node:child_process';
import { createServer as createPortProbe } from 'node:net';

export const isWindows = process.platform === 'win32';

const children = new WeakMap();

export function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function withTimeout(promise, milliseconds, message) {
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

export function spawnTracked(command, args, options, label) {
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

export function resultOf(child) {
  return children.get(child);
}

export async function availablePort(host, requestedPort = 0) {
  return new Promise((resolve, reject) => {
    const probe = createPortProbe();
    probe.once('error', reject);
    probe.listen({ host, port: requestedPort, exclusive: true }, () => {
      const address = probe.address();
      if (!address || typeof address === 'string') {
        probe.close();
        reject(new Error('Could not reserve a loopback port.'));
        return;
      }
      probe.close((error) => (error ? reject(error) : resolve(address.port)));
    });
  });
}

export async function stopProcessTree(child, label) {
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

/**
 * Poll an HTTP endpoint until it answers, failing fast if the child dies first.
 *
 * The exit race is the part worth keeping: without it a process that fails at
 * import time is reported as a timeout minutes later, naming the deadline
 * rather than the traceback that is already on the console.
 */
export async function waitForHttp(url, { child, label, timeoutMs = 60_000 }) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child) {
      const outcome = await Promise.race([resultOf(child), delay(0)]);
      if (outcome) {
        const detail = outcome.error?.message ?? outcome.signal ?? outcome.code;
        throw new Error(`${label} exited before it became ready (${detail}).`);
      }
    }
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2_000) });
      if (response.status < 500) return;
    } catch {
      // Not listening yet.
    }
    await delay(250);
  }
  throw new Error(`${label} did not become ready at ${url} within ${timeoutMs}ms.`);
}
