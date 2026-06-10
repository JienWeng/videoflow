<script lang="ts">
  import { onMount } from 'svelte';
  import {
    SvelteFlow,
    Background,
    Controls,
    MiniMap,
    useSvelteFlow,
    type Node,
    type Edge,
    type Connection
  } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { toast } from 'svelte-sonner';
  import { get, post, del } from '$lib/api';
  import { toFlow, loadPositions, savePositions, type ApiGraph } from './transform';
  import { layout } from './layout';
  import EntityNode from './EntityNode.svelte';
  import FlowHelper from './FlowHelper.svelte';

  let { onselect }: { onselect: (node: Node | null) => void } = $props();

  let nodes = $state.raw<Node[]>([]);
  let edges = $state.raw<Edge[]>([]);
  let flow: ReturnType<typeof useSvelteFlow> | undefined;

  const nodeTypes = { entity: EntityNode };

  export async function refresh() {
    try {
      const g: ApiGraph = await get('/graph');
      const { nodes: n, edges: e } = toFlow(g);
      const laidOut = layout(n, e);
      const saved = loadPositions();
      nodes = laidOut.map((node) =>
        saved[node.id] ? { ...node, position: saved[node.id] } : node
      );
      edges = e;
    } catch (err: any) {
      toast.error(`Failed to load graph: ${err.message}`);
    }
  }

  export function focusNode(id: string) {
    nodes = nodes.map((n) => ({ ...n, selected: n.id === id }));
    const node = nodes.find((n) => n.id === id);
    if (node) onselect(node);
    flow?.fitView({ nodes: [{ id }], duration: 400, maxZoom: 1.5 });
  }

  onMount(() => {
    refresh();
  });

  function kindOf(id: string): string {
    return String(nodes.find((n) => n.id === id)?.data?.kind ?? '');
  }

  async function handleConnect(conn: Connection) {
    const sk = kindOf(conn.source);
    const tk = kindOf(conn.target);
    try {
      if (sk === 'character' && tk === 'scene') {
        await post(`/scenes/${conn.target}/cast/${conn.source}`);
      } else if (sk === 'scene' && tk === 'character') {
        await post(`/scenes/${conn.source}/cast/${conn.target}`);
      } else if (sk === 'asset' && tk === 'shot') {
        await post(`/shots/${conn.target}/assets/${conn.source}`);
      } else if (sk === 'shot' && tk === 'asset') {
        await post(`/shots/${conn.source}/assets/${conn.target}`);
      } else {
        toast.error('Connect character→scene or asset→shot');
        await refresh();
        return;
      }
      toast.success('Connected');
    } catch (err: any) {
      toast.error(err.message);
    }
    await refresh();
  }

  async function handleDelete({ nodes: deletedNodes, edges: deleted }: { nodes: Node[]; edges: Edge[] }) {
    if (deletedNodes.length) {
      // Entities can't be deleted from the canvas; restore and bail before the
      // node's connected edges get misread as intentional detaches.
      toast.error('Delete relationships (edges), not entities');
      await refresh();
      return;
    }
    let changed = false;
    for (const edge of deleted) {
      const sk = kindOf(edge.source);
      const tk = kindOf(edge.target);
      try {
        if (sk === 'scene' && tk === 'character') {
          await del(`/scenes/${edge.source}/cast/${edge.target}`);
          changed = true;
        } else if (sk === 'character' && tk === 'scene') {
          await del(`/scenes/${edge.target}/cast/${edge.source}`);
          changed = true;
        } else if (sk === 'shot' && tk === 'asset') {
          await del(`/shots/${edge.source}/assets/${edge.target}`);
          changed = true;
        } else if (sk === 'asset' && tk === 'shot') {
          await del(`/shots/${edge.target}/assets/${edge.source}`);
          changed = true;
        } else {
          toast.error('Only character casts and shot assets can be detached');
        }
      } catch (err: any) {
        toast.error(err.message);
      }
    }
    if (changed) toast.success('Detached');
    await refresh();
  }
</script>

<div class="h-full w-full">
  <SvelteFlow
    bind:nodes
    bind:edges
    {nodeTypes}
    fitView
    colorMode="dark"
    proOptions={{ hideAttribution: true }}
    onconnect={handleConnect}
    ondelete={handleDelete}
    onnodeclick={({ node }) => onselect(node)}
    onpaneclick={() => onselect(null)}
    onnodedragstop={() => savePositions(nodes)}
  >
    <FlowHelper register={(f) => (flow = f)} />
    <Background />
    <Controls />
    <MiniMap />
  </SvelteFlow>
</div>
