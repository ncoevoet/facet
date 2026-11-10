import { I18N } from '../../core/i18n/keys';
import { KeymapConfig } from '../../core/services/keyboard-mapping.service';
import { shortcutAction, ShortcutActionId, UNDO_SHORTCUT_ROW } from '../../core/services/shortcut-registry';

/** The gallery's and photo page's keyboard references. One builder per page
 *  feeds the `?` shortcuts dialog and, for the gallery, the help dialog the
 *  user menu opens on the gallery routes, so they can never list different
 *  keys — and both show the keys the user actually remapped, not the
 *  defaults. Remappable rows take their label from `SHORTCUT_REGISTRY`. */
export interface ShortcutRow { keys: string[]; labelKey: string; }

export interface ShortcutSection { titleKey: string; rows: ShortcutRow[]; }

const label = (key: string): string => key.toUpperCase();

/** A remappable action's row: the user's key (none when unassigned), plus any
 *  fixed keys that do the same thing (`0` also rejects). */
function remappable(map: KeymapConfig, id: ShortcutActionId, fixed: string[] = []): ShortcutRow {
  return { keys: [...fixed, ...(map[id] ? [label(map[id])] : [])], labelKey: shortcutAction(id).labelKey };
}

export function galleryShortcutSection(map: KeymapConfig): ShortcutSection {
  return {
    titleKey: I18N.shortcuts.section_gallery,
    rows: [
      { keys: ['←', '→', '↑', '↓'], labelKey: I18N.shortcuts.navigate },
      { keys: ['Enter'], labelKey: I18N.shortcuts.open_detail },
      { keys: ['Space'], labelKey: I18N.shortcuts.toggle_select },
      { keys: ['Ctrl', 'A'], labelKey: I18N.shortcuts.select_all },
      { keys: ['1', '–', '5'], labelKey: I18N.shortcuts.rate },
      remappable(map, 'keep'),
      remappable(map, 'reject', ['0']),
      remappable(map, 'favourite'),
      remappable(map, 'stack'),
      { keys: ['⌘/Ctrl', 'Shift', 'S'], labelKey: I18N.shortcuts.quick_stack },
      UNDO_SHORTCUT_ROW,
      { keys: ['Esc'], labelKey: I18N.shortcuts.clear_selection },
      { keys: ['Shift', 'F10'], labelKey: I18N.shortcuts.context_menu },
      remappable(map, 'focusSearch'),
      remappable(map, 'toggleSidebar'),
      remappable(map, 'swapLayout'),
    ],
  };
}

export function photoShortcutSection(map: KeymapConfig): ShortcutSection {
  return {
    titleKey: I18N.shortcuts.section_detail,
    rows: [
      remappable(map, 'keep'),
      { keys: ['↑', '↓'], labelKey: I18N.shortcuts.navigate },
      { keys: ['←', '→'], labelKey: I18N.shortcuts.navigate_set },
      { keys: ['1', '–', '5'], labelKey: I18N.shortcuts.rate },
      remappable(map, 'reject', ['0']),
      remappable(map, 'favourite'),
      UNDO_SHORTCUT_ROW,
      { keys: ['Esc'], labelKey: I18N.shortcuts.close },
    ],
  };
}
