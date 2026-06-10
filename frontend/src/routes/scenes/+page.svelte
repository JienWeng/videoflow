<script lang="ts">
  import { onMount } from 'svelte';
  import { get, patch, post, del, mediaUrl } from '$lib/api';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import * as Dialog from '$lib/components/ui/dialog';
  import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '$lib/components/ui/table';
  import { toast } from 'svelte-sonner';
  import { Wand2, Save, Film, LayoutGrid, Video, Images, Trash2, Sparkles, ImagePlus } from '@lucide/svelte';

  let scenes: any[] = $state([]);
  let characters: any[] = $state([]);
  let shotsByScene: Record<string, any[]> = $state({});
  let storyboards: Record<string, any> = $state({});
  let error = $state('');
  let busy = $state('');
  let ok = $state('');

  let idea = $state('');
  let targetDuration: number | '' = $state('');
  let castSelection: Record<string, string[]> = $state({});
  let deleteTarget: any = $state(null);
  let sceneRefine: Record<string, string> = $state({});
  let shotRefine: Record<string, string> = $state({});
  let assetInstr: Record<string, string> = $state({});
  let assetMax: Record<string, number> = $state({});
  let generatedAssets: Record<string, any[]> = $state({});

  async function refresh() {
    [scenes, characters] = await Promise.all([get('/scenes'), get('/characters')]);
    const allAssets = await get('/assets');
    storyboards = {};
    for (const a of allAssets) {
      const sid = a.metadata_json?.scene_id;
      if (a.type === 'storyboard' && sid) storyboards[sid] = a;
    }
    await Promise.all(
      scenes.map(async (s) => {
        shotsByScene[s.id] = await get(`/scenes/${s.id}/shots`);
      })
    );
    shotsByScene = shotsByScene;
  }
  onMount(() => refresh().catch((e) => (error = e.message)));

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
      () => post('/scripts/generate', { idea, target_duration: targetDuration || null }),
      'Script generated — scenes created below.'
    );
  };

  const expandScene = (s: any) =>
    run(`expand-${s.id}`, () =>
      post(`/scenes/${s.id}/generate`, { character_ids: castSelection[s.id] ?? [] })
    );

  const generateShots = (s: any) =>
    run(`shots-${s.id}`, () => post(`/scenes/${s.id}/shots/generate`));

  const generateStoryboard = (s: any) =>
    run(`sb-${s.id}`, () => post(`/scenes/${s.id}/storyboard`), 'Storyboard generated.');

  const renderScene = (s: any) =>
    run(
      `render-${s.id}`,
      () => post(`/scenes/${s.id}/render`),
      'Render job submitted — track it on the Render page.'
    );

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

  async function generateAssets(s: any) {
    busy = `assets-${s.id}`;
    try {
      const created = await post(`/scenes/${s.id}/assets/generate`, {
        instruction: (assetInstr[s.id] ?? '').trim(),
        max_assets: assetMax[s.id] ?? 4
      });
      generatedAssets[s.id] = created;
      toast.success(`Generated ${created.length} asset${created.length === 1 ? '' : 's'}.`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
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
  <h1 class="text-lg font-semibold mb-4">Scenes</h1>

  <form class="mb-4 rounded-lg border border-border bg-card p-4" onsubmit={generateScript}>
    <label class="block text-xs text-muted-foreground mb-1" for="idea">Story idea → script + scenes</label>
    <textarea id="idea" bind:value={idea}
      placeholder="e.g. A short video about a kid learning to read..."
      class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm min-h-[70px] resize-y mb-2"></textarea>
    <div class="flex flex-wrap gap-4 items-end">
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="dur">Target duration (s, optional)</label>
        <input id="dur" type="number" bind:value={targetDuration} min="3"
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
      </div>
      <div>
        <Button type="submit" disabled={busy === 'script' || !idea} size="sm">
          <Wand2 class="size-4 mr-1" />Generate script
        </Button>
      </div>
    </div>
  </form>

  {#each scenes.slice().reverse() as s (s.id)}
    <Card class="mb-4">
      <CardContent class="p-4">
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
          <div class="flex gap-1">
            <Button variant="secondary" size="sm" disabled={!!busy} onclick={() => saveScene(s)}>
              <Save class="size-3 mr-1" />{busy === `save-${s.id}` ? 'Saving…' : 'Save scene'}
            </Button>
            <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive"
              disabled={!!busy} onclick={() => (deleteTarget = s)}>
              <Trash2 class="size-3 mr-1" />Delete
            </Button>
          </div>
        </div>

        <label class="block text-xs text-muted-foreground mb-1" for="sum-{s.id}">
          Summary <span class="opacity-50">({s.id})</span>
        </label>
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
        <div class="flex flex-wrap gap-3 mb-3">
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

        <div class="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={!!busy} onclick={() => expandScene(s)}>
            <Wand2 class="size-3 mr-1" />{busy === `expand-${s.id}` ? 'Expanding…' : '1. Expand scene (AI)'}
          </Button>
          <Button variant="outline" size="sm" disabled={!!busy} onclick={() => generateShots(s)}>
            <LayoutGrid class="size-3 mr-1" />{busy === `shots-${s.id}` ? 'Generating…' : '2. Generate shots (AI)'}
          </Button>
          <Button variant="outline" size="sm" disabled={!!busy || !(shotsByScene[s.id]?.length)} onclick={() => generateStoryboard(s)}>
            <Images class="size-3 mr-1" />{busy === `sb-${s.id}` ? 'Generating…' : '3. Generate storyboard (ERNIE)'}
          </Button>
          <Button size="sm" disabled={!!busy || !(shotsByScene[s.id]?.length)} onclick={() => renderScene(s)}>
            <Video class="size-3 mr-1" />{busy === `render-${s.id}` ? 'Submitting…' : '4. Render scene (Kling)'}
          </Button>
        </div>

        {#if shotsByScene[s.id]?.length}
          <div class="mt-3 flex gap-2 items-center">
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
                      <textarea class="w-full rounded border border-input bg-background px-2 py-1 text-xs min-h-[46px] resize-y"
                        bind:value={shot.prompt}></textarea>
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
        {/if}

        {#if storyboards[s.id]}
          <div class="mt-3">
            <div class="text-sm font-medium mb-1">Storyboard</div>
            <img class="max-w-[420px] w-full rounded-lg" src={mediaUrl(storyboards[s.id].file_path)} alt="Storyboard" loading="lazy" />
          </div>
        {/if}

        <div class="mt-3 border-t border-border pt-3">
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
            <Button variant="outline" size="sm" disabled={!!busy} onclick={() => generateAssets(s)}>
              <ImagePlus class="size-3 mr-1" />{busy === `assets-${s.id}` ? 'Generating…' : 'Generate assets'}
            </Button>
          </div>
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
      </CardContent>
    </Card>
  {/each}
</div>

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
