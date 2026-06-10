<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from '$lib/api';

  let nodes: any[] = $state([]);
  let edges: any[] = $state([]);
  let error = $state('');

  const COLUMNS = ['character', 'asset', 'scene', 'shot', 'render_job', 'output'];
  const COLORS: Record<string, string> = {
    character: '#ffb454',
    asset: '#59c2ff',
    scene: '#7fd962',
    shot: '#d2a6ff',
    render_job: '#f07178',
    output: '#95e6cb'
  };

  const COL_W = 190;
  const ROW_H = 46;

  let positions: Record<string, { x: number; y: number }> = $state({});
  let height = $state(400);

  onMount(async () => {
    try {
      const g = await get('/graph');
      nodes = g.nodes;
      edges = g.edges;
      const byType: Record<string, any[]> = {};
      for (const n of nodes) (byType[n.type] ??= []).push(n);
      let maxRows = 1;
      for (const [ci, type] of COLUMNS.entries()) {
        (byType[type] ?? []).forEach((n, ri) => {
          positions[n.id] = { x: ci * COL_W + 20, y: ri * ROW_H + 40 };
        });
        maxRows = Math.max(maxRows, byType[type]?.length ?? 0);
      }
      height = maxRows * ROW_H + 80;
      positions = positions;
    } catch (e: any) {
      error = e.message;
    }
  });
</script>

<h1>Relationship graph</h1>
{#if error}<div class="error">{error}</div>{/if}

<div class="panel" style="overflow-x:auto">
  <svg width={COLUMNS.length * COL_W + 40} {height}>
    {#each COLUMNS as type, ci}
      <text x={ci * COL_W + 20} y="20" fill="#8a91a0" font-size="12">{type}</text>
    {/each}
    {#each edges as e}
      {#if positions[e.source] && positions[e.target]}
        <path
          d="M {positions[e.source].x + 150} {positions[e.source].y + 14}
             C {positions[e.source].x + 175} {positions[e.source].y + 14},
               {positions[e.target].x - 25} {positions[e.target].y + 14},
               {positions[e.target].x} {positions[e.target].y + 14}"
          stroke="#2a2f3a"
          fill="none"
        />
      {/if}
    {/each}
    {#each nodes as n}
      {#if positions[n.id]}
        <g transform="translate({positions[n.id].x}, {positions[n.id].y})">
          <rect width="150" height="28" rx="6" fill="#181b22" stroke={COLORS[n.type] ?? '#2a2f3a'} />
          <text x="8" y="18" fill="#e6e9ef" font-size="11">
            {n.label.length > 20 ? n.label.slice(0, 19) + '…' : n.label}
          </text>
        </g>
      {/if}
    {/each}
  </svg>
</div>
