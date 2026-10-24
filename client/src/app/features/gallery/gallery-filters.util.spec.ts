import { describe, it, expect, beforeEach } from 'vitest';
import serverFilterKeys from './gallery-filters.generated.json';
import goldenAlbum from './testing/smart-album-stored.json';
import {
  DEFAULT_FILTERS,
  type GalleryFilters,
  type ViewFilterParams,
  anyHideToggleActive,
  applyQueryParams,
  buildApiParams,
  buildByPathsFilters,
  BY_PATHS_MAX,
  buildSyncParams,
  seededSearchThreshold,
  semanticSortPatch,
  RELEVANCE_SORT,
  smartAlbumFilterJson,
  applySavedAlbumFilters,
  exclusiveHidePatch,
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
    expect(buildApiParams(DEFAULT_FILTERS, false, undefined)).toMatchObject({
      page: 1, per_page: 64, sort: 'aggregate', sort_direction: 'DESC',
    });
  });
  it('omits empty string filters but includes non-empty ones', () => {
    const p = buildApiParams(filters({ camera: 'Canon' }), false, undefined);
    expect(p['camera']).toBe('Canon');
    expect(p['lens']).toBeUndefined();
  });
  it('encodes hide_* booleans only when true', () => {
    const p = buildApiParams(filters({ hide_blinks: true, hide_bursts: false }), false, undefined);
    expect(p['hide_blinks']).toBe(true);
    expect(p['hide_bursts']).toBeUndefined();
  });
  it('drops album_id for smart albums but keeps it otherwise', () => {
    expect(buildApiParams(filters({ album_id: '7' }), true, undefined)['album_id']).toBeUndefined();
    expect(buildApiParams(filters({ album_id: '7' }), false, undefined)['album_id']).toBe('7');
  });
  it('sends the set-scope fields to the API when set', () => {
    const p = buildApiParams(filters({ sequence_kind: 'bracket', sequence_group_id: '1' }), false, undefined);
    expect(p['sequence_kind']).toBe('bracket');
    expect(p['sequence_group_id']).toBe('1');
  });
});

