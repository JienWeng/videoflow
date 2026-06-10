<script lang="ts">
  import { PaneGroup, Pane, Handle } from '$lib/components/ui/resizable';
  import EntityCanvas from '$lib/canvas/EntityCanvas.svelte';
  import NodePanel from '$lib/canvas/NodePanel.svelte';
  import ChatPanel from '$lib/chat/ChatPanel.svelte';
  import { subscribeJobs } from '$lib/sse';
  import { onMount } from 'svelte';
  import type { Node } from '@xyflow/svelte';

  let canvas: EntityCanvas | undefined = $state();
  let selected = $state<Node | null>(null);

  onMount(() =>
    subscribeJobs(
      () => canvas?.refresh(),
      () => canvas?.refresh()
    )
  );
</script>

<PaneGroup direction="horizontal" class="h-full">
  <Pane defaultSize={72} minSize={40}>
    <EntityCanvas bind:this={canvas} onselect={(n) => (selected = n)} />
  </Pane>
  <Handle withHandle />
  <Pane defaultSize={28} minSize={20}>
    <div class="h-full border-l border-border">
      <ChatPanel onfocus={(id) => canvas?.focusNode(id)} onmutate={() => canvas?.refresh()} />
    </div>
  </Pane>
</PaneGroup>

<NodePanel node={selected} onclose={() => (selected = null)} onsaved={() => canvas?.refresh()} />
