<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, upload, mediaUrl, isImage } from '$lib/api';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { toast } from 'svelte-sonner';
  import { UserPlus, BookOpen, Images, Upload, ChevronDown } from '@lucide/svelte';

  let characters: any[] = $state([]);
  let assets: Record<string, any> = $state({});
  let error = $state('');
  let busy = $state('');
  let loaded = $state(false);
  let expanded: Record<string, boolean> = $state({});

  let name = $state('');
  let description = $state('');

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
    form.append('file', input.files[0]);
    form.append('character_id', c.id);
    run(`photo-${c.id}`, () => upload('/assets/upload', form));
  }
</script>

<div class="p-6">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Characters</h1>
    <p class="text-sm text-muted-foreground">Recurring cast with reference sheets that keep each character consistent across videos.</p>
  </div>

  {#if loaded && !characters.length}
    <Card class="mb-4">
      <CardContent class="p-4">
        <div class="flex items-center gap-2 mb-1">
          <Images class="size-4" />
          <span class="font-medium text-sm">No characters yet</span>
        </div>
        <p class="text-sm text-muted-foreground">
          Create a character below, then upload 2-4 photos of them — the photos become
          reference sheets that keep the character identical in every video.
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
    <div class="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-4">
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
              <img class="size-12 flex-none aspect-square object-cover rounded-md bg-muted"
                src={mediaUrl(firstRef.file_path)} alt={c.name} loading="lazy" />
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
                  {#each c.reference_asset_ids_json as refId (refId)}
                    {@const ref = assets[refId]}
                    {#if ref && isImage(ref.file_path)}
                      <img class="w-full aspect-square object-cover rounded-md bg-muted"
                        src={mediaUrl(ref.file_path)} alt={ref.name || c.name} title={ref.name} loading="lazy" />
                    {/if}
                  {/each}
                </div>
              {/if}
              <div class="flex flex-wrap gap-1 pt-1">
                <Button variant="outline" size="sm" disabled={!!busy} onclick={() => generateBible(c)}>
                  <BookOpen class="size-3 mr-1" />{busy === `bible-${c.id}` ? 'Generating…' : 'Generate bible'}
                </Button>
                <Button variant="outline" size="sm" disabled={!!busy} onclick={() => generateSheets(c)}>
                  <Images class="size-3 mr-1" />{busy === `sheets-${c.id}` ? 'Generating…' : 'Reference sheets (ERNIE)'}
                </Button>
                <label class="inline-flex items-center gap-1 cursor-pointer rounded-md border border-border px-2 py-1 text-xs hover:bg-accent">
                  <Upload class="size-3" />Upload reference photo
                  <input type="file" class="hidden" onchange={(e) => uploadPhoto(c, e)} />
                </label>
              </div>
            </div>
          {/if}
        </CardContent>
      </Card>
    {/each}
  </div>
</div>
