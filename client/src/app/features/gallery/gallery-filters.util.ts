/**
 * Pure filter logic for the gallery: types, defaults, and the URL/API/storage
 * codec. Extracted from gallery.store.ts so it can be unit-tested in isolation
 * and reused. Nothing here touches Angular signals, the router, or HTTP — the
 * store owns that and calls these functions.
 */

export type GalleryMode = 'grid' | 'mosaic';
export type TooltipMode = 'hover' | 'click' | 'off' | 'panel';

/** Every accepted tooltip mode, so the URL parser and the mode picker cannot drift apart. */
export const TOOLTIP_MODES: readonly TooltipMode[] = ['hover', 'click', 'off', 'panel'];

/** Which gesture(s) retarget the docked panel (tooltip_mode 'panel'). Meaningless
 *  for every other tooltip mode, which already has a single, fixed gesture.
 *  Default 'both' preserves the original panel behaviour exactly. */
export type PanelActivation = 'hover' | 'click' | 'both';

export const PANEL_ACTIVATIONS: readonly PanelActivation[] = ['hover', 'click', 'both'];

export const GALLERY_MODE_KEY = 'facet_gallery_mode';
export const DRAWER_STATE_KEY = 'facet_filter_drawer_open';
export const DISPLAY_OPTIONS_KEY = 'facet_display_options';
export const CARD_WIDTH_KEY = 'facet_card_width';
/** The gallery's last synced query, for the nav-icon return from another page:
 *  sessionStorage, so it survives tab-wide navigation but not a new session. */
export const GALLERY_SESSION_QUERY_KEY = 'facet_gallery_session_query';
/** The last sort the user picked, remembered across visits (localStorage):
 *  a fresh landing sorts by what you used last, not the viewer default. The
 *  URL always wins — a shared or bookmarked link means what it says. */
export const LAST_SORT_KEY = 'facet_last_sort';

export interface GalleryFilters {
  page: number;
  per_page: number;
  sort: string;
  sort_direction: string;
  type: string;
  camera: string;
  lens: string;
  tag: string;
  person_id: string;
  // Score ranges
  min_score: string;
  max_score: string;
  min_aesthetic: string;
  max_aesthetic: string;
  min_face_quality: string;
  max_face_quality: string;
  min_composition: string;
  max_composition: string;
  min_sharpness: string;
  max_sharpness: string;
  min_exposure: string;
  max_exposure: string;
  min_color: string;
  max_color: string;
  min_contrast: string;
  max_contrast: string;
  min_noise: string;
  max_noise: string;
  min_dynamic_range: string;
  max_dynamic_range: string;
  // Face ranges
  min_face_count: string;
  max_face_count: string;
  min_eye_sharpness: string;
  max_eye_sharpness: string;
  min_face_sharpness: string;
  max_face_sharpness: string;
  min_face_ratio: string;
  max_face_ratio: string;
  min_face_confidence: string;
  max_face_confidence: string;
  // Quality
  min_quality_score: string;
  max_quality_score: string;
  min_topiq: string;
  max_topiq: string;
  // Composition
  min_power_point: string;
  max_power_point: string;
  min_leading_lines: string;
  max_leading_lines: string;
  min_isolation: string;
  max_isolation: string;
  // Extended quality
  min_aesthetic_iaa: string;
  max_aesthetic_iaa: string;
  min_face_quality_iqa: string;
  max_face_quality_iqa: string;
  min_liqe: string;
  max_liqe: string;
  min_qrealign: string;
  max_qrealign: string;
  min_aesthetic_v25: string;
  max_aesthetic_v25: string;
  min_deqa: string;
  max_deqa: string;
  // Subject saliency
  min_subject_sharpness: string;
  max_subject_sharpness: string;
  min_subject_prominence: string;
  max_subject_prominence: string;
  min_subject_placement: string;
  max_subject_placement: string;
  min_bg_separation: string;
  max_bg_separation: string;
  // Narrative moment confidence
  min_moment_confidence: string;
  max_moment_confidence: string;
  // Technical
  min_saturation: string;
  max_saturation: string;
  min_luminance: string;
  max_luminance: string;
  min_histogram_spread: string;
  max_histogram_spread: string;
  /** Per-channel clipping, percent of pixels in the worst of R/G/B. A photo
   *  that was never measured is NULL server-side and matches neither bound:
   *  unknown is not clean. */
  min_channel_clip_shadow: string;
  max_channel_clip_shadow: string;
  min_channel_clip_highlight: string;
  max_channel_clip_highlight: string;
  // User ratings
  min_star_rating: string;
  max_star_rating: string;
  // EXIF ranges
  min_iso: string;
  max_iso: string;
  min_aperture: string;
  max_aperture: string;
  min_focal_length: string;
  max_focal_length: string;
  // Date range
  date_from: string;
  date_to: string;
  // Content
  composition_pattern: string;
  /** Pending panorama corrections: '' | 'any' | 'suppressed' | 'forced'. */
  sequence_override: string;
  // Similar-to filter
  similar_to: string;
  similarity_mode: 'visual' | 'color' | 'person';
  min_similarity: string;
  // Semantic search
  semanticQuery: string;
  /** 0-50 percent, as a string for URL round-trip (same idiom as min_similarity).
   *  Empty means "no client override" -- the server resolves its own
   *  per-model default when `threshold` is omitted entirely. */
  search_threshold: string;
  // Album filter
  album_id: string;
  // Folder filter
  path_prefix: string;
  // GPS filter
  no_gps: string;
  gps_lat: string;
  gps_lng: string;
  gps_radius_km: string;
  // Set scope (photo-detail "open this set in the gallery"). Ephemeral --
  // NEVER added to RANGE_AND_SELECT_KEYS: sequence_group_id is renumbered
  // from 1 on every detection pass, so round-tripping it through the URL
  // would let a bookmarked link silently resolve to a different set later.
  sequence_group_id: string;
  sequence_kind: string;
  burst_group_id: string;
  duplicate_group_id: string;
  // Display
  hide_details: boolean;
  tooltip_mode: TooltipMode;
  panel_activation: PanelActivation;
  hide_blinks: boolean;
  hide_bursts: boolean;
  hide_duplicates: boolean;
  hide_brackets: boolean;
  hide_panoramas: boolean;
  review_status: '' | 'undecided' | 'kept' | 'rejected';
  hide_rejected: boolean;
  favorites_only: boolean;
  // Positive "only X" filters, the counterpart of the hide toggles above.
  // duplicates_only keeps every member of a duplicate group, leads included;
  // the server suppresses the hide toggles while either of the two is set.
  show_rejected: boolean;
  blinks_only: boolean;
  duplicates_only: boolean;
  is_monochrome: boolean;
  manual_faces_need_review: boolean;
  faces_need_names: boolean;
  search: string;
  // Color facet (opt-in extraction; always-on filter)
  color_temp: string;   // warm | cool | neutral
  hue_bucket: string;   // red | orange | yellow | green | cyan | blue | purple | magenta
  // Quality tier (on the fly from aggregate thresholds)
  quality_tier: string; // excellent | good | fair | poor
}

