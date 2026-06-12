import dagre from '@dagrejs/dagre';
import type { Node, Edge } from '@xyflow/svelte';

const W = 180,
  H = 36;

// Orphan grid: cell size and nodes per row for entities with no edges.
const GRID_COLS = 6,
  CELL_W = 200,
  CELL_H = 90;

// Gap between tiled clusters and around the orphan grid.
const CLUSTER_GAP = 140;
// Approximate canvas viewport (px after fitView padding); cluster packing
// picks the shelf arrangement that maximizes the resulting fit zoom while
// preferring a landscape (>= 1.2 wide) overall aspect ratio.
const VIEW_W = 810,
  VIEW_H = 810;

const IMG_RE = /\.(png|jpe?g|webp|gif)$/i;

/** Honest per-node size estimate matching EntityNode.svelte rendering:
 * base row ~30px, image preview adds ~68px (h-16 + margin), render_job
 * status badge adds ~24px. Slightly padded so dagre never under-reserves. */
export function nodeSize(n: Node): { w: number; h: number } {
  const d = (n.data ?? {}) as Record<string, unknown>;
  const kind = String(d.kind ?? '');
  let h = H;
  const hasPreview =
    (kind === 'asset' && IMG_RE.test(String(d.file_path ?? ''))) ||
    (kind === 'output' && !!d.thumbnail_path);
  if (hasPreview) h += 70;
  if (kind === 'render_job') h += 26;
  return { w: W, h };
}

type Pos = { x: number; y: number };

/** Run dagre (LR) on a subset of nodes; returns top-left positions keyed by
 * id plus the bounding box of the result, normalized to origin (0,0). */
function dagreLayout(
  nodes: Node[],
  edges: Edge[],
  sizes: Map<string, { w: number; h: number }>
): { pos: Map<string, Pos>; w: number; h: number } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 110, ranker: 'tight-tree' });
  g.setDefaultEdgeLabel(() => ({}));
  const ids = new Set(nodes.map((n) => n.id));
  nodes.forEach((n) => {
    const s = sizes.get(n.id)!;
    g.setNode(n.id, { width: s.w, height: s.h });
  });
  edges.forEach((e) => {
    if (ids.has(e.source) && ids.has(e.target)) g.setEdge(e.source, e.target);
  });
  dagre.layout(g);

  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  const pos = new Map<string, Pos>();
  nodes.forEach((n) => {
    const p = g.node(n.id);
    const s = sizes.get(n.id)!;
    const x = p.x - s.w / 2,
      y = p.y - s.h / 2;
    pos.set(n.id, { x, y });
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x + s.w);
    maxY = Math.max(maxY, y + s.h);
  });
  pos.forEach((p) => {
    p.x -= minX;
    p.y -= minY;
  });
  return { pos, w: maxX - minX, h: maxY - minY };
}

/** Split the connected graph into scene-centric clusters so parallel
 * scene-chains don't stack into one tall dagre column. Shared hubs
 * (characters, reused assets) fuse everything into a single component, so we
 * run a multi-source BFS from the scene nodes instead: every node joins the
 * scene whose frontier reaches it first, ties broken by how many direct
 * edges it has into each contending scene's cluster. */
function clusterize(nodes: Node[], edges: Edge[]): Node[][] {
  const adj = new Map<string, string[]>();
  nodes.forEach((n) => adj.set(n.id, []));
  edges.forEach((e) => {
    if (adj.has(e.source) && adj.has(e.target)) {
      adj.get(e.source)!.push(e.target);
      adj.get(e.target)!.push(e.source);
    }
  });

  const seeds = nodes.filter((n) => String((n.data as any)?.kind ?? '') === 'scene');
  if (seeds.length < 2) return [nodes];

  const owner = new Map<string, string>();
  seeds.forEach((s) => owner.set(s.id, s.id));
  let frontier = seeds.map((s) => s.id);
  while (frontier.length) {
    const claims = new Map<string, Map<string, number>>();
    frontier.forEach((id) => {
      const seed = owner.get(id)!;
      adj.get(id)!.forEach((nb) => {
        if (owner.has(nb)) return;
        if (!claims.has(nb)) claims.set(nb, new Map());
        const m = claims.get(nb)!;
        m.set(seed, (m.get(seed) ?? 0) + 1);
      });
    });
    const next: string[] = [];
    claims.forEach((votes, id) => {
      let best = '',
        bestN = -1;
      votes.forEach((v, s) => {
        if (v > bestN) {
          bestN = v;
          best = s;
        }
      });
      owner.set(id, best);
      next.push(id);
    });
    frontier = next;
  }

  // Anything unreachable from a scene (rare) becomes its own trailing cluster.
  const clusters = new Map<string, Node[]>();
  nodes.forEach((n) => {
    const o = owner.get(n.id) ?? '__rest__';
    if (!clusters.has(o)) clusters.set(o, []);
    clusters.get(o)!.push(n);
  });
  return [...clusters.values()];
}

