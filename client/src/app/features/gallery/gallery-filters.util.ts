/**
 * Pure filter logic for the gallery: types, defaults, and the URL/API/storage
 * codec. Extracted from gallery.store.ts so it can be unit-tested in isolation
 * and reused. Nothing here touches Angular signals, the router, or HTTP — the
 * store owns that and calls these functions.
 */

export type GalleryMode = 'grid' | 'mosaic';
export type TooltipMode = 'hover' | 'click' | 'off';

export const GALLERY_MODE_KEY = 'facet_gallery_mode';
export const DRAWER_STATE_KEY = 'facet_filter_drawer_open';
export const DISPLAY_OPTIONS_KEY = 'facet_display_options';
export const CARD_WIDTH_KEY = 'facet_card_width';

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
  min_qalign: string;
  max_qalign: string;
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
  // Similar-to filter
  similar_to: string;
  similarity_mode: 'visual' | 'color' | 'person';
  min_similarity: string;
  // Semantic search
  semanticQuery: string;
  // Album filter
  album_id: string;
  // Folder filter
  path_prefix: string;
  // GPS filter
  gps_lat: string;
  gps_lng: string;
  gps_radius_km: string;
  // Display
  hide_details: boolean;
  tooltip_mode: TooltipMode;
  hide_blinks: boolean;
  hide_bursts: boolean;
  hide_duplicates: boolean;
  hide_rejected: boolean;
  favorites_only: boolean;
  is_monochrome: boolean;
  search: string;
  // Color facet (opt-in extraction; always-on filter)
  color_temp: string;   // warm | cool | neutral
  hue_bucket: string;   // red | orange | yellow | green | cyan | blue | purple | magenta
  // Quality tier (on the fly from aggregate thresholds)
  quality_tier: string; // excellent | good | fair | poor
}

/** Subset of viewer config defaults the URL/sync codec compares against. */
export interface FilterDefaults {
  sort?: string;
  sort_direction?: string;
  hide_details?: boolean;
  hide_blinks?: boolean;
  hide_bursts?: boolean;
  hide_duplicates?: boolean;
  hide_rejected?: boolean;
  tooltip_mode?: TooltipMode;
}

/** Keys excluded when building smart album filter JSON (display-only, ephemeral, or handled separately). */
export const SMART_ALBUM_EXCLUDE_KEYS = new Set([
  'page', 'per_page', 'semanticQuery', 'album_id',
  'similarity_mode', 'min_similarity',
  'hide_details', 'tooltip_mode', 'hide_blinks', 'hide_bursts',
  'hide_duplicates', 'hide_rejected',
  'gps_lat', 'gps_lng', 'gps_radius_km',
]);

/** Common string-typed filter keys shared across URL sync, API params, and filter counting. */
export const RANGE_AND_SELECT_KEYS: (keyof GalleryFilters)[] = [
  'type', 'camera', 'lens', 'tag', 'person_id', 'composition_pattern', 'search',
  'color_temp', 'hue_bucket', 'quality_tier',
  'min_score', 'max_score', 'min_aesthetic', 'max_aesthetic',
  'min_quality_score', 'max_quality_score', 'min_topiq', 'max_topiq',
  'min_face_quality', 'max_face_quality', 'min_composition', 'max_composition',
  'min_sharpness', 'max_sharpness', 'min_exposure', 'max_exposure',
  'min_color', 'max_color', 'min_contrast', 'max_contrast',
  'min_noise', 'max_noise', 'min_dynamic_range', 'max_dynamic_range',
  'min_saturation', 'max_saturation', 'min_luminance', 'max_luminance',
  'min_histogram_spread', 'max_histogram_spread',
  'min_power_point', 'max_power_point', 'min_leading_lines', 'max_leading_lines',
  'min_isolation', 'max_isolation',
  'min_aesthetic_iaa', 'max_aesthetic_iaa', 'min_face_quality_iqa', 'max_face_quality_iqa',
  'min_liqe', 'max_liqe',
  'min_qalign', 'max_qalign', 'min_aesthetic_v25', 'max_aesthetic_v25', 'min_deqa', 'max_deqa',
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
  'gps_lat', 'gps_lng', 'gps_radius_km',
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
  min_qalign: '',
  max_qalign: '',
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
  path_prefix: '',
  semanticQuery: '',
  album_id: '',
  gps_lat: '',
  gps_lng: '',
  gps_radius_km: '',
  similar_to: '',
  similarity_mode: 'visual',
  min_similarity: '70',
  hide_details: true,
  tooltip_mode: 'hover',
  hide_blinks: true,
  hide_bursts: true,
  hide_duplicates: true,
  hide_rejected: true,
  favorites_only: false,
  is_monochrome: false,
  search: '',
  color_temp: '',
  hue_bucket: '',
  quality_tier: '',
};

export type DisplayOptions = Pick<GalleryFilters,
  'hide_details' | 'tooltip_mode' | 'hide_blinks' | 'hide_bursts' | 'hide_duplicates' |
  'hide_rejected' | 'favorites_only' | 'is_monochrome'>;

