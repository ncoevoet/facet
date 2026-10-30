import { I18N } from '../../core/i18n/keys';
import { KeymapConfig } from '../../core/services/keyboard-mapping.service';

/** The gallery's and photo page's keyboard references. One builder per page
 *  feeds the `?` shortcuts dialog and, for the gallery, the help dialog the
 *  user menu opens on the gallery routes, so they can never list different
 *  keys — and both show the keys the user actually remapped, not the
 *  defaults. */
export interface ShortcutRow { keys: string[]; labelKey: string; }

export interface ShortcutSection { titleKey: string; rows: ShortcutRow[]; }

const label = (key: string): string => key.toUpperCase();

export function galleryShortcutSection(map: KeymapConfig): ShortcutSection {
  return {
    titleKey: I18N.shortcuts.section_gallery,
    rows: [
      { keys: ['←', '→', '↑', '↓'], labelKey: I18N.shortcuts.navigate },
      { keys: ['Enter'], labelKey: I18N.shortcuts.open_detail },
      { keys: ['Space'], labelKey: I18N.shortcuts.toggle_select },
      { keys: ['Ctrl', 'A'], labelKey: I18N.shortcuts.select_all },
      { keys: ['1', '–', '5'], labelKey: I18N.shortcuts.rate },
      { keys: [label(map.keep)], labelKey: I18N.review.shortcut },
      { keys: ['0', label(map.reject)], labelKey: I18N.shortcuts.reject },
      { keys: [label(map.favourite)], labelKey: I18N.shortcuts.favorite },
      { keys: map.stack ? [label(map.stack)] : [], labelKey: I18N.shortcuts.stack },
      { keys: ['⌘/Ctrl', 'Shift', 'S'], labelKey: I18N.shortcuts.quick_stack },
      { keys: ['Esc'], labelKey: I18N.shortcuts.clear_selection },
      { keys: ['Shift', 'F10'], labelKey: I18N.shortcuts.context_menu },
      { keys: [label(map.focusSearch)], labelKey: I18N.shortcuts.focus_search },
      { keys: [label(map.toggleSidebar)], labelKey: I18N.shortcuts.toggle_filters },
      { keys: [label(map.swapLayout)], labelKey: I18N.shortcuts.toggle_layout },
    ],
  };
}

export function photoShortcutSection(map: KeymapConfig): ShortcutSection {
  return {
    titleKey: I18N.shortcuts.section_detail,
    rows: [
      { keys: [label(map.keep)], labelKey: I18N.review.shortcut },
      { keys: ['←', '→'], labelKey: I18N.shortcuts.navigate },
      { keys: ['1', '–', '5'], labelKey: I18N.shortcuts.rate },
      { keys: ['0', label(map.reject)], labelKey: I18N.shortcuts.reject },
      { keys: [label(map.favourite)], labelKey: I18N.shortcuts.favorite },
      { keys: ['Esc'], labelKey: I18N.shortcuts.close },
    ],
  };
}
