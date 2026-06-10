<script lang="ts">
  import { mediaUrl } from '$lib/api';

  interface Props {
    path?: string | null;
  }

  let { path = null }: Props = $props();
</script>

{#if path && mediaUrl(path)}
  <!-- svelte-ignore a11y_media_has_caption -->
  <video class="preview" controls src={mediaUrl(path)}></video>
{:else}
  <span class="meta">no output yet</span>
{/if}
