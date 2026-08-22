import { describe, it, expect, beforeEach } from 'vitest';
import {
  DEFAULT_FILTERS,
  type GalleryFilters,
  type ViewFilterParams,
  anyHideToggleActive,
  applyQueryParams,
  buildApiParams,
  buildSyncParams,
  countActiveFilters,
  loadDisplayOptionsFromStorage,
  saveDisplayOptionsToStorage,
  DISPLAY_OPTIONS_KEY,
  TOOLTIP_MODES,
  PANEL_ACTIVATIONS,
} from './gallery-filters.util';

function filters(overrides: Partial<GalleryFilters> = {}): GalleryFilters {
  return { ...DEFAULT_FILTERS, ...overrides };
}

describe('countActiveFilters', () => {
  it('returns 0 for defaults', () => {
    expect(countActiveFilters(DEFAULT_FILTERS)).toBe(0);
  });
  it('counts non-empty string filters', () => {
    expect(countActiveFilters(filters({ camera: 'Canon', tag: 'beach' }))).toBe(2);
  });
  it('counts favorites_only and is_monochrome', () => {
    expect(countActiveFilters(filters({ favorites_only: true, is_monochrome: true }))).toBe(2);
  });
  it('counts similar_to and semanticQuery', () => {
    expect(countActiveFilters(filters({ similar_to: '/p.jpg', semanticQuery: 'dog' }))).toBe(2);
  });
  it('never counts the ephemeral set-scope fields', () => {
    // They deliberately escape RANGE_AND_SELECT_KEYS so a set-scoped gallery
    // needs its own dismissible chip -- the badge must stay silent about it.
    expect(countActiveFilters(filters({
      sequence_kind: 'bracket', sequence_group_id: '1', burst_group_id: '5', duplicate_group_id: '9',
    }))).toBe(0);
  });
});

describe('buildApiParams', () => {
  it('always includes pagination + sort', () => {
    expect(buildApiParams(DEFAULT_FILTERS, false)).toMatchObject({
      page: 1, per_page: 64, sort: 'aggregate', sort_direction: 'DESC',
    });
  });
  it('omits empty string filters but includes non-empty ones', () => {
    const p = buildApiParams(filters({ camera: 'Canon' }), false);
    expect(p['camera']).toBe('Canon');
    expect(p['lens']).toBeUndefined();
  });
  it('encodes hide_* booleans only when true', () => {
    const p = buildApiParams(filters({ hide_blinks: true, hide_bursts: false }), false);
    expect(p['hide_blinks']).toBe(true);
    expect(p['hide_bursts']).toBeUndefined();
  });
  it('drops album_id for smart albums but keeps it otherwise', () => {
    expect(buildApiParams(filters({ album_id: '7' }), true)['album_id']).toBeUndefined();
    expect(buildApiParams(filters({ album_id: '7' }), false)['album_id']).toBe('7');
  });
  it('sends the set-scope fields to the API when set', () => {
    const p = buildApiParams(filters({ sequence_kind: 'bracket', sequence_group_id: '1' }), false);
    expect(p['sequence_kind']).toBe('bracket');
    expect(p['sequence_group_id']).toBe('1');
  });
});

describe('buildSyncParams', () => {
  it('is empty when filters equal defaults', () => {
    expect(buildSyncParams(DEFAULT_FILTERS, undefined)).toEqual({});
  });
  it('includes sort only when it differs from the effective default', () => {
    expect(buildSyncParams(filters({ sort: 'date_taken' }), undefined)['sort']).toBe('date_taken');
    expect(buildSyncParams(filters({ sort: 'date_taken' }), { sort: 'date_taken' })['sort']).toBeUndefined();
  });
  it('includes similarity_mode only when non-visual and similar_to is set', () => {
    expect(
      buildSyncParams(filters({ similar_to: '/p.jpg', similarity_mode: 'color' }), undefined)['similarity_mode'],
    ).toBe('color');
  });
  it('emits hide_blinks=false when it differs from the true default', () => {
    expect(buildSyncParams(filters({ hide_blinks: false }), undefined)['hide_blinks']).toBe('false');
  });
  it('never writes the set-scope fields to the URL', () => {
    // sequence_group_id is renumbered from 1 on every detection pass, so a
    // bookmarked/shared URL carrying it would silently resolve to a
    // different set later -- it must stay in-memory only.
    const p = buildSyncParams(filters({
      sequence_kind: 'bracket', sequence_group_id: '1', burst_group_id: '5', duplicate_group_id: '9',
    }), undefined);
    expect(p['sequence_kind']).toBeUndefined();
    expect(p['sequence_group_id']).toBeUndefined();
    expect(p['burst_group_id']).toBeUndefined();
    expect(p['duplicate_group_id']).toBeUndefined();
  });
});

