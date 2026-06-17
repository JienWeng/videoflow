import { API_BASE } from '$lib/api';

/** Any event from /events: render-job events carry job_id, background-op events carry op_id. */
export type StreamEvent = {
  job_id?: string;
  op_id?: string;
  workflow_id?: string;
  action?: string;
  stage?: string;
  kind?: string;
  status?: string;
  scene_id?: string;
  output_id?: string;
  error?: string;
};
export type JobEvent = StreamEvent;

/** Subscribe to job/op events; falls back to polling via onFallback after repeated failures. */
export function subscribeJobs(onEvent: (e: StreamEvent) => void, onFallback?: () => void): () => void {
  let es: EventSource | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let retries = 0;
  let closed = false;

  // Trailing debounce so bursts only fire one refresh
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  function debounced(fn: () => void) {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(fn, 300);
  }

  function startPolling() {
    if (!pollTimer && onFallback) pollTimer = setInterval(() => debounced(onFallback!), 5000);
  }

  function connect() {
    if (closed) return;
    es = new EventSource(`${API_BASE}/events`);
    es.onmessage = (ev) => {
      retries = 0;
      const parsed: JobEvent = JSON.parse(ev.data);
      debounced(() => onEvent(parsed));
    };
    es.onerror = () => {
      es?.close();
      if (++retries > 3) startPolling();
      else setTimeout(connect, 1000 * retries);
    };
  }
  connect();
  return () => {
    closed = true;
    es?.close();
    if (pollTimer) clearInterval(pollTimer);
    if (debounceTimer) clearTimeout(debounceTimer);
  };
}
