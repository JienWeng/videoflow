<script lang="ts">
  import { onMount } from 'svelte';
  import {
    SvelteFlow,
    Background,
    Controls,
    MiniMap,
    Panel,
    useSvelteFlow,
    type Node,
    type Edge,
    type Connection
  } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { toast } from 'svelte-sonner';
  import { LayoutGrid, Plus, Clapperboard, Users, Image, ChevronLeft } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { get, post, del } from '$lib/api';
  import { toFlow, loadPositions, savePositions, clearPositions, kindColor, type ApiGraph } from './transform';
  import { layout, layoutFresh } from './layout';
  import EntityNode from './EntityNode.svelte';
  import FlowHelper from './FlowHelper.svelte';
  import CanvasMenu from './CanvasMenu.svelte';

  let { onselect }: { onselect: (node: Node | null) => void } = $props();

  let nodes = $state.raw<Node[]>([]);
  let edges = $state.raw<Edge[]>([]);
  let flow: ReturnType<typeof useSvelteFlow> | undefined;

  // Right-click context menu (CanvasMenu) — null when closed.
  let menu = $state<{ node: Node; x: number; y: number } | null>(null);
  // "+" add menu in the top-right panel.
  let addOpen = $state(false);
  let addMode = $state<'root' | 'scene' | 'character'>('root');
  let addName = $state('');
  let addBusy = $state(false);
  let addEl: HTMLDivElement | undefined = $state();

  const nodeTypes = { entity: EntityNode };

  export async function refresh() {
    try {
      const g: ApiGraph = await get('/graph');
      const { nodes: n, edges: e } = toFlow(g);
      // Pinned (saved) nodes keep their spots; fresh nodes get collision-free
      // dagre positions. After autoArrange clears the saved store, this is a
      // pure dagre layout until the user drags a node again.
      nodes = layoutFresh(n, e, loadPositions());
      edges = e;
    } catch (err: any) {
      toast.error(`Failed to load graph: ${err.message}`);
    }
  }

  export function autoArrange() {
    clearPositions();
    nodes = layout(nodes, edges);
    flow?.fitView({ duration: 400, padding: 0.1, minZoom: 0.1 });
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

  function openContextMenu({ node, event }: { node: Node; event: MouseEvent }) {
    event.preventDefault();
    menu = { node, x: event.clientX, y: event.clientY };
  }

  function closeAddMenu() {
    addOpen = false;
    addMode = 'root';
    addName = '';
  }

  async function createEntity() {
    const name = addName.trim();
    if (!name || addBusy) return;
    addBusy = true;
    try {
      const created =
        addMode === 'scene'
          ? await post('/scenes', { title: name })
          : await post('/characters', { name });
      toast.success(`${addMode === 'scene' ? 'Scene' : 'Character'} "${name}" created`);
      closeAddMenu();
      await refresh();
      focusNode(created.id);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      addBusy = false;
    }
  }

  function addClickAway(e: PointerEvent) {
    if (addOpen && addEl && !addEl.contains(e.target as globalThis.Node)) closeAddMenu();
  }
  function addKey(e: KeyboardEvent) {
    if (e.key === 'Escape') closeAddMenu();
  }
</script>

<div class="h-full w-full">
  <SvelteFlow
    bind:nodes
    bind:edges
    {nodeTypes}
    fitView
    fitViewOptions={{ padding: 0.1 }}
    minZoom={0.1}
    colorMode="dark"
    proOptions={{ hideAttribution: true }}
    onconnect={handleConnect}
    ondelete={handleDelete}
    onnodeclick={({ node }) => onselect(node)}
    onnodecontextmenu={openContextMenu}
    onpaneclick={() => onselect(null)}
    onnodedragstop={() => savePositions(nodes)}
  >
    <FlowHelper register={(f) => (flow = f)} />
    <Panel position="top-right" class="z-10">
      <div class="flex items-start gap-2">
        <div class="relative" bind:this={addEl}>
          <Button variant="secondary" size="icon" title="Add entity" data-testid="canvas-add" onclick={() => (addOpen ? closeAddMenu() : (addOpen = true))}>
            <Plus />
          </Button>
          {#if addOpen}
            <div
              class="absolute right-0 top-10 w-52 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
              data-testid="canvas-add-menu"
            >
              {#if addMode === 'root'}
                <button
                  class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs hover:bg-accent"
                  onclick={() => (addMode = 'scene')}
                >
                  <Clapperboard class="size-3.5" />New scene
                </button>
                <button
                  class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs hover:bg-accent"
                  onclick={() => (addMode = 'character')}
                >
                  <Users class="size-3.5" />New character
                </button>
                <a
                  class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs hover:bg-accent"
                  href="/assets"
                >
                  <Image class="size-3.5" />Upload asset
                </a>
              {:else}
                <button
                  class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs hover:bg-accent"
                  onclick={() => { addMode = 'root'; addName = ''; }}
                >
                  <ChevronLeft class="size-3.5" />Back
                </button>
                <div class="flex items-center gap-1 p-1">
                  <!-- svelte-ignore a11y_autofocus -->
                  <Input
                    class="h-7 text-xs"
                    placeholder={addMode === 'scene' ? 'Scene title' : 'Character name'}
                    autofocus
                    bind:value={addName}
                    onkeydown={(e: KeyboardEvent) => e.key === 'Enter' && createEntity()}
                  />
                  <Button size="sm" class="h-7 px-2 text-xs" disabled={!addName.trim() || addBusy} onclick={createEntity}>
                    {addBusy ? '…' : 'Add'}
                  </Button>
                </div>
              {/if}
            </div>
          {/if}
        </div>
        <Button variant="secondary" size="icon" title="Auto-arrange" onclick={autoArrange}>
          <LayoutGrid />
        </Button>
      </div>
    </Panel>
    <Background />
    <Controls />
    <MiniMap pannable zoomable nodeColor={(n) => kindColor(String(n.data?.kind ?? ''))} />
  </SvelteFlow>
</div>

<svelte:window onpointerdown={addClickAway} onkeydown={addKey} />

{#if menu}
  <CanvasMenu
    node={menu.node}
    x={menu.x}
    y={menu.y}
    {nodes}
    {edges}
    onclose={() => (menu = null)}
    {onselect}
    onmutate={refresh}
  />
{/if}
