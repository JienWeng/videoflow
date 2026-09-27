<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, API_BASE } from '$lib/api';
  import { subscribeJobs } from '$lib/sse';
  import VideoPreview from '$lib/components/VideoPreview.svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '$lib/components/ui/collapsible';
  import { PaneGroup, Pane, Handle } from '$lib/components/ui/resizable';
  import { toast } from 'svelte-sonner';
  import {
    Play,
    Clapperboard,
    RefreshCw,
    ChevronDown,
    History,
    Download,
    Star,
    Loader2,
    ListVideo
  } from '@lucide/svelte';

  let jobs: any[] = $state([]);
  let scenes: any[] = $state([]);
  let scripts: any[] = $state([]);
  let shots: any[] = $state([]);
  let outputs: Record<string, any[]> = $state({});
  let error = $state('');
  let busy = $state(false);
  let loaded = $state(false);

  // Advanced single-shot render form state.
  let sceneId = $state('');
  let shotId = $state('');
  let showAdvanced = $state(false);

  // Re-run state for a FAILED render (keyed by job id).
  let rerunning = $state('');

  // Master–detail selection: which scene's render activity is shown on the right.
  let selectedId: string | null = $state(null);
  let groupSort = $state<'latest' | 'story'>('latest');

  // Ticks once a second so elapsed timers on active renders stay live.
  let now = $state(Date.now());

  // --- Download links (raw vs captioned) ---
  function downloadUrl(outId: string, variant: 'raw' | 'captioned'): string {
    return `${API_BASE}/outputs/${outId}/download?variant=${variant}`;
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

  function statusVariant(status: string): 'default' | 'destructive' | 'secondary' | 'outline' {
    if (status === 'succeeded') return 'default';
    if (status === 'failed') return 'destructive';
    return 'secondary';
  }

  function isActive(status: string) {
    return status !== 'succeeded' && status !== 'failed';
  }

  async function refresh() {
    [jobs, scenes, scripts] = await Promise.all([
      get('/render-jobs'), get('/scenes'), get('/scripts')
    ]);
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

  // Re-run a FAILED render. Uses the originating shot/scene endpoints (a failed
  // job produced no output, so there is nothing to /retry).
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

  // Group jobs by scene — humans browse renders per scene, not per job id. Only
  // scenes WITH render activity appear in the master list.
  type SceneGroup = {
    sceneId: string;
    title: string;
    jobs: any[]; // newest first
    active: any[];
    succeeded: number;
    failed: number;
    latest: string; // newest created_at, for ordering
    storyTime: number;
    storyOrder: number;
  };

  let groups: SceneGroup[] = $derived.by(() => {
    const titles = new Map(scenes.map((s: any) => [s.id, s.title]));
    const storyPositions = new Map<string, { time: number; order: number }>();
    const sortedScripts = scripts.slice().sort((a, b) =>
      (a.created_at ?? '').localeCompare(b.created_at ?? '')
    );
    for (let scriptIndex = 0; scriptIndex < sortedScripts.length; scriptIndex += 1) {
      const script = sortedScripts[scriptIndex];
      const scriptScenes = scenes
        .filter((scene: any) => scene.script_id === script.id)
        .sort((a: any, b: any) => (a.scene_order ?? Number.MAX_SAFE_INTEGER) - (b.scene_order ?? Number.MAX_SAFE_INTEGER) ||
          (a.created_at ?? '').localeCompare(b.created_at ?? ''));
      for (const [sceneIndex, scene] of scriptScenes.entries()) {
        storyPositions.set(scene.id, {
          time: new Date(script.created_at ?? scene.created_at ?? 0).getTime(),
          order: scriptIndex * 10000 + (scene.scene_order ?? sceneIndex)
        });
      }
    }
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
        latest: list[0]?.created_at ?? '',
        storyTime: storyPositions.get(key)?.time ?? new Date(scenes.find((s: any) => s.id === key)?.created_at ?? 0).getTime(),
        storyOrder: storyPositions.get(key)?.order ?? 0
      });
    }
    if (groupSort === 'latest') {
      out.sort((a, b) => b.latest.localeCompare(a.latest));
    } else {
      out.sort((a, b) =>
        (a.sceneId === '__other__' ? Number.MAX_SAFE_INTEGER : a.storyTime) -
          (b.sceneId === '__other__' ? Number.MAX_SAFE_INTEGER : b.storyTime) ||
        a.storyOrder - b.storyOrder || a.title.localeCompare(b.title)
      );
    }
    return out;
  });

  const selectedGroup = $derived(groups.find((g) => g.sceneId === selectedId) ?? null);

  // Keep selection valid as activity changes: default to first group, fall back
  // when the selected scene's activity disappears.
  $effect(() => {
    if (!loaded) return;
    if (selectedId !== null && groups.some((g) => g.sceneId === selectedId)) return;
    selectedId = groups.length ? groups[0].sceneId : null;
  });

  function sceneOutputs(g: SceneGroup): { job: any; out: any }[] {
    const res: { job: any; out: any }[] = [];
    for (const j of g.jobs) {
      if (j.status !== 'succeeded') continue;
      for (const out of outputs[j.id] ?? []) res.push({ job: j, out });
    }
    return res;
  }

  // Compact one-line status for a list row — "2 rendered · 1 failed", etc.
  function groupStatusLine(g: SceneGroup): string {
    if (g.active.length) {
      return g.active.length === 1 ? 'rendering…' : `${g.active.length} rendering…`;
    }
    const parts: string[] = [];
    if (g.succeeded) parts.push(`${g.succeeded} rendered`);
    if (g.failed) parts.push(`${g.failed} failed`);
    return parts.length ? parts.join(' · ') : 'no finished renders';
  }

  // Status-dot colour: amber while anything runs, red if any failed and nothing
  // succeeded, emerald when there is at least one finished output, else muted.
  function groupDot(g: SceneGroup): string {
    if (g.active.length) return 'bg-amber-500/80';
    if (g.succeeded) return 'bg-emerald-500/80';
    if (g.failed) return 'bg-red-500/80';
    return 'bg-border';
  }

  function selectGroup(id: string) {
    selectedId = id;
  }

  // Arrow-key navigation in the left list (when not typing in a field).
  function listKeydown(e: KeyboardEvent) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (!groups.length) return;
    const i = groups.findIndex((g) => g.sceneId === selectedId);
    const next = e.key === 'ArrowDown' ? Math.min(groups.length - 1, i + 1) : Math.max(0, i - 1);
    if (next !== i || i === -1) {
      e.preventDefault();
      selectGroup(groups[next === -1 ? 0 : next].sceneId);
    }
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

