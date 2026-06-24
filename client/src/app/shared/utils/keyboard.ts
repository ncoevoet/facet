/**
 * True when a keyboard event originates from a text-entry context (input,
 * textarea, native select, or contenteditable), where global single-key
 * shortcuts must not fire. Shared by the gallery grid and the burst-culling
 * darkroom so both gate keyboard shortcuts the same way.
 */
export function isTypingContext(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) return false;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable;
}
