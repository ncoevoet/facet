/**
 * Close every tooltip, menu trigger and select a view owns, for a gallery
 * parking behind a photo page. Shared by the gallery, its cards and its
 * filter sidebar so a new overlay kind is added in one place.
 */
export function closeOverlayDirectives(
  tooltips: readonly { hide(delay?: number): void }[],
  menus: readonly { closeMenu(): void }[] = [],
  selects: readonly { close(): void }[] = [],
): void {
  for (const tooltip of tooltips) tooltip.hide(0);
  for (const menu of menus) menu.closeMenu();
  for (const select of selects) select.close();
}

/** Let Escape reach the enclosing view when the disclosure is already closed. */
export function closeDetailsOnEscape(event: Event, details: HTMLDetailsElement, summary: HTMLElement): void {
  if (!details.open) return;
  details.open = false;
  summary.focus();
  event.preventDefault();
  event.stopPropagation();
}
