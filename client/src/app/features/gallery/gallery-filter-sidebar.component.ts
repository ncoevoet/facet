import { ControlPopoverComponent } from '../../shared/components/control-popover/control-popover.component';
import { FaceOutlinePreferences } from '../../core/services/face-outline-preferences.service';
import { closeDetailsOnEscape, closeOverlayDirectives } from '../../shared/utils/overlays';
import { FEATURE_MARK, MarkTonePipe } from '../../shared/pipes/mark-tone.pipe';
import { Component, computed, DestroyRef, effect, ElementRef, inject, signal, viewChild, viewChildren, ChangeDetectionStrategy, afterNextRender, Injector, input, TemplateRef } from '@angular/core';
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
import { GalleryFilters, PERSON_FILTER_LIMIT, SEARCH_THRESHOLD_MAX, activeFilterUnits, countActiveFilters, filterUnit, hasZeroStarFilter, seededSearchThreshold, smartAlbumFilterJson } from './gallery-filters.util';
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { SaveSmartAlbumDialogComponent } from '../albums/save-smart-album-dialog.component';
import { CardActionsDialogComponent } from './card-actions-dialog.component';
import { folderDisplayName } from '../folders/folders.util';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { isUnavailableKey, unavailableSet } from '../../shared/utils/unavailable-metrics';
import { MetricSparklineComponent } from '../../shared/components/metric-sparkline/metric-sparkline.component';
import { TagGroupsComponent } from './tag-groups.component';
import { KeywordCatalogComponent } from './keyword-catalog.component';
import { KeywordTreeComponent } from './keyword-tree.component';
import { ScorePresenceComponent } from './score-presence.component';
import { SCORE_PRESENCE_KEYS } from './score-presence.util';
import { ADDITIONAL_FILTERS } from './gallery-metric-filters';
import { FilterPinsService, FILTER_PIN_LIMIT } from './filter-pins.service';



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
  'gallery.sidebar.moments': FEATURE_MARK,
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
  quality: ['score_presence', 'gallery.sidebar.quality', 'color_quality', 'gallery.sidebar.extended_quality', 'gallery.sidebar.technical', 'gallery.sidebar.exposure_range'],
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
  score_presence: 'score_presence',
  person_id: 'persons', faces_need_names: 'persons',
  date_from: 'date', date_to: 'date', no_capture_date: 'date',
  type: 'content', tag: 'content', keyword_branch: 'content', composition_pattern: 'content',
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

type RatingOption = 'any' | '1' | '2' | '3' | '4' | '5' | 'zero';