/** Sort that ranks a semantic query's matches by similarity; meaningful only while a query is set. */
export const RELEVANCE_SORT = 'relevance';

/**
 * The sort change a filter patch implies for the semantic query: setting a query from empty selects
 * Relevance (best first); clearing it while Relevance is active restores the viewer default sort.
 * A patch that names a sort itself is never overridden.
 */
export function semanticSortPatch(
  current: GalleryFilters,
  updates: Partial<GalleryFilters>,
  defaults: Pick<FilterDefaults, 'sort' | 'sort_direction'> | undefined,
): Partial<GalleryFilters> {
  if (!('semanticQuery' in updates) || 'sort' in updates) return {};
  if (updates.semanticQuery && !current.semanticQuery) {
    return { sort: RELEVANCE_SORT, sort_direction: updates.sort_direction ?? 'DESC' };
  }
  if (!updates.semanticQuery && current.sort === RELEVANCE_SORT) {
    return { sort: defaults?.sort ?? 'aggregate', sort_direction: defaults?.sort_direction ?? 'DESC' };
  }
  return {};
}

/** Subset of viewer config defaults the URL/sync codec compares against. */
export interface FilterDefaults {
  sort?: string;
  sort_direction?: string;
  hide_details?: boolean;
  hide_blinks?: boolean;
  hide_bursts?: boolean;
  hide_duplicates?: boolean;
  hide_brackets?: boolean;
  hide_panoramas?: boolean;
  hide_rejected?: boolean;
  tooltip_mode?: TooltipMode;
  panel_activation?: PanelActivation;
}

/** Highest match sensitivity the sidebar slider offers, and therefore the
 *  ceiling any URL-supplied `search_threshold` is clamped to. */
export const SEARCH_THRESHOLD_MAX = 50;

/** The percent string the gallery seeds `search_threshold` with, for a given
 *  resolved server default (`/api/config`'s `search_threshold_default`, a 0-1
 *  fraction).
 *
 *  Returns `''` when the server did not answer with a usable number -- an
 *  older backend, or a field that arrived missing. `''` is the meaningful
 *  value, not a fallback percent: it is what makes `/api/photos` omit
 *  `semantic_threshold` entirely and resolve its own per-model default. Guessing a
 *  number here instead would silently diverge from the server's calibration,
 *  and `String(Math.round(undefined * 100))` produced the string `'NaN'`,
 *  which is truthy and reached the API as `threshold=NaN` -> 422.
 *
 *  Single source for the seed: `loadConfig`, `resetFilters`, the sidebar's
 *  readout and both "is this still the untouched default?" comparisons all
 *  go through it. */
