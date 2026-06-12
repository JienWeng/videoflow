<script lang="ts">
  /**
   * Zoomable multi-track timeline.
   *
   * All pointer math lives here: positions are seconds * pps (pixels per
   * second). One drag at a time, captured on the inner content div so moves
   * keep arriving even when the pointer leaves the block. Caption blocks are
   * movable (start+end shift together) and resizable via 8px edge handles;
   * shot blocks are fixed (durations are baked into the render).
   */
  import { Plus } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import type { Segment, Shot, Selection } from './types';

  let {
    shots,
    segments,
    totalDuration,
    pps,
    currentTime,
    selection,
    viewWidth = $bindable(0),
    onseek,
    onselect,
    ondirty,
    onaddcaption,
    oncaptiondblclick
  }: {
    shots: Shot[];
    segments: Segment[];
    totalDuration: number;
    pps: number;
    currentTime: number;
    selection: Selection;
    viewWidth?: number;
    onseek: (t: number) => void;
    onselect: (sel: Selection) => void;
    ondirty: () => void;
    onaddcaption: () => void;
    oncaptiondblclick: (i: number) => void;
  } = $props();

  const MIN_DUR = 0.3; // seconds — captions can't be resized below this
  const SNAP = 0.1; // grid for move/resize

  let inner: HTMLDivElement | undefined = $state();

  const width = $derived(Math.max(totalDuration * pps, 1));
  // Label every second when ticks are far apart, every 5s when zoomed out.
  const labelEvery = $derived(pps >= 35 ? 1 : 5);
  const ticks = $derived(
    Array.from({ length: Math.max(0, Math.floor(totalDuration)) + 1 }, (_, i) => i)
  );

  const activeShot = $derived(
    shots.findIndex((s) => currentTime >= s.start && currentTime < s.end)
  );
  const activeCaption = $derived(
    segments.findIndex((s) => currentTime >= Number(s.start) && currentTime < Number(s.end))
  );

  const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const snap = (t: number) => Math.round(t / SNAP) * SNAP;

  /** Pointer x -> timeline seconds, clamped to [0, totalDuration]. */
  function timeAt(e: PointerEvent): number {
    if (!inner || pps <= 0) return 0;
    const r = inner.getBoundingClientRect();
    return clamp((e.clientX - r.left) / pps, 0, totalDuration);
  }

  type Drag =
    | { mode: 'seek' }
    | { mode: 'move'; i: number; grab: number } // grab = pointer offset into the block (s)
    | { mode: 'resize-l' | 'resize-r'; i: number };
  let drag = $state<Drag | null>(null);

  function capture(e: PointerEvent) {
    inner?.setPointerCapture(e.pointerId);
  }

  // Background / ruler: click or drag scrubs the playhead.
  function startSeek(e: PointerEvent) {
    drag = { mode: 'seek' };
    capture(e);
    onseek(timeAt(e));
  }

  function startMove(e: PointerEvent, i: number) {
    e.stopPropagation();
    onselect({ kind: 'caption', index: i });
    drag = { mode: 'move', i, grab: timeAt(e) - Number(segments[i].start) };
    capture(e);
  }

  function startResize(e: PointerEvent, i: number, mode: 'resize-l' | 'resize-r') {
    e.stopPropagation();
    onselect({ kind: 'caption', index: i });
    drag = { mode, i };
    capture(e);
  }

  function onMove(e: PointerEvent) {
    if (!drag) return;
    const t = timeAt(e);
    if (drag.mode === 'seek') {
      onseek(t);
      return;
    }
    const seg = segments[drag.i];
    if (!seg) return;
    const start = Number(seg.start);
    const end = Number(seg.end);
    if (drag.mode === 'move') {
      const dur = end - start;
      const next = clamp(snap(t - drag.grab), 0, Math.max(0, totalDuration - dur));
      if (next !== start) {
        seg.start = next;
        seg.end = Math.round((next + dur) * 1000) / 1000;
        ondirty();
      }
    } else if (drag.mode === 'resize-l') {
      const next = clamp(snap(t), 0, snap(end - MIN_DUR));
      if (next !== start) {
        seg.start = next;
        ondirty();
      }
    } else {
      const next = clamp(snap(t), snap(start + MIN_DUR), totalDuration);
      if (next !== end) {
        seg.end = next;
        ondirty();
      }
    }
  }

  function endDrag() {
    drag = null;
  }
</script>

