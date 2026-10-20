import { api, HttpError } from './api';

const unavailable = () => new Error('Your workspace is taking longer to start. Please try again.');

function pause(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const aborted = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = window.setTimeout(() => { signal.removeEventListener('abort', aborted); resolve(); }, 2000);
    signal.addEventListener('abort', aborted, {once: true});
    if (signal.aborted) aborted();
  });
}

// Only the idempotent readiness GET is retried, never writes. This runs once on
// entry/retry, not as an interval or keep-alive while a tab sits open.
export async function waitForWorkspace(signal: AbortSignal) {
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  signal.addEventListener('abort', abort, {once: true});
  if (signal.aborted) abort();
  const deadline = window.setTimeout(() => controller.abort(unavailable()), 45_000);
  try {
    while (!controller.signal.aborted) {
      try { await api.me(controller.signal); return; }
      catch (cause) {
        if (controller.signal.aborted) throw controller.signal.reason;
        if (!(cause instanceof HttpError) || !(cause.status === 0 || cause.status === 429 || cause.status >= 500)) throw cause;
      }
      await pause(controller.signal);
    }
    throw controller.signal.reason;
  } finally {
    clearTimeout(deadline);
    signal.removeEventListener('abort', abort);
  }
}
