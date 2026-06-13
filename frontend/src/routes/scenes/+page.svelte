<script lang="ts">
  import { onMount } from 'svelte';
  import { get, patch, post, del, mediaUrl } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import * as Dialog from '$lib/components/ui/dialog';
  import * as Collapsible from '$lib/components/ui/collapsible';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '$lib/components/ui/table';
  import { toast } from 'svelte-sonner';
  import { Wand2, Save, LayoutGrid, Video, Images, Trash2, Sparkles, ImagePlus, Lightbulb, VolumeX, Check, ChevronDown, Film, Clapperboard, Maximize2, Clock } from '@lucide/svelte';

  let scenes: any[] = $state([]);
  let characters: any[] = $state([]);
  let shotsByScene: Record<string, any[]> = $state({});
  let storyboards: Record<string, any> = $state({});
  let renderedScenes: Record<string, boolean> = $state({});
  let error = $state('');
  let busy = $state('');
  let ok = $state('');
  let loaded = $state(false);
  // Long generations run as background ops — per-key so several can run at once.
  let opBusy: Record<string, boolean> = $state({});

  let idea = $state('');
  let targetDuration: number | '' = $state('');
  let sceneCount: number | '' = $state('');
  let castSelection: Record<string, string[]> = $state({});
  let deleteTarget: any = $state(null);
  let sceneRefine: Record<string, string> = $state({});
  let shotRefine: Record<string, string> = $state({});
  let autoProps: Record<string, boolean> = $state({});
  let assetInstr: Record<string, string> = $state({});
  let assetMax: Record<string, number> = $state({});
  let generatedAssets: Record<string, any[]> = $state({});
  let assetPlans: Record<string, { assets: any[]; reasoning: string } | null> = $state({});
  let planSelected: Record<string, boolean[]> = $state({});
  let detailsOpen: Record<string, boolean> = $state({});
  let style: any = $state(null);
  // Storyboard lightbox: the asset currently shown enlarged in a Dialog.
  let lightbox: any = $state(null);

  async function refresh() {
    [scenes, characters] = await Promise.all([get('/scenes'), get('/characters')]);
    // Svelte 5 throws props_invalid_value when bind:open receives undefined
    // (Collapsible's open prop has a fallback) — seed every scene's entry.
    for (const s of scenes) detailsOpen[s.id] ??= false;
    const [allAssets, jobs] = await Promise.all([
      get('/assets'),
      get('/render-jobs').catch(() => [])
    ]);
    storyboards = {};
    for (const a of allAssets) {
      const sid = a.metadata_json?.scene_id;
      if (a.type === 'storyboard' && sid) storyboards[sid] = a;
    }
    const rendered: Record<string, boolean> = {};
    for (const j of jobs) {
      // Whole-scene renders only — a from-shot job (has shot_id) must not mark the scene done.
      if (j.status === 'succeeded' && j.scene_id && !j.shot_id) rendered[j.scene_id] = true;
    }
    renderedScenes = rendered;
    await Promise.all(
      scenes.map(async (s) => {
        // One scene's shots failing must not blank the whole list.
        shotsByScene[s.id] = await get(`/scenes/${s.id}/shots`).catch(() => []);
      })
    );
    shotsByScene = shotsByScene;
  }
  onMount(() => {
    refresh()
      .catch((e) => (error = e.message))
      .finally(() => (loaded = true));
    get('/style').then((s) => (style = s)).catch(() => {});
  });

  async function run(key: string, fn: () => Promise<unknown>, doneMsg = '') {
    busy = key;
    error = '';
    ok = '';
    try {
      await fn();
      await refresh();
      if (doneMsg) toast.success(doneMsg);
      ok = doneMsg;
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  const generateScript = (e: Event) => {
    e.preventDefault();
    run(
      'script',
      () =>
        post('/scripts/generate', {
          idea,
          target_duration: targetDuration || null,
          ...(sceneCount ? { scene_count: sceneCount } : {})
        }),
      'Script generated — scenes created below.'
    );
  };

  const expandScene = (s: any) =>
    run(`expand-${s.id}`, () =>
      post(`/scenes/${s.id}/generate`, { character_ids: castSelection[s.id] ?? [] })
    );

  async function generateShots(s: any) {
    const key = `shots-${s.id}`;
    opBusy[key] = true;
    try {
      await runBackgroundOp(
        `/scenes/${s.id}/shots/generate`,
        { auto_assets: autoProps[s.id] ?? true },
        {
          label: 'Shot generation',
          onDone: async () => {
            opBusy[key] = false;
            // Shots changed (and auto props may have generated assets) — refetch
            // this scene's shots and drop any now-stale suggestion plan.
            shotsByScene[s.id] = await get(`/scenes/${s.id}/shots`);
            assetPlans[s.id] = null;
          },
          onFail: () => (opBusy[key] = false)
        }
      );
    } catch (e: any) {
      opBusy[key] = false;
      toast.error(e.message);
    }
  }

  async function generateStoryboard(s: any) {
    const key = `sb-${s.id}`;
    opBusy[key] = true;
    try {
      await runBackgroundOp(`/scenes/${s.id}/storyboard`, undefined, {
        label: 'Storyboard',
        onDone: async () => {
          opBusy[key] = false;
          await refresh();
        },
        onFail: () => (opBusy[key] = false)
      });
    } catch (e: any) {
      opBusy[key] = false;
      toast.error(e.message);
    }
  }

  const renderScene = (s: any) =>
    run(
      `render-${s.id}`,
      () => post(`/scenes/${s.id}/render`),
      'Render job submitted — track it on the Render page.'
    );

  // Pipeline stepper: one entry per stage, computed from data already loaded.
  // "Expanded" = scene_json holds more than the pre-expand stub {script_scene_id}.
  function sceneSteps(s: any) {
    const expanded = !!(s.scene_json && Object.keys(s.scene_json).length > 1);
    const hasShots = (shotsByScene[s.id]?.length ?? 0) > 0;
    return [
      {
        key: 'expand',
        label: 'Expand',
        icon: Wand2,
        done: expanded,
        busy: busy === `expand-${s.id}`,
        busyLabel: 'Expanding…',
        action: () => expandScene(s)
      },
      {
        key: 'shots',
        label: 'Shots',
        icon: LayoutGrid,
        done: hasShots,
        busy: !!opBusy[`shots-${s.id}`],
        busyLabel: 'Generating shots…',
        action: () => generateShots(s)
      },
      {
        key: 'storyboard',
        label: 'Storyboard',
        icon: Images,
        done: !!storyboards[s.id],
        busy: !!opBusy[`sb-${s.id}`],
        busyLabel: 'Generating storyboard…',
        action: () => generateStoryboard(s)
      },
      {
        key: 'render',
        label: 'Render',
        icon: Video,
        done: !!renderedScenes[s.id],
        busy: busy === `render-${s.id}`,
        busyLabel: 'Submitting…',
        action: () => renderScene(s)
      }
    ];
  }

  // Furthest-completed stage index (-1 = nothing done) → drives the left accent
  // colour and the at-a-glance status line.
  function progressIndex(s: any) {
    const steps = sceneSteps(s);
    let last = -1;
    for (let i = 0; i < steps.length; i++) if (steps[i].done) last = i;
    return last;
  }

  const ACCENT = [
    'before:bg-sky-500/70', // expanded
    'before:bg-violet-500/70', // shots
    'before:bg-amber-500/70', // storyboard
    'before:bg-emerald-500/70' // rendered
  ];
  function accentClass(s: any) {
    const i = progressIndex(s);
    return i >= 0 ? ACCENT[i] : 'before:bg-border';
  }

  // One-line, human status derived purely from already-loaded data.
  function statusLine(s: any): string {
    const shots = shotsByScene[s.id]?.length ?? 0;
    const parts: string[] = [];
    if (renderedScenes[s.id]) parts.push('Rendered');
    else if (storyboards[s.id]) parts.push('Storyboard ready');
    else if (shots > 0) parts.push('Shots ready');
    else if (s.scene_json && Object.keys(s.scene_json).length > 1) parts.push('Expanded');
    else parts.push('New — needs expanding');
    if (shots > 0) parts.push(`${shots} shot${shots === 1 ? '' : 's'}`);
    if (s.duration) parts.push(`${s.duration}s`);
    return parts.join(' · ');
  }

  function toggleCast(sceneId: string, charId: string) {
    const cur = castSelection[sceneId] ?? [];
    castSelection[sceneId] = cur.includes(charId)
      ? cur.filter((c) => c !== charId)
      : [...cur, charId];
  }

  const saveScene = (s: any) =>
    run(`save-${s.id}`, () =>
      patch(`/scenes/${s.id}`, {
        title: s.title,
        summary: s.summary,
        duration: s.duration,
        aspect_ratio: s.aspect_ratio
      })
    , 'Scene saved.');

  async function confirmDeleteScene() {
    const s = deleteTarget;
    if (!s) return;
    busy = `delete-${s.id}`;
    try {
      const r = await del(`/scenes/${s.id}`);
      deleteTarget = null;
      toast.success(`Scene deleted (${r.shots_deleted} shots removed).`);
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  async function deleteShot(scene: any, shot: any) {
    busy = `delete-${shot.id}`;
    try {
      await del(`/shots/${shot.id}`);
      toast.success('Shot deleted.');
      shotsByScene[scene.id] = await get(`/scenes/${scene.id}/shots`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  async function refineScene(s: any) {
    const instruction = (sceneRefine[s.id] ?? '').trim();
    if (!instruction) return;
    busy = `refine-${s.id}`;
    try {
      const r = await post(`/scenes/${s.id}/refine`, { instruction });
      Object.assign(s, r.scene);
      sceneRefine[s.id] = '';
      toast.success(r.note || 'Refined');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  async function refineShot(scene: any, shot: any) {
    const instruction = (shotRefine[scene.id] ?? '').trim();
    if (!instruction) {
      toast.error('Type an instruction in the shot refine box first.');
      return;
    }
    busy = `refine-${shot.id}`;
    try {
      const r = await post(`/shots/${shot.id}/refine`, { instruction });
      Object.assign(shot, r.shot);
      toast.success(r.note || 'Refined');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  async function startAssetGeneration(s: any, instruction: string, maxAssets: number) {
    const key = `assets-${s.id}`;
    opBusy[key] = true;
    try {
      await runBackgroundOp(
        `/scenes/${s.id}/assets/generate`,
        { instruction, max_assets: maxAssets },
        {
          label: 'Asset generation',
          onDone: async (op) => {
            opBusy[key] = false;
            const ids: string[] = op.result_json?.asset_ids ?? [];
            const all = await get('/assets');
            generatedAssets[s.id] = all.filter((a: any) => ids.includes(a.id));
            assetPlans[s.id] = null; // any pending suggestion plan is now out of date
            // Generation auto-attaches assets and @-tags shot prompts — refresh the shot table.
            shotsByScene[s.id] = await get(`/scenes/${s.id}/shots`);
          },
          onFail: () => (opBusy[key] = false)
        }
      );
    } catch (e: any) {
      opBusy[key] = false;
      toast.error(e.message);
    }
  }

  const generateAssets = (s: any) =>
    startAssetGeneration(s, (assetInstr[s.id] ?? '').trim(), assetMax[s.id] ?? 4);

  async function suggestAssets(s: any) {
    busy = `plan-${s.id}`;
    assetPlans[s.id] = null; // hide any stale plan while re-planning
    try {
      const plan = await post(`/scenes/${s.id}/assets/plan`, {
        instruction: (assetInstr[s.id] ?? '').trim(),
        max_assets: assetMax[s.id] ?? 4
      });
      assetPlans[s.id] = plan;
      planSelected[s.id] = (plan.assets ?? []).map(() => true);
      if (!plan.assets?.length) toast.info('No new assets suggested for this scene.');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  async function generateSelectedAssets(s: any) {
    const plan = assetPlans[s.id];
    if (!plan) return;
    const selected = plan.assets.filter((_, i) => planSelected[s.id]?.[i]);
    if (!selected.length) return;
    const userInstruction = (assetInstr[s.id] ?? '').trim();
    const instruction =
      'Generate exactly these assets: ' +
      selected.map((a) => `${a.name} — ${a.description}`).join('; ') +
      (userInstruction ? `. ${userInstruction}` : '');
    await startAssetGeneration(s, instruction, selected.length);
  }

  const saveShot = (shot: any) =>
    run(`save-${shot.id}`, () =>
      patch(`/shots/${shot.id}`, {
        prompt: shot.prompt,
        duration: shot.duration,
        camera: shot.camera,
        movement: shot.movement
      })
    , 'Shot saved.');
</script>

<div class="p-6">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Scenes</h1>
    <p class="text-sm text-muted-foreground">Turn a story idea into scenes, then walk each one through Expand, Shots, Storyboard and Render.</p>
  </div>

  <form class="mb-6 rounded-xl border border-border bg-card/60 p-5 shadow-sm" onsubmit={generateScript}>
    <div class="flex items-center gap-2 mb-3">
      <div class="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Clapperboard class="size-4" />
      </div>
      <div>
        <h2 class="text-sm font-semibold leading-tight">Start a new story</h2>
        <p class="text-xs text-muted-foreground">Describe an idea — AI writes a script and splits it into scenes.</p>
      </div>
    </div>
    <label class="sr-only" for="idea">Story idea</label>
    <textarea id="idea" bind:value={idea}
      placeholder="e.g. A short video about a kid learning to read…"
      class="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm min-h-[76px] resize-y mb-3"></textarea>
    <div class="flex flex-wrap gap-4 items-end">
      <div class="min-w-[150px]">
        <label class="block text-xs text-muted-foreground mb-1" for="dur">Target duration</label>
        <div class="relative">
          <Clock class="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground/70 pointer-events-none" />
          <input id="dur" type="number" bind:value={targetDuration} min="3" placeholder="auto"
            class="w-full rounded-md border border-input bg-background pl-8 pr-2 py-1.5 text-sm" />
          <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground/70 pointer-events-none">sec</span>
        </div>
      </div>
      <div class="min-w-[120px]">
        <label class="block text-xs text-muted-foreground mb-1" for="scene-count">Scenes</label>
        <input id="scene-count" type="number" bind:value={sceneCount} min="1" max="20" placeholder="auto"
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
      </div>
      <p class="text-xs text-muted-foreground self-center pb-1.5">1 scene = 1 video</p>
      <div class="ml-auto">
        <Button type="submit" disabled={busy === 'script' || !idea} size="sm">
          <Wand2 class="size-4 mr-1" />{busy === 'script' ? 'Generating…' : 'Generate script'}
        </Button>
      </div>
    </div>
  </form>

  {#if !loaded}
    {#each Array(3) as _, i (i)}
      <div class="mb-4 rounded-xl border border-border p-4">
        <div class="flex items-center gap-4">
          <Skeleton class="size-16 shrink-0 rounded-lg" />
          <div class="flex-1 space-y-2">
            <Skeleton class="h-5 w-56" />
            <Skeleton class="h-3 w-44" />
            <Skeleton class="h-6 w-80" />
          </div>
          <Skeleton class="h-8 w-28" />
        </div>
      </div>
    {/each}
  {/if}

  {#each scenes.slice().reverse() as s (s.id)}
    {@const steps = sceneSteps(s)}
    <!-- The "current" step is the first not-done step ONLY when nothing after
         it is done. If a later step is done (legacy/out-of-band data, e.g. a
         rendered scene whose scene_json is still the pre-expand stub), pushing
         "Next" would re-run an earlier stage and clobber finished work — so we
         treat the scene as complete-ish: primary CTA becomes "Re-render" and
         the skipped earlier steps render muted but still clickable. -->
    {@const firstNotDone = steps.findIndex((st) => !st.done)}
    {@const laterDone = firstNotDone !== -1 && steps.some((st, i) => i > firstNotDone && st.done)}
    {@const currentIdx = laterDone ? -1 : firstNotDone}
    {@const current = currentIdx === -1 ? null : steps[currentIdx]}
    <Card class="mb-4 relative overflow-hidden before:absolute before:inset-y-0 before:left-0 before:w-1 {accentClass(s)}">
      <CardContent class="p-4 pl-5">
        <!-- Header: thumbnail + title/status + pipeline stepper + primary action -->
        <div class="flex items-start gap-4">
          <!-- Thumbnail for instant recognition (storyboard if present, else placeholder) -->
          {#if storyboards[s.id]}
            <button type="button"
              class="group relative size-16 shrink-0 overflow-hidden rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              title="View storyboard" onclick={() => (lightbox = storyboards[s.id])}>
              <img class="size-full object-cover transition-transform group-hover:scale-105"
                src={mediaUrl(storyboards[s.id].file_path)} alt="Storyboard" loading="lazy" />
              <span class="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/40 transition-colors">
                <Maximize2 class="size-4 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
              </span>
            </button>
          {:else}
            <div class="flex size-16 shrink-0 items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 text-muted-foreground/50">
              <Film class="size-5" />
            </div>
          {/if}

          <div class="min-w-0 flex-1">
            <!-- Title + status line -->
            <div class="flex items-center gap-2 mb-2">
              <h3 class="font-semibold text-sm truncate" title={s.title}>{s.title || 'Untitled scene'}</h3>
              <Badge variant="secondary" class="shrink-0 gap-1"><Clock class="size-3" />{s.duration}s</Badge>
            </div>
            <p class="text-xs text-muted-foreground mb-3">{statusLine(s)}</p>

            <!-- Pipeline stepper: connected segments, primary visual element -->
            <div class="flex items-center gap-0">
              {#each steps as st, i (st.key)}
                {#if i > 0}
                  <div class="h-0.5 w-4 sm:w-6 shrink-0 {st.done && steps[i - 1].done ? 'bg-primary/50' : 'bg-border'}"></div>
                {/if}
                {#if st.done}
                  <span class="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                    <Check class="size-3" />{st.label}{#if st.key === 'shots' && shotsByScene[s.id]?.length}<span class="opacity-70">{shotsByScene[s.id].length}</span>{/if}
                  </span>
                {:else if i === currentIdx}
                  <button type="button"
                    class="inline-flex items-center gap-1.5 rounded-full bg-background px-2.5 py-1 text-xs font-medium ring-2 ring-primary/70 hover:bg-accent disabled:opacity-60"
                    disabled={st.busy} onclick={st.action}>
                    <st.icon class="size-3" />{st.busy ? st.busyLabel : st.label}
                  </button>
                {:else if !st.done && laterDone}
                  <!-- Skipped earlier step on a complete-ish scene: muted, still clickable. -->
                  <button type="button"
                    class="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border px-2.5 py-1 text-xs text-muted-foreground/60 hover:text-foreground disabled:opacity-60"
                    title="Skipped — later steps are already done. Click to run it anyway."
                    disabled={st.busy} onclick={st.action}>
                    <st.icon class="size-3" />{st.busy ? st.busyLabel : st.label}
                  </button>
                {:else}
                  <span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-muted-foreground/50">
                    <st.icon class="size-3" />{st.label}
                  </span>
                {/if}
              {/each}
            </div>
          </div>

          <!-- Primary next-step action + delete -->
          <div class="flex shrink-0 items-center gap-2">
            {#if current}
              <div class="flex flex-col items-end gap-1">
                <Button size="sm" disabled={current.busy} onclick={current.action}>
                  <current.icon class="size-3.5 mr-1" />
                  {current.busy ? current.busyLabel : `Next: ${current.label}`}
                </Button>
                {#if current.key === 'shots'}
                  <label class="inline-flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none">
                    <input
                      type="checkbox"
                      class="w-auto"
                      checked={autoProps[s.id] ?? true}
                      onchange={(e) => (autoProps[s.id] = (e.currentTarget as HTMLInputElement).checked)}
                    />
                    auto props
                  </label>
                {/if}
              </div>
            {:else}
              <Button variant="secondary" size="sm" disabled={busy === `render-${s.id}`} onclick={() => renderScene(s)}>
                <Video class="size-3.5 mr-1" />{busy === `render-${s.id}` ? 'Submitting…' : 'Re-render'}
              </Button>
            {/if}
            <Button variant="ghost" size="icon" class="size-8 text-muted-foreground hover:text-destructive"
              title="Delete scene" disabled={!!busy} onclick={() => (deleteTarget = s)}>
              <Trash2 class="size-4" />
            </Button>
          </div>
        </div>

        <!-- Everything else lives behind the Details expander -->
        <Collapsible.Root open={detailsOpen[s.id] ?? false} onOpenChange={(v) => (detailsOpen[s.id] = v)}>
          <div class="mt-3 border-t border-border/60 pt-2">
            <Collapsible.Trigger
              class="flex w-full items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
              <ChevronDown class="size-3.5 transition-transform {detailsOpen[s.id] ? 'rotate-180' : ''}" />
              {detailsOpen[s.id] ? 'Hide details' : 'Edit details, shots & assets'}
              <span class="ml-auto font-mono text-[10px] opacity-40">{s.id}</span>
            </Collapsible.Trigger>
          </div>
          <Collapsible.Content>
            <div class="pt-3 space-y-4">
              <!-- Scene -->
              <div>
                <div class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Scene</div>
                <div class="flex flex-wrap gap-4 items-end mb-2">
                  <div style="flex:2;min-width:160px">
                    <label class="block text-xs text-muted-foreground mb-1" for="title-{s.id}">Title</label>
                    <input id="title-{s.id}" bind:value={s.title}
                      class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
                  </div>
                  <div style="flex:0 0 90px;min-width:90px">
                    <label class="block text-xs text-muted-foreground mb-1" for="dur-{s.id}">Duration</label>
                    <input id="dur-{s.id}" type="number" min="3" bind:value={s.duration}
                      class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
                  </div>
                  <div style="flex:0 0 100px;min-width:100px">
                    <label class="block text-xs text-muted-foreground mb-1" for="ar-{s.id}">Aspect</label>
                    <select id="ar-{s.id}" bind:value={s.aspect_ratio}
                      class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
                      <option>9:16</option><option>16:9</option><option>1:1</option>
                    </select>
                  </div>
                  <div>
                    <Button variant="secondary" size="sm" disabled={!!busy} onclick={() => saveScene(s)}>
                      <Save class="size-3 mr-1" />{busy === `save-${s.id}` ? 'Saving…' : 'Save scene'}
                    </Button>
                  </div>
                </div>

                <label class="block text-xs text-muted-foreground mb-1" for="sum-{s.id}">Summary</label>
                <textarea id="sum-{s.id}" bind:value={s.summary}
                  class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm min-h-[70px] resize-y mb-3"></textarea>

                <div class="flex gap-2 mb-3">
                  <input
                    bind:value={sceneRefine[s.id]}
                    placeholder="Tell AI what to change…"
                    class="flex-1 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  />
                  <Button variant="outline" size="sm"
                    disabled={!!busy || !(sceneRefine[s.id] ?? '').trim()} onclick={() => refineScene(s)}>
                    <Sparkles class="size-3 mr-1" />{busy === `refine-${s.id}` ? 'Refining…' : 'AI refine'}
                  </Button>
                </div>

                <div class="text-xs text-muted-foreground mb-1">Cast for expansion:</div>
                <div class="flex flex-wrap gap-3 mb-2">
                  {#each characters as c}
                    <label class="inline-flex items-center gap-1.5 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        class="w-auto"
                        checked={(castSelection[s.id] ?? s.character_ids_json ?? []).includes(c.id)}
                        onchange={() => toggleCast(s.id, c.id)}
                      />
                      {c.name}
                    </label>
                  {/each}
                </div>
                <Button variant="outline" size="sm" disabled={!!busy} onclick={() => expandScene(s)}>
                  <Wand2 class="size-3 mr-1" />{busy === `expand-${s.id}` ? 'Expanding…' : 'Re-expand scene (AI)'}
                </Button>
              </div>

              <!-- Shots -->
              <div class="border-t border-border pt-3">
                <div class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Shots</div>
                <div class="flex flex-wrap items-center gap-2 mb-2">
                  <Button variant="outline" size="sm" disabled={opBusy[`shots-${s.id}`]} onclick={() => generateShots(s)}>
                    <LayoutGrid class="size-3 mr-1" />{opBusy[`shots-${s.id}`] ? 'Generating…' : 'Regenerate shots (AI)'}
                  </Button>
                  <label class="inline-flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none">
                    <input
                      type="checkbox"
                      class="w-auto"
                      checked={autoProps[s.id] ?? true}
                      onchange={(e) => (autoProps[s.id] = (e.currentTarget as HTMLInputElement).checked)}
                    />
                    auto props
                  </label>
                </div>

                {#if shotsByScene[s.id]?.length}
                  <div class="flex gap-2 items-center">
                    <Sparkles class="size-3.5 text-muted-foreground shrink-0" />
                    <input
                      bind:value={shotRefine[s.id]}
                      placeholder="Shot refine instruction — then click the sparkles on a shot row…"
                      class="flex-1 rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                    />
                  </div>
                  <div class="mt-2 overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead class="w-8">#</TableHead>
                          <TableHead class="w-1/2">prompt</TableHead>
                          <TableHead>camera</TableHead>
                          <TableHead>movement</TableHead>
                          <TableHead class="w-16">s</TableHead>
                          <TableHead></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {#each shotsByScene[s.id] as shot (shot.id)}
                          <TableRow>
                            <TableCell>{shot.shot_order + 1}</TableCell>
                            <TableCell>
                              <div class="relative">
                                <textarea class="w-full rounded border border-input bg-background px-2 py-1 text-xs min-h-[46px] resize-y"
                                  bind:value={shot.prompt}></textarea>
                                {#if !/「[^」]+」/.test(shot.prompt ?? '')}
                                  <VolumeX
                                    class="absolute top-1 right-1 size-3.5 text-muted-foreground/60 pointer-events-none"
                                    title="No spoken line — every shot should speak"
                                  />
                                {/if}
                              </div>
                            </TableCell>
                            <TableCell>
                              <input class="w-full rounded border border-input bg-background px-2 py-1 text-xs"
                                bind:value={shot.camera} />
                            </TableCell>
                            <TableCell>
                              <input class="w-full rounded border border-input bg-background px-2 py-1 text-xs"
                                bind:value={shot.movement} />
                            </TableCell>
                            <TableCell>
                              <input type="number" min="1" max="15"
                                class="w-16 rounded border border-input bg-background px-2 py-1 text-xs"
                                bind:value={shot.duration} />
                            </TableCell>
                            <TableCell>
                              <div class="flex items-center gap-0.5">
                                <Button variant="outline" size="sm" disabled={!!busy} onclick={() => saveShot(shot)}>
                                  {busy === `save-${shot.id}` ? 'Saving…' : 'Save'}
                                </Button>
                                <Button variant="ghost" size="icon" class="size-7" title="AI refine this shot"
                                  disabled={!!busy || !(shotRefine[s.id] ?? '').trim()} onclick={() => refineShot(s, shot)}>
                                  <Sparkles class="size-3.5" />
                                </Button>
                                <Button variant="ghost" size="icon" class="size-7 text-destructive hover:text-destructive"
                                  title="Delete shot" disabled={!!busy} onclick={() => deleteShot(s, shot)}>
                                  <Trash2 class="size-3.5" />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        {/each}
                      </TableBody>
                    </Table>
                  </div>
                  <div class="text-xs text-muted-foreground mt-1">
                    Shot durations sum to {shotsByScene[s.id].reduce((t, sh) => t + (sh.duration || 0), 0)}s
                    (Kling allows 3–15s per render).
                  </div>
                {:else}
                  <p class="text-xs text-muted-foreground">No shots yet.</p>
                {/if}
              </div>

              <!-- Assets -->
              <div class="border-t border-border pt-3">
                <div class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Assets</div>
                <div class="text-xs text-muted-foreground mb-1">Generate assets (props) for this scene:</div>
                <div class="flex flex-wrap gap-2 items-center">
                  <input
                    bind:value={assetInstr[s.id]}
                    placeholder="e.g. 需要一个红色杯子 / a red cup"
                    class="flex-1 min-w-[200px] rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  />
                  <input type="number" min="1" max="8" title="Max assets"
                    value={assetMax[s.id] ?? 4}
                    onchange={(e) => (assetMax[s.id] = Number((e.currentTarget as HTMLInputElement).value) || 4)}
                    class="w-16 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  />
                  <Button variant="outline" size="sm" disabled={!!busy} onclick={() => suggestAssets(s)}>
                    <Lightbulb class="size-3 mr-1" />{busy === `plan-${s.id}` ? 'Suggesting…' : 'Suggest'}
                  </Button>
                  <Button variant="outline" size="sm" disabled={opBusy[`assets-${s.id}`]} onclick={() => generateAssets(s)}>
                    <ImagePlus class="size-3 mr-1" />{opBusy[`assets-${s.id}`] ? 'Generating…' : 'Generate assets'}
                  </Button>
                  {#if style?.style_prompt}
                    <Badge variant="secondary" class="text-muted-foreground max-w-[260px]" title={style.style_prompt}>
                      <span class="truncate">
                        styled: {style.style_prompt.length > 30
                          ? `${style.style_prompt.slice(0, 30)}…`
                          : style.style_prompt}
                      </span>
                    </Badge>
                  {/if}
                </div>
                {#if assetPlans[s.id]?.assets?.length}
                  {@const plan = assetPlans[s.id]!}
                  {@const selectedItems = plan.assets.filter((_, i) => planSelected[s.id]?.[i])}
                  {@const reuseCount = selectedItems.filter((a) => a.reuse).length}
                  {@const genCount = selectedItems.length - reuseCount}
                  <div class="mt-2 rounded-md border border-border p-2 space-y-2">
                    <div class="text-xs font-medium">Suggested assets</div>
                    <div class="flex flex-wrap gap-2">
                      {#each plan.assets as a, i (i)}
                        <label class="flex w-[230px] cursor-pointer items-start gap-2 rounded-md border border-border p-2 text-xs">
                          <input type="checkbox" class="mt-0.5 w-auto" bind:checked={planSelected[s.id][i]} />
                          <span class="min-w-0">
                            <span class="flex items-center gap-1.5">
                              <span class="font-medium truncate">{a.name}</span>
                              <Badge variant="secondary" class="text-[10px] px-1.5 py-0">{a.asset_type}</Badge>
                              {#if a.reuse}
                                <Badge variant="secondary" class="text-[10px] px-1.5 py-0 text-muted-foreground">reuses existing</Badge>
                              {/if}
                            </span>
                            <span class="block text-muted-foreground mt-0.5">{a.description}</span>
                            {#if a.shot_orders?.length}
                              <span class="block text-muted-foreground mt-0.5">
                                shots {a.shot_orders.map((o: number) => `#${o + 1}`).join(', ')}
                              </span>
                            {/if}
                          </span>
                        </label>
                      {/each}
                    </div>
                    {#if plan.reasoning}
                      <p class="text-xs text-muted-foreground">{plan.reasoning}</p>
                    {/if}
                    <Button size="sm" disabled={opBusy[`assets-${s.id}`] || !selectedItems.length}
                      onclick={() => generateSelectedAssets(s)}>
                      <ImagePlus class="size-3 mr-1" />
                      {opBusy[`assets-${s.id}`]
                        ? 'Generating…'
                        : reuseCount
                          ? `Generate ${genCount} + reuse ${reuseCount}`
                          : `Generate selected (${genCount})`}
                    </Button>
                  </div>
                {/if}
                {#if generatedAssets[s.id]?.length}
                  <div class="flex flex-wrap gap-2 mt-2">
                    {#each generatedAssets[s.id] as a (a.id)}
                      <div class="w-[120px]">
                        {#if mediaUrl(a.file_path)}
                          <img class="w-full aspect-square object-cover rounded-md border border-border"
                            src={mediaUrl(a.file_path)} alt={a.name} loading="lazy" />
                        {/if}
                        <div class="text-xs text-muted-foreground truncate mt-0.5" title={a.name}>{a.name}</div>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>

              <!-- Storyboard -->
              <div class="border-t border-border pt-3">
                <div class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Storyboard</div>
                <div class="flex flex-wrap items-center gap-2 mb-2">
                  <Button variant="outline" size="sm"
                    disabled={opBusy[`sb-${s.id}`] || !(shotsByScene[s.id]?.length)}
                    onclick={() => generateStoryboard(s)}>
                    <Images class="size-3 mr-1" />{opBusy[`sb-${s.id}`] ? 'Generating…' : 'Regenerate storyboard (ERNIE)'}
                  </Button>
                </div>
                {#if storyboards[s.id]}
                  <button type="button"
                    class="group relative block max-w-[420px] w-full overflow-hidden rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-ring"
                    title="Click to enlarge" onclick={() => (lightbox = storyboards[s.id])}>
                    <img class="w-full transition-transform group-hover:scale-[1.02]" src={mediaUrl(storyboards[s.id].file_path)} alt="Storyboard" loading="lazy" />
                    <span class="absolute right-2 top-2 flex items-center gap-1 rounded-md bg-black/60 px-2 py-1 text-xs text-white opacity-0 group-hover:opacity-100 transition-opacity">
                      <Maximize2 class="size-3" />Enlarge
                    </span>
                  </button>
                {:else}
                  <p class="text-xs text-muted-foreground">No storyboard yet.</p>
                {/if}
              </div>
            </div>
          </Collapsible.Content>
        </Collapsible.Root>
      </CardContent>
    </Card>
  {:else}
    {#if loaded && error}
      <Card>
        <CardContent class="p-4">
          <p class="text-sm text-destructive mb-2">Could not load scenes: {error}</p>
          <Button
            size="sm"
            variant="secondary"
            onclick={() => {
              error = '';
              refresh().catch((e) => (error = e.message));
            }}>Retry</Button
          >
        </CardContent>
      </Card>
    {:else if loaded}
      <Card>
        <CardContent class="p-4">
          <div class="flex items-center gap-2 mb-1">
            <Lightbulb class="size-4" />
            <span class="font-medium text-sm">No scenes yet</span>
          </div>
          <p class="text-sm text-muted-foreground">
            Write your idea above and generate a script — one scene becomes one video,
            and each scene then walks through Expand, Shots, Storyboard and Render.
          </p>
          <p class="text-sm text-muted-foreground mt-1">
            Tip: add characters and a style first so generated scenes stay consistent —
            先添加角色和风格，生成的场景更一致。
          </p>
        </CardContent>
      </Card>
    {/if}
  {/each}
</div>

<Dialog.Root open={lightbox !== null} onOpenChange={(open) => !open && (lightbox = null)}>
  <Dialog.Content class="max-w-4xl">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2"><Images class="size-4" />Storyboard</Dialog.Title>
    </Dialog.Header>
    {#if lightbox}
      <img class="w-full rounded-lg" src={mediaUrl(lightbox.file_path)} alt="Storyboard" />
    {/if}
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root open={deleteTarget !== null} onOpenChange={(open) => !open && (deleteTarget = null)}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>
        Delete scene and its {shotsByScene[deleteTarget?.id]?.length ?? 0} shots?
      </Dialog.Title>
      <Dialog.Description>
        "{deleteTarget?.title}" and all of its shots will be permanently deleted.
        Rendered videos are kept.
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" size="sm" onclick={() => (deleteTarget = null)}>Cancel</Button>
      <Button variant="destructive" size="sm" disabled={!!busy} onclick={confirmDeleteScene}>
        <Trash2 class="size-3 mr-1" />{busy === `delete-${deleteTarget?.id}` ? 'Deleting…' : 'Delete'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
