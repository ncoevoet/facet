import { TestBed } from '@angular/core/testing';
import { DEFAULT_KEYMAP, KeyboardMappingService, KEYMAP_STORAGE_KEY } from './keyboard-mapping.service';

describe('KeyboardMappingService', () => {
  const stored = (): unknown => JSON.parse(localStorage.getItem(KEYMAP_STORAGE_KEY)!);

  afterEach(() => localStorage.removeItem(KEYMAP_STORAGE_KEY));

  it('defaults to the built-in bindings when nothing is saved', () => {
    expect(TestBed.inject(KeyboardMappingService).keymap()).toEqual(DEFAULT_KEYMAP);
  });

  it('gives new installs the Stack shortcut S', () => {
    expect(TestBed.inject(KeyboardMappingService).keymap().stack).toBe('s');
  });

  it.each(['favourite', 'reject', 'keep', 'focusSearch', 'toggleSidebar', 'swapLayout'] as const)('preserves an older valid map assigning S to %s', action => {
    const older: Partial<typeof DEFAULT_KEYMAP> = { ...DEFAULT_KEYMAP };
    delete older.stack;
    const saved = { ...older, [action]: 's' };
    localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify(saved));
    const service = TestBed.inject(KeyboardMappingService);
    expect(service.keymap()).toEqual({ ...saved, stack: '' });
    expect(service.matches(new KeyboardEvent('keydown', { key: 's' }), 'stack')).toBe(false);
    expect(service.setKey('stack', 's')).toBe('in_use');
    expect(service.setKey('stack', 'g')).toBeNull();
    expect(stored()).toEqual({ ...saved, stack: 'g' });
  });

  it('keeps an explicitly unassigned Stack action after another preference is saved', () => {
    localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify({ ...DEFAULT_KEYMAP, stack: '', focusSearch: 's' }));
    const service = TestBed.inject(KeyboardMappingService);
    expect(service.keymap().stack).toBe('');
    service.setKey('focusSearch', 'g');
    expect(stored()).toEqual({ ...DEFAULT_KEYMAP, stack: '', focusSearch: 'g' });
  });

  it('lowercases a captured key and persists it per browser', () => {
    const service = TestBed.inject(KeyboardMappingService);
    service.setKey('reject', 'R');
    expect(service.keymap().reject).toBe('r');
    expect(stored()).toEqual({ ...DEFAULT_KEYMAP, reject: 'r' });
  });

  it('updates the live signal the page handlers read', () => {
    const service = TestBed.inject(KeyboardMappingService);
    const before = service.keymap().favourite;
    service.setKey('favourite', 'z');
    expect(service.keymap().favourite).toBe('z');
    expect(before).toBe(DEFAULT_KEYMAP.favourite);
  });

  it('falls back to the defaults for malformed saved values', () => {
    localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify({ favourite: 'ZZ', reject: 7, keep: true, focusSearch: '//', toggleSidebar: 'w' }));
    const service = TestBed.inject(KeyboardMappingService);
    expect(service.keymap().favourite).toBe(DEFAULT_KEYMAP.favourite);
    expect(service.keymap().reject).toBe(DEFAULT_KEYMAP.reject);
    expect(service.keymap().keep).toBe(DEFAULT_KEYMAP.keep);
    expect(service.keymap().focusSearch).toBe(DEFAULT_KEYMAP.focusSearch);
    expect(service.keymap().toggleSidebar).toBe('w');
  });

  it('falls back to the defaults for unparsable storage', () => {
    localStorage.setItem(KEYMAP_STORAGE_KEY, '{not json');
    expect(TestBed.inject(KeyboardMappingService).keymap()).toEqual(DEFAULT_KEYMAP);
  });

  it('refuses a reserved key or one another action holds, and keeps the old binding', () => {
    const service = TestBed.inject(KeyboardMappingService);
    for (const key of ['0', '7', ' ', '?']) expect(service.setKey('favourite', key)).toBe('reserved');
    expect(service.setKey('favourite', 'X')).toBe('in_use');
    expect(service.keymap()).toEqual(DEFAULT_KEYMAP);
    expect(localStorage.getItem(KEYMAP_STORAGE_KEY)).toBeNull();
  });

  it('refuses a character that lowercases to more than one, instead of losing it on reload', () => {
    const service = TestBed.inject(KeyboardMappingService);
    expect(service.setKey('favourite', 'İ')).toBe('reserved');
    expect(service.keymap().favourite).toBe(DEFAULT_KEYMAP.favourite);
  });

  it('ignores a saved reserved key', () => {
    localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify({ ...DEFAULT_KEYMAP, favourite: '7', reject: 'r' }));
    const service = TestBed.inject(KeyboardMappingService);
    expect(service.keymap().favourite).toBe(DEFAULT_KEYMAP.favourite);
    expect(service.keymap().reject).toBe('r');
  });

  it('returns two actions saved on one key to their defaults and keeps the other saved keys', () => {
    localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify({ ...DEFAULT_KEYMAP, favourite: 'q', reject: 'q', keep: 'j' }));
    expect(TestBed.inject(KeyboardMappingService).keymap()).toEqual({ ...DEFAULT_KEYMAP, keep: 'j' });
  });

  it('keeps a valid saved key when a reserved one beside it falls back', () => {
    localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify({ ...DEFAULT_KEYMAP, favourite: '7', keep: 'j' }));
    expect(TestBed.inject(KeyboardMappingService).keymap()).toEqual({ ...DEFAULT_KEYMAP, keep: 'j' });
  });

  it('falls back to every default when a fallen-back key is held by another saved action', () => {
    localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify({ ...DEFAULT_KEYMAP, favourite: '7', reject: 'f' }));
    expect(TestBed.inject(KeyboardMappingService).keymap()).toEqual(DEFAULT_KEYMAP);
  });

  it('resetAll restores every default and persists them', () => {
    const service = TestBed.inject(KeyboardMappingService);
    service.setKey('reject', 'r');
    service.resetAll();
    expect(service.keymap()).toEqual(DEFAULT_KEYMAP);
    expect(stored()).toEqual(DEFAULT_KEYMAP);
  });

  it('matches an event against the mapped key, case-insensitively', () => {
    const service = TestBed.inject(KeyboardMappingService);
    service.setKey('reject', 'r');
    expect(service.matches(new KeyboardEvent('keydown', { key: 'R' }), 'reject')).toBe(true);
    expect(service.matches(new KeyboardEvent('keydown', { key: 'x' }), 'reject')).toBe(false);
  });
});
