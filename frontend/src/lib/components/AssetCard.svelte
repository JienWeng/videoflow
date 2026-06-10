<script lang="ts">
  import { mediaUrl, isImage } from '$lib/api';

  interface Props {
    asset: any;
    children?: import('svelte').Snippet;
  }

  let { asset, children }: Props = $props();
</script>

<div class="card">
  {#if isImage(asset.file_path) && mediaUrl(asset.file_path)}
    <img class="thumb" src={mediaUrl(asset.file_path)} alt={asset.name} loading="lazy" />
  {:else}
    <div class="thumb" style="display:grid;place-items:center;font-size:2rem;">
      {asset.type === 'storyboard' ? '🎞' : asset.type?.includes('video') ? '🎥' : '📦'}
    </div>
  {/if}
  <h3>{asset.name || asset.id}</h3>
  <div class="meta">{asset.type} · {asset.id}</div>
  {#if asset.description}
    <div class="meta" style="margin-top:0.3rem">{asset.description.slice(0, 90)}</div>
  {/if}
  <div>
    {#each asset.tags_json ?? [] as tag}
      <span class="tag">{tag}</span>
    {/each}
  </div>
  {@render children?.()}
</div>
