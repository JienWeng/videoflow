<script lang="ts">
  import { goto } from '$app/navigation';
  import { mediaUrl } from '$lib/api';
  import { Play } from '@lucide/svelte';

  interface Props {
    path?: string | null;
    /** When set, clicking the video body (not the control bar) navigates here. */
    href?: string | null;
    title?: string;
    /** Stored thumbnail file_path — shown as a poster so we don't autoload full
     * video metadata for every card on a busy page. */
    poster?: string | null;
  }

  let { path = null, href = null, title = 'Open in editor', poster = null }: Props = $props();

  const src = $derived(mediaUrl(path));
  const posterUrl = $derived(mediaUrl(poster));

  // When we have a poster we render a lightweight thumbnail and only swap in the
  // real <video> after the user opts in — keeps lists snappy and saves the
  // browser from fetching metadata for dozens of takes at once.
  let activated = $state(false);

  function onclick(e: MouseEvent) {
    if (!href) return;
    const v = e.currentTarget as HTMLVideoElement;
    // Leave the native control bar (bottom strip) usable for play/seek.
    if (e.offsetY > v.clientHeight - 44) return;
    e.preventDefault();
    goto(href);
  }

  const boxClass =
    'w-[320px] aspect-video rounded-lg border border-border bg-black object-contain';
</script>

{#if src}
  {#if posterUrl && !activated}
    <!-- Poster-only preview: no <video> until activated, so metadata isn't fetched. -->
    <button
      type="button"
      class="group relative block {boxClass} overflow-hidden cursor-pointer p-0"
      title={href ? title : 'Play'}
      onclick={(e) => {
        // Click the play affordance -> load the player inline; clicking elsewhere
        // with an href navigates (matches the <video>-body behaviour).
        if (href) {
          e.preventDefault();
          goto(href);
        } else {
          activated = true;
        }
      }}
    >
      <img src={posterUrl} alt={title} class="h-full w-full object-contain" loading="lazy" />
      <span
        class="absolute inset-0 flex items-center justify-center bg-black/20 transition group-hover:bg-black/30"
      >
        <span class="flex size-11 items-center justify-center rounded-full bg-black/60 text-white">
          <Play class="size-5" />
        </span>
      </span>
    </button>
  {:else}
    <!-- svelte-ignore a11y_media_has_caption -->
    <video
      class="{boxClass} {href ? 'cursor-pointer' : ''}"
      controls
      preload={posterUrl ? 'none' : 'metadata'}
      poster={posterUrl ?? undefined}
      autoplay={activated}
      {src}
      title={href ? title : undefined}
      {onclick}
    ></video>
  {/if}
{:else}
  <span class="text-xs text-muted-foreground">Render to preview</span>
{/if}
