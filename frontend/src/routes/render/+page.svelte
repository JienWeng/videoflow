<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, patch, API_BASE } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { subscribeJobs } from '$lib/sse';
  import VideoPreview from '$lib/components/VideoPreview.svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '$lib/components/ui/collapsible';
  import { toast } from 'svelte-sonner';
  import {
    Play,
    Captions,
    Clapperboard,
    RefreshCw,
    ChevronDown,
    History,
    Download,
    Star,
    ShieldCheck,
    AlertTriangle,
    Loader2
  } from '@lucide/svelte';

  let jobs: any[] = $state([]);
  let scenes: any[] = $state([]);
  let shots: any[] = $state([]);
  let outputs: Record<string, any[]> = $state({});
  let error = $state('');
  let busy = $state(false);
  let loaded = $state(false);

  let sceneId = $state('');
  let shotId = $state('');

  // Caption defaults from /caption-config — fine-tuning lives in /editor/{id}.
  let captionStyles: string[] = $state([]);
  let captionDefaultModel = $state('');
  let captionDefaultLanguage = $state('zh');
  let captionDefaultStyle = $state('');
  // Captioning runs as a background op — per-output so several can run at once.
  let captioning: Record<string, boolean> = $state({});
  let retrying = $state('');
  // Per-output QA / keeper action state.
  let qaRunning: Record<string, boolean> = $state({});
  let selecting: Record<string, boolean> = $state({});

  // Ticks once a second so the elapsed timer on active renders stays live.
  let now = $state(Date.now());

  // --- Download links (raw vs captioned) ---
  function downloadUrl(outId: string, variant: 'raw' | 'captioned'): string {
    return `${API_BASE}/outputs/${outId}/download?variant=${variant}`;
  }

  // --- QA state model (badge + tooltip) ---
  // Prefer an explicit backend qa_status when present; otherwise derive from the
  // stored score / qa_json so older outputs still show a sensible badge.
  type QaState = 'pending' | 'running' | 'scored' | 'failed' | 'skipped';
  function qaState(out: any): QaState {
    if (qaRunning[out.id]) return 'running';
    const s = out.qa_status as string | undefined;
    if (s === 'running' || s === 'pending' || s === 'failed' || s === 'skipped' || s === 'scored')
      return s;
    if (out.score != null || out.qa_json?.recommendation) return 'scored';
    return 'pending';
  }
  function qaBadgeVariant(state: QaState): 'default' | 'destructive' | 'secondary' | 'outline' {
    if (state === 'scored') return 'default';
    if (state === 'failed') return 'destructive';
    if (state === 'running') return 'secondary';
    return 'outline';
  }
  function qaLabel(out: any, state: QaState): string {
    if (state === 'scored') return `QA ${out.score ?? '—'}/10`;
    if (state === 'running') return 'QA running';
    if (state === 'failed') return 'QA failed';
    if (state === 'skipped') return 'QA skipped';
    return 'QA pending';
  }
  function qaTooltip(out: any, state: QaState): string {
    if (state === 'scored') {
      const rec = out.qa_json?.recommendation;
      const issues = out.qa_json?.issues?.length ?? 0;
      return `Scored ${out.score ?? '—'}/10${rec ? ` · ${rec}` : ''}${issues ? ` · ${issues} issue(s)` : ''}`;
    }
    if (state === 'running') return 'Quality check in progress…';
    if (state === 'failed') return 'The quality check could not complete — run it again.';
    if (state === 'skipped') return 'Quality check was skipped for this take.';
    return 'Not checked yet — run a quality check to score it and unlock Fix & re-render.';
  }
  // Fix & re-render is only meaningful once QA has produced issues.
  function canFixRerender(out: any): boolean {
    return qaState(out) === 'scored' && (out.qa_json?.issues?.length ?? 0) > 0;
  }

  // --- Friendly error mapping (raw provider error -> short human line) ---
  function friendlyError(raw: string | null | undefined): string {
    const text = (raw ?? '').trim();
    if (!text) return 'Something went wrong (no detail provided).';
    const t = text.toLowerCase();
    if (t.includes('timeout') || t.includes('timed out'))
      return 'The provider took too long to respond — try again.';
    if (t.includes('rate limit') || t.includes('429') || t.includes('too many requests'))
      return 'Rate limited by the provider — wait a moment and retry.';
    if (t.includes('insufficient') && (t.includes('balance') || t.includes('credit') || t.includes('quota')))
      return 'The provider account is out of credit/quota.';
    if (t.includes('401') || t.includes('unauthorized') || t.includes('api key') || t.includes('forbidden') || t.includes('403'))
      return 'Provider rejected the API key — check Settings.';
    if (t.includes('content') && (t.includes('policy') || t.includes('moderation') || t.includes('blocked') || t.includes('safety')))
      return 'The prompt was blocked by the provider content filter.';
    if (t.includes('download failed'))
      return 'The finished video could not be downloaded — try again.';
    if (t.includes('ffmpeg') || t.includes('no frames'))
      return 'Could not process the video file (ffmpeg).';
    if (t.includes('connection') || t.includes('network') || t.includes('econn') || t.includes('failed to fetch'))
      return 'Network error reaching the provider — check the connection.';
    if (t.includes('500') || t.includes('internal server error') || t.includes('bad gateway') || t.includes('502') || t.includes('503'))
      return 'The provider had a server error — try again shortly.';
    return text.length > 160 ? text.slice(0, 157) + '…' : text;
  }

  function elapsed(iso: string | null): string {
    if (!iso) return '';
    const t = new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime();
    if (Number.isNaN(t)) return '';
    const s = Math.max(0, Math.round((now - t) / 1000));
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  }

  async function refreshJobOutputs(jobId: string) {
    const detail = await get(`/render-jobs/${jobId}`);
    outputs[jobId] = detail.outputs;
    outputs = outputs;
  }


  async function refresh() {
    [jobs, scenes] = await Promise.all([get('/render-jobs'), get('/scenes')]);
    const done = jobs.filter((j) => j.status === 'succeeded');
    for (const j of done) {
      if (!outputs[j.id]) {
        const detail = await get(`/render-jobs/${j.id}`);
        outputs[j.id] = detail.outputs;
      }
    }
    outputs = outputs;
  }

  onMount(() => {
    refresh()
      .catch((e) => (error = e.message))
      .finally(() => (loaded = true));
    get('/caption-config')
      .then((cfg: any) => {
        captionStyles = cfg.styles ?? [];
        captionDefaultModel = cfg.default_model ?? '';
        captionDefaultLanguage = cfg.default_language ?? 'zh';
        captionDefaultStyle = cfg.default_style ?? '';
      })
      .catch(() => {
        // Fallback to legacy endpoint
        get('/caption-styles').then((s) => (captionStyles = s)).catch(() => {});
      });
    const ticker = setInterval(() => (now = Date.now()), 1000);
    const unsubscribe = subscribeJobs(
      () => refresh().catch(() => {}),
      () => refresh().catch(() => {})
    );
    return () => {
      clearInterval(ticker);
      unsubscribe();
    };
  });

  async function runQualityCheck(jobId: string, out: any) {
    qaRunning[out.id] = true;
    try {
      await runBackgroundOp(
        `/outputs/${out.id}/run-qa`,
        undefined,
        {
          label: 'Quality check',
          onDone: async () => {
            qaRunning[out.id] = false;
            await refreshJobOutputs(jobId);
          },
          onFail: () => (qaRunning[out.id] = false)
        }
      );
    } catch (e: any) {
      qaRunning[out.id] = false;
      toast.error(e.message);
    }
  }

  async function toggleSelect(jobId: string, out: any) {
    selecting[out.id] = true;
    const next = !out.selected;
    try {
      await patch(`/outputs/${out.id}/select`, { selected: next });
      out.selected = next;
      outputs = outputs;
      toast.success(next ? 'Marked as the take to keep' : 'Unmarked');
      // Re-fetch every loaded job's outputs — the backend may make "keeper"
      // exclusive within a scene, deselecting siblings.
      await Promise.all(Object.keys(outputs).map((id) => refreshJobOutputs(id)));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      selecting[out.id] = false;
    }
  }

  async function addCaptions(jobId: string, out: any) {
    captioning[out.id] = true;
    error = '';
    const lang = captionDefaultLanguage || 'zh';
    try {
      await runBackgroundOp(
        `/outputs/${out.id}/caption`,
        {
          style: captionDefaultStyle || captionStyles[0] || 'kids',
          model: captionDefaultModel || undefined,
          language: lang === 'auto' ? null : lang
        },
        {
          label: 'Captioning',
          onDone: async () => {
            captioning[out.id] = false;
            // Refetch the job detail so the output row picks up captioned_path.
            await refreshJobOutputs(jobId);
          },
          onFail: () => (captioning[out.id] = false)
        }
      );
    } catch (e: any) {
      captioning[out.id] = false;
      toast.error(e.message);
    }
  }

  async function fixAndRerender(out: any) {
    retrying = out.id;
    try {
      const res = await post(`/outputs/${out.id}/retry`);
      toast.success(`Corrective re-render started — job ${res.job_id}`);
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      retrying = '';
    }
  }

  // Re-run a FAILED render. Uses the originating shot/scene endpoints (a failed
  // job produced no output, so there is nothing to /retry).
  let rerunning = $state('');
  async function reRenderJob(j: any) {
    rerunning = j.id;
    try {
      if (j.shot_id) {
        await post('/render/from-shot', { scene_id: j.scene_id, shot_id: j.shot_id });
      } else if (j.scene_id) {
        await post(`/scenes/${j.scene_id}/render`);
      } else {
        toast.error('This render has no scene to re-run.');
        return;
      }
      toast.success('Re-render started');
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      rerunning = '';
    }
  }

  async function loadShots() {
    shots = sceneId ? await get(`/scenes/${sceneId}/shots`) : [];
    shotId = '';
  }

  async function renderFromShot(e: Event) {
    e.preventDefault();
    busy = true;
    error = '';
    try {
      await post('/render/from-shot', { scene_id: sceneId, shot_id: shotId });
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = false;
    }
  }

  function statusVariant(status: string): 'default' | 'destructive' | 'secondary' | 'outline' {
    if (status === 'succeeded') return 'default';
    if (status === 'failed') return 'destructive';
    return 'secondary';
  }

  function isActive(status: string) {
    return status !== 'succeeded' && status !== 'failed';
  }

  function relativeTime(iso: string | null): string {
    if (!iso) return '';
    const t = new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime();
    if (Number.isNaN(t)) return '';
    const s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60) return `${s}s ago`;
    const m = Math.round(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.round(h / 24)}d ago`;
  }

  // Group jobs by scene — humans browse renders per scene, not per job id.
  type SceneGroup = {
    sceneId: string;
    title: string;
    jobs: any[]; // newest first
    active: any[];
    succeeded: number;
    failed: number;
    latest: string; // newest created_at, for ordering cards
  };

  let groups: SceneGroup[] = $derived.by(() => {
    const titles = new Map(scenes.map((s: any) => [s.id, s.title]));
    const bySceneId = new Map<string, any[]>();
    for (const j of jobs) {
      const key = j.scene_id && titles.has(j.scene_id) ? j.scene_id : '__other__';
      if (!bySceneId.has(key)) bySceneId.set(key, []);
      bySceneId.get(key)!.push(j);
    }
    const out: SceneGroup[] = [];
    for (const [key, list] of bySceneId) {
      list.sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
      out.push({
        sceneId: key,
        title: key === '__other__' ? 'Other renders' : (titles.get(key) ?? key),
        jobs: list,
        active: list.filter((j) => isActive(j.status)),
        succeeded: list.filter((j) => j.status === 'succeeded').length,
        failed: list.filter((j) => j.status === 'failed').length,
        latest: list[0]?.created_at ?? ''
      });
    }
    // Newest activity first; the fallback bucket sorts by its own newest job too.
    out.sort((a, b) => b.latest.localeCompare(a.latest));
    return out;
  });

  function sceneOutputs(g: SceneGroup): { job: any; out: any }[] {
    const res: { job: any; out: any }[] = [];
    for (const j of g.jobs) {
      if (j.status !== 'succeeded') continue;
      for (const out of outputs[j.id] ?? []) res.push({ job: j, out });
    }
    return res;
  }
</script>

{#snippet jobRow(j: any)}
  <div class="py-1 text-xs">
    <div class="flex flex-wrap items-center gap-2">
      <Badge variant={statusVariant(j.status)} class={isActive(j.status) ? 'animate-pulse' : ''}>{j.status}</Badge>
      <span class="text-muted-foreground">{j.model?.split('/').slice(-2).join('/')}</span>
      <span class="text-muted-foreground">{relativeTime(j.created_at)}</span>
      {#if j.status === 'failed'}
        <Button
          variant="outline"
          size="sm"
          class="ml-auto"
          disabled={!!rerunning}
          onclick={() => reRenderJob(j)}
        >
          <RefreshCw class="size-3 mr-1 {rerunning === j.id ? 'animate-spin' : ''}" />
          {rerunning === j.id ? 'submitting…' : 'Re-render'}
        </Button>
      {/if}
    </div>
    {#if j.status === 'failed'}
      <!-- Friendly mapped error + raw-detail expander -->
      <Collapsible class="mt-0.5">
        <div class="flex items-start gap-1.5">
          <span class="text-destructive" title={j.error || ''}>{friendlyError(j.error)}</span>
          {#if j.error}
            <CollapsibleTrigger
              class="shrink-0 inline-flex items-center gap-0.5 text-muted-foreground hover:text-foreground [&[data-state=open]>svg]:rotate-180"
            >
              details<ChevronDown class="size-3 transition-transform" />
            </CollapsibleTrigger>
          {/if}
        </div>
        {#if j.error}
          <CollapsibleContent>
            <pre class="mt-1 whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 p-2 text-[10px] text-muted-foreground">{j.error}</pre>
          </CollapsibleContent>
        {/if}
      </Collapsible>
    {/if}
  </div>
{/snippet}

<div class="p-6">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Render</h1>
    <p class="text-sm text-muted-foreground">Browse finished renders by scene — run a quality check, caption, download, pick a keeper, or re-run.</p>
  </div>

  <Collapsible class="mb-4 rounded-lg border border-border bg-card">
    <CollapsibleTrigger
      class="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-muted-foreground hover:text-foreground [&[data-state=open]>svg]:rotate-180"
    >
      <Play class="size-4" />
      Advanced: render a single shot
      <ChevronDown class="size-4 ml-auto transition-transform" />
    </CollapsibleTrigger>
    <CollapsibleContent>
      <form class="px-4 pb-4" onsubmit={renderFromShot}>
        <div class="flex flex-wrap gap-4 items-end">
          <div class="flex-1 min-w-[160px]">
            <label class="block text-xs text-muted-foreground mb-1" for="scene">Scene</label>
            <select id="scene" bind:value={sceneId} onchange={loadShots}
              class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
              <option value="">choose…</option>
              {#each scenes as s}<option value={s.id}>{s.title}</option>{/each}
            </select>
          </div>
          <div class="flex-1 min-w-[160px]">
            <label class="block text-xs text-muted-foreground mb-1" for="shot">Shot (prompt-agent render)</label>
            <select id="shot" bind:value={shotId} disabled={!shots.length}
              class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
              <option value="">choose…</option>
              {#each shots as sh}<option value={sh.id}>#{sh.shot_order + 1} {sh.prompt.slice(0, 50)}</option>{/each}
            </select>
          </div>
          <div>
            <Button type="submit" disabled={busy || !shotId} size="sm">
              <Play class="size-4 mr-1" />Render shot
            </Button>
          </div>
        </div>
        <div class="text-xs text-muted-foreground mt-2">Whole-scene multi-shot renders live on the Scenes page (step 4).</div>
      </form>
    </CollapsibleContent>
  </Collapsible>

  {#if !loaded}
    <div class="space-y-4">
      {#each Array(2) as _, i (i)}
        <Card>
          <CardHeader>
            <Skeleton class="h-5 w-48" />
          </CardHeader>
          <CardContent>
            <Skeleton class="h-44 w-[320px] rounded-lg" />
          </CardContent>
        </Card>
      {/each}
    </div>
  {:else if !jobs.length}
    <div class="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
      Nothing rendered yet — render a scene from the Scenes page or ask the chat. — 还没有渲染。
    </div>
  {:else}
    <div class="space-y-4">
      {#each groups as g (g.sceneId)}
        <Card data-scene-card={g.sceneId}>
          <CardHeader>
            <div class="flex flex-wrap items-center gap-2">
              <CardTitle class="text-base font-bold">{g.title}</CardTitle>
              <div class="flex items-center gap-1.5 ml-auto">
                {#if g.active.length}
                  <Badge variant="secondary" class="animate-pulse">{g.active.length} in progress</Badge>
                {/if}
                {#if g.succeeded}
                  <Badge variant="default">{g.succeeded} succeeded</Badge>
                {/if}
                {#if g.failed}
                  <Badge variant="destructive">{g.failed} failed</Badge>
                {/if}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {#if g.active.length}
              <div class="mb-4 space-y-1.5">
                {#each g.active as j (j.id)}
                  <div class="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
                    <Loader2 class="size-3.5 animate-spin text-muted-foreground" />
                    <Badge variant="secondary">{j.stage || j.status}</Badge>
                    {#if j.progress}
                      <span class="text-foreground">{j.progress}</span>
                    {/if}
                    <span class="text-muted-foreground">{j.model?.split('/').slice(-2).join('/')}</span>
                    <span class="ml-auto font-mono tabular-nums text-muted-foreground" title="Elapsed">
                      {elapsed(j.created_at)}
                    </span>
                  </div>
                {/each}
              </div>
            {/if}

            {#if sceneOutputs(g).length}
              <div class="flex flex-wrap gap-4">
                {#each sceneOutputs(g) as { job, out } (out.id)}
                  {@const qa = qaState(out)}
                  <div class="flex-none w-[320px] {out.selected ? 'rounded-lg ring-2 ring-primary ring-offset-2 ring-offset-background' : ''}">
                    <div class="relative">
                      <VideoPreview
                        path={out.captioned_path || out.video_path}
                        poster={out.thumbnail_path}
                        href={`/editor/${out.id}`}
                      />
                      {#if out.selected}
                        <Badge class="absolute left-2 top-2 gap-1">
                          <Star class="size-3 fill-current" />keeper
                        </Badge>
                      {/if}
                    </div>

                    <!-- Status row: QA badge (+tooltip) and captioned marker -->
                    <div class="text-xs mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge
                        variant={qaBadgeVariant(qa)}
                        class={qa === 'running' ? 'animate-pulse' : ''}
                        title={qaTooltip(out, qa)}
                      >
                        {#if qa === 'scored'}<ShieldCheck class="size-3 mr-0.5" />
                        {:else if qa === 'failed'}<AlertTriangle class="size-3 mr-0.5" />{/if}
                        {qaLabel(out, qa)}
                      </Badge>
                      {#if qa === 'scored' && out.qa_json?.recommendation}
                        <span class="text-muted-foreground">{out.qa_json.recommendation}</span>
                      {/if}
                      {#if out.captioned_path}<Badge variant="secondary">captioned</Badge>{/if}
                    </div>

                    <!-- Run quality check when unscored -->
                    {#if qa === 'pending' || qa === 'failed' || qa === 'skipped'}
                      <div class="mt-1">
                        <Button
                          variant="outline"
                          size="sm"
                          title="Score this take against the scene requirements — unlocks Fix & re-render"
                          disabled={qaRunning[out.id]}
                          onclick={() => runQualityCheck(job.id, out)}
                        >
                          <ShieldCheck class="size-3 mr-1" />
                          {qaRunning[out.id] ? 'checking…' : 'Run quality check'}
                        </Button>
                      </div>
                    {/if}

                    <!-- QA issues + Fix & re-render (only once scored with issues) -->
                    {#if out.qa_json?.issues?.length}
                      <ul class="text-xs text-muted-foreground mt-0.5 max-w-56 space-y-0.5">
                        {#each out.qa_json.issues.slice(0, 3) as issue (issue)}
                          <li class="truncate" title={issue}>- {issue}</li>
                        {/each}
                      </ul>
                    {/if}
                    {#if canFixRerender(out)}
                      <div class="mt-1">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!!retrying}
                          onclick={() => fixAndRerender(out)}
                        >
                          <RefreshCw class="size-3 mr-1 {retrying === out.id ? 'animate-spin' : ''}" />
                          {retrying === out.id ? 'submitting…' : 'Fix & re-render'}
                        </Button>
                      </div>
                    {/if}

                    <!-- Primary actions -->
                    <div class="flex flex-wrap items-center gap-1 mt-2">
                      <Button size="sm" href={`/editor/${out.id}`} title="Open in editor">
                        <Clapperboard class="size-3 mr-1" />Open in editor
                      </Button>
                      <Button
                        variant={out.selected ? 'default' : 'outline'}
                        size="sm"
                        title={out.selected ? 'This is the take to keep — click to unmark' : 'Mark this as the take to keep'}
                        disabled={selecting[out.id]}
                        onclick={() => toggleSelect(job.id, out)}
                      >
                        <Star class="size-3 mr-1 {out.selected ? 'fill-current' : ''}" />
                        {out.selected ? 'Keeper' : 'Use this take'}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        title="Burn captions with the project defaults — fine-tune in the editor"
                        disabled={captioning[out.id]}
                        onclick={() => addCaptions(job.id, out)}
                      >
                        <Captions class="size-3 mr-1" />
                        {captioning[out.id] ? 'transcribing…' : out.captioned_path ? 'Re-caption' : 'Auto captions'}
                      </Button>
                    </div>

                    <!-- Download controls (raw vs captioned). Defaults visually to
                         the captioned copy when available; the keeper take is the
                         one the backend serves by default. -->
                    <div class="flex flex-wrap items-center gap-1 mt-1">
                      {#if out.captioned_path}
                        <Button
                          variant="secondary"
                          size="sm"
                          href={downloadUrl(out.id, 'captioned')}
                          download
                          title="Download the captioned video"
                        >
                          <Download class="size-3 mr-1" />Captioned
                        </Button>
                      {/if}
                      <Button
                        variant={out.captioned_path ? 'ghost' : 'secondary'}
                        size="sm"
                        href={downloadUrl(out.id, 'raw')}
                        download
                        title="Download the original (uncaptioned) video"
                      >
                        <Download class="size-3 mr-1" />Raw
                      </Button>
                    </div>
                  </div>
                {/each}
              </div>
            {:else if !g.active.length}
              <div class="text-xs text-muted-foreground">No finished outputs for this scene yet.</div>
            {/if}

            <!-- Compact jobs strip — collapsed behind "history (N)" when there are more than 2 jobs. -->
            <div class="mt-3 border-t border-border pt-2">
              {#if g.jobs.length > 2}
                <Collapsible>
                  <CollapsibleTrigger
                    class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground [&[data-state=open]>svg.chev]:rotate-180"
                  >
                    <History class="size-3" />
                    history ({g.jobs.length})
                    <ChevronDown class="chev size-3 transition-transform" />
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div class="mt-1 divide-y divide-border/60">
                      {#each g.jobs as j (j.id)}
                        {@render jobRow(j)}
                      {/each}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              {:else}
                <div class="divide-y divide-border/60">
                  {#each g.jobs as j (j.id)}
                    {@render jobRow(j)}
                  {/each}
                </div>
              {/if}
            </div>
          </CardContent>
        </Card>
      {/each}
    </div>
  {/if}
</div>