export const DISPLAY_OPTION_KEYS: (keyof DisplayOptions)[] = [
  'hide_details', 'tooltip_mode', 'hide_blinks', 'hide_bursts', 'hide_duplicates',
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

/** Count the number of active (non-default) filters for the badge. */
export function countActiveFilters(f: GalleryFilters): number {
  let count = 0;
  const stringKeys: (keyof GalleryFilters)[] = [...RANGE_AND_SELECT_KEYS, 'similar_to', 'semanticQuery'];
  for (const key of stringKeys) {
    if (f[key]) count++;
  }
  if (f.favorites_only) count++;
  if (f.is_monochrome) count++;
  return count;
}

/** Apply URL query params over a base filter state. */
export function applyQueryParams(
  base: GalleryFilters,
  params: Record<string, string>,
): GalleryFilters {
  const result = { ...base };

  const stringKeys: (keyof GalleryFilters)[] = [
    ...RANGE_AND_SELECT_KEYS, 'sort', 'sort_direction', 'similar_to', 'min_similarity', 'semanticQuery', 'album_id',
  ];
  for (const key of stringKeys) {
    if (params[key]) (result as Record<string, unknown>)[key] = params[key];
  }
  if (params['similarity_mode'] && ['visual', 'color', 'person'].includes(params['similarity_mode'])) {
    result.similarity_mode = params['similarity_mode'] as GalleryFilters['similarity_mode'];
  }

  if (params['hide_details'] !== undefined) result.hide_details = params['hide_details'] !== 'false';
  if (params['hide_blinks'] !== undefined) result.hide_blinks = params['hide_blinks'] !== 'false';
  if (params['hide_bursts'] !== undefined) result.hide_bursts = params['hide_bursts'] !== 'false';
  if (params['hide_duplicates'] !== undefined)
    result.hide_duplicates = params['hide_duplicates'] !== 'false';
  if (params['hide_rejected'] !== undefined) result.hide_rejected = params['hide_rejected'] !== 'false';
  if (params['favorites_only'] !== undefined) result.favorites_only = params['favorites_only'] === 'true';
  if (params['is_monochrome'] !== undefined) result.is_monochrome = params['is_monochrome'] === 'true';
  if (params['tooltip_mode'] && ['hover', 'click', 'off'].includes(params['tooltip_mode'])) {
    result.tooltip_mode = params['tooltip_mode'] as TooltipMode;
  }
  if (params['page']) result.page = parseInt(params['page'], 10) || 1;

  return result;
}

/** Build the query-param map for URL sync — only values that differ from defaults. */
export function buildSyncParams(
  f: GalleryFilters,
  defaults: FilterDefaults | undefined,
): Record<string, string> {
  const params: Record<string, string> = {};
  if (f.sort !== (defaults?.sort ?? 'aggregate')) params['sort'] = f.sort;
  if (f.sort_direction !== (defaults?.sort_direction ?? 'DESC'))
    params['sort_direction'] = f.sort_direction;

  const stringKeys: (keyof GalleryFilters)[] = [...RANGE_AND_SELECT_KEYS, 'similar_to', 'album_id', 'semanticQuery'];
  for (const key of stringKeys) {
    if (f[key]) params[key] = String(f[key]);
  }
  if (f.similar_to && f.min_similarity) params['min_similarity'] = f.min_similarity;
  if (f.similar_to && f.similarity_mode && f.similarity_mode !== 'visual') params['similarity_mode'] = f.similarity_mode;

  if (f.hide_details !== (defaults?.hide_details ?? true))
    params['hide_details'] = String(f.hide_details);
  if (f.hide_blinks !== (defaults?.hide_blinks ?? true))
    params['hide_blinks'] = String(f.hide_blinks);
  if (f.hide_bursts !== (defaults?.hide_bursts ?? true))
    params['hide_bursts'] = String(f.hide_bursts);
  if (f.hide_duplicates !== (defaults?.hide_duplicates ?? true))
    params['hide_duplicates'] = String(f.hide_duplicates);
  if (f.hide_rejected !== (defaults?.hide_rejected ?? true))
    params['hide_rejected'] = String(f.hide_rejected);
  if (f.tooltip_mode !== (defaults?.tooltip_mode ?? 'hover'))
    params['tooltip_mode'] = f.tooltip_mode;
  if (f.favorites_only) params['favorites_only'] = 'true';
  if (f.is_monochrome) params['is_monochrome'] = 'true';

  return params;
}

/** Build API params from filters, omitting empty values. */
export function buildApiParams(
  f: GalleryFilters,
  isSmartAlbum: boolean,
): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {
    page: f.page,
    per_page: f.per_page,
    sort: f.sort,
    sort_direction: f.sort_direction,
  };

  const stringKeys: (keyof GalleryFilters)[] = [...RANGE_AND_SELECT_KEYS, 'album_id'];
  for (const key of stringKeys) {
    if (f[key]) params[key] = String(f[key]);
  }

  if (f.hide_blinks) params['hide_blinks'] = true;
  if (f.hide_bursts) params['hide_bursts'] = true;
  if (f.hide_duplicates) params['hide_duplicates'] = true;
  if (f.hide_rejected) params['hide_rejected'] = true;
  if (f.favorites_only) params['favorites_only'] = '1';
  if (f.is_monochrome) params['is_monochrome'] = '1';

  // Smart albums apply their filters directly — don't send album_id
  // (server would do an empty album_photos JOIN otherwise).
  if (isSmartAlbum) {
    delete params['album_id'];
  }

  return params;
}
