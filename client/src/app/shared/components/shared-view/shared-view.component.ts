import { Component, inject, signal, computed, OnInit, effect, viewChild, DestroyRef, ElementRef, afterNextRender } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatSliderModule } from '@angular/material/slider';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatInputModule } from '@angular/material/input';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { firstValueFrom } from 'rxjs';
import { Photo } from '../../models/photo.model';
import { ApiService } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { I18nService } from '../../../core/services/i18n.service';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { SortGroupKeyPipe } from '../../pipes/sort-group-key.pipe';
import { FilterDisplayPipe } from '../../pipes/filter-display.pipe';
import { AdditionalFilterDef } from '../../models/filter-def.model';
import {
  ADDITIONAL_FILTERS, SECTION_ORDER, FILTERS_BY_SECTION,
  FilterGroup, SECTION_ICONS,
} from '../../../features/gallery/gallery-filter-sidebar.component';
import { PhotoCardComponent } from '../photo-card/photo-card.component';
import { SlideshowComponent } from '../../../features/gallery/slideshow.component';
import { InfiniteScrollDirective } from '../../directives/infinite-scroll.directive';

interface SortOption {
  column: string;
  label: string;
}

interface FilterOption {
  value: string;
  count: number;
}

interface FilterOptions {
  cameras: FilterOption[];
  lenses: FilterOption[];
  tags: FilterOption[];
  patterns: FilterOption[];
  categories: FilterOption[];
}

