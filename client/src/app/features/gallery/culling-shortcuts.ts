/** Keyboard reference data for the culling page and the help dialog.
 *  Extracted from BurstCullingComponent so the help dialog can render the
 *  tables without importing the (lazy, heavy) culling component. */
export interface CullingShortcutRow { keys: string[]; labelKey: string; }

export const DARKROOM_SHORTCUTS: CullingShortcutRow[] = [
  { keys: ['←', '→'], labelKey: 'culling.shortcuts.navigate' },
  { keys: ['↑'], labelKey: 'culling.shortcuts.keep' },
  { keys: ['↓'], labelKey: 'culling.shortcuts.reject' },
  { keys: ['Z'], labelKey: 'culling.shortcuts.zoom' },
  { keys: ['P'], labelKey: 'culling.shortcuts.peaking' },
  { keys: ['G'], labelKey: 'culling.shortcuts.grid' },
  { keys: ['F'], labelKey: 'slideshow.fullscreen' },
  { keys: ['S'], labelKey: 'culling.stack_group' },
  { keys: ['Space'], labelKey: 'culling.shortcuts.confirm_next' },
  { keys: ['Esc'], labelKey: 'culling.shortcuts.close' },
];

export const CULLING_SHORTCUT_SECTIONS: { titleKey: string; rows: CullingShortcutRow[] }[] = [
  {
    titleKey: 'culling.shortcuts.page_title',
    rows: [
      { keys: ['↑', '↓'], labelKey: 'culling.shortcuts.select' },
      { keys: ['←', '→'], labelKey: 'culling.shortcuts.navigate' },
      { keys: ['Space'], labelKey: 'culling.shortcuts.toggle' },
      { keys: ['Shift+Space'], labelKey: 'culling.shortcuts.confirm_next' },
      { keys: ['Enter'], labelKey: 'culling.shortcuts.open' },
    ],
  },
  { titleKey: 'culling.shortcuts.darkroom_title', rows: DARKROOM_SHORTCUTS },
];

export const STACK_DARKROOM_SHORTCUTS: CullingShortcutRow[] = [
  { keys: ['R'], labelKey: 'stacks.reject_focused' },
  { keys: ['←', '→'], labelKey: 'culling.shortcuts.navigate' },
  { keys: ['S', 'Enter'], labelKey: 'stacks.stack_cover' },
  { keys: ['X'], labelKey: 'stacks.suggestion_skip' },
  ...DARKROOM_SHORTCUTS.filter(row => ['Z', 'P', 'G', 'F', 'Esc'].includes(row.keys[0])),
];
export const STACK_SHORTCUT_SECTIONS = [
  { titleKey: 'stacks.suggestions', rows: [
    { keys: ['↑', '↓'], labelKey: 'culling.shortcuts.select' },
    { keys: ['Enter'], labelKey: 'culling.shortcuts.open' },
    { keys: ['S'], labelKey: 'stacks.stack_cover' },
    { keys: ['X'], labelKey: 'stacks.suggestion_skip' },
  ] },
  { titleKey: 'culling.shortcuts.darkroom_title', rows: STACK_DARKROOM_SHORTCUTS },
];

export const MANUAL_STACK_SHORTCUT_SECTIONS = [{ titleKey: 'stacks.create', rows: [
  { keys: ['Esc'], labelKey: 'stacks.back_gallery' },
  { keys: ['R'], labelKey: 'stacks.reject_focused' },
  { keys: ['←', '→'], labelKey: 'culling.shortcuts.navigate' },
] }];
