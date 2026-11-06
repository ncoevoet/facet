export interface RovingMove {
  from: number;
  to: number;
}

/**
 * Keyboard handling shared by roving-tabindex thumbnail strips and grids.
 * `selector` matches the sibling items, which are the matches inside the
 * parent of the handler's host item. Arrow keys step by one, `vertical` items
 * for Up/Down (0 leaves them alone, as in a single-row strip), Home/End jump
 * to the first/last item. The target item takes focus and the event is
 * consumed; the move is returned so the caller can react to it. Returns null,
 * touching nothing, for modified keys, keys it does not own and targets
 * outside the items.
 */
export function rovingFocusKey(event: KeyboardEvent, selector: string, vertical = 0): RovingMove | null {
  if (event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return null;
  const items = [...(event.currentTarget as HTMLElement).parentElement!.querySelectorAll<HTMLElement>(selector)];
  const from = items.indexOf((event.target as HTMLElement).closest<HTMLElement>(selector)!);
  if (from < 0) return null;
  const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1 };
  if (vertical) { offsets['ArrowUp'] = -vertical; offsets['ArrowDown'] = vertical; }
  const offset = offsets[event.key];
  const to = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
    : offset === undefined ? null : Math.max(0, Math.min(items.length - 1, from + offset));
  if (to === null) return null;
  event.preventDefault(); event.stopPropagation(); items[to]?.focus();
  return { from, to };
}
