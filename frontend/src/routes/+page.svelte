<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from '$lib/api';
  import AssetCard from '$lib/components/AssetCard.svelte';
  import VideoPreview from '$lib/components/VideoPreview.svelte';

  let assets: any[] = $state([]);
  let characters: any[] = $state([]);
  let scenes: any[] = $state([]);
  let jobs: any[] = $state([]);
  let outputs: any[] = $state([]);
  let error = $state('');

  onMount(async () => {
    try {
      [assets, characters, scenes, jobs] = await Promise.all([
        get('/assets'),
        get('/characters'),
        get('/scenes'),
        get('/render-jobs')
      ]);
      const done = jobs.filter((j) => j.status === 'succeeded').slice(-3);
      const detail = await Promise.all(done.map((j) => get(`/render-jobs/${j.id}`)));
      outputs = detail.flatMap((d) => d.outputs);
    } catch (e: any) {
      error = e.message;
    }
  });
</script>

<h1>Dashboard</h1>
{#if error}<div class="error">{error}</div>{/if}

<div class="stats">
  <div class="stat"><div class="n">{assets.length}</div><div class="l">assets</div></div>
  <div class="stat"><div class="n">{characters.length}</div><div class="l">characters</div></div>
  <div class="stat"><div class="n">{scenes.length}</div><div class="l">scenes</div></div>
  <div class="stat"><div class="n">{jobs.length}</div><div class="l">render jobs</div></div>
</div>

<h2>Latest outputs</h2>
{#if outputs.length === 0}<div class="meta">No finished renders yet.</div>{/if}
<div class="grid">
  {#each outputs as out}
    <div class="card">
      <VideoPreview path={out.video_path} />
      <div class="meta">QA score: {out.score ?? '—'}</div>
    </div>
  {/each}
</div>

<h2>Recent assets</h2>
<div class="grid">
  {#each assets.slice(-8).reverse() as asset}
    <AssetCard {asset} />
  {/each}
</div>