@Component({
  selector: 'app-gallery-filter-sidebar',
  standalone: true,
  host: { class: 'contents' },
  imports: [
    ControlPopoverComponent,
    MarkTonePipe,
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
    TagGroupsComponent, KeywordCatalogComponent, KeywordTreeComponent,
    ScorePresenceComponent,
    PersonThumbnailUrlPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
<ng-template #bodyContent><div class="flex flex-col h-full bg-[var(--mat-sys-surface-container-lowest)] [&_.mat-expansion-panel]:!shadow-none [&_.mat-expansion-panel]:!rounded-none [&_.mat-expansion-panel]:!bg-transparent [&_.mat-expansion-panel]:!mx-0 [&_.mat-expansion-panel]:!my-0 [&_.mat-expansion-panel]:border-b [&_.mat-expansion-panel]:border-[var(--mat-sys-outline-variant)]">
<div class="shrink-0 px-4 border-b border-[var(--mat-sys-outline-variant)]">

      <div class="relative py-2 flex items-center gap-2">
        <span class="text-sm font-medium opacity-80">{{ I18N.gallery.filters | translate }}</span>
        @if (totalActiveCount()) {
          <span data-test="active-count" class="text-xs rounded min-w-5 h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-surface-container-high)] text-[var(--mat-sys-on-surface)] tabular-nums leading-none">{{ totalActiveCount() }}</span>
        }
        <span class="flex-1"></span>
        <details #countHelp data-count-help class="shrink-0">
          <summary #countSummary (keydown.escape)="closeCountHelp($event, countHelp, countSummary)" class="flex h-11 w-11 cursor-pointer list-none items-center justify-center rounded-full hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)] [&::-webkit-details-marker]:hidden"
            [attr.aria-label]="I18N.gallery.sidebar.count_scope | translate"
            [title]="I18N.gallery.sidebar.count_scope | translate">
            <mat-icon class="!text-xl !w-5 !h-5 !leading-5" aria-hidden="true">info_outline</mat-icon>
          </summary>
          <div class="absolute right-0 top-full z-30 w-64 max-w-[calc(100vw-2rem)] rounded-lg border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] p-3 text-xs leading-5 text-[var(--mat-sys-on-surface)] shadow-lg">
            <p class="m-0 font-medium">{{ I18N.gallery.sidebar.count_scope | translate }}</p>
            <p class="mb-0 mt-1">{{ I18N.gallery.sidebar.count_scope_options | translate }}</p>
            <p class="mb-0 mt-1">{{ I18N.gallery.sidebar.count_scope_types | translate }}</p>
            <p class="mb-0 mt-1">{{ I18N.gallery.sidebar.count_scope_badges | translate }}</p>
          </div>
        </details>
        <button mat-icon-button data-test="close" class="shrink-0"
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
      <details class="2xl:!hidden mb-1">
        <summary class="cursor-pointer py-2 text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.ui.filters.search | translate }}</summary>
        <label class="sr-only" for="sidebar-filename-search">{{ I18N.gallery.search_placeholder | translate }}</label>
        <div class="relative min-w-0">
          <input #sidebarSearch id="sidebar-filename-search" type="text" role="searchbox" enterkeyhint="search"
            class="min-h-11 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-lowest)] pl-3 pr-10 text-base text-[var(--mat-sys-on-surface)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
            [placeholder]="I18N.gallery.search_placeholder | translate" [value]="store.filters().search"
            (input)="onSidebarSearchChange($event)" (keyup.enter)="onSidebarSearchCommit($event)" />
          @if (store.filters().search) {
            <button type="button" class="absolute inset-y-0 right-0 flex w-10 cursor-pointer items-center justify-center rounded hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2"
              (click)="clearSidebarSearch()" [attr.aria-label]="I18N.gallery.clear_search | translate">
              <mat-icon class="!text-xl !w-5 !h-5">close</mat-icon>
            </button>
          }
        </div>
      </details>

      <!-- Find a filter -->
      <div class="relative mb-2">
        <label class="sr-only" for="filter-finder-input">{{ I18N.gallery.sidebar.find_filter | translate }}</label>
        <input #filterFinder id="filter-finder-input" [placeholder]="I18N.gallery.sidebar.find_filter | translate"
               type="text" role="searchbox" autocomplete="off"
               class="min-h-11 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-lowest)] py-2 pl-3 pr-10 text-base text-[var(--mat-sys-on-surface)] placeholder:text-[var(--mat-sys-on-surface-variant)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
               [value]="filterQuery()" (input)="filterQuery.set($any($event.target).value)" />
        @if (filterQuery()) {
          <button type="button" class="absolute inset-y-0 right-0 flex w-10 cursor-pointer items-center justify-center rounded hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2"
            (click)="clearFilterQuery()" [attr.aria-label]="I18N.gallery.sidebar.clear_find_filter | translate">
            <mat-icon class="!text-xl !w-5 !h-5">close</mat-icon>
          </button>
        }
      </div>

      @if (!filterQuery().trim()) {
        <nav mat-tab-nav-bar mat-stretch-tabs="true" animationDuration="0ms" [tabPanel]="tabPanel"
             [attr.aria-label]="I18N.gallery.sidebar.tabs.aria_label | translate"
             class="[&_.mdc-tab]:!min-w-0 [&_.mdc-tab]:!px-2 [&_.mdc-tab--active_mat-icon]:!text-[var(--mat-sys-primary)]">
          @for (tab of tabItems(); track tab.id) {
            <button type="button" mat-tab-link [active]="tab.active" (click)="selectTab(tab.id)"
               [matTooltip]="tab.labelKey | translate"
               [attr.aria-label]="tab.count ? (I18N.gallery.sidebar.tabs.active_count | translate:{ label: (tab.labelKey | translate), count: tab.count }) : (tab.labelKey | translate)">
              <span class="inline-flex flex-col items-center gap-0.5 min-w-0 py-1">
                <span class="inline-flex h-6 items-center justify-center gap-1">
                <mat-icon aria-hidden="true">{{ tab.icon }}</mat-icon>
                @if (tab.count) {
                  <span data-filter-tab-count aria-hidden="true" class="text-[0.625rem] rounded-full min-w-4 h-4 px-1 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ tab.count }}</span>
                }
                </span>
                <span data-filter-tab-label class="max-w-12 truncate text-[11px] leading-4">{{ tab.labelKey | translate }}</span>
              </span>
            </button>
          }
        </nav>
      }
    </div>

    <mat-tab-nav-panel #tabPanel class="flex-1 min-h-0 flex flex-col [--mat-expansion-header-collapsed-state-height:40px] [--mat-expansion-header-expanded-state-height:44px] [&_.mat-expansion-panel-body]:!px-2">
    <div data-scroll #scrollArea class="flex-1 min-h-0 overflow-y-auto px-2 pt-3 pb-4">

      @if (!filterQuery().trim() && pinnedFilters().length) {
        <section data-pinned-filters class="mb-3 border-b border-[var(--mat-sys-outline-variant)] pb-2" [attr.aria-label]="I18N.gallery.sidebar.pins.title | translate">
          <details class="mb-1" data-pins-help>
            <summary class="flex min-h-8 cursor-pointer list-none items-center gap-2 rounded px-1 text-xs font-semibold focus-visible:outline-2">
              <span>{{ I18N.gallery.sidebar.pins.title | translate }}</span>
              <mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base text-[var(--mat-sys-on-surface-variant)]">info_outline</mat-icon>
            </summary>
            <p class="m-0 px-1 pb-1 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.sidebar.pins.hint | translate:{ max: pinLimit } }}</p>
          </details>
          @for (def of pinnedFilters(); track def.id) {
            <ng-container [ngTemplateOutlet]="metricRow" [ngTemplateOutletContext]="{ $implicit: def }" />
          }
        </section>
      }
      @if (filterQuery().trim()) {
        @if (noFilterMatches()) {
          <p class="text-xs text-[var(--mat-sys-on-surface-variant)] px-2 py-3">{{ I18N.gallery.sidebar.no_filters_match | translate }}</p>
        }
        @for (group of metricFilterGroups(); track group.sectionKey) {
          <div class="px-1 pt-2 pb-1">
            <div class="flex items-center gap-2 text-xs font-medium text-[var(--mat-sys-on-surface-variant)] mb-1">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80" [class]="group.sectionKey | markTone">{{ sectionIcons[group.sectionKey] || 'tune' }}</mat-icon>
              {{ group.sectionKey | translate }}
            </div>
            @for (def of group.filters; track def.id) {
              <ng-container [ngTemplateOutlet]="metricRow" [ngTemplateOutletContext]="{ $implicit: def }" />
            }
          </div>
        }
      } @else {
        @switch (effectiveTab()) {
          @case ('browse') {
      <!-- Semantic Search (top of sidebar) -->
      @if (store.config()?.features?.show_semantic_search) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['semantic'] === true"
                             (opened)="onSectionToggle('semantic', true)"
                             (closed)="onSectionToggle('semantic', false)"
                             [style.background-color]="sectionStates()['semantic'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-2">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80">image_search</mat-icon>
              {{ I18N.gallery.sidebar.semantic_search | translate }}
            </mat-panel-title>
          </mat-expansion-panel-header>
          <div class="flex min-w-0 flex-col gap-1 pb-1" data-semantic-search>
            <div class="flex min-w-0 items-center gap-1">
              <label class="sr-only" for="semantic-search-input">{{ I18N.gallery.semantic_search | translate }}</label>
              <div class="relative min-w-0 flex-1">
                <input #semanticSearchInput id="semantic-search-input" type="text" role="searchbox" enterkeyhint="search"
                  class="min-h-11 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-lowest)] pl-3 pr-10 text-base text-[var(--mat-sys-on-surface)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
                  [value]="store.filters().semanticQuery" (input)="onSemanticSearch($event)"
                  [placeholder]="I18N.gallery.semantic_search_placeholder | translate" />
                @if (store.filters().semanticQuery) {
                  <button type="button" class="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded cursor-pointer hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2"
                    (click)="clearSemanticSearch()" [attr.aria-label]="I18N.gallery.clear_semantic_search | translate">
                    <mat-icon class="!text-xl !w-5 !h-5">close</mat-icon>
                  </button>
                }
              </div>
              <app-control-popover data-semantic-help [compact]="true" icon="info_outline" [label]="I18N.gallery.semantic_search_help | translate" [content]="semanticExplanation" />
              <ng-template #semanticExplanation>
                <div id="semantic-search-help" class="space-y-2 text-xs">
                  <p class="m-0">{{ I18N.gallery.semantic_search_info | translate }}</p>
                  <p class="m-0">{{ I18N.gallery.semantic_search_threshold_hint | translate }}</p>
                </div>
              </ng-template>
            </div>
            <div class="flex min-w-0 items-center gap-2">
              <span class="shrink-0 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.semantic_search_threshold | translate }}</span>
              <mat-slider [min]="0" [max]="SEARCH_THRESHOLD_MAX" [step]="1" [displayWith]="formatThresholdPercent" class="!mx-1 min-w-0 flex-1">
                <input matSliderThumb [value]="searchThresholdValue()" (valueChange)="onSearchThresholdChange($event)"
                  [attr.aria-label]="I18N.gallery.semantic_search_threshold | translate" aria-describedby="semantic-search-threshold-hint" />
              </mat-slider>
              <span class="w-8 shrink-0 text-right text-xs tabular-nums">{{ searchThresholdValue() }}%</span>
            </div>
            <p id="semantic-search-threshold-hint" class="sr-only">{{ I18N.gallery.semantic_search_threshold_hint | translate }}</p>
          </div>
        </mat-expansion-panel>
      }

      <!-- Persons -->
        <mat-expansion-panel class="!mb-1 mt-1" [expanded]="sectionStates()['persons'] !== false"
                             (opened)="onSectionToggle('persons', true)"
                             (closed)="onSectionToggle('persons', false)"
                             [style.background-color]="sectionStates()['persons'] !== false ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-2">
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
              <mat-label>{{ I18N.gallery.person | translate }}</mat-label>
              <input matInput #sidebarPersonInput
                     [matAutocomplete]="sidebarPersonAuto" [attr.aria-describedby]="selectedPersonIds().length >= personFilterLimit ? 'person-filter-limit' : null"
                     [value]="sidebarPersonQuery()"
                     [placeholder]="selectedPersons().length ? (I18N.gallery.person_add | translate) : ''"
                     (input)="sidebarPersonQuery.set($any($event.target).value)"
                     (focus)="sidebarPersonQuery.set('')" />
              <mat-autocomplete #sidebarPersonAuto="matAutocomplete"
                                (optionSelected)="onSidebarPersonSelected($event)"
                                [hideSingleSelectionIndicator]="true">
                @for (p of filteredPersons(); track p.id) {
                  <mat-option [value]="p.id" [disabled]="selectedPersonIds().length >= personFilterLimit">
                    <div class="flex items-center gap-2">
                      <img [src]="p.id | personThumbnailUrl" class="w-8 h-8 rounded-full object-cover shrink-0" [alt]="p.name || (I18N.gallery.unknown_person | translate)" loading="lazy" />
                      <span class="text-sm">{{ p.name || (I18N.gallery.unknown_person | translate) }} ({{ p.face_count }})</span>
                    </div>
                  </mat-option>
                }
              </mat-autocomplete>
            </mat-form-field>
            @if (selectedPersonIds().length >= personFilterLimit) { <p id="person-filter-limit" role="status" class="m-0 text-xs">{{ I18N.gallery.people_match.limit | translate:{ max: personFilterLimit } }}</p> }
            @if (selectedPersonIds().length > 1) {
              <fieldset class="m-0 border-0 p-0" [attr.aria-describedby]="'person-match-help'">
                <legend class="text-xs font-medium">{{ I18N.gallery.people_match.title | translate }}</legend>
                <div class="flex gap-3">
                  <label class="inline-flex min-h-11 items-center gap-2"><input type="radio" name="person-match" data-person-match="all" value="all" [checked]="store.filters().person_match === 'all'" (change)="store.updateFilter('person_match', 'all')" />{{ I18N.gallery.people_match.all | translate }}</label>
                  <label class="inline-flex min-h-11 items-center gap-2"><input type="radio" name="person-match" data-person-match="any" value="any" [checked]="store.filters().person_match === 'any'" (change)="store.updateFilter('person_match', 'any')" />{{ I18N.gallery.people_match.any | translate }}</label>
                </div>
                <p id="person-match-help" class="m-0 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.people_match.hint | translate }}</p>
              </fieldset>
            }
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
        <mat-expansion-panel-header class="!px-2">
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
          <mat-checkbox [checked]="!!store.filters().no_capture_date"
                        (change)="onMissingDateChange($event.checked)">
            {{ I18N.gallery.no_capture_date | translate }}
          </mat-checkbox>
        </div>
      </mat-expansion-panel>

      <!-- Content -->
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['content'] !== false"
                             (opened)="onSectionToggle('content', true)"
                             (closed)="onSectionToggle('content', false)"
                             [style.background-color]="sectionStates()['content'] !== false ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-2">
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
              <mat-form-field subscriptSizing="dynamic" class="w-full">
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
            <app-tag-groups />
            <app-keyword-catalog />
            <app-keyword-tree />
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

      <!-- Albums -->
      @if (store.config()?.features?.show_albums && albums().length) {
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()['albums'] === true"
                             (opened)="onSectionToggle('albums', true)"
                             (closed)="onSectionToggle('albums', false)"
                             [style.background-color]="sectionStates()['albums'] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-2">
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
                  <mat-option [value]="'' + a.id">{{ a.name }}@if (a.photo_count !== null) { ({{ a.photo_count }})}</mat-option>
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
        <mat-expansion-panel-header class="!px-2">
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
            <div class="text-xs text-[var(--mat-sys-on-surface-variant)] px-1">
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
          <mat-expansion-panel-header class="!px-2">
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
          <mat-expansion-panel-header class="!px-2">
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
          @case ('review') { <ng-container [ngTemplateOutlet]="reviewSettings" /> }
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
          <mat-expansion-panel-header class="!px-2">
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
              <span class="text-xs text-[var(--mat-sys-on-surface-variant)] px-1" [appHelpTip]="I18N.gallery.sidebar.metric_help.hue_bucket | translate">{{ I18N.gallery.hue | translate }}</span>
              <span class="sr-only" id="metric-help-hue_bucket">{{ I18N.gallery.sidebar.metric_help.hue_bucket | translate }}</span>
              <div class="flex flex-wrap gap-1.5" role="group" [attr.aria-label]="I18N.gallery.hue | translate" aria-describedby="metric-help-hue_bucket">
                @for (h of store.hueBuckets(); track h.value) {
                  <button type="button"
                    class="flex items-center gap-1.5 rounded-full pl-1.5 pr-2.5 py-1 text-xs border border-[var(--mat-sys-outline-variant)] cursor-pointer"
                    [class.!border-[var(--mat-sys-primary)]]="store.filters().hue_bucket === h.value"
                    [class.bg-[var(--mat-sys-primary-container)]]="store.filters().hue_bucket === h.value"
                    [attr.aria-pressed]="store.filters().hue_bucket === h.value"
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
      <app-score-presence [metrics]="scorePresenceMetrics" />
          }
          @case ('subject') {
      @for (group of subjectGroups(); track group.sectionKey) {
        <ng-container [ngTemplateOutlet]="metricPanel" [ngTemplateOutletContext]="{ $implicit: group }" />
      }
          }
          @case ('display') { <ng-container [ngTemplateOutlet]="displayLayoutSettings" /><ng-container [ngTemplateOutlet]="displaySettings" /> }
        }
      }

      <ng-template #metricPanel let-group>
        <mat-expansion-panel class="!mb-1" [expanded]="sectionStates()[group.sectionKey] === true"
                             (opened)="onSectionToggle(group.sectionKey, true)"
                             (closed)="onSectionToggle(group.sectionKey, false)"
                             [style.background-color]="sectionStates()[group.sectionKey] === true ? 'var(--mat-sys-surface-container)' : null">
          <mat-expansion-panel-header class="!px-2">
            <mat-panel-title class="flex items-center gap-2">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-none opacity-80" [class]="group.sectionKey | markTone">{{ sectionIcons[group.sectionKey] || 'tune' }}</mat-icon>
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

      <span id="filter-pin-limit" class="sr-only">{{ I18N.gallery.sidebar.pins.limit | translate:{ max: pinLimit } }}</span>
      <ng-template #metricRow let-def>
        <div class="flex flex-col gap-0" [attr.data-metric]="def.id">
          <div class="flex min-h-11 items-center gap-1">
            <span class="min-w-0 flex-1 text-xs px-1" [appHelpTip]="def.helpKey | translate">{{ def.labelKey | translate }}</span>
            <button #metricPin type="button" mat-icon-button [attr.data-pin-filter]="def.id" class="shrink-0"
                    [disabled]="!pinnedIds().has(def.id) && pinLimitReached()"
                    [attr.aria-pressed]="pinnedIds().has(def.id)"
                    [attr.aria-label]="(pinnedIds().has(def.id) ? I18N.gallery.sidebar.pins.remove : I18N.gallery.sidebar.pins.add) | translate:{ name: (def.labelKey | translate) }"
                    [attr.aria-describedby]="pinLimitReached() ? 'filter-pin-limit' : null" (click)="togglePin(def)">
              <mat-icon>{{ pinnedIds().has(def.id) ? 'star' : 'star_border' }}</mat-icon>
            </button>
          </div>
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
            <span class="text-xs text-[var(--mat-sys-on-surface-variant)] text-right" [class]="def.spanWidth">
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
</div></ng-template>
<ng-template #reviewSettings>
      <div data-section="review" class="flex flex-col gap-2 px-1 pt-1 pb-2">
        <div class="flex flex-col">
          @for (row of reviewRows(); track row.id) {
            @if ($index === 1) {
              <span class="text-xs uppercase text-[var(--mat-sys-on-surface-variant)] mt-2 mb-1 px-2">{{ I18N.gallery.sidebar.review.sets | translate }}</span>
            }
            <button type="button" matRipple class="flex w-full min-h-10 items-center gap-3 rounded-md px-2 py-1 text-left hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)] aria-disabled:opacity-50"
              [attr.data-row]="row.id" aria-haspopup="menu"
              [matMenuTriggerFor]="row.disabled ? null : menu" [attr.aria-disabled]="row.disabled || null"
              [attr.aria-label]="I18N.gallery.sidebar.review.value_aria | translate:{ label: (row.labelKey | translate), value: (row.valueLabelKey | translate) }"
              [appHelpTip]="(row.disabled ? I18N.gallery.sidebar.review.rejected_locked : row.helpKey) | translate">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-5 shrink-0 opacity-80">{{ row.icon }}</mat-icon>
              <span class="flex-1 min-w-0 text-sm break-words">{{ row.labelKey | translate }}</span>
              <span class="shrink-0 text-xs text-[var(--mat-sys-on-surface-variant)]" data-value>{{ row.valueLabelKey | translate }}</span>
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
                    <span class="text-xs text-[var(--mat-sys-on-surface-variant)] whitespace-normal leading-snug">{{ option.descKey | translate }}</span>
                  </span>
                </button>
              }
              </ng-template>
            </mat-menu>
          }
        </div>

        <div class="flex flex-col" data-row="quick">
          <span class="text-xs uppercase text-[var(--mat-sys-on-surface-variant)] mt-2 mb-1 px-2" data-test="quick-title">{{ I18N.gallery.sidebar.review.quick | translate }}</span>
          @if (!pinnedIds().has('star_rating_range')) {
            <button #reviewRating type="button" matRipple class="flex w-full min-h-10 items-center gap-3 rounded-md px-2 py-1 text-left hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
              data-row="rating" aria-haspopup="menu" [matMenuTriggerFor]="ratingMenu"
              [attr.aria-label]="I18N.gallery.sidebar.review.value_aria | translate:{ label: (I18N.gallery.star_rating_range | translate), value: (ratingValue().key | translate:ratingValue().vars) }"
              [appHelpTip]="I18N.gallery.sidebar.review.rating_help | translate">
              <mat-icon class="!text-xl !w-5 !h-5 !leading-5 shrink-0 opacity-80">{{ ratingOption() === 'any' ? 'star_border' : 'star' }}</mat-icon>
              <span class="flex-1 min-w-0 text-sm break-words">{{ I18N.gallery.star_rating_range | translate }}</span>
              <span class="shrink-0 text-xs text-[var(--mat-sys-on-surface-variant)]" data-value>{{ ratingValue().key | translate:ratingValue().vars }}</span>
              <mat-icon class="!text-xl !w-5 !h-5 !leading-5 shrink-0 opacity-70">expand_more</mat-icon>
            </button>
            <mat-menu #ratingMenu="matMenu">
              @for (option of ratingOptions; track option.id) {
                <button type="button" mat-menu-item role="menuitemradio" [attr.data-option]="option.id"
                  [attr.aria-checked]="ratingOption() === option.id" (click)="setRating(option.id)">
                  <mat-icon [class.invisible]="ratingOption() !== option.id">check</mat-icon>{{ option.key | translate:option.vars }}
                </button>
              }
            </mat-menu>
          }
          <mat-checkbox data-toggle="favorites_only" [checked]="store.filters().favorites_only"
            [appHelpTip]="I18N.gallery.sidebar.refine_help.favorites_only | translate"
            (change)="store.updateFilter('favorites_only', $event.checked)">{{ I18N.gallery.favorites_only | translate }}</mat-checkbox>
          <mat-checkbox data-toggle="is_monochrome" [checked]="store.filters().is_monochrome"
            [appHelpTip]="I18N.gallery.sidebar.refine_help.monochrome_only | translate"
            (change)="store.updateFilter('is_monochrome', $event.checked)">{{ I18N.gallery.monochrome_only | translate }}</mat-checkbox>
        </div>

        <!-- A correction is invisible in the labels until the detector runs
             again, so without this the only record of one still pending is
             the user's memory. Edition-only: nobody else can make one. -->
        @if (auth.isEdition()) {
          <span class="text-xs uppercase text-[var(--mat-sys-on-surface-variant)] mt-2">{{ I18N.gallery.sidebar.review.edition | translate }}</span>
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
</ng-template>
<ng-template #displayLayoutSettings>
        <div data-section="view-layout" class="flex flex-col gap-2 px-1 pt-1">
          <div class="flex items-center gap-2">
            <span class="text-sm text-[var(--mat-sys-on-surface-variant)] shrink-0">{{ I18N.gallery.layout_mode | translate }}</span>
            <div class="ml-auto flex gap-1"><ng-container [ngTemplateOutlet]="layoutControls()" /></div>
          </div>
          @if (sliderConfig(); as sc) {
            <div class="flex items-center gap-2">
              <span class="text-sm text-[var(--mat-sys-on-surface-variant)] shrink-0">{{ I18N.gallery.thumbnail_size | translate }}</span>
              <mat-slider [min]="thumbnailSliderMin()" [max]="sc.max_px" [step]="sc.step_px" class="flex-1">
                <input matSliderThumb [value]="store.cardWidth()" (valueChange)="store.setCardWidth($event)" [attr.aria-label]="I18N.gallery.thumbnail_size | translate" />
              </mat-slider>
              <span class="text-xs text-[var(--mat-sys-on-surface-variant)] w-10 text-right">{{ store.cardWidth() }}px</span>
            </div>
          }
        </div>
</ng-template>
<ng-template #displaySettings>
      <!-- View (display preferences, not filters): the tab's only section, so no panel around it -->
        <div data-section="view" class="flex flex-col gap-2 px-1 pt-1 pb-2">
          <mat-checkbox data-face-outline-toggle [checked]="faceOutlines.enabled()" (change)="faceOutlines.setEnabled($event.checked)">{{ I18N.gallery.face_outlines | translate }}</mat-checkbox>
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
          <button mat-button data-card-actions class="!min-h-11 !w-full !justify-start" (click)="openCardActionsDialog()">
            <mat-icon>tune</mat-icon>{{ I18N.gallery.card_actions.open | translate }}
          </button>
        </div>
<ng-container [ngTemplateOutlet]="displayExtras()" /></ng-template>
@if (!portSettings()) { <ng-container [ngTemplateOutlet]="bodyContent" /> }
  `,
})
export class GalleryFilterSidebarComponent {
  protected readonly faceOutlines = inject(FaceOutlinePreferences);
  readonly portSettings = input(false);
  readonly bodyContent = viewChild<TemplateRef<unknown>>('bodyContent');
  readonly reviewSettings = viewChild<TemplateRef<unknown>>('reviewSettings');
  readonly displaySettings = viewChild<TemplateRef<unknown>>('displaySettings');
  readonly displayLayoutSettings = viewChild<TemplateRef<unknown>>('displayLayoutSettings');
  readonly displayExtras = input<TemplateRef<unknown> | null>(null);
  readonly effectiveTab = computed(() => this.portSettings() && ['review', 'display'].includes(this.activeTab()) ? 'browse' : this.activeTab());
  readonly layoutControls = input<TemplateRef<unknown> | null>(null);
  protected readonly scorePresenceMetrics = [
    ...ADDITIONAL_FILTERS.filter(def => SCORE_PRESENCE_KEYS.has(def.minKey)),
    { minKey: 'min_topiq', labelKey: 'gallery.topiq_range' },
  ];
  protected readonly I18N = i18nKeys();
  readonly store = inject(GalleryStore);
  readonly auth = inject(AuthService);
  private dialog = inject(MatDialog);
  private albumService = inject(AlbumService);
  private readonly filterPins = inject(FilterPinsService);
  private readonly injector = inject(Injector);
  private readonly metricPins = viewChildren<unknown, ElementRef<HTMLButtonElement>>('metricPin', { read: ElementRef });
  private readonly reviewRating = viewChild<unknown, ElementRef<HTMLButtonElement>>('reviewRating', { read: ElementRef });
  protected readonly pinLimit = FILTER_PIN_LIMIT;
  private readonly pinnableIds = computed(() => Object.values(this.filtersBySection()).flat().map(def => def.id));
  readonly pinnedIds = computed(() => new Set(this.filterPins.ids(this.pinnableIds())));
  readonly pinLimitReached = computed(() => this.pinnedIds().size >= FILTER_PIN_LIMIT);
  readonly pinnedFilters = computed(() => {
    const available = new Map(Object.values(this.filtersBySection()).flat().map(def => [def.id, def]));
    return [...this.pinnedIds()].flatMap(id => {
      const def = available.get(id);
      return def ? [this.clampDef(def)] : [];
    });
  });

  togglePin(def: AdditionalFilterDef): void {
    if (!Object.values(this.filtersBySection()).flat().some(item => item.id === def.id)) return;
    const trigger = this.metricPins().find(pin => pin.nativeElement.dataset['pinFilter'] === def.id)?.nativeElement;
    const owner = this.auth.identity();
    const restoreFocus = trigger && trigger.ownerDocument.activeElement === trigger;
    const wasPinned = this.pinnedIds().has(def.id);
    if (!this.filterPins.toggle(def.id, this.pinnableIds())) return;
    if (wasPinned && !this.filterQuery().trim()) {
      const tab = TAB_IDS.find(id => TAB_SECTIONS[id].includes(def.sectionKey));
      if (tab) this.selectTab(tab);
      this.onSectionToggle(def.sectionKey, true);
    }
    if (restoreFocus) afterNextRender(() => {
      const focused = trigger.ownerDocument.activeElement;
      if (this.auth.identity() !== owner || (focused !== trigger && focused !== trigger.ownerDocument.body)) return;
      const destination = this.metricPins().find(pin => pin.nativeElement.dataset['pinFilter'] === def.id)?.nativeElement
        ?? (def.id === 'star_rating_range' ? this.reviewRating()?.nativeElement : null);
      destination?.focus();
    }, { injector: this.injector });
  }

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
  protected readonly personFilterLimit = PERSON_FILTER_LIMIT;
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
    if (!current.includes(id) && current.length < PERSON_FILTER_LIMIT) {
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
      let defs = q ? all : all.filter(def => !this.pinnedIds().has(def.id));
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
  readonly zeroStars = computed(() => hasZeroStarFilter(this.store.filters()));
  protected readonly ratingOptions: { id: RatingOption; key: string; vars: Record<string, number> }[] = [
    { id: 'any', key: I18N.gallery.sidebar.review.rating_any, vars: {} },
    ...[1, 2, 3, 4, 5].map(count => ({ id: String(count) as RatingOption, key: I18N.gallery.sidebar.review.rating_min, vars: { count } })),
    { id: 'zero', key: I18N.gallery.zero_stars, vars: {} },
  ];
  /** The menu entry matching the current bounds; `custom` for a min/max pair a link or smart album set. */
  readonly ratingOption = computed((): RatingOption | 'custom' => {
    const { min_star_rating: min, max_star_rating: max } = this.store.filters();
    if (this.zeroStars()) return 'zero';
    if (min === '' && max === '') return 'any';
    if (max === '' && ['1', '2', '3', '4', '5'].includes(min)) return min as RatingOption;
    return 'custom';
  });
  readonly ratingValue = computed(() => {
    const option = this.ratingOption();
    if (option !== 'custom') return this.ratingOptions.find(({ id }) => id === option)!;
    const { min_star_rating: min, max_star_rating: max } = this.store.filters();
    return { id: option, key: this.I18N.gallery.sidebar.review.rating_range, vars: { min: Number(min) || 0, max: max === '' ? 5 : Number(max) } };
  });

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

  /** Applies the star-rating bounds of the chosen menu entry. */
  setRating(option: RatingOption): void {
    void this.store.updateFilters({
      min_star_rating: option === 'any' || option === 'zero' ? '' : option,
      max_star_rating: option === 'zero' ? '0' : '',
    });
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

  readonly tabItems = computed(() => TAB_IDS.filter(id => !this.portSettings() || (id !== 'review' && id !== 'display')).map(id => ({
    id,
    icon: TAB_ICONS[id],
    labelKey: this.I18N.gallery.sidebar.tabs[id],
    count: this.tabActiveCounts()[id],
    active: this.effectiveTab() === id,
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
    this.store.updateFilters({ [key]: toIsoDateString(event.value), no_capture_date: '' });
  }

  onMissingDateChange(checked: boolean): void {
    this.store.updateFilters(checked
      ? { no_capture_date: '1', date_from: '', date_to: '' }
      : { no_capture_date: '' });
  }

  protected readonly closeCountHelp = closeDetailsOnEscape;

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
  private readonly popovers = viewChildren(ControlPopoverComponent);

  closeOverlays(): void {
    for (const popover of this.popovers()) popover.open.set(false);
    closeOverlayDirectives(this.tooltips(), this.menuTriggers(), this.selects());
  }

  cancelPendingSearch(): void {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    if (this.thresholdTimeout) clearTimeout(this.thresholdTimeout);
    if (this.filenameTimeout) clearTimeout(this.filenameTimeout);
    this.searchTimeout = null;
    this.thresholdTimeout = null;
    this.filenameTimeout = null;
    this.thresholdDraft.set(null);
    const filenameInput = this.sidebarSearch()?.nativeElement;
    if (filenameInput) filenameInput.value = this.store.filters().search;
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
    const disclosure = input?.closest('details');
    if (disclosure) disclosure.open = true;
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

  clearSidebarSearch(): void {
    if (this.filenameTimeout) clearTimeout(this.filenameTimeout);
    this.filenameTimeout = null;
    const input = this.sidebarSearch()?.nativeElement;
    if (input) { input.value = ''; input.focus(); }
    this.store.updateFilter('search', '');
  }

  private readonly filterFinder = viewChild<ElementRef<HTMLInputElement>>('filterFinder');

  protected clearFilterQuery(): void {
    this.filterQuery.set('');
    const input = this.filterFinder()?.nativeElement;
    if (input) { input.value = ''; input.focus(); }
  }

  onSemanticSearch(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.searchTimeout = setTimeout(() => {
      this.searchTimeout = null;
      this.store.updateFilter('semanticQuery', value);
    }, 400);
  }

  clearSemanticSearch(): void {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.searchTimeout = null;
    const input = this.semanticSearchInput()?.nativeElement;
    if (input) { input.value = ''; input.focus(); }
    this.store.updateFilter('semanticQuery', '');
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
