import {
  Component,
  inject,
  computed,
  signal,
  OnInit,
  OnDestroy,
  viewChild,
  afterNextRender,
  effect,
  untracked,
  DestroyRef,
  Injector,
  TemplateRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { MatSidenav, MatSidenavModule, MatSidenavContent } from '@angular/material/sidenav';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatInputModule } from '@angular/material/input';
import { MatSliderModule } from '@angular/material/slider';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatBottomSheet, MatBottomSheetModule } from '@angular/material/bottom-sheet';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { GalleryStore, BatchResult } from './gallery.store';
import { Photo } from '../../shared/models/photo.model';
import { isTypingContext } from '../../shared/utils/keyboard';
import { UndoService } from '../../core/services/undo.service';
import { SequenceOverrideService, SequenceKind } from '../../core/services/sequence-override.service';
import { SequenceKindIconPipe } from '../../shared/pipes/sequence-kind.pipe';
import { IsSelectedPipe } from '../../shared/pipes/selection.pipe';
import { PhotoSetKindIconPipe, PhotoSetKindLabelPipe } from '../../shared/pipes/photo-set-kind.pipe';
import { AuthService } from '../../core/services/auth.service';
import { useDesktopSignal, DETAILS_RAIL_MIN_WIDTH_PX } from '../../shared/utils/media-query';
import { downloadAll } from '../../shared/utils/download';
import { basename, copyLines } from '../../shared/utils/clipboard';
import { I18nService } from '../../core/services/i18n.service';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { SlideshowComponent } from './slideshow.component';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { PhotoCardComponent } from '../../shared/components/photo-card/photo-card.component';
import { PhotoSkeletonComponent } from '../../shared/components/photo-skeleton/photo-skeleton.component';
import {
  GalleryRow, aspectOf, buildGridRows, buildMosaicRows, gridColumnCount, totalRowsHeight,
  windowRange,
} from './gallery-rows.util';
import { GalleryFilters, applyQueryParams, loadDisplayOptionsFromStorage } from './gallery-filters.util';
import { AlbumService, Album } from '../../core/services/album.service';
import { CreateAlbumDialogComponent } from '../albums/create-album-dialog.component';
import { ExportEditorDialogComponent } from './export-editor-dialog.component';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { I18N, I18N_KEYS } from '../../core/i18n/keys';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { MAX_COMPARE_PANES } from './synced-zoom.component';
import { HistogramMode, isHistogramMode } from '../../shared/utils/histogram';

const RENDER_MIGRATION_DISMISSED_KEY = 'facet_render_migration_dismissed';