type Packing = { offsets: Pos[]; w: number; h: number };

/** Shelf-pack boxes (tallest first) into rows no wider than targetW. */
function shelfPack(order: { w: number; h: number; i: number }[], targetW: number): Packing {
  const offsets: Pos[] = order.map(() => ({ x: 0, y: 0 }));
  let shelfX = 0,
    shelfY = 0,
    shelfH = 0,
    totalW = 0;
  order.forEach((b) => {
    if (shelfX > 0 && shelfX + b.w > targetW) {
      shelfY += shelfH + CLUSTER_GAP;
      shelfX = 0;
      shelfH = 0;
    }
    offsets[b.i] = { x: shelfX, y: shelfY };
    shelfX += b.w + CLUSTER_GAP;
    shelfH = Math.max(shelfH, b.h);
    totalW = Math.max(totalW, shelfX - CLUSTER_GAP);
  });
  return { offsets, w: totalW, h: shelfY + shelfH };
}

/** Tile cluster boxes into rows, choosing — among every "first row holds the
 * k tallest clusters" row width — the arrangement whose bounding box fits the
 * viewport at the highest zoom, with a penalty for portrait/over-wide aspect
 * so the result reads as a balanced landscape rather than a tall column.
 * Returns offsets in input order plus the overall bounding box. */
function packClusters(boxes: { w: number; h: number }[]): Packing {
  const order = boxes
    .map((b, i) => ({ ...b, i }))
    .sort((a, b) => b.h - a.h || b.w - a.w);

  const candidates = new Set<number>();
  let acc = 0;
  order.forEach((b) => {
    acc += b.w + CLUSTER_GAP;
    candidates.add(acc - CLUSTER_GAP);
  });

  let best: Packing | null = null;
  let bestScore = -Infinity;
  candidates.forEach((targetW) => {
    const p = shelfPack(order, targetW);
    const aspect = p.h > 0 ? p.w / p.h : 1;
    let score = Math.min(VIEW_W / p.w, VIEW_H / p.h); // ~fitView zoom
    if (aspect < 1.2) score *= aspect / 1.2; // tall-column penalty
    if (aspect > 2.5) score *= 2.5 / aspect; // over-wide penalty
    if (score > bestScore) {
      bestScore = score;
      best = p;
    }
  });
  return best ?? shelfPack(order, Infinity);
}

export function layout(nodes: Node[], edges: Edge[]): Node[] {
  const connected = new Set<string>();
  edges.forEach((e) => {
    connected.add(e.source);
    connected.add(e.target);
  });

  const sizes = new Map(nodes.map((n) => [n.id, nodeSize(n)]));
  const main = nodes.filter((n) => connected.has(n.id));
  const positions = new Map<string, Pos>();
  let mainW = 0,
    mainH = 0;

  if (main.length > 0) {
    // Single dagre pass over the whole connected graph; if that comes out as
    // a tall column (typical: many parallel scene-chains sharing character
    // hubs), re-lay it out per scene-cluster and tile the clusters wide.
    const whole = dagreLayout(main, edges, sizes);
    let use: { groups: Node[][]; results: { pos: Map<string, Pos>; w: number; h: number }[] };
    if (whole.h > 0 && whole.w / whole.h >= 1.0) {
      use = { groups: [main], results: [whole] };
    } else {
      const groups = clusterize(main, edges);
      use = { groups, results: groups.map((g) => dagreLayout(g, edges, sizes)) };
    }
    const packed = packClusters(use.results.map((r) => ({ w: r.w, h: r.h })));
    use.groups.forEach((group, gi) => {
      const off = packed.offsets[gi];
      group.forEach((n) => {
        const p = use.results[gi].pos.get(n.id)!;
        positions.set(n.id, { x: p.x + off.x, y: p.y + off.y });
      });
    });
    mainW = packed.w;
    mainH = packed.h;
  }

  // Place orphans (no edges) in a tidy grid to the right of the main graph
  // so they don't stretch the layout vertically.
  const gridLeft = main.length ? mainW + CLUSTER_GAP : 0;
  let i = 0;
  return nodes.map((n) => {
    const p = positions.get(n.id);
    if (p) return { ...n, position: p };
    const col = i % GRID_COLS;
    const row = Math.floor(i / GRID_COLS);
    i += 1;
    return { ...n, position: { x: gridLeft + col * CELL_W, y: row * CELL_H } };
  });
}

function intersects(
  a: { x: number; y: number },
  b: { x: number; y: number },
  w = W,
  h = 110
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