interface SharedAlbumResponse {
  album: { id: number; name: string; description: string; is_smart?: boolean };
  photos: Photo[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_more: boolean;
  effective_sort?: string;
  effective_sort_direction?: string;
  sort_options_grouped?: Record<string, SortOption[]>;
  filter_options?: FilterOptions;
}

interface ViewerConfig {
  quality_thresholds?: { excellent: number; great: number; good: number };
  features?: Record<string, boolean>;
  sort_options_grouped?: Record<string, SortOption[]>;
}

interface SharedFilters {
  camera: string;
  lens: string;
  tag: string;
  date_from: string;
  date_to: string;
  composition_pattern: string;
  category: string;
  hide_blinks: boolean;
  hide_bursts: boolean;
  hide_duplicates: boolean;
  is_monochrome: boolean;
  [key: string]: string | boolean;
}

@Component({
  selector: 'app-shared-view',
  standalone: true,
  host: { class: 'block h-full' },
  imports: [
    MatIconModule, MatButtonModule, MatProgressSpinnerModule, MatMenuModule,
    MatSelectModule, MatFormFieldModule, MatSnackBarModule, MatTooltipModule,
    MatSliderModule, MatSidenavModule, MatExpansionModule, MatInputModule, MatCheckboxModule,
    TranslatePipe, FilterDisplayPipe, SortGroupKeyPipe,
    PhotoCardComponent, SlideshowComponent, InfiniteScrollDirective,
  ],
  template: `
    @if (loading()) {
      <div class="flex items-center justify-center h-64">
        <mat-spinner diameter="40" />
      </div>
    } @else if (error()) {
      <div class="flex flex-col items-center justify-center h-64 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">lock</mat-icon>
        <p>{{ error() }}</p>
      </div>
    } @else {
      <div class="bg-[var(--mat-sys-surface)] border-b border-[var(--mat-sys-outline-variant)] px-2 md:px-4 py-1 md:py-3">
        <div class="flex items-center gap-2">
          <div class="hidden md:block min-w-0 shrink">
            <h1 class="text-xl font-semibold truncate">{{ entityName() }}</h1>
            @if (description()) {
              <p class="text-sm opacity-70 mt-1">{{ description() }}</p>
            }
            <p class="text-xs opacity-50 mt-1">{{ 'albums.photos_count' | translate:{ count: total() } }}</p>
          </div>
          <div class="flex items-center gap-1 md:gap-2 flex-1 min-w-0">
            <mat-form-field class="flex-1 min-w-0 md:max-w-xs" subscriptSizing="dynamic">
              <mat-label>{{ 'gallery.sort' | translate }}</mat-label>
              <mat-select panelWidth="auto" panelClass="nowrap-panel" [value]="sortBy()" (selectionChange)="onSortChange($event.value)">
                @if (sortGroups(); as groups) {
                  @for (group of groups; track group[0]) {
                    <mat-optgroup [label]="('sort_groups.' + (group[0] | sortGroupKey)) | translate">
                      @for (opt of group[1]; track opt.column) {
                        <mat-option [value]="opt.column">{{ 'sort_options.' + opt.column | translate }}</mat-option>
                      }
                    </mat-optgroup>
                  }
                } @else {
                  <mat-option value="aggregate">{{ 'gallery.sort_aggregate' | translate }}</mat-option>
                  <mat-option value="aesthetic">{{ 'gallery.sort_aesthetic' | translate }}</mat-option>
                  <mat-option value="date_taken">{{ 'gallery.sort_date' | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <button mat-icon-button (click)="toggleSortDirection()" [matTooltip]="sortDirection() === 'desc' ? ('gallery.sort_desc' | translate) : ('gallery.sort_asc' | translate)">
              <mat-icon>{{ sortDirection() === 'desc' ? 'arrow_downward' : 'arrow_upward' }}</mat-icon>
            </button>
            @if (isManualAlbum()) {
              <button mat-icon-button (click)="filterDrawer.toggle()" [matTooltip]="'gallery.filters' | translate">
                <mat-icon [style.color]="filterDrawer.opened || activeFilterCount() ? 'var(--mat-sys-primary)' : ''">tune</mat-icon>
              </button>
            }
            <button mat-icon-button class="shrink-0 ml-auto" (click)="slideshowActive.set(true)" [matTooltip]="'slideshow.start' | translate">
              <mat-icon>slideshow</mat-icon>
            </button>
          </div>
        </div>
      </div>

      <mat-sidenav-container class="overflow-hidden" [style.height]="'calc(100% - ' + (selectionCount() > 0 ? '113' : '65') + 'px)'" [class.pb-10]="!isDesktop() && !selectionCount()">
        <mat-sidenav #filterDrawer [mode]="isDesktop() ? 'side' : 'over'" position="end" class="w-[min(320px,100vw)] p-0">
          <div class="overflow-y-auto px-2 pt-4 pb-4 h-full">
            <!-- Equipment -->
            @if (filterOptions()?.cameras?.length || filterOptions()?.lenses?.length) {
              <mat-expansion-panel class="!mb-1">
                <mat-expansion-panel-header>
                  <mat-panel-title class="flex items-center gap-2">
                    <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">photo_camera</mat-icon>
                    {{ 'gallery.sidebar.equipment' | translate }}
                    @if (filters().camera || filters().lens) {
                      <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ (filters().camera ? 1 : 0) + (filters().lens ? 1 : 0) }}</span>
                    }
                  </mat-panel-title>
                </mat-expansion-panel-header>
                <div class="flex flex-col gap-2 pb-2">
                  @if (filterOptions()?.cameras?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ 'gallery.camera' | translate }}</mat-label>
                      <mat-select [value]="filters().camera" (selectionChange)="updateFilter('camera', $event.value)">
                        <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                        @for (c of filterOptions()!.cameras; track c.value) {
                          <mat-option [value]="c.value">{{ c.value }} ({{ c.count }})</mat-option>
                        }
                      </mat-select>
                    </mat-form-field>
                  }
                  @if (filterOptions()?.lenses?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ 'gallery.lens' | translate }}</mat-label>
                      <mat-select [value]="filters().lens" (selectionChange)="updateFilter('lens', $event.value)">
                        <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                        @for (l of filterOptions()!.lenses; track l.value) {
                          <mat-option [value]="l.value">{{ l.value }} ({{ l.count }})</mat-option>
                        }
                      </mat-select>
                    </mat-form-field>
                  }
                </div>
              </mat-expansion-panel>
            }

            <!-- Content -->
            @if (filterOptions()?.tags?.length || filterOptions()?.patterns?.length || filterOptions()?.categories?.length) {
              <mat-expansion-panel class="!mb-1">
                <mat-expansion-panel-header>
                  <mat-panel-title class="flex items-center gap-2">
                    <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">label</mat-icon>
                    {{ 'gallery.sidebar.content' | translate }}
                    @if (contentFilterCount()) {
                      <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ contentFilterCount() }}</span>
                    }
                  </mat-panel-title>
                </mat-expansion-panel-header>
                <div class="flex flex-col gap-2 pb-2">
                  @if (filterOptions()?.tags?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ 'gallery.tag' | translate }}</mat-label>
                      <mat-select [value]="filters().tag" (selectionChange)="updateFilter('tag', $event.value)">
                        <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                        @for (t of filterOptions()!.tags; track t.value) {
                          <mat-option [value]="t.value">{{ t.value }} ({{ t.count }})</mat-option>
                        }
                      </mat-select>
                    </mat-form-field>
                  }
                  @if (filterOptions()?.patterns?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ 'gallery.composition_pattern' | translate }}</mat-label>
                      <mat-select [value]="filters().composition_pattern" (selectionChange)="updateFilter('composition_pattern', $event.value)">
                        <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                        @for (p of filterOptions()!.patterns; track p.value) {
                          <mat-option [value]="p.value">{{ ('composition_patterns.' + p.value) | translate }} ({{ p.count }})</mat-option>
                        }
                      </mat-select>
                    </mat-form-field>
                  }
                  @if (filterOptions()?.categories?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ 'ui.filters.type' | translate }}</mat-label>
                      <mat-select [value]="filters().category" (selectionChange)="updateFilter('category', $event.value)">
                        <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                        @for (cat of filterOptions()!.categories; track cat.value) {
                          <mat-option [value]="cat.value">{{ 'category_names.' + cat.value | translate }} ({{ cat.count }})</mat-option>
                        }
                      </mat-select>
                    </mat-form-field>
                  }
                </div>
              </mat-expansion-panel>
            }

            <!-- Date Range -->
            <mat-expansion-panel class="!mb-1">
              <mat-expansion-panel-header>
                <mat-panel-title class="flex items-center gap-2">
                  <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">calendar_today</mat-icon>
                  {{ 'gallery.sidebar.date' | translate }}
                  @if (filters().date_from || filters().date_to) {
                    <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ (filters().date_from ? 1 : 0) + (filters().date_to ? 1 : 0) }}</span>
                  }
                </mat-panel-title>
              </mat-expansion-panel-header>
              <div class="flex flex-col gap-2 pb-2">
                <mat-form-field subscriptSizing="dynamic" class="w-full">
                  <mat-label>{{ 'gallery.date_from' | translate }}</mat-label>
                  <input matInput type="date" [value]="filters().date_from" (change)="onDateChange('date_from', $event)" />
                </mat-form-field>
                <mat-form-field subscriptSizing="dynamic" class="w-full">
                  <mat-label>{{ 'gallery.date_to' | translate }}</mat-label>
                  <input matInput type="date" [value]="filters().date_to" (change)="onDateChange('date_to', $event)" />
                </mat-form-field>
              </div>
            </mat-expansion-panel>

            <!-- Display Options -->
            <mat-expansion-panel class="!mb-1">
              <mat-expansion-panel-header>
                <mat-panel-title class="flex items-center gap-2">
                  <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">display_settings</mat-icon>
                  {{ 'gallery.sidebar.display' | translate }}
                  @if (displayFilterCount()) {
                    <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ displayFilterCount() }}</span>
                  }
                </mat-panel-title>
              </mat-expansion-panel-header>
              <div class="flex flex-col gap-2 pb-2">
                <mat-checkbox
                  [checked]="filters().hide_blinks"
                  (change)="updateFilter('hide_blinks', $event.checked)"
                >{{ 'gallery.hide_blinks' | translate }}</mat-checkbox>
                <mat-checkbox
                  [checked]="filters().hide_bursts"
                  (change)="updateFilter('hide_bursts', $event.checked)"
                >{{ 'gallery.hide_bursts' | translate }}</mat-checkbox>
                <mat-checkbox
                  [checked]="filters().hide_duplicates"
                  (change)="updateFilter('hide_duplicates', $event.checked)"
                >{{ 'gallery.hide_duplicates' | translate }}</mat-checkbox>
                <mat-checkbox
                  [checked]="filters().is_monochrome"
                  (change)="updateFilter('is_monochrome', $event.checked)"
                >{{ 'gallery.monochrome_only' | translate }}</mat-checkbox>
              </div>
            </mat-expansion-panel>

            <!-- Metric filter sections (collapsed by default) -->
            @for (group of filterGroups; track group.sectionKey) {
              <mat-expansion-panel class="!mb-1">
                <mat-expansion-panel-header>
                  <mat-panel-title class="flex items-center gap-2">
                    <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">{{ sectionIcons[group.sectionKey] || 'tune' }}</mat-icon>
                    {{ group.sectionKey | translate }}
                    @if (rangeSectionActiveCounts()[group.sectionKey]) {
                      <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ rangeSectionActiveCounts()[group.sectionKey] }}</span>
                    }
                  </mat-panel-title>
                </mat-expansion-panel-header>
                <div class="flex flex-col gap-1 pb-1">
                  @for (def of group.filters; track def.id) {
                    <div class="flex flex-col gap-0">
                      <label class="text-xs opacity-60 px-1">{{ def.labelKey | translate }}</label>
                      <div class="flex items-center gap-1">
                        <mat-slider [min]="def.sliderMin" [max]="def.sliderMax" [step]="def.step" class="flex-1">
                          <input matSliderStartThumb
                            [value]="$any(filters())[def.minKey] ? +$any(filters())[def.minKey] : def.sliderMin"
                            (valueChange)="onDynamicRangeChange(def, 'min', $event)" />
                          <input matSliderEndThumb
                            [value]="$any(filters())[def.maxKey] ? +$any(filters())[def.maxKey] : def.sliderMax"
                            (valueChange)="onDynamicRangeChange(def, 'max', $event)" />
                        </mat-slider>
                        <span class="text-xs opacity-60 text-right" [class]="def.spanWidth">{{ filters() | filterDisplay:def }}</span>
                      </div>
                    </div>
                  }
                </div>
              </mat-expansion-panel>
            }

            <!-- Reset filters -->
            @if (activeFilterCount()) {
              <div class="py-3 px-1">
                <button mat-stroked-button class="w-full" (click)="resetFilters()">
                  <mat-icon>close</mat-icon>
                  {{ 'gallery.reset_filters' | translate }}
                </button>
              </div>
            }
          </div>
        </mat-sidenav>

        <mat-sidenav-content #contentArea>
          <div class="p-2">
            @if (isDesktop()) {
              @for (row of mosaicRows(); track $index) {
                <div class="flex gap-2 mb-2">
                  @for (photo of row.photos; track photo.path; let i = $index) {
                    <app-photo-card
                      [photo]="photo"
                      [config]="cardConfig()"
                      [hideDetails]="true"
                      [mosaicMode]="true"
                      [isEditionMode]="false"
                      [isSelected]="selectedPaths().has(photo.path)"
                      [thumbSize]="row.widths[i]"
                      [style.width.px]="row.widths[i]"
                      [style.height.px]="row.height"
                      (selectionChange)="toggleSelection($event.photo, $event.event)"
                      (doubleClicked)="openPhotoDetail($event)"
                    />
                  }
                </div>
              }
            } @else {
              <div class="grid grid-cols-1 gap-2">
                @for (photo of photos(); track photo.path) {
                  <app-photo-card
                    [photo]="photo"
                    [config]="cardConfig()"
                    [hideDetails]="true"
                    [isEditionMode]="false"
                    [isSelected]="selectedPaths().has(photo.path)"
                    (selectionChange)="toggleSelection($event.photo, $event.event)"
                    (doubleClicked)="openPhotoDetail($event)"
                  />
                }
              </div>
            }
            <div appInfiniteScroll scrollRoot="mat-sidenav-content" (scrollReached)="onScrollReached()"></div>
          </div>
        </mat-sidenav-content>
      </mat-sidenav-container>

      <!-- Selection action bar -->
      @if (selectionCount()) {
        <div class="fixed bottom-0 left-0 right-0 z-50 flex items-center gap-1 lg:gap-3 px-2 lg:px-6 py-1 lg:py-3 bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
          <span class="text-sm font-medium shrink-0">{{ 'gallery.selection.count' | translate:{ count: selectionCount() } }}</span>
          <div class="flex items-center gap-0 lg:gap-2 ml-auto">
            <button mat-icon-button class="lg:!hidden" (click)="clearSelection()" [matTooltip]="'gallery.selection.clear' | translate"><mat-icon>close</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="clearSelection()"><mat-icon>close</mat-icon> {{ 'gallery.selection.clear' | translate }}</button>
            <button mat-icon-button class="lg:!hidden" (click)="copyPaths()" [matTooltip]="'gallery.selection.copy_filenames' | translate"><mat-icon>content_copy</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="copyPaths()"><mat-icon>content_copy</mat-icon> {{ 'gallery.selection.copy_filenames' | translate }}</button>
            @if (auth.downloadProfiles().length) {
              <button mat-icon-button class="lg:!hidden" [matMenuTriggerFor]="dlMenu" [disabled]="downloading()" [matTooltip]="'gallery.selection.download' | translate">@if (downloading()) { <mat-spinner diameter="24" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> }</button>
              <button mat-flat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="dlMenu" [disabled]="downloading()">@if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> } {{ downloading() ? ('photo_detail.downloading' | translate) : ('gallery.selection.download' | translate) }}</button>
              <mat-menu #dlMenu="matMenu">
                <button mat-menu-item (click)="downloadSelected()"><mat-icon>image</mat-icon> {{ 'download.type_original' | translate }}</button>
                @for (profile of auth.downloadProfiles(); track profile) {
                  <button mat-menu-item (click)="downloadSelected('darktable', profile)"><mat-icon>photo_filter</mat-icon> {{ profile }}</button>
                }
              </mat-menu>
            } @else {
              <button mat-icon-button class="lg:!hidden" (click)="downloadSelected()" [disabled]="downloading()" [matTooltip]="'gallery.selection.download' | translate">@if (downloading()) { <mat-spinner diameter="24" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> }</button>
              <button mat-flat-button class="!hidden lg:!inline-flex" (click)="downloadSelected()" [disabled]="downloading()">@if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> } {{ downloading() ? ('photo_detail.downloading' | translate) : ('gallery.selection.download' | translate) }}</button>
            }
          </div>
        </div>
      }

      <!-- Mobile bottom bar -->
      @if (!selectionCount()) {
        <div class="md:hidden fixed bottom-0 left-0 right-0 z-50 h-11 flex items-center gap-2 px-4 bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] safe-area-pb">
          <span class="text-sm font-medium truncate">{{ entityName() }}</span>
          <span class="text-xs opacity-60 ml-auto shrink-0">{{ total() }}</span>
        </div>
      }

      <!-- Slideshow overlay -->
      @if (slideshowActive()) {
        <app-slideshow
          [photos]="photos()"
          [hasMore]="hasMore()"
          [loading]="loadingMore()"
          (closed)="slideshowActive.set(false)"
        />
      }
    }
  `,
})
export class SharedViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  private readonly contentArea = viewChild<ElementRef<HTMLElement>>('contentArea');
  private readonly scrollDirective = viewChild(InfiniteScrollDirective);

