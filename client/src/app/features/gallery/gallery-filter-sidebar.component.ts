import { Component, computed, DestroyRef, effect, ElementRef, inject, signal, viewChild, viewChildren, ChangeDetectionStrategy } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatSelectModule, MatSelect } from '@angular/material/select';
import { MatSliderModule } from '@angular/material/slider';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatInputModule } from '@angular/material/input';
import { MatTooltip, MatTooltipModule } from '@angular/material/tooltip';
import { HelpTooltipDirective } from '../../shared/directives/help-tooltip.directive';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTabsModule } from '@angular/material/tabs';
import { MatMenuModule, MatMenuTrigger } from '@angular/material/menu';
import { MatRippleModule } from '@angular/material/core';
import { MatDatepickerModule, MatDatepickerInputEvent } from '@angular/material/datepicker';
import { toIsoDateString } from '../../shared/utils/date-format';
import { MatAutocompleteModule, MatAutocompleteSelectedEvent } from '@angular/material/autocomplete';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { GalleryStore } from './gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FilterDisplayPipe } from '../../shared/pipes/filter-display.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { AdditionalFilterDef } from '../../shared/models/filter-def.model';
import { computeRangeFilterUpdate } from '../../shared/utils/range-filter';
import { useCoarsePointerSignal } from '../../shared/utils/media-query';
import { MOBILE_MIN_CARD_WIDTH_PX } from './gallery-rows.util';
import { GalleryFilters, SEARCH_THRESHOLD_MAX, activeFilterUnits, countActiveFilters, filterUnit, seededSearchThreshold, smartAlbumFilterJson } from './gallery-filters.util';
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { SaveSmartAlbumDialogComponent } from '../albums/save-smart-album-dialog.component';
import { CardActionsDialogComponent } from './card-actions-dialog.component';
import { folderDisplayName } from '../folders/folders.util';
import { i18nKeys } from '../../core/i18n/keys';
import { isUnavailableKey, unavailableSet } from '../../shared/utils/unavailable-metrics';
import { closeOverlayDirectives } from '../../shared/utils/overlays';
import { MetricSparklineComponent } from '../../shared/components/metric-sparkline/metric-sparkline.component';

