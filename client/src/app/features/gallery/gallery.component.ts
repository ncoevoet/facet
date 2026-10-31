import { StackActionsService } from './stack-actions.service';
import { STACK_EDITOR_HISTORY } from './stack-editor-history';
import {
  Component,
  ChangeDetectorRef,
  inject,
  computed,
  signal,
  OnInit,
  OnDestroy,
  viewChild,
  viewChildren,
  afterNextRender,
  effect,
  untracked,
  DestroyRef,
  Injector,
  TemplateRef,
  ElementRef,
  NgZone,
  ChangeDetectionStrategy
} from '@angular/core';
import { DOCUMENT, NgTemplateOutlet } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { MatSidenav, MatSidenavContainer, MatSidenavModule, MatSidenavContent } from '@angular/material/sidenav';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule, MatSelect } from '@angular/material/select';
import { MatInputModule } from '@angular/material/input';
import { MatSliderModule } from '@angular/material/slider';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatBottomSheet, MatBottomSheetModule } from '@angular/material/bottom-sheet';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatMenuModule, MatMenuTrigger } from '@angular/material/menu';
import { MatTooltip, MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, NavigationStart, Router, RouterOutlet } from '@angular/router';
import { filter, firstValueFrom, takeUntil } from 'rxjs';
import { GalleryStore, BatchResult, REVIEW_RESUME_NAVIGATION } from './gallery.store';
import { NoticeDismissals, NoticeKind, readNoticeDismissals, saveNoticeDismissals, withDismissal } from './notice-dismiss.util';
import { Photo } from '../../shared/models/photo.model';
import { isImeOrRepeat, isPageShortcutBlocked, isShortcutContextBlocked, isTypingContext } from '../../shared/utils/keyboard';
import { KeyboardMappingService } from '../../core/services/keyboard-mapping.service';
import { closeOverlayDirectives } from '../../shared/utils/overlays';
import { PHOTO_PATH } from '../../core/gallery-reuse.strategy';
import { UndoService } from '../../core/services/undo.service';
import { SequenceOverrideService, SequenceKind } from '../../core/services/sequence-override.service';
import {
  SequenceKindIconPipe, SEQUENCE_KINDS_KEPT_WHOLE,
} from '../../shared/pipes/sequence-kind.pipe';
import { isBracketLadderRejection } from '../../shared/utils/sequence-ladder';
import { IsSelectedPipe } from '../../shared/pipes/selection.pipe';
import { PhotoSetKindIconPipe, PhotoSetKindLabelPipe } from '../../shared/pipes/photo-set-kind.pipe';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { ScanService } from '../../core/services/scan.service';
import { useDesktopSignal, DETAILS_RAIL_MIN_WIDTH_PX } from '../../shared/utils/media-query';
import { downloadAll } from '../../shared/utils/download';
import { basename, copyLines } from '../../shared/utils/clipboard';
import { I18nService } from '../../core/services/i18n.service';
import { ApiService } from '../../core/services/api.service';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { STACK_MAX_MEMBERS, STACK_MIN_MEMBERS } from './stack-limits';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { MAX_REFRESH_PATHS, PhotoActionsService } from '../../core/services/photo-actions.service';
import { CardActionsService } from './card-actions.service';
import { SlideshowComponent } from './slideshow.component';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { GalleryPhotoMenuComponent, PhotoMenuAction, PhotoMenuActionEvent, isSheetAction } from './gallery-photo-menu.component';
import type { SheetAction } from './gallery-actions-sheet.component';
import { PhotoCardComponent } from '../../shared/components/photo-card/photo-card.component';
import { PhotoSkeletonComponent } from '../../shared/components/photo-skeleton/photo-skeleton.component';
import {
  GalleryRow, aspectOf, buildGridRows, buildMosaicRows,
  gridColumnCount, totalRowsHeight, windowRange,
} from './gallery-rows.util';
import { noticeLiftPx } from './selection-bar-layout.util';
import { GalleryFilters, activeFilterKeys, applyQueryParams, applySavedAlbumFilters, loadDisplayOptionsFromStorage } from './gallery-filters.util';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { CreateAlbumDialogComponent } from '../albums/create-album-dialog.component';
import { ExportEditorDialogComponent } from './export-editor-dialog.component';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { MAX_COMPARE_PANES } from './synced-zoom.component';
import { HistogramMode, isHistogramMode } from '../../shared/utils/histogram';

function assertNever(action: never): never {
  throw new Error(`Unhandled photo menu action: ${JSON.stringify(action)}`);
}

/** Width from which the toolbar search is shown (its `min-[1360px]:` class). */
const TOOLBAR_SEARCH_QUERY = '(min-width: 1360px)';

/** Where the focused card sat in the viewport when the gallery parked. */
interface ReturnAnchor { offset: number; width: number; height: number }

/** What the gallery restores on return; an anchor implies a photo path to re-anchor to. */
type ReturnTarget = { scroll: number; focus: Element | null } & (
  | { path: string | null; anchor: null }
  | { path: string; anchor: ReturnAnchor });

