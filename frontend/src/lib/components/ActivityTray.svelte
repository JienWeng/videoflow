<script lang="ts">
  import { Loader2, History } from '@lucide/svelte';
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

  function label(item: ActivityItem): string {
    return LABELS[item.kind] ?? item.kind;
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
</script>

<svelte:window onclick={onWindowClick} />

<div class="relative" bind:this={root}>
  {#if open}
    <div
      class="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-md border border-border bg-popover p-2 text-popover-foreground shadow-md"
    >
      <div class="px-2 py-1.5 text-xs font-semibold text-muted-foreground">Recent activity</div>
      {#if activity.items.length === 0}
        <div class="px-2 py-3 text-sm text-muted-foreground">No background activity yet.</div>
      {:else}
        <ul class="max-h-80 overflow-auto">
          {#each activity.items.slice(0, 10) as item (item.id)}
            <li class="rounded-md px-2 py-1.5 hover:bg-accent/50">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium">{label(item)}</span>
                <span class="ml-auto">
                  {#if isRunning(item)}
                    <Badge variant="secondary" class="animate-pulse">running</Badge>
                  {:else if item.status === 'failed'}
                    <Badge variant="destructive" title={item.error ?? 'failed'}>failed</Badge>
                  {:else}
                    <Badge>done</Badge>
                  {/if}
                </span>
              </div>
              <div class="flex items-center gap-2 text-xs text-muted-foreground">
                {#if item.scene_id}
                  <span class="truncate font-mono">{item.scene_id}</span>
                {:else if item.output_id}
                  <span class="truncate font-mono">{item.output_id}</span>
                {/if}
                <span class="ml-auto shrink-0">{timeAgo(item.created_at)}</span>
              </div>
              {#if item.status === 'failed'}
                {@const errorText = item.error?.trim() || 'failed (no detail)'}
                <div class="truncate text-xs text-destructive" title={errorText}>{errorText}</div>
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
           {activity.runningCount > 0 ? 'text-primary font-medium' : 'text-muted-foreground'}"
    aria-expanded={open}
  >
    {#if activity.runningCount > 0}
      <Loader2 class="size-4 animate-spin" />
      {activity.runningCount} running
    {:else}
      <History class="size-4" />
      Activity
    {/if}
  </button>
</div>
