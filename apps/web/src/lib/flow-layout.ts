/**
 * Top-to-bottom layout for a pipeline flow: each step goes one row below the step that
 * leads to it by the longest path from the input (loops, such as agent ⇄ tools, are not
 * followed back), and steps in a row are ordered by where their predecessors sit, so
 * connections cross as little as possible. Flows are deep and narrow (Fast and Agent side
 * by side), which fits a screen better than a long line.
 */

export const COL_W = 270;
export const ROW_H = 120;

type Step = { id: string };
type Link = { source: string; target: string };

export function layoutFlow(
  steps: readonly Step[],
  links: readonly Link[],
  start = "input",
): Record<string, { x: number; y: number }> {
  const ids = steps.map((s) => s.id);
  const next = new Map(ids.map((id) => [id, [] as string[]]));
  for (const l of links) next.get(l.source)?.push(l.target);

  // Edges that close a loop (back edges of a depth-first walk) are left out of the layering.
  const back = new Set<string>();
  const state = new Map<string, "open" | "done">();
  const walk = (id: string) => {
    state.set(id, "open");
    for (const to of next.get(id) ?? []) {
      if (state.get(to) === "open") back.add(`${id}>${to}`);
      else if (!state.has(to)) walk(to);
    }
    state.set(id, "done");
  };
  const roots = [ids.includes(start) ? start : ids[0], ...ids].filter(
    (x): x is string => x !== undefined,
  );
  for (const r of roots) if (!state.has(r)) walk(r);

  const forward = links.filter((l) => !back.has(`${l.source}>${l.target}`) && next.has(l.target));
  // A step that only loops with one other (an agent's tools) sits beside it, not below.
  const side = new Map<string, string>();
  for (const l of links) {
    if (!back.has(`${l.source}>${l.target}`)) continue;
    const preds = forward.filter((f) => f.target === l.source).map((f) => f.source);
    if (preds.length === 1 && preds[0] === l.target && !side.has(l.target)) {
      side.set(l.source, l.target);
    }
  }
  const ranked = forward.filter((l) => side.get(l.target) !== l.source);
  const column = new Map(ids.map((id) => [id, 0]));
  // Longest path: relax repeatedly (the graph without back edges has no cycles).
  for (let i = 0; i < ids.length; i += 1) {
    let changed = false;
    for (const l of ranked) {
      const c = (column.get(l.source) ?? 0) + 1;
      if (c > (column.get(l.target) ?? 0)) {
        column.set(l.target, c);
        changed = true;
      }
    }
    if (!changed) break;
  }
  for (const [b, a] of side) column.set(b, column.get(a) ?? 0);

  const byColumn = new Map<number, string[]>();
  for (const id of ids) {
    if (side.has(id)) continue;
    const c = column.get(id) ?? 0;
    byColumn.set(c, [...(byColumn.get(c) ?? []), id]);
  }
  const row = new Map<string, number>();
  for (const c of [...byColumn.keys()].sort((a, b) => a - b)) {
    const members = byColumn.get(c)!;
    const weight = (id: string) => {
      const from = ranked.filter((l) => l.target === id && row.has(l.source));
      return from.length
        ? from.reduce((s, l) => s + row.get(l.source)!, 0) / from.length
        : ids.indexOf(id);
    };
    members.sort((a, b) => weight(a) - weight(b));
    // Centre each column on the rows its predecessors use.
    const centre = members.length > 1 ? (members.length - 1) / 2 : 0;
    const anchor = c === 0 ? 0 : members.reduce((s, id) => s + weight(id), 0) / members.length;
    const base = Number.isFinite(anchor) && c > 0 ? anchor - centre : 0;
    // Each step's side step goes right after it.
    const lined = members.flatMap((id) => [
      id,
      ...[...side].filter(([, a]) => a === id).map(([b]) => b),
    ]);
    lined.forEach((id, i) => row.set(id, base + i));
  }
  const top = Math.min(...[...row.values()]);
  return Object.fromEntries(
    ids.map((id) => [id, { x: (row.get(id)! - top) * COL_W, y: (column.get(id) ?? 0) * ROW_H }]),
  );
}

/** Whether saved positions are useless (all missing or on top of each other). */
export function needsLayout(points: readonly { x?: number | null; y?: number | null }[]): boolean {
  const seen = new Set(points.map((p) => `${Math.round(p.x ?? 0)},${Math.round(p.y ?? 0)}`));
  return points.length > 1 && seen.size < points.length;
}