export function seededSearchThreshold(searchThresholdDefault: number | null | undefined): string {
  return typeof searchThresholdDefault === 'number' && Number.isFinite(searchThresholdDefault)
    ? String(Math.round(searchThresholdDefault * 100))
    : '';
}

/** Keys excluded when building smart album filter JSON (display-only, ephemeral, or handled separately). */
export const SMART_ALBUM_EXCLUDE_KEYS = new Set([
  'page', 'per_page', 'semanticQuery', 'search_threshold', 'album_id',
  'similar_to', 'similarity_mode', 'min_similarity',
  'hide_details', 'tooltip_mode', 'panel_activation', 'hide_blinks', 'hide_bursts',
  'hide_duplicates', 'hide_brackets', 'hide_panoramas', 'hide_rejected',
  'gps_lat', 'gps_lng', 'gps_radius_km',
  'sequence_group_id', 'sequence_kind', 'burst_group_id', 'duplicate_group_id',
]);

/** The smart-album JSON for a filter state. Relevance is dropped with the semantic query it ranks,
 *  so a reopened album never asks `/api/photos` for `sort=relevance` without `semantic_q` (a 400). */
export function smartAlbumFilterJson(filters: GalleryFilters): string {
  const dropSort = filters.sort === RELEVANCE_SORT;
  const filterJson: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v && v !== '' && !SMART_ALBUM_EXCLUDE_KEYS.has(k) && !(dropSort && (k === 'sort' || k === 'sort_direction'))) {
      filterJson[k] = v;
    }
  }
  return JSON.stringify(filterJson);
}

/** The store's filters once an album opens: the saved smart-album JSON laid over `current`, scoped to `albumId`.
 *  The inverse of `smartAlbumFilterJson`; a golden fixture shared with the server's agent tool
 *  (`testing/smart-album-stored.json`) pins that what an agent stores round-trips through both. */
export function applySavedAlbumFilters(current: GalleryFilters, savedJson: string, albumId: string): GalleryFilters {
  const saved = JSON.parse(savedJson) as Partial<GalleryFilters>;
  return { ...current, ...saved, ...exclusiveHidePatch(saved), album_id: albumId };
}

/** The store's mutual-exclusion rule: "hide rejected" and "favourites only" cannot both hold, so
 *  turning one on turns the other off. Returns only the companion keys to override. Shared by the
 *  store's updates and by `applySavedAlbumFilters`, which spreads a saved album over the viewer's
 *  defaults without going through the store (a favourites-only album would otherwise inherit
 *  `hide_rejected` and list fewer photos than it holds). */
export function exclusiveHidePatch(updates: Partial<GalleryFilters>): Partial<GalleryFilters> {
  const patch: Partial<GalleryFilters> = {};
  if (updates.hide_rejected) {
    patch.favorites_only = false;
    patch.show_rejected = false;
  }
  if (updates.favorites_only) {
    patch.hide_rejected = false;
    patch.show_rejected = false;
  }
  // "Only rejected" is the inverse reading of "hide rejected": the two never
  // hold together, and neither does a favourites-only view of rejects.
  if (updates.show_rejected) {
    patch.hide_rejected = false;
    patch.favorites_only = false;
  }
  return patch;
}

/** The review-status rules every filter write applies: a review status and a semantic/similar
 *  query are mutually exclusive (the one just set wins), and entering "undecided" sorts oldest
 *  first so the queue reads in shooting order. Shared by `updateFilter`, `updateFilters` and
 *  `applyQueryParams`; the last passes `withSort = false` because a URL carries its own sort. */
export function reviewStatusPatch(updates: Partial<GalleryFilters>, withSort = true): Partial<GalleryFilters> {
  const patch: Partial<GalleryFilters> = {};
  // "Only rejected" releases every hide toggle server-side, and its checkbox is disabled while a
  // review status is set, so a stale one would flood the queue with set members nobody can hide.
  if (updates.review_status) { patch.similar_to = ''; patch.semanticQuery = ''; patch.show_rejected = false; }
  else if (updates.semanticQuery || updates.similar_to) patch.review_status = '';
  if (withSort && updates.review_status === 'undecided') { patch.sort = 'date_taken'; patch.sort_direction = 'ASC'; }
  return patch;
}

/** The filters that scope the gallery to one photo set, clearing any other set scope first (a
 *  photo can belong to a burst AND a duplicate group at once, and only one scope can be active)
 *  and releasing the hide toggle that would collapse the set's members. `sequenceKind` is the
 *  `(sequence_kind, sequence_group_id)` kind for bracket / panorama / hdr_panorama. */