@Component({
  selector: 'app-gallery',
  imports: [
    NgTemplateOutlet,
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
    PluralKeyPipe,
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
    GalleryPhotoMenuComponent,
    PhotoSkeletonComponent,
    InfiniteScrollDirective,
  ],
  template: `
    <!-- Header-slot toolbar: the app shell renders this in the global header on lg+.
         Type filter + semantic search, rebound to the gallery store. -->
    <ng-template #galleryToolbar>
      @if (!pinned()) {
        <mat-form-field class="!hidden lg:!inline-flex w-44 ml-2 shrink-0" subscriptSizing="dynamic">
          <mat-label>{{ I18N.ui.filters.type | translate }}</mat-label>
          <mat-select panelWidth="auto" panelClass="nowrap-panel !max-h-[70vh]" [value]="store.filters().type" (selectionChange)="onTypeChange($event.value)">
            <mat-option value="">{{ I18N.gallery.all_photos | translate }}</mat-option>
            @for (t of store.types(); track t.id) {
              <mat-option [value]="t.id">{{ (t.id === 'top_picks' ? 'photo_types.top_picks' : 'category_names.' + t.id) | translate }} ({{ t.count }})</mat-option>
            }
          </mat-select>
        </mat-form-field>

        <!-- Search. Visible from 1360 px up — the same threshold as the count
             label, below which the toolbar has no room for it — and filters as
             you type (400 ms debounce; Enter and leaving the box commit, so
             clicking a photo never drops typed text). flex-1 fills whatever
             the type dropdown and the buttons leave. -->
        <mat-form-field class="!hidden min-[1360px]:!inline-flex min-w-48 flex-1 mr-2" subscriptSizing="dynamic">
          <input
            #toolbarSearch
            matInput
            [placeholder]="I18N.gallery.search_placeholder | translate"
            [value]="store.filters().search"
            (input)="onSearchInput($event)"
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
      }

      @if (!pinned()) {
        <button mat-icon-button data-stack-collapse (click)="store.toggleStackCollapse()"
          [matTooltip]="(store.collapseStacks() ? I18N.stacks.expand_all : I18N.stacks.collapse) | translate"
          [attr.aria-label]="(store.collapseStacks() ? I18N.stacks.expand_all : I18N.stacks.collapse) | translate"><mat-icon>{{ store.collapseStacks() ? 'unfold_more' : 'unfold_less' }}</mat-icon></button>
      }
      @if (auth.isEdition() && store.canScopeSelectionToView()) {
        <button mat-icon-button data-stack-suggestions (click)="openStackSuggestions()"
          [matTooltip]="I18N.stacks.suggestions | translate" [attr.aria-label]="I18N.stacks.suggestions | translate">
          <mat-icon>auto_awesome_motion</mat-icon>
        </button>
      }
      <!-- Keep top N%: server-rank the current view by the current sort and
           select the bottom (100-N)% for review/rejection via the selection bar. -->
      @if (auth.isEdition() && store.total() > 0 && store.canScopeSelectionToView()) {
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
              {{ I18N.gallery.keep_top.preview | translate:{ keep: keepPreviewKeep(), cut: keepPreviewCut(), total: store.photoTotal() } }}
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

    <div #noticeHost class="relative h-full">
    <mat-sidenav-container class="h-full">
      <!-- One end drawer, two occupants. Material allows a single drawer per
           side, which is also the behaviour we want: the details rail and the
           filters compete for the same strip, so opening the filters hides the
           rail and closing them brings it back, without either changing how much
           room the grid gets. -->
      <mat-sidenav #filterDrawer [disableClose]="detailsRailVisible()" [mode]="isDesktop() ? 'side' : 'over'" position="end" class="w-[min(320px,100vw)] p-0"
        (openedChange)="onFilterDrawerChange($event)">
        @if (detailsRailVisible()) {
          <!-- Deselect stays put above the scrolling details; the tooltip
               background covers the whole rail instead of a rounded card. -->
          <div class="flex flex-col h-full bg-[var(--facet-tooltip-bg)]" data-details-rail tabindex="-1" (keydown.escape)="onRailEscape($event)"
               (focusout)="onGridFocusOut($event)">
            @if (hasActivePhoto()) {
              <button mat-button class="!min-w-0 shrink-0 self-start mx-2 mt-2" (click)="releasePanel()">
                <mat-icon>arrow_back</mat-icon> {{ I18N.gallery.tooltip_mode.panel_deselect | translate }}
              </button>
            }
            <div class="min-h-0 flex-1 overflow-y-auto">
            @if (panelPhoto(); as p) {
              <app-photo-tooltip [photo]="p" [docked]="true" [pinned]="true"
                                 [histogramDefaultMode]="tooltipHistogramDefaultMode()"
                                 [indicatorPercent]="clippingIndicatorPercent()"
                                 [personLinks]="!pinned()"
        (personSelected)="store.updateFilter('person_id', $event)" />
            } @else {
              <div class="p-4 text-sm opacity-60 text-center">
                {{ I18N.gallery.tooltip_mode.panel_empty | translate }}
              </div>
            }
            </div>
          </div>
        } @else {
          <!-- Usually closed, and heavy enough that building it eagerly holds up the grid's first paint. -->
          @defer (on idle; when store.filterDrawerOpen()) {
            <app-gallery-filter-sidebar />
          }
        }
      </mat-sidenav>

      <!-- Main content. The drawer reserves its own strip, so the grid gets
           exactly the width it has whenever the filters are open. -->
      <mat-sidenav-content>
        @if (store.photoTotal() !== store.total()) {
          <p role="status" class="text-sm opacity-80 px-3 py-2">{{ I18N.stacks.totals | translate:{ photos: store.photoTotal(), items: store.total() } }}</p>
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

        <!-- Pinned-list chip: the assistant's ui_show_photos list replaces the filtered
             view; this is the way back to it (any filter change drops the list too). -->
        @if (store.pinnedPaths() !== null) {
          <div role="status" class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <mat-icon class="opacity-70 !text-base !w-5 !h-5">auto_awesome</mat-icon>
            <span class="min-w-[12rem] flex-1">
              {{ store.total() | pluralKey:I18N.gallery.pinned.chip:I18N.gallery.pinned.chip_plural | translate:{ count: store.total() } }}
            </span>
            <button mat-button class="!min-w-0" (click)="store.clearPinned()">
              {{ I18N.gallery.pinned.clear | translate }}
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
                [collapsedSetKinds]="collapsedSetKinds()"
                [burstFramesVisible]="burstFramesVisible()"
                    [photo]="photo"
                    [attr.data-pidx]="row.startIndex + i"
                    [style.width.px]="row.widths[i]"
                    [style.height.px]="row.height"
                    class="shrink-0"
                    [hideDetails]="rowCardHideDetails()"
                    [mosaicMode]="effectiveGalleryMode() === 'mosaic'"
                    [config]="store.config()"
                    [isSelected]="photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()"
                    [isActive]="row.startIndex + i === activeIndex()"
                    [gridHasActiveCard]="hasActivePhoto()"
                    [currentSort]="store.filters().sort"
                    [metricRanges]="store.metricRangesByColumn()"
                    [thumbSize]="thumbSize()"
                    [isEditionMode]="auth.isEdition()"
                    [personFilterId]="store.filters().person_id"
                    [tooltipMode]="tooltipMode()"
                    [panelActivation]="panelActivation()"
                    (selectionChange)="toggleSelection($event.photo, $event.event, row.startIndex + i)"
                    (tooltipShow)="showTooltip($event.event, $event.photo)"
                    (tooltipHide)="hideTooltip()"
                    [filterLinks]="!pinned()"
                (tagClicked)="store.updateFilter('tag', $event)"
                    (personFilterClicked)="filterByPerson($event)"
                    (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                    (openSimilarClicked)="openSimilar($event.photo, $event.mode)"
                    (openCritiqueClicked)="openCritique($event)"
                    (embedMetadataClicked)="embedMetadata($event)"
                    (openAddPersonClicked)="openAddPerson($event)"
                    [cardActions]="cardActions()"
                    (openStackClicked)="openStack($event)"
                    (openSetClicked)="store.scopeToSet($event.photo, $event.kind)"
                    (openDetailClicked)="downloadPhoto($event)"
                    (favoriteToggled)="store.toggleFavorite($event)"
                    (rejectedToggled)="store.toggleRejected($event)"
                    (starClicked)="store.setRating($event.photo.path, $event.star)"
                    [matContextMenuTriggerFor]="photoMenu.menu()"
                    [matContextMenuTriggerData]="{ photo: photo, index: row.startIndex + i, bulk: (photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()) && selectionCount() > 1 }"
                    [matContextMenuTriggerDisabled]="touchOnly()"
                    [matContextMenuTriggerRestoreFocus]="false"
                    (contextmenu)="onCardContextMenu(row.startIndex + i)"
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
                  [collapsedSetKinds]="collapsedSetKinds()"
                  [burstFramesVisible]="burstFramesVisible()"
                  [photo]="photo"
                  [attr.data-pidx]="i"
                  [config]="store.config()"
                  [isSelected]="photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()"
                  [isActive]="i === activeIndex()"
                  [gridHasActiveCard]="hasActivePhoto()"
                  [hideDetails]="effectiveHideDetails()"
                  [currentSort]="store.filters().sort"
                  [metricRanges]="store.metricRangesByColumn()"
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
                  [filterLinks]="!pinned()"
                      (tagClicked)="store.updateFilter('tag', $event)"
                  (personFilterClicked)="filterByPerson($event)"
                  (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                  (openSimilarClicked)="openSimilar($event.photo, $event.mode)"
                  (openCritiqueClicked)="openCritique($event)"
                  (embedMetadataClicked)="embedMetadata($event)"
                  (openAddPersonClicked)="openAddPerson($event)"
                  [cardActions]="cardActions()"
                  (openStackClicked)="openStack($event)"
                  (openSetClicked)="store.scopeToSet($event.photo, $event.kind)"
                  (openDetailClicked)="downloadPhoto($event)"
                  (favoriteToggled)="store.toggleFavorite($event)"
                  (rejectedToggled)="store.toggleRejected($event)"
                  (starClicked)="store.setRating($event.photo.path, $event.star)"
                  [matContextMenuTriggerFor]="photoMenu.menu()"
                  [matContextMenuTriggerData]="{ photo: photo, index: i, bulk: (photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()) && selectionCount() > 1 }"
                  [matContextMenuTriggerDisabled]="touchOnly()"
                  [matContextMenuTriggerRestoreFocus]="false"
                  (contextmenu)="onCardContextMenu(i)"
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
                  [collapsedSetKinds]="collapsedSetKinds()"
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
                      [metricRanges]="store.metricRangesByColumn()"
                      [thumbSize]="thumbSize()"
                      [isEditionMode]="auth.isEdition()"
                      [personFilterId]="store.filters().person_id"
                      [tooltipMode]="tooltipMode()"
                      [panelActivation]="panelActivation()"
                      (selectionChange)="toggleSelection($event.photo, $event.event, row.startIndex + i)"
                      (tooltipShow)="showTooltip($event.event, $event.photo)"
                      (tooltipHide)="hideTooltip()"
                      [filterLinks]="!pinned()"
                      (tagClicked)="store.updateFilter('tag', $event)"
                      (personFilterClicked)="filterByPerson($event)"
                      (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                      (openSimilarClicked)="openSimilar($event.photo, $event.mode)"
                      (openCritiqueClicked)="openCritique($event)"
                      (embedMetadataClicked)="embedMetadata($event)"
                      (openAddPersonClicked)="openAddPerson($event)"
                      [cardActions]="cardActions()"
                      (openStackClicked)="openStack($event)"
                      (openSetClicked)="store.scopeToSet($event.photo, $event.kind)"
                      (openDetailClicked)="downloadPhoto($event)"
                      (favoriteToggled)="store.toggleFavorite($event)"
                      (rejectedToggled)="store.toggleRejected($event)"
                      (starClicked)="store.setRating($event.photo.path, $event.star)"
                      [matContextMenuTriggerFor]="photoMenu.menu()"
                      [matContextMenuTriggerData]="{ photo: photo, index: row.startIndex + i, bulk: (photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()) && selectionCount() > 1 }"
                      [matContextMenuTriggerDisabled]="touchOnly()"
                      [matContextMenuTriggerRestoreFocus]="false"
                      (contextmenu)="onCardContextMenu(row.startIndex + i)"
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
            @if (store.loadErrorKey(); as key) {
              <p class="text-lg text-center max-w-xl">{{ key | translate }}</p>
            } @else {
              <p class="text-lg text-center">{{ I18N.gallery.load_error.message | translate }}</p>
            }
            <button mat-flat-button color="primary" (click)="store.reloadPhotos()">
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
            } @else if (scan.canLaunch()) {
              <button mat-flat-button color="primary" (click)="openScanLauncher()">
                <mat-icon>add_photo_alternate</mat-icon>
                {{ I18N.scan.get_started | translate }}
              </button>
            }
          </div>
        }

        <!-- Room for the floating selection card (its measured height plus margin) so the last row can scroll clear of it -->
        @if (selectionCount()) {
          <div aria-hidden="true" [style.height.px]="selectionBarReservePx()"></div>
        }
        <!-- Infinite scroll sentinel -->
        <div appInfiniteScroll (scrollReached)="onScrollReached()" class="h-1"></div>
      </mat-sidenav-content>

    </mat-sidenav-container>
      <!-- Advisory notices: floating, bottom-right, out of the layout flow. Anchored to the
           sidenav container (not the scrolling content) so they stay put with few photos,
           and the right offset is measured so the column clears an open end drawer / details rail
           and the content's own scrollbar.
           The container is its own stacking context, so a notice outside it cannot sit under the
           mobile 'over' drawer; it steps aside while that drawer is open instead.
           Lifted above the floating selection card, only when the two overlap horizontally. Order: review
           progress, the remembered review queue, the hidden-photos notice, the active-filters notice, then the
           thumbnail-migration notice. The migration notice is the only place the command that regenerates RAW thumbnails is
           surfaced: the grid reads photos.thumbnail, so browsing never regenerates it. -->
      @if (noticeStackVisible()) {
        <div data-gallery-notices class="pointer-events-none absolute z-10 flex flex-col gap-2 w-[min(26rem,calc(100%-1rem))]"
             (pointerenter)="noticePointerChange(true)" (pointerleave)="noticePointerChange(false)"
             (focusout)="noticeFocusLeft($event)"
             [style.bottom.px]="noticeBottomPx()" [style.right.px]="noticeRightPx()" [style.maxWidth]="noticeMaxWidth()">
          @if (scrollTopShown()) {
            <ng-container *ngTemplateOutlet="scrollTopFab; context: { $implicit: 'pointer-events-auto self-end' }" />
          }
          @if (noticesCollapsed()) {
            <button type="button" data-gallery-notices-pill
                    class="pointer-events-auto self-end px-3 py-1.5 rounded-full bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] shadow-lg flex items-center gap-1.5 text-xs"
                    (click)="expandNotices($event)">
              <mat-icon class="!text-base !w-4 !h-4 !leading-4">notifications</mat-icon>
              <span>{{ shownNoticeCount() | pluralKey:I18N.gallery.notices.collapsed:I18N.gallery.notices.collapsed_plural | translate:{ count: shownNoticeCount() } }}</span>
            </button>
          } @else {
            @if (reviewProgressShown()) {
              @if (store.reviewProgress(); as progress) {
                <section data-review-progress [class]="NOTICE_CARD_CLASS" [attr.aria-label]="I18N.gallery.review_progress.title | translate">
                  <mat-icon class="opacity-70 !text-base !w-5 !h-5 self-start">fact_check</mat-icon>
                  <div class="flex-1 min-w-0 flex flex-col gap-1">
                    <span id="notice-text-review_progress" class="flex flex-wrap gap-x-3 gap-y-0.5" role="status" aria-live="polite" aria-atomic="true">
                      <span>{{ I18N.gallery.review_progress.counts | translate:{ undecided: progress.undecided, kept: progress.kept, rejected: progress.rejected } }}</span>
                      <span class="opacity-70">{{ I18N.gallery.review_progress.complete | translate:{ percent: store.reviewPercent(), total: progress.total } }}</span>
                    </span>
                    <progress class="w-full h-1" max="100" [value]="store.reviewPercent()" [attr.aria-label]="I18N.gallery.review_progress.title | translate"></progress>
                    @if (progress.undecided > 0 && store.filters().review_status !== 'undecided') {
                      <button mat-button class="!min-w-0 self-start -ml-3" (click)="store.startReviewQueue()">{{ I18N.gallery.review_progress.start | translate }}</button>
                    }
                  </div>
                  <ng-container *ngTemplateOutlet="noticeClose; context: { $implicit: 'review_progress', alignTop: true }" />
                </section>
              }
            }
            @if (reviewBookmarkShown()) {
              <div [class]="NOTICE_CARD_CLASS">
                <mat-icon class="opacity-70 !text-base !w-5 !h-5">bookmark</mat-icon>
                <span id="notice-text-review_bookmark" class="flex-1 opacity-80">{{ I18N.gallery.review_progress.browser | translate }}</span>
                <button mat-button class="!min-w-0" [disabled]="store.loading()" (click)="continueReview()">{{ I18N.gallery.review_progress.resume | translate }}</button>
                <ng-container *ngTemplateOutlet="noticeClose; context: { $implicit: 'review_bookmark' }" />
              </div>
            }
            @if (hiddenNoticeShown()) {
              <div role="status" [class]="NOTICE_CARD_CLASS">
                <mat-icon class="opacity-70 !text-base !w-5 !h-5">visibility_off</mat-icon>
                <span id="notice-text-hidden" class="flex-1">
                  {{ I18N.gallery.hidden_banner.message | translate:{ n: store.hiddenSummary().total } }}
                  @if (hiddenReasons()) { ({{ hiddenReasons() }}) }
                </span>
                <button mat-button class="!min-w-0" (click)="store.showAllHidden()">
                  {{ I18N.gallery.hidden_banner.show_all | translate }}
                </button>
                <ng-container *ngTemplateOutlet="noticeClose; context: { $implicit: 'hidden' }" />
              </div>
            } @else if (restoreNoticeShown()) {
              <div role="status" [class]="NOTICE_CARD_CLASS">
                <mat-icon class="opacity-70 !text-base !w-5 !h-5">visibility</mat-icon>
                <span id="notice-text-restore_hidden" class="flex-1">
                  {{ I18N.gallery.hidden_banner.showing_all | translate }}
                </span>
                <button mat-button class="!min-w-0" (click)="store.restoreHidden()">
                  {{ I18N.gallery.hidden_banner.restore | translate }}
                </button>
                <ng-container *ngTemplateOutlet="noticeClose; context: { $implicit: 'restore_hidden' }" />
              </div>
            }
            @if (activeFiltersNoticeShown()) {
              <div role="status" [class]="NOTICE_CARD_CLASS">
                <mat-icon class="opacity-70 !text-base !w-5 !h-5">filter_alt</mat-icon>
                <span id="notice-text-active_filters" class="flex-1">
                  {{ store.activeFilterCount() | pluralKey:I18N.gallery.filters_notice.message:I18N.gallery.filters_notice.message_plural | translate:{ count: store.activeFilterCount() } }}
                </span>
                <button mat-button class="!min-w-0" (click)="store.resetFilters()">
                  {{ I18N.gallery.filters_notice.reset | translate }}
                </button>
                <ng-container *ngTemplateOutlet="noticeClose; context: { $implicit: 'active_filters' }" />
              </div>
            }
            @if (showRenderMigrationBanner()) {
              <div role="status" [class]="NOTICE_CARD_CLASS">
                <mat-icon class="opacity-70 !text-base !w-5 !h-5">auto_fix_high</mat-icon>
                <span id="notice-text-render_migration" class="flex-1">
                  {{ I18N.gallery.render_migration.message | translate:{ n: renderMigrationPending() } }}
                  {{ I18N.gallery.render_migration.command_hint | translate:{ command: REFRESH_THUMBNAILS_COMMAND } }}
                </span>
                <ng-container *ngTemplateOutlet="noticeClose; context: { $implicit: 'render_migration' }" />
              </div>
            }
          }
        </div>
      }

      <!-- Selection card: floats bottom-left inside the host (absolute, never over the end drawer).
           Its right edge stops at the same measured inset the notices use, so it wraps instead of
           running under an open drawer. Hidden while the mobile 'over' drawer is open: the drawer
           container is its own stacking context and a z-20 card would paint over it. -->
      @if (selectionCount() && !overDrawerOpen()) {
        <div #selectionBar data-selection-bar
             class="absolute bottom-2 md:bottom-4 left-2 md:left-4 z-20 w-fit flex flex-wrap items-center gap-1 px-2 py-1 rounded-2xl bg-[var(--mat-sys-surface-container)] border border-[var(--mat-sys-outline-variant)] shadow-lg max-md:mb-[env(safe-area-inset-bottom)]"
             [style.right.px]="noticeRightPx()">
          <!-- Every loaded photo is selected, but the view runs past the pages
               fetched so far. Offer the rest explicitly on its own line (w-full
               in a wrapping row) rather than silently widening what was asked. -->
          @if (offerWholeView()) {
            <div class="w-full flex flex-wrap items-center gap-2 text-xs opacity-80 px-1">
              <span>{{ I18N.gallery.selection.view_scope_offer | translate:{ count: store.photos().length } }}</span>
              <button mat-button class="!text-xs" (click)="selectWholeView()">{{ I18N.gallery.selection.view_scope_select_all | translate:{ total: store.photoTotal() } }}</button>
            </div>
          }
          @if (viewScoped()) {
            <p class="text-xs basis-full opacity-80">{{ I18N.stacks.folded_scope | translate }}</p>
          }
          <span data-selection-status tabindex="-1" class="text-sm font-medium shrink-0 px-1">{{ (viewScoped() ? I18N.gallery.selection.view_scope_active : I18N.gallery.selection.count) | translate:{ count: selectionCount() } }}</span>
          <button mat-icon-button disabledInteractive (click)="clearSelection()" [matTooltip]="I18N.gallery.selection.clear | translate" [attr.aria-label]="I18N.gallery.selection.clear | translate"><mat-icon>close</mat-icon></button>
          @if (!allLoadedSelected()) {
            <button mat-icon-button disabledInteractive (click)="selectAll()" [matTooltip]="I18N.gallery.selection.select_all | translate" [attr.aria-label]="I18N.gallery.selection.select_all | translate"><mat-icon>select_all</mat-icon></button>
          }
          <button mat-icon-button disabledInteractive (click)="invertSelection()" [matTooltip]="I18N.gallery.selection.invert | translate" [attr.aria-label]="I18N.gallery.selection.invert | translate"><mat-icon>flip</mat-icon></button>
          @if (canCompareSelection()) {
            <button mat-icon-button disabledInteractive (click)="compareSelection()" [matTooltip]="I18N.gallery.selection.compare | translate" [attr.aria-label]="I18N.gallery.selection.compare | translate"><mat-icon>compare</mat-icon></button>
          }
          @if (auth.isEdition()) {
            <button mat-icon-button [disabled]="viewScoped() || selectionCount() > MAX_REFRESH_PATHS" (click)="refreshSelectedPhotos()"
              [matTooltip]="I18N.photo_refresh.title | translate" [attr.aria-label]="I18N.photo_refresh.title | translate"><mat-icon>refresh</mat-icon></button>
          }
          <!-- Mobile: single Actions trigger opening a touch-friendly bottom sheet -->
          @if (auth.isEdition()) {
            <button mat-icon-button data-create-stack (click)="createStack()" [disabled]="!canCreateStack()"
              [matTooltip]="(canCreateStack() ? (stackShortcut() ? I18N.shortcuts.stack_hint : I18N.stacks.create) : I18N.stacks.explicit_only) | translate:{ key: stackShortcut() }"
              [attr.aria-label]="I18N.stacks.create | translate"><mat-icon>photo_library</mat-icon></button>
          }
          <button mat-icon-button class="md:!hidden" (click)="openActionsSheet()" [disabled]="downloading()" [matTooltip]="I18N.gallery.selection.actions | translate" [attr.aria-label]="I18N.gallery.selection.actions | translate">
            @if (downloading()) { <mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate"></mat-spinner> } @else { <mat-icon>more_horiz</mat-icon> }
          </button>
          <!-- Desktop actions (below md they live in the Actions sheet) -->
          <div class="contents max-md:hidden">
            @if (auth.isEdition()) {
              <span aria-hidden="true" class="w-px h-6 mx-1 bg-[var(--mat-sys-outline-variant)]"></span>
              <button mat-icon-button disabledInteractive (click)="batchFavorite()" [matTooltip]="I18N.gallery.selection.favorite | translate" [attr.aria-label]="I18N.gallery.selection.favorite | translate"><mat-icon>favorite</mat-icon></button>
              <button mat-icon-button disabledInteractive (click)="batchReview('kept')" [matTooltip]="I18N.review.keep | translate" [attr.aria-label]="I18N.review.keep | translate"><mat-icon>check_circle</mat-icon></button>
              <button mat-icon-button disabledInteractive (click)="batchReview('undecided')" [matTooltip]="I18N.review.reset | translate" [attr.aria-label]="I18N.review.reset | translate"><mat-icon>restart_alt</mat-icon></button>
              <button mat-icon-button disabledInteractive (click)="batchReject()" [matTooltip]="I18N.gallery.selection.reject | translate" [attr.aria-label]="I18N.gallery.selection.reject | translate"><mat-icon>thumb_down</mat-icon></button>
              <button mat-icon-button disabledInteractive [matMenuTriggerFor]="rateMenu" [matTooltip]="I18N.gallery.selection.rate | translate" [attr.aria-label]="I18N.gallery.selection.rate | translate"><mat-icon>star</mat-icon></button>
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
              <button mat-icon-button disabledInteractive [matMenuTriggerFor]="albumMenu" [matTooltip]="I18N.albums.add_photos | translate" [attr.aria-label]="I18N.albums.add_photos | translate"><mat-icon>photo_library</mat-icon></button>
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
              <button mat-icon-button disabledInteractive [matMenuTriggerFor]="sequenceMenu" [matTooltip]="I18N.gallery.selection.mark_sequence | translate" [attr.aria-label]="I18N.gallery.selection.mark_sequence | translate"><mat-icon>panorama_photosphere</mat-icon></button>
              <mat-menu #sequenceMenu="matMenu">
                <button mat-menu-item (click)="markAsPanorama('panorama')">
                  <mat-icon>{{ 'panorama' | sequenceKindIcon }}</mat-icon>
                  {{ I18N.gallery.selection.mark_panorama | translate }}
                </button>
                <button mat-menu-item (click)="markAsPanorama('hdr_panorama')">
                  <mat-icon>{{ 'hdr_panorama' | sequenceKindIcon }}</mat-icon>
                  {{ I18N.gallery.selection.mark_hdr_panorama | translate }}
                </button>
                <button mat-menu-item (click)="markAsPanorama('bracket')">
                  <mat-icon>{{ 'bracket' | sequenceKindIcon }}</mat-icon>
                  {{ I18N.gallery.selection.mark_bracket | translate }}
                </button>
              </mat-menu>
            }
            <span aria-hidden="true" class="w-px h-6 mx-1 bg-[var(--mat-sys-outline-variant)]"></span>
            <button mat-icon-button disabledInteractive (click)="copyPaths()" [matTooltip]="I18N.gallery.selection.copy_filenames | translate" [attr.aria-label]="I18N.gallery.selection.copy_filenames | translate"><mat-icon>content_copy</mat-icon></button>
            @if (auth.isEdition()) {
              <button mat-icon-button (click)="openCaptureDateDialog()" [matTooltip]="I18N.capture_date.title | translate" [attr.aria-label]="I18N.capture_date.title | translate"><mat-icon>edit_calendar</mat-icon></button>
              <button mat-icon-button disabledInteractive (click)="openBatchGpsDialog()" [matTooltip]="I18N.photo_detail.gps.batch_title | translate" [attr.aria-label]="I18N.photo_detail.gps.batch_title | translate"><mat-icon>location_on</mat-icon></button>
              <button mat-icon-button disabledInteractive (click)="openManualTagsDialog()" [matTooltip]="I18N.gallery.selection.edit_tags | translate" [attr.aria-label]="I18N.gallery.selection.edit_tags | translate"><mat-icon>sell</mat-icon></button>
              <button mat-icon-button disabledInteractive (click)="openExportDialog()" [matTooltip]="I18N.export.action | translate" [attr.aria-label]="I18N.export.action | translate"><mat-icon>drive_file_move</mat-icon></button>
              <button mat-icon-button disabledInteractive (click)="openCullDialog()" [matTooltip]="I18N.cull.action | translate" [attr.aria-label]="I18N.cull.action | translate"><mat-icon>folder_move</mat-icon></button>
              @if (store.config()?.cull?.trash_available) {
                <button mat-icon-button disabledInteractive (click)="deleteSelected()"
                        [disabled]="viewScoped()"
                        [matTooltip]="(viewScoped() ? I18N.cull.delete_disabled_view_scope_tooltip : I18N.cull.delete_action) | translate"
                        [attr.aria-label]="I18N.cull.delete_action | translate">
                  <mat-icon>delete</mat-icon>
                </button>
              }
            }
            @if (auth.downloadProfiles().length) {
              <button mat-icon-button [matMenuTriggerFor]="dlMenu" [disabled]="downloading()" [matTooltip]="(downloading() ? I18N.photo_detail.downloading : I18N.gallery.selection.download) | translate" [attr.aria-label]="(downloading() ? I18N.photo_detail.downloading : I18N.gallery.selection.download) | translate">@if (downloading()) { <mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate"></mat-spinner> } @else { <mat-icon>download</mat-icon> }</button>
              <mat-menu #dlMenu="matMenu">
                <button mat-menu-item (click)="downloadSelected()"><mat-icon>image</mat-icon> {{ I18N.download.type_original | translate }}</button>
                @for (profile of auth.downloadProfiles(); track profile) {
                  <button mat-menu-item (click)="downloadSelected('darktable', profile)"><mat-icon>photo_filter</mat-icon> {{ profile }}</button>
                }
                <button mat-menu-item (click)="downloadSelected('raw')"><mat-icon>raw_on</mat-icon> {{ I18N.download.type_raw | translate }}</button>
              </mat-menu>
            } @else {
              <button mat-icon-button (click)="downloadSelected()" [disabled]="downloading()" [matTooltip]="(downloading() ? I18N.photo_detail.downloading : I18N.gallery.selection.download) | translate" [attr.aria-label]="(downloading() ? I18N.photo_detail.downloading : I18N.gallery.selection.download) | translate">@if (downloading()) { <mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate"></mat-spinner> } @else { <mat-icon>download</mat-icon> }</button>
            }
          </div>
        </div>
      }
    </div>

    <!-- Scroll-to-top button: rides on top of the notice stack while one is up, so the two never share the corner -->
    <ng-template #scrollTopFab let-fabClass>
      <button
        mat-mini-fab
        [class]="fabClass"
        [matTooltip]="I18N.gallery.scroll_to_top | translate"
        [attr.aria-label]="I18N.gallery.scroll_to_top | translate"
        (click)="scrollToTop()"
      >
        <mat-icon>arrow_upward</mat-icon>
      </button>
    </ng-template>
    <ng-template #noticeClose let-kind let-alignTop="alignTop">
      <button mat-icon-button data-notice-close class="!w-7 !h-7 !min-w-0 !p-0 !inline-flex !items-center !justify-center -mr-1 shrink-0" [class.self-start]="alignTop" (click)="dismissNotice(kind)"
              [attr.aria-describedby]="'notice-text-' + kind"
              [matTooltip]="I18N.ui.buttons.dismiss | translate"
              [attr.aria-label]="I18N.ui.buttons.dismiss | translate">
        <mat-icon class="!text-base !w-4 !h-4 !leading-4">close</mat-icon>
      </button>
    </ng-template>
    @if (scrollTopShown() && !noticeStackVisible()) {
      <ng-container *ngTemplateOutlet="scrollTopFab; context: { $implicit: '!fixed right-4 lg:right-6 bottom-[60px] lg:bottom-6 z-40' }" />
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
        [personLinks]="!pinned()"
        (personSelected)="store.updateFilter('person_id', $event)"
      />
    }


    <!-- Right-click menu, shared by every card. Declared at the template root,
         outside every conditional block and loop, so the photoMenu reference is
         in scope of all three grid branches. -->
    <app-gallery-photo-menu
      #photoMenu
      [findSimilar]="!pinned()"
      [isEdition]="auth.isEdition()"
      [config]="store.config()"
      [albums]="albumOptions()"
      [downloadProfiles]="auth.downloadProfiles()"
      [canCompare]="canCompareSelection()"
      [viewScoped]="viewScoped()"
      [downloading]="downloading()"
      (action)="onPhotoMenuAction($event)"
      (closed)="onPhotoMenuClosed($event)"
    />
  `,
  changeDetection: ChangeDetectionStrategy.Eager,
  host: {
    class: 'block h-full',
    // meta.a is Cmd+A: macOS's select-all, the key a Mac user actually presses.
    // control.a keeps working on Windows/Linux (and on macOS for Ctrl+A).
    '(document:keydown.control.a)': 'onSelectAllShortcut($event)',
    '(document:keydown.meta.a)': 'onSelectAllShortcut($event)',
    '(document:keydown)': 'onGalleryShortcut($event)',
  },
})
export class GalleryComponent implements OnInit, OnDestroy {
  protected readonly I18N = i18nKeys();
  protected readonly MAX_REFRESH_PATHS = MAX_REFRESH_PATHS;
  protected readonly store = inject(GalleryStore);
  protected readonly auth = inject(AuthService);
  private readonly cardActionsService = inject(CardActionsService);
  private readonly keymap = inject(KeyboardMappingService);
  /** The user's hover-button layout for every card, from localStorage. */
  protected readonly cardActions = this.cardActionsService.config;
  protected readonly scan = inject(ScanService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly bottomSheet = inject(MatBottomSheet);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialog);
  private readonly albumService = inject(AlbumService);
  private readonly journal = inject(UserActivityJournal);
  private readonly photoActions = inject(PhotoActionsService);
  private readonly undoService = inject(UndoService);
  private readonly sequenceOverrides = inject(SequenceOverrideService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly stacks = inject(PhotoStackService);
  private readonly stackActions = inject(StackActionsService);
  private readonly outlet = inject(RouterOutlet, { optional: true });
  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly ngZone = inject(NgZone);
  private parked = false;
  private resumeNavigation = 0;
  // Detaching loses the DOM scroll position and focus.
  private returnTo: ReturnTarget | null = null;
  private readonly api = inject(ApiService);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly liveAnnouncer = inject(LiveAnnouncer);
  private readonly galleryToolbar = viewChild<TemplateRef<unknown>>('galleryToolbar');
  private readonly toolbarSearch = viewChild<ElementRef<HTMLInputElement>>('toolbarSearch');

  // Album options for "Add to album" menu
  protected readonly albumOptions = signal<Album[]>([]);
  protected readonly downloading = signal(false);

  // "Keep top N%" cull dial: keep the top N% of the current view, select the rest.
  protected readonly keepPercent = signal(20);
  protected readonly keepApplying = signal(false);
  protected readonly keepPreviewKeep = computed(() => Math.ceil(this.store.photoTotal() * this.keepPercent() / 100));
  protected readonly keepPreviewCut = computed(() => Math.max(0, this.store.photoTotal() - this.keepPreviewKeep()));

  private resizeObserver: ResizeObserver | null = null;
  private readonly scrollDirective = viewChild(InfiniteScrollDirective);
  private readonly filterSidebar = viewChild(GalleryFilterSidebarComponent);
  private readonly filterDrawer = viewChild<MatSidenav>('filterDrawer');
  private readonly selectionBar = viewChild<ElementRef<HTMLElement>>('selectionBar');
  private readonly noticeHost = viewChild<ElementRef<HTMLElement>>('noticeHost');
  private readonly destroyRef = inject(DestroyRef);
  private readonly staleness = inject(StalenessGuardFactory);
  private readonly injector = inject(Injector);
  private readonly document = inject(DOCUMENT);
  private readonly scrollContent = viewChild(MatSidenavContent);
  private readonly sidenavContainer = viewChild(MatSidenavContainer);
  private readonly ownTooltips = viewChildren(MatTooltip);
  private readonly menus = viewChildren(MatMenuTrigger);
  private readonly photoMenu = viewChild(GalleryPhotoMenuComponent);
  private readonly selects = viewChildren(MatSelect);
  private readonly cards = viewChildren(PhotoCardComponent);

  /** True once the gallery content is scrolled far enough to show the scroll-to-top button. */
  protected readonly showScrollTop = signal(false);
  /** The scroll-to-top FAB applies: scrolled down with no selection card in its corner. */
  protected readonly scrollTopShown = computed(() => this.showScrollTop() && !this.selectionCount());

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
  protected readonly allLoadedSelected = computed(() => {
    const photos = this.store.photos();
    if (!photos.length) return false;
    if (this.viewScoped()) {
      const excluded = this.excludedPaths();
      return photos.every(photo => !excluded.has(photo.path));
    }
    const selected = this.selectedPaths();
    return photos.every(photo => selected.has(photo.path));
  });

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
    && this.store.photoTotal() > this.store.photos().length,
  );

