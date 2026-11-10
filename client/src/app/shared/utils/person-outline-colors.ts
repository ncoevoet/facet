const COLORS = ['#ef4444', '#38bdf8', '#fbbf24', '#a78bfa', '#34d399', '#fb923c', '#f472b6', '#2dd4bf', '#c084fc', '#a3e635'];

export function selectedPersonIds(value: string): number[] {
  return [...new Set(value.split(',').filter(id => /^\d+$/.test(id)).map(Number)
    .filter(id => Number.isSafeInteger(id) && id > 0))].sort((a, b) => a - b);
}

/** Stable within a selection, with collisions resolved so selected people differ. */
export function personOutlineColors(value: string): Map<number, string> {
  const colors = new Map<number, string>();
  const used = new Set<number>();
  for (const id of selectedPersonIds(value)) {
    if (used.size === COLORS.length) {
      colors.set(id, `hsl(${(colors.size * 137.508) % 360} 78% 70%)`);
      continue;
    }
    let slot = id % COLORS.length;
    while (used.has(slot)) slot = (slot + 1) % COLORS.length;
    used.add(slot);
    colors.set(id, COLORS[slot]);
  }
  return colors;
}
