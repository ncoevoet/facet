import { Component, computed, inject, ElementRef, OnInit, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatSelect, MatSelectModule } from '@angular/material/select';
import { MatSliderModule } from '@angular/material/slider';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';
import { GalleryStore, GalleryFilters } from './gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FilterDisplayPipe } from '../../shared/pipes/filter-display.pipe';

interface AdditionalFilterDef {
  id: string;
  labelKey: string;
  sectionKey: string;
  minKey: keyof GalleryFilters;
  maxKey: keyof GalleryFilters;
  sliderMin: number;
  sliderMax: number;
  step: number;
  displaySuffix?: string;
  displayPrefix?: string;
  spanWidth: string;
}

const ADDITIONAL_FILTERS: AdditionalFilterDef[] = [
  // Quality
  { id: 'score_range', labelKey: 'gallery.score_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_score', maxKey: 'max_score', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'aesthetic_range', labelKey: 'gallery.aesthetic_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_aesthetic', maxKey: 'max_aesthetic', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'quality_score_range', labelKey: 'gallery.quality_score_range', sectionKey: 'gallery.sidebar.quality', minKey: 'min_quality_score', maxKey: 'max_quality_score', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  // Extended Quality
  { id: 'aesthetic_iaa_range', labelKey: 'gallery.aesthetic_iaa_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_aesthetic_iaa', maxKey: 'max_aesthetic_iaa', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'face_quality_iqa_range', labelKey: 'gallery.face_quality_iqa_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_face_quality_iqa', maxKey: 'max_face_quality_iqa', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
  { id: 'liqe_range', labelKey: 'gallery.liqe_range', sectionKey: 'gallery.sidebar.extended_quality', minKey: 'min_liqe', maxKey: 'max_liqe', sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16' },
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

const SECTION_ORDER = [
  'gallery.sidebar.quality',
  'gallery.sidebar.extended_quality',
  'gallery.sidebar.face',
  'gallery.sidebar.composition',
  'gallery.sidebar.saliency',
  'gallery.sidebar.technical',
  'gallery.sidebar.exposure_range',
  'gallery.sidebar.ratings',
];

interface FilterGroup {
  sectionKey: string;
  filters: AdditionalFilterDef[];
}

const SIDEBAR_SECTIONS_KEY = 'facet_sidebar_sections';
const ACTIVE_FILTERS_KEY = 'facet_active_filters';

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

function loadActiveFilterIds(): string[] {
  try {
    const raw = localStorage.getItem(ACTIVE_FILTERS_KEY);
    if (raw) return JSON.parse(raw) as string[];
  } catch { /* ignore */ }
  return [];
}

function saveActiveFilterIds(ids: Set<string>): void {
  try {
    localStorage.setItem(ACTIVE_FILTERS_KEY, JSON.stringify([...ids]));
  } catch { /* ignore */ }
}

@Component({
  selector: 'app-gallery-filter-sidebar',
  standalone: true,
  imports: [
    FormsModule,
    MatSelectModule,
    MatSliderModule,
    MatIconModule,
    MatButtonModule,
    MatFormFieldModule,
    MatCheckboxModule,
    MatInputModule,
    MatTooltipModule,
    TranslatePipe,
    FilterDisplayPipe,
  ],
  template: `
    <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--mat-sys-outline-variant)]">
      <span class="text-base font-medium">{{ 'gallery.filters' | translate }}</span>
      <div class="flex items-center">
        <button mat-icon-button [matTooltip]="'gallery.reset_filters' | translate" (click)="store.resetFilters(); clearActiveFilters()">
          <mat-icon>restart_alt</mat-icon>
        </button>
        <button mat-icon-button (click)="store.setFilterDrawerOpen(false)">
          <mat-icon>close</mat-icon>
        </button>
      </div>
    </div>

    <div #filterScrollArea data-scroll class="overflow-y-auto p-4 flex flex-col gap-1 max-h-[calc(100vh-120px)]">
      <!-- Date Range -->
      <details [open]="sectionStates()['date']" (toggle)="onSectionToggle('date', $event)" class="group/section">
        <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
          {{ 'gallery.sidebar.date' | translate }}
          <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
        </summary>
        <div class="flex flex-col gap-2 pb-2">
          <mat-form-field subscriptSizing="dynamic" class="w-full">
            <mat-label>{{ 'gallery.date_from' | translate }}</mat-label>
            <input matInput type="date" [value]="store.filters().date_from" (change)="onDateChange('date_from', $event)" />
          </mat-form-field>
          <mat-form-field subscriptSizing="dynamic" class="w-full">
            <mat-label>{{ 'gallery.date_to' | translate }}</mat-label>
            <input matInput type="date" [value]="store.filters().date_to" (change)="onDateChange('date_to', $event)" />
          </mat-form-field>
        </div>
      </details>

      <!-- Content -->
      @if (store.tags().length || store.patterns().length) {
        <details [open]="sectionStates()['content'] !== false" (toggle)="onSectionToggle('content', $event)" class="group/section">
          <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
            {{ 'gallery.sidebar.content' | translate }}
            <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
          </summary>
          <div class="flex flex-col gap-2 pb-2">
            @if (store.tags().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ 'gallery.tag' | translate }}</mat-label>
                <mat-select [value]="store.filters().tag" (selectionChange)="store.updateFilter('tag', $event.value)">
                  <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                  @for (t of store.tags(); track t.value) {
                    <mat-option [value]="t.value">{{ t.value }} ({{ t.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
            @if (store.patterns().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ 'gallery.composition_pattern' | translate }}</mat-label>
                <mat-select [value]="store.filters().composition_pattern" (selectionChange)="store.updateFilter('composition_pattern', $event.value)">
                  <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                  @for (p of store.patterns(); track p.value) {
                    <mat-option [value]="p.value">{{ ('composition_patterns.' + p.value) | translate }} ({{ p.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
          </div>
        </details>
      }

      <!-- Equipment -->
      @if (store.cameras().length || store.lenses().length) {
        <details [open]="sectionStates()['equipment'] !== false" (toggle)="onSectionToggle('equipment', $event)" class="group/section">
          <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
            {{ 'gallery.sidebar.equipment' | translate }}
            <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
          </summary>
          <div class="flex flex-col gap-2 pb-2">
            @if (store.cameras().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ 'gallery.camera' | translate }}</mat-label>
                <mat-select [value]="store.filters().camera" (selectionChange)="store.updateFilter('camera', $event.value)">
                  <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                  @for (c of store.cameras(); track c.value) {
                    <mat-option [value]="c.value">{{ c.value }} ({{ c.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
            @if (store.lenses().length) {
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ 'gallery.lens' | translate }}</mat-label>
                <mat-select [value]="store.filters().lens" (selectionChange)="store.updateFilter('lens', $event.value)">
                  <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                  @for (l of store.lenses(); track l.value) {
                    <mat-option [value]="l.value">{{ l.value }} ({{ l.count }})</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            }
          </div>
        </details>
      }

      <!-- Display Options -->
      <details [open]="sectionStates()['display'] !== false" (toggle)="onSectionToggle('display', $event)" class="group/section">
        <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
          {{ 'gallery.sidebar.display' | translate }}
          <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
        </summary>
        <div class="flex flex-col gap-2 pb-2">
          <mat-checkbox
            [checked]="store.filters().hide_details"
            (change)="store.updateFilter('hide_details', $event.checked)"
          >{{ 'gallery.hide_details' | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().hide_blinks"
            (change)="store.updateFilter('hide_blinks', $event.checked)"
          >{{ 'gallery.hide_blinks' | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().hide_bursts"
            (change)="store.updateFilter('hide_bursts', $event.checked)"
          >{{ 'gallery.hide_bursts' | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().hide_duplicates"
            (change)="store.updateFilter('hide_duplicates', $event.checked)"
          >{{ 'gallery.hide_duplicates' | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().hide_rejected"
            (change)="store.updateFilter('hide_rejected', $event.checked)"
          >{{ 'gallery.hide_rejected' | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().favorites_only"
            (change)="store.updateFilter('favorites_only', $event.checked)"
          >{{ 'gallery.favorites_only' | translate }}</mat-checkbox>
          <mat-checkbox
            [checked]="store.filters().is_monochrome"
            (change)="store.updateFilter('is_monochrome', $event.checked)"
          >{{ 'gallery.monochrome_only' | translate }}</mat-checkbox>
        </div>
      </details>

      <!-- Add Filter dropdown -->
      @if (availableFilterGroups().length) {
        <mat-form-field subscriptSizing="dynamic" class="w-full mt-2">
          <mat-label>{{ 'gallery.sidebar.add_filter' | translate }}</mat-label>
          <mat-select #addFilterSelect (selectionChange)="addAdditionalFilter($event.value)" [value]="null">
            @for (group of availableFilterGroups(); track group.sectionKey) {
              <mat-optgroup [label]="group.sectionKey | translate">
                @for (f of group.filters; track f.id) {
                  <mat-option [value]="f.id">{{ f.labelKey | translate }}</mat-option>
                }
              </mat-optgroup>
            }
          </mat-select>
        </mat-form-field>
      }

      <!-- Active additional filters -->
      @for (def of activeFilterDefs(); track def.id) {
        <div class="flex flex-col gap-1 mt-1">
          <div class="flex items-center justify-between">
            <label class="text-sm opacity-70">{{ def.labelKey | translate }}</label>
            <button mat-icon-button class="!w-7 !h-7 !p-0" [matTooltip]="'ui.buttons.remove' | translate" (click)="removeAdditionalFilter(def.id)">
              <mat-icon class="!text-lg">close</mat-icon>
            </button>
          </div>
          <div class="flex items-center gap-2">
            <mat-slider [min]="def.sliderMin" [max]="def.sliderMax" [step]="def.step" class="flex-1">
              <input matSliderStartThumb
                [value]="store.filters()[def.minKey] ? +store.filters()[def.minKey] : def.sliderMin"
                (valueChange)="onDynamicRangeChange(def, 'min', $event)" />
              <input matSliderEndThumb
                [value]="store.filters()[def.maxKey] ? +store.filters()[def.maxKey] : def.sliderMax"
                (valueChange)="onDynamicRangeChange(def, 'max', $event)" />
            </mat-slider>
            <span class="text-xs opacity-60 text-right" [class]="def.spanWidth">{{ store.filters() | filterDisplay:def }}</span>
          </div>
        </div>
      }
    </div>
  `,
})
export class GalleryFilterSidebarComponent implements OnInit {
  readonly store = inject(GalleryStore);
  readonly filterScrollArea = viewChild<ElementRef<HTMLDivElement>>('filterScrollArea');
  readonly addFilterSelect = viewChild<MatSelect>('addFilterSelect');

  readonly activeAdditionalFilters = signal<Set<string>>(new Set());
  readonly sectionStates = signal<Record<string, boolean>>(loadSectionStates());

  readonly activeFilterDefs = computed(() => {
    const activeIds = this.activeAdditionalFilters();
    return ADDITIONAL_FILTERS.filter(f => activeIds.has(f.id));
  });

  readonly availableFilterGroups = computed((): FilterGroup[] => {
    const activeIds = this.activeAdditionalFilters();
    const groups: FilterGroup[] = [];
    for (const sectionKey of SECTION_ORDER) {
      const filters = ADDITIONAL_FILTERS.filter(f => f.sectionKey === sectionKey && !activeIds.has(f.id));
      if (filters.length) {
        groups.push({ sectionKey, filters });
      }
    }
    return groups;
  });

  ngOnInit(): void {
    this.initActiveFilters();
  }

  addAdditionalFilter(filterId: string): void {
    this.activeAdditionalFilters.update(s => {
      const next = new Set(s);
      next.add(filterId);
      saveActiveFilterIds(next);
      return next;
    });
    this.addFilterSelect()?.writeValue(null);
  }

  removeAdditionalFilter(filterId: string): void {
    const def = ADDITIONAL_FILTERS.find(f => f.id === filterId);
    if (def) {
      this.store.updateFilters({ [def.minKey]: '', [def.maxKey]: '' } as Partial<GalleryFilters>);
    }
    this.activeAdditionalFilters.update(s => {
      const next = new Set(s);
      next.delete(filterId);
      saveActiveFilterIds(next);
      return next;
    });
  }

  clearActiveFilters(): void {
    this.activeAdditionalFilters.set(new Set());
    saveActiveFilterIds(new Set());
  }

  onSectionToggle(sectionId: string, event: Event): void {
    const isOpen = (event.target as HTMLDetailsElement).open;
    this.sectionStates.update(s => {
      const next = { ...s, [sectionId]: isOpen };
      saveSectionStates(next);
      return next;
    });
  }

  onDynamicRangeChange(def: AdditionalFilterDef, side: 'min' | 'max', value: number): void {
    // When min is still at default, redirect max thumb interaction to set min instead.
    // Users typically want to set a minimum threshold first.
    if (side === 'max' && !(this.store.filters()[def.minKey] as string)) {
      side = 'min';
    }
    const key = side === 'min' ? def.minKey : def.maxKey;
    const boundary = side === 'min' ? def.sliderMin : def.sliderMax;
    const filterValue = value === boundary ? '' : String(value);
    this.store.updateFilter(key as 'min_score', filterValue);
  }

  onDateChange(key: 'date_from' | 'date_to', event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.store.updateFilter(key, value);
  }

  private initActiveFilters(): void {
    const f = this.store.filters();
    const stored = new Set(loadActiveFilterIds());
    const active = new Set<string>(stored);

    // Also auto-activate any filters that have non-default values from URL params
    for (const def of ADDITIONAL_FILTERS) {
      const min = f[def.minKey] as string;
      const max = f[def.maxKey] as string;
      if (min || max) active.add(def.id);
    }

    this.activeAdditionalFilters.set(active);
  }
}