describe('applyQueryParams', () => {
  it('overlays string params', () => {
    const r = applyQueryParams(DEFAULT_FILTERS, { camera: 'Nikon', tag: 'sky' });
    expect(r.camera).toBe('Nikon');
    expect(r.tag).toBe('sky');
  });
  it('parses boolean params', () => {
    const r = applyQueryParams(DEFAULT_FILTERS, { hide_blinks: 'false', favorites_only: 'true' });
    expect(r.hide_blinks).toBe(false);
    expect(r.favorites_only).toBe(true);
  });
  it('validates similarity_mode against the allowlist', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { similarity_mode: 'bogus' }).similarity_mode).toBe('visual');
    expect(applyQueryParams(DEFAULT_FILTERS, { similarity_mode: 'color' }).similarity_mode).toBe('color');
  });
  it('accepts every tooltip mode and ignores anything else', () => {
    // The parser silently drops unknown values, so a mode missing from the
    // allowlist is un-shareable via URL rather than visibly broken.
    for (const mode of TOOLTIP_MODES) {
      expect(applyQueryParams(DEFAULT_FILTERS, { tooltip_mode: mode }).tooltip_mode).toBe(mode);
    }
    expect(applyQueryParams(DEFAULT_FILTERS, { tooltip_mode: 'sidebar' }).tooltip_mode)
      .toBe(DEFAULT_FILTERS.tooltip_mode);
  });
  it('accepts every panel activation and ignores anything else', () => {
    for (const activation of PANEL_ACTIVATIONS) {
      expect(applyQueryParams(DEFAULT_FILTERS, { panel_activation: activation }).panel_activation)
        .toBe(activation);
    }
    expect(applyQueryParams(DEFAULT_FILTERS, { panel_activation: 'bogus' }).panel_activation)
      .toBe(DEFAULT_FILTERS.panel_activation);
  });
  it('parses page as int with fallback to 1', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { page: '3' }).page).toBe(3);
    expect(applyQueryParams(DEFAULT_FILTERS, { page: 'x' }).page).toBe(1);
  });
  it('ignores the set-scope fields even if present in the URL', () => {
    // A crafted or stale URL must not resurrect a scope the server would
    // resolve against a since-renumbered group id.
    const r = applyQueryParams(DEFAULT_FILTERS, {
      sequence_kind: 'bracket', sequence_group_id: '1', burst_group_id: '5', duplicate_group_id: '9',
    });
    expect(r.sequence_kind).toBe('');
    expect(r.sequence_group_id).toBe('');
    expect(r.burst_group_id).toBe('');
    expect(r.duplicate_group_id).toBe('');
  });
  it('round-trips through buildSyncParams', () => {
    const original = filters({ camera: 'Canon', min_score: '7', hide_blinks: false, favorites_only: true });
    const restored = applyQueryParams(DEFAULT_FILTERS, buildSyncParams(original, undefined));
    expect(restored.camera).toBe('Canon');
    expect(restored.min_score).toBe('7');
    expect(restored.hide_blinks).toBe(false);
    expect(restored.favorites_only).toBe(true);
  });
});

describe('display options storage', () => {
  beforeEach(() => localStorage.clear());
  it('saves and loads the display subset', () => {
    saveDisplayOptionsToStorage(filters({ hide_details: false, tooltip_mode: 'click', is_monochrome: true }));
    const loaded = loadDisplayOptionsFromStorage();
    expect(loaded.hide_details).toBe(false);
    expect(loaded.tooltip_mode).toBe('click');
    expect(loaded.is_monochrome).toBe(true);
  });
  it('saves and loads panel_activation, same channel as tooltip_mode', () => {
    saveDisplayOptionsToStorage(filters({ panel_activation: 'click' }));
    expect(loadDisplayOptionsFromStorage().panel_activation).toBe('click');
  });
  it('returns {} when storage is empty', () => {
    expect(loadDisplayOptionsFromStorage()).toEqual({});
  });
  it('returns {} on malformed JSON', () => {
    localStorage.setItem(DISPLAY_OPTIONS_KEY, '{bad');
    expect(loadDisplayOptionsFromStorage()).toEqual({});
  });
});

describe('per-channel clipping filters', () => {
  const CLIPPING = {
    min_channel_clip_highlight: '5',
    max_channel_clip_shadow: '2',
  };

  it('reaches the API', () => {
    const p = buildApiParams(filters(CLIPPING), false);
    expect(p['min_channel_clip_highlight']).toBe('5');
    expect(p['max_channel_clip_shadow']).toBe('2');
  });

  it('round-trips through the URL', () => {
    // Unlike the ephemeral set-scope fields, this is a real filter: a link to
    // "everything with blown highlights" has to survive being bookmarked.
    const synced = buildSyncParams(filters(CLIPPING), undefined);
    expect(synced['min_channel_clip_highlight']).toBe('5');
    expect(synced['max_channel_clip_shadow']).toBe('2');

    const restored = applyQueryParams(DEFAULT_FILTERS, synced);
    expect(restored.min_channel_clip_highlight).toBe('5');
    expect(restored.max_channel_clip_shadow).toBe('2');
  });

  it('counts towards the active-filter badge', () => {
    expect(countActiveFilters(filters(CLIPPING))).toBe(2);
  });

  it('is absent from the defaults, so it never filters until asked for', () => {
    expect(DEFAULT_FILTERS.min_channel_clip_highlight).toBe('');
    expect(buildApiParams(DEFAULT_FILTERS, false)['min_channel_clip_highlight']).toBeUndefined();
  });
});

describe('anyHideToggleActive', () => {
  const allOff: ViewFilterParams = {
    hide_blinks: '0',
    hide_bursts: '0',
    hide_duplicates: '0',
    hide_brackets: '0',
    hide_panoramas: '0',
  };
  const keys: (keyof ViewFilterParams)[] = [
    'hide_blinks', 'hide_bursts', 'hide_duplicates', 'hide_brackets', 'hide_panoramas',
  ];

  it('returns false when every toggle is off', () => {
    expect(anyHideToggleActive(allOff)).toBe(false);
  });

  it.each(keys)('returns true when only %s is on', key => {
    expect(anyHideToggleActive({ ...allOff, [key]: '1' })).toBe(true);
  });
});