describe('buildApiParams semantic search', () => {
  it('emits semantic_q alone while the slider sits on the seed', () => {
    const p = buildApiParams(filters({ semanticQuery: 'sunset', search_threshold: '5' }), false, 0.05);
    expect(p['semantic_q']).toBe('sunset');
    expect(p).not.toHaveProperty('semantic_threshold');
  });
  it('emits semantic_threshold as a fraction once off the seed', () => {
    expect(buildApiParams(filters({ semanticQuery: 'sunset', search_threshold: '12' }), false, 0.05)['semantic_threshold']).toBe(0.12);
  });
  it('omits the threshold when the seed is unknown and the slider unset', () => {
    expect(buildApiParams(filters({ semanticQuery: 'sunset', search_threshold: '' }), false, undefined))
      .not.toHaveProperty('semantic_threshold');
  });
  it('emits neither key without a query', () => {
    const p = buildApiParams(filters({ search_threshold: '12' }), false, 0.05);
    expect(p).not.toHaveProperty('semantic_q');
    expect(p).not.toHaveProperty('semantic_threshold');
  });
  it('changes the serialised params on a slider-only move', () => {
    const at = (t: string) => JSON.stringify(buildApiParams(filters({ semanticQuery: 'x', search_threshold: t }), false, 0.05));
    expect(at('12')).not.toBe(at('5'));
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
  it('emits search_threshold only when semanticQuery is set', () => {
    expect(
      buildSyncParams(filters({ semanticQuery: 'dog', search_threshold: '12' }), undefined)['search_threshold'],
    ).toBe('12');
    expect(
      buildSyncParams(filters({ search_threshold: '12' }), undefined)['search_threshold'],
    ).toBeUndefined();
  });
  it('omits a search_threshold still sitting on the server seed, emits a changed one', () => {
    // 0.05 seeds '5'. Emitting the seed froze it into every shared link, so a
    // later server-side recalibration could never reach an existing bookmark.
    expect(
      buildSyncParams(filters({ semanticQuery: 'dog', search_threshold: '5' }), undefined, 0.05)['search_threshold'],
    ).toBeUndefined();
    expect(
      buildSyncParams(filters({ semanticQuery: 'dog', search_threshold: '12' }), undefined, 0.05)['search_threshold'],
    ).toBe('12');
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
  it('round-trips search_threshold only when emitted alongside semanticQuery', () => {
    const original = filters({ semanticQuery: 'dog', search_threshold: '12' });
    const restored = applyQueryParams(DEFAULT_FILTERS, buildSyncParams(original, undefined));
    expect(restored.search_threshold).toBe('12');
  });
  it('drops a non-numeric search_threshold rather than forwarding threshold=NaN', () => {
    // `+'abc' / 100` is NaN, which the API rejects with a 422 the gallery shows
    // only as a bare load error. '' is the meaningful value: the server then
    // resolves its own per-model default.
    expect(applyQueryParams(DEFAULT_FILTERS, { search_threshold: 'abc' }).search_threshold).toBe('');
  });
  it('clamps an out-of-range search_threshold to the slider span', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { search_threshold: '900' }).search_threshold).toBe('50');
    expect(applyQueryParams(DEFAULT_FILTERS, { search_threshold: '-3' }).search_threshold).toBe('0');
    expect(applyQueryParams(DEFAULT_FILTERS, { search_threshold: '7.6' }).search_threshold).toBe('8');
  });
});

describe('smartAlbumFilterJson', () => {
  it('drops the relevance sort with the semantic query it ranks', () => {
    const saved = JSON.parse(smartAlbumFilterJson(filters({
      semanticQuery: 'sunset', sort: RELEVANCE_SORT, sort_direction: 'DESC', camera: 'X100V',
    })));
    expect(saved).toEqual({ camera: 'X100V' });
  });

  it('keeps an ordinary sort', () => {
    const saved = JSON.parse(smartAlbumFilterJson(filters({ sort: 'date_taken', sort_direction: 'ASC' })));
    expect(saved.sort).toBe('date_taken');
    expect(saved.sort_direction).toBe('ASC');
  });
});

describe('applySavedAlbumFilters (golden fixture shared with the agent create_album tool)', () => {
  const stored = JSON.stringify(goldenAlbum.stored);

  it('lays the stored client form over the store with booleans kept and person_id / type populated', () => {
    const result = applySavedAlbumFilters(filters(), stored, '42');
    expect(result.album_id).toBe('42');
    expect(result.person_id).toBe('9001');
    expect(result.type).toBe('portrait');
    expect(result.favorites_only).toBe(true);
    expect(result.is_monochrome).toBe(true);
    const slice = Object.fromEntries(Object.keys(goldenAlbum.stored).map(k => [k, (result as unknown as Record<string, unknown>)[k]]));
    expect(slice).toEqual(goldenAlbum.stored);
  });

  it('serialises back to the same JSON, so the album auto-save does not rewrite what the agent stored', () => {
    const again = JSON.parse(smartAlbumFilterJson(applySavedAlbumFilters(filters(), stored, '42')));
    // The store always carries its sort; everything the agent stored is unchanged.
    expect(again).toEqual({ ...goldenAlbum.stored, sort: 'aggregate', sort_direction: 'DESC' });
  });
});

describe('applySavedAlbumFilters and the hide_rejected / favorites_only exclusion', () => {
  it('turns hide_rejected off for a favourites-only album, as the store does, so a rejected favourite is listed', () => {
    const result = applySavedAlbumFilters({ ...filters(), hide_rejected: true }, JSON.stringify({ favorites_only: true }), '7');
    expect(result.favorites_only).toBe(true);
    expect(result.hide_rejected).toBe(false);
  });

  it('keeps the viewer hide_rejected for an album that is not favourites-only', () => {
    const result = applySavedAlbumFilters({ ...filters(), hide_rejected: true }, JSON.stringify({ min_score: '6' }), '7');
    expect(result.hide_rejected).toBe(true);
  });
});

describe('exclusiveHidePatch', () => {
  it('clears the companion of whichever is turned on, and nothing when both are off', () => {
    expect(exclusiveHidePatch({ hide_rejected: true })).toEqual({ favorites_only: false });
    expect(exclusiveHidePatch({ favorites_only: true })).toEqual({ hide_rejected: false });
    expect(exclusiveHidePatch({ hide_rejected: false, favorites_only: false })).toEqual({});
  });
});

describe('seededSearchThreshold', () => {
  it('renders a 0-1 fraction as a whole percent string', () => {
    expect(seededSearchThreshold(0.05)).toBe('5');
    expect(seededSearchThreshold(0.15)).toBe('15');
  });
  it('returns "" for anything not a finite number, so /search omits threshold', () => {
    expect(seededSearchThreshold(undefined)).toBe('');
    expect(seededSearchThreshold(null)).toBe('');
    expect(seededSearchThreshold(NaN)).toBe('');
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
    const p = buildApiParams(filters(CLIPPING), false, undefined);
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
    expect(buildApiParams(DEFAULT_FILTERS, false, undefined)['min_channel_clip_highlight']).toBeUndefined();
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

 describe('review status codec', () => {
  it.each(['undecided', 'kept', 'rejected'] as const)('round trips %s and overrides hide rejected', review_status => {
    const f = filters({ review_status });
    expect(applyQueryParams(DEFAULT_FILTERS, buildSyncParams(f, undefined)).review_status).toBe(review_status);
    expect(buildApiParams(f, false, undefined)).toMatchObject({ review_status });
    expect(buildApiParams(f, false, undefined)['hide_rejected']).toBeUndefined();
  });
  it('ignores invalid review statuses', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { review_status: 'bad' }).review_status).toBe('');
  });
});

describe('review URL normalization', () => {
  it('drops relevance after a review status clears a semantic query', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { review_status: 'kept', semanticQuery: 'sunset', sort: RELEVANCE_SORT }))
      .toMatchObject({ semanticQuery: '', sort: 'aggregate' });
  });

  it('clears ranked searches and retains ordinary filters', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { review_status: 'kept', semanticQuery: 'sunset', similar_to: '/a.jpg', search: 'beach', album_id: '3' }))
      .toMatchObject({ review_status: 'kept', semanticQuery: '', similar_to: '', search: 'beach', album_id: '3' });
  });
});

