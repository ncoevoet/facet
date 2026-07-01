import { Component, inject, signal, computed, OnInit, effect, viewChild, DestroyRef, ElementRef, afterNextRender } from '@angular/core';
import { NgTemplateOutlet, NgClass } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
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
import { MatDatepickerModule, MatDatepickerInputEvent } from '@angular/material/datepicker';
import { toIsoDateString } from '../../utils/date-format';
import { firstValueFrom } from 'rxjs';
import { Photo } from '../../models/photo.model';
import { ApiService } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { I18nService } from '../../../core/services/i18n.service';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { SortGroupKeyPipe } from '../../pipes/sort-group-key.pipe';
import { FilterDisplayPipe } from '../../pipes/filter-display.pipe';
import { AdditionalFilterDef } from '../../models/filter-def.model';
import { computeRangeFilterUpdate } from '../../utils/range-filter';
import { useDesktopSignal } from '../../utils/media-query';
import { downloadAll } from '../../utils/download';
import {
  SECTION_ORDER, FILTERS_BY_SECTION,
  FilterGroup, SECTION_ICONS,
} from '../../../features/gallery/gallery-filter-sidebar.component';
import { PhotoCardComponent } from '../photo-card/photo-card.component';
import { SlideshowComponent } from '../../../features/gallery/slideshow.component';
import { InfiniteScrollDirective } from '../../directives/infinite-scroll.directive';
import { I18N } from '../../../core/i18n/keys';

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
  proofing_enabled?: boolean;
}

