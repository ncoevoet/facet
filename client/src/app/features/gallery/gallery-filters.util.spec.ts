import { describe, it, expect, beforeEach } from 'vitest';
import {
  DEFAULT_FILTERS,
  type GalleryFilters,
  applyQueryParams,
  buildApiParams,
  buildSyncParams,
  countActiveFilters,
  loadDisplayOptionsFromStorage,
  saveDisplayOptionsToStorage,
  DISPLAY_OPTIONS_KEY,
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
  it('parses page as int with fallback to 1', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { page: '3' }).page).toBe(3);
    expect(applyQueryParams(DEFAULT_FILTERS, { page: 'x' }).page).toBe(1);
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
  it('returns {} when storage is empty', () => {
    expect(loadDisplayOptionsFromStorage()).toEqual({});
  });
  it('returns {} on malformed JSON', () => {
    localStorage.setItem(DISPLAY_OPTIONS_KEY, '{bad');
    expect(loadDisplayOptionsFromStorage()).toEqual({});
  });
});