export function setScopePatch(
  kind: 'burst' | 'duplicate' | 'sequence', groupId: string, sequenceKind = '',
): Partial<GalleryFilters> {
  const patch: Partial<GalleryFilters> = {
    sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
  };
  if (kind === 'burst') {
    patch.burst_group_id = groupId;
    patch.hide_bursts = false;
  } else if (kind === 'duplicate') {
    patch.duplicate_group_id = groupId;
    patch.hide_duplicates = false;
  } else {
    patch.sequence_kind = sequenceKind;
    patch.sequence_group_id = groupId;
    if (sequenceKind === 'bracket') patch.hide_brackets = false;
    else patch.hide_panoramas = false;
  }
  return patch;
}

/** Common string-typed filter keys shared across URL sync, API params, and filter counting. */
export const RANGE_AND_SELECT_KEYS: (keyof GalleryFilters)[] = [
  'type', 'camera', 'lens', 'tag', 'person_id', 'composition_pattern', 'search',
  'color_temp', 'hue_bucket', 'quality_tier', 'sequence_override', 'review_status',
  'min_score', 'max_score', 'min_aesthetic', 'max_aesthetic',
  'min_quality_score', 'max_quality_score', 'min_topiq', 'max_topiq',
  'min_face_quality', 'max_face_quality', 'min_composition', 'max_composition',
  'min_sharpness', 'max_sharpness', 'min_exposure', 'max_exposure',
  'min_color', 'max_color', 'min_contrast', 'max_contrast',
  'min_noise', 'max_noise', 'min_dynamic_range', 'max_dynamic_range',
  'min_saturation', 'max_saturation', 'min_luminance', 'max_luminance',
  'min_histogram_spread', 'max_histogram_spread',
  'min_channel_clip_shadow', 'max_channel_clip_shadow',
  'min_channel_clip_highlight', 'max_channel_clip_highlight',
  'min_power_point', 'max_power_point', 'min_leading_lines', 'max_leading_lines',
  'min_isolation', 'max_isolation',
  'min_aesthetic_iaa', 'max_aesthetic_iaa', 'min_face_quality_iqa', 'max_face_quality_iqa',
  'min_liqe', 'max_liqe',
  'min_qrealign', 'max_qrealign', 'min_aesthetic_v25', 'max_aesthetic_v25', 'min_deqa', 'max_deqa',
  'min_subject_sharpness', 'max_subject_sharpness', 'min_subject_prominence', 'max_subject_prominence',
  'min_subject_placement', 'max_subject_placement', 'min_bg_separation', 'max_bg_separation',
  'min_moment_confidence', 'max_moment_confidence',
  'min_face_count', 'max_face_count',
  'min_eye_sharpness', 'max_eye_sharpness', 'min_face_sharpness', 'max_face_sharpness',
  'min_face_ratio', 'max_face_ratio', 'min_face_confidence', 'max_face_confidence',
  'min_star_rating', 'max_star_rating',
  'min_iso', 'max_iso', 'min_aperture', 'max_aperture', 'min_focal_length', 'max_focal_length',
  'date_from', 'date_to',
  'path_prefix',
  'no_gps', 'gps_lat', 'gps_lng', 'gps_radius_km',
];