interface SharedPick {
  path: string;
  picked: boolean;
  comment: string | null;
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
    NgTemplateOutlet, NgClass,
    MatIconModule, MatButtonModule, MatProgressSpinnerModule, MatMenuModule,
    MatSelectModule, MatFormFieldModule, MatSnackBarModule, MatTooltipModule,
    MatSliderModule, MatSidenavModule, MatExpansionModule, MatInputModule, MatCheckboxModule, MatDatepickerModule,
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
            <p class="text-xs opacity-50 mt-1">{{ I18N.albums.photos_count | translate:{ count: total() } }}</p>
          </div>
          <div class="flex items-center gap-1 md:gap-2 flex-1 min-w-0">
            <mat-form-field class="flex-1 min-w-0 md:max-w-xs" subscriptSizing="dynamic">
              <mat-label>{{ I18N.gallery.sort | translate }}</mat-label>
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
                  <mat-option value="aggregate">{{ I18N.gallery.sort_aggregate | translate }}</mat-option>
                  <mat-option value="aesthetic">{{ I18N.gallery.sort_aesthetic | translate }}</mat-option>
                  <mat-option value="date_taken">{{ I18N.gallery.sort_date | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <button mat-icon-button (click)="toggleSortDirection()" [matTooltip]="sortDirection() === 'desc' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)">
              <mat-icon>{{ sortDirection() === 'desc' ? 'arrow_downward' : 'arrow_upward' }}</mat-icon>
            </button>
            @if (isManualAlbum()) {
              <button mat-icon-button (click)="filterDrawer.toggle()" [matTooltip]="I18N.gallery.filters | translate">
                <mat-icon [style.color]="filterDrawer.opened || activeFilterCount() ? 'var(--mat-sys-primary)' : ''">tune</mat-icon>
              </button>
            }
            <button mat-icon-button class="shrink-0 ml-auto" (click)="slideshowActive.set(true)" [matTooltip]="I18N.slideshow.start | translate">
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
                    {{ I18N.gallery.sidebar.equipment | translate }}
                    @if (filters().camera || filters().lens) {
                      <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ (filters().camera ? 1 : 0) + (filters().lens ? 1 : 0) }}</span>
                    }
                  </mat-panel-title>
                </mat-expansion-panel-header>
                <div class="flex flex-col gap-2 pb-2">
                  @if (filterOptions()?.cameras?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ I18N.gallery.camera | translate }}</mat-label>
                      <mat-select [value]="filters().camera" (selectionChange)="updateFilter('camera', $event.value)">
                        <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                        @for (c of filterOptions()!.cameras; track c.value) {
                          <mat-option [value]="c.value">{{ c.value }} ({{ c.count }})</mat-option>
                        }
                      </mat-select>
                    </mat-form-field>
                  }
                  @if (filterOptions()?.lenses?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ I18N.gallery.lens | translate }}</mat-label>
                      <mat-select [value]="filters().lens" (selectionChange)="updateFilter('lens', $event.value)">
                        <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
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
                    {{ I18N.gallery.sidebar.content | translate }}
                    @if (contentFilterCount()) {
                      <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ contentFilterCount() }}</span>
                    }
                  </mat-panel-title>
                </mat-expansion-panel-header>
                <div class="flex flex-col gap-2 pb-2">
                  @if (filterOptions()?.tags?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ I18N.gallery.tag | translate }}</mat-label>
                      <mat-select [value]="filters().tag" (selectionChange)="updateFilter('tag', $event.value)">
                        <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                        @for (t of filterOptions()!.tags; track t.value) {
                          <mat-option [value]="t.value">{{ t.value }} ({{ t.count }})</mat-option>
                        }
                      </mat-select>
                    </mat-form-field>
                  }
                  @if (filterOptions()?.patterns?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ I18N.gallery.composition_pattern | translate }}</mat-label>
                      <mat-select [value]="filters().composition_pattern" (selectionChange)="updateFilter('composition_pattern', $event.value)">
                        <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
                        @for (p of filterOptions()!.patterns; track p.value) {
                          <mat-option [value]="p.value">{{ ('composition_patterns.' + p.value) | translate }} ({{ p.count }})</mat-option>
                        }
                      </mat-select>
                    </mat-form-field>
                  }
                  @if (filterOptions()?.categories?.length) {
                    <mat-form-field subscriptSizing="dynamic" class="w-full">
                      <mat-label>{{ I18N.ui.filters.type | translate }}</mat-label>
                      <mat-select [value]="filters().category" (selectionChange)="updateFilter('category', $event.value)">
                        <mat-option value="">{{ I18N.gallery.all | translate }}</mat-option>
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
                  {{ I18N.gallery.sidebar.date | translate }}
                  @if (filters().date_from || filters().date_to) {
                    <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ (filters().date_from ? 1 : 0) + (filters().date_to ? 1 : 0) }}</span>
                  }
                </mat-panel-title>
              </mat-expansion-panel-header>
              <div class="flex flex-col gap-2 pb-2">
                <mat-form-field subscriptSizing="dynamic" class="w-full">
                  <mat-label>{{ I18N.gallery.date_from | translate }}</mat-label>
                  <input matInput [matDatepicker]="fromDp" [value]="filters().date_from" (dateChange)="onDateChange('date_from', $event)" />
                  <mat-datepicker-toggle matIconSuffix [for]="fromDp" />
                  <mat-datepicker #fromDp />
                </mat-form-field>
                <mat-form-field subscriptSizing="dynamic" class="w-full">
                  <mat-label>{{ I18N.gallery.date_to | translate }}</mat-label>
                  <input matInput [matDatepicker]="toDp" [value]="filters().date_to" (dateChange)="onDateChange('date_to', $event)" />
                  <mat-datepicker-toggle matIconSuffix [for]="toDp" />
                  <mat-datepicker #toDp />
                </mat-form-field>
              </div>
            </mat-expansion-panel>

            <!-- Display Options -->
            <mat-expansion-panel class="!mb-1">
              <mat-expansion-panel-header>
                <mat-panel-title class="flex items-center gap-2">
                  <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">display_settings</mat-icon>
                  {{ I18N.gallery.sidebar.display | translate }}
                  @if (displayFilterCount()) {
                    <span class="text-xs rounded-full min-w-[1.25rem] h-5 px-1.5 flex items-center justify-center bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] leading-none">{{ displayFilterCount() }}</span>
                  }
                </mat-panel-title>
              </mat-expansion-panel-header>
              <div class="flex flex-col gap-2 pb-2">
                <mat-checkbox
                  [checked]="filters().hide_blinks"
                  (change)="updateFilter('hide_blinks', $event.checked)"
                >{{ I18N.gallery.hide_blinks | translate }}</mat-checkbox>
                <mat-checkbox
                  [checked]="filters().hide_bursts"
                  (change)="updateFilter('hide_bursts', $event.checked)"
                >{{ I18N.gallery.hide_bursts | translate }}</mat-checkbox>
                <mat-checkbox
                  [checked]="filters().hide_duplicates"
                  (change)="updateFilter('hide_duplicates', $event.checked)"
                >{{ I18N.gallery.hide_duplicates | translate }}</mat-checkbox>
                <mat-checkbox
                  [checked]="filters().is_monochrome"
                  (change)="updateFilter('is_monochrome', $event.checked)"
                >{{ I18N.gallery.monochrome_only | translate }}</mat-checkbox>
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
                      <span class="text-xs opacity-60 px-1">{{ def.labelKey | translate }}</span>
                      <div class="flex items-center gap-1">
                        <mat-slider [min]="def.sliderMin" [max]="def.sliderMax" [step]="def.step" class="flex-1">
                          <input matSliderStartThumb
                            [value]="$any(filters())[def.minKey] ? +$any(filters())[def.minKey] : def.sliderMin"
                            (valueChange)="onDynamicRangeChange(def, 'min', $event)"
                            [attr.aria-label]="(def.labelKey | translate) + ' min'" />
                          <input matSliderEndThumb
                            [value]="$any(filters())[def.maxKey] ? +$any(filters())[def.maxKey] : def.sliderMax"
                            (valueChange)="onDynamicRangeChange(def, 'max', $event)"
                            [attr.aria-label]="(def.labelKey | translate) + ' max'" />
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
                  {{ I18N.gallery.reset_filters | translate }}
                </button>
              </div>
            }
          </div>
        </mat-sidenav>

        <mat-sidenav-content #contentArea>
          <div class="p-2">
            @if (isDesktop()) {
              @for (row of mosaicRows(); track row.photos[0]?.path ?? $index) {
                <div class="flex gap-2 mb-2">
                  @for (photo of row.photos; track photo.path; let i = $index) {
                    <div class="relative" [style.width.px]="row.widths[i]" [style.height.px]="row.height">
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
                      @if (proofingActive()) {
                        <ng-container [ngTemplateOutlet]="proofingButtons"
                                      [ngTemplateOutletContext]="{ $implicit: photo, btnSize: 'w-8 h-8', iconSize: '!text-lg !w-5 !h-5 !leading-5', commentPos: 'right-10' }" />
                      }
                    </div>
                  }
                </div>
              }
            } @else {
              <div class="grid grid-cols-1 gap-2">
                @for (photo of photos(); track photo.path) {
                  <div class="relative">
                    <app-photo-card
                      [photo]="photo"
                      [config]="cardConfig()"
                      [hideDetails]="true"
                      [isEditionMode]="false"
                      [isSelected]="selectedPaths().has(photo.path)"
                      (selectionChange)="toggleSelection($event.photo, $event.event)"
                      (doubleClicked)="openPhotoDetail($event)"
                    />
                    @if (proofingActive()) {
                      <ng-container [ngTemplateOutlet]="proofingButtons"
                                    [ngTemplateOutletContext]="{ $implicit: photo, btnSize: 'w-9 h-9', iconSize: '!text-xl !w-6 !h-6 !leading-6', commentPos: 'right-12' }" />
                    }
                  </div>
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
          <span class="text-sm font-medium shrink-0">{{ I18N.gallery.selection.count | translate:{ count: selectionCount() } }}</span>
          <div class="flex items-center gap-0 lg:gap-2 ml-auto">
            <button mat-icon-button class="lg:!hidden" (click)="clearSelection()" [matTooltip]="I18N.gallery.selection.clear | translate"><mat-icon>close</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="clearSelection()"><mat-icon>close</mat-icon> {{ I18N.gallery.selection.clear | translate }}</button>
            <button mat-icon-button class="lg:!hidden" (click)="copyPaths()" [matTooltip]="I18N.gallery.selection.copy_filenames | translate"><mat-icon>content_copy</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="copyPaths()"><mat-icon>content_copy</mat-icon> {{ I18N.gallery.selection.copy_filenames | translate }}</button>
            @if (auth.downloadProfiles().length) {
              <button mat-icon-button class="lg:!hidden" [matMenuTriggerFor]="dlMenu" [disabled]="downloading()" [matTooltip]="I18N.gallery.selection.download | translate">@if (downloading()) { <mat-spinner diameter="24" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> }</button>
              <button mat-flat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="dlMenu" [disabled]="downloading()">@if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> } {{ downloading() ? (I18N.photo_detail.downloading | translate) : (I18N.gallery.selection.download | translate) }}</button>
              <mat-menu #dlMenu="matMenu">
                <button mat-menu-item (click)="downloadSelected()"><mat-icon>image</mat-icon> {{ I18N.download.type_original | translate }}</button>
                @for (profile of auth.downloadProfiles(); track profile) {
                  <button mat-menu-item (click)="downloadSelected('darktable', profile)"><mat-icon>photo_filter</mat-icon> {{ profile }}</button>
                }
              </mat-menu>
            } @else {
              <button mat-icon-button class="lg:!hidden" (click)="downloadSelected()" [disabled]="downloading()" [matTooltip]="I18N.gallery.selection.download | translate">@if (downloading()) { <mat-spinner diameter="24" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> }</button>
              <button mat-flat-button class="!hidden lg:!inline-flex" (click)="downloadSelected()" [disabled]="downloading()">@if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> } {{ downloading() ? (I18N.photo_detail.downloading | translate) : (I18N.gallery.selection.download | translate) }}</button>
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

      <!-- Client proofing: sticky picks counter -->
      @if (proofingActive()) {
        <div class="fixed bottom-14 md:bottom-4 right-4 z-40 flex items-center gap-1.5 rounded-full px-3 py-1.5 bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] shadow-lg text-sm font-medium pointer-events-none">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4">favorite</mat-icon>
          {{ I18N.proofing.picks_count | translate:{ count: picksCount() } }}
        </div>
      }

      <!-- Client proofing: PIN / name setup -->
      @if (pinRequired() || askName()) {
        <div class="fixed bottom-0 left-0 right-0 z-[55] flex flex-wrap items-center gap-2 px-3 md:px-6 py-3 bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
          <mat-icon class="text-[var(--mat-sys-primary)] shrink-0">favorite</mat-icon>
          <span class="text-sm">{{ (pinRequired() ? I18N.proofing.pin_prompt : I18N.proofing.name_prompt) | translate }}</span>
          @if (pinRequired()) {
            <input #pinInputEl type="password" inputmode="numeric" autocomplete="off"
                   class="w-24 px-2 py-1.5 rounded border bg-transparent text-sm"
                   [class]="pinError() ? 'border-red-500' : 'border-[var(--mat-sys-outline-variant)]'"
                   [placeholder]="I18N.proofing.pin_label | translate"
                   [attr.aria-label]="I18N.proofing.pin_label | translate"
                   [attr.aria-invalid]="pinError()"
                   [attr.aria-describedby]="pinError() ? 'proofing-pin-error' : null"
                   [value]="pinInput()" (input)="pinInput.set($any($event.target).value)"
                   (keydown.enter)="submitProofingSetup()" />
          }
          <input #nameInputEl type="text" maxlength="100"
                 class="w-40 px-2 py-1.5 rounded border border-[var(--mat-sys-outline-variant)] bg-transparent text-sm"
                 [placeholder]="I18N.proofing.name_label | translate"
                 [attr.aria-label]="I18N.proofing.name_label | translate"
                 [value]="nameInput()" (input)="nameInput.set($any($event.target).value)"
                 (keydown.enter)="submitProofingSetup()" />
          <button mat-flat-button (click)="submitProofingSetup()">{{ I18N.proofing.start | translate }}</button>
          @if (!pinRequired()) {
            <button mat-button (click)="askName.set(false)">{{ I18N.proofing.skip | translate }}</button>
          }
          @if (pinError()) {
            <span id="proofing-pin-error" role="alert" class="text-sm text-red-500">{{ I18N.proofing.pin_invalid | translate }}</span>
          }
        </div>
      }

      <!-- Client proofing: inline comment editor -->
      @if (commentFor()) {
        <div class="fixed bottom-0 left-0 right-0 z-[60] flex items-center gap-2 px-3 md:px-6 py-3 bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
          <mat-icon class="opacity-60 shrink-0">chat_bubble_outline</mat-icon>
          <input #commentInputEl type="text" maxlength="2000"
                 class="flex-1 min-w-0 px-2 py-1.5 rounded border border-[var(--mat-sys-outline-variant)] bg-transparent text-sm"
                 [placeholder]="I18N.proofing.comment_placeholder | translate"
                 [attr.aria-label]="I18N.proofing.comment_placeholder | translate"
                 [value]="commentDraft()" (input)="commentDraft.set($any($event.target).value)"
                 (keydown.enter)="saveComment()" />
          <button mat-button (click)="commentFor.set(null)">{{ I18N.ui.buttons.cancel | translate }}</button>
          <button mat-flat-button (click)="saveComment()">{{ I18N.ui.buttons.save | translate }}</button>
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

      <!-- Client proofing: pick + comment overlay buttons (shared by mosaic & grid) -->
      <ng-template #proofingButtons let-photo let-btnSize="btnSize" let-iconSize="iconSize" let-commentPos="commentPos">
        <button class="absolute top-1 right-1 z-10 flex items-center justify-center rounded-full bg-black/40 text-white hover:bg-black/60"
                [ngClass]="btnSize"
                [matTooltip]="(pickedPaths().has(photo.path) ? I18N.proofing.unpick : I18N.proofing.pick) | translate"
                [attr.aria-label]="(pickedPaths().has(photo.path) ? I18N.proofing.unpick : I18N.proofing.pick) | translate"
                [attr.aria-pressed]="pickedPaths().has(photo.path)"
                (click)="togglePick(photo, $event)">
          <mat-icon [ngClass]="iconSize" [class.!text-red-400]="pickedPaths().has(photo.path)">{{ pickedPaths().has(photo.path) ? 'favorite' : 'favorite_border' }}</mat-icon>
        </button>
        <button class="absolute top-1 z-10 flex items-center justify-center rounded-full bg-black/40 text-white hover:bg-black/60"
                [ngClass]="[btnSize, commentPos]"
                [matTooltip]="I18N.proofing.comment | translate"
                [attr.aria-label]="I18N.proofing.comment | translate"
                (click)="openComment(photo, $event)">
          <mat-icon [ngClass]="iconSize" [class.!text-amber-300]="pickComments().has(photo.path)">{{ pickComments().has(photo.path) ? 'chat' : 'chat_bubble_outline' }}</mat-icon>
        </button>
      </ng-template>
    }
  `,
})
export class SharedViewComponent implements OnInit {
  protected readonly I18N = I18N;
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  private readonly contentArea = viewChild<ElementRef<HTMLElement>>('contentArea');
  private readonly scrollDirective = viewChild(InfiniteScrollDirective);
  // Proofing editor inputs — focused when their bar opens (a11y keyboard flow).
  private readonly commentInputEl = viewChild<ElementRef<HTMLInputElement>>('commentInputEl');
  private readonly pinInputEl = viewChild<ElementRef<HTMLInputElement>>('pinInputEl');
  private readonly nameInputEl = viewChild<ElementRef<HTMLInputElement>>('nameInputEl');

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
    const sectionCounts = this.rangeSectionActiveCounts();
    for (const key of SECTION_ORDER) {
      count += sectionCounts[key] ?? 0;
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
  private readonly desktop = useDesktopSignal();
  protected readonly isDesktop = this.desktop.isDesktop;

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

  // Client proofing (session JWT scoped to this album, carried explicitly —
  // the shared page has no logged-in user)
  private static readonly PROOFING_NAME_KEY = 'facet_proofing_name';
  private readonly http = inject(HttpClient);
  protected readonly proofingToken = signal<string | null>(null);
  protected readonly proofingActive = computed(() => this.proofingToken() !== null);
  protected readonly pinRequired = signal(false);
  protected readonly pinError = signal(false);
  protected readonly askName = signal(false);
  protected readonly pinInput = signal('');
  protected readonly nameInput = signal('');
  protected readonly pickedPaths = signal<Set<string>>(new Set());
  protected readonly pickComments = signal<Map<string, string>>(new Map());
  protected readonly picksCount = computed(() => this.pickedPaths().size);
  protected readonly commentFor = signal<Photo | null>(null);
  protected readonly commentDraft = signal('');
  private proofingInitDone = false;

  private entityId = 0;
  private token = '';
  private currentPage = 1;
  private sortApplied = false;
  private resizeObserver: ResizeObserver | null = null;

  constructor() {
    afterNextRender(() => {
      this.desktop.setup();
    });

    // Set up ResizeObserver once loading completes and mat-sidenav-content is in the DOM
    effect(() => {
      if (!this.loading() && !this.resizeObserver) {
        // Defer to next microtask so Angular renders the sidenav container first
        queueMicrotask(() => this.setupResizeObserver());
      }
    });
    // Move keyboard focus into the proofing editors when they open (the viewChild
    // signal updates once the @if renders its input, re-running the effect).
    effect(() => {
      if (this.commentFor()) this.commentInputEl()?.nativeElement.focus();
    });
    effect(() => {
      if (this.pinRequired() || this.askName()) {
        (this.pinRequired() ? this.pinInputEl() : this.nameInputEl())?.nativeElement.focus();
      }
    });
    this.destroyRef.onDestroy(() => {
      this.desktop.cleanup();
      if (this.rangeDebounce) clearTimeout(this.rangeDebounce);
      this.resizeObserver?.disconnect();
      this.resizeObserver = null;
    });
  }

  async ngOnInit(): Promise<void> {
    this.entityId = Number(this.route.snapshot.paramMap.get('albumId'));
    this.token = this.route.snapshot.queryParamMap.get('token') ?? '';

    if (!this.entityId || !this.token) {
      this.error.set(this.i18n.t(I18N.albums.invalid_share_link));
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

  protected onDateChange(key: keyof SharedFilters, event: MatDatepickerInputEvent<Date>): void {
    this.updateFilter(key, toIsoDateString(event.value));
  }

  private rangeDebounce: ReturnType<typeof setTimeout> | null = null;

  protected onDynamicRangeChange(def: AdditionalFilterDef, side: 'min' | 'max', value: number): void {
    const { key, value: filterValue } = computeRangeFilterUpdate(
      def, side, value, this.filters()[def.minKey],
    );
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
      this.snackBar.open(this.i18n.t(I18N.gallery.selection.copied), '', { duration: 2000 });
    });
  }

  protected async downloadSelected(type = 'original', profile?: string): Promise<void> {
    this.downloading.set(true);
    try {
      await downloadAll(
        [...this.selectedPaths()],
        path => this.api.downloadUrl(path, type, profile, this.token),
        url => this.api.getRaw(url),
      );
    } finally {
      this.downloading.set(false);
    }
  }

  // --- Client proofing ---

  private initProofing(): void {
    if (this.proofingInitDone) return;
    this.proofingInitDone = true;
    const storedName = localStorage.getItem(SharedViewComponent.PROOFING_NAME_KEY) ?? '';
    this.nameInput.set(storedName);
    void this.mintProofingSession(storedName, '');
  }

  private async mintProofingSession(clientName: string, pin: string): Promise<boolean> {
    try {
      const res = await firstValueFrom(this.http.post<{ session_token: string }>(
        `/api/shared/album/${this.entityId}/session`,
        { token: this.token, pin, client_name: clientName },
      ));
      this.proofingToken.set(res.session_token);
      this.pinRequired.set(false);
      this.pinError.set(false);
      if (!localStorage.getItem(SharedViewComponent.PROOFING_NAME_KEY)) {
        this.askName.set(true);
      }
      await this.loadPicks();
      return true;
    } catch (e: unknown) {
      if (e instanceof HttpErrorResponse && e.status === 403) {
        const detail = (e.error as { detail?: string } | null)?.detail;
        if (detail === 'pin_required') {
          this.pinRequired.set(true);
        } else if (detail === 'pin_invalid') {
          this.pinRequired.set(true);
          this.pinError.set(true);
        }
      }
      return false;
    }
  }

  protected async submitProofingSetup(): Promise<void> {
    const name = this.nameInput().trim();
    const ok = await this.mintProofingSession(name, this.pinInput().trim());
    if (ok) {
      if (name) localStorage.setItem(SharedViewComponent.PROOFING_NAME_KEY, name);
      this.askName.set(false);
    }
  }

  private proofingHeaders(): Record<string, string> {
    return { Authorization: `Bearer ${this.proofingToken()}` };
  }

  private async loadPicks(): Promise<void> {
    try {
      const res = await firstValueFrom(this.http.get<{ picks: SharedPick[] }>(
        `/api/shared/album/${this.entityId}/picks`,
        { headers: this.proofingHeaders() },
      ));
      const picked = new Set<string>();
      const comments = new Map<string, string>();
      for (const pick of res.picks) {
        if (pick.picked) picked.add(pick.path);
        if (pick.comment) comments.set(pick.path, pick.comment);
      }
      this.pickedPaths.set(picked);
      this.pickComments.set(comments);
    } catch {
      // Non-critical — picks simply start empty
    }
  }

  private async putPick(path: string, picked: boolean, comment?: string): Promise<boolean> {
    if (!this.proofingToken()) return false;
    try {
      await firstValueFrom(this.http.put(
        `/api/shared/album/${this.entityId}/picks`,
        comment === undefined ? { path, picked } : { path, picked, comment },
        { headers: this.proofingHeaders() },
      ));
      return true;
    } catch {
      this.snackBar.open(this.i18n.t(I18N.proofing.save_error), '', { duration: 3000 });
      return false;
    }
  }

  protected async togglePick(photo: Photo, event: Event): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    const picked = !this.pickedPaths().has(photo.path);
    this.pickedPaths.update(prev => {
      const next = new Set(prev);
      if (picked) next.add(photo.path); else next.delete(photo.path);
      return next;
    });
    const ok = await this.putPick(photo.path, picked);
    if (!ok) {
      this.pickedPaths.update(prev => {
        const next = new Set(prev);
        if (picked) next.delete(photo.path); else next.add(photo.path);
        return next;
      });
    }
  }

  protected openComment(photo: Photo, event: Event): void {
    event.preventDefault();
    event.stopPropagation();
    this.commentDraft.set(this.pickComments().get(photo.path) ?? '');
    this.commentFor.set(photo);
  }

  protected async saveComment(): Promise<void> {
    const photo = this.commentFor();
    if (!photo) return;
    const comment = this.commentDraft().trim();
    const ok = await this.putPick(photo.path, this.pickedPaths().has(photo.path), comment);
    if (ok) {
      this.pickComments.update(prev => {
        const next = new Map(prev);
        if (comment) next.set(photo.path, comment); else next.delete(photo.path);
        return next;
      });
      this.commentFor.set(null);
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
        this.error.set(this.i18n.t(I18N.albums.share_link_revoked));
      } else {
        this.error.set(this.i18n.t(I18N.albums.load_error));
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
    if (res.proofing_enabled) {
      this.initProofing();
    }
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
