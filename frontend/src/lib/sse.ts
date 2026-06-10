import { API_BASE } from '$lib/api';

export type JobEvent = { job_id: string; status: string; output_id?: string; error?: string };

/** Subscribe to job events; falls back to polling via onFallback after repeated failures. */
export function subscribeJobs(onEvent: (e: JobEvent) => void, onFallback?: () => void): () => void {
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
