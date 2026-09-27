<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, patch, del, upload, mediaUrl, isImage } from '$lib/api';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import * as Dialog from '$lib/components/ui/dialog';
  import { toast } from 'svelte-sonner';
  import {
    UserPlus,
    BookOpen,
    Images,
    Upload,
    ChevronDown,
    Pencil,
    Trash2,
    Save,
    X,
    ChevronLeft,
    ChevronRight
  } from '@lucide/svelte';

  let characters: any[] = $state([]);
  let assets: Record<string, any> = $state({});
  let error = $state('');
  let busy = $state('');
  let loaded = $state(false);
  let expanded: Record<string, boolean> = $state({});

  let name = $state('');
  let description = $state('');

  // --- inline edit ---
  let editing: string | null = $state(null);
  let editForm = $state({
    name: '',
    description: '',
    appearance: '',
    personality: '',
    visual_rules: '', // one rule per line
    voice_rules: '' // one rule per line
  });

  // --- delete confirm ---
  let deleteTarget: any = $state(null);

  // --- reference-sheet lightbox ---
  let lightbox: { items: any[]; index: number; charName: string } | null = $state(null);

  async function refresh() {
    characters = await get('/characters');
    const all = await get('/assets');
    assets = Object.fromEntries(all.map((a: any) => [a.id, a]));
  }
  onMount(() =>
    refresh()
      .catch((e) => (error = e.message))
      .finally(() => (loaded = true))
  );

  async function run(key: string, fn: () => Promise<unknown>) {
    busy = key;
    error = '';
    try {
      await fn();
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  const createCharacter = (e: Event) => {
    e.preventDefault();
    run('create', async () => {
      await post('/characters', { name, description });
      name = '';
      description = '';
    });
  };

  function generateBible(c: any) {
    const notes = prompt(`Notes for ${c.name}'s character bible:`, c.description || '');
    if (notes === null) return;
    run(`bible-${c.id}`, () => post(`/characters/${c.id}/bible`, { notes }));
  }

  const generateSheets = (c: any) =>
    run(`sheets-${c.id}`, () => post(`/characters/${c.id}/reference-sheets`, {}));

  function uploadPhoto(c: any, e: Event) {
    const input = e.target as HTMLInputElement;
    if (!input.files?.length) return;
    const form = new FormData();
    for (const f of Array.from(input.files)) form.append('file', f);
    form.append('character_id', c.id);
    run(`photo-${c.id}`, () => upload('/assets/upload', form));
    input.value = '';
  }

  // ---- inline edit ----
  function startEdit(c: any) {
    editing = c.id;
    expanded[c.id] = true;
    editForm = {
      name: c.name ?? '',
      description: c.description ?? '',
      appearance: c.appearance ?? '',
      personality: c.personality ?? '',
      visual_rules: (c.visual_rules_json ?? []).join('\n'),
      voice_rules: (c.voice_rules_json ?? []).join('\n')
    };
  }

  function cancelEdit() {
    editing = null;
  }

  function saveEdit(c: any) {
    const body = {
      name: editForm.name.trim(),
      description: editForm.description,
      appearance: editForm.appearance,
      personality: editForm.personality,
      visual_rules: editForm.visual_rules
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
      voice_rules: editForm.voice_rules
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
    };
    if (!body.name) {
      toast.error('Name cannot be empty.');
      return;
    }
    run(`save-${c.id}`, async () => {
      await patch(`/characters/${c.id}`, body);
      editing = null;
      toast.success('Character saved.');
    });
  }

  // ---- delete ----
  async function confirmDelete() {
    const c = deleteTarget;
    if (!c) return;
    busy = `delete-${c.id}`;
    try {
      const r = await del(`/characters/${c.id}`);
      deleteTarget = null;
      toast.success(
        `Character deleted (detached from ${r.detached_from} place${r.detached_from === 1 ? '' : 's'}; reference images kept).`
      );
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  // ---- lightbox ----
  function openLightbox(c: any, startIndex = 0) {
    const items = (c.reference_asset_ids_json ?? [])
      .map((id: string) => assets[id])
      .filter((a: any) => a && isImage(a.file_path));
    if (!items.length) return;
    lightbox = { items, index: Math.min(startIndex, items.length - 1), charName: c.name };
  }
  function lightboxStep(delta: number) {
    if (!lightbox) return;
    const n = lightbox.items.length;
    lightbox.index = (lightbox.index + delta + n) % n;
  }
  function onLightboxKey(e: KeyboardEvent) {
    if (!lightbox) return;
    if (e.key === 'ArrowRight') lightboxStep(1);
    else if (e.key === 'ArrowLeft') lightboxStep(-1);
    else if (e.key === 'Escape') lightbox = null;
  }
</script>

<svelte:window onkeydown={onLightboxKey} />

<div class="p-6">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Characters</h1>
    <p class="text-sm text-muted-foreground">Add reference images for consistent characters.</p>
  </div>

  {#if loaded && !characters.length}
    <Card class="mb-4">
      <CardContent class="p-4">
        <div class="flex items-center gap-2 mb-1">
          <Images class="size-4" />
          <span class="font-medium text-sm">Add your first character</span>
        </div>
        <p class="text-sm text-muted-foreground">
          Enter a name below, then add 2–4 reference images.
        </p>
      </CardContent>
    </Card>
  {/if}

  <form class="mb-4 rounded-lg border border-border bg-card p-4" onsubmit={createCharacter}>
    <div class="flex flex-wrap gap-4 items-end">
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="name">Name</label>
        <input id="name" bind:value={name} required
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
      </div>
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="desc">Description</label>
        <input id="desc" bind:value={description}
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
      </div>
      <div>
        <Button type="submit" disabled={busy === 'create' || !name} size="sm">
          <UserPlus class="size-4 mr-1" />Create character
        </Button>
      </div>
    </div>
  </form>

  {#if !loaded}
    <div class="grid grid-cols-[repeat(auto-fill,minmax(290px,1fr))] gap-4">
      {#each Array(3) as _, i (i)}
        <div class="rounded-lg border border-border p-3 space-y-2">
          <Skeleton class="w-full aspect-square rounded-md" />
          <Skeleton class="h-4 w-24" />
          <Skeleton class="h-3 w-40" />
        </div>
      {/each}
    </div>
  {/if}

  <div class="grid grid-cols-[repeat(auto-fill,minmax(290px,1fr))] gap-4">
    {#each characters as c (c.id)}
      {@const firstRef = c.reference_asset_ids_json?.length ? assets[c.reference_asset_ids_json[0]] : null}
      <Card class="self-start">
        <CardContent class="p-3">
          <div class="flex items-center gap-3">
            {#if firstRef && isImage(firstRef.file_path)}
              <button type="button" class="flex-none" title="View reference sheets"
                onclick={() => openLightbox(c, 0)}>
                <img class="size-12 aspect-square object-cover rounded-md bg-muted cursor-zoom-in"
                  src={mediaUrl(firstRef.file_path)} alt={c.name} loading="lazy" />
              </button>
            {:else}
              <div class="size-12 flex-none rounded-md bg-muted grid place-items-center text-muted-foreground font-medium">
                {c.name?.[0] ?? '?'}
              </div>
            {/if}
            <div class="min-w-0 flex-1">
              <div class="font-medium text-sm truncate">{c.name}</div>
              <div class="text-xs text-muted-foreground truncate">
                {c.description || c.appearance || `${c.reference_asset_ids_json?.length ?? 0} reference images`}
              </div>
            </div>
            <Button variant="ghost" size="sm" class="flex-none px-2"
              aria-expanded={!!expanded[c.id]}
              onclick={() => (expanded[c.id] = !expanded[c.id])}>
              <ChevronDown class="size-4 transition-transform {expanded[c.id] ? 'rotate-180' : ''}" />
              <span class="text-xs">Details</span>
            </Button>
          </div>

          {#if expanded[c.id]}
            <div class="mt-3 space-y-2 border-t border-border pt-3">
              {#if editing === c.id}
                <!-- ---- inline edit form ---- -->
                <div class="grid gap-2">
                  <div class="grid gap-1.5">
                    <Label for="edit-name-{c.id}">Name</Label>
                    <Input id="edit-name-{c.id}" bind:value={editForm.name} />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="edit-desc-{c.id}">Description</Label>
                    <Input id="edit-desc-{c.id}" bind:value={editForm.description} />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="edit-appear-{c.id}">Appearance</Label>
                    <Textarea id="edit-appear-{c.id}" rows={2} bind:value={editForm.appearance} />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="edit-pers-{c.id}">Personality</Label>
                    <Textarea id="edit-pers-{c.id}" rows={2} bind:value={editForm.personality} />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="edit-rules-{c.id}">Visual rules (one per line)</Label>
                    <Textarea id="edit-rules-{c.id}" rows={3} bind:value={editForm.visual_rules}
                      placeholder="always wears red hoodie&#10;short black hair" />
                  </div>
                  <div class="grid gap-1.5">
                    <Label for="edit-voice-{c.id}">Voice rules (one per line)</Label>
                    <Textarea id="edit-voice-{c.id}" rows={3} bind:value={editForm.voice_rules}
                      placeholder="cheerful high-pitched voice&#10;speaks quickly" />
                  </div>
                  <div class="flex gap-2 pt-1">
                    <Button size="sm" disabled={busy === `save-${c.id}`} onclick={() => saveEdit(c)}>
                      <Save class="size-3 mr-1" />{busy === `save-${c.id}` ? 'Saving…' : 'Save'}
                    </Button>
                    <Button variant="outline" size="sm" disabled={!!busy} onclick={cancelEdit}>
                      <X class="size-3 mr-1" />Cancel
                    </Button>
                  </div>
                </div>
              {:else}
                <!-- ---- read view ---- -->
                <div class="text-xs text-muted-foreground">{c.id} · {c.reference_asset_ids_json?.length ?? 0} reference images</div>
                {#if c.appearance}
                  <div class="text-xs"><span class="text-muted-foreground">Appearance:</span> {c.appearance}</div>
                {/if}
                {#if c.personality}
                  <div class="text-xs"><span class="text-muted-foreground">Personality:</span> {c.personality}</div>
                {/if}
                {#if c.visual_rules_json?.length}
                  <div class="flex flex-wrap gap-1">
                    {#each c.visual_rules_json as rule}
                      <Badge variant="outline" class="max-w-full" title={rule}>
                        <span class="truncate">{rule}</span>
                      </Badge>
                    {/each}
                  </div>
                {/if}
                {#if c.reference_asset_ids_json?.length}
                  <div class="grid grid-cols-3 gap-2">
                    {#each c.reference_asset_ids_json as refId, i (refId)}
                      {@const ref = assets[refId]}
                      {#if ref && isImage(ref.file_path)}
                        <button type="button" class="block" title="View {ref.name || 'reference'}"
                          onclick={() => openLightbox(c, i)}>
                          <img class="w-full aspect-square object-cover rounded-md bg-muted cursor-zoom-in"
                            src={mediaUrl(ref.file_path)} alt={ref.name || c.name} loading="lazy" />
                        </button>
                      {/if}
                    {/each}
                  </div>
                {/if}

                <div class="flex flex-wrap gap-1 pt-1">
                  <Button variant="outline" size="sm" disabled={!!busy} onclick={() => startEdit(c)}>
                    <Pencil class="size-3 mr-1" />Edit
                  </Button>
                  <Button variant="outline" size="sm" disabled={!!busy} onclick={() => generateBible(c)}>
                    <BookOpen class="size-3 mr-1" />{busy === `bible-${c.id}` ? 'Generating…' : 'Generate bible'}
                  </Button>
                  <Button variant="outline" size="sm" disabled={!!busy} onclick={() => generateSheets(c)}>
                    <Images class="size-3 mr-1" />{busy === `sheets-${c.id}` ? 'Generating…' : 'Generate reference sheets'}
                  </Button>
                  <label class="inline-flex items-center gap-1 cursor-pointer rounded-md border border-border px-2 py-1 text-xs hover:bg-accent">
                    <Upload class="size-3" />Upload reference photo
                    <input type="file" class="hidden" multiple accept="image/*" onchange={(e) => uploadPhoto(c, e)} />
                  </label>
                  <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive"
                    disabled={!!busy} onclick={() => (deleteTarget = c)}>
                    <Trash2 class="size-3 mr-1" />Delete
                  </Button>
                </div>
              {/if}
            </div>
          {/if}
        </CardContent>
      </Card>
    {/each}
  </div>
</div>

<!-- Delete confirm dialog (app confirm pattern) -->
<Dialog.Root open={deleteTarget !== null} onOpenChange={(open) => !open && (deleteTarget = null)}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>Delete character?</Dialog.Title>
      <Dialog.Description>
        "{deleteTarget?.name}" will be removed and detached from every scene cast.
        Its reference images stay in the asset library.
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" size="sm" onclick={() => (deleteTarget = null)}>Cancel</Button>
      <Button variant="destructive" size="sm" disabled={!!busy} onclick={confirmDelete}>
        <Trash2 class="size-3 mr-1" />{busy === `delete-${deleteTarget?.id}` ? 'Deleting…' : 'Delete'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<!-- Reference-sheet lightbox -->
<Dialog.Root open={lightbox !== null} onOpenChange={(open) => !open && (lightbox = null)}>
  <Dialog.Content class="max-w-3xl sm:max-w-3xl">
    <Dialog.Header>
      <Dialog.Title class="truncate">
        {lightbox?.charName} — reference {(lightbox?.index ?? 0) + 1} / {lightbox?.items.length ?? 0}
      </Dialog.Title>
      {#if lightbox?.items[lightbox.index]?.name}
        <Dialog.Description class="truncate">{lightbox.items[lightbox.index].name}</Dialog.Description>
      {/if}
    </Dialog.Header>
    {#if lightbox}
      <div class="relative flex items-center justify-center bg-muted rounded-md">
        <img class="max-h-[70vh] w-auto max-w-full rounded-md object-contain"
          src={mediaUrl(lightbox.items[lightbox.index].file_path)}
          alt={lightbox.items[lightbox.index].name || lightbox.charName} />
        {#if lightbox.items.length > 1}
          <button type="button" aria-label="Previous"
            class="absolute left-2 grid size-9 place-items-center rounded-full bg-background/80 border border-border shadow hover:bg-background"
            onclick={() => lightboxStep(-1)}>
            <ChevronLeft class="size-4" />
          </button>
          <button type="button" aria-label="Next"
            class="absolute right-2 grid size-9 place-items-center rounded-full bg-background/80 border border-border shadow hover:bg-background"
            onclick={() => lightboxStep(1)}>
            <ChevronRight class="size-4" />
          </button>
        {/if}
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>
