<script lang="ts">
  import { mediaUrl, isImage } from '$lib/api';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { FileVideo, Package } from '@lucide/svelte';

  interface Props {
    asset: any;
    children?: import('svelte').Snippet;
  }

  let { asset, children }: Props = $props();
</script>

<Card>
  <CardContent class="p-3">
    {#if isImage(asset.file_path) && mediaUrl(asset.file_path)}
      <img class="w-full aspect-square object-cover rounded-md bg-muted mb-2"
        src={mediaUrl(asset.file_path)} alt={asset.name} loading="lazy" />
    {:else}
      <div class="w-full aspect-square rounded-md bg-muted mb-2 grid place-items-center text-muted-foreground">
        {#if asset.type === 'storyboard' || asset.type?.includes('video')}
          <FileVideo class="size-8" />
        {:else}
          <Package class="size-8" />
        {/if}
      </div>
    {/if}
    <div class="font-medium text-sm mb-0.5">{asset.name || asset.id}</div>
    <div class="text-xs text-muted-foreground mb-1">{asset.type} · {asset.id}</div>
    {#if asset.description}
      <div class="text-xs text-muted-foreground mb-1">{asset.description.slice(0, 90)}</div>
    {/if}
    <div class="flex flex-wrap gap-1 mb-2">
      {#each asset.tags_json ?? [] as tag}
        <Badge variant="outline" class="text-xs">{tag}</Badge>
      {/each}
    </div>
    {@render children?.()}
  </CardContent>
</Card>