<div class="flex h-full flex-col">
  <!-- Page header -->
  <div class="px-6 pt-6 pb-3 shrink-0">
    <h1 class="text-lg font-semibold">Render</h1>
    <p class="text-sm text-muted-foreground">Browse finished renders by scene, then open a take in the editor to caption, fine-tune and export.</p>
  </div>

  <PaneGroup direction="horizontal" class="flex-1 min-h-0 border-t border-border">
    <!-- LEFT: scenes with render activity (the monitor) -->
    <Pane defaultSize={28} minSize={20} class="min-w-0">
      <div class="flex h-full flex-col">
        <!-- Advanced single-shot render affordance -->
        <div class="shrink-0 border-b border-border p-3">
          <Collapsible bind:open={showAdvanced} class="rounded-lg border border-border bg-card">
            <CollapsibleTrigger
              class="flex w-full items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground [&[data-state=open]>svg]:rotate-180"
            >
              <Play class="size-4" />
              Render a single shot
              <ChevronDown class="size-4 ml-auto transition-transform" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <form class="px-3 pb-3 space-y-2.5" onsubmit={renderFromShot}>
                <div>
                  <label class="block text-xs text-muted-foreground mb-1" for="scene">Scene</label>
                  <select id="scene" bind:value={sceneId} onchange={loadShots}
                    class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
                    <option value="">choose…</option>
                    {#each scenes as s}<option value={s.id}>{s.title}</option>{/each}
                  </select>
                </div>
                <div>
                  <label class="block text-xs text-muted-foreground mb-1" for="shot">Shot (prompt-agent render)</label>
                  <select id="shot" bind:value={shotId} disabled={!shots.length}
                    class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
                    <option value="">choose…</option>
                    {#each shots as sh}<option value={sh.id}>#{sh.shot_order + 1} {sh.prompt.slice(0, 40)}</option>{/each}
                  </select>
                </div>
                <Button type="submit" disabled={busy || !shotId} size="sm" class="w-full">
                  <Play class="size-4 mr-1" />Render shot
                </Button>
                <p class="text-[11px] text-muted-foreground">Whole-scene multi-shot renders live on the Scenes page (step 4).</p>
              </form>
            </CollapsibleContent>
          </Collapsible>
          <div class="mt-2 flex items-center gap-1" role="group" aria-label="Render scene order">
            <span class="mr-1 text-[11px] text-muted-foreground">Order:</span>
            {#each [{ value: 'latest', label: 'Latest' }, { value: 'story', label: 'Story order' }] as option}
              <button type="button" aria-pressed={groupSort === option.value}
                class="rounded-full px-2 py-0.5 text-[11px] transition-colors {groupSort === option.value ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent'}"
                onclick={() => (groupSort = option.value as 'latest' | 'story')}>
                {option.label}
              </button>
            {/each}
          </div>
        </div>

        <!-- The list itself -->
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <div class="min-h-0 flex-1 overflow-y-auto p-2 space-y-1.5 focus:outline-none"
          tabindex="0" role="listbox" aria-label="Scenes with renders" onkeydown={listKeydown}>
          {#if !loaded}
            {#each Array(5) as _, i (i)}
              <div class="flex items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-2">
                <Skeleton class="size-10 shrink-0 rounded-md" />
                <div class="flex-1 space-y-1.5">
                  <Skeleton class="h-3.5 w-32" />
                  <Skeleton class="h-3 w-40" />
                </div>
              </div>
            {/each}
          {:else if error}
            <div class="rounded-lg border border-border p-3">
              <p class="text-sm text-destructive mb-2">Could not load renders: {error}</p>
              <Button size="sm" variant="secondary"
                onclick={() => { error = ''; refresh().catch((e) => (error = e.message)); }}>Retry</Button>
            </div>
          {:else if groups.length === 0}
            <div class="rounded-lg border border-dashed border-border p-3">
              <div class="flex items-center gap-2 mb-1">
                <Clapperboard class="size-4" />
                <span class="font-medium text-sm">Render a scene to see it here</span>
              </div>
              <p class="text-sm text-muted-foreground">
                Render a scene from the <span class="font-medium">Scenes</span> page (step 4), or
                use <span class="font-medium">Render a single shot</span> above. — 还没有渲染。
              </p>
            </div>
          {:else}
            {#each groups as g (g.sceneId)}
              <button
                type="button"
                data-scene-row={g.sceneId}
                onclick={() => selectGroup(g.sceneId)}
                class="group flex w-full items-start gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors
                  {g.sceneId === selectedId
                    ? 'border-primary/60 bg-accent'
                    : 'border-transparent hover:border-border hover:bg-accent/50'}"
              >
                <div class="flex size-10 shrink-0 items-center justify-center rounded-md border border-dashed border-border bg-muted/30 text-muted-foreground/50">
                  {#if g.active.length}
                    <Loader2 class="size-4 animate-spin text-amber-500/80" />
                  {:else}
                    <Clapperboard class="size-4" />
                  {/if}
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-1.5">
                    <span class="size-2 shrink-0 rounded-full {groupDot(g)} {g.active.length ? 'animate-pulse' : ''}"></span>
                    <span class="truncate text-sm font-medium" title={g.title}>{g.title}</span>
                  </div>
                  <p class="mt-0.5 truncate text-xs text-muted-foreground">{groupStatusLine(g)}</p>
                </div>
              </button>
            {/each}
          {/if}
        </div>
      </div>
    </Pane>

    <Handle withHandle />

    <!-- RIGHT: selected scene's render detail (the gallery) -->
    <Pane defaultSize={72} minSize={40} class="min-w-0">
      <div class="h-full overflow-y-auto">
        {#if !loaded}
          <div class="p-5 space-y-4">
            <Skeleton class="h-6 w-56" />
            <div class="flex flex-wrap gap-4">
              <Skeleton class="h-44 w-[320px] rounded-lg" />
              <Skeleton class="h-44 w-[320px] rounded-lg" />
            </div>
          </div>
        {:else if selectedGroup}
          {#key selectedGroup.sceneId}
            {@const g = selectedGroup}
            <div class="p-5">
              <!-- Header: scene title + at-a-glance counts -->
              <div class="flex flex-wrap items-center gap-2 mb-4">
                <h2 class="font-semibold text-base truncate" title={g.title}>{g.title}</h2>
                <div class="flex items-center gap-1.5 ml-auto">
                  {#if g.active.length}
                    <Badge variant="secondary" class="animate-pulse">{g.active.length} in progress</Badge>
                  {/if}
                  {#if g.succeeded}
                    <Badge variant="default">{g.succeeded} rendered</Badge>
                  {/if}
                  {#if g.failed}
                    <Badge variant="destructive">{g.failed} failed</Badge>
                  {/if}
                </div>
              </div>

              <!-- Running jobs pulse strip (top) -->
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

              <!-- Output gallery: each take is a card → open in editor -->
              {#if sceneOutputs(g).length}
                <div class="flex flex-wrap gap-4">
                  {#each sceneOutputs(g) as { out } (out.id)}
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
                        {#if out.captioned_path}
                          <Badge variant="secondary" class="absolute right-2 top-2">captioned</Badge>
                        {/if}
                      </div>

                      <!-- Primary: open in editor (the only place to finish a video) -->
                      <div class="mt-2">
                        <Button size="sm" class="w-full" href={`/editor/${out.id}`} title="Open in editor">
                          <Clapperboard class="size-3.5 mr-1.5" />Open in editor
                        </Button>
                      </div>

                      <!-- Download controls (raw vs captioned). Captioned shown
                           first when available. -->
                      <div class="flex flex-wrap items-center gap-1 mt-1.5">
                        {#if out.captioned_path}
                          <Button
                            variant="secondary"
                            size="sm"
                            class="flex-1"
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
                          class="flex-1"
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
                <div class="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                  Render this scene to create an output.
                </div>
              {/if}

              <!-- Compact failed/running jobs strip — collapsed behind "history (N)"
                   when there are more than 2 jobs. -->
              <div class="mt-5 border-t border-border pt-3">
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
            </div>
          {/key}
        {:else}
          <div class="flex h-full flex-col items-center justify-center text-center text-muted-foreground p-8">
            <ListVideo class="size-10 mb-3 opacity-40" />
            <p class="text-sm">No renders to show</p>
            <p class="text-xs mt-1 max-w-xs">
              Render a scene from the <span class="font-medium">Scenes</span> page, or use
              <span class="font-medium">Render a single shot</span> on the left.
            </p>
          </div>
        {/if}
      </div>
    </Pane>
  </PaneGroup>
</div>
