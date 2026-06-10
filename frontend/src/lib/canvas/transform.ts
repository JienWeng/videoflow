import type { Node, Edge } from '@xyflow/svelte';

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
