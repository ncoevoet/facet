import { Injectable, signal } from '@angular/core';
import { I18N } from '../i18n/keys';

/** The user-customisable keyboard actions. Each entry maps an action id to
 *  the (lowercased) primary key that triggers it on the gallery and photo
 *  pages. Modifiers (Ctrl/Cmd/Alt) are not remappable. */
export interface KeymapConfig {
  favourite: string;
  reject: string;
  keep: string;
  focusSearch: string;
  toggleSidebar: string;
  swapLayout: string;
  /** Empty when a saved binding already owns the new default. */
  stack: string;
}

export const DEFAULT_KEYMAP: KeymapConfig = {
  favourite: 'f',
  reject: 'x',
  keep: 'k',
  focusSearch: '/',
  toggleSidebar: 'b',
  swapLayout: 'v',
  stack: 's',
};

/** The remappable actions, labelled with the same strings the keyboard
 *  reference tables use, so the settings dialog and the reference can never
 *  name an action differently. */
export const KEYMAP_ACTIONS: { id: keyof KeymapConfig; labelKey: string }[] = [
  { id: 'favourite', labelKey: I18N.shortcuts.favorite },
  { id: 'reject', labelKey: I18N.shortcuts.reject },
  { id: 'keep', labelKey: I18N.review.shortcut },
  { id: 'focusSearch', labelKey: I18N.shortcuts.focus_search },
  { id: 'toggleSidebar', labelKey: I18N.shortcuts.toggle_filters },
  { id: 'swapLayout', labelKey: I18N.shortcuts.toggle_layout },
  { id: 'stack', labelKey: I18N.shortcuts.stack },
];

export const KEYMAP_STORAGE_KEY = 'facet_keymap';

/** Keys no action may take: 1–5 rate and 0 rejects, and 6–9 are held back
 *  with them so no digit ever triggers an action; Space selects the focused
 *  photo and ? opens the shortcut reference. */
const RESERVED_KEYS = new Set(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ' ', '?']);

/** The stored form of a pressed key — lowercased, one character, not
 *  reserved — or null when no action may take it. Lowercasing can lengthen a
 *  character (`İ` becomes two code units), so length is checked after it. */
export function assignableKey(key: string): string | null {
  const k = key.toLowerCase();
  return k.length === 1 && !RESERVED_KEYS.has(k) ? k : null;
}

/** A saved key that is reserved or that two actions share (a hand edit, or an
 *  older save meeting a newer rule) falls back to that action's default, so
 *  one keystroke never fires two actions. If that default is itself already
 *  taken by another saved key, restore the full defaults. A newly introduced
 *  Stack default yields to an older saved binding by staying unassigned. */
function load(): KeymapConfig {
  try {
    const raw = localStorage.getItem(KEYMAP_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_KEYMAP };
    const saved = JSON.parse(raw) as Partial<Record<keyof KeymapConfig, unknown>>;
    const actions = KEYMAP_ACTIONS.map(a => a.id);
    const keys = actions.map(action => {
      const v = saved[action];
      return typeof v === 'string' ? assignableKey(v) : null;
    });
    const out = { ...DEFAULT_KEYMAP };
    actions.forEach((action, i) => {
      const k = keys[i];
      if (k && keys.indexOf(k) === keys.lastIndexOf(k)) out[action] = k;
    });
    // Adding a default must not reset an older valid map that already uses S.
    // Keep an explicitly unassigned action unassigned on subsequent saves too.
    if (saved.stack === '' || (saved.stack === undefined && actions.some(action => action !== 'stack' && out[action] === out.stack))) {
      out.stack = '';
    }
    const assigned = Object.values(out).filter(Boolean);
    return new Set(assigned).size === assigned.length ? out : { ...DEFAULT_KEYMAP };
  } catch {
    return { ...DEFAULT_KEYMAP };
  }
}

/** Per-browser keyboard mapping for the gallery and photo-page actions,
 *  persisted in localStorage. Defaults match the built-in bindings; the user
 *  can reassign the primary key of each action from the settings dialog. */
@Injectable({ providedIn: 'root' })
export class KeyboardMappingService {
  readonly keymap = signal<KeymapConfig>(load());

  /** Assigns `key` to `action`. Refuses a key no action may take
   *  (`'reserved'`) or one another action holds (`'in_use'`). */
  setKey(action: keyof KeymapConfig, key: string): 'reserved' | 'in_use' | null {
    const k = assignableKey(key);
    if (!k) return 'reserved';
    const map = this.keymap();
    if (KEYMAP_ACTIONS.some(a => a.id !== action && map[a.id] === k)) return 'in_use';
    this.save({ ...map, [action]: k });
    return null;
  }

  resetAll(): void {
    this.save({ ...DEFAULT_KEYMAP });
  }

  private save(map: KeymapConfig): void {
    this.keymap.set(map);
    try { localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify(map)); } catch { /* session-only */ }
  }

  /** Whether `event` is the key currently mapped to `action`. */
  matches(event: KeyboardEvent, action: keyof KeymapConfig): boolean {
    const key = this.keymap()[action];
    return !!key && event.key.toLowerCase() === key;
  }
}
