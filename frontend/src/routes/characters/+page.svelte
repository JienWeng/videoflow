<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, upload, mediaUrl, isImage } from '$lib/api';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { toast } from 'svelte-sonner';
  import { UserPlus, BookOpen, Images, Upload } from '@lucide/svelte';

  let characters: any[] = $state([]);
  let assets: Record<string, any> = $state({});
  let error = $state('');
  let busy = $state('');

  let name = $state('');
  let description = $state('');

  async function refresh() {
    characters = await get('/characters');
    const all = await get('/assets');
    assets = Object.fromEntries(all.map((a: any) => [a.id, a]));
  }
  onMount(() => refresh().catch((e) => (error = e.message)));

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
  <h1 class="text-lg font-semibold mb-4">Characters</h1>

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

  <div class="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-4">
    {#each characters as c (c.id)}
      <Card>
        <CardContent class="p-3">
          {#if c.reference_asset_ids_json?.length}
            {@const ref = assets[c.reference_asset_ids_json[0]]}
            {#if ref && isImage(ref.file_path)}
              <img class="w-full aspect-square object-cover rounded-md bg-muted mb-2"
                src={mediaUrl(ref.file_path)} alt={c.name} loading="lazy" />
            {/if}
          {/if}
          <div class="font-medium text-sm mb-0.5">{c.name}</div>
          <div class="text-xs text-muted-foreground mb-1">{c.id} · {c.reference_asset_ids_json?.length ?? 0} reference images</div>
          {#if c.appearance}
            <div class="text-xs text-muted-foreground mb-2">{c.appearance.slice(0, 120)}</div>
          {/if}
          <div class="flex flex-wrap gap-1 mb-2">
            {#each c.visual_rules_json ?? [] as rule}
              <Badge variant="outline">{rule}</Badge>
            {/each}
          </div>
          <div class="flex flex-wrap gap-1 mt-1">
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
        </CardContent>
      </Card>
    {/each}
  </div>
</div>
