<script lang="ts">
  import { preventDefault } from 'svelte/legacy';

  import { onMount } from 'svelte';
  import { get, post, upload, mediaUrl, isImage } from '$lib/api';

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
      error = e.message;
    } finally {
      busy = '';
    }
  }

  const createCharacter = () =>
    run('create', async () => {
      await post('/characters', { name, description });
      name = '';
      description = '';
    });

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

<h1>Characters</h1>

<form class="panel" onsubmit={preventDefault(createCharacter)}>
  <div class="row">
    <div>
      <label for="name">Name</label>
      <input id="name" bind:value={name} required />
    </div>
    <div>
      <label for="desc">Description</label>
      <input id="desc" bind:value={description} />
    </div>
    <div><button disabled={busy === 'create' || !name}>Create character</button></div>
  </div>
  {#if error}<div class="error">{error}</div>{/if}
</form>

<div class="grid">
  {#each characters as c (c.id)}
    <div class="card">
      {#if c.reference_asset_ids_json?.length}
        {@const ref = assets[c.reference_asset_ids_json[0]]}
        {#if ref && isImage(ref.file_path)}
          <img class="thumb" src={mediaUrl(ref.file_path)} alt={c.name} loading="lazy" />
        {/if}
      {/if}
      <h3>{c.name}</h3>
      <div class="meta">{c.id} · {c.reference_asset_ids_json?.length ?? 0} reference images</div>
      {#if c.appearance}
        <div class="meta" style="margin-top:0.3rem">{c.appearance.slice(0, 120)}</div>
      {/if}
      <div>
        {#each c.visual_rules_json ?? [] as rule}
          <span class="tag">{rule}</span>
        {/each}
      </div>
      <div>
        <button class="small secondary" disabled={!!busy} onclick={() => generateBible(c)}>
          {busy === `bible-${c.id}` ? '…' : 'Generate bible'}
        </button>
        <button class="small secondary" disabled={!!busy} onclick={() => generateSheets(c)}>
          {busy === `sheets-${c.id}` ? '…' : 'Reference sheets (ERNIE)'}
        </button>
        <label class="small" style="margin-top:0.4rem">
          Upload reference photo
          <input type="file" onchange={(e) => uploadPhoto(c, e)} />
        </label>
      </div>
    </div>
  {/each}
</div>