<div class="flex rounded-lg border border-border bg-card">
  <!-- Track gutter (fixed, outside the scroller) -->
  <div class="flex w-24 shrink-0 flex-col border-r border-border text-xs text-muted-foreground">
    <div class="h-6 border-b border-border"></div>
    <div class="flex h-14 items-center border-b border-border px-2 font-medium">Shots</div>
    <div class="flex h-14 items-center justify-between px-2 font-medium">
      <span>Captions</span>
      <Button
        variant="ghost"
        size="icon-xs"
        title="Add a 2s caption at the playhead"
        onclick={onaddcaption}
      >
        <Plus />
      </Button>
    </div>
  </div>

  <!-- Scrollable, time-scaled content -->
  <div class="min-w-0 flex-1 overflow-x-auto" bind:clientWidth={viewWidth}>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      bind:this={inner}
      class="relative select-none {drag?.mode === 'seek' ? 'cursor-grabbing' : 'cursor-pointer'}"
      style="width:{width}px; touch-action: none;"
      onpointerdown={startSeek}
      onpointermove={onMove}
      onpointerup={endDrag}
      onpointercancel={endDrag}
    >
      <!-- Ruler -->
      <div class="relative h-6 border-b border-border bg-muted/30">
        {#each ticks as t (t)}
          <div
            class="absolute bottom-0 w-px {t % labelEvery === 0 ? 'h-2.5 bg-foreground/40' : 'h-1.5 bg-border'}"
            style="left:{t * pps}px"
          ></div>
          {#if t % labelEvery === 0}
            <span
              class="absolute top-0.5 text-[10px] leading-none text-muted-foreground"
              style="left:{t * pps + 3}px"
            >
              {t}s
            </span>
          {/if}
        {/each}
      </div>

      <!-- Shots track -->
      <div class="relative h-14 border-b border-border">
        {#each shots as shot, i (i)}
          <button
            type="button"
            class="absolute inset-y-1 overflow-hidden rounded-md border px-1.5 py-1 text-left
              {selection?.kind === 'shot' && selection.index === i
              ? 'border-primary bg-primary/20 ring-1 ring-primary'
              : i === activeShot
                ? 'border-blue-400/70 bg-blue-500/15'
                : 'border-border bg-muted/60 hover:bg-muted'}"
            style="left:{shot.start * pps}px; width:{Math.max(shot.duration * pps - 2, 8)}px"
            title={shot.prompt}
            onpointerdown={(e) => e.stopPropagation()}
            onclick={() => onselect({ kind: 'shot', index: i })}
          >
            <span class="block truncate text-[10px] font-semibold leading-tight">#{shot.index}</span>
            <span class="block truncate text-[10px] leading-tight text-muted-foreground">
              {shot.prompt}
            </span>
          </button>
        {/each}
        {#if !shots.length}
          <p class="px-2 py-4 text-[10px] text-muted-foreground">No shot data for this render.</p>
        {/if}
      </div>

      <!-- Captions track -->
      <div class="relative h-14">
        {#each segments as seg, i (i)}
          <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
          <div
            class="absolute inset-y-1 cursor-grab overflow-hidden rounded-md border px-2 py-1
              {selection?.kind === 'caption' && selection.index === i
              ? 'border-primary bg-primary/20 ring-1 ring-primary'
              : i === activeCaption
                ? 'border-amber-400/70 bg-amber-500/15'
                : 'border-border bg-secondary hover:bg-muted'}"
            style="left:{Number(seg.start) * pps}px; width:{Math.max(
              (Number(seg.end) - Number(seg.start)) * pps,
              14
            )}px; z-index:{(Number(seg.end) - Number(seg.start)) * pps < 14 ? 5 : 1}"
            title={seg.text}
            onpointerdown={(e) => startMove(e, i)}
            ondblclick={() => oncaptiondblclick(i)}
          >
            <span class="block truncate text-[10px] leading-tight">{seg.text || '(empty)'}</span>
            <span class="block text-[9px] leading-tight text-muted-foreground">
              {Number(seg.start).toFixed(1)}–{Number(seg.end).toFixed(1)}s
            </span>
            <!-- Resize handles -->
            <div
              class="absolute inset-y-0 left-0 w-2 cursor-ew-resize hover:bg-primary/40"
              onpointerdown={(e) => startResize(e, i, 'resize-l')}
            ></div>
            <div
              class="absolute inset-y-0 right-0 w-2 cursor-ew-resize hover:bg-primary/40"
              onpointerdown={(e) => startResize(e, i, 'resize-r')}
            ></div>
          </div>
        {/each}
        {#if !segments.length}
          <p class="px-2 py-4 text-[10px] text-muted-foreground">
            No captions yet — use + to add one at the playhead.
          </p>
        {/if}
      </div>

      <!-- Playhead -->
      <div
        class="pointer-events-none absolute inset-y-0 z-10 w-px bg-red-500"
        style="left:{currentTime * pps}px"
      >
        <div
          class="absolute -left-[4.5px] top-0 size-0 border-x-[4.5px] border-t-[6px] border-x-transparent border-t-red-500"
        ></div>
      </div>
    </div>
  </div>
</div>
