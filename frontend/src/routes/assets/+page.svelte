<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, upload, mediaUrl, isVideo } from '$lib/api';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { toast } from 'svelte-sonner';
  import { Upload, Tag } from '@lucide/svelte';

  let assets: any[] = $state([]);
  let characters: any[] = $state([]);
  let error = $state('');
  let busy = $state(false);
  let search = $state('');

  let file: FileList | null = $state(null);
  let assetType = $state('');
  let characterId = $state('');

  const ASSET_TYPES = ['', 'character_reference', 'location', 'prop', 'video_reference', 'audio_reference', 'voice'];

  async function refresh() {
    [assets, characters] = await Promise.all([get('/assets'), get('/characters')]);
  }
  onMount(() => refresh().catch((e) => (error = e.message)));

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
          <Button variant="outline" size="sm" disabled={busy} onclick={() => recognise(asset)}>
            <Tag class="size-3 mr-1" />AI tag
          </Button>
        </CardContent>
      </Card>
    {/each}
  </div>
</div>
