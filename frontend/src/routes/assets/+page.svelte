<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, patch, del, upload, mediaUrl, isImage, isVideo } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import * as Dialog from '$lib/components/ui/dialog';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import { toast } from 'svelte-sonner';
  import { Upload, Palette, Wand2, Pin, Trash2, X, Sparkles, Maximize2 } from '@lucide/svelte';

  const isAudio = (path?: string | null) => !!path && /\.(mp3|m4a|aac|wav|ogg|flac|opus)$/i.test(path);

  let assets: any[] = $state([]);
  let characters: any[] = $state([]);
  let error = $state('');
  let busy = $state(false);
  let search = $state('');
  let loaded = $state(false);

  // canonical asset vocabulary — fetched from the backend so the upload dropdown
  // and the type filter never drift from the AssetType enum. Falls back to the
  // known set if the endpoint is unavailable.
  let canonicalTypes: string[] = $state([
    'prop',
    'background',
    'character_reference',
    'storyboard',
    'video',
    'effect',
    'tool',
    'other'
  ]);

  // --- filter + sort ---
  let typeFilter = $state(''); // '' = all
  let sortBy = $state('newest'); // newest | oldest | name | type

  // --- Project style guide ---
  let style: any = $state(null);
  let styleLoaded = $state(false);
  let styleEditing = $state(false); // "Create manually" with no row yet
  let styleBusy = $state('');
  let styleForm = $state({ style_prompt: '', palette: '', lighting: '', audience: '', tone: '' });
  let reingestOpen = $state(false);
  let deleteTarget: any = $state(null);
  // Ingest derives the style FROM the story — gate it until one exists.
  let hasStory = $state(true);

  // --- lightbox / detail ---
  let detail: any = $state(null);

  // --- describe with AI ---
  let describeTarget: any = $state(null);
  let describeText = $state('');
  let describeBusy = $state(false);

  async function loadStoryPresence() {
    try {
      const [scenes, scripts] = await Promise.all([get('/scenes'), get('/scripts')]);
      hasStory = (scenes?.length ?? 0) > 0 || (scripts?.length ?? 0) > 0;
    } catch {
      hasStory = true; // fail open — the backend will still reject sensibly
    }
  }

  async function loadTypes() {
    try {
      const r = await get('/assets/types');
      if (Array.isArray(r?.types) && r.types.length) canonicalTypes = r.types;
    } catch {
      /* keep the built-in fallback */
    }
  }

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
      if (detail?.id === a.id) detail = null;
      toast.success(`Asset deleted (detached from ${r.detached_from} place${r.detached_from === 1 ? '' : 's'}).`);
      await Promise.all([refresh(), loadStyle()]);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = false;
    }
  }

  // ---- describe with AI (structures uploader-provided text into metadata) ----
  function openDescribe(asset: any) {
    describeTarget = asset;
    describeText = asset.description ?? '';
  }

  async function runDescribe() {
    const a = describeTarget;
    if (!a) return;
    const text = describeText.trim();
    if (!text) {
      toast.error('Add a few words describing the asset first.');
      return;
    }
    describeBusy = true;
    try {
      const updated = await post(`/assets/${a.id}/recognise`, { description: text });
      describeTarget = null;
      if (detail?.id === a.id) detail = updated;
      toast.success('Asset described — name, type and tags updated.');
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      describeBusy = false;
    }
  }

  let files: FileList | null = $state(null);
  let assetType = $state('');
  let characterId = $state('');

  async function refresh() {
    [assets, characters] = await Promise.all([get('/assets'), get('/characters')]);
  }
  onMount(() => {
    refresh()
      .catch((e) => (error = e.message))
      .finally(() => (loaded = true));
    loadStyle();
    loadStoryPresence();
    loadTypes();
  });

  async function doUpload(e: Event) {
    e.preventDefault();
    if (!files?.length) return;
    busy = true;
    error = '';
    try {
      const form = new FormData();
      for (const f of Array.from(files)) form.append('file', f);
      if (assetType) form.append('asset_type', assetType);
      if (characterId) form.append('character_id', characterId);
      const r = await upload('/assets/upload', form);
      const n = Array.isArray(r) ? r.length : 1;
      files = null;
      toast.success(`Uploaded ${n} file${n === 1 ? '' : 's'}.`);
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = false;
    }
  }

  // Map any stored type onto the canonical vocabulary for coherent filtering —
  // legacy/unknown values collapse to "other" (mirrors the backend canonicaliser).
  const canonical = (t: string | null | undefined) =>
    t && canonicalTypes.includes(t) ? t : 'other';

  // Distinct types actually present (canonicalised), for the filter chips.
  const presentTypes = $derived(
    Array.from(new Set(assets.map((a) => canonical(a.type)))).sort(
      (x, y) => canonicalTypes.indexOf(x) - canonicalTypes.indexOf(y)
    )
  );

  let filtered = $derived.by(() => {
    let out = assets;
    if (search) {
      const q = search.toLowerCase();
      out = out.filter((a) =>
        [a.name, a.type, a.description, ...(a.tags_json ?? [])]
          .join(' ')
          .toLowerCase()
          .includes(q)
      );
    }
    if (typeFilter) out = out.filter((a) => canonical(a.type) === typeFilter);

    const sorted = out.slice();
    if (sortBy === 'newest')
      sorted.sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
    else if (sortBy === 'oldest')
      sorted.sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''));
    else if (sortBy === 'name')
      sorted.sort((a, b) => (a.name ?? a.id).localeCompare(b.name ?? b.id));
    else if (sortBy === 'type')
      sorted.sort((a, b) => canonical(a.type).localeCompare(canonical(b.type)));
    return sorted;
  });
