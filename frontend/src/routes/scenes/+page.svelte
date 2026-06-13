<script lang="ts">
  import { onMount } from 'svelte';
  import { get, patch, post, del, mediaUrl } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { Button } from '$lib/components/ui/button';
  import * as Dialog from '$lib/components/ui/dialog';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { PaneGroup, Pane, Handle } from '$lib/components/ui/resizable';
  import { toast } from 'svelte-sonner';
  import { Wand2, LayoutGrid, Video, Images, Trash2, Lightbulb, Clock, Plus, Clapperboard, ChevronDown, ListVideo } from '@lucide/svelte';
  import SceneListItem from '$lib/scenes/SceneListItem.svelte';
  import SceneDetail from '$lib/scenes/SceneDetail.svelte';

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
  let style: any = $state(null);
  // Storyboard lightbox: the asset currently shown enlarged in a Dialog.
  let lightbox: any = $state(null);

  // Master–detail selection (in-memory). The "New story" generator lives at the
  // top of the left list and toggles open; null selectedId + no form = empty.
  let selectedId: string | null = $state(null);
  let showGenerator = $state(false);

  // List order: newest-activity first (matches the old reversed render).
  const orderedScenes = $derived(scenes.slice().reverse());
  const selectedScene = $derived(scenes.find((s) => s.id === selectedId) ?? null);

  // Keep selection valid as scenes change: default to first, fall back on delete.
  $effect(() => {
    if (!loaded) return;
    if (orderedScenes.length === 0) {
      if (selectedId !== null) selectedId = null;
      return;
    }
    if (selectedId === null || !scenes.some((s) => s.id === selectedId)) {
      selectedId = orderedScenes[0].id;
    }
  });

  async function refresh() {
    [scenes, characters] = await Promise.all([get('/scenes'), get('/characters')]);
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
    // Remember which scenes existed so we can select the newest one afterwards.
    const before = new Set(scenes.map((s) => s.id));
    run(
      'script',
      async () => {
        await post('/scripts/generate', {
          idea,
          target_duration: targetDuration || null,
          ...(sceneCount ? { scene_count: sceneCount } : {})
        });
      },
      'Script generated — scenes created.'
    ).then(() => {
      const fresh = scenes.find((s) => !before.has(s.id));
      if (fresh) {
        selectedId = fresh.id;
        showGenerator = false;
        idea = '';
      }
    });
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

  // Status-dot colour by furthest stage (mirrors the old left-accent palette).
  const DOT = [
    'bg-sky-500/80', // expanded
    'bg-violet-500/80', // shots
    'bg-amber-500/80', // storyboard
    'bg-emerald-500/80' // rendered
  ];
  function accentDot(s: any) {
    const i = progressIndex(s);
    return i >= 0 ? DOT[i] : 'bg-border';
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
      // If we just deleted the selected scene, drop selection so the $effect
      // falls back to the first remaining scene (or the empty state).
      if (selectedId === s.id) selectedId = null;
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

  function selectScene(id: string) {
    selectedId = id;
    showGenerator = false;
  }
</script>

<div class="flex h-full flex-col">
  <!-- Page header (unchanged copy) -->
  <div class="px-6 pt-6 pb-3 shrink-0">
    <h1 class="text-lg font-semibold">Scenes</h1>
    <p class="text-sm text-muted-foreground">Turn a story idea into scenes, then walk each one through Expand, Shots, Storyboard and Render.</p>
  </div>

  <PaneGroup direction="horizontal" class="flex-1 min-h-0 border-t border-border">
    <!-- LEFT: scene list (the monitor) -->
    <Pane defaultSize={28} minSize={20} class="min-w-0">
      <div class="flex h-full flex-col">
        <!-- New story affordance -->
        <div class="shrink-0 border-b border-border p-3">
          <Button variant={showGenerator ? 'secondary' : 'outline'} size="sm" class="w-full justify-start"
            onclick={() => (showGenerator = !showGenerator)}>
            <Plus class="size-4 mr-1.5" />New story
            <ChevronDown class="size-3.5 ml-auto transition-transform {showGenerator ? 'rotate-180' : ''}" />
          </Button>

          {#if showGenerator}
            <form class="mt-3 rounded-lg border border-border bg-card/60 p-3 shadow-sm" onsubmit={generateScript}>
              <div class="flex items-center gap-2 mb-2">
                <div class="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Clapperboard class="size-3.5" />
                </div>
                <div>
                  <h2 class="text-xs font-semibold leading-tight">Start a new story</h2>
                  <p class="text-[11px] text-muted-foreground">AI writes a script and splits it into scenes.</p>
                </div>
              </div>
              <label class="sr-only" for="idea">Story idea</label>
              <textarea id="idea" bind:value={idea}
                placeholder="e.g. A short video about a kid learning to read…"
                class="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm min-h-[72px] resize-y mb-2"></textarea>
              <div class="flex flex-wrap gap-2 items-end mb-2">
                <div class="min-w-[110px] flex-1">
                  <label class="block text-xs text-muted-foreground mb-1" for="dur">Duration</label>
                  <div class="relative">
                    <Clock class="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground/70 pointer-events-none" />
                    <input id="dur" type="number" bind:value={targetDuration} min="3" placeholder="auto"
                      class="w-full rounded-md border border-input bg-background pl-8 pr-8 py-1.5 text-sm" />
                    <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground/70 pointer-events-none">s</span>
                  </div>
                </div>
                <div class="min-w-[80px] flex-1">
                  <label class="block text-xs text-muted-foreground mb-1" for="scene-count">Scenes</label>
                  <input id="scene-count" type="number" bind:value={sceneCount} min="1" max="20" placeholder="auto"
                    class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
                </div>
              </div>
              <p class="text-[11px] text-muted-foreground mb-2">1 scene = 1 video</p>
              <Button type="submit" disabled={busy === 'script' || !idea} size="sm" class="w-full">
                <Wand2 class="size-4 mr-1" />{busy === 'script' ? 'Generating…' : 'Generate script'}
              </Button>
            </form>
          {/if}
        </div>

        <!-- The list itself -->
        <div class="min-h-0 flex-1 overflow-y-auto p-2 space-y-1.5">
          {#if !loaded}
            {#each Array(5) as _, i (i)}
              <div class="flex items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-2">
                <Skeleton class="size-10 shrink-0 rounded-md" />
                <div class="flex-1 space-y-1.5">
                  <Skeleton class="h-3.5 w-32" />
                  <Skeleton class="h-3 w-40" />
                  <Skeleton class="h-2 w-24" />
                </div>
              </div>
            {/each}
          {:else if error}
            <div class="rounded-lg border border-border p-3">
              <p class="text-sm text-destructive mb-2">Could not load scenes: {error}</p>
              <Button size="sm" variant="secondary"
                onclick={() => { error = ''; refresh().catch((e) => (error = e.message)); }}>Retry</Button>
            </div>
          {:else if orderedScenes.length === 0}
            <div class="rounded-lg border border-dashed border-border p-3">
              <div class="flex items-center gap-2 mb-1">
                <Lightbulb class="size-4" />
                <span class="font-medium text-sm">No scenes yet</span>
              </div>
              <p class="text-sm text-muted-foreground">
                Click <span class="font-medium">New story</span> above and generate a script — one scene
                becomes one video, and each scene then walks through Expand, Shots, Storyboard and Render.
              </p>
              <p class="text-sm text-muted-foreground mt-1">
                Tip: add characters and a style first so generated scenes stay consistent —
                先添加角色和风格，生成的场景更一致。
              </p>
              {#if !showGenerator}
                <Button size="sm" class="mt-2" onclick={() => (showGenerator = true)}>
                  <Plus class="size-4 mr-1" />New story
                </Button>
              {/if}
            </div>
          {:else}
            {#each orderedScenes as s (s.id)}
              <SceneListItem
                scene={s}
                selected={s.id === selectedId}
                statusLine={statusLine(s)}
                accentDot={accentDot(s)}
                steps={sceneSteps(s).map((st) => ({ key: st.key, label: st.label, done: st.done }))}
                storyboard={storyboards[s.id] ?? null}
                onselect={() => selectScene(s.id)}
              />
            {/each}
          {/if}
        </div>
      </div>
    </Pane>

    <Handle withHandle />

    <!-- RIGHT: selected scene detail (the workspace) -->
    <Pane defaultSize={72} minSize={40} class="min-w-0">
      <div class="h-full overflow-y-auto">
        {#if !loaded}
          <div class="p-5 space-y-4">
            <div class="flex items-start gap-4">
              <Skeleton class="size-16 shrink-0 rounded-lg" />
              <div class="flex-1 space-y-2">
                <Skeleton class="h-5 w-56" />
                <Skeleton class="h-6 w-80" />
              </div>
              <Skeleton class="h-8 w-28" />
            </div>
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-40 w-full" />
          </div>
        {:else if selectedScene}
          {#key selectedScene.id}
            <SceneDetail
              s={selectedScene}
              steps={sceneSteps(selectedScene)}
              {characters}
              {style}
              {busy}
              {opBusy}
              storyboard={storyboards[selectedScene.id] ?? null}
              shots={shotsByScene[selectedScene.id] ?? []}
              bind:castSelection
              bind:sceneRefine
              bind:shotRefine
              bind:autoProps
              bind:assetInstr
              bind:assetMax
              bind:generatedAssets
              bind:assetPlans
              bind:planSelected
              onExpand={expandScene}
              onSave={saveScene}
              onRefineScene={refineScene}
              onToggleCast={toggleCast}
              onGenerateShots={generateShots}
              onSaveShot={saveShot}
              onRefineShot={refineShot}
              onDeleteShot={deleteShot}
              onSuggestAssets={suggestAssets}
              onGenerateAssets={generateAssets}
              onGenerateSelectedAssets={generateSelectedAssets}
              onGenerateStoryboard={generateStoryboard}
              onRenderScene={renderScene}
              onDelete={(s: any) => (deleteTarget = s)}
              onLightbox={(a: any) => (lightbox = a)}
            />
          {/key}
        {:else}
          <div class="flex h-full flex-col items-center justify-center text-center text-muted-foreground p-8">
            <ListVideo class="size-10 mb-3 opacity-40" />
            <p class="text-sm">Select or create a scene</p>
            <p class="text-xs mt-1 max-w-xs">
              Pick a scene from the list to work on it, or click <span class="font-medium">New story</span> to generate one.
            </p>
          </div>
        {/if}
      </div>
    </Pane>
  </PaneGroup>
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
