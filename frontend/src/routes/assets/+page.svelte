<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, patch, del, upload, mediaUrl, isImage, isVideo } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import * as Dialog from '$lib/components/ui/dialog';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import { toast } from 'svelte-sonner';
  import { Upload, Tag, Palette, Wand2, Pin, Trash2, X } from '@lucide/svelte';

  let assets: any[] = $state([]);
  let characters: any[] = $state([]);
  let error = $state('');
  let busy = $state(false);
  let search = $state('');

  // --- Project style guide ---
  let style: any = $state(null);
  let styleLoaded = $state(false);
  let styleEditing = $state(false); // "Create manually" with no row yet
  let styleBusy = $state('');
  let styleForm = $state({ style_prompt: '', palette: '', lighting: '', audience: '', tone: '' });
  let reingestOpen = $state(false);
  let deleteTarget: any = $state(null);

  function seedStyleForm(s: any) {
    styleForm = {
      style_prompt: s?.style_prompt ?? '',
      palette: s?.palette ?? '',
      lighting: s?.lighting ?? '',
      audience: s?.audience ?? '',
      tone: s?.tone ?? ''
    };
  }

  async function loadStyle() {
    try {
      style = await get('/style');
      if (style) seedStyleForm(style);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      styleLoaded = true;
    }
  }

  async function ingestStyle() {
    styleBusy = 'ingest';
    reingestOpen = false;
    try {
      await runBackgroundOp('/style/ingest', undefined, {
        label: 'Style ingest',
        onDone: async () => {
          styleBusy = '';
          await loadStyle(); // reloads the panel and reseeds the form
          styleEditing = false;
        },
        onFail: () => (styleBusy = '')
      });
    } catch (e: any) {
      styleBusy = '';
      toast.error(e.message);
    }
  }

  async function saveStyle() {
    styleBusy = 'save';
    try {
      style = await patch('/style', styleForm);
      styleEditing = false;
      toast.success('Style saved.');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      styleBusy = '';
    }
  }

  const styleRefs = $derived(
    ((style?.reference_asset_ids_json ?? []) as string[]).map(
      (id) => assets.find((a) => a.id === id) ?? { id, name: id, file_path: null }
    )
  );

  async function patchRefs(ids: string[], doneMsg: string) {
    styleBusy = 'refs';
    try {
      style = await patch('/style', { reference_asset_ids: ids });
      toast.success(doneMsg);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      styleBusy = '';
    }
  }

  function addStyleRef(asset: any) {
    const cur: string[] = style?.reference_asset_ids_json ?? [];
    if (cur.includes(asset.id)) {
      toast.info('Already a style reference.');
      return;
    }
    patchRefs([...cur, asset.id], `"${asset.name || asset.id}" pinned as style reference.`);
  }

  const removeStyleRef = (id: string) =>
    patchRefs(
      ((style?.reference_asset_ids_json ?? []) as string[]).filter((r) => r !== id),
      'Style reference removed.'
    );

  async function confirmDeleteAsset() {
    const a = deleteTarget;
    if (!a) return;
    busy = true;
    try {
      const r = await del(`/assets/${a.id}`);
      deleteTarget = null;
      toast.success(`Asset deleted (detached from ${r.detached_from} place${r.detached_from === 1 ? '' : 's'}).`);
      await Promise.all([refresh(), loadStyle()]);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = false;
    }
  }

  let file: FileList | null = $state(null);
  let assetType = $state('');
  let characterId = $state('');

  const ASSET_TYPES = ['', 'character_reference', 'location', 'prop', 'video_reference', 'audio_reference', 'voice'];

  async function refresh() {
    [assets, characters] = await Promise.all([get('/assets'), get('/characters')]);
  }
  onMount(() => {
    refresh().catch((e) => (error = e.message));
    loadStyle();
  });

  async function doUpload(e: Event) {
    e.preventDefault();
    if (!file?.length) return;
    busy = true;
    error = '';
    try {
      const form = new FormData();
      form.append('file', file[0]);
      if (assetType) form.append('asset_type', assetType);
      if (characterId) form.append('character_id', characterId);
      await upload('/assets/upload', form);
      file = null;
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = false;
    }
  }

  async function recognise(asset: any) {
    const description = prompt(`Describe "${asset.name}" for AI tagging:`, asset.description || '');
    if (description === null) return;
    busy = true;
    try {
      await post(`/assets/${asset.id}/recognise`, { description });
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = false;
    }
  }

  let filtered = $derived(search
    ? assets.filter((a) =>
        [a.name, a.type, a.description, ...(a.tags_json ?? [])]
          .join(' ')
          .toLowerCase()
          .includes(search.toLowerCase())
      )
    : assets);
