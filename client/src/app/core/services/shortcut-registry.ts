import { I18N } from '../i18n/keys';

/** A page whose keyboard handler reads the remappable actions. Two actions
 *  may share a key only when they share no scope. */
export type ShortcutScope = 'gallery' | 'photo';

export interface ShortcutAction {
  /** Stable id: the key under which the user's choice is saved. */
  id: string;
  /** Lowercased single character, or '' for an action that starts unassigned. */
  defaultKey: string;
  scopes: readonly ShortcutScope[];
  /** The same string the `?` reference uses, so the two never name an action differently. */
  labelKey: string;
}

/** The one table of remappable keyboard actions. The keymap dialog, the
 *  saved-keymap loader and the `?` reference rows all read from it, so adding
 *  an action here is the whole change for those surfaces. */
export const SHORTCUT_REGISTRY = [
  { id: 'favourite', defaultKey: 'f', scopes: ['gallery', 'photo'], labelKey: I18N.shortcuts.favorite },
  { id: 'reject', defaultKey: 'x', scopes: ['gallery', 'photo'], labelKey: I18N.shortcuts.reject },
  { id: 'keep', defaultKey: 'k', scopes: ['gallery', 'photo'], labelKey: I18N.review.shortcut },
  { id: 'focusSearch', defaultKey: '/', scopes: ['gallery'], labelKey: I18N.shortcuts.focus_search },
  { id: 'toggleSidebar', defaultKey: 'b', scopes: ['gallery'], labelKey: I18N.shortcuts.toggle_filters },
  { id: 'swapLayout', defaultKey: 'v', scopes: ['gallery'], labelKey: I18N.shortcuts.toggle_layout },
  { id: 'stack', defaultKey: 's', scopes: ['gallery'], labelKey: I18N.shortcuts.stack },
] as const satisfies readonly ShortcutAction[];

export type ShortcutActionId = (typeof SHORTCUT_REGISTRY)[number]['id'];

/** Ctrl/Cmd+Z presses the snackbar's Undo while one is showing (UndoService).
 *  Fixed, not remappable; listed on every page that offers a snackbar Undo. */
export const UNDO_SHORTCUT_ROW = { keys: ['⌘/Ctrl', 'Z'], labelKey: I18N.shortcuts.undo };

export function shortcutAction(id: ShortcutActionId): ShortcutAction {
  return SHORTCUT_REGISTRY.find(a => a.id === id)!;
}

/** Whether two actions are ever live on the same page, so must not share a
 *  key. Every action today is live on the gallery, so all seven conflict;
 *  a photo-only or darkroom-only action added later need not. */
export function shareScope(a: Pick<ShortcutAction, 'scopes'>, b: Pick<ShortcutAction, 'scopes'>): boolean {
  return a.scopes.some(s => b.scopes.includes(s));
}
