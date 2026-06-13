<script lang="ts">
  import { onMount } from 'svelte';
  import { beforeNavigate } from '$app/navigation';
  import { get, patch, post, put, del, mediaUrl } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { Button } from '$lib/components/ui/button';
  import * as Dialog from '$lib/components/ui/dialog';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { PaneGroup, Pane, Handle } from '$lib/components/ui/resizable';
  import { toast } from 'svelte-sonner';
  import { Wand2, LayoutGrid, Video, Images, Trash2, Lightbulb, Clock, Plus, Clapperboard, ListVideo, Search, X, AlertTriangle } from '@lucide/svelte';
  import SceneListItem from '$lib/scenes/SceneListItem.svelte';
  import SceneDetail from '$lib/scenes/SceneDetail.svelte';

  let scenes: any[] = $state([]);
  let characters: any[] = $state([]);
  let shotsByScene: Record<string, any[]> = $state({});
  let storyboards: Record<string, any> = $state({});
  let renderedScenes: Record<string, boolean> = $state({});
  let error = $state('');
  // Per-key busy gating: only the keys of in-flight actions are true, so
  // unrelated buttons stay live while one op runs (replaces the old single lock).
  let busy: Record<string, boolean> = $state({});
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
  // Destructive-confirm: { title, message, run } shown in a dialog when content
  // would be overwritten (regenerate shots / re-expand / regenerate storyboard).
  let confirmAction: { title: string; message: string; run: () => void } | null = $state(null);

  // ── Dirty tracking ────────────────────────────────────────────────────────
  // Baseline = the last server-loaded value of each editable field, keyed by
  // scene/shot id. A row is "dirty" when its live (bound) value differs. We
  // preserve dirty edits across refresh() (so an op elsewhere never silently
  // discards typing) and guard navigation while anything is unsaved.
  const SCENE_FIELDS = ['title', 'summary', 'duration', 'aspect_ratio'] as const;
  const SHOT_FIELDS = ['prompt', 'duration', 'camera', 'movement'] as const;
  let sceneBaseline: Record<string, Record<string, any>> = $state({});
  let shotBaseline: Record<string, Record<string, any>> = $state({});

  function snapScene(s: any): Record<string, any> {
    const out: Record<string, any> = {};
    for (const f of SCENE_FIELDS) out[f] = s[f];
    return out;
  }
  function snapShot(sh: any): Record<string, any> {
    const out: Record<string, any> = {};
    for (const f of SHOT_FIELDS) out[f] = sh[f];
    return out;
  }
  function sceneDirty(s: any): boolean {
    const base = sceneBaseline[s.id];
    if (!base) return false;
    return SCENE_FIELDS.some((f) => s[f] !== base[f]);
  }
  function shotDirty(sh: any): boolean {
    const base = shotBaseline[sh.id];
    if (!base) return false;
    return SHOT_FIELDS.some((f) => sh[f] !== base[f]);
  }
  // Any unsaved scene OR shot edit anywhere — drives the nav/unload guard.
  const dirtyCount = $derived(
    scenes.filter((s) => sceneDirty(s)).length +
      Object.values(shotsByScene)
        .flat()
        .filter((sh: any) => shotDirty(sh)).length
  );

  // Master–detail selection (in-memory). The "New story" generator opens in a
  // dedicated dialog; null selectedId = empty workspace.
  let selectedId: string | null = $state(null);
  let showGenerator = $state(false);

  // ── List UX: search + stage filter + keyboard nav ──────────────────────────
  let search = $state('');
  // '' = all; otherwise the furthest-stage label we filter on.
  let stageFilter = $state<'' | 'new' | 'expanded' | 'shots' | 'storyboard' | 'rendered'>('');

  // List order: newest-activity first (matches the old reversed render).
  const orderedScenes = $derived(scenes.slice().reverse());

  function stageOf(s: any): 'new' | 'expanded' | 'shots' | 'storyboard' | 'rendered' {
    if (renderedScenes[s.id]) return 'rendered';
    if (storyboards[s.id]) return 'storyboard';
    if ((shotsByScene[s.id]?.length ?? 0) > 0) return 'shots';
    if (isExpanded(s)) return 'expanded';
    return 'new';
  }

  const visibleScenes = $derived(
    orderedScenes.filter((s) => {
      if (stageFilter && stageOf(s) !== stageFilter) return false;
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return (
        (s.title ?? '').toLowerCase().includes(q) ||
        (s.summary ?? '').toLowerCase().includes(q)
      );
    })
  );

  const selectedScene = $derived(scenes.find((s) => s.id === selectedId) ?? null);

  // Keep selection valid as scenes change: default to first visible, fall back
  // on delete. Never auto-switch away from a still-present selection.
  $effect(() => {
    if (!loaded) return;
    if (selectedId !== null && scenes.some((s) => s.id === selectedId)) return;
    selectedId = visibleScenes.length ? visibleScenes[0].id : null;
  });

  // ── Expand detection ────────────────────────────────────────────────────────
  // A stage is "done" if it OR any later stage is done. Expansion can't be told
  // apart from a stub by scene_json key-count alone (manual scenes, partial
  // specs), so the presence of shots / a storyboard / a render IMPLIES expanded.
  function hasExpandJson(s: any): boolean {
    return !!(s.scene_json && Object.keys(s.scene_json).length > 1);
  }
  function isExpanded(s: any): boolean {
    return (
      hasExpandJson(s) ||
      (shotsByScene[s.id]?.length ?? 0) > 0 ||
      !!storyboards[s.id] ||
      !!renderedScenes[s.id]
    );
  }

  // Merge fresh server rows over the previous state WITHOUT clobbering unsaved
  // edits: a dirty scene/shot keeps its in-memory field values; everything else
  // (and all non-editable fields) take the server's values, and the baseline is
  // (re)set to the server snapshot so saved rows go clean.
  function mergeScenes(fresh: any[]) {
    const prevById = new Map(scenes.map((s) => [s.id, s]));
    const baseline: Record<string, Record<string, any>> = {};
    const merged = fresh.map((srv) => {
      // Snapshot the baseline from the UNTOUCHED server row first, so it always
      // reflects the latest server field values — never the kept edits below.
      baseline[srv.id] = snapScene(srv);
      const prev = prevById.get(srv.id);
      if (prev && sceneDirty(prev)) {
        // keep edits; the baseline (captured above) stays at the server snapshot
        // so the row remains dirty until the user actually Saves.
        for (const f of SCENE_FIELDS) srv[f] = prev[f];
      }
      return srv;
    });
    sceneBaseline = baseline;
    return merged;
  }
  function mergeShots(sceneId: string, fresh: any[]) {
    const prevById = new Map((shotsByScene[sceneId] ?? []).map((s) => [s.id, s]));
    const merged = fresh.map((srv) => {
      // Snapshot the baseline from the UNTOUCHED server row first (before the
      // dirty-keep loop overwrites srv), so a kept edit still reads as dirty.
      shotBaseline[srv.id] = snapShot(srv);
      const prev = prevById.get(srv.id);
      if (prev && shotDirty(prev)) {
        for (const f of SHOT_FIELDS) srv[f] = prev[f];
      }
      return srv;
    });
    shotBaseline = shotBaseline; // re-assign so dirty derivations re-run
    return merged;
  }

  async function refresh() {
    const [freshScenes, chars] = await Promise.all([get('/scenes'), get('/characters')]);
    characters = chars;
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
    scenes = mergeScenes(freshScenes);
    await Promise.all(
      scenes.map(async (s) => {
        // One scene's shots failing must not blank the whole list.
        const fresh = await get(`/scenes/${s.id}/shots`).catch(() => []);
        shotsByScene[s.id] = mergeShots(s.id, fresh);
      })
    );
    shotsByScene = shotsByScene;
  }
  onMount(() => {
    refresh()
      .catch((e) => (error = e.message))
      .finally(() => (loaded = true));
    get('/style').then((s) => (style = s)).catch(() => {});

    const onUnload = (e: BeforeUnloadEvent) => {
      if (dirtyCount > 0) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  });

  beforeNavigate((nav) => {
    if (dirtyCount > 0 && !confirm('You have unsaved scene/shot edits. Leave anyway?'))
      nav.cancel();
  });

  async function run(key: string, fn: () => Promise<unknown>, doneMsg = '') {
    busy[key] = true;
    error = '';
    try {
      await fn();
      await refresh();
      if (doneMsg) toast.success(doneMsg);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy[key] = false;
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

  // Re-expand overwrites the expanded scene + drops its shots → confirm first.
  function expandSceneGuarded(s: any) {
    if (isExpanded(s)) {
      confirmAction = {
        title: 'Re-expand scene?',
        message:
          'Re-expanding rewrites this scene from the cast and may replace its shots. Unsaved edits on this scene will be lost. Continue?',
        run: () => expandScene(s)
      };
    } else {
      expandScene(s);
    }
  }

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
            shotsByScene[s.id] = mergeShots(s.id, await get(`/scenes/${s.id}/shots`));
            shotsByScene = shotsByScene;
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

  // Regenerating replaces every existing shot → confirm when shots exist.
  function generateShotsGuarded(s: any) {
    if ((shotsByScene[s.id]?.length ?? 0) > 0) {
      confirmAction = {
        title: 'Regenerate shots?',
        message:
          'This replaces every existing shot for this scene with a fresh AI breakdown. Unsaved shot edits will be lost. Continue?',
        run: () => generateShots(s)
      };
    } else {
      generateShots(s);
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

  // Regenerating replaces the existing 分镜图 → confirm when one exists.
  function generateStoryboardGuarded(s: any) {
    if (storyboards[s.id]) {
      confirmAction = {
        title: 'Regenerate storyboard?',
        message:
          'This replaces the existing storyboard image for this scene. Continue?',
        run: () => generateStoryboard(s)
      };
    } else {
      generateStoryboard(s);
    }
  }

  const renderScene = (s: any) =>
    run(
      `render-${s.id}`,
      () => post(`/scenes/${s.id}/render`),
      'Render job submitted — track it on the Render page.'
    );

  // Pipeline stepper: one entry per stage, computed from data already loaded.
  // Each stage's "done" uses the later-done rule so the stepper never shows an
  // earlier stage as incomplete once a later one exists.
  function sceneSteps(s: any) {
    const hasShots = (shotsByScene[s.id]?.length ?? 0) > 0;
    const hasStoryboard = !!storyboards[s.id];
    const hasRender = !!renderedScenes[s.id];
    return [
      {
        key: 'expand',
        label: 'Expand',
        icon: Wand2,
        done: isExpanded(s),
        busy: !!busy[`expand-${s.id}`],
        busyLabel: 'Expanding…',
        action: () => expandSceneGuarded(s)
      },
      {
        key: 'shots',
        label: 'Shots',
        icon: LayoutGrid,
        done: hasShots || hasStoryboard || hasRender,
        busy: !!opBusy[`shots-${s.id}`],
        busyLabel: 'Generating shots…',
        action: () => generateShotsGuarded(s)
      },
      {
        key: 'storyboard',
        label: 'Storyboard',
        icon: Images,
        done: hasStoryboard || hasRender,
        busy: !!opBusy[`sb-${s.id}`],
        busyLabel: 'Generating storyboard…',
        action: () => generateStoryboardGuarded(s)
      },
      {
        key: 'render',
        label: 'Render',
        icon: Video,
        done: hasRender,
        busy: !!busy[`render-${s.id}`],
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
    else if (isExpanded(s)) parts.push('Expanded');
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
    busy[`delete-${s.id}`] = true;
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
      busy[`delete-${s.id}`] = false;
    }
  }

  async function deleteShot(scene: any, shot: any) {
    busy[`delete-${shot.id}`] = true;
    try {
      await del(`/shots/${shot.id}`);
      delete shotBaseline[shot.id];
      toast.success('Shot deleted.');
      shotsByScene[scene.id] = mergeShots(scene.id, await get(`/scenes/${scene.id}/shots`));
      shotsByScene = shotsByScene;
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy[`delete-${shot.id}`] = false;
    }
  }

  async function addShot(scene: any) {
    busy[`add-${scene.id}`] = true;
    try {
      await post(`/scenes/${scene.id}/shots`, {});
      toast.success('Shot added.');
      shotsByScene[scene.id] = mergeShots(scene.id, await get(`/scenes/${scene.id}/shots`));
      shotsByScene = shotsByScene;
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy[`add-${scene.id}`] = false;
    }
  }

  // Move a shot up/down by swapping with its neighbour, then persist the order.
  async function moveShot(scene: any, shot: any, dir: -1 | 1) {
    const list = (shotsByScene[scene.id] ?? []).slice();
    const i = list.findIndex((s) => s.id === shot.id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    busy[`reorder-${scene.id}`] = true;
    try {
      const ordered = await put(`/scenes/${scene.id}/shots/order`, {
        ordered_ids: list.map((s) => s.id)
      });
      shotsByScene[scene.id] = mergeShots(scene.id, ordered);
      shotsByScene = shotsByScene;
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy[`reorder-${scene.id}`] = false;
    }
  }

  async function refineScene(s: any) {
    const instruction = (sceneRefine[s.id] ?? '').trim();
    if (!instruction) return;
    busy[`refine-${s.id}`] = true;
    try {
      const r = await post(`/scenes/${s.id}/refine`, { instruction });
      Object.assign(s, r.scene);
      sceneBaseline[s.id] = snapScene(s); // refined values are the new clean baseline
      sceneRefine[s.id] = '';
      toast.success(r.note || 'Refined');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy[`refine-${s.id}`] = false;
    }
  }

  async function refineShot(scene: any, shot: any) {
    const instruction = (shotRefine[scene.id] ?? '').trim();
    if (!instruction) {
      toast.error('Type an instruction in the shot refine box first.');
      return;
    }
    busy[`refine-${shot.id}`] = true;
    try {
      const r = await post(`/shots/${shot.id}/refine`, { instruction });
      Object.assign(shot, r.shot);
      shotBaseline[shot.id] = snapShot(shot);
      toast.success(r.note || 'Refined');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy[`refine-${shot.id}`] = false;
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
            shotsByScene[s.id] = mergeShots(s.id, await get(`/scenes/${s.id}/shots`));
            shotsByScene = shotsByScene;
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
    busy[`plan-${s.id}`] = true;
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
      busy[`plan-${s.id}`] = false;
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

  // Arrow-key navigation in the left list (when not typing in a field).
  function listKeydown(e: KeyboardEvent) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const list = visibleScenes;
    if (!list.length) return;
    const i = list.findIndex((s) => s.id === selectedId);
    const next = e.key === 'ArrowDown' ? Math.min(list.length - 1, i + 1) : Math.max(0, i - 1);
    if (next !== i || i === -1) {
      e.preventDefault();
      selectScene(list[next === -1 ? 0 : next].id);
    }
  }

  const STAGE_FILTERS: { value: typeof stageFilter; label: string }[] = [
    { value: '', label: 'All' },
    { value: 'new', label: 'New' },
    { value: 'expanded', label: 'Expanded' },
    { value: 'shots', label: 'Shots' },
    { value: 'storyboard', label: 'Storyboard' },
    { value: 'rendered', label: 'Rendered' }
  ];
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
        <!-- New story affordance + search + stage filter -->
        <div class="shrink-0 border-b border-border p-3 space-y-2.5">
          <Button variant="default" size="sm" class="w-full justify-start"
            onclick={() => (showGenerator = true)}>
            <Plus class="size-4 mr-1.5" />New story
          </Button>

          <div class="relative">
            <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground/70 pointer-events-none" />
            <input
              bind:value={search}
              placeholder="Search scenes…"
              aria-label="Search scenes"
              class="w-full rounded-md border border-input bg-background pl-8 pr-8 py-1.5 text-sm" />
            {#if search}
              <button type="button" title="Clear search"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/70 hover:text-foreground"
                onclick={() => (search = '')}>
                <X class="size-3.5" />
              </button>
            {/if}
          </div>

          <div class="flex flex-wrap gap-1">
            {#each STAGE_FILTERS as f (f.value)}
              <button type="button"
                class="rounded-full px-2 py-0.5 text-[11px] transition-colors
                  {stageFilter === f.value
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground hover:bg-accent'}"
                onclick={() => (stageFilter = f.value)}>
                {f.label}
              </button>
            {/each}
          </div>
        </div>

        <!-- The list itself -->
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <div class="min-h-0 flex-1 overflow-y-auto p-2 space-y-1.5 focus:outline-none"
          tabindex="0" role="listbox" aria-label="Scenes" onkeydown={listKeydown}>
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
              <Button size="sm" class="mt-2" onclick={() => (showGenerator = true)}>
                <Plus class="size-4 mr-1" />New story
              </Button>
            </div>
          {:else if visibleScenes.length === 0}
            <div class="rounded-lg border border-dashed border-border p-3 text-center">
              <p class="text-sm text-muted-foreground">No scenes match this search/filter.</p>
              <Button size="sm" variant="secondary" class="mt-2"
                onclick={() => { search = ''; stageFilter = ''; }}>Clear filters</Button>
            </div>
          {:else}
            {#each visibleScenes as s (s.id)}
              <SceneListItem
                scene={s}
                selected={s.id === selectedId}
                statusLine={statusLine(s)}
                accentDot={accentDot(s)}
                dirty={sceneDirty(s) || (shotsByScene[s.id] ?? []).some((sh: any) => shotDirty(sh))}
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
              sceneDirty={sceneDirty(selectedScene)}
              shotDirty={(sh: any) => shotDirty(sh)}
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
              onExpand={expandSceneGuarded}
              onSave={saveScene}
              onRefineScene={refineScene}
              onToggleCast={toggleCast}
              onGenerateShots={generateShotsGuarded}
              onAddShot={addShot}
              onMoveShot={moveShot}
              onSaveShot={saveShot}
              onRefineShot={refineShot}
              onDeleteShot={deleteShot}
              onSuggestAssets={suggestAssets}
              onGenerateAssets={generateAssets}
              onGenerateSelectedAssets={generateSelectedAssets}
              onGenerateStoryboard={generateStoryboardGuarded}
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

<!-- New story generator: dedicated dialog with room to think -->
<Dialog.Root open={showGenerator} onOpenChange={(open) => (showGenerator = open)}>
  <Dialog.Content class="max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2">
        <span class="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Clapperboard class="size-4" />
        </span>
        Start a new story
      </Dialog.Title>
      <Dialog.Description>AI writes a script and splits it into scenes. 1 scene = 1 video.</Dialog.Description>
    </Dialog.Header>
    <form onsubmit={generateScript} class="space-y-3">
      <div>
        <label class="block text-xs text-muted-foreground mb-1" for="idea">Story idea</label>
        <textarea id="idea" bind:value={idea}
          placeholder="e.g. A short video about a kid learning to read…"
          class="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm min-h-[120px] resize-y"></textarea>
      </div>
      <div class="flex flex-wrap gap-3 items-end">
        <div class="min-w-[120px] flex-1">
          <label class="block text-xs text-muted-foreground mb-1" for="dur">Target duration</label>
          <div class="relative">
            <Clock class="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground/70 pointer-events-none" />
            <input id="dur" type="number" bind:value={targetDuration} min="3" placeholder="auto"
              class="w-full rounded-md border border-input bg-background pl-8 pr-8 py-1.5 text-sm" />
            <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground/70 pointer-events-none">s</span>
          </div>
        </div>
        <div class="min-w-[100px] flex-1">
          <label class="block text-xs text-muted-foreground mb-1" for="scene-count">Scenes</label>
          <input id="scene-count" type="number" bind:value={sceneCount} min="1" max="20" placeholder="auto"
            class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
        </div>
      </div>
      <p class="text-[11px] text-muted-foreground">
        Tip: add characters and a style first so generated scenes stay consistent —
        先添加角色和风格，生成的场景更一致。
      </p>
      <Dialog.Footer>
        <Button type="button" variant="outline" size="sm" onclick={() => (showGenerator = false)}>Cancel</Button>
        <Button type="submit" disabled={busy['script'] || !idea} size="sm">
          <Wand2 class="size-4 mr-1" />{busy['script'] ? 'Generating…' : 'Generate script'}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

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

<!-- Destructive-action confirm (regenerate shots / re-expand / regenerate storyboard) -->
<Dialog.Root open={confirmAction !== null} onOpenChange={(open) => !open && (confirmAction = null)}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2">
        <AlertTriangle class="size-4 text-amber-500" />{confirmAction?.title}
      </Dialog.Title>
      <Dialog.Description>{confirmAction?.message}</Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" size="sm" onclick={() => (confirmAction = null)}>Cancel</Button>
      <Button size="sm" onclick={() => { const a = confirmAction; confirmAction = null; a?.run(); }}>
        Continue
      </Button>
    </Dialog.Footer>
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
      <Button variant="destructive" size="sm" disabled={busy[`delete-${deleteTarget?.id}`]} onclick={confirmDeleteScene}>
        <Trash2 class="size-3 mr-1" />{busy[`delete-${deleteTarget?.id}`] ? 'Deleting…' : 'Delete'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