  // Loading state
  protected readonly loading = signal(true);
  protected readonly loadingMore = signal(false);
  protected readonly downloading = signal(false);
  protected readonly error = signal('');

  // Entity data
  protected readonly entityName = signal('');
  protected readonly description = signal('');
  protected readonly photos = signal<Photo[]>([]);
  protected readonly total = signal(0);
  protected readonly hasMore = signal(false);
  protected readonly isManualAlbum = signal(false);

  // Config (for sort options and card config)
  protected readonly config = signal<ViewerConfig | null>(null);

  protected readonly cardConfig = computed(() => {
    const c = this.config();
    if (!c) return null;
    return { quality_thresholds: c.quality_thresholds, features: {} };
  });

  // Sort
  protected readonly sortBy = signal('aggregate');
  protected readonly sortDirection = signal<'asc' | 'desc'>('desc');

  protected readonly sortGroups = computed(() => {
    const grouped = this.config()?.sort_options_grouped;
    if (!grouped) return null;
    return Object.entries(grouped);
  });

  // Filters (for manual albums)
  protected readonly filters = signal<SharedFilters>({
    camera: '', lens: '', tag: '', date_from: '', date_to: '',
    composition_pattern: '', category: '',
    hide_blinks: false, hide_bursts: false, hide_duplicates: false, is_monochrome: false,
  });
  protected readonly filterOptions = signal<FilterOptions | null>(null);
  protected readonly filterGroups: FilterGroup[] = SECTION_ORDER.map(sectionKey => ({
    sectionKey,
    filters: FILTERS_BY_SECTION[sectionKey],
  }));
  protected readonly sectionIcons = SECTION_ICONS;
  protected readonly rangeSectionActiveCounts = computed((): Record<string, number> => {
    const f = this.filters();
    const counts: Record<string, number> = {};
    for (const sectionKey of SECTION_ORDER) {
      counts[sectionKey] = FILTERS_BY_SECTION[sectionKey].filter(
        def => f[def.minKey] || f[def.maxKey]
      ).length;
    }
    return counts;
  });
  protected readonly activeFilterCount = computed(() => {
    const f = this.filters();
    let count = [f.camera, f.lens, f.tag, f.date_from, f.date_to, f.composition_pattern, f.category].filter(v => !!v).length
      + (f.hide_blinks ? 1 : 0) + (f.hide_bursts ? 1 : 0) + (f.hide_duplicates ? 1 : 0) + (f.is_monochrome ? 1 : 0);
    for (const def of ADDITIONAL_FILTERS) {
      if (f[def.minKey] || f[def.maxKey]) count++;
    }
    return count;
  });
  protected readonly contentFilterCount = computed(() => {
    const f = this.filters();
    return (f.tag ? 1 : 0) + (f.composition_pattern ? 1 : 0) + (f.category ? 1 : 0);
  });
  protected readonly displayFilterCount = computed(() => {
    const f = this.filters();
    return (f.hide_blinks ? 1 : 0) + (f.hide_bursts ? 1 : 0) + (f.hide_duplicates ? 1 : 0) + (f.is_monochrome ? 1 : 0);
  });