</script>

<div class="p-6">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Assets</h1>
    <p class="text-sm text-muted-foreground">Set the project look and manage generated media.</p>
  </div>

  <Card class="mb-4">
    <CardContent class="p-4">
      <div class="flex items-center gap-2 mb-1">
        <Palette class="size-4" />
        <span class="font-medium text-sm">Project style</span>
      </div>
      <p class="text-xs text-muted-foreground mb-3">
        Used for asset, storyboard, and video generation.
      </p>

      {#if !styleLoaded}
        <p class="text-sm text-muted-foreground">Loading…</p>
      {:else if !style && !styleEditing}
        <p class="text-sm text-muted-foreground mb-2">Choose how to set the project style.</p>
        <div class="flex gap-2">
          <Button
            size="sm"
            disabled={styleBusy === 'ingest' || !hasStory}
            title={!hasStory
              ? 'Write a script first — the style is derived from your story (先写剧本，再从故事提炼风格)'
              : undefined}
            onclick={ingestStyle}
          >
            <Wand2 class="size-3 mr-1" />{styleBusy === 'ingest' ? 'Deriving…' : 'Ingest from story'}
          </Button>
          <Button variant="outline" size="sm" onclick={() => (styleEditing = true)}>
            Create manually
          </Button>
        </div>
        {#if !hasStory}
          <p class="text-xs text-muted-foreground mt-2">
            Write a script first — the style is derived from your story (先写剧本，再从故事提炼风格).
          </p>
        {/if}
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
        <label class="block text-xs text-muted-foreground mb-1" for="file">File(s)</label>
        <input id="file" type="file" multiple bind:files
          class="block w-full text-sm rounded-md border border-input bg-background px-2 py-1.5" />
      </div>
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="type">Type (auto if blank)</label>
        <select id="type" bind:value={assetType}
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
          <option value="">auto</option>
          {#each canonicalTypes as t}<option value={t}>{t}</option>{/each}
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
        <Button type="submit" disabled={busy || !files?.length} size="sm">
          <Upload class="size-4 mr-1" />Upload{files && files.length > 1 ? ` (${files.length})` : ''}
        </Button>
      </div>
    </div>
  </form>

  <!-- search + filter + sort -->
  <div class="mb-4 flex flex-wrap items-center gap-3">
    <input
      placeholder="Search by name, tag, type…"
      bind:value={search}
      class="w-full max-w-sm rounded-md border border-input bg-background px-2 py-1.5 text-sm"
    />
    <div class="flex items-center gap-2">
      <Button variant={typeFilter === '' ? 'default' : 'outline'} size="sm"
        onclick={() => (typeFilter = '')}>All</Button>
      {#each presentTypes as t (t)}
        <Button variant={typeFilter === t ? 'default' : 'outline'} size="sm"
          onclick={() => (typeFilter = typeFilter === t ? '' : t)}>{t}</Button>
      {/each}
    </div>
    <div class="ml-auto flex items-center gap-1.5">
      <label class="text-xs text-muted-foreground" for="sort">Sort</label>
      <select id="sort" bind:value={sortBy}
        class="rounded-md border border-input bg-background px-2 py-1.5 text-sm">
        <option value="newest">Newest</option>
        <option value="oldest">Oldest</option>
        <option value="name">Name</option>
        <option value="type">Type</option>
      </select>
    </div>
  </div>

  {#if !loaded}
    <div class="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-4">
      {#each Array(4) as _, i (i)}
        <div class="rounded-lg border border-border p-3 space-y-2">
          <Skeleton class="w-full aspect-square rounded-md" />
          <Skeleton class="h-4 w-28" />
          <Skeleton class="h-3 w-36" />
        </div>
      {/each}
    </div>
  {:else if !assets.length}
    <p class="text-sm text-muted-foreground">
      Generated props, reference sheets and rendered videos will appear here.
    </p>
  {:else if !filtered.length}
    <p class="text-sm text-muted-foreground">Clear the filter or add an asset.</p>
  {/if}

  <div class="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-4">
    {#each filtered as asset (asset.id)}
      <Card>
        <CardContent class="p-3">
          <button type="button" class="block w-full text-left" title="Open"
            onclick={() => (detail = asset)}>
            {#if asset.type === 'video' || isVideo?.(asset.file_path)}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video preload="metadata" src={mediaUrl(asset.file_path)}
                class="w-full rounded-md bg-black mb-2 aspect-video object-contain pointer-events-none"></video>
            {:else if asset.type === 'audio' || isAudio(asset.file_path)}
              <div class="mb-2 grid aspect-square w-full place-items-center rounded-md bg-muted text-sm text-muted-foreground">Audio asset</div>
            {:else if asset.file_path && mediaUrl(asset.file_path) && isImage(asset.file_path)}
              <img class="w-full aspect-square object-cover rounded-md bg-muted mb-2 cursor-zoom-in"
                src={mediaUrl(asset.file_path)} alt={asset.name} loading="lazy" />
            {:else}
              <div class="w-full aspect-square rounded-md bg-muted mb-2 grid place-items-center text-muted-foreground text-2xl">
                {asset.type?.includes('video') ? 'V' : 'F'}
              </div>
            {/if}
          </button>
          <div class="font-medium text-sm mb-0.5">{asset.name || asset.id}</div>
          <div class="text-xs text-muted-foreground mb-1">{canonical(asset.type)} · {asset.id}</div>
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
            <Button variant="ghost" size="icon" class="size-8" title="Open detail"
              onclick={() => (detail = asset)}>
              <Maximize2 class="size-3.5" />
            </Button>
            <Button variant="ghost" size="icon" class="size-8" title="Describe with AI"
              disabled={busy} onclick={() => openDescribe(asset)}>
              <Sparkles class="size-3.5" />
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

<!-- Asset detail / lightbox -->
<Dialog.Root open={detail !== null} onOpenChange={(open) => !open && (detail = null)}>
  <Dialog.Content class="max-w-4xl sm:max-w-4xl">
    <Dialog.Header>
      <Dialog.Title class="truncate">{detail?.name || detail?.id}</Dialog.Title>
      <Dialog.Description>{canonical(detail?.type)} · {detail?.id}</Dialog.Description>
    </Dialog.Header>
    {#if detail}
      <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_260px]">
        <div class="flex items-center justify-center bg-muted rounded-md min-h-[240px]">
          {#if detail.type === 'video' || isVideo?.(detail.file_path)}
            <!-- svelte-ignore a11y_media_has_caption -->
            <video controls preload="metadata" src={mediaUrl(detail.file_path)}
              class="max-h-[70vh] w-full rounded-md bg-black object-contain"></video>
          {:else if detail.type === 'audio' || isAudio(detail.file_path)}
            {#if mediaUrl(detail.file_path)}
              <audio controls preload="metadata" src={mediaUrl(detail.file_path)} class="w-full"></audio>
            {:else}
              <p class="p-8 text-sm text-muted-foreground">This audio file has no playable local URL.</p>
            {/if}
          {:else if mediaUrl(detail.file_path) && isImage(detail.file_path)}
            <img class="max-h-[70vh] w-auto max-w-full rounded-md object-contain"
              src={mediaUrl(detail.file_path)} alt={detail.name || detail.id} />
          {:else}
            <div class="p-8 text-sm text-muted-foreground">This file type cannot be previewed here.</div>
          {/if}
        </div>
        <div class="space-y-3 text-xs">
          {#if detail.description}
            <div>
              <div class="text-muted-foreground mb-0.5">Description</div>
              <div>{detail.description}</div>
            </div>
          {/if}
          {#if detail.character_id}
            <div>
              <div class="text-muted-foreground mb-0.5">Character</div>
              <div>{characters.find((c) => c.id === detail.character_id)?.name ?? detail.character_id}</div>
            </div>
          {/if}
          {#if detail.tags_json?.length}
            <div>
              <div class="text-muted-foreground mb-1">Tags</div>
              <div class="flex flex-wrap gap-1">
                {#each detail.tags_json as tag}<Badge variant="outline">{tag}</Badge>{/each}
              </div>
            </div>
          {/if}
          <div>
            <div class="text-muted-foreground mb-0.5">File</div>
            <div class="break-all">{detail.file_path ?? '—'}</div>
          </div>
          {#if detail.created_at}
            <div>
              <div class="text-muted-foreground mb-0.5">Created</div>
              <div>{detail.created_at}</div>
            </div>
          {/if}
          {#if detail.metadata_json && Object.keys(detail.metadata_json).length}
            <div>
              <div class="text-muted-foreground mb-0.5">Metadata</div>
              <pre class="whitespace-pre-wrap break-all rounded-md bg-muted p-2 text-[11px]">{JSON.stringify(detail.metadata_json, null, 2)}</pre>
            </div>
          {/if}
          <div class="flex flex-wrap gap-1 pt-1">
            <Button variant="outline" size="sm" onclick={() => openDescribe(detail)}>
              <Sparkles class="size-3 mr-1" />Describe with AI
            </Button>
            {#if isImage(detail.file_path)}
              <Button variant="outline" size="sm" disabled={!!styleBusy} onclick={() => addStyleRef(detail)}>
                <Pin class="size-3 mr-1" />Pin as style
              </Button>
            {/if}
            <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive"
              onclick={() => (deleteTarget = detail)}>
              <Trash2 class="size-3 mr-1" />Delete
            </Button>
          </div>
        </div>
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>

<!-- Describe with AI -->
<Dialog.Root open={describeTarget !== null} onOpenChange={(open) => !open && (describeTarget = null)}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>Describe with AI</Dialog.Title>
      <Dialog.Description>
        The assistant structures the text you provide into a name, type and searchable
        tags. It reads your words, not the pixels — describe what's in the asset.
      </Dialog.Description>
    </Dialog.Header>
    <div class="grid gap-1.5">
      <Label for="describe-text">What is this asset?</Label>
      <Textarea id="describe-text" rows={4} bind:value={describeText}
        placeholder="e.g. a red lipstick bullet on a black background, product shot" />
    </div>
    <Dialog.Footer>
      <Button variant="outline" size="sm" onclick={() => (describeTarget = null)}>Cancel</Button>
      <Button size="sm" disabled={describeBusy} onclick={runDescribe}>
        <Sparkles class="size-3 mr-1" />{describeBusy ? 'Structuring…' : 'Structure metadata'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

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
