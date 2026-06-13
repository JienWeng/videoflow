<script lang="ts">
  import { mediaUrl } from '$lib/api';
  import { Film } from '@lucide/svelte';

  // A compact, selectable scene row for the master list. All derivation is done
  // by the parent and passed in so the list and detail share one source of truth.
  let {
    scene,
    selected = false,
    statusLine,
    accentDot,
    dirty = false,
    steps,
    storyboard = null,
    onselect
  }: {
    scene: any;
    selected?: boolean;
    statusLine: string;
    accentDot: string;
    dirty?: boolean;
    steps: { key: string; label: string; done: boolean }[];
    storyboard?: any;
    onselect: () => void;
  } = $props();

  // First not-done step → the "next" micro-indicator (null when all done). The
  // parent computes each step's `done` with the later-done rule, so this never
  // points at an "earlier" stage once a later one is complete.
  const nextStep = $derived(steps.find((st) => !st.done) ?? null);
</script>

<button
  type="button"
  onclick={onselect}
  class="group flex w-full items-start gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors
         {selected
    ? 'border-primary/60 bg-accent'
    : 'border-transparent hover:border-border hover:bg-accent/50'}"
>
  <!-- Thumbnail (storyboard) or status dot -->
  {#if storyboard}
    <img
      class="size-10 shrink-0 rounded-md border border-border object-cover"
      src={mediaUrl(storyboard.file_path)}
      alt=""
      loading="lazy"
    />
  {:else}
    <div class="flex size-10 shrink-0 items-center justify-center rounded-md border border-dashed border-border bg-muted/30 text-muted-foreground/50">
      <Film class="size-4" />
    </div>
  {/if}

  <div class="min-w-0 flex-1">
    <div class="flex items-center gap-1.5">
      <span class="size-2 shrink-0 rounded-full {accentDot}"></span>
      <span class="truncate text-sm font-medium" title={scene.title}>
        {scene.title || 'Untitled scene'}
      </span>
      {#if dirty}
        <span class="ml-auto shrink-0 rounded-sm bg-amber-500/15 px-1 text-[10px] font-medium text-amber-600"
          title="Unsaved edits">unsaved</span>
      {/if}
    </div>
    <p class="mt-0.5 truncate text-xs text-muted-foreground">{statusLine}</p>

    <!-- Stepper as 4 tiny dots + a faint "Next:" hint — the list is a monitor. -->
    <div class="mt-1.5 flex items-center gap-1.5">
      <div class="flex items-center gap-1">
        {#each steps as st (st.key)}
          <span
            class="size-1.5 rounded-full {st.done ? 'bg-primary/70' : 'bg-border'}"
            title={st.label}
          ></span>
        {/each}
      </div>
      {#if nextStep}
        <span class="truncate text-[10px] text-muted-foreground/70">Next: {nextStep.label}</span>
      {:else}
        <span class="truncate text-[10px] text-emerald-600/80">Complete</span>
      {/if}
    </div>
  </div>
</button>