  // Responsive: force single-column grid on small screens
  protected readonly isDesktop = signal(false);
  private desktopMql: MediaQueryList | null = null;
  private desktopMqlHandler: ((e: MediaQueryListEvent) => void) | null = null;

  // Mosaic
  protected readonly containerWidth = signal(0);
  protected readonly mosaicRows = computed(() => {
    const photos = this.photos();
    const width = this.containerWidth();
    const targetHeight = 168;
    const gap = 8;

    if (!photos.length || width <= 0) return [];

    const rows: { photos: Photo[]; widths: number[]; height: number }[] = [];
    let rowPhotos: Photo[] = [];
    let rowAspects: number[] = [];

    for (const photo of photos) {
      const aspect = (photo.image_width && photo.image_height)
        ? photo.image_width / photo.image_height
        : 4 / 3;
      rowPhotos.push(photo);
      rowAspects.push(aspect);

      const totalAspect = rowAspects.reduce((a, b) => a + b, 0);
      const availableWidth = width - (rowPhotos.length - 1) * gap;
      const rowHeight = availableWidth / totalAspect;

      if (rowHeight <= targetHeight) {
        const widths = rowAspects.map(a => Math.floor(a * rowHeight));
        const usedWidth = widths.reduce((a, b) => a + b, 0) + (widths.length - 1) * gap;
        widths[widths.length - 1] += width - usedWidth;
        rows.push({ photos: [...rowPhotos], widths, height: Math.floor(rowHeight) });
        rowPhotos = [];
        rowAspects = [];
      }
    }

    if (rowPhotos.length) {
      const widths = rowAspects.map(a => Math.floor(a * targetHeight));
      rows.push({ photos: [...rowPhotos], widths, height: targetHeight });
    }

    return rows;
  });

