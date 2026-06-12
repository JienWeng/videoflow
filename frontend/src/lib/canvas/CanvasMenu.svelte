<script lang="ts">
  /** Right-click context menu for canvas nodes: open / link / delink / delete.
   * Submenus stay simple — clicking a parent item swaps the menu content to a
   * choice list with a back row (no nested popovers). */
  import type { Node, Edge } from '@xyflow/svelte';
  import { toast } from 'svelte-sonner';
  import {
    PanelRight,
    Clapperboard,
    UserPlus,
    UserMinus,
    Paperclip,
    Unlink,
    Trash2,
    ChevronLeft,
    ChevronRight
  } from '@lucide/svelte';
  import { post, del } from '$lib/api';

  let {
    node,
    x,
    y,
    nodes,
    edges,
    onclose,
    onselect,
    onmutate
  }: {
    node: Node;
    x: number;
    y: number;
    nodes: Node[];
    edges: Edge[];
    onclose: () => void;
    onselect: (node: Node) => void;
    onmutate: () => Promise<void> | void;
  } = $props();

  type View =
    | 'root'
    | 'add-cast'
    | 'remove-cast'
    | 'attach-asset'
    | 'detach-asset'
    | 'add-to-scene'
    | 'attach-to-shot'
    | 'confirm-delete';
  let view = $state<View>('root');
  let busy = $state(false);
  let el: HTMLDivElement | undefined = $state();

  const kind = $derived(String(node.data?.kind ?? ''));
  const label = $derived(String(node.data?.label ?? node.id));

  const byId = $derived(new Map(nodes.map((n) => [n.id, n])));
  const kindOf = (id: string) => String(byId.get(id)?.data?.kind ?? '');
  const labelOf = (id: string) => String(byId.get(id)?.data?.label ?? id);
  const byLabel = (a: { label: string }, b: { label: string }) => a.label.localeCompare(b.label);

  function ofKind(k: string) {
    return nodes
      .filter((n) => String(n.data?.kind ?? '') === k)
      .map((n) => ({ id: n.id, label: String(n.data?.label ?? n.id) }))
      .sort(byLabel);
  }

  /** Neighbor ids of the current node along edges whose other end is `k`. */
  function linked(k: string): Set<string> {
    const ids = new Set<string>();
    for (const e of edges) {
      if (e.source === node.id && kindOf(e.target) === k) ids.add(e.target);
      if (e.target === node.id && kindOf(e.source) === k) ids.add(e.source);
    }
    return ids;
  }

  // Choice lists (derived from the already-loaded graph — no extra fetches).
  const castIds = $derived(kind === 'scene' ? linked('character') : new Set<string>());
  const castList = $derived(
    [...castIds].map((id) => ({ id, label: labelOf(id) })).sort(byLabel)
  );
  const charactersNotInCast = $derived(ofKind('character').filter((c) => !castIds.has(c.id)));
  const shotAssetIds = $derived(kind === 'shot' ? linked('asset') : new Set<string>());
  const shotAssetList = $derived(
    [...shotAssetIds].map((id) => ({ id, label: labelOf(id) })).sort(byLabel)
  );
  const assetsNotAttached = $derived(
    ofKind('asset').filter((a) => !shotAssetIds.has(a.id)).slice(0, 12)
  );
  const sceneIdsCastingMe = $derived(kind === 'character' ? linked('scene') : new Set<string>());
  const scenesNotCastingMe = $derived(ofKind('scene').filter((s) => !sceneIdsCastingMe.has(s.id)));
  const shotsForAsset = $derived(
    nodes
      .filter((n) => String(n.data?.kind ?? '') === 'shot' && !linked('shot').has(n.id))
      .map((n) => ({
        id: n.id,
        label: `${labelOf(String(n.data?.scene_id ?? ''))} #${Number(n.data?.shot_order ?? 0) + 1}`
      }))
      .sort(byLabel)
      .slice(0, 12)
  );

  async function run(op: () => Promise<unknown>, ok: string) {
    busy = true;
    try {
      await op();
      toast.success(ok);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      busy = false;
      onclose();
      await onmutate();
    }
  }

  const deleteWarning = $derived(
    kind === 'scene'
      ? `"${label}" and its shots will be deleted. Render history is kept.`
      : kind === 'shot'
        ? `"${label}" will be deleted.`
        : kind === 'character'
          ? `"${label}" will be deleted and detached from every scene cast. Its assets are kept.`
          : `"${label}" will be deleted and detached from scenes, shots, characters and the style guide.`
  );

  function confirmDelete() {
    if (kind === 'scene') run(() => del(`/scenes/${node.id}`), 'Scene deleted');
    else if (kind === 'shot') run(() => del(`/shots/${node.id}`), 'Shot deleted');
    else if (kind === 'character')
      run(() => del(`/characters/${node.id}`), 'Character deleted (detached from casts)');
    else if (kind === 'asset') run(() => del(`/assets/${node.id}`), 'Asset deleted');
  }

  function clickAway(e: PointerEvent) {
    if (el && !el.contains(e.target as globalThis.Node)) onclose();
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') onclose();
  }

  // Clamp so the menu never opens off-screen.
  const left = $derived(Math.min(x, (typeof window !== 'undefined' ? window.innerWidth : 9999) - 240));
  const top = $derived(Math.min(y, (typeof window !== 'undefined' ? window.innerHeight : 9999) - 320));

  const itemCls =
    'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs hover:bg-accent disabled:opacity-50';
