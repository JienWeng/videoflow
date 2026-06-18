<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { get, post, mediaUrl } from '$lib/api';
  import { subscribeJobs } from '$lib/sse';
  import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { toast } from 'svelte-sonner';
  import { Wand2, LoaderCircle, CircleCheck, CircleX, Octagon, Sparkles } from '@lucide/svelte';

  type Run = {
    id: string;
    idea: string;
    status: string;
    stage: string | null;
    attempt: number;
    best_score: number | null;
    last_error: string | null;
    last_verdict_json: Record<string, any>;
  };
  type Step = { id: string; seq: number; action: string; rationale: string; result_summary: string };
  type Detail = { run: Run; steps: Step[]; output: any | null };

  let idea = $state('');
  let budget = $state(400);
  let aspect = $state('9:16');
  let language = $state('zh');
  let style = $state('');
  let starting = $state(false);

  const ASPECTS = [
    { v: '9:16', label: 'Portrait 9:16' },
    { v: '16:9', label: 'Landscape 16:9' },
    { v: '1:1', label: 'Square 1:1' }
  ];
  const LANGUAGES = [
    { v: 'zh', label: 'Chinese' },
    { v: 'en', label: 'English' }
  ];
  let runs = $state<Run[]>([]);
  let selected = $state<string | null>(null);
  let detail = $state<Detail | null>(null);

  const TERMINAL = new Set(['done', 'failed', 'cancelled']);
  const ACTION_LABELS: Record<string, string> = {
    generate_script: 'Wrote the script',
    expand_scene: 'Designed the scene',
    generate_shots: 'Planned the shots',
    generate_storyboard: 'Drew the storyboard',
    render_scene: 'Rendered the video',
    revise_render: 'Revised the render',
    regenerate_render: 'Regenerated the video',
    qa: 'Reviewed quality',
    caption: 'Added captions',
    finish: 'Finished',
    abort: 'Stopped'
  };

  async function refreshRuns() {
    try {
      runs = await get('/workflows');
      if (!selected && runs.length) select(runs[0].id);
    } catch (e: any) {
      /* surfaced elsewhere */
    }
  }

  async function loadDetail(id: string) {
    try {
      detail = await get(`/workflows/${id}`);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  function select(id: string) {
    selected = id;
    loadDetail(id);
  }

  async function start() {
    if (!idea.trim()) return;
    starting = true;
    try {
      const run: Run = await post('/workflows', {
        idea: idea.trim(),
        config: {
          budget,
          aspect_ratio: aspect,
          dialogue_language: language,
          style: style.trim() || undefined
        }
      });
      idea = '';
      await refreshRuns();
      select(run.id);
      toast.success('Autopilot started — sit back.');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      starting = false;
    }
  }

  async function cancel(id: string) {
    try {
      await post(`/workflows/${id}/cancel`);
      await refreshRuns();
      if (selected === id) loadDetail(id);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  let unsub: (() => void) | null = null;
  onMount(() => {
    refreshRuns();
    unsub = subscribeJobs((ev) => {
      if (!ev.workflow_id) return;
      refreshRuns();
      if (ev.workflow_id === selected) loadDetail(selected);
    });
  });
  onDestroy(() => unsub?.());

  function statusBadge(s: string) {
    if (s === 'done') return { variant: 'default', icon: CircleCheck, label: 'Done' };
    if (s === 'failed') return { variant: 'destructive', icon: CircleX, label: 'Failed' };
    if (s === 'cancelled') return { variant: 'outline', icon: Octagon, label: 'Cancelled' };
    if (s === 'awaiting_render')
      return { variant: 'secondary', icon: LoaderCircle, label: 'Rendering…' };
    return { variant: 'secondary', icon: LoaderCircle, label: 'Working…' };
  }
</script>

<div class="p-6 max-w-5xl">
  <div class="mb-4">
    <h1 class="flex items-center gap-2 text-lg font-semibold">
      <Wand2 class="size-5" />Autopilot
    </h1>
    <p class="text-sm text-muted-foreground">
      Give one idea. The AI director writes, designs, renders, reviews and captions a video on its
      own — stopping when it's good enough or the budget runs out.
    </p>
  </div>

  <Card class="mb-5">
    <CardContent class="p-4">
      <form
        class="flex flex-col gap-3"
        onsubmit={(e) => {
          e.preventDefault();
          start();
        }}
      >
        <textarea
          rows="3"
          class="w-full rounded-md border border-input bg-background p-3 text-sm"
          placeholder="e.g. 乐乐和天天在教室里学会分享一支彩色铅笔"
          bind:value={idea}
          disabled={starting}
        ></textarea>

        <div class="grid gap-3 sm:grid-cols-3">
          <label class="text-xs text-muted-foreground">
            Orientation
            <select
              class="mt-1 h-8 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground"
              bind:value={aspect}
              disabled={starting}
            >
              {#each ASPECTS as a (a.v)}<option value={a.v}>{a.label}</option>{/each}
            </select>
          </label>
          <label class="text-xs text-muted-foreground">
            Dialogue language
            <select
              class="mt-1 h-8 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground"
              bind:value={language}
              disabled={starting}
            >
              {#each LANGUAGES as l (l.v)}<option value={l.v}>{l.label}</option>{/each}
            </select>
          </label>
          <label class="text-xs text-muted-foreground">
            Style (optional)
            <input
              class="mt-1 h-8 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground"
              placeholder="soft 3D pastel cartoon"
              bind:value={style}
              disabled={starting}
            />
          </label>
        </div>
        <p class="text-[11px] text-muted-foreground">
          Base look comes from your project Style guide; the optional box adds a style for just this run.
        </p>

        <div class="flex flex-wrap items-center gap-3">
          <label class="flex items-center gap-2 text-sm text-muted-foreground">
            Budget
            <input
              type="number"
              min="50"
              step="50"
              class="h-8 w-24 rounded-md border border-input bg-background px-2 text-sm"
              bind:value={budget}
              disabled={starting}
            />
            <span class="text-[11px]">credits (~{Math.floor(budget / 150)} renders)</span>
          </label>
          <div class="flex-1"></div>
          <Button type="submit" disabled={starting || !idea.trim()}>
            {#if starting}
              <LoaderCircle class="size-4 mr-1 animate-spin" />Starting…
            {:else}
              <Sparkles class="size-4 mr-1" />Create video
            {/if}
          </Button>
        </div>
      </form>
    </CardContent>
  </Card>

  <div class="grid gap-5 md:grid-cols-[260px_1fr]">
    <!-- Run list -->
    <div class="space-y-2">
      <div class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Runs</div>
      {#if !runs.length}
        <p class="text-xs text-muted-foreground">No runs yet.</p>
      {/if}
      {#each runs as r (r.id)}
        {@const b = statusBadge(r.status)}
        <button
          type="button"
          class="w-full rounded-lg border p-3 text-left transition-colors {selected === r.id
            ? 'border-primary bg-accent'
            : 'border-border hover:bg-accent/50'}"
          onclick={() => select(r.id)}
        >
          <div class="line-clamp-2 text-sm">{r.idea || '(untitled)'}</div>
          <div class="mt-1 flex items-center gap-1.5">
            <Badge variant={b.variant as any} class="gap-1 text-[10px]">
              <b.icon class="size-3 {TERMINAL.has(r.status) ? '' : 'animate-spin'}" />{b.label}
            </Badge>
            {#if r.best_score != null}
              <span class="text-[10px] text-muted-foreground">score {r.best_score}/10</span>
            {/if}
          </div>
        </button>
      {/each}
    </div>

    <!-- Detail: director timeline + output -->
    <div>
      {#if !detail}
        <p class="text-sm text-muted-foreground">Select a run to watch the director work.</p>
      {:else}
        {@const r = detail.run}
        {@const b = statusBadge(r.status)}
        <div class="mb-3 flex items-center gap-2">
          <Badge variant={b.variant as any} class="gap-1">
            <b.icon class="size-3.5 {TERMINAL.has(r.status) ? '' : 'animate-spin'}" />{b.label}
          </Badge>
          {#if r.attempt}
            <span class="text-xs text-muted-foreground">{r.attempt} render attempt(s)</span>
          {/if}
          <div class="flex-1"></div>
          {#if !TERMINAL.has(r.status)}
            <Button size="sm" variant="ghost" onclick={() => cancel(r.id)}>Cancel</Button>
          {/if}
        </div>

        {#if r.last_error}
          <Card class="mb-3 border-destructive/40">
            <CardContent class="p-3 text-xs text-destructive">{r.last_error}</CardContent>
          </Card>
        {/if}

        {#if detail.output?.video_path}
          {@const src = mediaUrl(detail.output.captioned_path || detail.output.video_path)}
          <Card class="mb-4">
            <CardHeader class="pb-2">
              <CardTitle class="text-sm">Result</CardTitle>
              {#if detail.output.captioned_path}
                <CardDescription class="text-xs">Captioned</CardDescription>
              {/if}
            </CardHeader>
            <CardContent>
              {#if src}
                <!-- svelte-ignore a11y_media_has_caption -->
                <video src={src} controls class="w-full max-w-md rounded-md"></video>
              {/if}
            </CardContent>
          </Card>
        {/if}

        <div class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Director timeline
        </div>
        <ol class="mt-2 space-y-2">
          {#each detail.steps as s (s.id)}
            <li class="rounded-lg border border-border bg-card p-3">
              <div class="flex items-center gap-2">
                <span class="text-[11px] tabular-nums text-muted-foreground">{s.seq}</span>
                <span class="text-sm font-medium">{ACTION_LABELS[s.action] ?? s.action}</span>
              </div>
              {#if s.rationale}
                <p class="mt-0.5 text-[12px] text-muted-foreground">{s.rationale}</p>
              {/if}
              {#if s.result_summary}
                <p class="mt-0.5 text-[11px] text-muted-foreground/80">{s.result_summary}</p>
              {/if}
            </li>
          {/each}
          {#if !detail.steps.length}
            <li class="text-xs text-muted-foreground">Warming up…</li>
          {/if}
        </ol>
      {/if}
    </div>
  </div>
</div>
