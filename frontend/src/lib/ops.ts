import { get, post } from '$lib/api';
import { subscribeJobs } from '$lib/sse';
import { toast } from 'svelte-sonner';

export type Op = {
  id: string;
  kind: string;
  status: 'running' | 'succeeded' | 'failed';
  scene_id?: string | null;
  output_id?: string | null;
  error?: string | null;
  result_json?: Record<string, any> | null;
};

type OpHandlers = {
  onDone?: (op: Op) => unknown;
  onFail?: (op: Op) => unknown;
  label: string;
};

/**
 * POST `path` with ?background=true (202 -> {op_id}), then resolve completion
 * via the SSE stream (filtered on op_id) plus a 5s polling fallback on
 * GET /ops/{op_id}. Toasts start/success/failure; cleans up when terminal.
 * Throws only if the initial POST fails.
 */
export async function runBackgroundOp(
  path: string,
  body: unknown,
  { onDone, onFail, label }: OpHandlers
): Promise<void> {
  const sep = path.includes('?') ? '&' : '?';
  const started = await post(`${path}${sep}background=true`, body);
  const opId: string = started.op_id;
  toast.info(`${label} started`);

  let settled = false;
  let unsubscribe: (() => void) | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  function settle(op: Op) {
    if (settled) return;
    settled = true;
    unsubscribe?.();
    if (pollTimer) clearInterval(pollTimer);
    if (op.status === 'succeeded') {
      toast.success(`${label} done`);
      void onDone?.(op);
    } else {
      toast.error(op.error || `${label} failed`);
      void onFail?.(op);
    }
  }

  async function check() {
    if (settled) return;
    try {
      const op: Op = await get(`/ops/${opId}`);
      if (op.status !== 'running') settle(op);
    } catch {
      /* transient — the poll/SSE will retry */
    }
  }

  unsubscribe = subscribeJobs((e) => {
    if (e.op_id === opId && e.status !== 'running') void check();
  });
  pollTimer = setInterval(() => void check(), 5000);
}
