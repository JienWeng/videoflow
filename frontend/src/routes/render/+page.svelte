<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { subscribeJobs } from '$lib/sse';
  import VideoPreview from '$lib/components/VideoPreview.svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '$lib/components/ui/collapsible';
  import { toast } from 'svelte-sonner';
  import { Play, Captions, Clapperboard, RefreshCw, ChevronDown, History } from '@lucide/svelte';

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
    return subscribeJobs(
      () => refresh().catch(() => {}),
      () => refresh().catch(() => {})
    );
  });

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
  <div class="flex items-center gap-2 text-xs py-1">
    <Badge variant={statusVariant(j.status)} class={isActive(j.status) ? 'animate-pulse' : ''}>{j.status}</Badge>
    <span class="text-muted-foreground">{j.model?.split('/').slice(-2).join('/')}</span>
    <span class="text-muted-foreground">{relativeTime(j.created_at)}</span>
    {#if j.error}
      <span class="text-destructive max-w-[320px] truncate" title={j.error}>{j.error}</span>
    {/if}
  </div>
{/snippet}

<div class="p-6">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Render</h1>
    <p class="text-sm text-muted-foreground">Browse finished renders by scene — caption, edit or re-run the outputs.</p>
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
                  <div class="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
                    <Badge variant="secondary" class="animate-pulse">{j.status}</Badge>
                    <span class="text-muted-foreground">{j.model?.split('/').slice(-2).join('/')}</span>
                    <span class="text-muted-foreground ml-auto">{relativeTime(j.created_at)}</span>
                  </div>
                {/each}
              </div>
            {/if}

            {#if sceneOutputs(g).length}
              <div class="flex flex-wrap gap-4">
                {#each sceneOutputs(g) as { job, out } (out.id)}
                  <div class="flex-none">
                    <VideoPreview path={out.captioned_path || out.video_path} href={`/editor/${out.id}`} />
                    <div class="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                      QA: {out.score ?? '—'} {out.qa_json?.recommendation ?? ''}
                      {#if out.captioned_path}<Badge class="ml-1">captioned</Badge>{/if}
                    </div>
                    {#if out.qa_json?.issues?.length}
                      <ul class="text-xs text-muted-foreground mt-0.5 max-w-56 space-y-0.5">
                        {#each out.qa_json.issues.slice(0, 3) as issue (issue)}
                          <li class="truncate" title={issue}>- {issue}</li>
                        {/each}
                      </ul>
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
                    <div class="flex flex-wrap items-center gap-1 mt-1">
                      <Button size="sm" href={`/editor/${out.id}`} title="Open in editor">
                        <Clapperboard class="size-3 mr-1" />Open in editor
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