  // Slideshow
  protected readonly slideshowActive = signal(false);

  // Multi-select
  protected readonly selectedPaths = signal<Set<string>>(new Set());
  protected readonly selectionCount = computed(() => this.selectedPaths().size);
  private lastSelectedIndex = -1;

  private entityId = 0;
  private token = '';
  private currentPage = 1;
  private sortApplied = false;
  private resizeObserver: ResizeObserver | null = null;

  constructor() {
    afterNextRender(() => {
      const mql = window.matchMedia('(min-width: 768px)');
      this.isDesktop.set(mql.matches);
      this.desktopMql = mql;
      this.desktopMqlHandler = (e: MediaQueryListEvent) => this.isDesktop.set(e.matches);
      mql.addEventListener('change', this.desktopMqlHandler);
    });

    // Set up ResizeObserver once loading completes and mat-sidenav-content is in the DOM
    effect(() => {
      if (!this.loading() && !this.resizeObserver) {
        // Defer to next microtask so Angular renders the sidenav container first
        queueMicrotask(() => this.setupResizeObserver());
      }
    });
    this.destroyRef.onDestroy(() => {
      if (this.desktopMql && this.desktopMqlHandler) {
        this.desktopMql.removeEventListener('change', this.desktopMqlHandler);
      }
      if (this.rangeDebounce) clearTimeout(this.rangeDebounce);
      this.resizeObserver?.disconnect();
      this.resizeObserver = null;
    });
  }

