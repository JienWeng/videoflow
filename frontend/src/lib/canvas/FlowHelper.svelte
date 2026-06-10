<script lang="ts">
  import { onMount } from 'svelte';
  import { useSvelteFlow } from '@xyflow/svelte';

  type FlowInstance = ReturnType<typeof useSvelteFlow>;

  let { register }: { register: (flow: FlowInstance) => void } = $props();

  const flow = useSvelteFlow();
  onMount(() => register(flow));
</script>