@Component({
  selector: 'app-gallery',
  imports: [
    MatSidenavModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatButtonModule,
    MatFormFieldModule,
    MatSelectModule,
    MatInputModule,
    MatSliderModule,
    MatDialogModule,
    MatMenuModule,
    MatTooltipModule,
    MatBottomSheetModule,
    TranslatePipe,
    SequenceKindIconPipe,
    IsSelectedPipe,
    PhotoSetKindIconPipe,
    PhotoSetKindLabelPipe,
    MatSnackBarModule,
    PhotoTooltipComponent,
    SlideshowComponent,
    GalleryFilterSidebarComponent,
    PhotoCardComponent,
    PhotoSkeletonComponent,
    InfiniteScrollDirective,
  ],
  template: `
    <!-- Header-slot toolbar: the app shell renders this in the global header on lg+.
         Type filter + semantic search, rebound to the gallery store. -->
    <ng-template #galleryToolbar>
      <mat-form-field class="!hidden lg:!inline-flex w-52 ml-2" subscriptSizing="dynamic">
        <mat-label>{{ I18N.ui.filters.type | translate }}</mat-label>
        <mat-select panelWidth="auto" panelClass="nowrap-panel !max-h-[70vh]" [value]="store.filters().type" (selectionChange)="onTypeChange($event.value)">
          <mat-option value="">{{ I18N.gallery.all_photos | translate }}</mat-option>
          @for (t of store.types(); track t.id) {
            <mat-option [value]="t.id">{{ (t.id === 'top_picks' ? 'photo_types.top_picks' : 'category_names.' + t.id) | translate }} ({{ t.count }})</mat-option>
          }
        </mat-select>
      </mat-form-field>

      <!-- Search -->
      <mat-form-field class="!hidden 2xl:!inline-flex w-64" subscriptSizing="dynamic">
        <input
          matInput
          [placeholder]="I18N.gallery.search_placeholder | translate"
          [value]="store.filters().search"
          (keyup.enter)="onSearchChange($event)"
          (blur)="onSearchChange($event)"
        />
        @if (store.filters().search) {
          <button matSuffix mat-icon-button (click)="clearSearch()" [attr.aria-label]="I18N.gallery.clear_search | translate">
            <mat-icon>close</mat-icon>
          </button>
        } @else {
          <mat-icon matSuffix>search</mat-icon>
        }
      </mat-form-field>

      <!-- Keep top N%: server-rank the current view by the current sort and
           select the bottom (100-N)% for review/rejection via the selection bar. -->
      @if (auth.isEdition() && store.total() > 0) {
        <button mat-icon-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="keepTopMenu"
                [matTooltip]="I18N.gallery.keep_top.label | translate"
                [attr.aria-label]="I18N.gallery.keep_top.label | translate">
          <mat-icon>content_cut</mat-icon>
        </button>
        <mat-menu #keepTopMenu="matMenu" class="!max-w-none">
          <div class="p-4 w-80" tabindex="-1" (click)="$event.stopPropagation()" (keydown)="$event.stopPropagation()">
            <div class="text-xs opacity-70 mb-2">{{ I18N.gallery.keep_top.help | translate }}</div>
            <div class="flex items-center gap-2">
              <mat-slider class="flex-1 !min-w-0" [min]="5" [max]="95" [step]="5" [discrete]="true">
                <input matSliderThumb [value]="keepPercent()" (valueChange)="keepPercent.set($event)"
                       [attr.aria-label]="I18N.gallery.keep_top.label | translate" />
              </mat-slider>
              <span class="text-sm font-medium w-9 text-right">{{ keepPercent() }}%</span>
            </div>
            <div class="text-xs opacity-70 my-2">
              {{ I18N.gallery.keep_top.preview | translate:{ keep: keepPreviewKeep(), cut: keepPreviewCut(), total: store.total() } }}
            </div>
            <button mat-flat-button class="w-full" [disabled]="keepApplying() || keepPreviewCut() === 0" (click)="applyKeepTop()">
              @if (keepApplying()) {
                <mat-spinner diameter="18" class="!inline-block !align-baseline" [attr.aria-label]="I18N.ui.labels.loading | translate" ></mat-spinner>
              } @else {
                <mat-icon>checklist</mat-icon>
              }
              {{ I18N.gallery.keep_top.apply | translate }}
            </button>
          </div>
        </mat-menu>
      }
    </ng-template>

    <mat-sidenav-container class="h-full">
      <!-- One end drawer, two occupants. Material allows a single drawer per
           side, which is also the behaviour we want: the details rail and the
           filters compete for the same strip, so opening the filters hides the
           rail and closing them brings it back, without either changing how much
           room the grid gets. -->
      <mat-sidenav #filterDrawer disableClose="false" [mode]="isDesktop() ? 'side' : 'over'" position="end" class="w-[min(320px,100vw)] p-0"
        (openedChange)="onFilterDrawerChange($event)">
        @if (detailsRailVisible()) {
          <div class="p-2">
            @if (tooltipPhoto(); as p) {
              <app-photo-tooltip [photo]="p" [docked]="true" [pinned]="true"
                                 [histogramDefaultMode]="tooltipHistogramDefaultMode()"
                                 [indicatorPercent]="clippingIndicatorPercent()"
                                 (personSelected)="store.updateFilter('person_id', $event)" />
            } @else {
              <div class="rounded-xl p-4 text-sm opacity-60 text-center"
                   style="background: var(--facet-tooltip-bg); border: 1px solid var(--facet-tooltip-border)">
                {{ I18N.gallery.tooltip_mode.panel_empty | translate }}
              </div>
            }
          </div>
        } @else {
          <app-gallery-filter-sidebar />
        }
      </mat-sidenav>

      <!-- Main content. The drawer reserves its own strip, so the grid gets
           exactly the width it has whenever the filters are open. -->
      <mat-sidenav-content>
        <!-- Hidden-photos banner -->
        @if (showHiddenBanner()) {
          <div class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex items-center gap-3 text-sm">
            <mat-icon class="opacity-70 !text-base !w-5 !h-5">visibility_off</mat-icon>
            <span class="flex-1">
              {{ I18N.gallery.hidden_banner.message | translate:{ n: store.hiddenSummary().total } }}
            </span>
            <button mat-button class="!min-w-0" (click)="store.showAllHidden()">
              {{ I18N.gallery.hidden_banner.show_all | translate }}
            </button>
          </div>
        } @else if (canRestoreHidden()) {
          <div class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex items-center gap-3 text-sm">
            <mat-icon class="opacity-70 !text-base !w-5 !h-5">visibility</mat-icon>
            <span class="flex-1">
              {{ I18N.gallery.hidden_banner.showing_all | translate }}
            </span>
            <button mat-button class="!min-w-0" (click)="store.restoreHidden()">
              {{ I18N.gallery.hidden_banner.restore | translate }}
            </button>
          </div>
        }

        <!-- Set-scope chip: the photo-detail "open this set in the gallery" action.
             Never reflected in the URL (sequence_group_id is renumbered on every
             detection pass), so this is the only affordance out of it. -->
        @if (setScopeKind(); as kind) {
          <div class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex items-center gap-3 text-sm">
            <mat-icon class="opacity-70 !text-base !w-5 !h-5">{{ kind | photoSetKindIcon }}</mat-icon>
            <span class="flex-1">
              {{ I18N.gallery.set_scope.message | translate:{ kind: (kind | photoSetKindLabel | translate) } }}
            </span>
            <button mat-button class="!min-w-0" (click)="clearSetScope()">
              {{ I18N.ui.buttons.clear | translate }}
            </button>
          </div>
        }

        <!-- Thumbnail-migration notice. The grid reads photos.thumbnail, so a RAW
             scanned before the render fix keeps showing the old rendering until it
             is regenerated, and browsing never regenerates it. This banner is the
             only place the command that does is surfaced. -->
        @if (showRenderMigrationBanner()) {
          <div class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex items-center gap-3 text-sm">
            <mat-icon class="opacity-70 !text-base !w-5 !h-5">auto_fix_high</mat-icon>
            <span class="flex-1">
              {{ I18N.gallery.render_migration.message | translate:{ n: renderMigrationPending() } }}
              {{ I18N.gallery.render_migration.command_hint | translate:{ command: REFRESH_THUMBNAILS_COMMAND } }}
            </span>
            <button mat-button class="!min-w-0" (click)="dismissRenderMigration()">
              {{ I18N.ui.buttons.dismiss | translate }}
            </button>
          </div>
        }

        <!-- Album-scoped actions (album detail view). The scenes browse is open to
             all authenticated users; culling stays edition-only. -->
        @if (store.currentAlbum(); as album) {
          @if (!album.is_smart) {
            <div class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex items-center gap-3 text-sm">
              <mat-icon class="opacity-70 !text-base !w-5 !h-5">photo_library</mat-icon>
              <span class="flex-1 truncate">{{ album.name }}</span>
              <button mat-button class="!min-w-0" [matTooltip]="I18N.albums.scenes | translate"
                      (click)="openAlbumScoped('/scenes', album.id)">
                <mat-icon>movie_filter</mat-icon> {{ I18N.albums.scenes | translate }}
              </button>
              @if (auth.isEdition()) {
                <button mat-button class="!min-w-0" [matTooltip]="I18N.albums.cull | translate"
                        (click)="openAlbumScoped('/culling', album.id)">
                  <mat-icon>auto_delete</mat-icon> {{ I18N.albums.cull | translate }}
                </button>
              }
            </div>
          }
        }

        <!-- Photo grid / mosaic -->
        @if (store.photos().length) {
          @if (virtualOn()) {
            <!-- Windowed rendering: only rows near the viewport are in the DOM,
                 spacers preserve the scroll geometry -->
            <div
              id="gallery-rows-host"
              role="grid"
              tabindex="0"
              [attr.aria-label]="I18N.gallery.photo_grid | translate"
              [attr.aria-rowcount]="rowsModel().length"
              class="flex flex-col p-2 md:p-4 outline-none"
              (keydown)="onGridKeydown($event)"
              (focusout)="onGridFocusOut($event)"
            >
              <div [style.height.px]="topSpacer()" aria-hidden="true"></div>
              @for (row of visibleRows(); track row.photos[0].path) {
                <div class="flex gap-2 mb-2" [style.height.px]="row.height">
                  @for (photo of row.photos; track photo.path; let i = $index) {
                    <app-photo-card
                  [collapsedSequenceKinds]="collapsedSequenceKinds()"
                  [burstFramesVisible]="burstFramesVisible()"
                      [photo]="photo"
                      [attr.data-pidx]="row.startIndex + i"
                      [style.width.px]="row.widths[i]"
                      [style.height.px]="row.height"
                      class="shrink-0"
                      [hideDetails]="true"
                      [mosaicMode]="effectiveGalleryMode() === 'mosaic'"
                      [config]="store.config()"
                      [isSelected]="photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()"
                      [isActive]="row.startIndex + i === activeIndex()"
                      [gridHasActiveCard]="hasActivePhoto()"
                      [currentSort]="store.filters().sort"
                      [thumbSize]="thumbSize()"
                      [isEditionMode]="auth.isEdition()"
                      [personFilterId]="store.filters().person_id"
                      [tooltipMode]="tooltipMode()"
                      [panelActivation]="panelActivation()"
                      (selectionChange)="toggleSelection($event.photo, $event.event, row.startIndex + i)"
                      (tooltipShow)="showTooltip($event.event, $event.photo)"
                      (tooltipHide)="hideTooltip()"
                      (tagClicked)="store.updateFilter('tag', $event)"
                      (personFilterClicked)="filterByPerson($event)"
                      (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                      (openSimilarClicked)="openSimilar($event.photo, $event.mode)"
                      (openCritiqueClicked)="openCritique($event)"
                      (embedMetadataClicked)="embedMetadata($event)"
                      (openAddPersonClicked)="openAddPerson($event)"
                      (favoriteToggled)="store.toggleFavorite($event)"
                      (rejectedToggled)="store.toggleRejected($event)"
                      (starClicked)="store.setRating($event.photo.path, $event.star)"
                      (doubleClicked)="downloadPhoto($event)"
                    />
                  }
                </div>
              }
              <div [style.height.px]="bottomSpacer()" aria-hidden="true"></div>
            </div>
          } @else if (effectiveGalleryMode() === 'grid') {
            <div
              role="grid"
              tabindex="0"
              [attr.aria-label]="I18N.gallery.photo_grid | translate"
              class="grid grid-cols-1 gap-2 p-2 md:p-4 outline-none"
              [style.grid-template-columns]="galleryColsStyle()"
              (keydown)="onGridKeydown($event)"
              (focusout)="onGridFocusOut($event)"
            >
              @for (photo of store.photos(); track photo.path; let i = $index) {
                <app-photo-card
                  [collapsedSequenceKinds]="collapsedSequenceKinds()"
                  [burstFramesVisible]="burstFramesVisible()"
                  [photo]="photo"
                  [attr.data-pidx]="i"
                  [config]="store.config()"
                  [isSelected]="photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()"
                  [isActive]="i === activeIndex()"
                  [gridHasActiveCard]="hasActivePhoto()"
                  [hideDetails]="effectiveHideDetails()"
                  [currentSort]="store.filters().sort"
                  [thumbSize]="thumbSize()"
                  [isEditionMode]="auth.isEdition()"
                  [personFilterId]="store.filters().person_id"
                  [tooltipMode]="tooltipMode()"
                      [panelActivation]="panelActivation()"
                  [style.content-visibility]="'auto'"
                  [style.contain-intrinsic-size]="'auto ' + (cardWidth() + 80) + 'px'"
                  (selectionChange)="toggleSelection($event.photo, $event.event, i)"
                  (tooltipShow)="showTooltip($event.event, $event.photo)"
                  (tooltipHide)="hideTooltip()"
                  (tagClicked)="store.updateFilter('tag', $event)"
                  (personFilterClicked)="filterByPerson($event)"
                  (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                  (openSimilarClicked)="openSimilar($event.photo, $event.mode)"
                  (openCritiqueClicked)="openCritique($event)"
                  (embedMetadataClicked)="embedMetadata($event)"
                  (openAddPersonClicked)="openAddPerson($event)"
                  (favoriteToggled)="store.toggleFavorite($event)"
                  (rejectedToggled)="store.toggleRejected($event)"
                  (starClicked)="store.setRating($event.photo.path, $event.star)"
                  (doubleClicked)="downloadPhoto($event)"
                />
              }
            </div>
          } @else {
            <div
              role="grid"
              tabindex="0"
              [attr.aria-label]="I18N.gallery.photo_grid | translate"
              class="flex flex-col gap-2 p-2 md:p-4 outline-none"
              (keydown)="onGridKeydown($event)"
              (focusout)="onGridFocusOut($event)"
            >
              @for (row of mosaicRows(); track row.photos[0]?.path ?? $index) {
                <!-- No content-visibility on the row: it comes with paint
                     containment, which clipped the current photo's marker off
                     at the row's top and bottom edge. Each card below still
                     declares its own, so what is given up is only the
                     row-level grouping of the skip -- and only here, in the
                     branch that keeps every row in the DOM. -->
                <div class="flex gap-2">
                  @for (photo of row.photos; track photo.path; let i = $index) {
                    <app-photo-card
                  [collapsedSequenceKinds]="collapsedSequenceKinds()"
                  [burstFramesVisible]="burstFramesVisible()"
                      [photo]="photo"
                      [attr.data-pidx]="row.startIndex + i"
                      [style.width.px]="row.widths[i]"
                      [style.height.px]="row.height"
                      [hideDetails]="true"
                      [mosaicMode]="true"
                      [config]="store.config()"
                      [isSelected]="photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()"
                      [isActive]="row.startIndex + i === activeIndex()"
                      [gridHasActiveCard]="hasActivePhoto()"
                      [currentSort]="store.filters().sort"
                      [thumbSize]="thumbSize()"
                      [isEditionMode]="auth.isEdition()"
                      [personFilterId]="store.filters().person_id"
                      [tooltipMode]="tooltipMode()"
                      [panelActivation]="panelActivation()"
                      (selectionChange)="toggleSelection($event.photo, $event.event, row.startIndex + i)"
                      (tooltipShow)="showTooltip($event.event, $event.photo)"
                      (tooltipHide)="hideTooltip()"
                      (tagClicked)="store.updateFilter('tag', $event)"
                      (personFilterClicked)="filterByPerson($event)"
                      (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                      (openSimilarClicked)="openSimilar($event.photo, $event.mode)"
                      (openCritiqueClicked)="openCritique($event)"
                      (embedMetadataClicked)="embedMetadata($event)"
                      (openAddPersonClicked)="openAddPerson($event)"
                      (favoriteToggled)="store.toggleFavorite($event)"
                      (rejectedToggled)="store.toggleRejected($event)"
                      (starClicked)="store.setRating($event.photo.path, $event.star)"
                      (doubleClicked)="downloadPhoto($event)"
                    />
                  }
                </div>
              }
            </div>
          }
        }

        <!-- Loading skeletons -->
        @if (store.loading()) {
          <div role="status" [attr.aria-label]="I18N.gallery.loading_photos | translate" aria-busy="true">
            @if (!store.photos().length) {
              <div
                class="grid grid-cols-1 gap-2 p-2 md:p-4"
                [style.grid-template-columns]="galleryColsStyle()"
              >
                @for (i of skeletonItems(); track i) {
                  <app-photo-skeleton [height]="cardWidth()" />
                }
              </div>
            } @else {
              <div class="flex gap-2 p-2 md:p-4">
                @for (i of appendSkeletonItems(); track i) {
                  <app-photo-skeleton class="flex-1" [height]="cardWidth()" />
                }
              </div>
            }
          </div>
        }

        <!-- Load error state -->
        @if (!store.loading() && store.loadError()) {
          <div class="flex flex-col items-center justify-center gap-4 p-16" role="alert">
            <mat-icon class="!text-6xl !w-16 !h-16 text-[var(--mat-sys-error)]">cloud_off</mat-icon>
            <p class="text-lg text-center">{{ I18N.gallery.load_error.message | translate }}</p>
            <button mat-flat-button color="primary" (click)="store.loadPhotos()">
              <mat-icon>refresh</mat-icon>
              {{ I18N.gallery.load_error.retry | translate }}
            </button>
          </div>
        }

        <!-- Empty state -->
        @if (!store.loading() && !store.loadError() && store.photos().length === 0 && store.total() === 0) {
          <div class="flex flex-col items-center justify-center gap-4 p-16 opacity-60">
            <mat-icon class="!text-6xl !w-16 !h-16">photo_library</mat-icon>
            <p class="text-lg">{{ I18N.gallery.no_photos | translate }}</p>
            @if (store.activeFilterCount()) {
              <button mat-stroked-button (click)="store.resetFilters()">
                {{ I18N.gallery.reset_filters | translate }}
              </button>
            } @else if (canShowScanButton()) {
              <button mat-flat-button color="primary" (click)="openScanLauncher()">
                <mat-icon>add_photo_alternate</mat-icon>
                {{ I18N.scan.get_started | translate }}
              </button>
            }
          </div>
        }

        <!-- Infinite scroll sentinel -->
        <div appInfiniteScroll (scrollReached)="onScrollReached()" class="h-1"></div>
      </mat-sidenav-content>
    </mat-sidenav-container>

    <!-- Scroll-to-top button -->
    @if (showScrollTop() && !selectionCount()) {
      <button
        mat-mini-fab
        class="!fixed right-4 lg:right-6 bottom-[60px] lg:bottom-6 z-40"
        [matTooltip]="I18N.gallery.scroll_to_top | translate"
        [attr.aria-label]="I18N.gallery.scroll_to_top | translate"
        (click)="scrollToTop()"
      >
        <mat-icon>arrow_upward</mat-icon>
      </button>
    }

    <!-- Slideshow overlay -->
    @if (store.slideshowActive()) {
      <app-slideshow
        [photos]="store.photos()"
        [hasMore]="store.hasMore()"
        [loading]="store.loading()"
      />
    }

    <!-- Photo details tooltip (single instance, repositioned on hover, hidden on small/touch devices) -->
    @if (!tooltipDisabled() && !panelMode() && (tooltipMode() === 'click' || (isDesktop() && !isTouchDevice()))) {
      <app-photo-tooltip
        [photo]="tooltipPhoto()"
        [x]="tooltipX()"
        [y]="tooltipY()"
        [flipped]="tooltipFlipped()"
        [pinned]="tooltipMode() === 'click'"
        [histogramDefaultMode]="tooltipHistogramDefaultMode()"
        [indicatorPercent]="clippingIndicatorPercent()"
        (personSelected)="store.updateFilter('person_id', $event)"
      />
    }


    <!-- Selection action bar -->
    @if (selectionCount()) {
      <div data-selection-bar class="fixed bottom-0 left-0 right-0 z-50 flex flex-wrap items-center justify-center gap-1 lg:gap-3 px-2 lg:px-6 py-1 lg:py-3 max-lg:pb-[max(0.25rem,env(safe-area-inset-bottom))] bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
        <!-- Every loaded photo is selected, but the view runs past the pages
             fetched so far. Offer the rest explicitly on its own line (w-full
             in a wrapping row) rather than silently widening what was asked. -->
        @if (offerWholeView()) {
          <div class="w-full flex flex-wrap items-center justify-center gap-2 text-xs opacity-80">
            <span>{{ I18N.gallery.selection.view_scope_offer | translate:{ count: store.photos().length } }}</span>
            <button mat-button class="!text-xs" (click)="selectWholeView()">{{ I18N.gallery.selection.view_scope_select_all | translate:{ total: store.total() } }}</button>
          </div>
        }
        <span data-selection-status tabindex="-1" class="text-sm font-medium shrink-0">{{ (viewScoped() ? I18N.gallery.selection.view_scope_active : I18N.gallery.selection.count) | translate:{ count: selectionCount() } }}</span>
        <div class="flex items-center gap-0 lg:gap-2">
          <button mat-icon-button class="lg:!hidden" (click)="clearSelection()" [matTooltip]="I18N.gallery.selection.clear | translate" [attr.aria-label]="I18N.gallery.selection.clear | translate"><mat-icon>close</mat-icon></button>
          <button mat-button class="!hidden lg:!inline-flex" (click)="clearSelection()"><mat-icon>close</mat-icon> {{ I18N.gallery.selection.clear | translate }}</button>
          @if (!allLoadedSelected()) {
            <button mat-icon-button class="lg:!hidden" (click)="selectAll()" [matTooltip]="I18N.gallery.selection.select_all | translate" [attr.aria-label]="I18N.gallery.selection.select_all | translate"><mat-icon>select_all</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="selectAll()"><mat-icon>select_all</mat-icon> {{ I18N.gallery.selection.select_all | translate }}</button>
          }
          <button mat-icon-button class="lg:!hidden" (click)="invertSelection()" [matTooltip]="I18N.gallery.selection.invert | translate" [attr.aria-label]="I18N.gallery.selection.invert | translate"><mat-icon>flip</mat-icon></button>
          <button mat-button class="!hidden lg:!inline-flex" (click)="invertSelection()"><mat-icon>flip</mat-icon> {{ I18N.gallery.selection.invert | translate }}</button>
          @if (canCompareSelection()) {
            <button mat-icon-button class="lg:!hidden" (click)="compareSelection()" [matTooltip]="I18N.gallery.selection.compare | translate" [attr.aria-label]="I18N.gallery.selection.compare | translate"><mat-icon>compare</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="compareSelection()"><mat-icon>compare</mat-icon> {{ I18N.gallery.selection.compare | translate }}</button>
          }
          <!-- Mobile: single Actions trigger opening a touch-friendly bottom sheet -->
          <button mat-flat-button class="lg:!hidden" (click)="openActionsSheet()" [disabled]="downloading()">
            @if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline" [attr.aria-label]="I18N.ui.labels.loading | translate" ></mat-spinner> } @else { <mat-icon>more_horiz</mat-icon> }
            {{ I18N.gallery.selection.actions | translate }}
          </button>
          @if (auth.isEdition()) {
            <button mat-button class="!hidden lg:!inline-flex" (click)="batchFavorite()"><mat-icon>favorite</mat-icon> {{ I18N.gallery.selection.favorite | translate }}</button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="batchReject()"><mat-icon>thumb_down</mat-icon> {{ I18N.gallery.selection.reject | translate }}</button>
            <button mat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="rateMenu"><mat-icon>star</mat-icon> {{ I18N.gallery.selection.rate | translate }}</button>
            <mat-menu #rateMenu="matMenu">
              @for (star of [1, 2, 3, 4, 5]; track star) {
                <button mat-menu-item (click)="batchRate(star)">
                  {{ '★'.repeat(star) }}
                </button>
              }
              <button mat-menu-item (click)="batchRate(0)">
                {{ I18N.gallery.selection.clear | translate }}
              </button>
            </mat-menu>
          }
          @if (auth.isEdition() && store.config()?.features?.show_albums) {
            <button mat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="albumMenu"><mat-icon>photo_library</mat-icon> {{ I18N.albums.add_photos | translate }}</button>
            <mat-menu #albumMenu="matMenu">
              @for (album of albumOptions(); track album.id) {
                <button mat-menu-item (click)="addToAlbum(album.id)">{{ album.name }}</button>
              }
              <button mat-menu-item (click)="createAlbumAndAdd()">
                <mat-icon>add</mat-icon>
                {{ I18N.albums.create | translate }}
              </button>
            </mat-menu>
          }
          <!-- The other half of the panorama correction: culling can only fix a
               set the detector found, and an undetected sweep appears in no
               culling group at all. Here the frames are in front of the user. -->
          @if (auth.isEdition()) {
            <button mat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="sequenceMenu"><mat-icon>panorama_photosphere</mat-icon> {{ I18N.gallery.selection.mark_sequence | translate }}</button>
            <mat-menu #sequenceMenu="matMenu">
              <button mat-menu-item (click)="markAsPanorama('panorama')">
                <mat-icon>{{ 'panorama' | sequenceKindIcon }}</mat-icon>
                {{ I18N.gallery.selection.mark_panorama | translate }}
              </button>
              <button mat-menu-item (click)="markAsPanorama('hdr_panorama')">
                <mat-icon>{{ 'hdr_panorama' | sequenceKindIcon }}</mat-icon>
                {{ I18N.gallery.selection.mark_hdr_panorama | translate }}
              </button>
            </mat-menu>
          }
          <button mat-button class="!hidden lg:!inline-flex" (click)="copyPaths()"><mat-icon>content_copy</mat-icon> {{ I18N.gallery.selection.copy_filenames | translate }}</button>
          @if (auth.isEdition()) {
            <button mat-button class="!hidden lg:!inline-flex" (click)="openExportDialog()"><mat-icon>drive_file_move</mat-icon> {{ I18N.export.action | translate }}</button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="openCullDialog()"><mat-icon>folder_move</mat-icon> {{ I18N.cull.action | translate }}</button>
          }
          @if (auth.downloadProfiles().length) {
            <button mat-flat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="dlMenu" [disabled]="downloading()">@if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline" [attr.aria-label]="I18N.ui.labels.loading | translate" ></mat-spinner> } @else { <mat-icon>download</mat-icon> } {{ downloading() ? (I18N.photo_detail.downloading | translate) : (I18N.gallery.selection.download | translate) }}</button>
            <mat-menu #dlMenu="matMenu">
              <button mat-menu-item (click)="downloadSelected()"><mat-icon>image</mat-icon> {{ I18N.download.type_original | translate }}</button>
              @for (profile of auth.downloadProfiles(); track profile) {
                <button mat-menu-item (click)="downloadSelected('darktable', profile)"><mat-icon>photo_filter</mat-icon> {{ profile }}</button>
              }
              <button mat-menu-item (click)="downloadSelected('raw')"><mat-icon>raw_on</mat-icon> {{ I18N.download.type_raw | translate }}</button>
            </mat-menu>
          } @else {
            <button mat-flat-button class="!hidden lg:!inline-flex" (click)="downloadSelected()" [disabled]="downloading()">@if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline" [attr.aria-label]="I18N.ui.labels.loading | translate" ></mat-spinner> } @else { <mat-icon>download</mat-icon> } {{ downloading() ? (I18N.photo_detail.downloading | translate) : (I18N.gallery.selection.download | translate) }}</button>
          }
        </div>
      </div>
    }
  `,
  host: {
    class: 'block h-full',
    '(document:keydown.control.a)': 'onSelectAllShortcut($event)',
  },
})
export class GalleryComponent implements OnInit, OnDestroy {
  protected readonly I18N = I18N_KEYS;
  protected readonly store = inject(GalleryStore);
  protected readonly auth = inject(AuthService);
  protected readonly canShowScanButton = computed(
    () => this.auth.isSuperadmin() && this.auth.hasFeature('show_scan_button'),
  );
  private readonly snackBar = inject(MatSnackBar);
  private readonly bottomSheet = inject(MatBottomSheet);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialog);
  private readonly albumService = inject(AlbumService);
  private readonly photoActions = inject(PhotoActionsService);
  private readonly undoService = inject(UndoService);
  private readonly sequenceOverrides = inject(SequenceOverrideService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(ApiService);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly liveAnnouncer = inject(LiveAnnouncer);
  private readonly galleryToolbar = viewChild<TemplateRef<unknown>>('galleryToolbar');

  // Album options for "Add to album" menu
  protected readonly albumOptions = signal<Album[]>([]);
  protected readonly downloading = signal(false);

  // "Keep top N%" cull dial: keep the top N% of the current view, select the rest.
  protected readonly keepPercent = signal(20);
  protected readonly keepApplying = signal(false);
  protected readonly keepPreviewKeep = computed(() => Math.ceil(this.store.total() * this.keepPercent() / 100));
  protected readonly keepPreviewCut = computed(() => Math.max(0, this.store.total() - this.keepPreviewKeep()));

  private resizeObserver: ResizeObserver | null = null;
  private readonly scrollDirective = viewChild(InfiniteScrollDirective);
  private readonly filterDrawer = viewChild<MatSidenav>('filterDrawer');
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);
  private readonly scrollContent = viewChild(MatSidenavContent);

  /** True once the gallery content is scrolled far enough to show the scroll-to-top button. */
  protected readonly showScrollTop = signal(false);

  // Sidebar scroll preservation
  private savedFilterScroll = 0;

  // Tooltip state
  protected readonly tooltipPhoto = signal<Photo | null>(null);
  protected readonly tooltipX = signal(0);
  protected readonly tooltipY = signal(0);
  protected readonly tooltipFlipped = signal(false);

  // Selection state lives in the store (survives navigation, visible to services)
  protected readonly selectedPaths = this.store.selectedPaths;
  protected readonly excludedPaths = this.store.excludedPaths;
  protected readonly selectionCount = this.store.selectionCount;
  /** True while the selection means "the whole filtered view", not a path list. */
  protected readonly viewScoped = this.store.viewScopeSelected;

  /** True when every loaded photo is already selected. */
  protected readonly allLoadedSelected = computed(() =>
    this.store.photos().length > 0 && this.selectionCount() >= this.store.photos().length,
  );

  /**
   * Whether to offer widening the selection to the whole filtered view.
   *
   * Only when it would actually add something: the loaded photos are all
   * selected, the view holds more than those, and the selection is not already
   * view-scoped. Withheld under a similarity/semantic view, where there is no
   * filter payload that reproduces what is on screen.
   */
  protected readonly offerWholeView = computed(() =>
    !this.viewScoped()
    && this.store.canScopeSelectionToView()
    && this.allLoadedSelected()
    && this.store.total() > this.store.photos().length,
  );

  /** True when the device has no hover capability (touch device) */
  protected readonly isTouchDevice = signal(false);

  /** Thumbnail request size derived from card width (2x for retina, capped at 640). Returns 640 on mobile (full-width cards). */
  readonly thumbSize = computed(() => {
    if (this.isTouchDevice()) return 640;
    return Math.min(this.store.cardWidth() * 2, 640);
  });

  /** Card min-width from store for the responsive grid */
  readonly cardWidth = computed(() => this.store.cardWidth() || 168);

  /** Inline `grid-template-columns` for the plain (non-virtualized) CSS grid:
   * auto-fill by the density slider on desktop, an explicit column count on
   * mobile so a narrow viewport never floors below MOBILE_MIN_COLUMNS (keeps
   * this grid in sync with the virtualized row model and keyboard navigation). */
  readonly galleryColsStyle = computed(() =>
    this.isDesktop()
      ? `repeat(auto-fill, minmax(${this.cardWidth()}px, 1fr))`
      : `repeat(${this.gridColumns()}, 1fr)`,
  );

  /** Skeleton placeholders for the initial load (matches a typical first page). */
  protected readonly skeletonItems = computed(() => Array.from({ length: 24 }, (_, i) => i));
  /** Skeleton placeholders for an appended page (single row). */
  protected readonly appendSkeletonItems = computed(() => {
    const width = this.containerWidth() || 1200;
    const cols = Math.max(1, Math.floor(width / (this.cardWidth() + 8)));
    return Array.from({ length: cols }, (_, i) => i);
  });

  /** Whether the viewport is md+ (768px) — mosaic is only available on desktop */
  private readonly desktop = useDesktopSignal({
    onChange: matches => { if (!matches) this.tooltipPhoto.set(null); },
  });
  protected readonly isDesktop = this.desktop.isDesktop;

  /**
   * Whether the viewport is wide enough to give up a 320px strip permanently.
   *
   * The details rail is not merely a desktop feature: at the md breakpoint the
   * drawer would take more than a third of the window and leave the grid too
   * narrow to browse, so it wants its own, higher bar.
   */
  private readonly railWide = useDesktopSignal({ breakpointPx: DETAILS_RAIL_MIN_WIDTH_PX });

  /** Effective gallery mode: force grid on small viewports */
  readonly effectiveGalleryMode = computed(() =>
    (this.isDesktop() && this.containerWidth() > 0) ? this.store.galleryMode() : 'grid',
  );

  /** Whether to hide photo details below the thumbnails */
  readonly effectiveHideDetails = computed(() => this.store.filters().hide_details);

  /** Tooltip mode signal — 'hover' | 'click' | 'off' */
  readonly tooltipMode = computed(() => this.store.filters().tooltip_mode);
  /** Which gesture(s) retarget the docked panel — only meaningful when tooltipMode is 'panel'. */
  readonly panelActivation = computed(() => this.store.filters().panel_activation);
  /** Whether tooltip is fully disabled (off mode) — used for skipping rendering and hover handlers */
  readonly tooltipDisabled = computed(() => this.tooltipMode() === 'off');

  /** Docked rail needs real width, not merely "not a phone". */
  readonly panelMode = computed(() => this.tooltipMode() === 'panel' && this.railWide.isDesktop());

  /**
   * Whether the end drawer currently shows details rather than filters.
   *
   * The filters win while they are open: they are an explicit, transient action,
   * and the rail is a standing preference to come back to once they are closed.
   */
  readonly detailsRailVisible = computed(
    () => this.panelMode() && !this.store.filterDrawerOpen(),
  );

  /** Sequence kinds whose sets are currently collapsed behind one frame.
   *
   *  A tile only earns its set badge while the matching toggle is hiding the
   *  rest of the set. With the toggle off every frame is on screen in its own
   *  right, and badging all of them would say nothing.
   */
  readonly collapsedSequenceKinds = computed(() => {
    const f = this.store.filters();
    const kinds: string[] = [];
    if (f.hide_brackets) kinds.push('bracket');
    if (f.hide_panoramas) kinds.push('panorama', 'hdr_panorama');
    return kinds;
  });

  /** Whether a burst's non-lead frames are on screen.
   *
   *  Drives the "best" badge, and is the mirror of the rule above: with
   *  `hide_bursts` on -- the default -- every burst photo in the grid is
   *  already its group's lead, so badging each of them would say nothing. */
  readonly burstFramesVisible = computed(() => !this.store.filters().hide_bursts);

  /** Percent of clipped pixels a channel must exceed to earn a histogram marker. */
  readonly clippingIndicatorPercent = computed(
    () => this.store.config()?.clipping?.indicator_percent ?? 1);

  /** House default for the tooltip's OWN histogram channel mode -- independent
   *  of the detail panel's `viewer.clipping.histogram_mode`. A stale/unrecognised
   *  config value degrades to 'luma' rather than the widget rendering nothing. */
  readonly tooltipHistogramDefaultMode = computed<HistogramMode>(() => {
    const configured = this.store.config()?.clipping?.tooltip_histogram_mode;
    return isHistogramMode(configured) ? configured : 'luma';
  });

  /** Show the hidden-photos banner when filters are hiding rows and at least one is on. */
  readonly showHiddenBanner = computed(() => {
    const f = this.store.filters();
    return this.store.hiddenSummary().total > 0
      && (f.hide_blinks || f.hide_bursts || f.hide_duplicates || f.hide_brackets || f.hide_panoramas);
  });

  /** Offer the restore only while all five are still off, so it never fights a manual change.
   *  The stash itself (and showAllHidden()/restoreHidden()) lives on GalleryStore — the
   *  timeline's reachability banner offers the same affordance and needs the same state. */
  readonly canRestoreHidden = computed(() => {
    const stash = this.store.hiddenFiltersStash();
    if (!stash) return false;
    const f = this.store.filters();
    return !f.hide_blinks && !f.hide_bursts && !f.hide_duplicates && !f.hide_brackets
      && !f.hide_panoramas;
  });

  /** The active set-scope kind (from photo-detail's "open this set"), or null. */
  readonly setScopeKind = computed(() => {
    const f = this.store.filters();
    if (f.sequence_kind && f.sequence_group_id) return f.sequence_kind;
    if (f.burst_group_id) return 'burst';
    if (f.duplicate_group_id) return 'duplicate';
    return null;
  });

  /** The command that migrates the whole library in one go. */
  protected readonly REFRESH_THUMBNAILS_COMMAND = 'python facet.py --refresh-thumbnails';

  /** RAW rows still on the pre-fix rendering, as of the last config load. */
  readonly renderMigrationPending = computed(
    () => this.store.config()?.render_migration?.pending ?? 0,
  );

  /**
   * Dismissal is remembered, like the culling swipe hint: the notice is advisory
   * and the migration can take hours, so re-raising it on every visit would be
   * nagging rather than informing.
   */
  private readonly renderMigrationDismissed = signal(
    localStorage.getItem(RENDER_MIGRATION_DISMISSED_KEY) === 'true',
  );

  readonly showRenderMigrationBanner = computed(
    () => this.renderMigrationPending() > 0 && !this.renderMigrationDismissed(),
  );

  dismissRenderMigration(): void {
    localStorage.setItem(RENDER_MIGRATION_DISMISSED_KEY, 'true');
    this.renderMigrationDismissed.set(true);
  }

  clearSetScope(): void {
    const kind = this.setScopeKind();
    if (!kind) return;
    const updates: Partial<GalleryFilters> = {
      sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
    };
    const stored = loadDisplayOptionsFromStorage();
    const defaults = this.store.config()?.defaults;
    if (kind === 'burst') updates.hide_bursts = stored.hide_bursts ?? (defaults?.hide_bursts ?? true);
    else if (kind === 'duplicate') updates.hide_duplicates = stored.hide_duplicates ?? (defaults?.hide_duplicates ?? true);
    else if (kind === 'bracket') updates.hide_brackets = stored.hide_brackets ?? (defaults?.hide_brackets ?? true);
    else updates.hide_panoramas = stored.hide_panoramas ?? (defaults?.hide_panoramas ?? true);
    void this.store.updateFilters(updates);
  }

  /** Container width for mosaic layout (updated via ResizeObserver) */
  protected readonly containerWidth = signal(0);

  // --- Virtual scrolling (row windowing with top/bottom spacers) ---

  /** Gap between cards/rows in pixels (matches the gap-2 Tailwind class). */
  private static readonly ROW_GAP = 8;
  /** Pixels rendered beyond the viewport in both directions. */
  private static readonly OVERSCAN = 1200;

  /** Scroll offset relative to the rows container, and viewport height. */
  protected readonly relScrollTop = signal(0);
  protected readonly viewportH = signal(0);

  /**
   * Windowing active: user flag on, AND heights are deterministic - mosaic
   * always is; grid only with details hidden (the default). Grid with
   * details shown falls back to full rendering.
   */
  readonly virtualOn = computed(() =>
    this.store.virtualScroll()
    && this.containerWidth() > 0
    && (this.effectiveGalleryMode() === 'mosaic' || this.effectiveHideDetails()),
  );

  /** Unified row model for the active mode. */
  readonly rowsModel = computed<GalleryRow[]>(() => {
    const photos = this.store.photos();
    // Rows live inside the p-2 md:p-4 container - subtract its padding
    const width = this.containerWidth() - (this.isDesktop() ? 32 : 16);
    if (!photos.length || width <= 0) return [];
    if (this.effectiveGalleryMode() === 'mosaic') {
      return buildMosaicRows(photos, width, this.cardWidth(), GalleryComponent.ROW_GAP);
    }
    return buildGridRows(
      photos, width, this.cardWidth(), GalleryComponent.ROW_GAP,
      this.effectiveHideDetails(), this.isDesktop(),
    );
  });

  readonly totalRowsHeight = computed(() => totalRowsHeight(this.rowsModel()));

  private readonly visibleRange = computed(() =>
    windowRange(this.rowsModel(), this.relScrollTop(), this.viewportH() || 900, GalleryComponent.OVERSCAN),
  );

  readonly visibleRows = computed(() => {
    const { first, last } = this.visibleRange();
    return last < first ? [] : this.rowsModel().slice(first, last + 1);
  });

  readonly topSpacer = computed(() => {
    const { first, last } = this.visibleRange();
    const rows = this.rowsModel();
    return last < first || !rows.length ? 0 : rows[first].offset;
  });

  readonly bottomSpacer = computed(() => {
    const { last } = this.visibleRange();
    const rows = this.rowsModel();
    if (!rows.length || last < 0 || last >= rows.length) return 0;
    const bottomEdge = rows[last].offset + rows[last].height;
    return Math.max(0, this.totalRowsHeight() - bottomEdge);
  });

  /** Update the window position from the live DOM geometry (rAF-throttled). */
  private updateWindowPosition(): void {
    const viewport = this.scrollContent()?.getElementRef().nativeElement as HTMLElement | undefined;
    const rowsHost = document.getElementById('gallery-rows-host');
    if (!viewport) return;
    this.viewportH.set(viewport.clientHeight);
    if (rowsHost) {
      const rel = viewport.getBoundingClientRect().top - rowsHost.getBoundingClientRect().top;
      this.relScrollTop.set(Math.max(0, rel));
    }
  }

  /** Mosaic row layout: justified rows of photos preserving aspect ratios */
  readonly mosaicRows = computed(() => {
    const photos = this.store.photos();
    // Rows live inside the p-2 md:p-4 container - subtract its padding
    const width = this.containerWidth() - (this.isDesktop() ? 32 : 16);
    if (!photos.length || width <= 0) return [];
    return buildMosaicRows(photos, width, this.store.cardWidth() || 168, GalleryComponent.ROW_GAP);
  });

  constructor() {
    afterNextRender(() => {
      this.isTouchDevice.set(window.matchMedia('(hover: none)').matches);
      this.desktop.setup();
      this.railWide.setup();
      this.setupResizeObserver();
      this.setupScrollTracking();
    });

    // Project the gallery toolbar into the global header slot (rendered lg-only by the shell)
    effect(() => {
      const t = this.galleryToolbar();
      if (t) this.headerSlot.set(t);
    });

    // Sync store.filterDrawerOpen signal → mat-sidenav. The details rail shares
    // this drawer, so it keeps the strip open on its own once the filters close.
    effect(() => {
      const open = this.store.filterDrawerOpen() || this.panelMode();
      const drawer = this.filterDrawer();
      if (!drawer) return;
      if (open) drawer.open();
      else drawer.close();
    });

    // Re-check sentinel whenever photos, card width, gallery mode, or hide_details change
    effect(() => {
      this.store.photos(); // track dependency
      this.store.cardWidth(); // track dependency
      this.store.galleryMode(); // track dependency
      this.effectiveHideDetails(); // track dependency — toggling details changes card height
      this.scrollDirective()?.recheck();
      // Clear tooltip when photos change (prevents stale tooltips after filter changes)
      untracked(() => this.tooltipPhoto.set(null));
      // Re-measure the virtual window once the new rows are in the DOM
      requestAnimationFrame(() => this.updateWindowPosition());
    });

    // A tooltip shown under one mode's semantics (hover tracks the cursor,
    // click toggles on the same photo, panel docks and keeps the last one on
    // mouse-out) must not carry over into another's. Most visibly: a photo
    // left in tooltipPhoto by hover survives a switch to click mode, so the
    // FIRST click on that same photo matches showTooltip's toggle condition
    // and hides instead of shows. A dedicated effect rather than folding this
    // into the one above: that one also recomputes scroll/virtual-window
    // layout, which a mode switch has no reason to trigger.
    effect(() => {
      this.tooltipMode(); // track dependency
      untracked(() => this.tooltipPhoto.set(null));
    });
  }

  async ngOnInit(): Promise<void> {
    this.pageHelp.setDescription(I18N.gallery.help);
    // Read (and clear) BEFORE tryRestoreView: a scoped "open this set" request
    // means the user wants that new scoped view, never a resumed previous one.
    const setScope = this.consumeSetScopeState();
    if (!setScope && this.tryRestoreView()) return;
    // Reset album state to avoid stale singleton data; loadConfig() resets filters from scratch
    this.store.currentAlbum.set(null);
    this.store.initializing.set(true);
    await this.store.loadConfig();
    // Apply the ephemeral set scope AFTER loadConfig, which replaces `filters`
    // wholesale -- applying it before would just be discarded. Never in the
    // URL: sequence_group_id is renumbered on every detection pass, so a
    // bookmarked/shared/reloaded link must never resolve to a different set.
    if (setScope) {
      this.store.filters.update(current => ({ ...current, ...setScope }));
    }
    // Set album_id from route path param (for /album/:albumId route)
    const albumId = this.route.snapshot.paramMap.get('albumId');
    if (albumId) {
      try {
        const album = await firstValueFrom(this.albumService.get(+albumId));
        if (album.smart_filter_json) {
          // Apply saved filters BEFORE setting currentAlbum (avoids effect saving defaults)
          const savedFilters = JSON.parse(album.smart_filter_json);
          this.store.filters.update(current => ({ ...current, ...savedFilters, album_id: albumId }));
        } else {
          this.store.filters.update(current => ({ ...current, album_id: albumId }));
        }
        this.store.currentAlbum.set(album);
      } catch {
        this.store.filters.update(current => ({ ...current, album_id: albumId }));
      }
    }
    // Photos first — a slow filter-option endpoint must never hold back the grid
    await this.store.loadPhotos();
    this.store.initializing.set(false);
    void Promise.all([this.store.loadFilterOptions(), this.store.loadTypeCounts()]);
    // IntersectionObserver fires too early before DOM paint — defer recheck
    requestAnimationFrame(() => setTimeout(() => this.scrollDirective()?.recheck()));
    if (this.store.config()?.features?.show_albums) {
      firstValueFrom(this.albumService.list()).then(res =>
        this.albumOptions.set(res.albums.filter(a => !a.is_smart)),
      ).catch(() => {});
    }
  }

  ngOnDestroy(): void {
    this.pageHelp.setDescription(null);
    const t = this.galleryToolbar();
    if (t) this.headerSlot.clear(t);
    this.saveViewSnapshot();
    this.resizeObserver?.disconnect();
    this.desktop.cleanup();
    this.railWide.cleanup();
  }

  /** Capture scroll + query state so back-navigation can skip the reload. */
  private saveViewSnapshot(): void {
    if (!this.store.photos().length) return;
    this.store.viewSnapshot.set({
      scrollTop: this.scrollContent()?.measureScrollOffset('top') ?? 0,
      albumId: this.route.snapshot.paramMap.get('albumId'),
      filterKey: this.store.filterKey(),
    });
  }

  /**
   * Read, and immediately clear, the ephemeral set-scope filters carried from
   * photo-detail's "open this set in the gallery" action via router
   * navigation `state` rather than the URL -- `sequence_group_id` is
   * renumbered on every detection pass, so it must never be bookmarkable or
   * shareable. Browsers keep `history.state` for the current history entry
   * across a reload, so it is cleared right after being read: a reload of a
   * scoped gallery must fall back to the normal unscoped view, not silently
   * resolve to a possibly-different set.
   */
  private consumeSetScopeState(): Partial<GalleryFilters> | null {
    const state = history.state as Record<string, unknown> | undefined;
    const scope = state?.['setScope'] as Partial<GalleryFilters> | undefined;
    if (!scope) return null;
    const rest: Record<string, unknown> = { ...state };
    delete rest['setScope'];
    history.replaceState(rest, '', location.href);
    return scope;
  }

  /**
   * Restore the previous gallery view if the route + filters are unchanged.
   * Skips loadConfig/loadPhotos entirely; background data stays fresh via
   * loadTypeCounts/loadFilterOptions.
   */
  private tryRestoreView(): boolean {
    const snap = this.store.viewSnapshot();
    this.store.viewSnapshot.set(null);
    if (!snap || !this.store.photos().length) return false;
    if (snap.albumId !== this.route.snapshot.paramMap.get('albumId')) return false;
    const candidate = applyQueryParams(this.store.filters(), this.route.snapshot.queryParams);
    if (snap.filterKey !== this.store.filterKey(candidate)) return false;
    afterNextRender(() => {
      this.scrollContent()?.scrollTo({ top: snap.scrollTop });
      requestAnimationFrame(() => setTimeout(() => this.scrollDirective()?.recheck()));
    }, { injector: this.injector });
    void this.store.loadTypeCounts();
    void this.store.loadFilterOptions();
    return true;
  }

  /** Save/restore sidebar scroll position on drawer open/close */
  onFilterDrawerChange(open: boolean): void {
    // The details rail holds this drawer open by itself, so an `open` it caused
    // must not be recorded as "the user asked for filters" — otherwise closing
    // the filters would immediately re-open them and the toggle would be stuck.
    if (open && this.detailsRailVisible()) return;
    this.store.setFilterDrawerOpen(open);
    const sidebarEl = document.querySelector('app-gallery-filter-sidebar div[data-scroll]') as HTMLElement | null;
    if (!sidebarEl) return;

    if (!open) {
      this.savedFilterScroll = sidebarEl.scrollTop;
    } else {
      queueMicrotask(() => { sidebarEl.scrollTop = this.savedFilterScroll; });
    }
  }

  /** Selecting a photo with the pointer also moves the grid's cursor onto it,
   *  so the next rating keystroke lands on the photo the user just clicked
   *  rather than on wherever the arrow keys were left. The index comes from the
   *  template because that is where it is already known -- it is the same
   *  expression each call site feeds `data-pidx`, which is what `focusCard`
   *  looks a card up by, so the cursor, the marker and the focus target cannot
   *  drift apart. Deriving it here from the path would be a second answer to a
   *  question the caller has already answered.
   *
   *  Focus is moved explicitly rather than left to the browser. A pointer click
   *  does land focus on the card by itself, but only because `onSelect` lets
   *  the default through, and only for a caller that really is a click; saying
   *  it out loud makes the rule hold for any caller. It is also what lifts the
   *  newly current card clear of the action bar that this very selection has
   *  just raised over it. */
  protected toggleSelection(photo: Photo, event: MouseEvent | undefined, index: number): void {
    this.store.toggleSelection(photo, event);
    this.setCursor(index);
    this.focusCard(index);
  }

  protected clearSelection(): void {
    this.store.clearSelection();
    this.restoreCursorFocus();
  }

  /** Keep DOM focus wherever the marker is, so that a drawn marker always means
   *  a live keyboard.
   *
   *  `onGridKeydown` is bound on the grid containers, so the arrows and the
   *  rating keys only reach this component while focus is inside one of them.
   *  The marker is component state and outlives focus, which is where the two
   *  come apart: every route that empties the selection is driven from the
   *  action bar, and the bar unmounts the instant the count reaches zero, so
   *  the control that was just clicked takes focus down with it and the browser
   *  falls back to `<body>`. The photo stays framed in tertiary while nothing
   *  typed at it does anything -- the marker promising a keyboard that is no
   *  longer listening.
   *
   *  Nothing is taken while focus is already inside a grid. That leaves Escape
   *  alone: it is the one route in from the inside, standing on the very card
   *  it would be sent to, so handling it here would only re-focus and re-scroll
   *  a card the user has not left. And nothing is taken when the cursor is not
   *  on a photo that is actually in the results, because then no marker is
   *  drawn and there is no promise to keep -- the card still sitting at that
   *  index until the grid re-renders is not the photo the cursor means.
   *
   *  Nothing is scrolled, either. The card is still exactly where the user left
   *  it; an action bar unmounting is not a reason to move the viewport under
   *  them. That also settles the windowed-out case: a card that is not in the
   *  DOM holds no focus to hand back, so the retry that would page it in is
   *  deliberately not entered. */
  private restoreCursorFocus(): void {
    if (!this.hasActivePhoto()) return;
    if (document.activeElement?.closest('[role="grid"]')) return;
    this.focusCard(this.activeIndex(), false, false);
  }

  /**
   * Both of these branch on whether anything is selected yet — an empty
   * selection widens to the whole filtered view, a partial one to the loaded
   * photos. The branch lives in the store rather than here so the three entry
   * points (this bar, the mobile actions sheet, Ctrl+A) cannot drift apart.
   */
  protected selectAll(): void {
    this.store.selectAll();
    this.anchorFocusAndAnnounceSelectionStatus();
  }

  protected invertSelection(): void {
    this.store.invertSelection();
    this.announceSelectionStatus();
  }

  protected selectWholeView(): void {
    this.store.selectWholeView();
    this.anchorFocusAndAnnounceSelectionStatus();
  }

  /**
   * Announce the selection the way the bar states it, reusing the count span's
   * own translated text rather than adding a string all six language bundles
   * would need. Every widening action announces; only the two that destroy
   * their own button also move focus, below.
   */
  private announceSelectionStatus(): void {
    const key = this.viewScoped() ? I18N.gallery.selection.view_scope_active : I18N.gallery.selection.count;
    void this.liveAnnouncer.announce(this.i18n.t(key, { count: this.selectionCount() }));
  }

  /**
   * Both whole-view toggle buttons ("select all in view" and its sibling
   * "select all") live inside an `@if` keyed on the very selection state their
   * own click flips (`offerWholeView()` / `allLoadedSelected()`), so Angular
   * removes the still-focused button on the same tick and focus falls back to
   * `document.body` with nothing announced. The selection-count span right
   * after them states the new count either way and is never removed by either
   * toggle, so it serves as the focus anchor (`tabindex="-1"` keeps it out of
   * the tab order).
   *
   * Invert deliberately does NOT come through here: its button survives its own
   * click, so moving focus would cost a keyboard user the place they need to
   * press it again.
   */
  private anchorFocusAndAnnounceSelectionStatus(): void {
    document.querySelector<HTMLElement>('[data-selection-status]')?.focus();
    this.announceSelectionStatus();
  }

  /** Two panes is the smallest useful compare; past four they are too small to read. */
  protected readonly canCompareSelection = computed(
    () => this.selectionCount() >= 2 && this.selectionCount() <= MAX_COMPARE_PANES,
  );

  protected async compareSelection(): Promise<void> {
    const selected = new Set(this.store.selectedLoadedPaths());
    // Keep the grid's order rather than selection order: comparing left-to-right
    // as they are laid out is what the user is already looking at.
    const photos = this.store.photos().filter(p => selected.has(p.path)).slice(0, MAX_COMPARE_PANES);
    if (photos.length < 2) return;
    const { CompareSelectedDialogComponent } = await import('./compare-selected-dialog.component');
    this.dialog.open(CompareSelectedDialogComponent, {
      data: { photos },
      width: '96vw',
      height: '92vh',
      maxWidth: '96vw',
      autoFocus: false,
    });
  }

  /** Ctrl+A selects all loaded photos unless focus is in an input or a dialog is open. */
  protected onSelectAllShortcut(event: Event): void {
    const target = event.target as HTMLElement | null;
    if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
    if (target?.isContentEditable) return;
    if (document.querySelector('mat-dialog-container, mat-bottom-sheet-container')) return;
    if (!this.store.photos().length) return;
    event.preventDefault();
    this.selectAll();
  }

  /**
   * The selected paths as strings, fetched from the server when the selection
   * is the whole view.
   *
   * Only for the handful of actions that genuinely need filenames on the client
   * (copy, download, add-to-album): everything else sends the filter and lets
   * the server derive the rows, which is the point of the view scope.
   *
   * Under view scope that fetch materialises the entire filtered set — a
   * multi-megabyte response the user never explicitly asked for, and for
   * add-to-album a write of one row per photo — so it is confirmed against the
   * server's own count first, in whichever words fit the action. A null
   * `confirmMessageKey` is for the caller that already asks in its own words
   * (`downloadSelected`, past DOWNLOAD_CONFIRM_PHOTOS): two dialogs for one
   * click is worse than one. The size bound itself lives one level down, in
   * `pathsInView`, so all three consumers inherit it.
   */
  private async resolveSelectionPaths(
    confirmMessageKey: string | null = I18N.gallery.selection.view_scope_confirm_message,
  ): Promise<string[] | null> {
    if (!this.viewScoped()) return [...this.selectedPaths()];
    if (confirmMessageKey !== null && await this.confirmWholeView(confirmMessageKey) === null) {
      return null;
    }
    return this.store.pathsInView();
  }

  protected async copyPaths(): Promise<void> {
    // Copying changes nothing, so it says so rather than borrowing the
    // mutation wording every other whole-view action confirms with.
    const paths = await this.resolveSelectionPaths(I18N.gallery.selection.view_scope_copy_message);
    if (!paths?.length) return;
    await copyLines(paths.map(basename));
    this.snackBar.open(this.i18n.t(I18N.gallery.selection.copied), '', { duration: 2000 });
  }

  /** Above this size, undo (chunked per-photo inverse calls) is not offered. */
  private static readonly UNDO_MAX_PHOTOS = 500;

  /** Above this many photos a download is confirmed first: it is one blob fetch
   *  plus one synthetic anchor click per photo, and a whole-view selection (or
   *  a "Keep top N%" one) turns that into thousands. */
  private static readonly DOWNLOAD_CONFIRM_PHOTOS = 50;

  /** The server caps a sequence correction at 500 frames, and a set is a
   *  handful of frames one camera shot together — so it is never "the view". */
  private static readonly MARK_SEQUENCE_MAX_PHOTOS = 500;

  /**
   * Ask before a mutation runs over the whole filtered view.
   *
   * The count comes from the server rather than from `total()`, which is only
   * ever whichever page response landed last. Returns the number shown to the
   * user, or null if they declined (or it could not be fetched) — the caller
   * checks the server's own count against it afterwards.
   *
   * `messageKey` names what the action will actually do to those photos; the
   * default states a mutation, which is what every batch write is.
   */
  private async confirmWholeView(
    messageKey: string = I18N.gallery.selection.view_scope_confirm_message,
  ): Promise<number | null> {
    const total = await this.store.countInView();
    if (total === null) return null;
    const count = Math.max(0, total - this.excludedPaths().size);
    if (count === 0) {
      this.snackBar.open(this.i18n.t(I18N.gallery.selection.view_scope_empty), '', { duration: 3000 });
      return null;
    }
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.gallery.selection.view_scope_confirm_title),
        message: this.i18n.t(messageKey, { count }),
      },
    });
    const confirmed = await firstValueFrom(ref.afterClosed());
    return confirmed ? count : null;
  }

  private async executeBatchAction(
    action: (paths: string[]) => Promise<BatchResult | null>,
    i18nKey: string,
    extraParams?: Record<string, string | number>,
  ): Promise<void> {
    const viewScoped = this.viewScoped();
    let announced: number | null = null;
    if (viewScoped) {
      announced = await this.confirmWholeView();
      if (announced === null) return;
    }
    const paths = [...this.selectedPaths()];
    const result = await action(paths);
    if (result === null) return; // store reverted and notified
    this.clearSelection();
    const params = { count: result.count, ...extraParams };
    // Undo replays inverse calls from a snapshot, and the snapshot can only
    // cover LOADED photos -- so offering it for an action that reached further
    // would promise to restore 64 of 5,000. Gate on coverage, not just size.
    const covered = result.snapshot.size === result.targeted;
    if (covered && result.snapshot.size > 0 && result.snapshot.size <= GalleryComponent.UNDO_MAX_PHOTOS) {
      this.undoService.register({
        labelKey: i18nKey,
        labelParams: params,
        undo: async () => {
          await this.store.restoreSnapshot(result.snapshot);
          // The snapshot's keys, not `paths`: they are the same set whenever
          // undo is offered at all (that is what `covered` asserts), and they
          // are the only ones a view-scoped action ever named.
          this.store.restoreSelection(result.snapshot.keys());
        },
      });
    } else {
      this.snackBar.open(this.i18n.t(i18nKey, params), '', { duration: 2000 });
    }
    // The view can move between the count and the write (another session, a
    // scan). Say so rather than absorbing it: the user approved a number.
    if (announced !== null && announced !== result.count) {
      this.snackBar.open(
        this.i18n.t(I18N.gallery.selection.view_scope_mismatch, { count: result.count, announced }),
        '', { duration: 5000 },
      );
    }
  }

  protected async batchFavorite(): Promise<void> {
    await this.executeBatchAction(p => this.store.batchFavorite(p), 'gallery.selection.batch_favorited');
  }

  protected async batchReject(): Promise<void> {
    await this.executeBatchAction(p => this.store.batchReject(p), 'gallery.selection.batch_rejected');
  }

  protected async batchRate(rating: number): Promise<void> {
    await this.executeBatchAction(p => this.store.batchRating(p, rating), 'gallery.selection.batch_rated', { rating });
  }

  /**
   * Declare the selected frames one panorama the detector missed.
   *
   * Not routed through `executeBatchAction`: that undoes by restoring a photo's
   * favorite/reject/rating snapshot, and nothing here touches those — the
   * inverse of a correction is dropping it, which is its own endpoint. Two
   * frames is the floor because one frame is not a set.
   */
  protected async markAsPanorama(kind: SequenceKind): Promise<void> {
    // Unlike the flag mutations, this one keeps its path list: the server caps
    // the correction at MARK_SEQUENCE_MAX_PHOTOS frames and there is no
    // filter-scoped form, because declaring a whole view to be one panorama is
    // not a thing anyone means.
    if (this.viewScoped()) {
      this.snackBar.open(this.i18n.t(I18N.gallery.selection.mark_needs_paths), '', { duration: 4000 });
      return;
    }
    const paths = [...this.selectedPaths()];
    if (paths.length < 2) {
      this.snackBar.open(this.i18n.t(I18N.gallery.selection.mark_needs_two), '', { duration: 3000 });
      return;
    }
    if (paths.length > GalleryComponent.MARK_SEQUENCE_MAX_PHOTOS) {
      this.snackBar.open(
        this.i18n.t(I18N.gallery.selection.mark_too_many,
                    { count: paths.length, max: GalleryComponent.MARK_SEQUENCE_MAX_PHOTOS }),
        '', { duration: 4000 },
      );
      return;
    }
    try {
      await this.sequenceOverrides.setAsync(paths, kind);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
      return;
    }
    this.store.patchSequenceOverride(paths, kind);
    this.clearSelection();
    this.undoService.register({
      labelKey: I18N.gallery.selection.marked_panorama,
      labelParams: { count: paths.length },
      undo: async () => {
        await this.sequenceOverrides.clearAsync(paths);
        this.store.patchSequenceOverride(paths, null);
        this.store.restoreSelection(paths);
      },
    });
  }

  /**
   * "Keep top N%": ask the server for the bottom (100-N)% of the current view by
   * the current sort, select them, and let the user reject via the selection bar.
   */
  protected async applyKeepTop(): Promise<void> {
    if (this.keepApplying()) return;
    this.keepApplying.set(true);
    try {
      const res = await this.store.selectBottomPercent(this.keepPercent());
      if (!res) return;
      const msg = res.truncated
        ? this.i18n.t(I18N.gallery.keep_top.truncated, { count: res.paths.length, cut: res.cut })
        : this.i18n.t(I18N.gallery.keep_top.selected, { count: res.cut });
      this.snackBar.open(msg, '', { duration: 3000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.keepApplying.set(false);
    }
  }

  protected downloadPhoto(photo: Photo): void {
    this.router.navigate(['/photo'], {
      queryParams: { path: photo.path },
      state: { photo },
    });
  }

  /** Open the mobile bulk-actions bottom sheet and dispatch the chosen action. */
  protected async openActionsSheet(): Promise<void> {
    const { GalleryActionsSheetComponent } = await import('./gallery-actions-sheet.component');
    const ref = this.bottomSheet.open(GalleryActionsSheetComponent, {
      data: {
        count: this.selectionCount(),
        isEdition: this.auth.isEdition(),
        showAlbums: !!this.store.config()?.features?.show_albums,
        albums: this.albumOptions(),
        downloadProfiles: this.auth.downloadProfiles(),
        canCompare: this.canCompareSelection(),
      },
    });
    const action = await firstValueFrom(ref.afterDismissed());
    if (!action) return;
    switch (action.kind) {
      case 'favorite': await this.batchFavorite(); break;
      case 'reject': await this.batchReject(); break;
      case 'rate': await this.batchRate(action.rating); break;
      case 'album': await this.addToAlbum(action.albumId); break;
      case 'create-album': await this.createAlbumAndAdd(); break;
      case 'invert': this.invertSelection(); break;
      case 'compare': await this.compareSelection(); break;
      case 'export': this.openExportDialog(); break;
      case 'cull': await this.openCullDialog(); break;
      case 'copy': await this.copyPaths(); break;
      case 'mark-panorama': await this.markAsPanorama(action.sequenceKind); break;
      case 'download': await this.downloadSelected(action.type, action.profile); break;
    }
  }

  protected async downloadSelected(type = 'original', profile?: string): Promise<void> {
    // Confirms below in its own words, against the count it actually resolved.
    const paths = await this.resolveSelectionPaths(null);
    if (!paths?.length) return;
    // One blob fetch and one synthetic anchor click per photo, serially: past a
    // few dozen that is a browser-melting amount of work to start by accident,
    // and both "Keep top N%" and a whole-view selection reach thousands.
    if (paths.length > GalleryComponent.DOWNLOAD_CONFIRM_PHOTOS && !await this.confirmDownload(paths.length)) {
      return;
    }
    this.downloading.set(true);
    try {
      await downloadAll(
        paths,
        path => this.api.downloadUrl(path, type, profile),
        url => this.api.getRaw(url),
      );
    } finally {
      this.downloading.set(false);
    }
  }

  private async confirmDownload(count: number): Promise<boolean> {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.gallery.selection.download_confirm_title, { count }),
        message: this.i18n.t(I18N.gallery.selection.download_confirm_message, { count }),
      },
    });
    return !!await firstValueFrom(ref.afterClosed());
  }

  protected openAlbumScoped(path: string, albumId: number): void {
    void this.router.navigate([path], { queryParams: { album: albumId } });
  }

  async addToAlbum(albumId: number): Promise<void> {
    // No filter-scoped form server-side, so a whole-view selection resolves to
    // paths here rather than adding nothing at all. Filing photos into an album
    // writes album_photos rows and leaves the photos themselves untouched, so
    // it must not confirm in the wording of a mutation.
    const paths = await this.resolveSelectionPaths(I18N.gallery.selection.view_scope_album_message);
    if (!paths?.length) return;
    await firstValueFrom(this.albumService.addPhotos(albumId, paths));
    this.snackBar.open(this.i18n.t(I18N.albums.photos_added), '', { duration: 2000 });
    this.clearSelection();
  }

  async createAlbumAndAdd(): Promise<void> {
    const ref = this.dialog.open(CreateAlbumDialogComponent, { width: '400px' });
    const album = await firstValueFrom(ref.afterClosed());
    if (!album) return;
    this.albumOptions.update(list => [album, ...list]);
    await this.addToAlbum(album.id);
  }

  async openScanLauncher(): Promise<void> {
    const { ScanLauncherComponent } = await import('../scan/scan-launcher.component');
    const ref = this.dialog.open(ScanLauncherComponent, { width: '36rem' });
    const completed = await firstValueFrom(ref.afterClosed());
    if (completed) {
      await this.store.loadTypeCounts();
      await this.store.loadPhotos();
    }
  }

  openExportDialog(): void {
    const albumId = this.route.snapshot.paramMap.get('albumId');
    if (albumId) {
      this.dialog.open(ExportEditorDialogComponent, { width: '420px', data: { albumId: +albumId } });
      return;
    }
    // Under view scope the dialog gets the filter, not a path list, so the
    // export is not bounded by the endpoint's 10,000-path cap.
    this.dialog.open(ExportEditorDialogComponent, {
      width: '420px',
      data: this.viewScoped()
        ? { filters: this.store.filterPayload(), exclude: [...this.excludedPaths()], count: this.selectionCount() }
        : { paths: [...this.selectedPaths()] },
    });
  }

  async openCullDialog(): Promise<void> {
    const viewScoped = this.viewScoped();
    const paths = [...this.selectedPaths()];
    if (!viewScoped && !paths.length) return;
    const { CullDialogComponent } = await import('./cull-dialog.component');
    const ref = this.dialog.open(CullDialogComponent, {
      width: '32rem',
      data: {
        paths,
        // Same trade as the export: the filter travels instead of the paths, so
        // a whole-view cull is not bounded by the endpoint's 10,000-path cap.
        filters: viewScoped ? this.store.filterPayload() : null,
        exclude: viewScoped ? [...this.excludedPaths()] : [],
        count: this.selectionCount(),
        trashAvailable: this.store.config()?.cull?.trash_available ?? false,
        allowTrash: this.store.config()?.cull?.allow_trash ?? false,
      },
    });
    const applied = await firstValueFrom(ref.afterClosed());
    if (applied) {
      // Reload first: clearing the selection hands focus back to the marked
      // card, and the rows the cull has just moved away are still standing in
      // the list until this returns.
      await this.store.loadPhotos();
      this.clearSelection();
    }
  }

  openCritique(photo: Photo): void {
    this.photoActions.openCritique(photo);
  }

  embedMetadata(photo: Photo): void {
    this.photoActions.embedMetadata(photo);
  }

  showTooltip(event: MouseEvent, photo: Photo): void {
    const mode = this.tooltipMode();
    if (mode === 'off') return;
    // The rail is parked, so none of the placement maths below applies to it.
    // Only while it is actually shown, though: with the mode selected on a
    // viewport too narrow for the rail, skipping the maths left the floating
    // tooltip to render at a stale coordinate in the middle of the page.
    if (mode === 'panel' && this.panelMode()) {
      this.tooltipPhoto.set(photo);
      return;
    }
    // Hover mode is meaningless on touch (mouseenter fires once on tap and
    // sticks) so we suppress it there. Click mode is the intended touch path
    // and must work — only block hover on touch devices.
    if (mode === 'hover' && this.isTouchDevice()) return;
    // In click mode, toggle: clicking the same photo hides the tooltip.
    if (mode === 'click' && this.tooltipPhoto() === photo) {
      this.hideTooltip();
      return;
    }
    const card = (event.currentTarget as HTMLElement)?.closest('.relative.rounded-lg') as HTMLElement ?? event.currentTarget as HTMLElement;
    const rect = card.getBoundingClientRect();
    const padding = 16;
    const isLandscape = aspectOf(photo) > 1;
    const vh = window.innerHeight;
    const vw = window.innerWidth;

    const thumbImg = (card.querySelector('img') as HTMLImageElement | null);
    const thumbAspect = (thumbImg?.naturalWidth && thumbImg.naturalHeight)
      ? thumbImg.naturalWidth / thumbImg.naturalHeight
      : aspectOf(photo);
    const tooltipNatH = thumbAspect > 1 ? 640 / thumbAspect : 640;

    let tooltipWidth: number;
    let tooltipHeight: number;
    if (isLandscape) {
      const imgH = Math.min(tooltipNatH, vh * 0.35);
      const imgW = imgH * thumbAspect;
      tooltipWidth = Math.ceil(imgW) + 24;
      // 260 = scoring panel (~160) + tech/EXIF row (~60) + tags row (~40)
      tooltipHeight = Math.ceil(imgH) + 260;
    } else {
      const imgH = Math.min(tooltipNatH, vh * 0.5);
      const imgW = imgH * thumbAspect;
      tooltipWidth = Math.ceil(imgW) + 260 + 12 + 24;
      // 100 = tech/EXIF row (~60) + tags row (~40)
      tooltipHeight = Math.max(Math.ceil(imgH), 300) + 100;
    }

    const wouldOverflowRight = rect.right + padding + tooltipWidth > vw - padding;
    let x: number;
    if (wouldOverflowRight) {
      x = rect.left - tooltipWidth - padding;
    } else {
      x = rect.right + padding;
    }

    let y = rect.top + rect.height / 2 - tooltipHeight / 2;
    y = Math.max(padding, Math.min(y, vh - tooltipHeight - padding));

    this.tooltipFlipped.set(wouldOverflowRight);
    this.tooltipX.set(x);
    this.tooltipY.set(y);
    this.tooltipPhoto.set(photo);

    setTimeout(() => {
      if (this.tooltipPhoto() !== photo) return;
      const el = document.querySelector('app-photo-tooltip > div') as HTMLElement | null;
      if (!el) return;
      const { width: actualWidth, height: actualHeight } = el.getBoundingClientRect();
      const wouldOverflowRightActual = rect.right + padding + actualWidth > vw - padding;
      const newX = wouldOverflowRightActual
        ? rect.left - actualWidth - padding
        : rect.right + padding;
      if (Math.abs(newX - this.tooltipX()) > 1) this.tooltipX.set(newX);
      if (wouldOverflowRightActual !== this.tooltipFlipped()) this.tooltipFlipped.set(wouldOverflowRightActual);

      let newY = rect.top + rect.height / 2 - actualHeight / 2;
      newY = Math.max(padding, Math.min(newY, vh - actualHeight - padding));
      if (Math.abs(newY - this.tooltipY()) > 1) this.tooltipY.set(newY);
    }, 0);
  }

  hideTooltip(): void {
    // A docked rail keeps the last photo on mouse-out. Blanking it every time
    // the cursor crossed a gap would undo the reason for docking it.
    if (this.panelMode()) return;
    this.tooltipPhoto.set(null);
  }

  // --- Card action handlers ---

  openSimilar(photo: Photo, mode: 'visual' | 'color' | 'person'): void {
    this.hideTooltip();
    this.store.updateFilters({ similar_to: photo.path, similarity_mode: mode, min_similarity: '70' });
  }

  openAddPerson(photo: Photo): void {
    this.photoActions.openAddPerson(photo);
  }

  async removePerson(photo: Photo, personId: number): Promise<void> {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.manage_persons.remove_person_title),
        message: this.i18n.t(I18N.manage_persons.confirm_remove_person),
      },
    });
    const confirmed = await firstValueFrom(ref.afterClosed());
    if (confirmed) {
      this.store.unassignPerson(photo.path, personId);
    }
  }

  filterByPerson(personId: number): void {
    this.store.updateFilter('person_id', String(personId));
  }

  protected onTypeChange(type: string): void {
    this.store.updateFilter('type', type);
  }

  protected onSearchChange(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (value !== this.store.filters().search) this.store.updateFilter('search', value);
  }

  protected clearSearch(): void {
    this.store.updateFilter('search', '');
  }

  private setupResizeObserver(): void {
    this.resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        this.containerWidth.set(Math.floor(entry.contentRect.width));
      }
      this.updateWindowPosition();
    });

    // Observe the sidenav-content area for width changes
    const content = document.querySelector('mat-sidenav-content');
    if (content) {
      this.resizeObserver.observe(content);
    }
  }

  onScrollReached(): void {
    if (this.store.hasMore() && !this.store.loading() && !this.store.initializing()) {
      this.store.nextPage().then(() => this.scrollDirective()?.recheck());
    }
  }

  // --- Keyboard navigation (roving focus over the photo grid) ---

  /** Index of the keyboard-focused photo; -1 when keyboard nav is inactive. */
  protected readonly activeIndex = signal(-1);

  /** Path of the photo the cursor is standing on, kept in step with the index.
   *
   *  The index on its own only means anything against the list that was on
   *  screen when it was set. A filter change that yields a result set of the
   *  same length or longer keeps it in bounds, so the marker quietly reframes
   *  an unrelated photo -- and that is where the next rating keystroke lands. */
  private readonly activePath = signal<string | null>(null);

  /** Move the cursor onto `index`, keeping the photo it means in step with it.
   *  -1 -- or any index past the end -- clears both. */
  private setCursor(index: number): void {
    this.activeIndex.set(index);
    this.activePath.set(this.store.photos()[index]?.path ?? null);
  }

  /** Re-find the marked photo whenever the result set changes, so the cursor
   *  follows the photo rather than the slot, and drops to nothing once the
   *  photo is no longer in the results. The scan is O(n) over the result set,
   *  but it runs once per list change, not once per keystroke.
   *
   *  Only the list is tracked. The effect writes both cursor signals, so
   *  reading them tracked would make it re-run on its own writes. */
  private readonly cursorFollowsPhoto = effect(() => {
    const photos = this.store.photos();
    untracked(() => {
      const path = this.activePath();
      if (path === null) return;
      const at = photos.findIndex(p => p.path === path);
      if (at === this.activeIndex()) return;
      this.activeIndex.set(at);
      if (at < 0) this.activePath.set(null);
    });
  });

  /** Drop the cursor when focus genuinely leaves a grid.
   *
   *  The cards fade everything that is not the current photo, so a marker left
   *  standing while focus sits in the filter sidebar or a dialog dims the whole
   *  gallery for a keyboard that is no longer listening -- and a mouse-only
   *  user, who never puts focus back into a grid, would carry that from their
   *  first click to the end of the session.
   *
   *  Two destinations do not count as leaving. Another card in the same grid is
   *  the cursor moving, not going away. The selection action bar is where Clear
   *  lives, and `clearSelection` has to be able to hand focus back to the marked
   *  card afterwards, so the bar is excluded by name. A null relatedTarget --
   *  focus dropped to the body, or out to the browser chrome -- does count. */
  protected onGridFocusOut(event: FocusEvent): void {
    const next = event.relatedTarget as HTMLElement | null;
    if (next?.closest('[role="grid"], [data-selection-bar]')) return;
    this.setCursor(-1);
  }

  /** Whether the cursor is actually standing on a photo that is on screen.
   *
   *  The cards fade everything that is not the current photo, so this has to be
   *  false in both of the cases where there is nothing to leave at full
   *  strength: before the cursor has ever moved (-1), and after a filter change
   *  has left it pointing past the end of a shorter result set. Either one
   *  would otherwise render the whole grid dimmed with nothing marked.
   *
   *  `cursorFollowsPhoto` normally resolves the second case to -1 outright, but
   *  it runs when effects are flushed; this reads straight off the signals, so
   *  it also covers the frame in between. */
  protected readonly hasActivePhoto = computed(() =>
    this.activeIndex() >= 0 && this.activeIndex() < this.store.photos().length);

  /** Columns per row in grid mode (mirrors the CSS auto-fill column math). */
  private gridColumns(): number {
    const width = this.containerWidth() - (this.isDesktop() ? 32 : 16);
    return gridColumnCount(width, this.cardWidth(), GalleryComponent.ROW_GAP, this.isDesktop());
  }

  /** Vertical step for the active index: grid = ±columns, mosaic = same offset in adjacent row. */
  private verticalTarget(index: number, dir: 1 | -1): number {
    const count = this.store.photos().length;
    if (this.effectiveGalleryMode() === 'grid' && !this.virtualOn()) {
      const next = index + dir * this.gridColumns();
      return Math.max(0, Math.min(count - 1, next));
    }
    const rows = this.virtualOn() ? this.rowsModel() : this.mosaicRows();
    const rowIdx = rows.findIndex(r => index >= r.startIndex && index < r.startIndex + r.photos.length);
    const targetRow = rows[rowIdx + dir];
    if (rowIdx < 0 || !targetRow) return index;
    const offset = index - rows[rowIdx].startIndex;
    return targetRow.startIndex + Math.min(offset, targetRow.photos.length - 1);
  }

  protected onGridKeydown(event: KeyboardEvent): void {
    if (isTypingContext(event)) return;
    const photos = this.store.photos();
    if (!photos.length) return;
    const index = Math.max(0, this.activeIndex());
    let next: number | null = null;

    switch (event.key) {
      case 'ArrowRight': next = Math.min(photos.length - 1, index + 1); break;
      case 'ArrowLeft': next = Math.max(0, index - 1); break;
      case 'ArrowDown': next = this.verticalTarget(index, 1); break;
      case 'ArrowUp': next = this.verticalTarget(index, -1); break;
      case 'Home': next = 0; break;
      case 'End': next = photos.length - 1; break;
      case 'Escape':
        if (this.selectionCount()) {
          event.preventDefault();
          this.clearSelection();
        }
        return;
      default:
        this.handleRatingKey(event, photos, index);
        return;
    }

    event.preventDefault();
    this.setCursor(next);
    this.focusCard(next);
  }

  /** Rate-and-advance shortcuts on the focused card: 1-5 set stars, 0/X reject
   * (both auto-advance), F toggles favorite (stays put — a tag-like toggle).
   * Edition-only and gated on the rating-controls feature flag, mirroring the
   * card's own template guards. */
  private handleRatingKey(event: KeyboardEvent, photos: Photo[], index: number): void {
    // Don't hijack modified combos (Ctrl/Cmd+1..5 switch browser tabs).
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (!this.auth.isEdition() || !this.store.config()?.features?.show_rating_controls) return;
    const photo = photos[index];
    if (!photo) return;

    let advance = false;
    if (event.key >= '1' && event.key <= '5') {
      this.store.setRating(photo.path, Number(event.key));
      advance = true;
    } else if (event.key === '0' || event.key === 'x' || event.key === 'X') {
      this.store.toggleRejected(photo.path);
      advance = true;
    } else if (event.key === 'f' || event.key === 'F') {
      this.store.toggleFavorite(photo.path);
    } else {
      return;
    }

    event.preventDefault();
    if (advance) {
      const next = Math.min(photos.length - 1, index + 1);
      this.setCursor(next);
      this.focusCard(next);
    }
  }

  /** Focus a card by photo index; if windowed out of the DOM, scroll its row
   * into view first and retry once the window has rendered it.
   *
   * The tile inside the card takes the focus -- it is what carries the tabindex
   * -- but the card itself is what gets scrolled: `scroll-margin` does not
   * inherit, and the clearance that lifts the current photo out from under the
   * action bar is declared on the card host. Asking the tile would ask an
   * element that has none.
   *
   * `scroll = false` places focus without moving the viewport, and gives up on
   * a card that is not in the DOM rather than paging it in. */
  private focusCard(index: number, retried = false, scroll = true): void {
    const host = document.querySelector(`[data-pidx="${index}"]`) as HTMLElement | null;
    if (host) {
      const focusable = (host.querySelector('[tabindex]') as HTMLElement | null) ?? host;
      focusable.focus({ preventScroll: !scroll });
      if (scroll) host.scrollIntoView({ block: 'nearest' });
      return;
    }
    if (retried || !scroll || !this.virtualOn()) return;
    const row = this.rowsModel().find(r =>
      index >= r.startIndex && index < r.startIndex + r.photos.length);
    const content = this.scrollContent();
    if (!row || !content) return;
    // row.offset is relative to the rows host - convert to viewport scrollTop
    const absolute = content.measureScrollOffset('top') + row.offset - this.relScrollTop();
    content.scrollTo({ top: Math.max(0, absolute) });
    requestAnimationFrame(() => {
      this.updateWindowPosition();
      requestAnimationFrame(() => this.focusCard(index, true));
    });
  }

  /** Track scrolling: scroll-to-top button + virtual window position. */
  private setupScrollTracking(): void {
    const content = this.scrollContent();
    if (!content) return;
    let rafPending = false;
    content.elementScrolled()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.showScrollTop.set(content.measureScrollOffset('top') > 800);
        if (!rafPending) {
          rafPending = true;
          requestAnimationFrame(() => {
            rafPending = false;
            this.updateWindowPosition();
          });
        }
      });
    requestAnimationFrame(() => this.updateWindowPosition());
  }

  /** Smoothly scroll the gallery content back to the top. */
  protected scrollToTop(): void {
    this.scrollContent()?.scrollTo({ top: 0, behavior: 'smooth' });
  }
}
