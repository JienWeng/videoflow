<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from '$lib/api';
  import VideoPreview from '$lib/components/VideoPreview.svelte';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { Image, Users, ListVideo, Film } from '@lucide/svelte';

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

  const stats = $derived([
    { label: 'Assets', value: assets.length, icon: Image },
    { label: 'Characters', value: characters.length, icon: Users },
    { label: 'Scenes', value: scenes.length, icon: ListVideo },
    { label: 'Render jobs', value: jobs.length, icon: Film }
  ]);
</script>

<div class="p-6">
  <h1 class="text-lg font-semibold mb-4">Studio</h1>
  {#if error}<div class="text-destructive text-sm mb-4">{error}</div>{/if}

  <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
    {#each stats as s}
      <Card>
        <CardContent class="pt-4">
          <div class="flex items-center gap-2 text-muted-foreground mb-1">
            <s.icon class="size-4" />
            <span class="text-sm">{s.label}</span>
          </div>
          <div class="text-2xl font-bold">{s.value}</div>
        </CardContent>
      </Card>
    {/each}
  </div>

  <h2 class="text-base font-semibold mb-3">Latest outputs</h2>
  {#if outputs.length === 0}
    <div class="text-sm text-muted-foreground mb-4">No finished renders yet.</div>
  {/if}
  <div class="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-4 mb-6">
    {#each outputs as out}
      <Card>
        <CardContent class="p-3">
          <VideoPreview path={out.video_path} />
          <div class="text-xs text-muted-foreground mt-1">QA score: {out.score ?? '—'}</div>
        </CardContent>
      </Card>
    {/each}
  </div>

  <h2 class="text-base font-semibold mb-3">Recent assets</h2>
  <div class="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
    {#each assets.slice(-8).reverse() as asset}
      <Card>
        <CardContent class="p-3">
          <div class="font-medium text-sm mb-0.5">{asset.name || asset.id}</div>
          <div class="text-xs text-muted-foreground">{asset.type}</div>
          {#if asset.tags_json?.length}
            <div class="flex flex-wrap gap-1 mt-1">
              {#each asset.tags_json.slice(0, 3) as tag}
                <Badge variant="outline" class="text-xs">{tag}</Badge>
              {/each}
            </div>
          {/if}
        </CardContent>
      </Card>
    {/each}
  </div>
</div>
