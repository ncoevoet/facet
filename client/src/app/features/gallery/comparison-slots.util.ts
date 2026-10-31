/** Assign a frame to one pane without duplicating a frame already in another. */
export function assignComparisonSlot(paths: readonly string[], slot: number, path: string): string[] {
  if (slot < 0 || slot >= paths.length) return [...paths];
  const next = [...paths];
  const previous = next[slot];
  const existing = next.indexOf(path);
  next[slot] = path;
  if (existing >= 0 && existing !== slot) next[existing] = previous;
  return next;
}
