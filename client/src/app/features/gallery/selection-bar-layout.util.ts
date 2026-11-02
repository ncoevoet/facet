/** Extents (px) needed to decide whether the notices must rise above the selection card. */
export interface NoticeLiftInput {
  /** Bottom edge of the gallery host. */
  hostBottom: number;
  /** Card top edge, in the same space as hostBottom. */
  barTop: number;
  barBottom: number;
  /** Notice bounds at its ordinary bottom position, before applying any lift. */
  noticeTop: number | null;
  noticeBottom: number | null;
  /** Card left/right, relative to the host's left edge. */
  barLeft: number;
  barRight: number;
  /** Measured notice stack left/right, relative to the host's left edge; null when absent. */
  noticeLeft: number | null;
  noticeRight: number | null;
}

/**
 * Pixels the advisory notices must rise to clear the floating selection card.
 *
 * Zero unless the card and the notice stack overlap horizontally (touching edges do not
 * overlap). Otherwise the distance from the host bottom up to the card top, which already
 * includes the card's own bottom margin.
 */
export function noticeLiftPx(input: NoticeLiftInput): number {
  const { hostBottom, barTop, barLeft, barRight, noticeLeft, noticeRight } = input;
  if (noticeLeft === null || noticeRight === null || input.noticeTop === null || input.noticeBottom === null) return 0;
  if (input.barBottom <= input.noticeTop || barTop >= input.noticeBottom) return 0;
  if (barRight <= noticeLeft || noticeRight <= barLeft) return 0;
  return Math.max(0, Math.ceil(hostBottom - barTop));
}
