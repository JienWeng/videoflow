<script lang="ts">
  import EntityCanvas from '$lib/canvas/EntityCanvas.svelte';
  import NodePanel from '$lib/canvas/NodePanel.svelte';
  import type { Node } from '@xyflow/svelte';

  let canvas: EntityCanvas | undefined = $state();
  let selected = $state<Node | null>(null);
</script>

<div class="h-full">
  <EntityCanvas bind:this={canvas} onselect={(n) => (selected = n)} />
</div>
<NodePanel node={selected} onclose={() => (selected = null)} onsaved={() => canvas?.refresh()} />