export const DEFAULT_FILTERS: GalleryFilters = {
  page: 1,
  per_page: 64,
  sort: 'aggregate',
  sort_direction: 'DESC',
  type: '',
  camera: '',
  lens: '',
  tag: '',
  person_id: '',
  min_score: '',
  max_score: '',
  min_aesthetic: '',
  max_aesthetic: '',
  min_face_quality: '',
  max_face_quality: '',
  min_composition: '',
  max_composition: '',
  min_sharpness: '',
  max_sharpness: '',
  min_exposure: '',
  max_exposure: '',
  min_color: '',
  max_color: '',
  min_contrast: '',
  max_contrast: '',
  min_noise: '',
  max_noise: '',
  min_dynamic_range: '',
  max_dynamic_range: '',
  min_face_count: '',
  max_face_count: '',
  min_eye_sharpness: '',
  max_eye_sharpness: '',
  min_face_sharpness: '',
  max_face_sharpness: '',
  min_face_ratio: '',
  max_face_ratio: '',
  min_face_confidence: '',
  max_face_confidence: '',
  min_quality_score: '',
  max_quality_score: '',
  min_topiq: '',
  max_topiq: '',
  min_power_point: '',
  max_power_point: '',
  min_leading_lines: '',
  max_leading_lines: '',
  min_isolation: '',
  max_isolation: '',
  min_aesthetic_iaa: '',
  max_aesthetic_iaa: '',
  min_face_quality_iqa: '',
  max_face_quality_iqa: '',
  min_liqe: '',
  max_liqe: '',
  min_qrealign: '',
  max_qrealign: '',
  min_aesthetic_v25: '',
  max_aesthetic_v25: '',
  min_deqa: '',
  max_deqa: '',
  min_subject_sharpness: '',
  max_subject_sharpness: '',
  min_subject_prominence: '',
  max_subject_prominence: '',
  min_subject_placement: '',
  max_subject_placement: '',
  min_bg_separation: '',
  max_bg_separation: '',
  min_moment_confidence: '',
  max_moment_confidence: '',
  min_saturation: '',
  max_saturation: '',
  min_luminance: '',
  max_luminance: '',
  min_histogram_spread: '',
  max_histogram_spread: '',
  min_channel_clip_shadow: '',
  max_channel_clip_shadow: '',
  min_channel_clip_highlight: '',
  max_channel_clip_highlight: '',
  min_star_rating: '',
  max_star_rating: '',
  min_iso: '',
  max_iso: '',
  min_aperture: '',
  max_aperture: '',
  min_focal_length: '',
  max_focal_length: '',
  date_from: '',
  date_to: '',
  composition_pattern: '',
  sequence_override: '',
  path_prefix: '',
  semanticQuery: '',
  search_threshold: '',
  album_id: '',
  no_gps: '',
  gps_lat: '',
  gps_lng: '',
  gps_radius_km: '',
  sequence_group_id: '',
  sequence_kind: '',
  burst_group_id: '',
  duplicate_group_id: '',
  similar_to: '',
  similarity_mode: 'visual',
  min_similarity: '70',
  hide_details: true,
  tooltip_mode: 'panel',
  panel_activation: 'both',
  hide_blinks: true,
  hide_bursts: true,
  hide_duplicates: true,
  hide_brackets: true,
  hide_panoramas: true,
  review_status: '',
  hide_rejected: true,
  favorites_only: false,
  show_rejected: false,
  blinks_only: false,
  duplicates_only: false,
  is_monochrome: false,
  manual_faces_need_review: false,
  faces_need_names: false,
  search: '',
  color_temp: '',
  hue_bucket: '',
  quality_tier: '',
};

export type DisplayOptions = Pick<GalleryFilters,
  'hide_details' | 'tooltip_mode' | 'panel_activation' | 'hide_blinks' | 'hide_bursts' | 'hide_duplicates' | 'hide_brackets' | 'hide_panoramas' |
  'hide_rejected' | 'favorites_only' | 'is_monochrome'>;

export const DISPLAY_OPTION_KEYS: (keyof DisplayOptions)[] = [
  'hide_details', 'tooltip_mode', 'panel_activation', 'hide_blinks', 'hide_bursts', 'hide_duplicates', 'hide_brackets', 'hide_panoramas',
  'hide_rejected', 'favorites_only', 'is_monochrome',
];

export function loadDisplayOptionsFromStorage(): Partial<DisplayOptions> {
  try {
    const raw = localStorage.getItem(DISPLAY_OPTIONS_KEY);
    if (raw) return JSON.parse(raw) as Partial<DisplayOptions>;
  } catch { /* ignore */ }
  return {};
}

export function saveDisplayOptionsToStorage(filters: GalleryFilters): void {
  try {
    const opts: Partial<DisplayOptions> = {};
    for (const key of DISPLAY_OPTION_KEYS) {
      (opts as Record<string, boolean>)[key] = filters[key] as boolean;
    }
    localStorage.setItem(DISPLAY_OPTIONS_KEY, JSON.stringify(opts));
  } catch { /* ignore */ }
}

/** The keys of the active (non-default) filters, in a stable order. */
export function activeFilterKeys(f: GalleryFilters): (keyof GalleryFilters)[] {
  const stringKeys: (keyof GalleryFilters)[] = [...RANGE_AND_SELECT_KEYS, 'similar_to', 'semanticQuery'];
  const flagKeys: (keyof GalleryFilters)[] = [
    'favorites_only', 'show_rejected', 'blinks_only', 'duplicates_only', 'is_monochrome',
    'manual_faces_need_review', 'faces_need_names',
  ];
  return [...stringKeys, ...flagKeys].filter(key => !!f[key]);
}

/**
 * The control a filter key belongs to: `min_x` and `max_x` are one range
 * slider (`x`), and the four geolocation keys are one location filter (`gps`).
 * Every other key is its own control.
 */
export function filterUnit(key: string): string {
  if (key.startsWith('min_') || key.startsWith('max_')) return key.slice(4);
  if (key === 'no_gps' || key.startsWith('gps_')) return 'gps';
  return key;
}

/** The distinct controls with an active filter, in `activeFilterKeys` order. */
export function activeFilterUnits(f: GalleryFilters): string[] {
  return [...new Set(activeFilterKeys(f).map(filterUnit))];
}

