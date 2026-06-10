<script lang="ts">
  import { mediaUrl } from '$lib/api';

  export let path: string | null = null;
</script>

{#if path && mediaUrl(path)}
  <!-- svelte-ignore a11y-media-has-caption -->
  <video class="preview" controls src={mediaUrl(path)} />
{:else}
  <span class="meta">no output yet</span>
{/if}