</script>

<svelte:window onpointerdown={clickAway} onkeydown={key} />

<div
  bind:this={el}
  data-testid="canvas-context-menu"
  class="fixed z-50 w-56 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
  style="left: {left}px; top: {top}px"
  role="menu"
  tabindex="-1"
  oncontextmenu={(e) => e.preventDefault()}
>
  {#if view === 'root'}
    <div class="truncate px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground" title={label}>
      {kind.replace('_', ' ')} — {label}
    </div>
    <button class={itemCls} role="menuitem" onclick={() => { onselect(node); onclose(); }}>
      <PanelRight class="size-3.5" />Open details
    </button>
    {#if kind === 'output'}
      <a class={itemCls} role="menuitem" href={`/editor/${node.id}`}>
        <Clapperboard class="size-3.5" />Open in editor
      </a>
    {/if}

    {#if kind === 'scene'}
      <button class={itemCls} role="menuitem" disabled={!charactersNotInCast.length} onclick={() => (view = 'add-cast')}>
        <UserPlus class="size-3.5" />Add character to cast<ChevronRight class="ml-auto size-3" />
      </button>
      <button class={itemCls} role="menuitem" disabled={!castList.length} onclick={() => (view = 'remove-cast')}>
        <UserMinus class="size-3.5" />Remove from cast<ChevronRight class="ml-auto size-3" />
      </button>
    {:else if kind === 'shot'}
      <button class={itemCls} role="menuitem" disabled={!assetsNotAttached.length} onclick={() => (view = 'attach-asset')}>
        <Paperclip class="size-3.5" />Attach asset<ChevronRight class="ml-auto size-3" />
      </button>
      <button class={itemCls} role="menuitem" disabled={!shotAssetList.length} onclick={() => (view = 'detach-asset')}>
        <Unlink class="size-3.5" />Detach asset<ChevronRight class="ml-auto size-3" />
      </button>
    {:else if kind === 'character'}
      <button class={itemCls} role="menuitem" disabled={!scenesNotCastingMe.length} onclick={() => (view = 'add-to-scene')}>
        <Clapperboard class="size-3.5" />Add to scene<ChevronRight class="ml-auto size-3" />
      </button>
    {:else if kind === 'asset'}
      <button class={itemCls} role="menuitem" disabled={!shotsForAsset.length} onclick={() => (view = 'attach-to-shot')}>
        <Paperclip class="size-3.5" />Attach to shot<ChevronRight class="ml-auto size-3" />
      </button>
    {/if}

    {#if kind !== 'render_job' && kind !== 'output'}
      <div class="my-1 h-px bg-border"></div>
      <button class="{itemCls} text-destructive hover:bg-destructive/10" role="menuitem" onclick={() => (view = 'confirm-delete')}>
        <Trash2 class="size-3.5" />Delete {kind}…
      </button>
    {/if}
  {:else if view === 'confirm-delete'}
    <div class="px-2 py-1.5 text-xs text-muted-foreground">{deleteWarning}</div>
    <div class="flex gap-1 p-1">
      <button class="{itemCls} justify-center border border-border" onclick={() => (view = 'root')}>Cancel</button>
      <button
        class="{itemCls} justify-center bg-destructive text-destructive-foreground hover:bg-destructive/90"
        data-testid="confirm-delete"
        disabled={busy}
        onclick={confirmDelete}
      >
        {busy ? 'Deleting…' : 'Delete'}
      </button>
    </div>
  {:else}
    {@const choices =
      view === 'add-cast' ? charactersNotInCast
      : view === 'remove-cast' ? castList
      : view === 'attach-asset' ? assetsNotAttached
      : view === 'detach-asset' ? shotAssetList
      : view === 'add-to-scene' ? scenesNotCastingMe
      : shotsForAsset}
    <button class={itemCls} onclick={() => (view = 'root')}>
      <ChevronLeft class="size-3.5" />Back
    </button>
    <div class="my-1 h-px bg-border"></div>
    <div class="max-h-56 overflow-y-auto">
      {#each choices as choice (choice.id)}
        <button
          class={itemCls}
          role="menuitem"
          disabled={busy}
          onclick={() => {
            if (view === 'add-cast')
              run(() => post(`/scenes/${node.id}/cast/${choice.id}`), `Added ${choice.label} to cast`);
            else if (view === 'remove-cast')
              run(() => del(`/scenes/${node.id}/cast/${choice.id}`), `Removed ${choice.label} from cast`);
            else if (view === 'attach-asset')
              run(() => post(`/shots/${node.id}/assets/${choice.id}`), `Attached ${choice.label}`);
            else if (view === 'detach-asset')
              run(() => del(`/shots/${node.id}/assets/${choice.id}`), `Detached ${choice.label}`);
            else if (view === 'add-to-scene')
              run(() => post(`/scenes/${choice.id}/cast/${node.id}`), `Added to ${choice.label}`);
            else run(() => post(`/shots/${choice.id}/assets/${node.id}`), `Attached to ${choice.label}`);
          }}
        >
          <span class="truncate">{choice.label}</span>
        </button>
      {:else}
        <div class="px-2 py-1.5 text-xs text-muted-foreground">Nothing available</div>
      {/each}
    </div>
  {/if}
</div>