  async ngOnInit(): Promise<void> {
    this.entityId = Number(this.route.snapshot.paramMap.get('albumId'));
    this.token = this.route.snapshot.queryParamMap.get('token') ?? '';

    if (!this.entityId || !this.token) {
      this.error.set(this.i18n.t('albums.invalid_share_link'));
      this.loading.set(false);
      return;
    }

    // Fetch config for quality thresholds (used by photo cards)
    try {
      const cfg = await firstValueFrom(this.api.get<ViewerConfig>('/config'));
      this.config.set(cfg);
    } catch {
      // Non-critical — continue without config
    }

    await this.loadPage(1);
  }

  protected onSortChange(value: string): void {
    this.sortApplied = true;
    this.sortBy.set(value);
    this.reloadFromFirstPage();
  }

  protected toggleSortDirection(): void {
    this.sortApplied = true;
    this.sortDirection.update(d => d === 'desc' ? 'asc' : 'desc');
    this.reloadFromFirstPage();
  }

  protected updateFilter(key: keyof SharedFilters, value: string | boolean): void {
    this.filters.update(f => ({ ...f, [key]: value }));
    this.refreshFiltered();
  }

  protected onDateChange(key: keyof SharedFilters, event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.updateFilter(key, value);
  }

  private rangeDebounce: ReturnType<typeof setTimeout> | null = null;

