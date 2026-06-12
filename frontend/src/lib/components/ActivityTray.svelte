<script lang="ts">
  import { fade } from 'svelte/transition';
  import {
    Loader2,
    History,
    Images,
    ImagePlus,
    LayoutGrid,
    Captions,
    Palette,
    Film
  } from '@lucide/svelte';
  import { Badge } from '$lib/components/ui/badge';
  import { activity, type ActivityItem } from '$lib/activity.svelte';

  let open = $state(false);
  let root: HTMLDivElement | undefined = $state();

  const LABELS: Record<string, string> = {
    storyboard: 'Storyboard',
    assets: 'Assets',
    shots: 'Shots',
    caption: 'Caption',
    style_ingest: 'Style ingest',
    render: 'Render'
  };

  // Map kinds to lucide icon components
  const KIND_ICONS: Record<string, any> = {
    storyboard: Images,
    assets: ImagePlus,
    shots: LayoutGrid,
    caption: Captions,
    style_ingest: Palette,
    render: Film
  };

  function label(item: ActivityItem): string {
    return LABELS[item.kind] ?? item.kind;
  }

  function kindIcon(item: ActivityItem): any {
    return KIND_ICONS[item.kind] ?? History;
  }

  function timeAgo(iso: string): string {
    const ms = Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime();
    if (!Number.isFinite(ms) || ms < 0) return 'now';
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function isRunning(item: ActivityItem): boolean {
    return item.status === 'running' || item.status === 'pending';
  }

  function onWindowClick(e: MouseEvent) {
    if (open && root && !root.contains(e.target as Node)) open = false;
  }

  function onWindowKeydown(e: KeyboardEvent) {
    if (open && e.key === 'Escape') {
      open = false;
    }
  }

  const hasRunning = $derived(activity.runningCount > 0);
</script>

<svelte:window onclick={onWindowClick} onkeydown={onWindowKeydown} />

<div class="relative" bind:this={root}>
  {#if open}
    <div
      transition:fade={{ duration: 120 }}
      class="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-lg border border-border bg-popover shadow-lg text-popover-foreground"
    >
      <!-- Header row -->
      <div class="flex items-center gap-2 px-3 py-2 border-b border-border">
        <span class="text-xs font-semibold">Activity</span>
        {#if activity.items.length > 0}
          <Badge variant="secondary" class="text-[10px] px-1.5 py-0">{activity.items.length}</Badge>
        {/if}
        {#if hasRunning}
          <span class="ml-auto flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <span class="relative flex size-2">
              <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75"></span>
              <span class="relative inline-flex size-2 rounded-full bg-primary"></span>
            </span>
            {activity.runningCount} running
          </span>
        {/if}
      </div>

      {#if activity.items.length === 0}
        <div class="px-3 py-4 text-sm text-muted-foreground">No background activity yet.</div>
      {:else}
        <ul class="max-h-80 overflow-y-auto">
          {#each activity.items.slice(0, 10) as item (item.id)}
            {@const Icon = kindIcon(item)}
            <li class="px-3 py-2 hover:bg-accent/50 {item.status === 'failed' ? 'border-l-2 border-destructive' : ''}">
              <div class="flex items-center gap-2">
                <Icon class="size-3.5 shrink-0 text-muted-foreground" />
                <span class="text-sm font-medium truncate flex-1">{label(item)}</span>
                <span class="text-xs text-muted-foreground shrink-0">{timeAgo(item.created_at)}</span>
                <span class="shrink-0">
                  {#if isRunning(item)}
                    <Badge variant="secondary" class="animate-pulse text-[10px] px-1.5 py-0">running</Badge>
                  {:else if item.status === 'failed'}
                    <Badge variant="destructive" class="text-[10px] px-1.5 py-0">failed</Badge>
                  {:else}
                    <Badge class="text-[10px] px-1.5 py-0">done</Badge>
                  {/if}
                </span>
              </div>
              {#if item.scene_id || item.output_id}
                <div class="mt-0.5 pl-5 text-[10px] text-muted-foreground font-mono truncate">
                  {item.scene_id ?? item.output_id}
                </div>
              {/if}
              {#if item.status === 'failed'}
                {@const errorText = item.error?.trim() || 'failed (no detail)'}
                <div class="mt-0.5 pl-5 truncate text-[10px] text-destructive" title={errorText}>{errorText}</div>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  <button
    type="button"
    onclick={() => (open = !open)}
    class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent
           {hasRunning ? 'text-primary font-medium' : 'text-muted-foreground'}"
    aria-expanded={open}
  >
    {#if hasRunning}
      <Loader2 class="size-4 animate-spin" />
      {activity.runningCount} running
    {:else}
      <History class="size-4" />
      Activity
    {/if}
  </button>
</div>