</script>

<div class="p-6">
  <h1 class="text-lg font-semibold mb-4">Assets</h1>

  <Card class="mb-4">
    <CardContent class="p-4">
      <div class="flex items-center gap-2 mb-1">
        <Palette class="size-4" />
        <span class="font-medium text-sm">Project style</span>
      </div>
      <p class="text-xs text-muted-foreground mb-3">
        Applied automatically to all asset, storyboard and video generation.
      </p>

      {#if !styleLoaded}
        <p class="text-sm text-muted-foreground">Loading…</p>
      {:else if !style && !styleEditing}
        <p class="text-sm text-muted-foreground mb-2">No style guide yet</p>
        <div class="flex gap-2">
          <Button size="sm" disabled={styleBusy === 'ingest'} onclick={ingestStyle}>
            <Wand2 class="size-3 mr-1" />{styleBusy === 'ingest' ? 'Deriving…' : 'Ingest from story'}
          </Button>
          <Button variant="outline" size="sm" onclick={() => (styleEditing = true)}>
            Create manually
          </Button>
        </div>
      {:else}
        <div class="grid gap-3">
          <div class="grid gap-1.5">
            <Label for="style-prompt">Style prompt</Label>
            <Textarea id="style-prompt" rows={3} bind:value={styleForm.style_prompt}
              placeholder="e.g. warm watercolor children's book illustration, soft edges…" />
          </div>
          <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div class="grid gap-1.5">
              <Label for="style-palette">Palette</Label>
              <Input id="style-palette" bind:value={styleForm.palette} />
            </div>
            <div class="grid gap-1.5">
              <Label for="style-lighting">Lighting</Label>
              <Input id="style-lighting" bind:value={styleForm.lighting} />
            </div>
            <div class="grid gap-1.5">
              <Label for="style-audience">Audience</Label>
              <Input id="style-audience" bind:value={styleForm.audience} />
            </div>
            <div class="grid gap-1.5">
              <Label for="style-tone">Tone</Label>
              <Input id="style-tone" bind:value={styleForm.tone} />
            </div>
          </div>

          {#if styleRefs.length}
            <div>
              <div class="text-xs text-muted-foreground mb-1">Style reference images</div>
              <div class="flex flex-wrap gap-2">
                {#each styleRefs as ref (ref.id)}
                  <div class="relative w-[72px]">
                    {#if mediaUrl(ref.file_path)}
                      <img class="w-full aspect-square object-cover rounded-md border border-border"
                        src={mediaUrl(ref.file_path)} alt={ref.name} title={ref.name} loading="lazy" />
                    {:else}
                      <div class="w-full aspect-square rounded-md border border-border bg-muted grid place-items-center text-[10px] text-muted-foreground p-1 text-center"
                        title={ref.name}>{ref.name}</div>
                    {/if}
                    <button type="button" aria-label="Remove style reference"
                      class="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full bg-background border border-border shadow hover:bg-muted"
                      disabled={styleBusy === 'refs'} onclick={() => removeStyleRef(ref.id)}>
                      <X class="size-3" />
                    </button>
                  </div>
                {/each}
              </div>
            </div>
          {:else}
            <p class="text-xs text-muted-foreground">
              No style reference images — pin image assets below with the pin button.
            </p>
          {/if}

          <div class="flex gap-2">
            <Button size="sm" disabled={!!styleBusy} onclick={saveStyle}>
              {styleBusy === 'save' ? 'Saving…' : 'Save'}
            </Button>
            <Button variant="outline" size="sm" disabled={!!styleBusy} onclick={() => (reingestOpen = true)}>
              <Wand2 class="size-3 mr-1" />{styleBusy === 'ingest' ? 'Deriving…' : 'Re-ingest from story'}
            </Button>
          </div>
        </div>
      {/if}
    </CardContent>
  </Card>

  <form class="mb-4 rounded-lg border border-border bg-card p-4" onsubmit={doUpload}>
    <div class="flex flex-wrap gap-4 items-end">
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="file">File</label>
        <input id="file" type="file" bind:files={file}
          class="block w-full text-sm rounded-md border border-input bg-background px-2 py-1.5" />
      </div>
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="type">Type (auto if blank)</label>
        <select id="type" bind:value={assetType}
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
          {#each ASSET_TYPES as t}<option value={t}>{t || 'auto'}</option>{/each}
        </select>
      </div>
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="char">Link to character</label>
        <select id="char" bind:value={characterId}
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
          <option value="">none</option>
          {#each characters as c}<option value={c.id}>{c.name}</option>{/each}
        </select>
      </div>
      <div>
        <Button type="submit" disabled={busy || !file?.length} size="sm">
          <Upload class="size-4 mr-1" />Upload
        </Button>
      </div>
    </div>
  </form>

  <input
    placeholder="Search by name, tag, type…"
    bind:value={search}
    class="mb-4 w-full max-w-sm rounded-md border border-input bg-background px-2 py-1.5 text-sm"
  />

  {#if !assets.length}
    <p class="text-sm text-muted-foreground">
      Generated props, reference sheets and rendered videos will appear here.
    </p>
  {/if}

  <div class="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-4">
    {#each filtered.slice().reverse() as asset (asset.id)}
      <Card>
        <CardContent class="p-3">
          {#if asset.type === 'video' || isVideo?.(asset.file_path)}
            <!-- svelte-ignore a11y_media_has_caption -->
            <video controls preload="metadata" src={mediaUrl(asset.file_path)}
              class="w-full rounded-md bg-black mb-2 aspect-video object-contain"></video>
          {:else if asset.file_path && mediaUrl(asset.file_path)}
            <img class="w-full aspect-square object-cover rounded-md bg-muted mb-2"
              src={mediaUrl(asset.file_path)} alt={asset.name} loading="lazy" />
          {:else}
            <div class="w-full aspect-square rounded-md bg-muted mb-2 grid place-items-center text-muted-foreground text-2xl">
              {asset.type?.includes('video') ? 'V' : 'F'}
            </div>
          {/if}
          <div class="font-medium text-sm mb-0.5">{asset.name || asset.id}</div>
          <div class="text-xs text-muted-foreground mb-1">{asset.type} · {asset.id}</div>
          {#if asset.description}
            <div class="text-xs text-muted-foreground mb-1">{asset.description.slice(0, 90)}</div>
          {/if}
          <div class="flex flex-wrap gap-1 mb-2">
            {#if asset.metadata_json?.render_job_id}
              <Badge variant="secondary">From render</Badge>
            {/if}
            {#if asset.metadata_json?.captioned_path}
              <Badge>captioned</Badge>
            {/if}
            {#each asset.tags_json ?? [] as tag}
              <Badge variant="outline">{tag}</Badge>
            {/each}
          </div>
          <div class="flex items-center gap-1">
            <Button variant="outline" size="sm" disabled={busy} onclick={() => recognise(asset)}>
              <Tag class="size-3 mr-1" />AI tag
            </Button>
            {#if isImage(asset.file_path)}
              <Button variant="ghost" size="icon" class="size-8" title="Use as style ref"
                disabled={busy || !!styleBusy} onclick={() => addStyleRef(asset)}>
                <Pin class="size-3.5" />
              </Button>
            {/if}
            <Button variant="ghost" size="icon" class="size-8 text-destructive hover:text-destructive"
              title="Delete asset" disabled={busy} onclick={() => (deleteTarget = asset)}>
              <Trash2 class="size-3.5" />
            </Button>
          </div>
        </CardContent>
      </Card>
    {/each}
  </div>
</div>

<Dialog.Root open={reingestOpen} onOpenChange={(open) => !open && (reingestOpen = false)}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>Re-ingest style from story?</Dialog.Title>
      <Dialog.Description>
        Overwrite the derived style fields from the current story?
        The name and reference images are kept.
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" size="sm" onclick={() => (reingestOpen = false)}>Cancel</Button>
      <Button size="sm" disabled={!!styleBusy} onclick={ingestStyle}>
        <Wand2 class="size-3 mr-1" />Re-ingest
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root open={deleteTarget !== null} onOpenChange={(open) => !open && (deleteTarget = null)}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>Delete asset?</Dialog.Title>
      <Dialog.Description>
        "{deleteTarget?.name || deleteTarget?.id}" will be deleted and detached from
        scenes, shots, characters and the style guide.
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" size="sm" onclick={() => (deleteTarget = null)}>Cancel</Button>
      <Button variant="destructive" size="sm" disabled={busy} onclick={confirmDeleteAsset}>
        <Trash2 class="size-3 mr-1" />{busy ? 'Deleting…' : 'Delete'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
