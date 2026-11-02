import { inject, Pipe, PipeTransform } from '@angular/core';
import { i18nKeys } from '../../core/i18n/keys';
import { I18nService } from '../../core/services/i18n.service';
import { ADDITIONAL_FILTERS } from './gallery-metric-filters';

/** Shared by saved rules and proposed queries; values never pass through this resolver. */
export function galleryFilterLabel(key: string, translate: (key: string) => string): string {
  const I18N = i18nKeys();
  const metric = ADDITIONAL_FILTERS.find(row => row.minKey === key || row.maxKey === key);
  if (metric) {
    const unit = (metric.displaySuffix ?? metric.displayPrefix ?? '').trim();
    return `${translate(metric.labelKey)}${unit ? ' (' + unit + ')' : ''} ${key === metric.minKey ? '≥' : '≤'}`;
  }
  // TOPIQ remains accepted by the saved/API filter contract, though absent from the sidebar registry.
  if (key === 'min_topiq' || key === 'max_topiq') return `${translate(I18N.gallery.topiq_range)} ${key === 'min_topiq' ? '≥' : '≤'}`;
  const labels: Record<string, string> = {
    sort: I18N.gallery.sort, sort_direction: I18N.ui.sort.toggle_direction,
    type: I18N.ui.filters.type, category: I18N.tooltip.category,
    camera: I18N.gallery.camera, lens: I18N.gallery.lens, tag: I18N.gallery.tag,
    tag_groups: I18N.gallery.tag_groups.title, keyword_branch: I18N.keyword_hierarchy.title,
    score_presence: I18N.gallery.measurements.title,
    person_id: I18N.gallery.person, person: I18N.gallery.person, person_match: I18N.gallery.people_match.title,
    date_from: I18N.gallery.date_from, date_to: I18N.gallery.date_to, no_capture_date: I18N.gallery.no_capture_date,
    composition_pattern: I18N.gallery.composition_pattern, sequence_override: I18N.gallery.sequence_override.label,
    path_prefix: I18N.folders.title, no_gps: I18N.gallery.no_geolocation,
    review_status: I18N.gallery.sidebar.review.decision, favorites_only: I18N.gallery.favorites_only,
    show_rejected: I18N.gallery.sidebar.review.values.only_rejected,
    blinks_only: I18N.gallery.sidebar.review.desc.blinks_only,
    duplicates_only: I18N.gallery.sidebar.review.desc.duplicates_only,
    is_monochrome: I18N.gallery.monochrome_only, manual_faces_need_review: I18N.gallery.manual_faces_need_review,
    faces_need_names: I18N.gallery.faces_need_names, search: I18N.gallery.search_chip,
    color_temp: I18N.gallery.color_temp, hue_bucket: I18N.gallery.hue, quality_tier: I18N.gallery.quality_tier,
    album_id: I18N.albums.title,
    sequence_group_id: I18N.gallery.sidebar.review.sets, sequence_kind: I18N.ui.filters.type,
    burst_group_id: I18N.culling.burst_groups, duplicate_group_id: I18N.gallery.sidebar.review.duplicates,
    semanticQuery: I18N.gallery.semantic_search, semantic_query: I18N.gallery.semantic_search,
    search_threshold: I18N.gallery.semantic_search_threshold, semantic_threshold: I18N.gallery.semantic_search_threshold,
    similar_to: I18N.similar.title, similarity_mode: I18N.similar.similarity, min_similarity: I18N.gallery.criteria.similarity,
    gps_lat: I18N.photo_detail.gps.latitude, gps_lng: I18N.photo_detail.gps.longitude, gps_radius_km: I18N.gallery.gps_radius,
    hide_blinks: I18N.gallery.hide_blinks, hide_bursts: I18N.gallery.hide_bursts, hide_duplicates: I18N.gallery.hide_duplicates,
    hide_brackets: I18N.gallery.sidebar.refine_help.hide_brackets, hide_panoramas: I18N.gallery.sidebar.refine_help.hide_panoramas,
    hide_rejected: I18N.rating.hide_rejected,
  };
  return labels[key] ? translate(labels[key]) : key;
}

// Resolve at render time, including captured previews, when the translation signal changes.
@Pipe({ name: 'galleryFilterLabel', pure: false })
export class GalleryFilterLabelPipe implements PipeTransform {
  private readonly i18n = inject(I18nService);
  transform(key: string): string {
    return galleryFilterLabel(key, value => this.i18n.t(value));
  }
}
