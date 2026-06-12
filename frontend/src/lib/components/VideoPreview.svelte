<script lang="ts">
  import { mediaUrl } from '$lib/api';

  interface Props {
    path?: string | null;
  }

  let { path = null }: Props = $props();
</script>

{#if path && mediaUrl(path)}
  <!-- svelte-ignore a11y_media_has_caption -->
  <video
    class="w-[320px] aspect-video rounded-lg border border-border bg-black object-contain"
    controls
    preload="metadata"
    src={mediaUrl(path)}
  ></video>
{:else}
  <span class="text-xs text-muted-foreground">no output yet</span>
{/if}
