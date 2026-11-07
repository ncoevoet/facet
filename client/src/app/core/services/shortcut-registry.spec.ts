import { SHORTCUT_REGISTRY, shareScope, UNDO_SHORTCUT_ROW } from './shortcut-registry';
import { assignableKey, DEFAULT_KEYMAP } from './keyboard-mapping.service';
import { galleryShortcutSection, photoShortcutSection } from '../../features/gallery/gallery-shortcuts';
import { CULLING_SHORTCUT_SECTIONS, STACK_SHORTCUT_SECTIONS } from '../../features/gallery/culling-shortcuts';

describe('SHORTCUT_REGISTRY', () => {
  it('has unique ids, and every default is assignable', () => {
    const ids = SHORTCUT_REGISTRY.map(a => a.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const a of SHORTCUT_REGISTRY) expect(assignableKey(a.defaultKey)).toBe(a.defaultKey);
  });

  it('gives no two actions on the same page the same default key', () => {
    for (const a of SHORTCUT_REGISTRY) {
      for (const b of SHORTCUT_REGISTRY) {
        if (a !== b && a.defaultKey && shareScope(a, b)) expect(b.defaultKey, `${a.id} vs ${b.id}`).not.toBe(a.defaultKey);
      }
    }
  });

  it('is the source of the default keymap', () => {
    expect(Object.keys(DEFAULT_KEYMAP)).toEqual(SHORTCUT_REGISTRY.map(a => a.id));
  });

  it('treats actions on disjoint pages as free to share a key', () => {
    expect(shareScope({ scopes: ['gallery'] }, { scopes: ['photo'] })).toBe(false);
    expect(shareScope({ scopes: ['gallery', 'photo'] }, { scopes: ['photo'] })).toBe(true);
  });

  it.each([
    ['gallery', galleryShortcutSection],
    ['photo', photoShortcutSection],
  ] as const)('lists every %s action in that page\'s ? reference, under the registry label', (scope, build) => {
    const labels = build(DEFAULT_KEYMAP).rows.map(r => r.labelKey);
    for (const a of SHORTCUT_REGISTRY.filter(x => (x.scopes as readonly string[]).includes(scope))) {
      expect(labels).toContain(a.labelKey);
    }
  });

  it('shows the user\'s key, not the default, and an empty key list when unassigned', () => {
    const rows = galleryShortcutSection({ ...DEFAULT_KEYMAP, reject: 'r', stack: '' }).rows;
    const byLabel = (id: string) => rows.find(r => r.labelKey === SHORTCUT_REGISTRY.find(a => a.id === id)!.labelKey)!;
    expect(byLabel('reject').keys).toEqual(['0', 'R']);
    expect(byLabel('stack').keys).toEqual([]);
  });

  it('lists Ctrl/Cmd+Z on every page that offers a snackbar Undo', () => {
    expect(galleryShortcutSection(DEFAULT_KEYMAP).rows).toContain(UNDO_SHORTCUT_ROW);
    expect(CULLING_SHORTCUT_SECTIONS[0].rows).toContain(UNDO_SHORTCUT_ROW);
    expect(STACK_SHORTCUT_SECTIONS[0].rows).toContain(UNDO_SHORTCUT_ROW);
  });
});
