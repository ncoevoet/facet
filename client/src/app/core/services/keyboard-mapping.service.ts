import { Injectable, signal } from '@angular/core';
import { SHORTCUT_REGISTRY, ShortcutActionId, shareScope, shortcutAction } from './shortcut-registry';

/** The user's key for each remappable action (see `SHORTCUT_REGISTRY`): the
 *  lowercased primary key, or '' when unassigned. Modifiers (Ctrl/Cmd/Alt)
 *  are not remappable. */
export type KeymapConfig = Record<ShortcutActionId, string>;

export const DEFAULT_KEYMAP: KeymapConfig = Object.fromEntries(
  SHORTCUT_REGISTRY.map(a => [a.id, a.defaultKey]),
) as KeymapConfig;

const ACTION_IDS: ShortcutActionId[] = SHORTCUT_REGISTRY.map(a => a.id);

/** Whether `key` is held by an action other than `action` that shares a page with it. */
function heldInScope(map: KeymapConfig, action: ShortcutActionId, key: string): boolean {
  return ACTION_IDS.some(other => other !== action && map[other] === key && shareScope(shortcutAction(action), shortcutAction(other)));
}

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

/** A saved key that is reserved or that two actions on the same page share (a hand edit, or an
 *  older save meeting a newer rule) falls back to that action's default, so
 *  one keystroke never fires two actions. If that default is itself already
 *  taken by another saved key, restore the full defaults. A newly introduced
 *  Stack default yields to an older saved binding by staying unassigned. */
function load(): KeymapConfig {
  try {
    const raw = localStorage.getItem(KEYMAP_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_KEYMAP };
    const saved = JSON.parse(raw) as Partial<Record<ShortcutActionId, unknown>>;
    const keys = Object.fromEntries(ACTION_IDS.map(action => {
      const v = saved[action];
      return [action, typeof v === 'string' ? assignableKey(v) ?? '' : ''];
    })) as KeymapConfig;
    const out = { ...DEFAULT_KEYMAP };
    for (const action of ACTION_IDS) {
      const k = keys[action];
      if (k && !heldInScope(keys, action, k)) out[action] = k;
    }
    // Adding a default must not reset an older valid map that already uses S.
    // Keep an explicitly unassigned action unassigned on subsequent saves too.
    if (saved.stack === '' || (saved.stack === undefined && heldInScope(out, 'stack', out.stack))) {
      out.stack = '';
    }
    return ACTION_IDS.some(action => out[action] && heldInScope(out, action, out[action])) ? { ...DEFAULT_KEYMAP } : out;
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
   *  (`'reserved'`) or one held by another action on a page this one is
   *  live on (`'in_use'`). */
  setKey(action: ShortcutActionId, key: string): 'reserved' | 'in_use' | null {
    const k = assignableKey(key);
    if (!k) return 'reserved';
    const map = this.keymap();
    if (heldInScope(map, action, k)) return 'in_use';
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
  matches(event: KeyboardEvent, action: ShortcutActionId): boolean {
    const key = this.keymap()[action];
    return !!key && event.key.toLowerCase() === key;
  }
}