/** Count the number of active (non-default) filters for the badge: a range or the location counts once. */
export function countActiveFilters(f: GalleryFilters): number {
  return activeFilterUnits(f).length;
}

/** Apply URL query params over a base filter state. */
export function applyQueryParams(
  base: GalleryFilters,
  params: Record<string, string>,
): GalleryFilters {
  const result = { ...base };

  const stringKeys: (keyof GalleryFilters)[] = [
    ...RANGE_AND_SELECT_KEYS, 'sort', 'sort_direction', 'similar_to', 'min_similarity',
    'semanticQuery', 'album_id',
  ];
  for (const key of stringKeys) {
    if (params[key]) (result as Record<string, unknown>)[key] = params[key];
  }
  if (!['', 'undecided', 'kept', 'rejected'].includes(result.review_status)) result.review_status = '';
  if (result.review_status) Object.assign(result, reviewStatusPatch(result, false));
  result.no_gps = ['1', 'true'].includes(result.no_gps) ? '1' : '';
  if (result.no_gps) {
    result.gps_lat = ''; result.gps_lng = ''; result.gps_radius_km = '';
    result.similar_to = ''; result.semanticQuery = '';
  }
  // no_gps cleared the query above, so the sort below is judged on the surviving one.
  // Relevance is the implied sort of a semantic query, and meaningless without one.
  if (result.semanticQuery && !params['sort']) {
    result.sort = RELEVANCE_SORT;
    if (!params['sort_direction']) result.sort_direction = 'DESC';
  } else if (!result.semanticQuery && result.sort === RELEVANCE_SORT) {
    result.sort = base.sort === RELEVANCE_SORT ? 'aggregate' : base.sort;
    result.sort_direction = base.sort === RELEVANCE_SORT ? 'DESC' : base.sort_direction;
  }
  // Parsed rather than copied: this one is sent to the API as a NUMBER
  // (`+value / 100`), so a mangled shared link carrying `search_threshold=abc`
  // became `threshold=NaN`, which the server rejects with a 422 the gallery
  // surfaces only as a bare load error. Out-of-range is clamped to the
  // slider's own span so a seeded value is always reachable from the thumb.
  if (params['search_threshold']) {
    const parsed = Number(params['search_threshold']);
    result.search_threshold = Number.isFinite(parsed)
      ? String(Math.min(SEARCH_THRESHOLD_MAX, Math.max(0, Math.round(parsed))))
      : '';
  }
  if (params['similarity_mode'] && ['visual', 'color', 'person'].includes(params['similarity_mode'])) {
    result.similarity_mode = params['similarity_mode'] as GalleryFilters['similarity_mode'];
  }

  if (params['hide_details'] !== undefined) result.hide_details = params['hide_details'] !== 'false';
  if (params['hide_blinks'] !== undefined) result.hide_blinks = params['hide_blinks'] !== 'false';
  if (params['hide_bursts'] !== undefined) result.hide_bursts = params['hide_bursts'] !== 'false';
  if (params['hide_duplicates'] !== undefined)
    result.hide_duplicates = params['hide_duplicates'] !== 'false';
  if (params['hide_brackets'] !== undefined)
    result.hide_brackets = params['hide_brackets'] !== 'false';
  if (params['hide_panoramas'] !== undefined)
    result.hide_panoramas = params['hide_panoramas'] !== 'false';
  if (params['hide_rejected'] !== undefined) result.hide_rejected = params['hide_rejected'] !== 'false';
  if (params['favorites_only'] !== undefined) result.favorites_only = params['favorites_only'] === 'true';
  if (params['show_rejected'] !== undefined) result.show_rejected = params['show_rejected'] === 'true';
  if (result.review_status) result.show_rejected = false; // the URL's flag lands after reviewStatusPatch above
  if (params['blinks_only'] !== undefined) result.blinks_only = params['blinks_only'] === 'true';
  if (params['duplicates_only'] !== undefined) result.duplicates_only = params['duplicates_only'] === 'true';
  if (params['is_monochrome'] !== undefined) result.is_monochrome = params['is_monochrome'] === 'true';
  if (params['manual_faces_need_review'] !== undefined) result.manual_faces_need_review = params['manual_faces_need_review'] === 'true';
  if (params['faces_need_names'] !== undefined) result.faces_need_names = params['faces_need_names'] === 'true';
  if (params['tooltip_mode'] && TOOLTIP_MODES.includes(params['tooltip_mode'] as TooltipMode)) {
    result.tooltip_mode = params['tooltip_mode'] as TooltipMode;
  }
  if (params['panel_activation'] && PANEL_ACTIVATIONS.includes(params['panel_activation'] as PanelActivation)) {
    result.panel_activation = params['panel_activation'] as PanelActivation;
  }
  if (params['page']) result.page = parseInt(params['page'], 10) || 1;
  return result;
}

