<script lang="ts">
  /**
   * First-run welcome overlay. Explains the three surfaces of the Studio and
   * the 3-step path to a first video, then gets out of the way. Dismissal is
   * persisted in localStorage['videoflow.onboarded'] so it shows exactly once.
   *
   * Rendered only on the Studio route (see +page.svelte). Closing — via the
   * button, the backdrop, or Escape — sets the flag; "Show me around" also
   * opens the command palette so the user lands somewhere actionable.
   */
  import { Button } from '$lib/components/ui/button';
  import {
    LayoutGrid,
    MessageSquare,
    PanelLeft,
    Sparkles,
    Command,
    X
  } from '@lucide/svelte';

  const STORAGE_KEY = 'videoflow.onboarded';

  let { onpalette }: { onpalette?: () => void } = $props();

  // Default open=false so SSR/first-paint never flashes the overlay; onMount
  // flips it on only when the flag is absent.
  let open = $state(false);

  $effect(() => {
    try {
      if (!localStorage.getItem(STORAGE_KEY)) open = true;
    } catch {
      /* storage blocked — just skip onboarding */
    }
  });

  function dismiss() {
    open = false;
    try {
      localStorage.setItem(STORAGE_KEY, '1');
    } catch {
      /* ignore */
    }
  }

  function showAround() {
    dismiss();
    onpalette?.();
  }

  function onKeydown(e: KeyboardEvent) {
    if (open && e.key === 'Escape') dismiss();
  }

  const surfaces = [
    {
      icon: LayoutGrid,
      title: 'The canvas',
      body: 'Your project as a living map — characters, scenes, shots and renders. Click a node to work on it.'
    },
    {
      icon: MessageSquare,
      title: 'The command center',
      body: 'The chat on the right runs everything: write a script, generate shots, render, add captions. Just ask.'
    },
    {
      icon: PanelLeft,
      title: 'The pipeline sidebar',
      body: 'Jump between Scenes, Characters, Assets and Render. The active project lives at the top.'
    }
  ];

  const steps = [
    'Add characters and a style so everything stays consistent.',
    'Tell the chat your story idea — it writes a script and splits it into scenes.',
    'Walk each scene through shots → storyboard → render, then add captions.'
  ];
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
  <!-- Backdrop: click outside the card to dismiss. -->
  <div
    class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
    role="presentation"
    onclick={(e) => e.target === e.currentTarget && dismiss()}
  >
    <div
      class="relative w-full max-w-xl rounded-2xl border border-border bg-popover p-6 text-popover-foreground shadow-2xl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
    >
      <Button
        variant="ghost"
        size="icon"
        class="absolute right-2 top-2 size-7 text-muted-foreground"
        aria-label="Dismiss"
        onclick={dismiss}
      >
        <X class="size-4" />
      </Button>

      <div class="mb-1 flex items-center gap-2">
        <Sparkles class="size-5 text-primary" />
        <h2 id="onboarding-title" class="text-lg font-semibold">Welcome to VideoFlow</h2>
      </div>
      <p class="mb-5 text-sm text-muted-foreground">
        Three surfaces, one flow — here is the lay of the land.
      </p>

      <div class="mb-5 grid gap-3 sm:grid-cols-3">
        {#each surfaces as s (s.title)}
          <div class="rounded-lg border border-border bg-card/50 p-3">
            <s.icon class="mb-1.5 size-4 text-primary" />
            <p class="text-sm font-medium">{s.title}</p>
            <p class="mt-0.5 text-xs text-muted-foreground">{s.body}</p>
          </div>
        {/each}
      </div>

      <div class="mb-5 rounded-lg border border-border bg-card/50 p-4">
        <p class="mb-2 text-sm font-medium">Your first video in 3 steps</p>
        <ol class="space-y-1.5 text-sm text-muted-foreground">
          {#each steps as step, i (i)}
            <li class="flex gap-2">
              <span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
                {i + 1}
              </span>
              <span>{step}</span>
            </li>
          {/each}
        </ol>
      </div>

      <div class="flex items-center justify-between gap-3">
        <p class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Command class="size-3.5" />
          Press
          <kbd class="rounded border border-border bg-muted px-1 py-0.5 text-[10px] font-medium">Ctrl/⌘ K</kbd>
          anytime to search and jump.
        </p>
        <div class="flex gap-2">
          <Button variant="ghost" size="sm" onclick={dismiss}>Got it</Button>
          <Button size="sm" onclick={showAround}>Show me around</Button>
        </div>
      </div>
    </div>
  </div>
{/if}
