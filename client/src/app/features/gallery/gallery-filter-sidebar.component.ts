import { Component, computed, DestroyRef, ElementRef, inject, signal, viewChild } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatSelectModule } from '@angular/material/select';
import { MatSliderModule } from '@angular/material/slider';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatDatepickerModule, MatDatepickerInputEvent } from '@angular/material/datepicker';
import { toIsoDateString } from '../../shared/utils/date-format';
import { MatAutocompleteModule, MatAutocompleteSelectedEvent } from '@angular/material/autocomplete';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { GalleryStore, SMART_ALBUM_EXCLUDE_KEYS } from './gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FilterDisplayPipe } from '../../shared/pipes/filter-display.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { AdditionalFilterDef } from '../../shared/models/filter-def.model';
import { computeRangeFilterUpdate } from '../../shared/utils/range-filter';
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { SaveSmartAlbumDialogComponent } from '../albums/save-smart-album-dialog.component';
import { I18N } from '../../core/i18n/keys';

export const ADDITIONAL_FILTERS: AdditionalFilterDef[] = [
  // Quality
  { id: 'score_range', labelKey: 'gallery.score_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_score', maxKey: 'max_score', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'aesthetic_range', labelKey: 'gallery.aesthetic_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_aesthetic', maxKey: 'max_aesthetic', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'quality_score_range', labelKey: 'gallery.quality_score_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_quality_score', maxKey: 'max_quality_score', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  // Extended Quality
  { id: 'aesthetic_iaa_range', labelKey: 'gallery.aesthetic_iaa_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_aesthetic_iaa', maxKey: 'max_aesthetic_iaa', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'face_quality_iqa_range', labelKey: 'gallery.face_quality_iqa_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_face_quality_iqa', maxKey: 'max_face_quality_iqa', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'liqe_range', labelKey: 'gallery.liqe_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_liqe', maxKey: 'max_liqe', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'qalign_range', labelKey: 'gallery.qalign_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_qalign', maxKey: 'max_qalign', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'aesthetic_v25_range', labelKey: 'gallery.aesthetic_v25_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_aesthetic_v25', maxKey: 'max_aesthetic_v25', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'deqa_range', labelKey: 'gallery.deqa_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_deqa', maxKey: 'max_deqa', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  // Face Metrics
  { id: 'face_count_range', labelKey: 'gallery.face_count_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_count', maxKey: 'max_face_count', sliderMin: 0, sliderMax: 20, step: 1, spanWidth: 'w-16' },
  { id: 'face_quality_range', labelKey: 'gallery.face_quality_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_quality', maxKey: 'max_face_quality', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'eye_sharpness_range', labelKey: 'gallery.eye_sharpness_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_eye_sharpness', maxKey: 'max_eye_sharpness', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'face_sharpness_range', labelKey: 'gallery.face_sharpness_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_sharpness', maxKey: 'max_face_sharpness', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'face_ratio_range', labelKey: 'gallery.face_ratio_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_ratio', maxKey: 'max_face_ratio', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  { id: 'face_confidence_range', labelKey: 'gallery.face_confidence_range', sectionKey: 'gallery.sidebar.face', minKey: 'min_face_confidence', maxKey: 'max_face_confidence', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  // Composition
  { id: 'composition_range', labelKey: 'gallery.composition_range', sectionKey: 'gallery.sidebar.composition', minKey: 'min_composition', maxKey: 'max_composition', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'power_point_range', labelKey: 'gallery.power_point_range', sectionKey: 'gallery.sidebar.composition', minKey: 'min_power_point', maxKey: 'max_power_point', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'leading_lines_range', labelKey: 'gallery.leading_lines_range', sectionKey: 'gallery.sidebar.composition', minKey: 'min_leading_lines', maxKey: 'max_leading_lines', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'isolation_range', labelKey: 'gallery.isolation_range', sectionKey: 'gallery.sidebar.composition', minKey: 'min_isolation', maxKey: 'max_isolation', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  // Subject Saliency
  { id: 'subject_sharpness_range', labelKey: 'gallery.subject_sharpness_range', sectionKey: 'gallery.sidebar.saliency', minKey: 'min_subject_sharpness', maxKey: 'max_subject_sharpness', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'subject_prominence_range', labelKey: 'gallery.subject_prominence_range', sectionKey: 'gallery.sidebar.saliency', minKey: 'min_subject_prominence', maxKey: 'max_subject_prominence', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'subject_placement_range', labelKey: 'gallery.subject_placement_range', sectionKey: 'gallery.sidebar.saliency', minKey: 'min_subject_placement', maxKey: 'max_subject_placement', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'bg_separation_range', labelKey: 'gallery.bg_separation_range', sectionKey: 'gallery.sidebar.saliency', minKey: 'min_bg_separation', maxKey: 'max_bg_separation', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },

  { id: 'moment_confidence_range', labelKey: 'gallery.moment_confidence_range', sectionKey: 'gallery.sidebar.moments', minKey: 'min_moment_confidence', maxKey: 'max_moment_confidence', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  // Technical
  { id: 'sharpness_range', labelKey: 'gallery.sharpness_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_sharpness', maxKey: 'max_sharpness', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'exposure_range', labelKey: 'gallery.exposure_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_exposure', maxKey: 'max_exposure', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'color_range', labelKey: 'gallery.color_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_color', maxKey: 'max_color', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'contrast_range', labelKey: 'gallery.contrast_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_contrast', maxKey: 'max_contrast', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'saturation_range', labelKey: 'gallery.saturation_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_saturation', maxKey: 'max_saturation', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  { id: 'noise_range', labelKey: 'gallery.noise_range', sectionKey: 'gallery.sidebar.technical', minKey: 'min_noise', maxKey: 'max_noise', sliderMin: 0, sliderMax: 20, step: 0.5, spanWidth: 'w-16' },
  // Exposure & Range
  { id: 'dynamic_range', labelKey: 'gallery.dynamic_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_dynamic_range', maxKey: 'max_dynamic_range', sliderMin: 0, sliderMax: 15, step: 0.5, displaySuffix: ' EV', spanWidth: 'w-16' },
  { id: 'luminance_range', labelKey: 'gallery.luminance_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_luminance', maxKey: 'max_luminance', sliderMin: 0, sliderMax: 1, step: 0.01, spanWidth: 'w-16' },
  { id: 'histogram_range', labelKey: 'gallery.histogram_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_histogram_spread', maxKey: 'max_histogram_spread', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'iso_range', labelKey: 'gallery.iso_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_iso', maxKey: 'max_iso', sliderMin: 50, sliderMax: 25600, step: 50, spanWidth: 'w-20' },
  { id: 'aperture_range', labelKey: 'gallery.aperture_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_aperture', maxKey: 'max_aperture', sliderMin: 0.7, sliderMax: 64, step: 0.1, displayPrefix: 'f/', spanWidth: 'w-20' },
  { id: 'focal_range', labelKey: 'gallery.focal_range', sectionKey: 'gallery.sidebar.exposure_range', minKey: 'min_focal_length', maxKey: 'max_focal_length', sliderMin: 1, sliderMax: 1200, step: 1, displaySuffix: 'mm', spanWidth: 'w-24' },
  // User Ratings
  { id: 'star_rating_range', labelKey: 'gallery.star_rating_range', sectionKey: 'gallery.sidebar.ratings', minKey: 'min_star_rating', maxKey: 'max_star_rating', sliderMin: 0, sliderMax: 5, step: 1, spanWidth: 'w-16' },
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

const SIDEBAR_SECTIONS_KEY = 'facet_sidebar_sections';
// One-time cleanup of legacy localStorage key from v3.x.
try { localStorage.removeItem('facet_active_filters'); } catch { /* ignore */ }

function loadSectionStates(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(SIDEBAR_SECTIONS_KEY);
    if (raw) return JSON.parse(raw) as Record<string, boolean>;
  } catch { /* ignore */ }
  return {};
}

function saveSectionStates(states: Record<string, boolean>): void {
  try {
    localStorage.setItem(SIDEBAR_SECTIONS_KEY, JSON.stringify(states));
  } catch { /* ignore */ }
}

@Component({
  selector: 'app-gallery-filter-sidebar',
  standalone: true,
  host: { class: 'flex flex-col h-full' },
  imports: [
    DecimalPipe,
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
    MatAutocompleteModule,
    MatExpansionModule,
    MatDatepickerModule,
    MatDialogModule,
    TranslatePipe,
    FilterDisplayPipe,
    PersonThumbnailUrlPipe,
  ],
  template: `
<div data-scroll class="flex-1 min-h-0 overflow-y-auto px-2 pb-4">

      <div class="sticky top-0 z-20 -mx-2 px-2 pt-3 pb-2 bg-[var(--mat-sys-surface)] flex items-center gap-2">
        <span class="text-sm font-medium opacity-80">{{ I18N.gallery.filters | translate }}</span>
        @if (store.activeFilterCount()) {
          <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ store.activeFilterCount() }}</span>
          <button mat-button class="!ml-auto !min-w-0 !px-2 !text-xs" (click)="store.resetFilters()">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">close</mat-icon>
            {{ I18N.gallery.reset_filters | translate }}
          </button>
        }
      </div>

      <!-- Find a filter -->
      <mat-form-field subscriptSizing="dynamic" class="w-full !mb-1">
        <mat-icon matPrefix class="mr-1 opacity-60">manage_search</mat-icon>
        <input matInput [placeholder]="I18N.gallery.sidebar.find_filter | translate"
               [attr.aria-label]="I18N.gallery.sidebar.find_filter | translate"
               [value]="filterQuery()" (input)="filterQuery.set($any($event.target).value)" />
        @if (filterQuery()) {
          <button matSuffix mat-icon-button class="!w-6 !h-6 !p-0" (click)="filterQuery.set('')">
            <mat-icon class="!text-sm !w-4 !h-4">close</mat-icon>
          </button>
        }
      </mat-form-field>

      @if (filterQuery().trim()) {
        @if (noFilterMatches()) {
          <p class="text-xs opacity-50 px-2 py-3">{{ I18N.gallery.sidebar.no_filters_match | translate }}</p>
        }
        @for (group of searchResultGroups(); track group.sectionKey) {
          <div class="px-1 pt-2 pb-1">
            <div class="flex items-center gap-2 text-xs font-medium opacity-70 mb-1">
              <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-60">{{ sectionIcons[group.sectionKey] || 'tune' }}</mat-icon>
              {{ group.sectionKey | translate }}
            </div>
            @for (def of group.filters; track def.id) {
              <ng-container [ngTemplateOutlet]="metricRow" [ngTemplateOutletContext]="{ $implicit: def }" />
            }
          </div>
        }
      } @else {

      <!-- Semantic Search (top of sidebar) -->
      @if (store.config()?.features?.show_semantic_search) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['semantic'] === true"
                             (opened)="onSectionToggle('semantic', true)"
                             (closed)="onSectionToggle('semantic', false)"
                             [style.background-color]="sectionStates()['semantic'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header>
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">image_search</mat-icon>
              {{ I18N.gallery.sidebar.semantic_search | translate }}
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            <mat-form-field subscriptSizing="dynamic" class="w-full">
              <mat-label>{{ I18N.gallery.semantic_search | translate }}</mat-label>
              <mat-icon matPrefix class="mr-1 opacity-60">image_search</mat-icon>
              <input matInput
                [value]="store.filters().semanticQuery"
                (input)="onSemanticSearch($event)"
                [placeholder]="I18N.gallery.semantic_search_placeholder | translate" />
              @if (store.filters().semanticQuery) {
                <button matSuffix mat-icon-button class="!w-6 !h-6 !p-0" (click)="store.updateFilter('semanticQuery', '')">
                  <mat-icon class="!text-sm !w-4 !h-4">close</mat-icon>
                </button>
              }
            </mat-form-field>
            <p class="text-xs opacity-50 px-1">{{ I18N.gallery.semantic_search_info | translate }}</p>
          </div>
        </mat-expansion-panel>
      }

      <!-- Smart album filter notice -->
      @if (store.currentAlbum()?.is_smart && auth.isEdition()) {
        <div class="flex items-start gap-2 rounded-lg bg-[var(--mat-sys-tertiary-container)] text-[var(--mat-sys-on-tertiary-container)] text-xs px-3 py-2 mb-2">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 shrink-0 mt-0.5">info</mat-icon>
          <span>{{ I18N.gallery.sidebar.smart_album_filter_notice | translate }}</span>
        </div>
      }

      <!-- Search (visible below 2xl, hidden on 2xl+ where header search is shown) -->
      <div class="2xl:!hidden mt-4 mb-1">
        <mat-form-field subscriptSizing="dynamic" class="w-full">
          <mat-label>{{ I18N.ui.filters.search | translate }}</mat-label>
          <mat-icon matPrefix class="mr-1 opacity-60">search</mat-icon>
          <input matInput
            [placeholder]="I18N.gallery.search_placeholder | translate"
            [value]="store.filters().search"
            (keyup.enter)="onSidebarSearchChange($event)"
            (blur)="onSidebarSearchChange($event)" />
          @if (store.filters().search) {
            <button matSuffix mat-icon-button class="!w-6 !h-6 !p-0" (click)="store.updateFilter('search', '')">
              <mat-icon class="!text-sm !w-4 !h-4">close</mat-icon>
            </button>
          }
        </mat-form-field>
      </div>

      <!-- Persons -->
      @if (store.persons().length) {
        <mat-expansion-panel class="!mb-1 mt-1" [expanded]="sectionStates()['persons'] !== false"
                             (opened)="onSectionToggle('persons', true)"
                             (closed)="onSectionToggle('persons', false)"
                             [style.background-color]="sectionStates()['persons'] !== false ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header>
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">people</mat-icon>
              {{ I18N.gallery.sidebar.persons | translate }}
              @if (sectionActiveCounts()['persons']) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['persons'] }}</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
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
                  <button class="relative shrink-0 group/person" [matTooltip]="p.name || (I18N.gallery.unknown_person | translate)" (click)="removePersonChip(p.id)">
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
      }

      <!-- Date Range -->
      <mat-expansion-panel class="!mb-1 mt-4" [expanded]="sectionStates()['date'] !== false"
                           (opened)="onSectionToggle('date', true)"
                           (closed)="onSectionToggle('date', false)"
                           [style.background-color]="sectionStates()['date'] !== false ? 'var(--mat-sys-surface-container)' : null">
        <mat-expansion-panel-header>
          <mat-panel-title class="flex items-center gap-2">
            <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">calendar_today</mat-icon>
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
          <mat-expansion-panel-header>
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">label</mat-icon>
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
                <mat-select panelWidth="auto" panelClass="nowrap-panel" [value]="store.filters().type" (selectionChange)="store.updateFilter('type', $event.value)">
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

      <!-- Color & Quality tier -->
      @if (store.colorTemps().length || store.hueBuckets().length || qualityTiers.length) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['color_quality'] === true"
                             (opened)="onSectionToggle('color_quality', true)"
                             (closed)="onSectionToggle('color_quality', false)"
                             [style.background-color]="sectionStates()['color_quality'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header>
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">palette</mat-icon>
              {{ I18N.gallery.sidebar.color_quality | translate }}
              @if (colorQualityActiveCount()) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ colorQualityActiveCount() }}</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
            <!-- Quality tier -->
            <mat-form-field subscriptSizing="dynamic" class="w-full">
              <mat-label>{{ I18N.gallery.quality_tier | translate }}</mat-label>
              <mat-select [value]="store.filters().quality_tier" (selectionChange)="store.updateFilter('quality_tier', $event.value)">
                <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                @for (t of qualityTiers; track t) {
                  <mat-option [value]="t">{{ ('gallery.quality_tiers.' + t) | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <!-- Color temperature -->
            @if (store.colorTemps().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ I18N.gallery.color_temp | translate }}</mat-label>
                <mat-select [value]="store.filters().color_temp" (selectionChange)="store.updateFilter('color_temp', $event.value)">
                  <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                  @for (c of store.colorTemps(); track c.value) {
                    <mat-option [value]="c.value">{{ ('gallery.color_temps.' + c.value) | translate }} ({{ c.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
            <!-- Hue buckets as colour chips -->
            @if (store.hueBuckets().length) {
              <span class="text-xs opacity-60 px-1">{{ I18N.gallery.hue | translate }}</span>
              <div class="flex flex-wrap gap-1.5">
                @for (h of store.hueBuckets(); track h.value) {
                  <button type="button"
                    class="flex items-center gap-1.5 rounded-full pl-1.5 pr-2.5 py-1 text-xs border border-[var(--mat-sys-outline-variant)]"
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

      <!-- Equipment -->
      @if (store.cameras().length || store.lenses().length) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['equipment'] !== false"
                             (opened)="onSectionToggle('equipment', true)"
                             (closed)="onSectionToggle('equipment', false)"
                             [style.background-color]="sectionStates()['equipment'] !== false ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header>
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">photo_camera</mat-icon>
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

      <!-- Refine (result-affecting filters) -->
      <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['refine'] !== false"
                           (opened)="onSectionToggle('refine', true)"
                           (closed)="onSectionToggle('refine', false)"
                           [style.background-color]="sectionStates()['refine'] !== false ? 'var(--mat-sys-surface-container)' : null">
        <mat-expansion-panel-header>
          <mat-panel-title class="flex items-center gap-2">
            <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">filter_alt</mat-icon>
            {{ I18N.gallery.sidebar.refine | translate }}
            @if (sectionActiveCounts()['refine']) {
              <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ sectionActiveCounts()['refine'] }}</span>
            }
          </mat-panel-title>
        </mat-expansion-panel-header>
        <div class="flex flex-col gap-2 pb-2">
          <mat-checkbox
            [checked]="store.filters().hide_blinks"
            (change)="store.updateFilter('hide_blinks', $event.checked)"
          >{{ I18N.gallery.hide_blinks | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().hide_bursts"
            (change)="store.updateFilter('hide_bursts', $event.checked)"
          >{{ I18N.gallery.hide_bursts | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().hide_duplicates"
            (change)="store.updateFilter('hide_duplicates', $event.checked)"
          >{{ I18N.gallery.hide_duplicates | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().hide_rejected"
            (change)="store.updateFilter('hide_rejected', $event.checked)"
          >{{ I18N.gallery.hide_rejected | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().favorites_only"
            (change)="store.updateFilter('favorites_only', $event.checked)"
          >{{ I18N.gallery.favorites_only | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().is_monochrome"
            (change)="store.updateFilter('is_monochrome', $event.checked)"
          >{{ I18N.gallery.monochrome_only | translate }}</mat-checkbox>
        </div>
      </mat-expansion-panel>

      <!-- View (display preferences, not filters) -->
      <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['view'] !== false"
                           (opened)="onSectionToggle('view', true)"
                           (closed)="onSectionToggle('view', false)"
                           [style.background-color]="sectionStates()['view'] !== false ? 'var(--mat-sys-surface-container)' : null">
        <mat-expansion-panel-header>
          <mat-panel-title class="flex items-center gap-2">
            <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">display_settings</mat-icon>
            {{ I18N.gallery.sidebar.view | translate }}
          </mat-panel-title>
        </mat-expansion-panel-header>
        <div class="flex flex-col gap-2 pb-2">
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
          <div class="hidden md:flex items-center gap-2 mt-2">
            <span class="text-sm opacity-70 shrink-0">{{ I18N.gallery.layout_mode | translate }}</span>
            <div class="flex gap-1 ml-auto">
              <button mat-icon-button class="!w-8 !h-8 !p-0 inline-flex items-center justify-center"
                [class.!bg-[var(--mat-sys-primary-container)]]="store.galleryMode() === 'grid'"
                [matTooltip]="I18N.gallery.layout_grid | translate"
                (click)="store.setGalleryMode('grid')">
                <mat-icon class="!text-lg !w-5 !h-5 !leading-5">grid_view</mat-icon>
              </button>
              <button mat-icon-button class="!w-8 !h-8 !p-0 inline-flex items-center justify-center"
                [class.!bg-[var(--mat-sys-primary-container)]]="store.galleryMode() === 'mosaic'"
                [matTooltip]="I18N.gallery.layout_mosaic | translate"
                (click)="store.setGalleryMode('mosaic')">
                <mat-icon class="!text-lg !w-5 !h-5 !leading-5">auto_awesome_mosaic</mat-icon>
              </button>
            </div>
          </div>
          @if (sliderConfig(); as sc) {
            <div class="hidden md:flex items-center gap-2 mt-2">
              <span class="text-sm opacity-70 shrink-0">{{ I18N.gallery.thumbnail_size | translate }}</span>
              <mat-slider [min]="sc.min_px" [max]="sc.max_px" [step]="sc.step_px" class="flex-1">
                <input matSliderThumb [value]="store.cardWidth()" (valueChange)="store.setCardWidth($event)" [attr.aria-label]="I18N.gallery.thumbnail_size | translate" />
              </mat-slider>
              <span class="text-xs opacity-60 w-10 text-right">{{ store.cardWidth() }}px</span>
            </div>
          }
        </div>
      </mat-expansion-panel>

      <!-- Metric filter sections (collapsed by default) -->
      <!-- Albums -->
      @if (store.config()?.features?.show_albums && albums().length) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['albums'] === true"
                             (opened)="onSectionToggle('albums', true)"
                             (closed)="onSectionToggle('albums', false)"
                             [style.background-color]="sectionStates()['albums'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header>
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">photo_album</mat-icon>
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
      @if (store.config()?.features?.show_map) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['location'] === true"
                             (opened)="onSectionToggle('location', true)"
                             (closed)="onSectionToggle('location', false)"
                             [style.background-color]="sectionStates()['location'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header>
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">place</mat-icon>
              {{ I18N.gallery.sidebar.location | translate }}
              @if (store.filters().gps_lat) {
                <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">1</span>
              }
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex flex-col gap-2 pb-2">
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
            <button mat-stroked-button class="w-full" (click)="openGpsFilterMap()">
              <mat-icon>map</mat-icon>
              {{ I18N.gallery.select_on_map | translate }}
            </button>
          </div>
        </mat-expansion-panel>
      }

      <!-- Metric filter sections (collapsed by default) -->
      <!-- Common metric sections -->
      @for (group of commonFilterGroups(); track group.sectionKey) {
        <ng-container [ngTemplateOutlet]="metricPanel" [ngTemplateOutletContext]="{ $implicit: group }" />
      }

      <!-- Advanced metrics (collapsed; nested sections) -->
      <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['advanced'] === true"
                           (opened)="onSectionToggle('advanced', true)"
                           (closed)="onSectionToggle('advanced', false)"
                           [style.background-color]="sectionStates()['advanced'] === true ? 'var(--mat-sys-surface-container)' : null">
        <mat-expansion-panel-header>
          <mat-panel-title class="flex items-center gap-2">
            <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">tune</mat-icon>
            {{ I18N.gallery.sidebar.advanced_metrics | translate }}
            @if (advancedActiveCount()) {
              <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ advancedActiveCount() }}</span>
            }
          </mat-panel-title>
        </mat-expansion-panel-header>
        <div class="flex flex-col gap-1 pb-1">
          @for (group of advancedFilterGroups(); track group.sectionKey) {
            <ng-container [ngTemplateOutlet]="metricPanel" [ngTemplateOutletContext]="{ $implicit: group }" />
          }
        </div>
      </mat-expansion-panel>
      }

      <ng-template #metricPanel let-group>
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()[group.sectionKey] === true"
                             (opened)="onSectionToggle(group.sectionKey, true)"
                             (closed)="onSectionToggle(group.sectionKey, false)"
                             [style.background-color]="sectionStates()[group.sectionKey] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header>
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">{{ sectionIcons[group.sectionKey] || 'tune' }}</mat-icon>
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
        <div class="flex flex-col gap-0">
          <span class="text-xs opacity-60 px-1">{{ def.labelKey | translate }}</span>
          <div class="flex items-center gap-1">
            <div class="flex-1 flex flex-col">
              @if (metricHistograms()[def.minKey]; as bars) {
                <div class="flex items-end gap-px h-3 px-2" aria-hidden="true">
                  @for (h of bars; track $index) {
                    <span class="flex-1 rounded-sm bg-[var(--mat-sys-primary)] opacity-25" [style.height.%]="h"></span>
                  }
                </div>
              }
              <mat-slider [min]="def.sliderMin" [max]="def.sliderMax" [step]="def.step" class="w-full">
                <input matSliderStartThumb
                  [value]="$any(store.filters())[def.minKey] ? +$any(store.filters())[def.minKey] : def.sliderMin"
                  (valueChange)="onDynamicRangeChange(def, 'min', $event)"
                  [attr.aria-label]="(def.labelKey | translate) + ' min'" />
                <input matSliderEndThumb
                  [value]="$any(store.filters())[def.maxKey] ? +$any(store.filters())[def.maxKey] : def.sliderMax"
                  (valueChange)="onDynamicRangeChange(def, 'max', $event)"
                  [attr.aria-label]="(def.labelKey | translate) + ' max'" />
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

    <!-- Save as smart album (pinned footer, shown only when relevant) -->
    @if (store.config()?.features?.show_albums && auth.isEdition() && store.activeFilterCount() > 0 && !store.filters().album_id) {
      <div class="shrink-0 px-2 py-2 border-t border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface)]">
        <button mat-stroked-button class="w-full" (click)="saveAsSmartAlbum()">
          <mat-icon>bookmark_add</mat-icon>
          {{ I18N.albums.save_smart | translate }}
        </button>
      </div>
    }
  `,
})
export class GalleryFilterSidebarComponent {
  protected readonly I18N = I18N;
  readonly store = inject(GalleryStore);
  readonly auth = inject(AuthService);
  private dialog = inject(MatDialog);
  private albumService = inject(AlbumService);
  readonly albums = signal<Album[]>([]);
  readonly sectionStates = signal<Record<string, boolean>>(loadSectionStates());
  readonly sliderConfig = computed(() => this.store.config()?.display?.thumbnail_slider ?? null);

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

  readonly sectionIcons = SECTION_ICONS;
  private i18n = inject(I18nService);

  // Quality tiers (on-the-fly, derived server-side from aggregate thresholds).
  readonly qualityTiers = ['excellent', 'good', 'fair', 'poor'] as const;

  // Representative swatch colour per hue bucket (mid-hue, full saturation).
  readonly hueSwatches: Record<string, string> = {
    red: '#e53935', orange: '#fb8c00', yellow: '#fdd835', green: '#43a047',
    cyan: '#00acc1', blue: '#1e88e5', purple: '#8e24aa', magenta: '#d81b60',
  };

  readonly colorQualityActiveCount = computed(() => {
    const f = this.store.filters();
    return (f.color_temp ? 1 : 0) + (f.hue_bucket ? 1 : 0) + (f.quality_tier ? 1 : 0);
  });

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

  private matchGroups(order: string[]): FilterGroup[] {
    const q = this.filterQuery().trim().toLowerCase();
    const tr = q ? this.translatedDefs() : null;
    const out: FilterGroup[] = [];
    for (const sectionKey of order) {
      const all = FILTERS_BY_SECTION[sectionKey];
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
  readonly searchResultGroups = computed(() => [...this.commonFilterGroups(), ...this.advancedFilterGroups()]);
  readonly noFilterMatches = computed(() => !!this.filterQuery().trim() && this.searchResultGroups().length === 0);

  readonly metricHistograms = computed(() => {
    const ranges = this.store.metricRanges();
    const out: Record<string, number[]> = {};
    for (const key of Object.keys(ranges)) {
      const buckets = ranges[key].buckets;
      const max = Math.max(1, ...buckets);
      out[key] = buckets.map(b => Math.round((b / max) * 100));
    }
    return out;
  });

  readonly advancedActiveCount = computed(() => {
    const counts = this.sectionActiveCounts();
    return ADVANCED_SECTION_ORDER.reduce((sum, key) => sum + (counts[key] || 0), 0);
  });

  readonly sectionActiveCounts = computed((): Record<string, number> => {
    const f = this.store.filters();
    const counts: Record<string, number> = {
      date: (f.date_from ? 1 : 0) + (f.date_to ? 1 : 0),
      content: (f.type ? 1 : 0) + (f.tag ? 1 : 0) + (f.composition_pattern ? 1 : 0),
      equipment: (f.camera ? 1 : 0) + (f.lens ? 1 : 0),
      persons: f.person_id ? f.person_id.split(',').length : 0,
      refine: (f.favorites_only ? 1 : 0) + (f.is_monochrome ? 1 : 0) + (f.hide_rejected ? 1 : 0),
    };
    const fAny = f as Record<string, any>;
    for (const sectionKey of SECTION_ORDER) {
      counts[sectionKey] = FILTERS_BY_SECTION[sectionKey].filter(
        def => fAny[def.minKey] || fAny[def.maxKey]
      ).length;
    }
    return counts;
  });

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

  private searchTimeout: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    if (this.store.config()?.features?.show_albums) {
      firstValueFrom(this.albumService.list()).then(res =>
        this.albums.set(res.albums),
      ).catch(() => {});
    }
    inject(DestroyRef).onDestroy(() => {
      if (this.searchTimeout) clearTimeout(this.searchTimeout);
    });
  }

  onSidebarSearchChange(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.store.updateFilter('search', value);
  }

  onSemanticSearch(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.searchTimeout = setTimeout(() => {
      this.store.updateFilter('semanticQuery', value);
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

  saveAsSmartAlbum(): void {
    const f = this.store.filters();
    const filterJson: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(f)) {
      if (v && v !== '' && !SMART_ALBUM_EXCLUDE_KEYS.has(k)) {
        filterJson[k] = v;
      }
    }
    const ref = this.dialog.open(SaveSmartAlbumDialogComponent, {
      width: '400px',
      data: { filterJson: JSON.stringify(filterJson) },
    });
    ref.afterClosed().subscribe(result => {
      if (result) {
        firstValueFrom(this.albumService.list()).then(res =>
          this.albums.set(res.albums),
        ).catch(() => {});
      }
    });
  }
}
