import { MarkerType, type Node, type Edge } from '@xyflow/svelte';

/** Per-kind accent colors — node left borders and minimap dots share these so
 * the zoomed-out canvas still reads as structure-by-color. */
export const KIND_COLORS: Record<string, string> = {
  character: 'hsl(210, 85%, 60%)', // blue
  asset: 'hsl(150, 60%, 50%)', // green
  scene: 'hsl(270, 70%, 65%)', // purple
  shot: 'hsl(35, 90%, 55%)', // orange
  render_job: 'hsl(330, 70%, 60%)', // pink
  output: 'hsl(190, 80%, 55%)' // cyan
};

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? 'hsl(0, 0%, 55%)';
}

/** Human-friendly labels for the collapsible legend (kept here so the legend
 * and the node tints stay in sync — one source of truth for the palette). */
export const KIND_LABELS: Record<string, string> = {
  scene: 'Scene',
  shot: 'Shot',
  character: 'Character',
  asset: 'Asset',
  render_job: 'Render',
  output: 'Output'
};

/** Order the legend swatches follow the pipeline left→right. */
export const LEGEND_KINDS = ['scene', 'shot', 'character', 'asset', 'render_job', 'output'];

/** Edge accent by relationship label — colors the lines by what they mean so a
 * "casts" link reads differently from a "render" link even when labels are
 * hidden at far zoom. Falls back to a neutral grey for unknown relations. */
export const EDGE_COLORS: Record<string, string> = {
  casts: 'hsl(210, 85%, 60%)', // character ↔ scene (blue, matches character)
  uses: 'hsl(150, 60%, 50%)', // asset usage (green, matches asset)
  reference: 'hsl(150, 50%, 45%)', // character reference asset (dim green)
  shot: 'hsl(35, 90%, 55%)', // scene → shot (orange, matches shot)
  render: 'hsl(330, 70%, 60%)', // → render job (pink)
  output: 'hsl(190, 80%, 55%)', // render job → output (cyan)
  storyboard: 'hsl(270, 70%, 65%)' // scene → storyboard asset (purple)
};

export function edgeColor(label: string | undefined): string {
  return (label && EDGE_COLORS[label]) || 'hsl(0, 0%, 42%)';
}

export type ApiGraph = {
  nodes: { id: string; type: string; label: string; data?: Record<string, any> }[];
  edges: { source: string; target: string; label: string }[];
};

export function toFlow(g: ApiGraph): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = g.nodes.map((n) => ({
    id: n.id,
    type: 'entity',
    position: { x: 0, y: 0 },
    data: { kind: n.type, label: n.label, ...(n.data ?? {}) }
  }));
  const edges: Edge[] = g.edges.map((e) => {
    const color = edgeColor(e.label);
    return {
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      // Relationship label is kept in `data.rel` always; the visible `label`
      // is toggled on by EntityCanvas only on hover/selection to avoid clutter.
      data: { rel: e.label || '' },
      style: `stroke: ${color};`,
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 }
    } as Edge;
  });
  return { nodes, edges };
}

const POS_KEY = 'videoflow.canvas.positions';

export function loadPositions(): Record<string, { x: number; y: number }> {
  try {
    return JSON.parse(localStorage.getItem(POS_KEY) ?? '{}');
  } catch {
    return {};
  }
}

export function savePositions(nodes: Node[]) {
  const pos = Object.fromEntries(nodes.map((n) => [n.id, n.position]));
  localStorage.setItem(POS_KEY, JSON.stringify(pos));
}

export function clearPositions() {
  localStorage.removeItem(POS_KEY);
}
