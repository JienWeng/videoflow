import dagre from '@dagrejs/dagre';
import type { Node, Edge } from '@xyflow/svelte';

const W = 180,
  H = 64;

// Orphan grid: cell size and nodes per row for entities with no edges.
const GRID_COLS = 6,
  CELL_W = 200,
  CELL_H = 90;

export function layout(nodes: Node[], edges: Edge[]): Node[] {
  const connected = new Set<string>();
  edges.forEach((e) => {
    connected.add(e.source);
    connected.add(e.target);
  });

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => {
    if (connected.has(n.id)) g.setNode(n.id, { width: W, height: H });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  // Place orphans (no edges) in a tidy grid below the connected graph
  // instead of letting dagre stack them in a single rank.
  let maxY = 0;
  let minX = 0;
  let hasConnected = false;
  nodes.forEach((n) => {
    if (!connected.has(n.id)) return;
    const p = g.node(n.id);
    if (!hasConnected) {
      hasConnected = true;
      maxY = p.y + H / 2;
      minX = p.x - W / 2;
    } else {
      maxY = Math.max(maxY, p.y + H / 2);
      minX = Math.min(minX, p.x - W / 2);
    }
  });
  const gridTop = hasConnected ? maxY + CELL_H : 0;
  const gridLeft = hasConnected ? minX : 0;

  let i = 0;
  return nodes.map((n) => {
    if (connected.has(n.id)) {
      const p = g.node(n.id);
      return { ...n, position: { x: p.x - W / 2, y: p.y - H / 2 } };
    }
    const col = i % GRID_COLS;
    const row = Math.floor(i / GRID_COLS);
    i += 1;
    return { ...n, position: { x: gridLeft + col * CELL_W, y: gridTop + row * CELL_H } };
  });
}

function intersects(
  a: { x: number; y: number },
  b: { x: number; y: number },
  w = W,
  h = H
): boolean {
  return a.x < b.x + w && a.x + w > b.x && a.y < b.y + h && a.y + h > b.y;
}

/**
 * Layout that respects saved (user-pinned) positions: every node gets a full
 * dagre layout, then nodes present in `saved` are pinned to their saved spot.
 * Nodes NOT in `saved` (fresh nodes) keep their dagre position, nudged down
 * in 100px steps until they no longer overlap any pinned node, so new
 * entities appear tidily even when the rest of the canvas is hand-arranged.
 */
export function layoutFresh(
  nodes: Node[],
  edges: Edge[],
  saved: Record<string, { x: number; y: number }>
): Node[] {
  const laidOut = layout(nodes, edges);
  const pinned = laidOut
    .filter((n) => saved[n.id])
    .map((n) => saved[n.id]);

  return laidOut.map((n) => {
    if (saved[n.id]) return { ...n, position: saved[n.id] };
    // Collision pass: shift fresh nodes down until clear of pinned nodes.
    const pos = { ...n.position };
    let guard = 0;
    while (guard < 100 && pinned.some((p) => intersects(pos, p))) {
      pos.y += 100;
      guard += 1;
    }
    return { ...n, position: pos };
  });
}
