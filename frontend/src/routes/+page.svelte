<script lang="ts">
  import EntityCanvas from '$lib/canvas/EntityCanvas.svelte';
  import NodePanel from '$lib/canvas/NodePanel.svelte';
  import ChatPanel from '$lib/chat/ChatPanel.svelte';
  import type { Node } from '@xyflow/svelte';

  let canvas: EntityCanvas | undefined = $state();
  let selected = $state<Node | null>(null);
</script>

<div class="h-full flex">
  <div class="flex-1 min-w-0">
    <EntityCanvas bind:this={canvas} onselect={(n) => (selected = n)} />
  </div>
  <div class="w-96 border-l border-border">
    <ChatPanel onfocus={(id) => canvas?.focusNode(id)} onmutate={() => canvas?.refresh()} />
  </div>
</div>
<NodePanel node={selected} onclose={() => (selected = null)} onsaved={() => canvas?.refresh()} />