  /** True when the device has no hover capability (touch device) */
  protected readonly isTouchDevice = signal(false);
  /** Touch-first device: the right-click menu stays off so the native
   *  long-press behaviour is kept. Read once, unlike the looser `(hover: none)`
   *  behind `isTouchDevice`, which only steers the tooltip. */
  protected readonly touchOnly = signal(false);
  /** Grid index of the card the photo menu was opened on, for focus hand-back. */
  private photoMenuIndex = -1;

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

  /** Whether the viewport is md+ (768px) — drives the side/over drawer, container padding and hover tooltips */
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

  /** Effective gallery mode: grid until the container has been measured, then the user's choice at every width */
  readonly effectiveGalleryMode = computed(() =>
    this.containerWidth() > 0 ? this.store.galleryMode() : 'grid',
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

  /** An assistant-pinned list is shown: the filter controls are hidden so no edit can drop it. */
  protected readonly pinned = computed(() => this.store.pinnedPaths() !== null);

  /**
   * Whether the end drawer currently shows details rather than filters.
   *
   * The filters win while they are open: they are an explicit, transient action,
   * and the rail is a standing preference to come back to once they are closed.
   */
  readonly detailsRailVisible = computed(
    () => this.panelMode() && (!this.store.filterDrawerOpen() || this.pinned()),
  );

  /** Set kinds whose sets are currently collapsed behind one frame.
   *
   *  A tile only earns its set badge while the matching toggle is hiding the
   *  rest of the set. With the toggle off every frame is on screen in its own
   *  right, and badging all of them would say nothing.
   */
  readonly collapsedSetKinds = computed(() => {
    const f = this.store.filters();
    const kinds: string[] = [];
    if (f.hide_bursts) kinds.push('burst');
    if (f.hide_duplicates) kinds.push('duplicate');
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

  /** The mobile filter drawer overlays the content (and anything outside the sidenav container). */
  protected readonly overDrawerOpen = computed(() => !this.isDesktop() && this.store.filterDrawerOpen());

  /** How far the notices must rise to clear the floating selection card: non-zero only while the
   *  card exists AND overlaps the notice stack horizontally (see `noticeLiftPx`). */
  private readonly selectionBarOverlap = signal(0);

  /** Card height plus its bottom margin (distance from the host bottom to the card top); sizes the
   *  grid's end spacer. Floored so a single-row card still leaves the last row clear. */
  protected readonly selectionBarReservePx = signal(112);

  /** Shared bottom margin of the card and the notices: 16px md+, 8px below. */
  private readonly floatMarginPx = computed(() => this.isDesktop() ? 16 : 8);

  /** Bottom offset of the floating notices: the shared margin, plus the card's reach when they overlap it. */
  protected readonly noticeBottomPx = computed(() => this.floatMarginPx() + this.selectionBarOverlap());

  /** Track the selection card's geometry for as long as the card exists. */
  private readonly trackSelectionBar = effect(onCleanup => {
    const bar = this.selectionBar()?.nativeElement;
    const host = this.noticeHost()?.nativeElement;
    const content = this.scrollContent()?.getElementRef().nativeElement;
    // Re-measure when the drawer opens/closes (changes the card's right cap and wrap).
    this.noticeRightPx();
    // The notice stack renders after this effect runs; re-measure once it is in the DOM.
    const noticesShown = this.noticesShown();
    if (!bar || !host || typeof ResizeObserver === 'undefined') {
      this.selectionBarOverlap.set(0);
      return;
    }
    const measure = () => {
      const hostRect = host.getBoundingClientRect();
      const barRect = bar.getBoundingClientRect();
      const notices = host.querySelector('[data-gallery-notices]')?.getBoundingClientRect() ?? null;
      this.selectionBarReservePx.set(Math.max(112, Math.ceil(hostRect.bottom - barRect.top)));
      this.selectionBarOverlap.set(noticeLiftPx({
        hostBottom: hostRect.bottom,
        barTop: barRect.top,
        barLeft: barRect.left - hostRect.left,
        barRight: barRect.right - hostRect.left,
        noticeLeft: notices ? notices.left - hostRect.left : null,
        noticeRight: notices ? notices.right - hostRect.left : null,
      }));
    };
    measure();
    if (noticesShown) afterNextRender(measure, { injector: this.injector });
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    observer.observe(host);
    if (content) observer.observe(content);
    onCleanup(() => {
      observer.disconnect();
      this.selectionBarOverlap.set(0);
    });
  });

  /** Keeps the stack's left edge at least one margin from the host's left edge when the right inset is large. */
  protected readonly noticeMaxWidth = computed(() => `calc(100% - ${this.noticeRightPx() + this.floatMarginPx()}px)`);

  /** Gap between the gallery content's right edge (end drawer and scrollbar excluded) and the host's. */
  private readonly noticeInsetPx = signal(0);

  /** Right offset of the floating notices: a margin (16px md+, 8px below) plus the drawer/scrollbar gap. */
  protected readonly noticeRightPx = computed(() => this.noticeInsetPx() + this.floatMarginPx());

  /** Re-measure the drawer/scrollbar gap whenever the host or the content box resizes. */
  private readonly trackNoticeInset = effect(onCleanup => {
    const host = this.noticeHost()?.nativeElement;
    const content = this.scrollContent()?.getElementRef().nativeElement;
    if (!host || !content || typeof ResizeObserver === 'undefined') {
      this.noticeInsetPx.set(0);
      return;
    }
    const measure = () => this.noticeInsetPx.set(Math.max(0, Math.ceil(
      host.getBoundingClientRect().right - (content.getBoundingClientRect().left + content.clientWidth))));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    observer.observe(content);
    onCleanup(() => {
      observer.disconnect();
      this.noticeInsetPx.set(0);
    });
  });

  /** Why photos are hidden, in words: "287 burst repeat(s), 23 blink(s)...". */
  protected readonly hiddenReasons = computed(() => {
    this.i18n.translations();
    const h = this.store.hiddenSummary();
    const reasons: [number, string][] = [
      [h.bursts, I18N.gallery.hidden_banner.reason_bursts],
      [h.blinks, I18N.gallery.hidden_banner.reason_blinks],
      [h.duplicates, I18N.gallery.hidden_banner.reason_duplicates],
      [h.brackets, I18N.gallery.hidden_banner.reason_brackets],
      [h.panoramas, I18N.gallery.hidden_banner.reason_panoramas],
    ];
    return reasons.filter(([n]) => n > 0).map(([n, key]) => this.i18n.t(key, { n })).join(', ');
  });

  /** Show the hidden-photos banner when filters are hiding rows and at least one is on. */
  readonly showHiddenBanner = computed(() => {
    const f = this.store.filters();
    return this.store.hiddenSummary().total > 0
      && (f.hide_blinks || f.hide_bursts || f.hide_duplicates || f.hide_brackets || f.hide_panoramas);
  });

  /** Offer the restore only while all five are still off, so it never fights a manual change.
   *  The stash itself (and showAllHidden()/restoreHidden()) lives on GalleryStore — the
   *  timeline's reachability banner offers the same affordance and needs the same state.
   *  Suppressed under an "only X" filter too: that view shows a subset by design, so the
   *  banner's "showing all photos" sentence would be false while one is up. The stash
   *  survives, so turning the only-filter off brings the offer back. */
  readonly canRestoreHidden = computed(() => {
    const stash = this.store.hiddenFiltersStash();
    if (!stash) return false;
    const f = this.store.filters();
    return !f.hide_blinks && !f.hide_bursts && !f.hide_duplicates && !f.hide_brackets
      && !f.hide_panoramas
      && !f.blinks_only && !f.duplicates_only && !f.show_rejected;
  });

  /** Notices closed in this tab, with the signatures each had when closed. */
  private readonly noticeDismissals = signal<NoticeDismissals>(readNoticeDismissals());

  /** What makes each notice "the same one": its scope (never its sort) or its count, never the live review counts. */
  private readonly noticeSignatures = computed<Record<NoticeKind, string>>(() => ({
    review_progress: this.store.reviewProgressKey(),
    review_bookmark: JSON.stringify(this.store.reviewBookmark()?.filters ?? null),
    hidden: JSON.stringify([this.store.reviewProgressKey(), this.store.hiddenSummary().total]),
    restore_hidden: JSON.stringify(this.store.hiddenFiltersStash()),
    active_filters: JSON.stringify(activeFilterKeys(this.store.filters())),
    render_migration: String(this.renderMigrationPending()),
  }));

  private noticeClosed(kind: NoticeKind): boolean {
    return this.noticeDismissals()[kind]?.includes(this.noticeSignatures()[kind]) ?? false;
  }

  /** Close one notice for this tab, for as long as it stays the same notice. Nothing else changes. */
  protected dismissNotice(kind: NoticeKind): void {
    const host = this.noticeHost()?.nativeElement;
    const hadFocus = !!host?.contains(document.activeElement);
    const next = withDismissal(this.noticeDismissals(), kind, this.noticeSignatures()[kind]);
    this.noticeDismissals.set(next);
    saveNoticeDismissals(next);
    // The focused × leaves the DOM with its card: hand focus to the next card's ×, else the grid.
    if (hadFocus) afterNextRender(() => {
      const target = host?.querySelector<HTMLElement>('[data-notice-close]') ?? this.scrollContent()?.getElementRef().nativeElement;
      if (!target) return;
      if (!target.hasAttribute('tabindex') && !target.matches('button')) target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: true });
    }, { injector: this.injector });
  }

  /** The review-progress card: on in the user menu, counts loaded, and not closed in this tab. */
  /** An empty scope has nothing to review, so it gets no "0 of 0" card. */
  protected readonly reviewProgressShown = computed(() =>
    this.store.reviewProgressVisible() && !!this.store.reviewProgress()?.total && !this.noticeClosed('review_progress'));
  protected readonly reviewBookmarkShown = computed(() => !!this.store.reviewBookmark() && !this.noticeClosed('review_bookmark'));
  protected readonly hiddenNoticeShown = computed(() => this.showHiddenBanner() && !this.noticeClosed('hidden'));
  protected readonly restoreNoticeShown = computed(() => this.canRestoreHidden() && !this.noticeClosed('restore_hidden'));

  /** The active-filters card: any filter on, outside an album. An album view is skipped because a
   *  smart album's saved filters are always "active" there (a permanent card), and the reset would
   *  also leave the album -- the sidebar's reset stays the way out. The album id itself is never counted. */
  protected readonly activeFiltersNoticeShown = computed(() =>
    this.store.activeFilterCount() > 0 && !this.store.currentAlbum() && !this.noticeClosed('active_filters'));

  /** The cards that are up right now, in stack order: the one list the stack's presence,
   *  the collapsed pill's count and the collapse lifecycle all derive from. */
  private readonly shownNoticeKinds = computed<NoticeKind[]>(() => ([
    ['review_progress', this.reviewProgressShown()], ['review_bookmark', this.reviewBookmarkShown()],
    ['hidden', this.hiddenNoticeShown()], ['restore_hidden', this.restoreNoticeShown()],
    ['active_filters', this.activeFiltersNoticeShown()], ['render_migration', this.showRenderMigrationBanner()],
  ] as [NoticeKind, boolean][]).filter(([, shown]) => shown).map(([kind]) => kind));

  /** Whether the floating notice stack has at least one card to show. */
  protected readonly noticesShown = computed(() => this.shownNoticeKinds().length > 0);

  /** The stack steps aside while the mobile 'over' drawer is open (see the template comment). */
  protected readonly noticeStackVisible = computed(() => !this.overDrawerOpen() && this.noticesShown());

  /** How many cards are up right now — the collapsed pill's count. */
  protected readonly shownNoticeCount = computed(() => this.shownNoticeKinds().length);

  /** Auto-collapse: after a few seconds the stack folds into a count pill so it
   *  stops covering the grid. Hovering the stack, a new or dismissed card, or a
   *  click on the pill expand it again and restart the countdown. Session-only:
   *  nothing is persisted, and parking the gallery pauses the countdown. */
  private static readonly NOTICE_COLLAPSE_MS = 6000;
  private noticeCollapseTimer: ReturnType<typeof setTimeout> | null = null;
  private noticePointerInside = false;
  private noticeSignatureSeen = '';
  private noticeDrawerSeen = false;
  protected readonly noticesCollapsed = signal(false);

  /** Which cards are up right now. Any change in this set is fresh activity:
   *  it re-expands the stack and grants a new full window. */
  private readonly noticesSignature = computed(() => this.shownNoticeKinds().join(','));

  private disarmNoticeCollapse(): void {
    if (this.noticeCollapseTimer !== null) {
      clearTimeout(this.noticeCollapseTimer);
      this.noticeCollapseTimer = null;
    }
  }

  /** Restart the collapse countdown, unless the pointer rests on the stack or the
   *  stack is not on screen (no cards, or the mobile drawer); keyboard focus on a
   *  card is checked when it fires. The app is zoneless, but the test build loads
   *  zone.js: the timer runs outside it so a pending 6 s timeout never holds
   *  whenStable, and the fold therefore runs its own change detection. */
  protected armNoticeCollapse(): void {
    this.disarmNoticeCollapse();
    if (this.noticePointerInside || !this.noticeStackVisible()) return;
    this.noticeCollapseTimer = this.ngZone.runOutsideAngular(() => setTimeout(() => {
      this.noticeCollapseTimer = null;
      // Keyboard focus on a card holds the stack open; leaving it re-arms (noticeFocusLeft).
      if (this.noticeKeyboardFocused()) return;
      this.noticesCollapsed.set(true);
      this.changeDetector.detectChanges();
    }, GalleryComponent.NOTICE_COLLAPSE_MS));
  }

  protected noticePointerChange(inside: boolean): void {
    this.noticePointerInside = inside;
    this.armNoticeCollapse();
  }

  /** Whether a keyboard user is on a control in the stack. Read live rather than
   *  tracked from focusin/focusout: a focused card that leaves the DOM fires no
   *  focusout, and a flag would then hold the stack open for good. */
  private noticeKeyboardFocused(): boolean {
    const active = document.activeElement;
    return !!active && !!this.noticeHost()?.nativeElement.querySelector('[data-gallery-notices]')?.contains(active)
      && active.matches(':focus-visible');
  }

  /** Focus left a control of the stack: grant a fresh window once it has settled. */
  protected noticeFocusLeft(event: FocusEvent): void {
    if ((event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) return;
    this.armNoticeCollapse();
  }

  /** The pill replaces itself with the cards. When it held focus, hand focus to
   *  the first card's ×, as a dismissal does, so it never falls back to the page. */
  protected expandNotices(event: Event): void {
    const hadFocus = document.activeElement === event.currentTarget;
    this.noticesCollapsed.set(false);
    this.armNoticeCollapse();
    if (hadFocus) afterNextRender(() => {
      this.noticeHost()?.nativeElement.querySelector<HTMLElement>('[data-notice-close]')?.focus({ preventScroll: true });
    }, { injector: this.injector });
  }

  /** Fold/unfold the stack as its card set changes: the first cards arm the
   *  countdown, a new or dismissed card re-expands with a fresh window, an
   *  emptied stack resets so the next arrival starts expanded. The mobile
   *  'over' drawer hides the stack entirely, so the countdown waits and starts
   *  afresh when it closes. A stack that leaves the DOM fires no pointerleave,
   *  so it also clears the pointer hold. */
  private readonly noticeCollapseLifecycle = effect(() => {
    const signature = this.noticesSignature();
    const drawerOpen = this.overDrawerOpen();
    untracked(() => {
      const previous = this.noticeSignatureSeen;
      const drawerWasOpen = this.noticeDrawerSeen;
      this.noticeDrawerSeen = drawerOpen;
      if (!signature || drawerOpen) {
        this.noticePointerInside = false;
        this.disarmNoticeCollapse();
        // Behind the drawer the set is not "seen": a card that joined meanwhile
        // still re-expands the stack once the drawer closes.
        if (!signature) {
          this.noticeSignatureSeen = '';
          this.noticesCollapsed.set(false);
        }
        return;
      }
      this.noticeSignatureSeen = signature;
      if (signature !== previous) {
        this.noticesCollapsed.set(false);
        this.armNoticeCollapse();
      } else if (drawerWasOpen && !this.noticesCollapsed()) {
        this.armNoticeCollapse();
      }
    });
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
  /** Shell shared by the cards of the floating notice stack. */
  protected readonly NOTICE_CARD_CLASS = 'pointer-events-auto px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] shadow-lg flex items-center gap-3 text-sm';

  /** RAW rows still on the pre-fix rendering, as of the last config load. */
  readonly renderMigrationPending = computed(
    () => this.store.config()?.render_migration?.pending ?? 0,
  );

  readonly showRenderMigrationBanner = computed(
    () => this.renderMigrationPending() > 0 && !this.noticeClosed('render_migration'),
  );

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

  /** Cards in the row branch hide their details except in grid mode with details switched on. */
  protected readonly rowCardHideDetails = computed(
    () => this.effectiveGalleryMode() === 'mosaic' || this.effectiveHideDetails(),
  );

  /** Unified row model for the active mode. */
  readonly rowsModel = computed<GalleryRow[]>(() => {
    const photos = this.store.photos();
    // Rows live inside the p-2 md:p-4 container - subtract its padding
    const width = this.containerWidth() - (this.isDesktop() ? 32 : 16);
    if (!photos.length || width <= 0) return [];
    const gap = GalleryComponent.ROW_GAP;
    const build = this.effectiveGalleryMode() === 'mosaic'
      ? (ps: Photo[]) => buildMosaicRows(ps, width, this.cardWidth(), gap)
      : (ps: Photo[]) => buildGridRows(ps, width, this.cardWidth(), gap, this.effectiveHideDetails(), this.isDesktop());
    return build(photos);
  });

  readonly totalRowsHeight = computed(() => totalRowsHeight(this.rowsModel()));

  private readonly visibleRange = computed(() => {
    const rows = this.rowsModel();
    if (!this.virtualOn()) return { first: 0, last: rows.length - 1 };
    return windowRange(rows, this.relScrollTop(), this.viewportH() || 900, GalleryComponent.OVERSCAN);
  });

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
      this.touchOnly.set(window.matchMedia('(hover: none) and (pointer: coarse)').matches);
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

    // Capture before the outlet detaches the DOM and loses scroll and focus.
    this.router.events.pipe(filter(e => e instanceof NavigationStart), takeUntilDestroyed()).subscribe(() => {
      if (!this.router.currentNavigation?.()?.extras?.state?.[REVIEW_RESUME_NAVIGATION]) this.resumeNavigation++;
      if (this.parked) return;
      const focus = document.activeElement;
      const index = Number((focus?.closest('[data-pidx]') as HTMLElement | null)?.dataset['pidx']);
      // The photo the focused card belongs to, or the cursor's when focus is elsewhere.
      const path = Number.isInteger(index) ? this.store.photos()[index]?.path ?? null : this.activePath();
      const viewport = this.scrollContent()?.getElementRef().nativeElement.getBoundingClientRect();
      const card = path === null ? null : this.cardRect(this.indexOfPath(path));
      const scroll = this.scrollContent()?.measureScrollOffset('top') ?? 0;
      this.returnTo = path !== null && viewport && card && viewport.width > 0 && viewport.height > 0
        ? { scroll, focus, path, anchor: { offset: card.top - viewport.top, width: viewport.width, height: viewport.height } }
        : { scroll, focus, path, anchor: null };
    });
    this.outlet?.detachEvents.pipe(takeUntilDestroyed()).subscribe(component => {
      if (component !== this) return;
      this.parked = true;
      this.store.parkListingReads();
      this.disarmNoticeCollapse();
      // Pending filter edits would otherwise replace the photo URL.
      this.filterSidebar()?.cancelPendingSearch();
      this.cancelToolbarSearch();
      if (this.store.slideshowActive()) {
        this.store.slideshowActive.set(false);
        // Detached views need an explicit render to release slideshow timers and listeners.
        this.changeDetector.detectChanges();
      }
      // A tooltip left showing would sit over the photo page and swallow its first Escape.
      closeOverlayDirectives(this.ownTooltips(), this.menus(), this.selects());
      // Context-menu triggers are separate from MatMenuTrigger; all cards share this panel.
      this.photoMenu()?.menu().closed.emit();
      for (const card of this.cards()) card.closeOverlays();
      this.filterSidebar()?.closeOverlays();
      this.setGalleryChrome(false);
    });
    this.outlet?.attachEvents.pipe(takeUntilDestroyed()).subscribe(component => {
      if (component !== this) return;
      this.parked = false;
      void this.store.resumeListingReads();
      // Returning from a photo restarts the notice countdown: the reviewer is
      // looking again, so the stack earns a fresh window before folding.
      if (!this.noticesCollapsed()) this.armNoticeCollapse();
      this.setGalleryChrome(true);
      this.tooltipPhoto.set(null);
      // A resize while parked measured the detached drawer as 0 and zeroed the content margin.
      this.sidenavContainer()?.updateContentMargins();
      const back = this.returnTo;
      this.returnTo = null;
      if (back) {
        this.scrollContent()?.scrollTo({ top: back.scroll });
        // The photo page's arrows replace its URL, so the page being left names the photo viewed last.
        const left = this.router.currentNavigation()?.previousNavigation?.finalUrl;
        const viewed = left?.root.children['primary']?.segments[0]?.path === PHOTO_PATH ? left.queryParamMap.get('path') : null;
        const viewedAt = viewed && viewed !== back.path ? this.indexOfPath(viewed) : -1;
        if (viewedAt >= 0) {
          this.setCursor(viewedAt);
          this.focusCard(viewedAt);
        } else {
          // The detach blurred the focused card and `onGridFocusOut` cleared the cursor, so put it back first.
          const at = back.path === null ? -1 : this.indexOfPath(back.path);
          this.setCursor(at);
          const onCard = !!back.focus?.closest('[data-pidx]');
          // A card whose photo is gone is about to be destroyed: do not focus it.
          if (back.focus instanceof HTMLElement && back.focus.isConnected && (!onCard || at >= 0)) {
            back.focus.focus({ preventScroll: true });
          }
          if (at >= 0 && !onCard) this.restoreCursorFocus();
          if (at >= 0 && back.anchor) this.restoreReturnAnchor(back.path, back.anchor);
        }
      }
      this.refreshSideData();
    });

    // Sync store.filterDrawerOpen signal → mat-sidenav. The details rail shares
    // this drawer, so it keeps the strip open on its own once the filters close.
    effect(() => {
      // The persisted flag is left alone while pinned: the drawer only stays shut.
      const open = (this.store.filterDrawerOpen() && !this.pinned()) || this.panelMode();
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
    this.store.galleryMounts.update(n => n + 1);
    this.setGalleryChrome(true);
    // Read (and clear) BEFORE tryRestoreView: a scoped "open this set" request
    // means the user wants that new scoped view, never a resumed previous one.
    const setScope = this.consumeSetScopeState();
    // A parameterless landing on `/` is the nav icon's return from another
    // page (a reload carries its own query params, an album route its
    // albumId). The session's last gallery query is merged into the filters
    // AFTER loadConfig rebuilds them -- directly, not through a navigation:
    // the ActivatedRoute snapshot does not refresh for same-component
    // param-only navigations, so a navigate-then-read silently lost the
    // restored filters (the album-route return hit exactly that).
    const savedQuery = (!setScope && !this.route.snapshot.paramMap.get('albumId')
      && !Object.keys(this.route.snapshot.queryParams).length)
      ? this.store.readGallerySessionQuery()
      : null;
    const routeAlbumId = this.route.snapshot.paramMap.get('albumId');
    if (!setScope && this.tryRestoreView()) return;
    // Reset album state to avoid stale singleton data; loadConfig() resets filters from scratch
    this.store.currentAlbum.set(null);
    this.store.initializing.set(true);
    await this.store.loadConfig();
    // Record what THIS init resolved to: a plain URL entry must write its own
    // filters (syncUrl never runs for one), and the albums page shares
    // loadConfig but must never touch this memory. An album route skips the
    // write -- its filters belong to the album view, not the plain gallery.
    if (!routeAlbumId) {
      this.store.saveSessionQuery();
    }
    if (savedQuery) {
      this.store.applySessionQuery(savedQuery);
    }
    // Apply the ephemeral set scope AFTER loadConfig, which replaces `filters`
    // wholesale -- applying it before would just be discarded. Never in the
    // URL: sequence_group_id is renumbered on every detection pass, so a
    // bookmarked/shared/reloaded link must never resolve to a different set.
    if (setScope) {
      this.store.filters.update(current => ({ ...current, ...setScope }));
    }
    // Set album_id from route path param (for /album/:albumId route)
    const albumId = this.store.filters().album_id === '0' ? null
      : this.store.filters().album_id || this.route.snapshot.paramMap.get('albumId');
    if (albumId) {
      try {
        const album = await firstValueFrom(this.albumService.get(+albumId));
        if (album.smart_filter_json) {
          // Apply saved filters BEFORE setting currentAlbum (avoids effect saving defaults)
          const savedJson = album.smart_filter_json;
          this.store.filters.update(current => applyQueryParams(applySavedAlbumFilters(current, savedJson, albumId), this.route.snapshot.queryParams));
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
    this.refreshSideData();
    // IntersectionObserver fires too early before DOM paint — defer recheck
    requestAnimationFrame(() => setTimeout(() => this.scrollDirective()?.recheck()));
    if (this.store.config()?.features?.show_albums) {
      firstValueFrom(this.albumService.list()).then(res =>
        this.albumOptions.set(res.albums.filter(a => !a.is_smart)),
      ).catch(() => {});
    }
  }

  private indexOfPath(path: string): number {
    return this.store.photos().findIndex(photo => photo.path === path);
  }

  /** The rendered card's rect for a photo index, or null when it is not in the DOM. */
  private cardRect(index: number): DOMRect | null {
    return index >= 0 ? document.querySelector(`[data-pidx="${index}"]`)?.getBoundingClientRect() ?? null : null;
  }

  /** Re-anchor after drawer margins and card heights settle, including parked resizes. */
  private restoreReturnAnchor(path: string, anchor: ReturnAnchor): void {
    const navigation = this.resumeNavigation;
    let interacted = false;
    const veto = () => { interacted = true; };
    const cleanup = () => {
      document.removeEventListener('pointerdown', veto, true);
      document.removeEventListener('keydown', veto, true);
    };
    document.addEventListener('pointerdown', veto, true);
    document.addEventListener('keydown', veto, true);
    const unregister = this.destroyRef.onDestroy(cleanup);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      try {
        if (interacted || this.parked || this.destroyRef.destroyed || navigation !== this.resumeNavigation) return;
        // Responsive DOM removal can passively clear the cursor; explicit new input vetoes restoration.
        if (this.activePath() !== null && this.activePath() !== path) return;
        const index = this.indexOfPath(path);
        if (index < 0) return;
        const focus = document.activeElement;
        if (focus && focus !== document.body && focus !== document.documentElement
          && !focus.closest(`[data-pidx="${index}"]`)) return;
        const content = this.scrollContent();
        const viewport = content?.getElementRef().nativeElement.getBoundingClientRect();
        const card = this.cardRect(index);
        if (!content || !viewport || !card || viewport.height <= 0) return;
        const resized = viewport.width !== anchor.width || viewport.height !== anchor.height;
        const offset = resized ? Math.max(0, Math.min(anchor.offset, viewport.height - card.height)) : anchor.offset;
        const delta = card.top - viewport.top - offset;
        if (Math.abs(delta) >= 1) content.scrollTo({ top: Math.max(0, content.measureScrollOffset('top') + delta) });
        this.setCursor(index);
        this.focusCard(index, false, false);
      } finally { cleanup(); unregister(); }
    }));
  }

  private setGalleryChrome(active: boolean): void {
    this.pageHelp.setDescription(active ? I18N.gallery.help : null);
    const toolbar = this.galleryToolbar();
    if (toolbar) {
      if (active) this.headerSlot.set(toolbar);
      else this.headerSlot.clear(toolbar);
    }
  }

  private refreshSideData(): void {
    void this.store.loadTypeCounts();
    void this.store.loadFilterOptions();
  }

  ngOnDestroy(): void {
    this.cancelToolbarSearch();
    this.disarmNoticeCollapse();
    this.setGalleryChrome(false);
    this.saveViewSnapshot();
    this.resizeObserver?.disconnect();
    this.desktop.cleanup();
    this.railWide.cleanup();
  }

  /** Capture scroll + query state so back-navigation can skip the reload. */
  private saveViewSnapshot(): void {
    if (!this.store.photos().length) return;
    this.store.viewSnapshot.set({
      scrollTop: this.parked ? this.returnTo?.scroll ?? 0 : this.scrollContent()?.measureScrollOffset('top') ?? 0,
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
    void this.store.resumeListingReads();
    this.refreshSideData();
    return true;
  }

  /** Save/restore sidebar scroll position on drawer open/close */
  onFilterDrawerChange(open: boolean): void {
    // openedChange fires when an animation ends, so a close() followed quickly by
    // open() reports the stale close after the drawer is open again. Recording it
    // would make the sync effect close the drawer, whose pending open would then
    // reopen it -- an endless open/close loop.
    if (open !== this.filterDrawer()?.opened) return;
    // The details rail holds this drawer open by itself, so an `open` it caused
    // must not be recorded as "the user asked for filters" — otherwise closing
    // the filters would immediately re-open them and the toggle would be stuck.
    if (open && this.detailsRailVisible()) return;
    // A close caused by the pin is not the user's choice; keep the persisted flag.
    if (this.pinned()) return;
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
    if (this.parked) return;
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

  protected async copyPaths(explicitPaths?: string[]): Promise<void> {
    // Copying changes nothing, so it says so rather than borrowing the
    // mutation wording every other whole-view action confirms with.
    const paths = explicitPaths
      ?? await this.resolveSelectionPaths(I18N.gallery.selection.view_scope_copy_message);
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
    this.offerMutationUndo(result, i18nKey, params);
    // The view can move between the count and the write (another session, a
    // scan). Say so rather than absorbing it: the user approved a number.
    if (announced !== null && announced !== result.count) {
      this.snackBar.open(
        this.i18n.t(I18N.gallery.selection.view_scope_mismatch, { count: result.count, announced }),
        '', { duration: 5000 },
      );
    }
  }

  private offerMutationUndo(
    result: BatchResult,
    i18nKey: string,
    params: Record<string, string | number>,
    restoreSelection = true,
  ): void {
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
          if (restoreSelection) this.store.restoreSelection(result.snapshot.keys());
        },
      });
    } else {
      this.snackBar.open(this.i18n.t(i18nKey, params), '', { duration: 2000 });
    }
  }

  private async reviewSingle(path: string, decision: 'kept' | 'undecided'): Promise<BatchResult | null> {
    const result = await this.store.batchReview([path], decision, false);
    if (result) this.offerMutationUndo(result, this.I18N.review.updated, { count: result.count }, false);
    return result;
  }

  protected async batchReview(decision: 'kept' | 'undecided'): Promise<void> {
    await this.executeBatchAction(p => this.store.batchReview(p, decision), this.I18N.review.updated);
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
    } catch (error) {
      const notALadder = isBracketLadderRejection(kind, error);
      this.snackBar.open(
        this.i18n.t(notALadder ? I18N.culling.bracket.not_a_ladder : I18N.errors.action_failed),
        '', { duration: 3000 },
      );
      return;
    }
    this.store.patchSequenceOverride(paths, kind);
    this.clearSelection();
    this.undoService.register({
      labelKey: kind === 'bracket' ? I18N.gallery.selection.marked_bracket : I18N.gallery.selection.marked_panorama,
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

  /** Records which card the photo menu opened on, and drops the floating
   *  tooltip so it does not sit on top of the menu. */
  protected onCardContextMenu(index: number): void {
    this.photoMenuIndex = index;
    this.hideTooltip();
  }

  /** `'keydown'` is Escape/arrow-out and `'click'` is an item picked: both hand
   *  focus back to the card. A backdrop click or Tab leaves focus where the
   *  user put it. */
  protected onPhotoMenuClosed(reason: 'click' | 'keydown' | 'tab' | void): void {
    if (reason === 'keydown' || reason === 'click') this.focusCard(this.photoMenuIndex, false, false);
  }

  protected async onPhotoMenuAction(e: PhotoMenuActionEvent): Promise<void> {
    if (e.bulk) {
      if (isSheetAction(e.action)) await this.runSelectionAction(e.action);
      return;
    }
    await this.runSinglePhotoAction(e.action, e.photo);
  }

  /** The right-click menu's single-photo actions. The favorite, reject and
   *  rating ones go to the same store calls the card's own buttons make, so
   *  optimistic update, in-flight de-dup and revert-on-error come with them. */
  private async runSinglePhotoAction(action: PhotoMenuAction, photo: Photo): Promise<void> {
    const paths = [photo.path];
    switch (action.kind) {
      case 'review': await this.reviewSingle(photo.path, action.decision); break;
      case 'toggle-favorite': this.store.toggleFavorite(photo.path); break;
      case 'toggle-reject': this.store.toggleRejected(photo.path); break;
      case 'rate': this.store.setRating(photo.path, action.rating); break;
      case 'open': this.downloadPhoto(photo); break;
      case 'similar': this.openSimilar(photo, action.mode); break;
      case 'critique': this.openCritique(photo); break;
      case 'refresh': await this.photoActions.refreshPhotos(paths); break;
      case 'embed': this.embedMetadata(photo); break;
      case 'assign-face': this.openAddPerson(photo); break;
      case 'album': await this.addToAlbum(action.albumId, paths); break;
      case 'create-album': await this.createAlbumAndAdd(paths); break;
      case 'copy': await this.copyPaths(paths); break;
      case 'export': this.openExportDialog(paths); break;
      case 'cull': await this.openCullDialog(paths); break;
      case 'delete': await this.deleteSelected(paths); break;
      case 'download': await this.downloadSelected(action.type, action.profile, paths); break;
      // Selection-wide kinds: the single-photo menu never offers them.
      case 'stack':
      case 'favorite':
      case 'reject':
      case 'invert':
      case 'compare':
      case 'mark-panorama':
      case 'capture-date':
      case 'tags':
      case 'gps':
        break;
      default: return assertNever(action);
    }
  }

  protected async continueReview(): Promise<void> {
    const navigation = this.resumeNavigation;
    const ownsView = () => !this.destroyRef.destroyed && !this.parked && navigation === this.resumeNavigation;
    const path = await this.store.continueReview(ownsView);
    if (!ownsView()) return;
    const photo = path ? this.store.photos().find(p => p.path === path) : null;
    if (photo) this.downloadPhoto(photo);
  }

  protected readonly canCreateStack = computed(() => this.auth.isEdition() && !this.viewScoped() && this.selectionCount() >= STACK_MIN_MEMBERS && this.selectionCount() <= STACK_MAX_MEMBERS);

  protected readonly stackShortcut = computed(() => this.keymap.keymap().stack.toUpperCase());
  private stackOpening = false;

  protected async quickStack(): Promise<void> {
    if (!this.canOpenStackFlow()) return;
    const selection = this.selectedPaths();
    const paths = [...selection];
    const session = this.stacks.context();
    const live = () => !this.destroyRef.destroyed && !this.parked && this.stacks.isLive(session);
    const selectionClear = this.store.captureSelectionClear(paths);
    this.stackOpening = true;
    try {
      const preview = await firstValueFrom(this.stacks.previewRegroup(paths, 'selected').pipe(takeUntil(this.router.events.pipe(filter(event => event instanceof NavigationStart))), takeUntilDestroyed(this.destroyRef)));
      if (!live() || this.selectedPaths() !== selection || this.viewScoped()) return;
      if (preview.source_stacks.length) {
        this.stackOpening = false;
        await this.createStack();
        return;
      }
      // Create refuses newly stacked members too, closing the race after preview.
      const applied = await this.stackActions.commit(this.stacks.create(paths, paths[0]), {
        paths, action: 'create', session, live, labelKey: I18N.stacks.stacked, labelParams: { count: paths.length },
        onUndone: selectionClear.restore,
      });
      if (applied && live()) selectionClear.clear();
    } catch (error) {
      // A preview failure is not a membership conflict; 401/403/429 already have the interceptor's toast.
      if (!live() || error instanceof HttpErrorResponse && [401, 403, 429].includes(error.status)) return;
      const conflict = error instanceof HttpErrorResponse && error.status === 409;
      this.snackBar.open(this.i18n.t(conflict ? I18N.stacks.stack_failed : I18N.errors.action_failed), '', { duration: 5000 });
    } finally { this.stackOpening = false; }
  }

  private canOpenStackFlow(): boolean {
    return this.canCreateStack() && !this.stackOpening && !this.parked && !this.store.slideshowActive() && !this.dialog.openDialogs.length;
  }

  protected async createStack(): Promise<void> {
    if (!this.canOpenStackFlow()) return;
    this.stackOpening = true;
    try {
      const paths = [...this.selectedPaths()];
      const focused = this.store.focusedPath();
      await this.router.navigate(['/stacks/edit'], { state: { [STACK_EDITOR_HISTORY]: {
        version: 1, identity: this.auth.identity(), paths, activePath: focused && paths.includes(focused) ? focused : undefined, returnUrl: this.router.url,
      } } });
    } finally { this.stackOpening = false; }
  }

  protected async openStack(photo: Photo): Promise<void> {
    if (!photo.stack_id) return;
    this.downloadPhoto(photo);
  }

  protected async openStackSuggestions(): Promise<void> {
    const filters = this.store.filterPayload();
    if (!filters || !this.auth.isEdition()) return;
    if (!this.store.canScopeSelectionToView() || this.pinned()) return;
    await this.router.navigate(['/culling'], {
      queryParams: { mode: 'stacks', filters: JSON.stringify(filters), return: this.router.url },
    });
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
        canStack: this.canCreateStack(),
        viewScoped: this.viewScoped(),
        trashAvailable: this.store.config()?.cull?.trash_available ?? false,
      },
    });
    const action = await firstValueFrom(ref.afterDismissed());
    if (!action) return;
    await this.runSelectionAction(action);
  }

  /** Runs one bulk action on the current selection. Shared by the mobile
   *  sheet and the right-click menu's bulk mode so the two cannot drift. */
  protected async refreshSelectedPhotos(): Promise<void> {
    if (!this.viewScoped()) await this.photoActions.refreshPhotos([...this.selectedPaths()]);
  }

  private async runSelectionAction(action: SheetAction): Promise<void> {
    switch (action.kind) {
      case 'refresh': await this.refreshSelectedPhotos(); break;
      case 'stack': await this.createStack(); break;
      case 'review': await this.batchReview(action.decision); break;
      case 'favorite': await this.batchFavorite(); break;
      case 'reject': await this.batchReject(); break;
      case 'rate': await this.batchRate(action.rating); break;
      case 'album': await this.addToAlbum(action.albumId); break;
      case 'create-album': await this.createAlbumAndAdd(); break;
      case 'invert': this.invertSelection(); break;
      case 'compare': await this.compareSelection(); break;
      case 'export': this.openExportDialog(); break;
      case 'cull': await this.openCullDialog(); break;
      case 'capture-date': await this.openCaptureDateDialog(); break;
      case 'tags': await this.openManualTagsDialog(); break;
      case 'gps': await this.openBatchGpsDialog(); break;
      case 'delete': await this.deleteSelected(); break;
      case 'copy': await this.copyPaths(); break;
      case 'mark-panorama': await this.markAsPanorama(action.sequenceKind); break;
      case 'download': await this.downloadSelected(action.type, action.profile); break;
    }
  }

  protected async downloadSelected(type = 'original', profile?: string, explicitPaths?: string[]): Promise<void> {
    // Confirms below in its own words, against the count it actually resolved.
    const paths = explicitPaths ?? await this.resolveSelectionPaths(null);
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

  async addToAlbum(albumId: number, explicitPaths?: string[]): Promise<void> {
    // No filter-scoped form server-side, so a whole-view selection resolves to
    // paths here rather than adding nothing at all. Filing photos into an album
    // writes album_photos rows and leaves the photos themselves untouched, so
    // it must not confirm in the wording of a mutation.
    const paths = explicitPaths
      ?? await this.resolveSelectionPaths(I18N.gallery.selection.view_scope_album_message);
    if (!paths?.length) return;
    await firstValueFrom(this.albumService.addPhotos(albumId, paths));
    this.journal.record('album', paths, { album_id: albumId, action: 'add' });
    this.snackBar.open(this.i18n.t(I18N.albums.photos_added), '', { duration: 2000 });
    // Explicit paths come from the context menu on one photo: the user's
    // selection is theirs to keep.
    if (explicitPaths === undefined) this.clearSelection();
  }

  async createAlbumAndAdd(explicitPaths?: string[]): Promise<void> {
    const ref = this.dialog.open(CreateAlbumDialogComponent, { width: '400px' });
    const album = await firstValueFrom(ref.afterClosed());
    if (!album) return;
    this.albumOptions.update(list => [album, ...list]);
    await this.addToAlbum(album.id, explicitPaths);
  }

  async openScanLauncher(): Promise<void> {
    if (await this.scan.openLauncher()) {
      await this.store.loadTypeCounts();
      await this.store.reloadPhotos();
    }
  }

  openExportDialog(explicitPaths?: string[]): void {
    // Explicit paths name what to export, so the album route below -- which
    // exports the whole album whatever is selected -- must not claim them.
    if (explicitPaths !== undefined) {
      this.dialog.open(ExportEditorDialogComponent, { width: '420px', data: { paths: [...explicitPaths] } });
      return;
    }
    const albumId = this.route.snapshot.paramMap.get('albumId');
    if (albumId) {
      this.dialog.open(ExportEditorDialogComponent, { width: '420px', data: { albumId: +albumId } });
      return;
    }
    // Under view scope the dialog gets the filter, not a path list. The 10,000
    // ceiling (and its 412) applies either way: what this avoids is putting the
    // paths on the wire, not the cap.
    this.dialog.open(ExportEditorDialogComponent, {
      width: '420px',
      data: this.viewScoped()
        ? { filters: this.store.filterPayload(), exclude: [...this.excludedPaths()], count: this.selectionCount() }
        : { paths: [...this.selectedPaths()] },
    });
  }

  async openCaptureDateDialog(): Promise<void> {
    if (!this.auth.isEdition()) return;
    const viewScoped = this.viewScoped();
    const selected = this.selectedPaths();
    const first = viewScoped ? undefined : this.store.photos().find(photo => selected.has(photo.path) && photo.date_taken);
    const data = {
      paths: [...selected],
      filters: viewScoped ? structuredClone(this.store.filterPayload()) : null,
      exclude: viewScoped ? [...this.excludedPaths()] : [],
      count: this.selectionCount(),
      reference: first?.date_taken ? { path: first.path, date: first.date_taken } : null,
    };
    if (!viewScoped && !data.paths.length) return;
    const liveness = this.staleness.create(this.destroyRef, { track: 'status' });
    try {
      const { CaptureDateDialogComponent } = await import('../photo-detail/capture-date-dialog.component');
      if (!liveness.current()) return;
      this.dialog.open(CaptureDateDialogComponent, { width: '95vw', maxWidth: '760px', data });
    } finally { liveness.dispose(); }
  }

  async openBatchGpsDialog(): Promise<void> {
    if (!this.auth.isEdition() || !this.selectionCount()) return;
    const selectionIdentity = () => JSON.stringify({
      view: this.viewScoped(), paths: [...this.selectedPaths()].sort(),
      exclude: [...this.excludedPaths()].sort(), filters: this.store.filterPayload(),
    });
    const originalSelection = selectionIdentity();
    const batch = this.viewScoped()
      ? { filters: structuredClone(this.store.filterPayload()), exclude: [...this.excludedPaths()] }
      : { photo_paths: [...this.selectedPaths()] };
    const { current, dispose } = this.staleness.create(this.destroyRef);
    const onBatchApplied = () => {
      if (current() && selectionIdentity() === originalSelection) this.store.clearSelection();
    };
    try {
      const { GpsEditDialogComponent } = await import('../photo-detail/gps-edit-dialog.component');
      if (!current()) return;
      this.dialog.open(GpsEditDialogComponent, {
        width: '95vw', maxWidth: '640px',
        data: { path: '', filename: this.i18n.t(I18N.photo_detail.gps.batch_title), lat: null, lng: null, batch, onBatchApplied },
      });
    } finally { dispose(); }
  }

  /** Bulk add/remove of one manual tag. The dialog owns the request; the list is
   *  refetched afterwards because a photo opened in the detail view carries the
   *  grid row's `manual_tags`, which a bulk write has just made stale. */
  async openManualTagsDialog(): Promise<void> {
    const viewScoped = this.viewScoped();
    const paths = [...this.selectedPaths()];
    if (!viewScoped && !paths.length) return;
    const { ManualTagsDialogComponent } = await import('./manual-tags-dialog.component');
    const ref = this.dialog.open(ManualTagsDialogComponent, {
      width: '95vw',
      maxWidth: '500px',
      data: {
        paths,
        filters: viewScoped ? this.store.filterPayload() : null,
        exclude: viewScoped ? [...this.excludedPaths()] : [],
        count: this.selectionCount(),
      },
    });
    const written = await firstValueFrom(ref.afterClosed());
    if (!written) return;
    this.journal.record('tags', paths, { count: written });
    const kept = viewScoped ? new Set(this.excludedPaths()) : new Set(this.selectedPaths());
    await this.store.reloadPhotos();
    this.restoreSelectionWithout(viewScoped, kept, []);
  }

  async openCullDialog(explicitPaths?: string[]): Promise<void> {
    const explicit = explicitPaths !== undefined;
    const viewScoped = !explicit && this.viewScoped();
    const paths = explicit ? [...explicitPaths] : [...this.selectedPaths()];
    if (!viewScoped && !paths.length) return;
    const filterScope = JSON.stringify(this.store.filterPayload());
    const { current, dispose } = this.staleness.create(this.destroyRef, {
      track: 'status', valid: () => JSON.stringify(this.store.filterPayload()) === filterScope,
    });
    try {
      // Taken before the dialog: the reload after a cull may drop these rows.
      const culled = explicit ? this.store.photos().filter(p => paths.includes(p.path)) : [];
      const { CullDialogComponent } = await import('./cull-dialog.component');
      if (!current()) return;
      const ref = this.dialog.open(CullDialogComponent, {
        closeOnNavigation: false,
        width: '32rem',
        data: {
          paths,
          // Same trade as the export: the filter travels instead of the paths,
          // and the server's 10,000 ceiling (412) applies to it just the same.
          filters: viewScoped ? this.store.filterPayload() : null,
          exclude: viewScoped ? [...this.excludedPaths()] : [],
          count: explicit ? paths.length : this.selectionCount(),
          trashAvailable: this.store.config()?.cull?.trash_available ?? false,
          allowTrash: this.store.config()?.cull?.allow_trash ?? false,
        },
      });
      const applied = await firstValueFrom(ref.afterClosed());
      if (applied && current()) {
        // Reload first: clearing the selection hands focus back to the marked
        // card, and the rows the cull has just moved away are still standing in
        // the list until this returns.
        if (!explicit) {
          await this.store.reloadPhotos();
          if (current()) this.clearSelection();
          return;
        }
        // loadPhotos() drops a whole-view selection (a view selection names the
        // view, and the reload is what the store reads as "the view changed"),
        // so what the user built is captured first and put back after it.
        const wasViewScoped = this.viewScoped();
        const kept = wasViewScoped ? new Set(this.excludedPaths()) : new Set(this.selectedPaths());
        await this.store.reloadPhotos();
        if (current()) this.restoreSelectionWithout(wasViewScoped, kept, culled);
      }
    } finally { dispose(); }
  }

  /** After a cull of explicit paths only those photos leave the selection; the
   *  rest of what the user built stays, in the scope it was built in. Under
   *  view scope "leaves" means joining the exclusion list. */
  private restoreSelectionWithout(wasViewScoped: boolean, kept: Set<string>, culled: Photo[]): void {
    const gone = new Set(culled.map(p => p.path));
    if (!wasViewScoped) {
      this.store.restoreSelection([...kept].filter(path => !gone.has(path)));
      return;
    }
    this.store.selectWholeView();
    for (const path of new Set([...kept, ...gone])) this.store.toggleSelection({ path } as Photo);
  }

  /**
   * Bulk "Delete…": paths only, never `filters`/`exclude` (decision 8 / B5) --
   * a filter-driven request is the one shape that can trash an unbounded set,
   * so under view scope this is disabled rather than switched to a
   * filter-based request; the guard below is a belt-and-braces check against
   * the button state, not the primary gate.
   *
   * Drops rows via `GalleryStore.removePhotos` (decision 6 bullet 4), never
   * `loadPhotos()` -- the existing cull reload is correct for cull, whose
   * rows survive a move/trash, but delete's rows are already gone from
   * `photos` server-side by the time this response returns.
   */
  async deleteSelected(explicitPaths?: string[]): Promise<void> {
    const explicit = explicitPaths !== undefined;
    // Explicit paths name their own targets, so view scope -- which `paths`
    // cannot express -- is not in play.
    if (!explicit && this.viewScoped()) return;
    const paths = explicit ? [...explicitPaths] : [...this.selectedPaths()];
    if (!paths.length) return;
    const selectedSet = new Set(paths);
    const loaded = this.store.photos().filter(p => selectedSet.has(p.path));
    // One explicit path is the context menu's single-photo delete: it gets the
    // single-photo wording, and the lead check photo-detail makes.
    const lone = explicit && paths.length === 1;
    if (lone && !loaded.length) return;
    const hasSiblings = loaded.some(p =>
      !!p.sequence_kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(p.sequence_kind));
    const { PhotoDeleteDialogComponent } = await import('../../shared/components/photo-delete-dialog/photo-delete-dialog.component');
    const ref = this.dialog.open(PhotoDeleteDialogComponent, {
      ...(lone ? { width: '95vw', maxWidth: '28rem' } : { width: '32rem' }),
      data: {
        surface: lone ? 'photo_detail' : 'bulk',
        paths,
        count: paths.length,
        hasCompanion: true,
        hasSiblings,
        // No per-path lead signal client-side for a bulk selection -- the
        // response's own `refused_bracket_lead` is what the partial-result
        // toast below reports instead.
        hasBracketLead: lone && loaded[0].sequence_kind === 'bracket' && loaded[0].sequence_ev_offset === 0,
      },
    });
    const result = await firstValueFrom(ref.afterClosed());
    if (!result) return;
    const res = await this.photoActions.deletePhotos(paths, result);
    if (!res) return;
    // `removed_missing` rows are as gone as trashed ones -- the grid must not
    // keep a tile for a row the server just reconciled away.
    const removed = [...res.deleted, ...res.removed_missing];
    this.store.removePhotos(removed);
    // `removePhotos` already prunes the deleted paths out of the selection.
    if (!explicit) this.clearSelection();
    // Every failure bucket counts as "failed" here, not just
    // `refused_bracket_lead` -- an unwritable trash dir (errors), a path the
    // rescan already dropped (not_found/not_visible) or whose file was
    // already gone (skipped) are just as much a reason the user's count came
    // up short, and a response where every path landed in one of those must
    // read as a failure rather than the "0 deleted, 0 refused" neutral result
    // the old two-field toast rendered.
    const failed = res.refused_bracket_lead.length + res.not_found.length + res.not_visible.length
      + res.skipped.length + Object.keys(res.errors).length;
    if (removed.length === 0 && failed > 0) {
      this.snackBar.open(this.i18n.t(I18N.cull.delete_failed), '', { duration: 4000 });
    } else {
      this.snackBar.open(
        this.i18n.t(I18N.cull.delete_partial_result, { deleted: removed.length, failed }),
        '', { duration: 4000 },
      );
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

  private searchTimeout: ReturnType<typeof setTimeout> | null = null;

  /** Debounced live filtering for the toolbar search box: waiting for
   *  Enter/blur made typing feel dead (the grid froze with no hint that a
   *  commit was pending). Enter and blur still commit immediately via the
   *  same updateFilter path. */
  protected onSearchInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.searchTimeout = setTimeout(() => {
      this.searchTimeout = null;
      if (value !== this.store.filters().search) this.store.updateFilter('search', value);
    }, 400);
  }

  protected onSearchChange(event: Event): void {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.searchTimeout = null;
    const value = (event.target as HTMLInputElement).value;
    if (value !== this.store.filters().search) this.store.updateFilter('search', value);
  }

  /** Focuses the search (the toolbar's, else the sidebar's), toggles the
   *  filter sidebar, switches grid/mosaic, or opens the selected-photo stack
   *  editor. The keys come from the user's key mapping
   *  (the keyboard settings dialog); typing contexts and open dialogs bow
   *  out, matching the select-all shortcut's guards, and so does the
   *  slideshow: it is an inline overlay, not a MatDialog, so the dialog
   *  query below cannot see it. */
  protected onGalleryShortcut(event: KeyboardEvent): void {
    if (this.parked || this.store.slideshowActive() || event.defaultPrevented) return;
    // Either Cmd or Ctrl, like select-all; never both.
    const quickChord = event.key.toLowerCase() === 's' && event.shiftKey && !event.altKey && event.ctrlKey !== event.metaKey;
    if (quickChord && !isImeOrRepeat(event) && !isShortcutContextBlocked(event) && this.canOpenStackFlow()) {
      event.preventDefault(); void this.quickStack(); return;
    }
    if (isPageShortcutBlocked(event)) return;

    if (this.keymap.matches(event, 'stack')) {
      if (event.repeat || event.isComposing || event.keyCode === 229 || !this.canCreateStack()) return;
      event.preventDefault();
      void this.createStack();
      return;
    }
    if (this.keymap.matches(event, 'focusSearch')) {
      const search = this.toolbarSearch()?.nativeElement;
      if (!search) return;
      event.preventDefault();
      if (window.matchMedia(TOOLBAR_SEARCH_QUERY).matches) {
        search.focus();
        search.select();
        return;
      }
      // Below 1360 px the toolbar search is hidden; the sidebar carries its own.
      this.store.setFilterDrawerOpen(true);
      afterNextRender(() => this.filterSidebar()?.focusSearch(), { injector: this.injector });
      return;
    }
    if (this.keymap.matches(event, 'toggleSidebar')) {
      event.preventDefault();
      this.store.setFilterDrawerOpen(!this.store.filterDrawerOpen());
      return;
    }
    if (this.keymap.matches(event, 'swapLayout')) {
      event.preventDefault();
      this.store.setGalleryMode(this.effectiveGalleryMode() === 'grid' ? 'mosaic' : 'grid');
    }
  }

  protected clearSearch(): void {
    this.cancelToolbarSearch();
    this.store.updateFilter('search', '');
  }

  /** Drop a pending toolbar search and show the committed one again. A timer
   *  that fired on a parked or destroyed gallery would rewrite whatever URL is
   *  showing by then (the photo page's) with gallery query params. */
  private cancelToolbarSearch(): void {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.searchTimeout = null;
    const input = this.toolbarSearch()?.nativeElement;
    if (input) input.value = this.store.filters().search;
  }

  private setupResizeObserver(): void {
    this.resizeObserver = new ResizeObserver(entries => {
      // A parked gallery measures 0; keep its layout for the return.
      if (this.parked) return;
      for (const entry of entries) {
        this.containerWidth.set(Math.floor(entry.contentRect.width));
      }
      this.updateWindowPosition();
    });

    // Observe the sidenav-content area for width changes
    const content = document.querySelector('mat-sidenav-content');
    if (content) {
      // Measure now so the first frame is laid out for the real width, not after the observer's first tick.
      const style = getComputedStyle(content);
      const measured = Math.floor(content.clientWidth - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0));
      if (measured > 0) this.containerWidth.set(measured);
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
    const path = this.store.photos()[index]?.path ?? null;
    this.activeIndex.set(index);
    this.activePath.set(path);
    // The mirror outlives a blur: a drop with the window unfocused (the user went to the agent) keeps it.
    if (path !== null) this.store.focusedPath.set(path);
    else if (document.hasFocus()) this.store.focusedPath.set(null);
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
      const focused = this.store.focusedPath();
      if (focused !== null && !photos.some(p => p.path === focused)) this.store.focusedPath.set(null);
      const path = this.activePath();
      if (path === null) return;
      const at = photos.findIndex(p => p.path === path);
      if (at === this.activeIndex()) return;
      this.activeIndex.set(at);
      if (at < 0) this.activePath.set(null);
    });
  });

  /** A new pin (or the pin ending) is a different list: the photo the docked rail holds and the
   *  keyboard cursor belong to the previous view, so both are dropped. The first run is skipped --
   *  mounting over an existing pin has nothing to reset -- and a filter reload that leaves the
   *  pin null does not notify. setCursor only writes signals; it never moves DOM focus. */
  private readonly resetOnPinChange = (() => {
    let previous: string[] | null | undefined;
    return effect(() => {
      const pin = this.store.pinnedPaths();
      untracked(() => {
        const first = previous === undefined;
        const changed = pin !== previous;
        previous = pin;
        if (first || !changed) return;
        this.tooltipPhoto.set(null);
        this.setCursor(-1);
      });
    });
  })();

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
   *  card afterwards, so the bar is excluded by name. The overlay container is
   *  the photo context menu taking focus, which is not leaving either. A null relatedTarget --
   *  focus dropped to the body, or out to the browser chrome -- does count. */
  protected onGridFocusOut(event: FocusEvent): void {
    const next = event.relatedTarget as HTMLElement | null;
    if (next?.closest('[role="grid"], [data-selection-bar], [data-details-rail], .cdk-overlay-container')) return;
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

  /** What the docked rail shows: the current photo while there is one, so
   *  crossing other cards on the way to the rail cannot retarget it, and the
   *  last hovered/clicked photo otherwise. */
  protected readonly panelPhoto = computed(() =>
    this.hasActivePhoto() ? this.store.photos()[this.activeIndex()] : this.tooltipPhoto());

  /** The rail's Deselect: drop the current photo, and with it the lock and the
   *  dimming, and take it out of the batch selection its click put it in.
   *  The rail keeps showing it until the next hover rather than jumping to
   *  whichever card the pointer crossed last. */
  protected releasePanel(): void {
    const photo = this.panelPhoto();
    if (!this.hasActivePhoto() || !photo) return;
    this.tooltipPhoto.set(photo);
    // Same rule as IsSelectedPipe: a view-scoped selection is "all but excluded".
    const selected = this.viewScoped()
      ? !this.excludedPaths().has(photo.path)
      : this.selectedPaths().has(photo.path);
    if (selected) this.store.toggleSelection(photo);
    this.setCursor(-1);
  }

  /** Escape: with the docked rail, first what Deselect does -- the held photo,
   *  its frame and the dimming go -- then, as everywhere, the rest of the selection.
   *  A view-scoped selection is cleared even when the release emptied it (one photo in
   *  view), so the store does not keep a view scope with a leftover exclusion set. */
  private escapeSelection(): void {
    if (this.panelMode()) this.releasePanel();
    if (this.selectionCount() || this.viewScoped()) this.clearSelection();
  }

  /** Escape from inside the rail. The drawer is kept open by `disableClose` while the
   *  rail occupies it (it would otherwise close and be reopened by the open/close
   *  effect, a flicker and a focus jump); propagation is left alone so an open
   *  tooltip's overlay handler still closes. The Deselect button is removed by the
   *  release, so focus is parked on the rail rather than dropping to the body. */
  protected onRailEscape(event: Event): void {
    event.preventDefault();
    this.escapeSelection();
    (event.currentTarget as HTMLElement | null)?.focus();
  }

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
    if (rowIdx < 0) return index;
    const targetRow = rows[rowIdx + dir];
    if (!targetRow) return index;
    const offset = index - rows[rowIdx].startIndex;
    return targetRow.startIndex + Math.min(offset, targetRow.photos.length - 1);
  }

  /** The photo index of the card an event came from (`data-pidx`), 0 when it came from none. */
  private indexOfCard(target: EventTarget | null): number {
    const raw = (target as HTMLElement | null)?.closest?.('[data-pidx]')?.getAttribute('data-pidx');
    const parsed = raw == null ? NaN : Number(raw);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
  }

  protected onGridKeydown(event: KeyboardEvent): void {
    if (isTypingContext(event)) return;
    const photos = this.store.photos();
    if (!photos.length) return;
    const index = this.activeIndex() >= 0 ? this.activeIndex() : this.indexOfCard(event.target);
    let next: number | null = null;

    switch (event.key) {
      case 'ArrowRight': next = Math.min(photos.length - 1, index + 1); break;
      case 'ArrowLeft': next = Math.max(0, index - 1); break;
      case 'ArrowDown': next = this.verticalTarget(index, 1); break;
      case 'ArrowUp': next = this.verticalTarget(index, -1); break;
      case 'Home': next = 0; break;
      case 'End': next = photos.length - 1; break;
      case 'Escape':
        // A click-opened tooltip is the innermost layer: close it before touching the selection.
        if (this.tooltipMode() === 'click' && this.tooltipPhoto()) {
          event.preventDefault();
          this.hideTooltip();
          return;
        }
        if (this.selectionCount() || (this.panelMode() && this.hasActivePhoto())) {
          event.preventDefault();
          this.escapeSelection();
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

  /** Rate-and-advance shortcuts on the focused card: 1-5 set stars, the mapped
   *  reject key (or 0) rejects (both auto-advance), the mapped favourite key
   *  toggles favorite (stays put — a tag-like toggle), the mapped keep key
   *  keeps (review queue). Edition-only and gated on the rating-controls
   *  feature flag, mirroring the card's own template guards. */
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
    } else if (this.keymap.matches(event, 'keep')) {
      event.preventDefault();
      void this.reviewSingle(photo.path, 'kept').then(result => {
        if (result) this.focusAfterDecision(photos, index);
      });
      return;
    } else if (event.key === '0' || this.keymap.matches(event, 'reject')) {
      if (this.store.filters().review_status) {
        void this.store.toggleRejected(photo.path).then(() => this.focusAfterDecision(photos, index));
      } else {
        this.store.toggleRejected(photo.path);
        advance = true;
      }
    } else if (this.keymap.matches(event, 'favourite')) {
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

  private focusAfterDecision(photos: Photo[], index: number): void {
    const nextIndex = this.store.photos().findIndex(p => p.path === photos[index + 1]?.path);
    const target = nextIndex >= 0 ? nextIndex : Math.min(index, this.store.photos().length - 1);
    if (target >= 0) { this.setCursor(target); this.focusCard(target); }
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
