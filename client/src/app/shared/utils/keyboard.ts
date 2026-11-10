/**
 * True when a keyboard event belongs to text entry or a control with keyboard
 * navigation/typeahead (including ARIA menus, selects and comboboxes), where
 * page-level shortcuts must not fire. Shared by the gallery, photo page and
 * darkroom so they gate keyboard shortcuts the same way.
 */
export function isTypingContext(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) return false;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable
    || !!target.closest?.('[role="combobox"], [role="listbox"], [role="option"], [role="menu"], [role="menubar"], [role^="menuitem"]');
}

/**
 * True when Enter or Space would activate the focused control (a button, link or menu item):
 * a page-level shortcut on those keys must leave it to the control.
 */
export function isControlActivation(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  return !!target?.closest?.('button, a[href], [role="menuitem"], [role="option"]');
}

/** True for an auto-repeat or an IME composition keystroke, which no shortcut should act on. */
export function isImeOrRepeat(event: KeyboardEvent): boolean {
  return event.repeat || event.isComposing || event.keyCode === 229;
}

/** True for Ctrl+Z or Cmd+Z (one of the two, never both), without Shift or Alt. */
export function isUndoChord(event: KeyboardEvent): boolean {
  return event.key.toLowerCase() === 'z' && event.ctrlKey !== event.metaKey && !event.shiftKey && !event.altKey;
}

const DIALOG_HOSTS = 'mat-dialog-container, mat-bottom-sheet-container';

/** True when focus is in a typing context or a dialog / bottom sheet is open, whatever modifiers are held. */
export function isShortcutContextBlocked(event: KeyboardEvent): boolean {
  return isTypingContext(event) || !!document.querySelector(`${DIALOG_HOSTS}, [role="dialog"][aria-modal="true"]`);
}

/**
 * Like {@link isShortcutContextBlocked}, except that a modal workspace marked `data-undo-surface`
 * (the culling darkroom, which offers its own Undo snackbars) lets Ctrl/Cmd+Z through.
 * A dialog opened over it still blocks the key.
 */
export function isUndoContextBlocked(event: KeyboardEvent): boolean {
  return isTypingContext(event)
    || !!document.querySelector(`${DIALOG_HOSTS}, [role="dialog"][aria-modal="true"]:not([data-undo-surface])`);
}

/**
 * True when a page-level letter/digit shortcut must stand down: focus is in a typing
 * context, a modifier is held, or a dialog / bottom sheet is open.
 */
export function isPageShortcutBlocked(event: KeyboardEvent): boolean {
  return isShortcutContextBlocked(event) || event.ctrlKey || event.metaKey || event.altKey;
}