// The only keys POST /photos/by_paths accepts in `filters` (any other is a 422), generated from
// `gallery_filter_keys()` by scripts/dump_filter_keys.py; tests/test_dump_filter_keys.py fails CI when stale.
const SERVER_FILTER_KEYS: ReadonlySet<string> = new Set<string>(serverFilterKeys);

describe('buildByPathsFilters', () => {
  it('carries the view filters but no paging or sort', () => {
    const p = buildByPathsFilters(filters({ hide_rejected: true, camera: 'Canon', album_id: '4', min_score: '7' }), false, '', undefined);
    expect(p).toMatchObject({ hide_rejected: true, camera: 'Canon', album_id: '4', min_score: '7' });
    for (const key of ['page', 'per_page', 'sort', 'sort_direction']) expect(p).not.toHaveProperty(key);
  });
  it('strips both semantic keys, which by_paths would 422', () => {
    const p = buildByPathsFilters(filters({ semanticQuery: 'sunset', search_threshold: '12', camera: 'Canon' }), false, '', 0.05);
    expect(p).toMatchObject({ camera: 'Canon' });
    expect(p).not.toHaveProperty('semantic_q');
    expect(p).not.toHaveProperty('semantic_threshold');
  });
  it('sends the viewer default type explicitly when the filter has none', () => {
    expect(buildByPathsFilters(filters(), false, 'top_picks', undefined)['type']).toBe('top_picks');
    expect(buildByPathsFilters(filters({ type: 'portrait' }), false, 'top_picks', undefined)['type']).toBe('portrait');
  });
  it('sends an empty type for a person view, as GET /photos resolves it', () => {
    expect(buildByPathsFilters(filters({ person_id: '3' }), false, 'top_picks', undefined)['type']).toBe('');
  });
  it('drops album_id for a smart album', () => {
    expect(buildByPathsFilters(filters({ album_id: '4' }), true, '', undefined)).not.toHaveProperty('album_id');
  });
  it('emits only keys the server accepts, so none can 422', () => {
    const every: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(DEFAULT_FILTERS)) every[key] = typeof value === 'boolean' ? true : 'x';
    const emitted = Object.keys(buildByPathsFilters(filters(every as Partial<GalleryFilters>), false, 'x', undefined));
    expect(emitted.length).toBeGreaterThan(20);
    expect(emitted.filter(key => !SERVER_FILTER_KEYS.has(key))).toEqual([]);
  });
  it('chunks at the server cap', () => {
    expect(BY_PATHS_MAX).toBe(500);
  });
});