  protected onDynamicRangeChange(def: AdditionalFilterDef, side: 'min' | 'max', value: number): void {
    const effectiveSide = (side === 'max' && !this.filters()[def.minKey]) ? 'min' : side;
    const key = effectiveSide === 'min' ? def.minKey : def.maxKey;
    const boundary = effectiveSide === 'min' ? def.sliderMin : def.sliderMax;
    const filterValue = value === boundary ? '' : String(value);
    this.filters.update(f => ({ ...f, [key]: filterValue }));
    if (this.rangeDebounce) clearTimeout(this.rangeDebounce);
    this.rangeDebounce = setTimeout(() => this.refreshFiltered(), 300);
  }

  protected resetFilters(): void {
    this.filters.set({
      camera: '', lens: '', tag: '', date_from: '', date_to: '',
      composition_pattern: '', category: '',
      hide_blinks: false, hide_bursts: false, hide_duplicates: false, is_monochrome: false,
    });
    this.refreshFiltered();
  }

  /** Reload photos without destroying the DOM (no loading spinner). */
  private async refreshFiltered(): Promise<void> {
    this.currentPage = 1;
    await this.loadPage(1);
  }

  protected onScrollReached(): void {
    if (this.hasMore() && !this.loadingMore() && !this.loading()) {
      this.loadingMore.set(true);
      this.loadPage(this.currentPage + 1, true)
        .then(() => this.scrollDirective()?.recheck())
        .finally(() => this.loadingMore.set(false));
    }
  }

  // --- Multi-select ---

  protected toggleSelection(photo: Photo, event?: MouseEvent): void {
    const photos = this.photos();
    const clickedIndex = photos.findIndex(p => p.path === photo.path);
    const current = this.selectedPaths();
    const next = new Set(current);

    if (event?.shiftKey && this.lastSelectedIndex >= 0 && clickedIndex >= 0) {
      const start = Math.min(this.lastSelectedIndex, clickedIndex);
      const end = Math.max(this.lastSelectedIndex, clickedIndex);
      for (let i = start; i <= end; i++) {
        next.add(photos[i].path);
      }
    } else if (next.has(photo.path)) {
      next.delete(photo.path);
    } else {
      next.add(photo.path);
    }

    if (clickedIndex >= 0) this.lastSelectedIndex = clickedIndex;
    this.selectedPaths.set(next);
  }

  protected clearSelection(): void {
    this.selectedPaths.set(new Set());
    this.lastSelectedIndex = -1;
  }