/** Build the query-param map for URL sync — only values that differ from defaults, plus the sort, which is always written. */
export function buildSyncParams(
  f: GalleryFilters,
  defaults: FilterDefaults | undefined,
  searchThresholdDefault?: number | null,
): Record<string, string> {
  const params: Record<string, string> = {};
  // A semantic query implies Relevance (DESC), so that is the only sort left unwritten. Every other
  // sort is written even when it equals the viewer default: a URL without one falls back to the
  // browser's remembered sort (see GalleryStore.loadConfig), so an unwritten default would reopen a
  // link, bookmark or reload on whatever sort the opening browser last picked.
  const impliedDirection = f.semanticQuery ? 'DESC' : (defaults?.sort_direction ?? 'DESC');
  if (!(f.semanticQuery && f.sort === RELEVANCE_SORT)) params['sort'] = f.sort;
  if (f.sort_direction !== impliedDirection)
    params['sort_direction'] = f.sort_direction;

  const stringKeys: (keyof GalleryFilters)[] = [...RANGE_AND_SELECT_KEYS, 'similar_to', 'album_id', 'semanticQuery'];
  for (const key of stringKeys) {
    if (f[key]) params[key] = String(f[key]);
  }
  if (f.similar_to && f.min_similarity) params['min_similarity'] = f.min_similarity;
  if (f.similar_to && f.similarity_mode && f.similarity_mode !== 'visual') params['similarity_mode'] = f.similarity_mode;
  // Only when the user moved the slider off the server's own seed -- the same
  // "only values that differ from the default" contract every other key here
  // follows. Emitting the seeded value froze it into every shared link, so a
  // later server-side recalibration could never reach an existing bookmark.
  if (f.semanticQuery && f.search_threshold
    && f.search_threshold !== seededSearchThreshold(searchThresholdDefault))
    params['search_threshold'] = f.search_threshold;

  if (f.hide_details !== (defaults?.hide_details ?? true))
    params['hide_details'] = String(f.hide_details);
  if (f.hide_blinks !== (defaults?.hide_blinks ?? true))
    params['hide_blinks'] = String(f.hide_blinks);
  if (f.hide_bursts !== (defaults?.hide_bursts ?? true))
    params['hide_bursts'] = String(f.hide_bursts);
  if (f.hide_duplicates !== (defaults?.hide_duplicates ?? true))
    params['hide_duplicates'] = String(f.hide_duplicates);
  if (f.hide_brackets !== (defaults?.hide_brackets ?? true))
    params['hide_brackets'] = String(f.hide_brackets);
  if (f.hide_panoramas !== (defaults?.hide_panoramas ?? true))
    params['hide_panoramas'] = String(f.hide_panoramas);
  if (f.hide_rejected !== (defaults?.hide_rejected ?? true))
    params['hide_rejected'] = String(f.hide_rejected);
  if (f.tooltip_mode !== (defaults?.tooltip_mode ?? 'panel'))
    params['tooltip_mode'] = f.tooltip_mode;
  if (f.panel_activation !== (defaults?.panel_activation ?? 'both'))
    params['panel_activation'] = f.panel_activation;
  if (f.favorites_only) params['favorites_only'] = 'true';
  if (f.show_rejected) params['show_rejected'] = 'true';
  if (f.blinks_only) params['blinks_only'] = 'true';
  if (f.duplicates_only) params['duplicates_only'] = 'true';
  if (f.is_monochrome) params['is_monochrome'] = 'true';
  if (f.manual_faces_need_review) params['manual_faces_need_review'] = 'true';
  if (f.faces_need_names) params['faces_need_names'] = 'true';

  return params;
}

