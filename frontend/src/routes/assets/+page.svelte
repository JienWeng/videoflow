<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, upload } from '$lib/api';
  import AssetCard from '$lib/components/AssetCard.svelte';

  let assets: any[] = [];
  let characters: any[] = [];
  let error = '';
  let busy = false;
  let search = '';

  let file: FileList | null = null;
  let assetType = '';
  let characterId = '';

  const ASSET_TYPES = ['', 'character_reference', 'location', 'prop', 'video_reference', 'audio_reference', 'voice'];

  async function refresh() {
    [assets, characters] = await Promise.all([get('/assets'), get('/characters')]);
  }
  onMount(() => refresh().catch((e) => (error = e.message)));

  async function doUpload() {
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
      error = e.message;
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
      error = e.message;
    } finally {
      busy = false;
    }
  }

  $: filtered = search
    ? assets.filter((a) =>
        [a.name, a.type, a.description, ...(a.tags_json ?? [])]
          .join(' ')
          .toLowerCase()
          .includes(search.toLowerCase())
      )
    : assets;
</script>

<h1>Assets</h1>

<form class="panel" on:submit|preventDefault={doUpload}>
  <div class="row">
    <div>
      <label for="file">File</label>
      <input id="file" type="file" bind:files={file} />
    </div>
    <div>
      <label for="type">Type (auto if blank)</label>
      <select id="type" bind:value={assetType}>
        {#each ASSET_TYPES as t}<option value={t}>{t || 'auto'}</option>{/each}
      </select>
    </div>
    <div>
      <label for="char">Link to character</label>
      <select id="char" bind:value={characterId}>
        <option value="">none</option>
        {#each characters as c}<option value={c.id}>{c.name}</option>{/each}
      </select>
    </div>
    <div><button disabled={busy || !file?.length}>Upload</button></div>
  </div>
  {#if error}<div class="error">{error}</div>{/if}
</form>

<input placeholder="Search by name, tag, type…" bind:value={search} style="margin-bottom:1rem" />

<div class="grid">
  {#each filtered.slice().reverse() as asset (asset.id)}
    <AssetCard {asset}>
      <button class="small secondary" disabled={busy} on:click={() => recognise(asset)}>
        AI tag
      </button>
    </AssetCard>
  {/each}
</div>
