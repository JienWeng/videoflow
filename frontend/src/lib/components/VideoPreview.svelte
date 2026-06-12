<script lang="ts">
  import { goto } from '$app/navigation';
  import { mediaUrl } from '$lib/api';

  interface Props {
    path?: string | null;
    /** When set, clicking the video body (not the control bar) navigates here. */
    href?: string | null;
    title?: string;
  }

  let { path = null, href = null, title = 'Open in editor' }: Props = $props();

  function onclick(e: MouseEvent) {
    if (!href) return;
    const v = e.currentTarget as HTMLVideoElement;
    // Leave the native control bar (bottom strip) usable for play/seek.
    if (e.offsetY > v.clientHeight - 44) return;
    e.preventDefault();
    goto(href);
  }
</script>

{#if path && mediaUrl(path)}
  <!-- svelte-ignore a11y_media_has_caption -->
  <video
    class="w-[320px] aspect-video rounded-lg border border-border bg-black object-contain {href ? 'cursor-pointer' : ''}"
    controls
    preload="metadata"
    src={mediaUrl(path)}
    title={href ? title : undefined}
    {onclick}
  ></video>
{:else}
  <span class="text-xs text-muted-foreground">no output yet</span>
{/if}