  protected copyPaths(): void {
    const filenames = [...this.selectedPaths()]
      .map(p => p.split(/[\\/]/).pop() ?? p)
      .join('\n');
    navigator.clipboard.writeText(filenames).then(() => {
      this.snackBar.open(this.i18n.t('gallery.selection.copied'), '', { duration: 2000 });
    });
  }

  protected async downloadSelected(type = 'original', profile?: string): Promise<void> {
    this.downloading.set(true);
    try {
      const paths = [...this.selectedPaths()];
      for (const path of paths) {
        const url = this.api.downloadUrl(path, type, profile, this.token);
        const blob = await firstValueFrom(this.api.getRaw(url));
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = path.split(/[\\/]/).pop() ?? '';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);
      }
    } finally {
      this.downloading.set(false);
    }
  }

  // --- Photo detail navigation ---

  protected openPhotoDetail(photo: Photo): void {
    this.router.navigate(
      [`/shared/album/${this.entityId}/photo`],
      {
        queryParams: { path: photo.path, token: this.token },
        state: { photo },
      },
    );
  }

  // --- Data loading ---

  private async reloadFromFirstPage(): Promise<void> {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.loading.set(true);
    this.photos.set([]);
    this.currentPage = 1;
    await this.loadPage(1);
  }

  private async loadPage(page: number, append = false): Promise<void> {
    try {
      await this.loadAlbumPage(page, append);
    } catch (e: unknown) {
      if (e instanceof HttpErrorResponse && (e.status === 403 || e.status === 401)) {
        this.error.set(this.i18n.t('albums.share_link_revoked'));
      } else {
        this.error.set(this.i18n.t('albums.load_error'));
      }
    } finally {
      this.loading.set(false);
    }
  }

  private async loadAlbumPage(page: number, append: boolean): Promise<void> {
    const params: Record<string, string | number> = {
      token: this.token,
      page,
    };

    // Only send sort params if user has explicitly changed sort (let backend use saved default otherwise)
    if (this.sortApplied) {
      params['sort'] = this.sortBy();
      params['sort_direction'] = this.sortDirection() === 'desc' ? 'DESC' : 'ASC';
    }

    // Add active filters to API call
    for (const [key, value] of Object.entries(this.filters())) {
      if (value) params[key] = typeof value === 'boolean' ? '1' : value;
    }

    const res = await firstValueFrom(
      this.api.get<SharedAlbumResponse>(`/shared/album/${this.entityId}`, params),
    );
    this.entityName.set(res.album.name);
    this.description.set(res.album.description);
    this.isManualAlbum.set(!res.album.is_smart);
    this.total.set(res.total);
    this.hasMore.set(res.has_more);
    this.currentPage = res.page;

    // Sync sort signals from API response (for saved smart album defaults)
    if (res.effective_sort) {
      this.sortBy.set(res.effective_sort);
      this.sortDirection.set(res.effective_sort_direction === 'ASC' ? 'asc' : 'desc');
    }

    // Apply sort_options_grouped from API response if available and config doesn't have them
    if (res.sort_options_grouped && !this.config()?.sort_options_grouped) {
      this.config.update(c => c ? { ...c, sort_options_grouped: res.sort_options_grouped } : { sort_options_grouped: res.sort_options_grouped });
    }

    // Store filter options (returned on page 1 for manual albums)
    if (res.filter_options) {
      this.filterOptions.set(res.filter_options);
    }

    this.applyPhotos(res.photos, append);
  }

  private applyPhotos(photos: Photo[], append: boolean): void {
    // Ensure tags_list exists on all photos
    for (const p of photos) {
      if (!p.tags_list) {
        p.tags_list = p.tags ? p.tags.split(',').map(t => t.trim()) : [];
      }
      if (!p.persons) {
        p.persons = [];
      }
    }
    if (append) {
      this.photos.update(prev => [...prev, ...photos]);
    } else {
      this.photos.set(photos);
    }
  }

  // --- ResizeObserver ---

  private setupResizeObserver(): void {
    this.resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        this.containerWidth.set(Math.floor(entry.contentRect.width));
      }
    });

    const content = document.querySelector('mat-sidenav-content') ?? this.contentArea()?.nativeElement;
    if (content) {
      this.resizeObserver.observe(content);
    }
  }
}
