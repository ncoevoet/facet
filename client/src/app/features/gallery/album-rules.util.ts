import { DEFAULT_FILTERS, GalleryFilters, SMART_ALBUM_EXCLUDE_KEYS, exclusiveHidePatch, reviewStatusPatch, smartAlbumFilterJson } from './gallery-filters.util';

export interface AlbumRuleRow { key: string; saved: string; working: string; changed: boolean; }

/** Reset only the fields the existing smart-album serializer can persist. */
export function restoreAlbumRuleFields(current: GalleryFilters, savedJson: string, sort = DEFAULT_FILTERS.sort, direction = DEFAULT_FILTERS.sort_direction, type = DEFAULT_FILTERS.type): GalleryFilters {
  const saved: unknown = JSON.parse(savedJson);
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) throw new Error('Invalid album rules');
  const result = { ...current } as unknown as Record<string, unknown>;
  const restored: Record<string, unknown> = {};
  const defaults = { ...DEFAULT_FILTERS, sort, sort_direction: direction, type };
  for (const [key, value] of Object.entries(saved)) {
    if (!(key in defaults) || typeof value !== typeof defaults[key as keyof GalleryFilters]) throw new Error('Unsupported album rule');
  }
  for (const [key, value] of Object.entries(defaults)) {
    if (!SMART_ALBUM_EXCLUDE_KEYS.has(key)) result[key] = restored[key] = (saved as Record<string, unknown>)[key] ?? value;
  }
  return { ...result, ...exclusiveHidePatch(restored), ...reviewStatusPatch(restored, false) } as unknown as GalleryFilters;
}

export function albumRuleRows(saved: GalleryFilters, working: GalleryFilters): AlbumRuleRow[] {
  const before = JSON.parse(smartAlbumFilterJson(saved)) as Record<string, unknown>;
  const after = JSON.parse(smartAlbumFilterJson(working)) as Record<string, unknown>;
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].sort().map(key => ({
    key,
    saved: before[key] === undefined ? '' : String(before[key]), working: after[key] === undefined ? '' : String(after[key]),
    changed: before[key] !== after[key],
  }));
}

/** These transient modes cannot be represented by the existing saved-rule contract. */
export function hasUnsavableAlbumMode(filters: GalleryFilters, pinned: boolean): boolean {
  return pinned || !!(filters.semanticQuery || filters.similar_to || filters.gps_lat || filters.gps_lng || filters.gps_radius_km
    || filters.sequence_group_id || filters.sequence_kind || filters.burst_group_id || filters.duplicate_group_id);
}