export const ADDITIONAL_FILTERS: AdditionalFilterDef[] = [
  // Quality
  { id: 'score_range', labelKey: 'gallery.score_range', helpKey: 'gallery.sidebar.metric_help.score_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_score', maxKey: 'max_score', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'aesthetic_range', labelKey: 'gallery.aesthetic_range', helpKey: 'gallery.sidebar.metric_help.aesthetic_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_aesthetic', maxKey: 'max_aesthetic', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'quality_score_range', labelKey: 'gallery.quality_score_range', helpKey: 'gallery.sidebar.metric_help.quality_score_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_quality_score', maxKey: 'max_quality_score', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  // Extended Quality
  { id: 'aesthetic_iaa_range', labelKey: 'gallery.aesthetic_iaa_range', helpKey: 'gallery.sidebar.metric_help.aesthetic_iaa_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_aesthetic_iaa', maxKey: 'max_aesthetic_iaa', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'face_quality_iqa_range', labelKey: 'gallery.face_quality_iqa_range', helpKey: 'gallery.sidebar.metric_help.face_quality_iqa_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_face_quality_iqa', maxKey: 'max_face_quality_iqa', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'liqe_range', labelKey: 'gallery.liqe_range', helpKey: 'gallery.sidebar.metric_help.liqe_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_liqe', maxKey: 'max_liqe', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'qrealign_range', labelKey: 'gallery.qrealign_range', helpKey: 'gallery.sidebar.metric_help.qrealign_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_qrealign', maxKey: 'max_qrealign', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'aesthetic_v25_range', labelKey: 'gallery.aesthetic_v25_range', helpKey: 'gallery.sidebar.metric_help.aesthetic_v25_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_aesthetic_v25', maxKey: 'max_aesthetic_v25', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'deqa_range', labelKey: 'gallery.deqa_range', helpKey: 'gallery.sidebar.metric_help.deqa_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_deqa', maxKey: 'max_deqa', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  // Face Metrics
  { id: 'face_count_range', labelKey: 'gallery.face_count_range', helpKey: 'gallery.sidebar.metric_help.face_count_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_count', maxKey: 'max_face_count', sliderMin: 0, sliderMax: 20, step: 1, spanWidth: 'w-16' },
  { id: 'face_quality_range', labelKey: 'gallery.face_quality_range', helpKey: 'gallery.sidebar.metric_help.face_quality_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_quality', maxKey: 'max_face_quality', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'eye_sharpness_range', labelKey: 'gallery.eye_sharpness_range', helpKey: 'gallery.sidebar.metric_help.eye_sharpness_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_eye_sharpness', maxKey: 'max_eye_sharpness', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'face_sharpness_range', labelKey: 'gallery.face_sharpness_range', helpKey: 'gallery.sidebar.metric_help.face_sharpness_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_sharpness', maxKey: 'max_face_sharpness', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'face_ratio_range', labelKey: 'gallery.face_ratio_range', helpKey: 'gallery.sidebar.metric_help.face_ratio_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_ratio', maxKey: 'max_face_ratio', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  { id: 'face_confidence_range', labelKey: 'gallery.face_confidence_range', helpKey: 'gallery.sidebar.metric_help.face_confidence_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_confidence', maxKey: 'max_face_confidence', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  // Composition
  { id: 'composition_range', labelKey: 'gallery.composition_range', helpKey: 'gallery.sidebar.metric_help.composition_range', sectionKey: 'gallery.sidebar.composition', minKey: 'min_composition', maxKey: 'max_composition', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'power_point_range', labelKey: 'gallery.power_point_range', helpKey: 'gallery.sidebar.metric_help.power_point_range', sectionKey: 'gallery.sidebar.composition', minKey: 'min_power_point', maxKey: 'max_power_point', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'leading_lines_range', labelKey: 'gallery.leading_lines_range', helpKey: 'gallery.sidebar.metric_help.leading_lines_range', sectionKey: 'gallery.sidebar.composition', minKey: 'min_leading_lines', maxKey: 'max_leading_lines', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'isolation_range', labelKey: 'gallery.isolation_range', helpKey: 'gallery.sidebar.metric_help.isolation_range', sectionKey: 'gallery.sidebar.composition', minKey: 'min_isolation', maxKey: 'max_isolation', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  // Subject Saliency
  { id: 'subject_sharpness_range', labelKey: 'gallery.subject_sharpness_range', helpKey: 'gallery.sidebar.metric_help.subject_sharpness_range', sectionKey: 'gallery.sidebar.saliency', minKey: 'min_subject_sharpness', maxKey: 'max_subject_sharpness', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'subject_prominence_range', labelKey: 'gallery.subject_prominence_range', helpKey: 'gallery.sidebar.metric_help.subject_prominence_range', sectionKey: 'gallery.sidebar.saliency', minKey: 'min_subject_prominence', maxKey: 'max_subject_prominence', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'subject_placement_range', labelKey: 'gallery.subject_placement_range', helpKey: 'gallery.sidebar.metric_help.subject_placement_range', sectionKey: 'gallery.sidebar.saliency', minKey: 'min_subject_placement', maxKey: 'max_subject_placement', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'bg_separation_range', labelKey: 'gallery.bg_separation_range', helpKey: 'gallery.sidebar.metric_help.bg_separation_range', sectionKey: 'gallery.sidebar.saliency', minKey: 'min_bg_separation', maxKey: 'max_bg_separation', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },

  { id: 'moment_confidence_range', labelKey: 'gallery.moment_confidence_range', helpKey: 'gallery.sidebar.metric_help.moment_confidence_range', sectionKey: 'gallery.sidebar.moments', minKey: 'min_moment_confidence', maxKey: 'max_moment_confidence', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  // Technical
  { id: 'sharpness_range', labelKey: 'gallery.sharpness_range', helpKey: 'gallery.sidebar.metric_help.sharpness_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_sharpness', maxKey: 'max_sharpness', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'exposure_range', labelKey: 'gallery.exposure_range', helpKey: 'gallery.sidebar.metric_help.exposure_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_exposure', maxKey: 'max_exposure', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'color_range', labelKey: 'gallery.color_range', helpKey: 'gallery.sidebar.metric_help.color_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_color', maxKey: 'max_color', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'contrast_range', labelKey: 'gallery.contrast_range', helpKey: 'gallery.sidebar.metric_help.contrast_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_contrast', maxKey: 'max_contrast', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'saturation_range', labelKey: 'gallery.saturation_range', helpKey: 'gallery.sidebar.metric_help.saturation_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_saturation', maxKey: 'max_saturation', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  { id: 'noise_range', labelKey: 'gallery.noise_range', helpKey: 'gallery.sidebar.metric_help.noise_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_noise', maxKey: 'max_noise', sliderMin: 0, sliderMax: 20, step: 0.5, spanWidth: 'w-16' },
  // Exposure & Range
  { id: 'dynamic_range', labelKey: 'gallery.dynamic_range', helpKey: 'gallery.sidebar.metric_help.dynamic_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_dynamic_range', maxKey: 'max_dynamic_range', sliderMin: 0, sliderMax: 15, step: 0.5, displaySuffix: ' EV', spanWidth: 'w-16' },
  { id: 'luminance_range', labelKey: 'gallery.luminance_range', helpKey: 'gallery.sidebar.metric_help.luminance_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_luminance', maxKey: 'max_luminance', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  { id: 'histogram_range', labelKey: 'gallery.histogram_range', helpKey: 'gallery.sidebar.metric_help.histogram_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_histogram_spread', maxKey: 'max_histogram_spread', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  // Percent of pixels, worst of R/G/B. Capped at 25 rather than 100: over 28
  // sampled photos the worst highlight clipping seen was 12.7% and the worst
  // shadow 30.4%, so a 0-100 slider would spend nine tenths of its travel on
  // values no photo has.
  { id: 'channel_clip_highlight_range', labelKey: 'gallery.channel_clip_highlight_range', helpKey: 'gallery.sidebar.metric_help.channel_clip_highlight_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_channel_clip_highlight', maxKey: 'max_channel_clip_highlight', sliderMin: 0, sliderMax: 25, step: 0.5, displaySuffix: '%', spanWidth: 'w-16' },
  { id: 'channel_clip_shadow_range', labelKey: 'gallery.channel_clip_shadow_range', helpKey: 'gallery.sidebar.metric_help.channel_clip_shadow_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_channel_clip_shadow', maxKey: 'max_channel_clip_shadow', sliderMin: 0, sliderMax: 25, step: 0.5, displaySuffix: '%', spanWidth: 'w-16' },
  { id: 'iso_range', labelKey: 'gallery.iso_range', helpKey: 'gallery.sidebar.metric_help.iso_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_iso', maxKey: 'max_iso', sliderMin: 50, sliderMax: 25600, step: 50, spanWidth: 'w-20' },
  { id: 'aperture_range', labelKey: 'gallery.aperture_range', helpKey: 'gallery.sidebar.metric_help.aperture_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_aperture', maxKey: 'max_aperture', sliderMin: 0.7, sliderMax: 64, step: 0.1, displayPrefix: 'f/', spanWidth: 'w-20' },
  { id: 'focal_range', labelKey: 'gallery.focal_range', helpKey: 'gallery.sidebar.metric_help.focal_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_focal_length', maxKey: 'max_focal_length', sliderMin: 1, sliderMax: 1200, step: 1, displaySuffix: 'mm', spanWidth: 'w-24' },
  // User Ratings
  { id: 'star_rating_range', labelKey: 'gallery.star_rating_range', helpKey: 'gallery.sidebar.metric_help.star_rating_range', sectionKey: 'gallery.sidebar.ratings', minKey: 'min_star_rating', maxKey: 'max_star_rating', sliderMin: 0, sliderMax: 5, step: 1, spanWidth: 'w-16' },
];

export const COMMON_SECTION_ORDER = [
  'gallery.sidebar.quality',
  'gallery.sidebar.ratings',
];

export const ADVANCED_SECTION_ORDER = [
  'gallery.sidebar.extended_quality',
  'gallery.sidebar.face',
  'gallery.sidebar.composition',
  'gallery.sidebar.saliency',
  'gallery.sidebar.moments',
  'gallery.sidebar.technical',
  'gallery.sidebar.exposure_range',
];

export const SECTION_ORDER = [...COMMON_SECTION_ORDER, ...ADVANCED_SECTION_ORDER];

export interface FilterGroup {
  sectionKey: string;
  filters: AdditionalFilterDef[];
}

// Pre-built map for O(1) section lookup — both filterGroups and sectionActiveCounts use this.
export const FILTERS_BY_SECTION: Record<string, AdditionalFilterDef[]> = Object.fromEntries(
  SECTION_ORDER.map(key => [key, ADDITIONAL_FILTERS.filter(f => f.sectionKey === key)])
);

export const SECTION_ICONS: Record<string, string> = {
  'gallery.sidebar.quality': 'star',
  'gallery.sidebar.extended_quality': 'analytics',
  'gallery.sidebar.face': 'face',
  'gallery.sidebar.composition': 'grid_3x3',
  'gallery.sidebar.saliency': 'center_focus_strong',
  'gallery.sidebar.moments': 'auto_awesome',
  'gallery.sidebar.technical': 'tune',
  'gallery.sidebar.exposure_range': 'exposure',
  'gallery.sidebar.ratings': 'grade',
};

/** Panels that are not metric sections (those come from `SECTION_ORDER`). */
export const BROWSE_PANELS = ['semantic', 'persons', 'date', 'content', 'albums', 'location', 'folder', 'equipment'] as const;

export type SidebarTabId = 'browse' | 'review' | 'quality' | 'subject' | 'display';

/** Which panels each tab holds, in render order. Every panel is in exactly one tab. */
export const TAB_SECTIONS: Record<SidebarTabId, readonly string[]> = {
  browse: BROWSE_PANELS,
  review: ['refine', 'gallery.sidebar.ratings'],
  quality: ['gallery.sidebar.quality', 'color_quality', 'gallery.sidebar.extended_quality', 'gallery.sidebar.technical', 'gallery.sidebar.exposure_range'],
  subject: ['gallery.sidebar.face', 'gallery.sidebar.composition', 'gallery.sidebar.saliency', 'gallery.sidebar.moments'],
  display: ['view'],
};

export const TAB_IDS = Object.keys(TAB_SECTIONS) as SidebarTabId[];

export const TAB_ICONS: Record<SidebarTabId, string> = {
  browse: 'travel_explore',
  review: 'rule',
  quality: 'high_quality',
  subject: 'center_focus_strong',
  display: 'display_settings',
};

const DEFAULT_TAB: SidebarTabId = 'browse';

export type SegmentRowId = 'decision' | 'rejected' | 'bursts' | 'duplicates' | 'blinks' | 'brackets' | 'panoramas';

/**
 * The filter keys each segment of a Review row writes. "Only" clears the matching "hide" toggle (the
 * server suspends the hide toggles while an "only" flag is set), and a hide clears its "only", so a row
 * is always one of its segments. The rejected row reads the same keys as the old pair of checkboxes.
 */
export const SEGMENT_PATCHES: Record<Exclude<SegmentRowId, 'decision'>, Record<string, Partial<GalleryFilters>>> = {
  rejected: {
    hide: { hide_rejected: true, show_rejected: false },
    show: { hide_rejected: false, show_rejected: false },
    only: { hide_rejected: false, show_rejected: true },
  },
  bursts: { best: { hide_bursts: true }, all: { hide_bursts: false } },
  duplicates: {
    hide: { hide_duplicates: true, duplicates_only: false },
    all: { hide_duplicates: false, duplicates_only: false },
    only: { hide_duplicates: false, duplicates_only: true },
  },
  blinks: {
    hide: { hide_blinks: true, blinks_only: false },
    all: { hide_blinks: false, blinks_only: false },
    only: { hide_blinks: false, blinks_only: true },
  },
  brackets: { base: { hide_brackets: true }, all: { hide_brackets: false } },
  panoramas: { lead: { hide_panoramas: true }, all: { hide_panoramas: false } },
};

/** One choice of a Review row: a short value label, and the sentence that says what it does. */
export interface SegmentOption { value: string; labelKey: string; descKey: string }
export interface SegmentRow {
  id: SegmentRowId;
  icon: string;
  labelKey: string;
  helpKey: string;
  value: string;
  /** The label of the option `value` selects, shown on the row and in its accessible name. */
  valueLabelKey: string;
  disabled: boolean;
  options: SegmentOption[];
}

/**
 * The panel a filter control (see `filterUnit`) is counted under. One map feeds the
 * panel badges, the tab badges and the header total, so a range counts once everywhere.
 * A unit absent from the map (the filename search, `similar_to`, the unexposed `topiq`
 * range) lives outside the tabs and is counted by the header only.
 */
export const UNIT_PANEL: Record<string, string> = {
  person_id: 'persons', faces_need_names: 'persons',
  date_from: 'date', date_to: 'date',
  type: 'content', tag: 'content', composition_pattern: 'content',
  camera: 'equipment', lens: 'equipment',
  review_status: 'refine', favorites_only: 'refine', is_monochrome: 'refine', show_rejected: 'refine',
  blinks_only: 'refine', duplicates_only: 'refine', sequence_override: 'refine', manual_faces_need_review: 'refine',
  path_prefix: 'folder',
  gps: 'location',
  color_temp: 'color_quality', hue_bucket: 'color_quality', quality_tier: 'color_quality',
  semanticQuery: 'semantic',
  ...Object.fromEntries(ADDITIONAL_FILTERS.map(d => [filterUnit(d.minKey), d.sectionKey])),
};

const SIDEBAR_SECTIONS_KEY = 'facet_sidebar_sections';
const SIDEBAR_TAB_KEY = 'facet_sidebar_tab';
// One-time cleanup of legacy localStorage key from v3.x.
try { localStorage.removeItem('facet_active_filters'); } catch { /* ignore */ }

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch { /* ignore */ }
  return null;
}

function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch { /* ignore */ }
}

function loadSectionStates(): Record<string, boolean> {
  try {
    const raw = readStored(SIDEBAR_SECTIONS_KEY);
    if (raw) return JSON.parse(raw) as Record<string, boolean>;
  } catch { /* ignore */ }
  return {};
}

function saveSectionStates(states: Record<string, boolean>): void {
  writeStored(SIDEBAR_SECTIONS_KEY, JSON.stringify(states));
}

/** The stored tab id, or the default for a missing or unknown one. */
export function loadActiveTab(): SidebarTabId {
  const raw = readStored(SIDEBAR_TAB_KEY);
  return TAB_IDS.find(id => id === raw) ?? DEFAULT_TAB;
}

@Component({
  selector: 'app-gallery-filter-sidebar',
  standalone: true,
  host: { class: 'flex flex-col h-full' },
  imports: [
    DecimalPipe,
    MetricSparklineComponent,
    NgTemplateOutlet,
    FormsModule,
    MatSelectModule,
    MatSliderModule,
    MatIconModule,
    MatButtonModule,
    MatFormFieldModule,
    MatCheckboxModule,
    MatInputModule,
    MatTooltipModule,
    HelpTooltipDirective,
    MatAutocompleteModule,
    MatExpansionModule,
    MatTabsModule,
    MatMenuModule,
    MatRippleModule,
    MatDatepickerModule,
    MatDialogModule,
    TranslatePipe,
    FilterDisplayPipe,
    PersonThumbnailUrlPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
<div class="shrink-0 px-2">

      <div class="pt-3 pb-2 flex items-center gap-2">
        <span class="text-sm font-medium opacity-80">{{ I18N.gallery.filters | translate }}</span>
        @if (totalActiveCount()) {
          <span data-test="active-count" class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ totalActiveCount() }}</span>
        }
        <span class="flex-1"></span>
        @if (totalActiveCount()) {
          <button mat-button data-test="reset" class="!min-w-0 !px-2 !text-xs"
            [matTooltip]="I18N.gallery.sidebar.reset_tooltip | translate"
            (click)="store.resetFilters()">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">restart_alt</mat-icon>
            {{ I18N.gallery.reset_filters | translate }}
          </button>
        }
        <button mat-icon-button data-test="close" class="md:hidden !w-8 !h-8 !p-0 !min-w-0 shrink-0"
          [matTooltip]="I18N.dialog.close | translate"
          [attr.aria-label]="I18N.dialog.close | translate"
          (click)="store.setFilterDrawerOpen(false)">
          <mat-icon class="!text-lg !w-5 !h-5 !leading-5">close</mat-icon>
        </button>
      </div>

      <!-- Smart album filter notice -->
      @if (store.currentAlbum()?.is_smart && auth.isEdition()) {
        <div class="flex items-start gap-2 rounded-lg bg-[var(--mat-sys-tertiary-container)] text-[var(--mat-sys-on-tertiary-container)] text-xs px-3 py-2 mb-2">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 shrink-0 mt-0.5">info</mat-icon>
          <span>{{ I18N.gallery.sidebar.smart_album_filter_notice | translate }}</span>
        </div>
      }

      <!-- Search (visible below 2xl, hidden on 2xl+ where header search is shown) -->
      <div class="2xl:!hidden mb-1">
        <mat-form-field subscriptSizing="dynamic" class="w-full">
          <mat-label>{{ I18N.ui.filters.search | translate }}</mat-label>
          <mat-icon matPrefix class="mr-1 opacity-60">search</mat-icon>
          <input matInput #sidebarSearch
            [placeholder]="I18N.gallery.search_placeholder | translate"
            [value]="store.filters().search"
            (input)="onSidebarSearchChange($event)"
            (keyup.enter)="onSidebarSearchCommit($event)" />
          @if (store.filters().search) {
            <button matSuffix mat-icon-button class="!w-6 !h-6 !p-0" (click)="store.updateFilter('search', '')" [attr.aria-label]="I18N.gallery.clear_search | translate">
              <mat-icon class="!text-sm !w-4 !h-4">close</mat-icon>
            </button>
          }
        </mat-form-field>
      </div>

      <!-- Find a filter -->
      <mat-form-field subscriptSizing="dynamic" class="w-full !mb-1">
        <mat-icon matPrefix class="mr-1 opacity-60">manage_search</mat-icon>
        <input matInput [placeholder]="I18N.gallery.sidebar.find_filter | translate"
               [attr.aria-label]="I18N.gallery.sidebar.find_filter | translate"
               [value]="filterQuery()" (input)="filterQuery.set($any($event.target).value)" />
        @if (filterQuery()) {
          <button matSuffix mat-icon-button class="!w-6 !h-6 !p-0" (click)="filterQuery.set('')" [attr.aria-label]="I18N.gallery.sidebar.clear_find_filter | translate">
            <mat-icon class="!text-sm !w-4 !h-4">close</mat-icon>
          </button>
        }
      </mat-form-field>

      @if (!filterQuery().trim()) {
        <nav mat-tab-nav-bar mat-stretch-tabs="true" animationDuration="0ms" [tabPanel]="tabPanel"
             [attr.aria-label]="I18N.gallery.sidebar.tabs.aria_label | translate"
             class="[&_.mdc-tab]:!min-w-0 [&_.mdc-tab]:!px-2 [&_.mdc-tab--active_mat-icon]:!text-[var(--mat-sys-primary)]">
          @for (tab of tabItems(); track tab.id) {
            <button type="button" mat-tab-link [active]="tab.active" (click)="selectTab(tab.id)"
               [matTooltip]="tab.labelKey | translate"
               [attr.aria-label]="tab.count ? (I18N.gallery.sidebar.tabs.active_count | translate:{ label: (tab.labelKey | translate), count: tab.count }) : (tab.labelKey | translate)">
              <span class="relative inline-flex">
                <mat-icon aria-hidden="true">{{ tab.icon }}</mat-icon>
                @if (tab.count) {
                  <span aria-hidden="true" class="absolute -top-1 -right-2 text-[0.625rem] rounded-full min-w-[1rem] h-4 px-1 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ tab.count }}</span>
                }
              </span>
            </button>
          }
        </nav>
      }
    </div>

    <mat-tab-nav-panel #tabPanel class="flex-1 min-h-0 flex flex-col [--mat-expansion-header-collapsed-state-height:40px] [--mat-expansion-header-expanded-state-height:44px] [&_.mat-expansion-panel-body]:!px-4">
    <div data-scroll #scrollArea class="flex-1 min-h-0 overflow-y-auto px-2 pt-3 pb-4">

      @if (filterQuery().trim()) {
        @if (noFilterMatches()) {
          <p class="text-xs opacity-50 px-2 py-3">{{ I18N.gallery.sidebar.no_filters_match | translate }}</p>
        }
        @for (group of metricFilterGroups(); track group.sectionKey) {
          <div class="px-1 pt-2 pb-1">
            <div class="flex items-center gap-2 text-xs font-medium opacity-70 mb-1">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">{{ sectionIcons[group.sectionKey] || 'tune' }}</mat-icon>
              {{ group.sectionKey | translate }}
            </div>
            @for (def of group.filters; track def.id) {
              <ng-container [ngTemplateOutlet]="metricRow" [ngTemplateOutletContext]="{ $implicit: def }" />
            }
          </div>
        }
      } @else {
        @switch (activeTab()) {
          @case ('browse') {
      <!-- Semantic Search (top of sidebar) -->
      @if (store.config()?.features?.show_semantic_search) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['semantic'] === true"
                             (opened)="onSectionToggle('semantic', true)"
                             (closed)="onSectionToggle('semantic', false)"
                             [style.background-color]="sectionStates()['semantic'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-4">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">image_search</mat-icon>
              {{ I18N.gallery.sidebar.semantic_search | translate }}
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            <mat-form-field subscriptSizing="dynamic" class="w-full">
              <mat-label>{{ I18N.gallery.semantic_search | translate }}</mat-label>
              <mat-icon matPrefix class="mr-1 opacity-60">image_search</mat-icon>
              <input #semanticSearchInput matInput
                [value]="store.filters().semanticQuery"
                (input)="onSemanticSearch($event)"
                [placeholder]="I18N.gallery.semantic_search_placeholder | translate" />
              @if (store.filters().semanticQuery) {
                <button matSuffix mat-icon-button class="!w-6 !h-6 !p-0" (click)="store.updateFilter('semanticQuery', '')" [attr.aria-label]="I18N.gallery.clear_semantic_search | translate">
                  <mat-icon class="!text-sm !w-4 !h-4">close</mat-icon>
                </button>
              }
            </mat-form-field>
            <p class="text-xs opacity-50 px-1">{{ I18N.gallery.semantic_search_info | translate }}</p>
            <div class="flex items-center gap-2 px-1">
              <span class="text-sm opacity-70 shrink-0">{{ I18N.gallery.semantic_search_threshold | translate }}</span>
              <mat-slider [min]="0" [max]="SEARCH_THRESHOLD_MAX" [step]="1" [displayWith]="formatThresholdPercent" class="flex-1">
                <input matSliderThumb
                  [value]="searchThresholdValue()"
                  (valueChange)="onSearchThresholdChange($event)"
                  [attr.aria-label]="I18N.gallery.semantic_search_threshold | translate"
                  aria-describedby="semantic-search-threshold-hint" />
              </mat-slider>
              <span class="text-xs opacity-60 w-10 text-right">{{ searchThresholdValue() }}%</span>
            </div>
            <p id="semantic-search-threshold-hint" class="text-xs opacity-50 px-1">{{ I18N.gallery.semantic_search_threshold_hint | translate }}</p>
          </div>
        </mat-expansion-panel>
      }

      <!-- Persons -->
        <mat-expansion-panel class="!mb-1 mt-1" [expanded]="sectionStates()['persons'] !== false"
                             (opened)="onSectionToggle('persons', true)"
                             (closed)="onSectionToggle('persons', false)"
                             [style.background-color]="sectionStates()['persons'] !== false ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-4">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">people</mat-icon>
              {{ I18N.gallery.sidebar.persons | translate }}
              @if (sectionActiveCounts()['persons']) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['persons'] }}</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            <mat-checkbox
              [aria-describedby]="store.filters().faces_need_names ? 'face-naming-hint' : ''"
              [checked]="store.filters().faces_need_names"
              (change)="store.updateFilter('faces_need_names', $event.checked)"
            >{{ I18N.gallery.faces_need_names | translate }}</mat-checkbox>
            @if (store.filters().faces_need_names) {
              <p id="face-naming-hint" class="text-xs text-gray-500 dark:text-gray-400">{{ (auth.isEdition() ? I18N.gallery.faces_need_names_hint : I18N.gallery.faces_need_names_readonly_hint) | translate }}</p>
            }
            <mat-form-field subscriptSizing="dynamic" class="w-full">
              @if (!selectedPersons().length) {
                <mat-label>{{ I18N.gallery.person | translate }}</mat-label>
              }
              <input matInput #sidebarPersonInput
                     [matAutocomplete]="sidebarPersonAuto"
                     [value]="sidebarPersonQuery()"
                     [placeholder]="selectedPersons().length ? (I18N.gallery.person_add | translate) : ''"
                     (input)="sidebarPersonQuery.set($any($event.target).value)"
                     (focus)="sidebarPersonQuery.set('')" />
              <mat-autocomplete #sidebarPersonAuto="matAutocomplete"
                                (optionSelected)="onSidebarPersonSelected($event)"
                                [hideSingleSelectionIndicator]="true">
                @for (p of filteredPersons(); track p.id) {
                  <mat-option [value]="p.id">
                    <div class="flex items-center gap-2">
                      <img [src]="p.id | personThumbnailUrl" class="w-8 h-8 rounded-full object-cover shrink-0" [alt]="p.name || (I18N.gallery.unknown_person | translate)" loading="lazy" />
                      <span class="text-sm">{{ p.name || (I18N.gallery.unknown_person | translate) }} ({{ p.face_count }})</span>
                    </div>
                  </mat-option>
                }
              </mat-autocomplete>
            </mat-form-field>
            @if (selectedPersons().length) {
              <div class="flex flex-wrap gap-1.5">
                @for (p of selectedPersons(); track p.id) {
                  <button class="relative shrink-0 group/person cursor-pointer" [matTooltip]="p.name || (I18N.gallery.unknown_person | translate)" (click)="removePersonChip(p.id)">
                    <img [src]="p.id | personThumbnailUrl" class="w-9 h-9 rounded-full object-cover" [alt]="p.name || (I18N.gallery.unknown_person | translate)" />
                    <div class="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center opacity-0 group-hover/person:opacity-100 transition-opacity">
                      <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-white">close</mat-icon>
                    </div>
                  </button>
                }
              </div>
            }
          </div>
        </mat-expansion-panel>

      <!-- Date Range -->
      <mat-expansion-panel class="!mb-1 mt-4" [expanded]="sectionStates()['date'] !== false"
                           (opened)="onSectionToggle('date', true)"
                           (closed)="onSectionToggle('date', false)"
                           [style.background-color]="sectionStates()['date'] !== false ? 'var(--mat-sys-surface-container)' : null">
        <mat-expansion-panel-header class="!px-4">
          <mat-panel-title class="flex items-center gap-2">
            <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">calendar_today</mat-icon>
            {{ I18N.gallery.sidebar.date | translate }}
            @if (sectionActiveCounts()['date']) {
              <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['date'] }}</span>
            }
          </mat-panel-title>
        </mat-expansion-panel-header>
        <div class="flex flex-col gap-2 pb-2">
          <mat-form-field subscriptSizing="dynamic" class="w-full">
            <mat-label>{{ I18N.gallery.date_from | translate }}</mat-label>
            <input matInput [matDatepicker]="fromDp" [value]="store.filters().date_from" (dateChange)="onDateChange('date_from', $event)" />
            <mat-datepicker-toggle matIconSuffix [for]="fromDp" />
            <mat-datepicker #fromDp />
          </mat-form-field>
          <mat-form-field subscriptSizing="dynamic" class="w-full">
            <mat-label>{{ I18N.gallery.date_to | translate }}</mat-label>
            <input matInput [matDatepicker]="toDp" [value]="store.filters().date_to" (dateChange)="onDateChange('date_to', $event)" />
            <mat-datepicker-toggle matIconSuffix [for]="toDp" />
            <mat-datepicker #toDp />
          </mat-form-field>
        </div>
      </mat-expansion-panel>

      <!-- Content -->
      @if (store.types().length || store.tags().length || store.patterns().length) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['content'] !== false"
                             (opened)="onSectionToggle('content', true)"
                             (closed)="onSectionToggle('content', false)"
                             [style.background-color]="sectionStates()['content'] !== false ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-4">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">label</mat-icon>
              {{ I18N.gallery.sidebar.content | translate }}
              @if (sectionActiveCounts()['content']) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['content'] }}</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            @if (store.types().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full lg:!hidden">
                <mat-label>{{ I18N.ui.filters.type | translate }}</mat-label>
                <mat-select panelWidth="auto" panelClass="nowrap-panel !max-h-[70vh]" [value]="store.filters().type" (selectionChange)="store.updateFilter('type', $event.value)">
                  <mat-option value="">{{ I18N.gallery.all_photos | translate }}</mat-option>
                  @for (t of store.types(); track t.id) {
                    <mat-option [value]="t.id">{{ (t.id === 'top_picks' ? 'photo_types.top_picks' : 'category_names.' + t.id) | translate }} ({{ t.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
            @if (store.tags().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ I18N.gallery.tag | translate }}</mat-label>
                <mat-select [value]="store.filters().tag" (selectionChange)="store.updateFilter('tag', $event.value)">
                  <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                  @for (t of store.tags(); track t.value) {
                    <mat-option [value]="t.value">{{ t.value }} ({{ t.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
            @if (store.patterns().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ I18N.gallery.composition_pattern | translate }}</mat-label>
                <mat-select [value]="store.filters().composition_pattern" (selectionChange)="store.updateFilter('composition_pattern', $event.value)">
                  <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                  @for (p of store.patterns(); track p.value) {
                    <mat-option [value]="p.value">{{ ('composition_patterns.' + p.value) | translate }} ({{ p.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
          </div>
        </mat-expansion-panel>
      }

      <!-- Albums -->
      @if (store.config()?.features?.show_albums && albums().length) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['albums'] === true"
                             (opened)="onSectionToggle('albums', true)"
                             (closed)="onSectionToggle('albums', false)"
                             [style.background-color]="sectionStates()['albums'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-4">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">photo_album</mat-icon>
              {{ I18N.albums.title | translate }}
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            <mat-form-field subscriptSizing="dynamic" class="w-full">
              <mat-label>{{ I18N.albums.title | translate }}</mat-label>
              <mat-select [value]="store.filters().album_id" (selectionChange)="store.updateFilter('album_id', $event.value)">
                <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                @for (a of albums(); track a.id) {
                  <mat-option [value]="'' + a.id">{{ a.name }} ({{ a.photo_count }})</mat-option>
                }
              </mat-select>
            </mat-form-field>
          </div>
        </mat-expansion-panel>
      }

      <!-- Location filter -->
      <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['location'] === true"
                           (opened)="onSectionToggle('location', true)"
                           (closed)="onSectionToggle('location', false)"
                           [style.background-color]="sectionStates()['location'] === true ? 'var(--mat-sys-surface-container)' : null">
        <mat-expansion-panel-header class="!px-4">
          <mat-panel-title class="flex items-center gap-2">
            <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">place</mat-icon>
            {{ I18N.gallery.sidebar.location | translate }}
            @if (sectionActiveCounts()['location']) {
              <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['location'] }}</span>
            }
          </mat-panel-title>
        </mat-expansion-panel-header>
        <div class="flex flex-col gap-2 pb-2">
          <mat-checkbox [checked]="!!store.filters().no_gps" (change)="store.updateFilter('no_gps', $event.checked ? '1' : '')">
            {{ I18N.gallery.no_geolocation | translate }}
          </mat-checkbox>
          @if (store.filters().gps_lat) {
            <div class="text-xs opacity-60 px-1">
              @if (store.gpsLocationName()) {
                {{ store.gpsLocationName() }} — {{ store.filters().gps_radius_km }} km
              } @else {
                {{ +store.filters().gps_lat | number:'1.4-4' }}, {{ +store.filters().gps_lng | number:'1.4-4' }}
                — {{ store.filters().gps_radius_km }} km
              }
            </div>
            <button mat-stroked-button class="w-full" (click)="clearGpsFilter()">
              <mat-icon>close</mat-icon>
              {{ I18N.gallery.gps_clear | translate }}
            </button>
          }
          @if (store.config()?.features?.show_map) {
            <button mat-stroked-button class="w-full" (click)="openGpsFilterMap()">
              <mat-icon>map</mat-icon>
              {{ I18N.gallery.select_on_map | translate }}
            </button>
          }
        </div>
      </mat-expansion-panel>

      <!-- Folder filter -->
      @if (store.config()?.features?.show_folders || store.filters().path_prefix) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['folder'] === true"
                             (opened)="onSectionToggle('folder', true)"
                             (closed)="onSectionToggle('folder', false)"
                             [style.background-color]="sectionStates()['folder'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-4">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">folder</mat-icon>
              {{ I18N.gallery.sidebar.folder | translate }}
              @if (sectionActiveCounts()['folder']) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['folder'] }}</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            @if (store.filters().path_prefix) {
              <div class="flex items-center gap-1">
                <button mat-stroked-button class="flex-1 min-w-0 !justify-start" [matTooltip]="store.filters().path_prefix"
                        [attr.aria-label]="I18N.gallery.choose_folder | translate" (click)="openFolderPicker()">
                  <mat-icon>folder</mat-icon>
                  <span class="truncate">{{ currentFolderName() }}</span>
                </button>
                <button mat-icon-button [matTooltip]="I18N.gallery.folder_clear | translate"
                        [attr.aria-label]="I18N.gallery.folder_clear | translate" (click)="clearFolderFilter()">
                  <mat-icon>close</mat-icon>
                </button>
              </div>
            } @else {
              <button mat-stroked-button class="w-full" (click)="openFolderPicker()">
                <mat-icon>folder_open</mat-icon>
                {{ I18N.gallery.choose_folder | translate }}
              </button>
            }
          </div>
        </mat-expansion-panel>
      }

      <!-- Equipment -->
      @if (store.cameras().length || store.lenses().length) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['equipment'] !== false"
                             (opened)="onSectionToggle('equipment', true)"
                             (closed)="onSectionToggle('equipment', false)"
                             [style.background-color]="sectionStates()['equipment'] !== false ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-4">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">photo_camera</mat-icon>
              {{ I18N.gallery.sidebar.equipment | translate }}
              @if (sectionActiveCounts()['equipment']) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['equipment'] }}</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            @if (store.cameras().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ I18N.gallery.camera | translate }}</mat-label>
                <mat-select [value]="store.filters().camera" (selectionChange)="store.updateFilter('camera', $event.value)">
                  <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                  @for (c of store.cameras(); track c.value) {
                    <mat-option [value]="c.value">{{ c.value }} ({{ c.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
            @if (store.lenses().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ I18N.gallery.lens | translate }}</mat-label>
                <mat-select [value]="store.filters().lens" (selectionChange)="store.updateFilter('lens', $event.value)">
                  <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                  @for (l of store.lenses(); track l.value) {
                    <mat-option [value]="l.value">{{ l.value }} ({{ l.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
          </div>
        </mat-expansion-panel>
      }
          }
          @case ('review') {
      <div data-section="review" class="flex flex-col gap-2 px-1 pt-1 pb-2">
        <div class="flex flex-col">
          @for (row of reviewRows(); track row.id) {
            @if ($index === 1) {
              <span class="text-xs uppercase opacity-60 mt-2 mb-1 px-2">{{ I18N.gallery.sidebar.review.sets | translate }}</span>
            }
            <button type="button" matRipple class="flex w-full min-h-10 items-center gap-3 rounded-md px-2 py-1 text-left hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)] aria-disabled:opacity-50"
              [attr.data-row]="row.id" aria-haspopup="menu"
              [matMenuTriggerFor]="row.disabled ? null : menu" [attr.aria-disabled]="row.disabled || null"
              [attr.aria-label]="I18N.gallery.sidebar.review.value_aria | translate:{ label: (row.labelKey | translate), value: (row.valueLabelKey | translate) }"
              [appHelpTip]="(row.disabled ? I18N.gallery.sidebar.review.rejected_locked : row.helpKey) | translate">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-5 shrink-0 opacity-80">{{ row.icon }}</mat-icon>
              <span class="flex-1 min-w-0 text-sm break-words">{{ row.labelKey | translate }}</span>
              <span class="shrink-0 text-xs opacity-70" data-value>{{ row.valueLabelKey | translate }}</span>
              <mat-icon class="!text-xl !w-5 !h-5 !leading-5 shrink-0 opacity-70">expand_more</mat-icon>
            </button>
            <mat-menu #menu="matMenu">
              <ng-template matMenuContent>
              @for (option of row.options; track option.value) {
                <button type="button" mat-menu-item role="menuitemradio" [attr.data-option]="option.value"
                  [attr.aria-checked]="option.value === row.value"
                  [appHelpTip]="option.descKey | translate"
                  (click)="onSegment(row.id, option.value)">
                  <mat-icon [class.invisible]="option.value !== row.value">check</mat-icon>
                  <span class="flex flex-col py-1">
                    <span class="text-sm">{{ option.labelKey | translate }}</span>
                    <span class="text-xs opacity-70 whitespace-normal leading-snug">{{ option.descKey | translate }}</span>
                  </span>
                </button>
              }
              </ng-template>
            </mat-menu>
          }
        </div>

        <div class="flex items-center gap-2 mt-1" role="group" [attr.aria-label]="I18N.gallery.sidebar.review.quick | translate" data-row="quick">
          <span class="relative inline-flex">
            <button type="button" mat-stroked-button class="!min-w-0 !w-10 !h-8 !px-0" data-row="rating"
              [class.!bg-[var(--mat-sys-primary-container)]]="ratingMin() > 0"
              [attr.aria-label]="ratingKey() | translate:ratingVars()"
              [appHelpTip]="ratingKey() | translate:ratingVars()"
              (click)="cycleRating()">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-5 !m-0">{{ ratingMin() > 0 ? 'star' : 'star_border' }}</mat-icon>
            </button>
            @if (ratingMin() > 0) {
              <span aria-hidden="true" data-test="rating-badge" class="pointer-events-none absolute -top-1.5 -right-1.5 text-[0.625rem] rounded-full min-w-[1rem] h-4 px-1 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ ratingMin() }}</span>
            }
          </span>
          <span class="sr-only" aria-live="polite" data-test="rating-status">{{ ratingKey() | translate:ratingVars() }}</span>
          @if (ratingMaxLabel()) {
            <span class="text-xs opacity-70" data-test="rating-max">{{ ratingMaxLabel() }}</span>
          }
          <button type="button" mat-stroked-button class="!min-w-0 !w-10 !h-8 !px-0" data-toggle="favorites_only"
            [class.!bg-[var(--mat-sys-primary-container)]]="store.filters().favorites_only"
            [attr.aria-pressed]="store.filters().favorites_only"
            [attr.aria-label]="I18N.gallery.favorites_only | translate"
            [appHelpTip]="I18N.gallery.sidebar.refine_help.favorites_only | translate"
            (click)="store.updateFilter('favorites_only', !store.filters().favorites_only)">
            <mat-icon class="!text-xl !w-5 !h-5 !leading-5 !m-0">favorite</mat-icon>
          </button>
          <button type="button" mat-stroked-button class="!min-w-0 !w-10 !h-8 !px-0" data-toggle="is_monochrome"
            [class.!bg-[var(--mat-sys-primary-container)]]="store.filters().is_monochrome"
            [attr.aria-pressed]="store.filters().is_monochrome"
            [attr.aria-label]="I18N.gallery.monochrome_only | translate"
            [appHelpTip]="I18N.gallery.sidebar.refine_help.monochrome_only | translate"
            (click)="store.updateFilter('is_monochrome', !store.filters().is_monochrome)">
            <mat-icon class="!text-xl !w-5 !h-5 !leading-5 !m-0">contrast</mat-icon>
          </button>
        </div>

        <!-- A correction is invisible in the labels until the detector runs
             again, so without this the only record of one still pending is
             the user's memory. Edition-only: nobody else can make one. -->
        @if (auth.isEdition()) {
          <span class="text-xs uppercase opacity-60 mt-2">{{ I18N.gallery.sidebar.review.edition | translate }}</span>
          <button type="button" mat-stroked-button class="!min-w-0 !h-8 !text-xs !justify-start" data-toggle="manual_faces_need_review"
            [class.!bg-[var(--mat-sys-primary-container)]]="store.filters().manual_faces_need_review"
            [attr.aria-pressed]="store.filters().manual_faces_need_review"
            [appHelpTip]="I18N.gallery.sidebar.refine_help.manual_faces_need_review | translate"
            (click)="store.updateFilter('manual_faces_need_review', !store.filters().manual_faces_need_review)">
            {{ I18N.gallery.manual_faces_need_review | translate }}
          </button>
          @if (store.filters().manual_faces_need_review) {
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ I18N.gallery.manual_faces_review_hint | translate }}</p>
          }
          <mat-form-field subscriptSizing="dynamic" class="w-full">
            <mat-label>{{ I18N.gallery.sequence_override.label | translate }}</mat-label>
            <mat-select [value]="store.filters().sequence_override"
                        [appHelpTip]="I18N.gallery.sidebar.refine_help.sequence_override | translate"
                        (selectionChange)="store.updateFilter('sequence_override', $event.value)">
              <mat-option value="">{{ I18N.gallery.sequence_override.all | translate }}</mat-option>
              <mat-option value="any">{{ I18N.gallery.sequence_override.any | translate }}</mat-option>
              <mat-option value="suppressed">{{ I18N.gallery.sequence_override.suppressed | translate }}</mat-option>
              <mat-option value="forced">{{ I18N.gallery.sequence_override.forced | translate }}</mat-option>
            </mat-select>
          </mat-form-field>
        }
      </div>
          }
          @case ('quality') {
      @for (group of qualityGroups(); track group.sectionKey) {
        <ng-container [ngTemplateOutlet]="metricPanel" [ngTemplateOutletContext]="{ $implicit: group }" />
      }

      <!-- Color & Quality tier -->
      @if (store.colorTemps().length || store.hueBuckets().length || qualityTiers.length) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['color_quality'] === true"
                             (opened)="onSectionToggle('color_quality', true)"
                             (closed)="onSectionToggle('color_quality', false)"
                             [style.background-color]="sectionStates()['color_quality'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-4">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">palette</mat-icon>
              {{ I18N.gallery.sidebar.color_quality | translate }}
              @if (sectionActiveCounts()['color_quality']) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['color_quality'] }}</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            <!-- Quality tier -->
            <mat-form-field subscriptSizing="dynamic" class="w-full">
              <mat-label [appHelpTip]="I18N.gallery.sidebar.metric_help.quality_tier | translate">{{ I18N.gallery.quality_tier | translate }}</mat-label>
              <mat-select [value]="store.filters().quality_tier" aria-describedby="metric-help-quality_tier" (selectionChange)="store.updateFilter('quality_tier', $event.value)">
                <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                @for (t of qualityTiers; track t) {
                  <mat-option [value]="t">{{ ('gallery.quality_tiers.' + t) | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <span class="sr-only" id="metric-help-quality_tier">{{ I18N.gallery.sidebar.metric_help.quality_tier | translate }}</span>
            <!-- Color temperature -->
            @if (store.colorTemps().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label [appHelpTip]="I18N.gallery.sidebar.metric_help.color_temp | translate">{{ I18N.gallery.color_temp | translate }}</mat-label>
                <mat-select [value]="store.filters().color_temp" aria-describedby="metric-help-color_temp" (selectionChange)="store.updateFilter('color_temp', $event.value)">
                  <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                  @for (c of store.colorTemps(); track c.value) {
                    <mat-option [value]="c.value">{{ ('gallery.color_temps.' + c.value) | translate }} ({{ c.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
              <span class="sr-only" id="metric-help-color_temp">{{ I18N.gallery.sidebar.metric_help.color_temp | translate }}</span>
            }
            <!-- Hue buckets as colour chips -->
            @if (store.hueBuckets().length) {
              <span class="text-xs opacity-60 px-1" [appHelpTip]="I18N.gallery.sidebar.metric_help.hue_bucket | translate">{{ I18N.gallery.hue | translate }}</span>
              <span class="sr-only" id="metric-help-hue_bucket">{{ I18N.gallery.sidebar.metric_help.hue_bucket | translate }}</span>
              <div class="flex flex-wrap gap-1.5" role="group" [attr.aria-label]="I18N.gallery.hue | translate" aria-describedby="metric-help-hue_bucket">
                @for (h of store.hueBuckets(); track h.value) {
                  <button type="button"
                    class="flex items-center gap-1.5 rounded-full pl-1.5 pr-2.5 py-1 text-xs border border-[var(--mat-sys-outline-variant)] cursor-pointer"
                    [class.!border-[var(--mat-sys-primary)]]="store.filters().hue_bucket === h.value"
                    [class.bg-[var(--mat-sys-primary-container)]]="store.filters().hue_bucket === h.value"
                    [matTooltip]="('gallery.hue_buckets.' + h.value | translate) + ' (' + h.count + ')'"
                    (click)="toggleHueBucket(h.value)">
                    <span class="w-3.5 h-3.5 rounded-full shrink-0 border border-black/10" [style.background-color]="hueSwatches[h.value]"></span>
                    {{ ('gallery.hue_buckets.' + h.value) | translate }}
                  </button>
                }
              </div>
            }
          </div>
        </mat-expansion-panel>
      }

      @for (group of qualityAdvancedGroups(); track group.sectionKey) {
        <ng-container [ngTemplateOutlet]="metricPanel" [ngTemplateOutletContext]="{ $implicit: group }" />
      }
          }
          @case ('subject') {
      @for (group of subjectGroups(); track group.sectionKey) {
        <ng-container [ngTemplateOutlet]="metricPanel" [ngTemplateOutletContext]="{ $implicit: group }" />
      }
          }
          @case ('display') {
      <!-- View (display preferences, not filters): the tab's only section, so no panel around it -->
        <div data-section="view" class="flex flex-col gap-2 px-4 pt-1 pb-2">
          @if (store.galleryMode() !== 'mosaic') {
            <mat-checkbox
              [checked]="store.filters().hide_details"
              (change)="store.updateFilter('hide_details', $event.checked)"
            >{{ I18N.gallery.hide_details | translate }}</mat-checkbox>
          }
          <mat-checkbox
            [checked]="store.virtualScroll()"
            (change)="store.setVirtualScroll($event.checked)"
          >{{ I18N.gallery.sidebar.virtual_scroll | translate }}</mat-checkbox>
          <button mat-stroked-button class="!justify-start" (click)="openCardActionsDialog()">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">tune</mat-icon>
            {{ I18N.gallery.card_actions.title | translate }}
          </button>
          <div class="flex items-center gap-2 mt-2">
            <span class="text-sm opacity-70 shrink-0">{{ I18N.gallery.layout_mode | translate }}</span>
            <div class="flex gap-1 ml-auto">
              <button mat-icon-button class="!w-8 !h-8 !p-0 inline-flex items-center justify-center"
                [class.!bg-[var(--mat-sys-primary-container)]]="store.galleryMode() === 'grid'"
                [matTooltip]="I18N.gallery.layout_grid | translate"
                [attr.aria-label]="I18N.gallery.layout_grid | translate"
                (click)="store.setGalleryMode('grid')">
                <mat-icon class="!text-lg !w-5 !h-5 !leading-5">grid_view</mat-icon>
              </button>
              <button mat-icon-button class="!w-8 !h-8 !p-0 inline-flex items-center justify-center"
                [class.!bg-[var(--mat-sys-primary-container)]]="store.galleryMode() === 'mosaic'"
                [matTooltip]="I18N.gallery.layout_mosaic | translate"
                [attr.aria-label]="I18N.gallery.layout_mosaic | translate"
                (click)="store.setGalleryMode('mosaic')">
                <mat-icon class="!text-lg !w-5 !h-5 !leading-5">auto_awesome_mosaic</mat-icon>
              </button>
            </div>
          </div>
          @if (sliderConfig(); as sc) {
            <div class="flex items-center gap-2 mt-2">
              <span class="text-sm opacity-70 shrink-0">{{ I18N.gallery.thumbnail_size | translate }}</span>
              <mat-slider [min]="thumbnailSliderMin()" [max]="sc.max_px" [step]="sc.step_px" class="flex-1">
                <input matSliderThumb [value]="store.cardWidth()" (valueChange)="store.setCardWidth($event)" [attr.aria-label]="I18N.gallery.thumbnail_size | translate" />
              </mat-slider>
              <span class="text-xs opacity-60 w-10 text-right">{{ store.cardWidth() }}px</span>
            </div>
          }
        </div>
          }
        }
      }

      <ng-template #metricPanel let-group>
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()[group.sectionKey] === true"
                             (opened)="onSectionToggle(group.sectionKey, true)"
                             (closed)="onSectionToggle(group.sectionKey, false)"
                             [style.background-color]="sectionStates()[group.sectionKey] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-4">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">{{ sectionIcons[group.sectionKey] || 'tune' }}</mat-icon>
              {{ group.sectionKey | translate }}
              @if (sectionActiveCounts()[group.sectionKey]) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()[group.sectionKey] }}</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-1 pb-1">
            @for (def of group.filters; track def.id) {
              <ng-container [ngTemplateOutlet]="metricRow" [ngTemplateOutletContext]="{ $implicit: def }" />
            }
          </div>
        </mat-expansion-panel>
      </ng-template>

      <ng-template #metricRow let-def>
        <div class="flex flex-col gap-0" [attr.data-metric]="def.id">
          <span class="text-xs opacity-60 px-1" [appHelpTip]="def.helpKey | translate">{{ def.labelKey | translate }}</span>
          <span class="sr-only" [id]="'metric-help-' + def.id">{{ def.helpKey | translate }}</span>
          <div class="flex items-center gap-1">
            <div class="flex-1 flex flex-col">
              @if (store.metricRanges()[def.minKey]; as range) {
                <app-metric-sparkline [range]="range" />
              }
              <mat-slider [min]="def.sliderMin" [max]="def.sliderMax" [step]="def.step" class="w-full">
                <input matSliderStartThumb
                  [value]="$any(store.filters())[def.minKey] ? +$any(store.filters())[def.minKey] : def.sliderMin"
                  (valueChange)="onDynamicRangeChange(def, 'min', $event)"
                  [attr.aria-label]="(def.labelKey | translate) + ' min'" [attr.aria-describedby]="'metric-help-' + def.id" />
                <input matSliderEndThumb
                  [value]="$any(store.filters())[def.maxKey] ? +$any(store.filters())[def.maxKey] : def.sliderMax"
                  (valueChange)="onDynamicRangeChange(def, 'max', $event)"
                  [attr.aria-label]="(def.labelKey | translate) + ' max'" [attr.aria-describedby]="'metric-help-' + def.id" />
              </mat-slider>
            </div>
            <span class="text-xs opacity-60 text-right" [class]="def.spanWidth">
              @if ($any(store.filters())[def.minKey] || $any(store.filters())[def.maxKey]) {
                {{ store.filters() | filterDisplay:def }}
              } @else {
                {{ I18N.gallery.sidebar.any | translate }}
              }
            </span>
          </div>
        </div>
      </ng-template>
    </div>
    </mat-tab-nav-panel>


    <!-- Save as smart album (pinned footer, shown only when relevant) -->
    @if (store.config()?.features?.show_albums && auth.isEdition() && store.activeFilterCount() > 0 && !store.filters().album_id) {
      <div class="shrink-0 px-2 py-2 border-t border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface)]">
        <button mat-stroked-button class="w-full" [matTooltip]="I18N.albums.save_smart_tooltip | translate" (click)="saveAsSmartAlbum()">
          <mat-icon>bookmark_add</mat-icon>
          {{ I18N.albums.save_smart | translate }}
        </button>
      </div>
    }
  `,
})
export class GalleryFilterSidebarComponent {
  protected readonly I18N = i18nKeys();
  readonly store = inject(GalleryStore);
  readonly auth = inject(AuthService);
  private dialog = inject(MatDialog);
  private albumService = inject(AlbumService);
  readonly albums = signal<Album[]>([]);
  readonly sectionStates = signal<Record<string, boolean>>(loadSectionStates());
  readonly activeTab = signal<SidebarTabId>(loadActiveTab());
  private readonly scrollArea = viewChild<ElementRef<HTMLElement>>('scrollArea');
  private readonly coarsePointer = useCoarsePointerSignal();
  readonly sliderConfig = computed(() => this.store.config()?.display?.thumbnail_slider ?? null);

  protected readonly SEARCH_THRESHOLD_MAX = SEARCH_THRESHOLD_MAX;

  /** MatSlider's own `aria-valuetext` host binding wins over an `[attr.]` one on
   *  the thumb, so the unit has to come through `displayWith` -- a bare "5" is
   *  what a screen reader announced otherwise. */
  protected readonly formatThresholdPercent = (value: number): string => `${value}%`;

  /** Open the hover-button customiser: reorder and show/hide what the photo
   *  cards' top row offers. Writes go through CardActionsService on save. */
  protected openCardActionsDialog(): void {
    this.dialog.open(CardActionsDialogComponent, { width: '26rem', autoFocus: false });
  }

  /** The value being dragged right now, before the 400ms debounce commits it.
   *
   *  Without it the percent readout reads the committed filter, so it stays
   *  frozen at the old number for the whole drag and only catches up 400ms
   *  after the thumb is released -- the slider looked dead while in use. */
  private readonly thresholdDraft = signal<number | null>(null);

  /** Numeric mirror of the string filter for the `<input matSliderThumb [value]>`
   *  binding, and for the percent readout next to it -- a computed, never a
   *  template method call (per project rule).
   *
   *  Unseeded ('') must NOT render as 0: the server only omits `threshold`
   *  entirely when the client sends nothing, then gates at its own calibrated
   *  default (`config.search_threshold_default`) -- so the thumb and readout
   *  fall back to that same effective value rather than lying about a 0%
   *  gate. Falls back to 0 only if config itself hasn't loaded yet. */
  protected readonly searchThresholdValue = computed(() => {
    const draft = this.thresholdDraft();
    if (draft !== null) return draft;
    const raw = this.store.filters().search_threshold;
    if (raw) return Number(raw);
    const seeded = seededSearchThreshold(this.store.config()?.search_threshold_default);
    return seeded ? Number(seeded) : 0;
  });

  /**
   * Lowest card width the thumbnail slider offers.
   *
   * On a touch device the server minimum is below the mobile column floor for
   * the whole of the slider's travel, so every stop renders the same 3 columns
   * and the control is inert; MOBILE_MIN_CARD_WIDTH_PX is the first width that
   * clears the floor on a 390px screen. A mouse-driven window keeps the server's
   * minimum: there the floor never applies and the existing travel already works.
   */
  readonly thumbnailSliderMin = computed(() => {
    const configured = this.sliderConfig()?.min_px ?? MOBILE_MIN_CARD_WIDTH_PX;
    return this.coarsePointer.isCoarsePointer()
      ? Math.min(configured, MOBILE_MIN_CARD_WIDTH_PX)
      : configured;
  });

  // Person autocomplete (multi-select with search)
  readonly sidebarPersonQuery = signal('');
  private readonly sidebarPersonInput = viewChild<ElementRef<HTMLInputElement>>('sidebarPersonInput');

  readonly selectedPersonIds = computed(() => {
    const raw = this.store.filters().person_id;
    return raw ? raw.split(',') : [];
  });

  readonly selectedPersons = computed(() => {
    const ids = new Set(this.selectedPersonIds());
    if (!ids.size) return [];
    return this.store.persons().filter(p => ids.has(String(p.id)));
  });

  readonly filteredPersons = computed(() => {
    const query = this.sidebarPersonQuery().toLowerCase().trim();
    const selected = new Set(this.selectedPersonIds());
    const all = this.store.persons().filter(p => !selected.has(String(p.id)));
    if (!query) return all;
    return all.filter(p => p.name?.toLowerCase().includes(query));
  });

  removePersonChip(id: number): void {
    const ids = this.selectedPersonIds().filter(pid => pid !== String(id));
    this.store.updateFilter('person_id', ids.join(','));
  }

  onSidebarPersonSelected(event: MatAutocompleteSelectedEvent): void {
    const id = String(event.option.value);
    const current = this.selectedPersonIds();
    if (!current.includes(id)) {
      this.store.updateFilter('person_id', [...current, id].join(','));
    }
    this.sidebarPersonQuery.set('');
    const el = this.sidebarPersonInput()?.nativeElement;
    if (el) el.value = '';
  }

  readonly currentFolderName = computed(() => folderDisplayName(this.store.filters().path_prefix));

  readonly sectionIcons = SECTION_ICONS;
  private i18n = inject(I18nService);

  // Quality tiers (on-the-fly, derived server-side from aggregate thresholds).
  readonly qualityTiers = ['excellent', 'good', 'fair', 'poor'] as const;

  // Representative swatch colour per hue bucket (mid-hue, full saturation).
  readonly hueSwatches: Record<string, string> = {
    red: '#e53935', orange: '#fb8c00', yellow: '#fdd835', green: '#43a047',
    cyan: '#00acc1', blue: '#1e88e5', purple: '#8e24aa', magenta: '#d81b60',
  };


  toggleHueBucket(value: string): void {
    const current = this.store.filters().hue_bucket;
    this.store.updateFilter('hue_bucket', current === value ? '' : value);
  }

  readonly filterQuery = signal('');

  private readonly translatedDefs = computed(() => {
    this.i18n.translations();
    const m: Record<string, { label: string; section: string }> = {};
    for (const d of ADDITIONAL_FILTERS) {
      m[d.id] = { label: this.i18n.t(d.labelKey).toLowerCase(), section: this.i18n.t(d.sectionKey).toLowerCase() };
    }
    return m;
  });

  private clampDef(def: AdditionalFilterDef): AdditionalFilterDef {
    const r = this.store.metricRanges()[def.minKey];
    if (!r) return def;
    let lo = Number((Math.floor(r.min / def.step + 1e-9) * def.step).toFixed(6));
    let hi = Number((Math.ceil(r.max / def.step - 1e-9) * def.step).toFixed(6));
    if (!(hi > lo)) return def;
    // Never clamp away an active filter value: if a persisted/URL value sits
    // outside the data-driven bounds, widen the bounds so the slider can still
    // represent and reach it. Otherwise the thumb pins to the edge while the
    // effective filter (and its display text + active-count badge) keep the old
    // out-of-range value, with no way to drag back to it.
    const f = this.store.filters() as unknown as Record<string, unknown>;
    const activeMin = Number(f[def.minKey]);
    const activeMax = Number(f[def.maxKey]);
    if (f[def.minKey] && Number.isFinite(activeMin)) lo = Math.min(lo, activeMin);
    if (f[def.maxKey] && Number.isFinite(activeMax)) hi = Math.max(hi, activeMax);
    return { ...def, sliderMin: lo, sliderMax: hi };
  }

  /** Filters whose metric the licensing policy hides (commercial mode) are dropped entirely. */
  private readonly filtersBySection = computed((): Record<string, AdditionalFilterDef[]> => {
    const hidden = unavailableSet(this.store.config()?.unavailable_metrics);
    if (!hidden.size) return FILTERS_BY_SECTION;
    return Object.fromEntries(
      Object.entries(FILTERS_BY_SECTION).map(([k, defs]) => [k, defs.filter(d => !isUnavailableKey(d.minKey, hidden))])
    );
  });

  private matchGroups(order: string[]): FilterGroup[] {
    const bySection = this.filtersBySection();
    const q = this.filterQuery().trim().toLowerCase();
    const tr = q ? this.translatedDefs() : null;
    const out: FilterGroup[] = [];
    for (const sectionKey of order) {
      const all = bySection[sectionKey];
      let defs = all;
      if (q && tr) {
        const sectionMatches = all.length > 0 && tr[all[0].id].section.includes(q);
        defs = sectionMatches ? all : all.filter(d => tr[d.id].label.includes(q));
      }
      if (!defs.length) continue;
      out.push({ sectionKey, filters: defs.map(d => this.clampDef(d)) });
    }
    return out;
  }

  readonly commonFilterGroups = computed(() => this.matchGroups(COMMON_SECTION_ORDER));
  readonly advancedFilterGroups = computed(() => this.matchGroups(ADVANCED_SECTION_ORDER));
  readonly metricFilterGroups = computed(() => [...this.commonFilterGroups(), ...this.advancedFilterGroups()]);
  readonly noFilterMatches = computed(() => !!this.filterQuery().trim() && this.metricFilterGroups().length === 0);

  readonly qualityAdvancedGroups = computed(() => this.advancedFilterGroups().filter(g => TAB_SECTIONS.quality.includes(g.sectionKey)));
  readonly subjectGroups = computed(() => this.advancedFilterGroups().filter(g => TAB_SECTIONS.subject.includes(g.sectionKey)));
  readonly ratingMin = computed(() => Number(this.store.filters().min_star_rating) || 0);
  private readonly ratingMax = computed(() => Number(this.store.filters().max_star_rating) || 0);
  /** The minimum the next click sets: one more star, and nothing (off) after 5 or after a max bound. */
  private readonly ratingNext = computed(() => {
    const next = Math.floor(this.ratingMin()) + 1;
    if (next > 5 || (this.ratingMax() && next > this.ratingMax())) return 0;
    return next;
  });
  /** "≤ 4" when a max bound came in from a link or smart album (the button only sets the min). */
  readonly ratingMaxLabel = computed(() => this.ratingMax() ? `≤ ${this.ratingMax()}` : '');
  /** The sentence for the button's tooltip and accessible name: the current state, and what a click does. */
  readonly ratingKey = computed(() => {
    const rv = this.I18N.gallery.sidebar.review;
    if (this.ratingMin() === 0) return rv.rating_off;
    if (this.ratingNext() === 0) return rv.rating_last;
    return rv.rating_step;
  });
  readonly ratingVars = computed(() => ({ count: this.ratingMin(), next: this.ratingNext() }));

  /**
   * The Review tab's menu rows: the decision first, then the sets. A stale "hide"
   * and "only" together read as "only", as the server treats them.
   */
  readonly reviewRows = computed((): SegmentRow[] => {
    const f = this.store.filters();
    const I18N = this.I18N;
    const rv = I18N.gallery.sidebar.review;
    const vals = rv.values;
    const desc = rv.desc;
    const help = I18N.gallery.sidebar.refine_help;
    const triState = (only: boolean, hide: boolean, fallback: string): string => {
      if (only) return 'only';
      if (hide) return 'hide';
      return fallback;
    };
    const rows: Omit<SegmentRow, 'valueLabelKey'>[] = [
      {
        id: 'decision', icon: 'rule', labelKey: rv.decision, helpKey: help.review_status,
        value: f.review_status || 'all', disabled: false,
        options: [
          { value: 'all', labelKey: vals.all, descKey: desc.decision_all },
          { value: 'undecided', labelKey: vals.undecided, descKey: desc.decision_undecided },
          { value: 'kept', labelKey: vals.kept, descKey: desc.decision_kept },
          { value: 'rejected', labelKey: vals.rejected, descKey: desc.decision_rejected },
        ],
      },
      {
        id: 'bursts', icon: 'burst_mode', labelKey: rv.bursts, helpKey: help.hide_bursts,
        value: f.hide_bursts ? 'best' : 'all', disabled: false,
        options: [
          { value: 'best', labelKey: vals.best_frame, descKey: desc.bursts_best },
          { value: 'all', labelKey: vals.all_frames, descKey: desc.bursts_all },
        ],
      },
      {
        id: 'duplicates', icon: 'content_copy', labelKey: rv.duplicates, helpKey: help.hide_duplicates,
        value: triState(f.duplicates_only, f.hide_duplicates, 'all'), disabled: false,
        options: [
          { value: 'hide', labelKey: vals.hidden, descKey: desc.duplicates_hide },
          { value: 'all', labelKey: vals.shown, descKey: desc.duplicates_show },
          { value: 'only', labelKey: vals.only_these, descKey: desc.duplicates_only },
        ],
      },
      {
        id: 'blinks', icon: 'visibility_off', labelKey: rv.blinks, helpKey: help.hide_blinks,
        value: triState(f.blinks_only, f.hide_blinks, 'all'), disabled: false,
        options: [
          { value: 'hide', labelKey: vals.hidden, descKey: desc.blinks_hide },
          { value: 'all', labelKey: vals.shown, descKey: desc.blinks_show },
          { value: 'only', labelKey: vals.only_these, descKey: desc.blinks_only },
        ],
      },
      {
        id: 'brackets', icon: 'exposure', labelKey: rv.brackets, helpKey: help.hide_brackets,
        value: f.hide_brackets ? 'base' : 'all', disabled: false,
        options: [
          { value: 'base', labelKey: vals.base_exposure, descKey: desc.brackets_base },
          { value: 'all', labelKey: vals.all_frames, descKey: desc.brackets_all },
        ],
      },
      {
        id: 'panoramas', icon: 'panorama', labelKey: rv.panoramas, helpKey: help.hide_panoramas,
        value: f.hide_panoramas ? 'lead' : 'all', disabled: false,
        options: [
          { value: 'lead', labelKey: vals.middle_frame, descKey: desc.panoramas_middle },
          { value: 'all', labelKey: vals.all_frames, descKey: desc.panoramas_all },
        ],
      },
      {
        id: 'rejected', icon: 'block', labelKey: rv.rejected, helpKey: help.hide_rejected,
        value: triState(f.show_rejected, f.hide_rejected, 'show'), disabled: !!f.review_status,
        options: [
          { value: 'hide', labelKey: vals.hidden, descKey: desc.rejected_hide },
          { value: 'show', labelKey: vals.shown, descKey: desc.rejected_show },
          { value: 'only', labelKey: vals.only_rejected, descKey: desc.rejected_only },
        ],
      },
    ];
    return rows.map(row => ({ ...row, valueLabelKey: row.options.find(o => o.value === row.value)?.labelKey ?? row.options[0].labelKey }));
  });


  onSegment(row: SegmentRowId, value: string): void {
    if (row === 'decision') void this.store.updateFilter('review_status', value === 'all' ? '' : value as GalleryFilters['review_status']);
    else void this.store.updateFilters(SEGMENT_PATCHES[row][value]);
  }

  /** Each click raises the minimum star rating by one; the click after 5 clears it. */
  cycleRating(): void {
    const next = this.ratingNext();
    void this.store.updateFilter('min_star_rating', next ? String(next) : '');
  }

  readonly qualityGroups = computed(() => this.commonFilterGroups().filter(g => g.sectionKey === 'gallery.sidebar.quality'));

  /** Active controls per panel, from `UNIT_PANEL`; a range counts once. Hidden metrics never count. */
  readonly sectionActiveCounts = computed((): Record<string, number> => {
    const bySection = this.filtersBySection();
    const counts: Record<string, number> = {};
    for (const panels of Object.values(TAB_SECTIONS)) for (const panel of panels) counts[panel] = 0;
    for (const unit of activeFilterUnits(this.store.filters())) {
      const panel = UNIT_PANEL[unit];
      if (!panel) continue;
      if (bySection[panel] && !bySection[panel].some(d => filterUnit(d.minKey) === unit)) continue;
      counts[panel]++;
    }
    return counts;
  });

  /** Each tab's badge: the sum of its panels' counts. */
  readonly tabActiveCounts = computed((): Record<SidebarTabId, number> => {
    const counts = this.sectionActiveCounts();
    return Object.fromEntries(
      TAB_IDS.map(id => [id, TAB_SECTIONS[id].reduce((sum, panel) => sum + (counts[panel] ?? 0), 0)]),
    ) as Record<SidebarTabId, number>;
  });

  /** Active controls outside every panel (the filename search, similar-to): header-only. */
  readonly fixedAreaCount = computed(() => activeFilterUnits(this.store.filters()).filter(unit => !UNIT_PANEL[unit]).length);

  /** The header badge and Reset: every active control, a hidden metric's included, so Reset can always clear it. */
  readonly totalActiveCount = computed(() => countActiveFilters(this.store.filters()));

  readonly tabItems = computed(() => TAB_IDS.map(id => ({
    id,
    icon: TAB_ICONS[id],
    labelKey: this.I18N.gallery.sidebar.tabs[id],
    count: this.tabActiveCounts()[id],
    active: this.activeTab() === id,
  })));

  selectTab(id: SidebarTabId): void {
    if (id === this.activeTab()) return;
    this.activeTab.set(id);
    writeStored(SIDEBAR_TAB_KEY, id);
    this.sidebarPersonQuery.set('');
    const el = this.scrollArea()?.nativeElement;
    if (el) el.scrollTop = 0;
  }

  onSectionToggle(sectionId: string, isOpen: boolean): void {
    this.sectionStates.update(s => {
      const next = { ...s, [sectionId]: isOpen };
      saveSectionStates(next);
      return next;
    });
  }

  onDynamicRangeChange(def: AdditionalFilterDef, side: 'min' | 'max', value: number): void {
    const { key, value: filterValue } = computeRangeFilterUpdate(
      def, side, value, (this.store.filters() as Record<string, any>)[def.minKey],
    );
    this.store.updateFilterDebounced(key as 'min_score', filterValue);
  }

  onDateChange(key: 'date_from' | 'date_to', event: MatDatepickerInputEvent<Date>): void {
    this.store.updateFilter(key, toIsoDateString(event.value));
  }

  private readonly semanticSearchInput = viewChild<ElementRef<HTMLInputElement>>('semanticSearchInput');
  private searchTimeout: ReturnType<typeof setTimeout> | null = null;
  // Kept separate from searchTimeout so a slider drag can't cancel a pending
  // text search (or vice versa) -- they debounce independent filter keys.
  private thresholdTimeout: ReturnType<typeof setTimeout> | null = null;
  // The filename box's own debounce: sharing searchTimeout with the semantic
  // box let a keystroke in one cancel the other's pending update.
  private filenameTimeout: ReturnType<typeof setTimeout> | null = null;
  private albumsLoaded = false;

  constructor() {
    this.coarsePointer.setup();
    effect(() => {
      if (this.store.config()?.features?.show_albums && !this.albumsLoaded) {
        this.albumsLoaded = true;
        this.refreshAlbums();
      }
    });
    inject(DestroyRef).onDestroy(() => {
      this.cancelPendingSearch();
      if (this.filenameTimeout) clearTimeout(this.filenameTimeout);
      this.coarsePointer.cleanup();
    });
  }

  private readonly tooltips = viewChildren(MatTooltip);
  private readonly selects = viewChildren(MatSelect);
  private readonly menuTriggers = viewChildren(MatMenuTrigger);

  /** Hide every tooltip the sidebar owns, for a gallery parking behind a photo page. */
  hideTooltips(): void {
    closeOverlayDirectives(this.tooltips());
  }

  /** Close overlays before the gallery parks behind a photo. */
  closeOverlays(): void {
    closeOverlayDirectives(this.tooltips(), this.menuTriggers(), this.selects());
  }

  cancelPendingSearch(): void {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    if (this.thresholdTimeout) clearTimeout(this.thresholdTimeout);
    this.searchTimeout = null;
    this.thresholdTimeout = null;
    this.thresholdDraft.set(null);
    const input = this.semanticSearchInput()?.nativeElement;
    if (input) input.value = this.store.filters().semanticQuery;
  }

  private refreshAlbums(): void {
    firstValueFrom(this.albumService.list()).then(res =>
      this.albums.set(res.albums),
    ).catch(() => {});
  }

  private readonly sidebarSearch = viewChild<ElementRef<HTMLInputElement>>('sidebarSearch');

  /** The `/` shortcut's target when the toolbar search is hidden (below 1360 px). */
  focusSearch(): void {
    const input = this.sidebarSearch()?.nativeElement;
    input?.focus();
    input?.select();
  }

  onSidebarSearchChange(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    // Debounced live filtering on every keystroke: waiting for Enter/blur
    // made typing feel dead, with the grid frozen and no hint that a commit
    // was pending. Enter still commits immediately through the same path.
    if (this.filenameTimeout) clearTimeout(this.filenameTimeout);
    this.filenameTimeout = setTimeout(() => {
      this.filenameTimeout = null;
      this.store.updateFilter('search', value);
    }, 400);
  }

  onSidebarSearchCommit(event: Event): void {
    if (this.filenameTimeout) {
      clearTimeout(this.filenameTimeout);
      this.filenameTimeout = null;
    }
    this.store.updateFilter('search', (event.target as HTMLInputElement).value);
  }

  onSemanticSearch(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.searchTimeout = setTimeout(() => {
      this.store.updateFilter('semanticQuery', value);
    }, 400);
  }

  onSearchThresholdChange(value: number): void {
    this.thresholdDraft.set(value);
    if (this.thresholdTimeout) clearTimeout(this.thresholdTimeout);
    this.thresholdTimeout = setTimeout(() => {
      this.thresholdTimeout = null;
      this.thresholdDraft.set(null);
      this.store.updateFilter('search_threshold', String(value));
    }, 400);
  }

  openGpsFilterMap(): void {
    import('./gps-filter-map-dialog.component').then(m => {
      const ref = this.dialog.open(m.GpsFilterMapDialogComponent, {
        width: '95vw',
        maxWidth: '600px',
        data: {
          lat: this.store.filters().gps_lat ? +this.store.filters().gps_lat : undefined,
          lng: this.store.filters().gps_lng ? +this.store.filters().gps_lng : undefined,
          radius_km: this.store.filters().gps_radius_km ? +this.store.filters().gps_radius_km : undefined,
        },
      });
      ref.afterClosed().subscribe(result => {
        if (result) {
          this.store.updateFilters({
            no_gps: '',
            gps_lat: String(result.lat),
            gps_lng: String(result.lng),
            gps_radius_km: String(result.radius_km),
          });
        }
      });
    });
  }

  clearGpsFilter(): void {
    this.store.updateFilters({ gps_lat: '', gps_lng: '', gps_radius_km: '' });
  }

  openFolderPicker(): void {
    import('./folder-picker-dialog.component').then(m => {
      const ref = this.dialog.open(m.FolderPickerDialogComponent, {
        width: '95vw',
        maxWidth: '600px',
        data: { path_prefix: this.store.filters().path_prefix },
      });
      ref.afterClosed().subscribe((result?: string) => {
        if (result !== undefined && result !== this.store.filters().path_prefix) {
          this.store.updateFilter('path_prefix', result);
        }
      });
    });
  }

  clearFolderFilter(): void {
    this.store.updateFilter('path_prefix', '');
  }

  saveAsSmartAlbum(): void {
    const ref = this.dialog.open(SaveSmartAlbumDialogComponent, {
      width: '400px',
      data: { filterJson: smartAlbumFilterJson(this.store.filters()) },
    });
    ref.afterClosed().subscribe(result => {
      if (result) {
        this.refreshAlbums();
      }
    });
  }
}
