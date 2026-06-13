<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import {
    SvelteFlow,
    ConnectionMode,
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
  import {
    LayoutGrid,
    Plus,
    Clapperboard,
    Users,
    Image,
    ChevronLeft,
    MousePointerClick,
    Palette,
    ChevronDown,
    X
  } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { get, post, del } from '$lib/api';
  import {
    toFlow,
    loadPositions,
    savePositions,
    clearPositions,
    kindColor,
    edgeColor,
    LEGEND_KINDS,
    KIND_LABELS,
    type ApiGraph
  } from './transform';
  import { layout, layoutFresh } from './layout';
  import EntityNode from './EntityNode.svelte';
  import FlowHelper from './FlowHelper.svelte';
  import CanvasMenu from './CanvasMenu.svelte';
  import NodePanel from './NodePanel.svelte';

  let { onselect }: { onselect: (node: Node | null) => void } = $props();

  let nodes = $state.raw<Node[]>([]);
  let edges = $state.raw<Edge[]>([]);
  let flow: ReturnType<typeof useSvelteFlow> | undefined;

  // Right-click context menu (CanvasMenu) — null when closed. `view` lets the
  // Delete/Backspace gesture open it straight on the confirm-delete step.
  let menu = $state<{ node: Node; x: number; y: number; view?: 'root' | 'confirm-delete' } | null>(
    null
  );
  // "+" add menu in the top-right panel.
  let addOpen = $state(false);
  let addMode = $state<'root' | 'scene' | 'character'>('root');
  let addName = $state('');
  let addBusy = $state(false);
  let addEl: HTMLDivElement | undefined = $state();

  // Header / legend / coachmark UI state.
  let legendOpen = $state(false);
  // Coachmark dismissal persists so the hint shows once per browser, not forever.
  let coachDismissed = $state(true);
  // The node whose detail panel is open (docked inside this canvas pane). Driven
  // by clicks/context-menu so the panel never covers the chat or the minimap.
  let panelNode = $state<Node | null>(null);
  // True once /graph has answered at least once (so the header reads honestly).
  let loaded = $state(false);

  const nodeTypes = { entity: EntityNode };

  // Currently hovered edge id — used to reveal that edge's relationship label
  // even when nothing is selected.
  let hoveredEdge = $state<string | null>(null);
  // Last edge clicked — tracked here so the highlight/label + keyboard-detach
  // gesture don't depend on xyflow's internal edge selection (which our restyle
  // effect already overwrites with our own `selected` flag).
  let selectedEdge = $state<string | null>(null);

  // Which node's relationships to highlight. Driven by the docked panel's node.
  const selectedNodeId = $derived(panelNode?.id ?? null);

  /** Pure restyle pass: edges incident to the highlighted node stay vivid +
   * labelled + animated, the rest dim; a hovered/clicked edge reveals its
   * label. Color/arrowheads come from the relationship type. Operates on the
   * given list so it can run both reactively and right after a refresh. */
  function styleEdges(list: Edge[], sel: string | null, hov: string | null, selE: string | null): Edge[] {
    return list.map((e) => {
      const rel = String((e.data as any)?.rel ?? '');
      const color = edgeColor(rel || undefined);
      const incident = !sel || e.source === sel || e.target === sel;
      const dim = sel != null && !incident;
      const active = e.id === hov || e.id === selE;
      const showLabel = ((sel != null && incident) || active) && !!rel;
      return {
        ...e,
        selected: e.id === selE,
        label: showLabel ? rel : undefined,
        // The Svelte edge label is an HTML div; labelStyle is applied as its
        // style string, so the chip background lives here (React-flow's
        // labelBgStyle/labelBgPadding props are ignored by Svelte Flow).
        labelStyle:
          'color: hsl(0 0% 88%); font-size: 10px; padding: 1px 5px; border-radius: 6px; ' +
          'background: hsl(0 0% 9% / 0.92); border: 1px solid ' +
          color +
          '; white-space: nowrap;',
        animated: (sel != null && incident) || active,
        style: `stroke: ${color}; stroke-opacity: ${dim ? 0.12 : 1}; stroke-width: ${
          (incident && sel != null) || active ? 2 : 1.5
        }px;`,
        markerEnd: { ...(e.markerEnd as any), color, width: 16, height: 16 }
      } as Edge;
    });
  }

  // Restyle edges reactively WITHOUT replacing the bound array out from under
  // xyflow: this effect depends only on the highlight inputs (selection / hover
  // / clicked edge) and reads `edges` via untrack, so xyflow's own writes to
  // `edges` (geometry, internal selection) never retrigger it — no feedback
  // loop.
  $effect(() => {
    const sel = selectedNodeId;
    const hov = hoveredEdge;
    const selE = selectedEdge;
    untrack(() => {
      if (edges.length) edges = styleEdges(edges, sel, hov, selE);
    });
  });

  export async function refresh() {
    try {
      const g: ApiGraph = await get('/graph');
      const { nodes: n, edges: e } = toFlow(g);
      const firstLoad = !loaded;
      // Pinned (saved) nodes keep their spots; fresh nodes get collision-free
      // dagre positions. After autoArrange clears the saved store, this is a
      // pure dagre layout until the user drags a node again.
      nodes = layoutFresh(n, e, loadPositions());
      // Re-apply the current highlight so a background refresh (SSE job update)
      // while a node panel is open doesn't flash the dimming/labels away.
      edges = styleEdges(e, selectedNodeId, hoveredEdge, selectedEdge);
      loaded = true;
      // Coachmark: only the first time a non-empty graph appears, and only if
      // the user hasn't dismissed it before.
      if (firstLoad) {
        try {
          coachDismissed = localStorage.getItem('videoflow.canvas.coach') === '1';
        } catch {
          coachDismissed = false;
        }
        if (n.length) focusNewestScene();
      }
    } catch (err: any) {
      toast.error(`Failed to load graph: ${err.message}`);
      loaded = true;
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
    if (node) {
      panelNode = node;
      onselect(node);
    }
    flow?.fitView({ nodes: [{ id }], duration: 400, maxZoom: 1.5 });
  }

  /** Open the canvas centred on the most recent scene cluster rather than
   * fit-all (which shrinks a busy graph into illegible specks). Falls back to
   * the plain fitView if there are no scenes yet. */
  function focusNewestScene() {
    const scenes = nodes.filter((n) => String(n.data?.kind ?? '') === 'scene');
    if (!scenes.length) return;
    // "Newest" = the scene placed lowest-then-rightmost by the layout, a decent
    // proxy for most-recently-added without a created_at on the graph node.
    const newest = scenes.reduce((a, b) =>
      b.position.y > a.position.y || (b.position.y === a.position.y && b.position.x > a.position.x)
        ? b
        : a
    );
    // Pull in the scene plus its direct neighbours so the cluster reads as a unit.
    const around = new Set<string>([newest.id]);
    for (const e of edges) {
      if (e.source === newest.id) around.add(e.target);
      if (e.target === newest.id) around.add(e.source);
    }
    flow?.fitView({
      nodes: [...around].map((id) => ({ id })),
      duration: 500,
      padding: 0.25,
      maxZoom: 1.1
    });
  }

  onMount(() => {
    refresh();
  });

  function dismissCoach() {
    coachDismissed = true;
    try {
      localStorage.setItem('videoflow.canvas.coach', '1');
    } catch {
      // ignore storage failures — the coachmark just reappears next load
    }
  }

  function selectNode(node: Node | null) {
    panelNode = node;
    onselect(node);
  }

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
        // Invalid pair: the dropped edge was never committed to the DOM by
        // xyflow's onconnect path the way a node delete is, so there's nothing
        // to undo — just tell the user. No refresh() (it would needlessly
        // re-fetch and reset the viewport on a no-op).
        toast.error('Connect character↔scene or asset↔shot');
        return;
      }
      toast.success('Connected');
      await refresh();
    } catch (err: any) {
      toast.error(err.message);
      await refresh();
    }
  }

  /** Detach a single relationship edge. Shared by the keyboard gesture and the
   * native ondelete path. Returns true if it mapped to a real detach. */
  async function detachEdge(edge: Edge): Promise<boolean> {
    const sk = kindOf(edge.source);
    const tk = kindOf(edge.target);
    if (sk === 'scene' && tk === 'character') {
      await del(`/scenes/${edge.source}/cast/${edge.target}`);
    } else if (sk === 'character' && tk === 'scene') {
      await del(`/scenes/${edge.target}/cast/${edge.source}`);
    } else if (sk === 'shot' && tk === 'asset') {
      await del(`/shots/${edge.source}/assets/${edge.target}`);
    } else if (sk === 'asset' && tk === 'shot') {
      await del(`/shots/${edge.target}/assets/${edge.source}`);
    } else {
      return false;
    }
    return true;
  }

  async function handleDelete({
    nodes: deletedNodes,
    edges: deleted
  }: {
    nodes: Node[];
    edges: Edge[];
  }) {
    // With deleteKey disabled, this path only fires for programmatic deletes; we
    // keep edge handling here so the relationship-detach UX stays intact.
    if (deletedNodes.length) {
      await refresh();
      return;
    }
    let changed = false;
    for (const edge of deleted) {
      try {
        if (await detachEdge(edge)) changed = true;
        else toast.error('Only character casts and shot assets can be detached');
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

  /** Delete/Backspace gesture: route the selected node into the SAME
   * confirm-delete flow the context menu uses (no error toast), and let a
   * selected edge fall through to the detach flow. Ignored while typing. */
  function onWindowKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      closeAddMenu();
      return;
    }
    if (e.key !== 'Delete' && e.key !== 'Backspace') return;
    const t = e.target as HTMLElement | null;
    if (
      t &&
      (t.tagName === 'INPUT' ||
        t.tagName === 'TEXTAREA' ||
        t.isContentEditable ||
        t.closest('[data-testid="canvas-context-menu"]'))
    ) {
      return;
    }
    const selNode = nodes.find((n) => n.selected) ?? panelNode ?? null;
    if (selNode) {
      e.preventDefault();
      const kind = String(selNode.data?.kind ?? '');
      // render_job / output have no delete affordance in the context menu, so
      // the gesture is a no-op for them rather than a confusing error.
      if (kind === 'render_job' || kind === 'output') return;
      menu = {
        node: selNode,
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        view: 'confirm-delete'
      };
      return;
    }
    if (selectedEdge) {
      const edge = edges.find((ed) => ed.id === selectedEdge);
      if (edge) {
        e.preventDefault();
        selectedEdge = null;
        void handleDelete({ nodes: [], edges: [edge] });
      }
    }
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
</script>

<!-- relative wrapper: anchors the docked NodePanel as an absolute card *inside*
  the canvas pane, so it never overlaps the chat composer or the minimap. -->
<div class="relative h-full w-full">
  <SvelteFlow
    bind:nodes
    bind:edges
    {nodeTypes}
    connectionMode={ConnectionMode.Loose}
    fitView
    fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
    minZoom={0.1}
    deleteKey={null}
    colorMode="dark"
    proOptions={{ hideAttribution: true }}
    onconnect={handleConnect}
    ondelete={handleDelete}
    onnodeclick={({ node }) => {
      selectedEdge = null;
      selectNode(node);
    }}
    onnodecontextmenu={openContextMenu}
    onpaneclick={() => {
      selectedEdge = null;
      selectNode(null);
    }}
    onedgeclick={({ edge }) => (selectedEdge = edge.id)}
    onedgepointerenter={({ edge }) => (hoveredEdge = edge.id)}
    onedgepointerleave={() => (hoveredEdge = null)}
    onnodedragstop={() => savePositions(nodes)}
  >
    <FlowHelper register={(f) => (flow = f)} />

    <!-- Header + controls + legend live as ONE left-docked column. Keeping
      everything on the left frees the entire right edge for the docked detail
      panel, so opening a node never hides the add/arrange controls. -->
    <Panel position="top-left" class="z-10">
      <div class="flex flex-col gap-1.5">
        <div
          class="flex items-center gap-1.5 rounded-md border border-border bg-card/90 px-2 py-1.5 shadow-sm backdrop-blur"
        >
          <Clapperboard class="size-3.5 text-muted-foreground" />
          <span class="text-xs font-medium">Story canvas</span>
          {#if loaded}
            <span class="text-[10px] text-muted-foreground">· {nodes.length}</span>
          {/if}
          <div class="mx-0.5 h-4 w-px bg-border"></div>
          <div class="relative" bind:this={addEl}>
            <Button
              variant="ghost"
              size="icon-sm"
              title="Add entity"
              data-testid="canvas-add"
              onclick={() => (addOpen ? closeAddMenu() : (addOpen = true))}
            >
              <Plus class="size-4" />
            </Button>
            {#if addOpen}
              <div
                class="absolute left-0 top-9 z-20 w-52 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
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
                    onclick={() => {
                      addMode = 'root';
                      addName = '';
                    }}
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
                    <Button
                      size="sm"
                      class="h-7 px-2 text-xs"
                      disabled={!addName.trim() || addBusy}
                      onclick={createEntity}
                    >
                      {addBusy ? '…' : 'Add'}
                    </Button>
                  </div>
                {/if}
              </div>
            {/if}
          </div>
          <Button variant="ghost" size="icon-sm" title="Auto-arrange" onclick={autoArrange}>
            <LayoutGrid class="size-4" />
          </Button>
          <button
            class="flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-accent"
            title="Toggle color legend"
            onclick={() => (legendOpen = !legendOpen)}
          >
            <Palette class="size-3" />
            <ChevronDown class="size-3 transition-transform {legendOpen ? 'rotate-180' : ''}" />
          </button>
        </div>
        {#if legendOpen}
          <div
            class="flex flex-col gap-1 rounded-md border border-border bg-card/90 p-2 shadow-sm backdrop-blur"
            data-testid="canvas-legend"
          >
            {#each LEGEND_KINDS as k (k)}
              <div class="flex items-center gap-2 text-[11px]">
                <span
                  class="inline-block size-2.5 rounded-full"
                  style="background: {kindColor(k)}"
                ></span>
                <span class="text-muted-foreground">{KIND_LABELS[k] ?? k}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </Panel>

    <!-- Persistent help affordance / first-node coachmark. Bottom-center so it
      clears the Controls (bottom-left) and the MiniMap (bottom-right). -->
    {#if loaded && nodes.length > 0 && !coachDismissed}
      <Panel position="bottom-center" class="z-10">
        <div
          class="flex items-center gap-2 rounded-full border border-border bg-card/95 px-3 py-1.5 text-[11px] text-muted-foreground shadow-md backdrop-blur"
          data-testid="canvas-coachmark"
        >
          <MousePointerClick class="size-3.5 shrink-0 text-foreground" />
          <span>Right-click a node for actions · drag from a node edge to connect</span>
          <button
            class="ml-1 rounded-sm p-0.5 hover:bg-accent hover:text-foreground"
            title="Dismiss"
            onclick={dismissCoach}
          >
            <X class="size-3" />
          </button>
        </div>
      </Panel>
    {/if}

    <Background />
    <Controls />
    <MiniMap pannable zoomable nodeColor={(n) => kindColor(String(n.data?.kind ?? ''))} />
  </SvelteFlow>

  <!-- Docked detail panel: absolutely positioned inside this pane (top-right),
    NOT a viewport-fixed full-height slab, so the chat + minimap stay reachable. -->
  <NodePanel
    node={panelNode}
    onclose={() => selectNode(null)}
    onsaved={refresh}
  />
</div>

<svelte:window onpointerdown={addClickAway} onkeydown={onWindowKeydown} />

{#if menu}
  <CanvasMenu
    node={menu.node}
    x={menu.x}
    y={menu.y}
    initialView={menu.view ?? 'root'}
    {nodes}
    {edges}
    onclose={() => (menu = null)}
    onselect={selectNode}
    onmutate={refresh}
  />
{/if}
