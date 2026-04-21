/**
 * Toast primitive — the shared feedback-loop surface for Princeps.
 *
 * Tiny pub/sub API. The <Toast /> component in
 * `src/components/Toast.jsx` subscribes and renders the queue; callers
 * anywhere in the app call `toast.success('message')` / `toast.error(...)` /
 * `toast.info(...)` and never need to wire a prop.
 *
 * Contract:
 *   - auto-dismiss after `duration` ms (default 3000)
 *   - max 3 stacked concurrently — the oldest is dropped when a 4th arrives
 *   - levels: "success" | "error" | "info"
 */
const DEFAULT_DURATION = 3000;
const MAX_STACK = 3;

let _id = 0;
const _listeners = new Set();
let _queue = []; // [{ id, level, message, duration, ts }]

function _emit() {
  const snapshot = _queue.slice();
  for (const fn of _listeners) {
    try { fn(snapshot); } catch { /* swallow — never let a bad listener kill the bus */ }
  }
}

function _push(level, message, opts) {
  const duration = (opts && typeof opts.duration === "number") ? opts.duration : DEFAULT_DURATION;
  const id = ++_id;
  const entry = { id, level, message: String(message ?? ""), duration, ts: Date.now() };
  _queue = [..._queue, entry];
  // Cap stack — drop oldest.
  if (_queue.length > MAX_STACK) {
    _queue = _queue.slice(_queue.length - MAX_STACK);
  }
  _emit();
  if (duration > 0) {
    setTimeout(() => _dismiss(id), duration);
  }
  return id;
}

function _dismiss(id) {
  const before = _queue.length;
  _queue = _queue.filter((t) => t.id !== id);
  if (_queue.length !== before) _emit();
}

export function subscribe(listener) {
  _listeners.add(listener);
  // Replay current state so the subscriber doesn't miss the first tick.
  try { listener(_queue.slice()); } catch { /* noop */ }
  return () => _listeners.delete(listener);
}

export const toast = {
  success: (message, opts) => _push("success", message, opts),
  error:   (message, opts) => _push("error",   message, opts),
  info:    (message, opts) => _push("info",    message, opts),
  dismiss: (id) => _dismiss(id),
};

// Expose on window for console-driven smoke tests & for non-React callers
// (BOT-DM hooks this from useDatasetLayer).
if (typeof window !== "undefined") {
  // eslint-disable-next-line no-underscore-dangle
  window.__princepsToast = toast;
}

export default toast;
