<script lang="ts">
  type Stage = { key: string; label: string };

  let {
    status = 'running',
    stages = [],
    error = ''
  }: { status?: string; stages?: string[]; error?: string } = $props();

  const labels: Stage[] = [
    { key: 'story', label: 'Story' },
    { key: 'scenes', label: 'Scenes' },
    { key: 'shots', label: 'Shots' },
    { key: 'dialogue', label: 'Dialogue' },
    { key: 'visuals', label: 'Visuals' },
    { key: 'render', label: 'Render' }
  ];

  const completed = $derived(new Set(stages));
  const current = $derived(
    status === 'failed' ? '' : labels.find((stage) => !completed.has(stage.key))?.key ?? 'render'
  );
</script>

<div class="rounded-xl border border-border bg-card p-5 shadow-sm">
  <div class="mb-4 flex items-center justify-between gap-3">
    <div>
      <h2 class="font-semibold">Creating your video</h2>
      <p class="text-sm text-muted-foreground">
        VideoFlow is handling the scenes, dialogue, visuals, and render.
      </p>
    </div>
    {#if status === 'running'}
      <span class="text-xs text-muted-foreground">Working…</span>
    {:else if status === 'failed'}
      <span class="text-xs text-destructive">Needs attention</span>
    {/if}
  </div>

  <ol class="space-y-3">
    {#each labels as stage}
      {@const done = completed.has(stage.key)}
      {@const active = current === stage.key}
      <li class="flex items-center gap-3 text-sm">
        <span class="grid size-6 place-items-center rounded-full border text-xs
          {done ? 'border-emerald-500 bg-emerald-500/10 text-emerald-600' : active ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}">
          {done ? '✓' : active ? '•' : '·'}
        </span>
        <span class={done ? 'text-foreground' : active ? 'font-medium' : 'text-muted-foreground'}>{stage.label}</span>
      </li>
    {/each}
  </ol>

  {#if error}
    <div class="mt-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
      <p class="font-medium text-destructive">Generation stopped</p>
      <p class="mt-1 break-words text-muted-foreground">{error}</p>
      <p class="mt-2 text-xs text-muted-foreground">Your completed work is available in the advanced workspace.</p>
    </div>
  {/if}
</div>