describe('relevance sort', () => {
  it('never leaves sort=relevance when no_gps clears the semantic query', () => {
    const f = applyQueryParams(DEFAULT_FILTERS, { no_gps: '1', semanticQuery: 'sunset' });
    expect(f.semanticQuery).toBe('');
    expect(f.sort).not.toBe(RELEVANCE_SORT);
    const g = applyQueryParams(DEFAULT_FILTERS, { no_gps: '1', semanticQuery: 'sunset', sort: RELEVANCE_SORT });
    expect(g.semanticQuery).toBe('');
    expect(g.sort).not.toBe(RELEVANCE_SORT);
  });

  const defaults = { sort: 'aggregate', sort_direction: 'DESC' };
  it('is implied by a semantic query, so a link carrying only the query loads as relevance', () => {
    const restored = applyQueryParams(DEFAULT_FILTERS, { semanticQuery: 'dog' });
    expect(restored).toMatchObject({ sort: RELEVANCE_SORT, sort_direction: 'DESC' });
  });
  it('keeps an explicit sort next to the query', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { semanticQuery: 'dog', sort: 'date_taken', sort_direction: 'ASC' }))
      .toMatchObject({ sort: 'date_taken', sort_direction: 'ASC' });
  });
  it('drops a relevance sort that arrives without a query', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { sort: RELEVANCE_SORT }).sort).toBe('aggregate');
  });
  it('does not write the implied sort, but writes any other one even when it equals the default', () => {
    expect(buildSyncParams(filters({ semanticQuery: 'dog', sort: RELEVANCE_SORT }), undefined)).not.toHaveProperty('sort');
    expect(buildSyncParams(filters({ semanticQuery: 'dog', sort: 'aggregate' }), undefined)['sort']).toBe('aggregate');
  });
  it('round-trips every sort/direction combination under a query', () => {
    for (const sort of [RELEVANCE_SORT, 'aggregate', 'date_taken']) {
      for (const sort_direction of ['DESC', 'ASC']) {
        const original = filters({ semanticQuery: 'dog', sort, sort_direction });
        const restored = applyQueryParams(DEFAULT_FILTERS, buildSyncParams(original, undefined));
        expect(restored).toMatchObject({ sort, sort_direction });
      }
    }
  });
  it('sends sort=relevance to the API', () => {
    expect(buildApiParams(filters({ semanticQuery: 'dog', sort: RELEVANCE_SORT }), false, 0.05)['sort']).toBe(RELEVANCE_SORT);
  });
  it('semanticSortPatch selects relevance on a new query and restores the default on clear', () => {
    expect(semanticSortPatch(DEFAULT_FILTERS, { semanticQuery: 'dog' }, defaults)).toEqual({ sort: RELEVANCE_SORT, sort_direction: 'DESC' });
    const active = filters({ semanticQuery: 'dog', sort: RELEVANCE_SORT, sort_direction: 'ASC' });
    expect(semanticSortPatch(active, { semanticQuery: '' }, { sort: 'date_taken', sort_direction: 'DESC' }))
      .toEqual({ sort: 'date_taken', sort_direction: 'DESC' });
  });
  it('semanticSortPatch leaves other cases alone', () => {
    expect(semanticSortPatch(filters({ semanticQuery: 'dog' }), { semanticQuery: 'cat' }, defaults)).toEqual({});
    expect(semanticSortPatch(filters({ semanticQuery: 'dog', sort: 'date_taken' }), { semanticQuery: '' }, defaults)).toEqual({});
    expect(semanticSortPatch(DEFAULT_FILTERS, { semanticQuery: 'dog', sort: 'date_taken' }, defaults)).toEqual({});
    expect(semanticSortPatch(DEFAULT_FILTERS, { camera: 'Canon' }, defaults)).toEqual({});
  });
});

describe('no geolocation filter', () => {
  it('round trips through URL, API, and filter count and clears radius/search conflicts', () => {
    const f = applyQueryParams(DEFAULT_FILTERS, { no_gps: '1', gps_lat: '0', gps_lng: '0', gps_radius_km: '5', semanticQuery: 'sunset', similar_to: '/photo.jpg' });
    expect(f).toMatchObject({ no_gps: '1', gps_lat: '', gps_lng: '', gps_radius_km: '', semanticQuery: '', similar_to: '' });
    expect(buildApiParams(f, false, undefined)).toMatchObject({ no_gps: '1' });
    expect(applyQueryParams(DEFAULT_FILTERS, buildSyncParams(f, undefined)).no_gps).toBe('1');
    expect(countActiveFilters(f)).toBe(1);
  });
});


describe('review and location URL coexistence', () => {
  it('retains both ordinary filters while clearing incompatible ranked and radius modes', () => {
    const f = applyQueryParams(DEFAULT_FILTERS, { review_status: 'kept', no_gps: '1', semanticQuery: 'sunset', similar_to: '/a.jpg', gps_lat: '0', gps_lng: '0', gps_radius_km: '5' });
    expect(f).toMatchObject({ review_status: 'kept', no_gps: '1', semanticQuery: '', similar_to: '', gps_lat: '', gps_lng: '', gps_radius_km: '' });
    expect(applyQueryParams(DEFAULT_FILTERS, buildSyncParams(f, undefined))).toMatchObject({ review_status: 'kept', no_gps: '1' });
    expect(buildApiParams(f, false, undefined)).toMatchObject({ review_status: 'kept', no_gps: '1' });
  });
});
