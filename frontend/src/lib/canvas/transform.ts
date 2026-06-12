import type { Node, Edge } from '@xyflow/svelte';

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
  const edges: Edge[] = g.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    label: e.label || undefined
  }));
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