/** Build API params from filters, omitting empty values. */
export function buildApiParams(
  f: GalleryFilters,
  isSmartAlbum: boolean,
  searchThresholdDefault: number | null | undefined,
): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {
    page: f.page,
    per_page: f.per_page,
    sort: f.sort,
    sort_direction: f.sort_direction,
  };

  const stringKeys: (keyof GalleryFilters)[] = [
    ...RANGE_AND_SELECT_KEYS, 'album_id',
    'sequence_group_id', 'sequence_kind', 'burst_group_id', 'duplicate_group_id',
  ];
  for (const key of stringKeys) {
    if (f[key]) params[key] = String(f[key]);
  }

  if (f.hide_blinks) params['hide_blinks'] = true;
  if (f.hide_bursts) params['hide_bursts'] = true;
  if (f.hide_duplicates) params['hide_duplicates'] = true;
  if (f.hide_brackets) params['hide_brackets'] = true;
  if (f.hide_panoramas) params['hide_panoramas'] = true;
  if (f.hide_rejected && !f.review_status) params['hide_rejected'] = true;
  if (f.favorites_only) params['favorites_only'] = '1';
  if (f.show_rejected) params['show_rejected'] = '1';
  if (f.blinks_only) params['blinks_only'] = '1';
  if (f.duplicates_only) params['duplicates_only'] = '1';
  if (f.is_monochrome) params['is_monochrome'] = '1';
  if (f.manual_faces_need_review) params['manual_faces_need_review'] = '1';
  if (f.faces_need_names) params['faces_need_names'] = '1';

  // Semantic search is a filter of `GET /photos`. The threshold travels only when
  // the slider left the server's seed, so the server resolves its own calibrated
  // default; the seed is a required argument so `filterKey` sees a slider-only move.
  if (f.semanticQuery) {
    params['semantic_q'] = f.semanticQuery;
    if (f.search_threshold && f.search_threshold !== seededSearchThreshold(searchThresholdDefault))
      params['semantic_threshold'] = +f.search_threshold / 100;
  }

  // Smart albums apply their filters directly — don't send album_id
  // (server would do an empty album_photos JOIN otherwise).
  if (isSmartAlbum) {
    delete params['album_id'];
  }

  return params;
}

/** Largest `paths` list `POST /photos/by_paths` accepts (server `BY_PATHS_MAX`). */
export const BY_PATHS_MAX = 500;

/** Paging, ordering and semantic-search keys of `buildApiParams`: meaningless (and a 422 on `by_paths`) when the caller names the rows itself. */
export const BY_PATHS_PAGING_KEYS: ReadonlySet<string> = new Set([
  'page', 'per_page', 'sort', 'sort_direction', 'semantic_q', 'semantic_threshold',
]);

/**
 * The `filters` member of a `POST /photos/by_paths` body for the gallery view: everything
 * `buildApiParams` sends except paging and sort, so a photo that no longer matches (rejected under
 * `hide_rejected`, out of the album or score range) comes back missing exactly as a reload would
 * drop it. `type` is sent explicitly because the endpoint defaults it to '' while `GET /photos`
 * resolves the viewer's default (and '' for a person view).
 */
export function buildByPathsFilters(
  f: GalleryFilters,
  isSmartAlbum: boolean,
  defaultType: string,
  searchThresholdDefault: number | null | undefined,
): Record<string, string | number | boolean> {
  const filters: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(buildApiParams(f, isSmartAlbum, searchThresholdDefault))) {
    if (!BY_PATHS_PAGING_KEYS.has(key)) filters[key] = value;
  }
  filters['type'] = f.type || (f.person_id ? '' : defaultType);
  return filters;
}

/** Wire projection of the five hide toggles as explicit '1'/'0' strings.
 *  Views fetched independently of the gallery grid (timeline, folders, type
 *  counts) must send the gallery's EFFECTIVE toggle state rather than omitting
 *  false ones for the server to resolve from `viewer.defaults` — the moment a
 *  user has ever toggled anything, localStorage/URL overlays can diverge from
 *  that config default (see gallery.store.ts loadConfig()). */
export interface ViewFilterParams {
  hide_blinks: string;
  hide_bursts: string;
  hide_duplicates: string;
  hide_brackets: string;
  hide_panoramas: string;
}

export function buildViewFilterParams(f: GalleryFilters): ViewFilterParams {
  return {
    hide_blinks: f.hide_blinks ? '1' : '0',
    hide_bursts: f.hide_bursts ? '1' : '0',
    hide_duplicates: f.hide_duplicates ? '1' : '0',
    hide_brackets: f.hide_brackets ? '1' : '0',
    hide_panoramas: f.hide_panoramas ? '1' : '0',
  };
}

/** Shallow comparator for `viewFilterParams` so unrelated filter churn (camera,
 *  page, sort…) doesn't re-fire every consumer's effect on every keystroke. */
export function viewFilterParamsEqual(a: ViewFilterParams, b: ViewFilterParams): boolean {
  return a.hide_blinks === b.hide_blinks
    && a.hide_bursts === b.hide_bursts
    && a.hide_duplicates === b.hide_duplicates
    && a.hide_brackets === b.hide_brackets
    && a.hide_panoramas === b.hide_panoramas;
}

/** True when at least one of the five hide toggles is on — a bucket/day whose
 *  photos are ALL hidden by such a toggle can render a count of 0, which
 *  timeline-days.component.ts then makes unreachable. Shared by the desktop
 *  and mobile timeline banners so the "photos may be hidden" predicate lives
 *  in exactly one place. */
export function anyHideToggleActive(p: ViewFilterParams): boolean {
  return p.hide_blinks === '1' || p.hide_bursts === '1' || p.hide_duplicates === '1'
    || p.hide_brackets === '1' || p.hide_panoramas === '1';
}
