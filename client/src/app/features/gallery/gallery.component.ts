import { ControlPopoverComponent } from '../../shared/components/control-popover/control-popover.component';
import { closeDetailsOnEscape, closeOverlayDirectives } from '../../shared/utils/overlays';
import { GallerySelectionActions } from './gallery-selection-actions';
import { GalleryVisitPositions, GalleryHistoryPosition } from './gallery-visit-positions.service';
import { TagNavigation } from '../../shared/models/tag-navigation';
import { refineTagQuery } from './tag-query.util';
import { buildSyncParams } from './gallery-filters.util';
import { MovableToolbarDirective, TOOLBAR_POSITION_EVENT } from '../../shared/directives/movable-toolbar.directive';
import { GalleryReviewNavigationService } from './gallery-review-navigation.service';
import { GalleryViewControlsComponent } from './gallery-view-controls.component';
import { GalleryCriteriaComponent } from './gallery-criteria.component';
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
import { MatInputModule } from '@angular/material/input';
import { MatSliderModule } from '@angular/material/slider';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatBottomSheet, MatBottomSheetModule } from '@angular/material/bottom-sheet';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatMenuModule, MatMenuTrigger, MenuCloseReason } from '@angular/material/menu';
import { MatTooltip, MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, NavigationStart, Router, RouterOutlet } from '@angular/router';
import { filter, firstValueFrom, takeUntil } from 'rxjs';
import { ComparisonSessionService } from './comparison-session.service';
import { GalleryStore, HiddenFilterFlags, REVIEW_RESUME_NAVIGATION } from './gallery.store';
import { NoticeDismissals, NoticeKind, readNoticeDismissals, saveNoticeDismissals, withDismissal } from './notice-dismiss.util';
import { Photo } from '../../shared/models/photo.model';
import { isImeOrRepeat, isPageShortcutBlocked, isShortcutContextBlocked, isTypingContext } from '../../shared/utils/keyboard';
import { KeyboardMappingService } from '../../core/services/keyboard-mapping.service';
import { GALLERY_REVISIT, PHOTO_PATH } from '../../core/gallery-reuse.strategy';
import { SequenceKindIconPipe } from '../../shared/pipes/sequence-kind.pipe';
import { IsSelectedPipe } from '../../shared/pipes/selection.pipe';
import { PhotoSetKindIconPipe, PhotoSetKindLabelPipe } from '../../shared/pipes/photo-set-kind.pipe';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { ScanService } from '../../core/services/scan.service';
import { useDesktopSignal, DETAILS_RAIL_MIN_WIDTH_PX } from '../../shared/utils/media-query';
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
  GalleryRow, aspectOf, buildGridRows, buildMosaicRows, buildListRows, metadataRowHeight,
  gridColumnCount, totalRowsHeight, windowRange, MOBILE_MIN_COLUMNS, MOBILE_DETAILS_MIN_COLUMNS,
} from './gallery-rows.util';
import { noticeLiftPx } from './selection-bar-layout.util';
import { GalleryFilters, applyQueryParams, applySavedAlbumFilters, loadDisplayOptionsFromStorage, nextGalleryMode } from './gallery-filters.util';
import { AlbumService, Album } from '../../core/services/album.service';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { PageHelpService } from '../../core/services/page-help.service';
import { MAX_COMPARE_QUEUE } from './comparison-slots.util';
import { HistogramMode, isHistogramMode } from '../../shared/utils/histogram';

function assertNever(action: never): never {
  throw new Error(`Unhandled photo menu action: ${JSON.stringify(action)}`);
}

/** Where the focused card sat in the viewport when the gallery parked. */
interface ReturnAnchor { offset: number; width: number; height: number }



/** What the gallery restores on return; an anchor implies a photo path to re-anchor to. */
type ReturnTarget = { scroll: number; focus: Element | null } & (
  | { path: string | null; anchor: null }
  | { path: string; anchor: ReturnAnchor });

/** The hide toggle that collapses each kind of set; any other sequence kind is a panorama variant. */
const SET_KIND_TOGGLE: Record<string, keyof HiddenFilterFlags> = {
  burst: 'hide_bursts', duplicate: 'hide_duplicates', bracket: 'hide_brackets', panorama: 'hide_panoramas',
};

@Component({
  selector: 'app-gallery',
  imports: [ControlPopoverComponent,
    MovableToolbarDirective,
    NgTemplateOutlet,
    MatSidenavModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatButtonModule,
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
    GalleryViewControlsComponent, GalleryCriteriaComponent,
    PhotoCardComponent,
    GalleryPhotoMenuComponent,
    PhotoSkeletonComponent,
    InfiniteScrollDirective,
  ],
  template: `
    <!-- Collection controls stay with the photo workspace at every width.
         Existing handlers retain debounce, pin and parked-route protections. -->
    <ng-template #galleryToolbar>
      @if (!pinned()) {
        <!-- Exact text search commits through the existing debounced handler. -->
        <label class="relative block min-w-40 flex-1 @min-[480px]:@max-[639px]:min-w-0">
          <span class="sr-only">{{ I18N.gallery.search_placeholder | translate }}</span>
          <input
            #toolbarSearch
            matInput
            type="search"
            autocomplete="off"
            class="h-10 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-lowest)] py-2 pl-3 pr-11 text-base text-[var(--mat-sys-on-surface)] placeholder:text-[var(--mat-sys-on-surface-variant)] [&::-webkit-search-cancel-button]:hidden"
            [placeholder]="I18N.ui.filters.search | translate"
            [title]="I18N.gallery.search_placeholder | translate"
            [value]="store.filters().search"
            (input)="onSearchInput($event)"
            (keyup.enter)="onSearchChange($event)"
            (keydown.escape)="closeMobileSearch($event)"
            (blur)="onSearchChange($event)"
          />
          @if (store.filters().search) {
            <button type="button" class="!absolute right-0 top-0" mat-icon-button (click)="clearSearch()" [attr.aria-label]="I18N.gallery.clear_search | translate">
              <mat-icon>close</mat-icon>
            </button>
          } @else {
            <mat-icon class="pointer-events-none !absolute right-3 top-2 text-[var(--mat-sys-on-surface-variant)]" aria-hidden="true">search</mat-icon>
          }
        </label>
      }

    </ng-template>
    <ng-template #collectionStackControls>
      @if (!pinned()) {
        <button mat-button class="!min-h-11 !w-full !justify-start" data-stack-collapse (click)="store.toggleStackCollapse()"
          [matTooltip]="(store.collapseStacks() ? I18N.stacks.expand_all : I18N.stacks.collapse) | translate"
          [attr.aria-label]="(store.collapseStacks() ? I18N.stacks.expand_all : I18N.stacks.collapse) | translate"><mat-icon>{{ store.collapseStacks() ? 'unfold_more' : 'unfold_less' }}</mat-icon>{{ (store.collapseStacks() ? I18N.stacks.expand_all : I18N.stacks.collapse) | translate }}</button>
      }
    </ng-template>
    <ng-template #collectionReviewCommands>
      @if (auth.isEdition() && store.canScopeSelectionToView()) {
        <button mat-button class="!min-h-11 !w-full !justify-start" data-stack-suggestions (click)="openStackSuggestions()"
          [matTooltip]="I18N.stacks.suggestions | translate" [attr.aria-label]="I18N.stacks.suggestions | translate">
          <mat-icon>auto_awesome_motion</mat-icon>{{ I18N.stacks.suggestions | translate }}
        </button>
      }
      <!-- Keep top N%: server-rank the current view by the current sort and
           select the bottom (100-N)% for review/rejection via the selection bar. -->
      @if (auth.isEdition() && store.total() > 0 && store.canScopeSelectionToView()) {
        <details #keepTopDetails data-keep-top-controls tabindex="-1" class="group/keep-top rounded border border-[var(--mat-sys-outline-variant)]" (keydown.escape)="closeDisclosure($event, keepTopDetails, keepTopSummary)">
          <summary #keepTopSummary class="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
            <mat-icon aria-hidden="true">content_cut</mat-icon>{{ I18N.gallery.keep_top.label | translate }}
            <mat-icon aria-hidden="true" class="ml-auto group-open/keep-top:rotate-180">expand_more</mat-icon>
          </summary>
          <div class="p-3" >
            <div class="text-xs text-[var(--mat-sys-on-surface-variant)] mb-2">{{ I18N.gallery.keep_top.help | translate }}</div>
            <div class="flex items-center gap-2">
              <mat-slider class="flex-1 !min-w-0" [min]="5" [max]="95" [step]="5" [discrete]="true">
                <input matSliderThumb [value]="keepPercent()" (valueChange)="keepPercent.set($event)"
                       [attr.aria-label]="I18N.gallery.keep_top.label | translate" />
              </mat-slider>
              <span class="text-sm font-medium w-9 text-right">{{ keepPercent() }}%</span>
            </div>
            <div class="text-xs text-[var(--mat-sys-on-surface-variant)] my-2">
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
        </details>
      }
    </ng-template>


    <div #noticeHost class="relative h-full">
    <mat-sidenav-container class="h-full !overflow-clip">
      <!-- One end drawer, two occupants. Material allows a single drawer per
           side, which is also the behaviour we want: the details rail and the
           filters compete for the same strip, so opening the filters hides the
           rail and closing them brings it back, without either changing how much
           room the grid gets. -->
      <app-gallery-view-controls #collectionViewControls (slideshowRequested)="closeCollectionPopovers(true)" [portPrimary]="true" [portFilters]="true" [portDisplay]="true" class="contents" />
      <app-gallery-filter-sidebar #collectionSettings [portSettings]="true"
         [layoutControls]="collectionViewControls.sidebarLayoutControls() ?? null"
         [displayExtras]="collectionViewControls.displayControls() ?? null" />
      <mat-sidenav #filterDrawer [disableClose]="detailsRailVisible()" [mode]="isDesktop() ? 'side' : 'over'" position="end" class="w-[min(320px,100vw)] p-0"
        (openedChange)="onFilterDrawerChange($event)">
        @if (detailsRailVisible()) {
          <!-- Deselect stays put above the scrolling details; the tooltip
               background covers the whole rail instead of a rounded card. -->
          <div class="flex flex-col h-full bg-[var(--facet-tooltip-bg)]" data-details-rail tabindex="-1" (keydown.escape)="onRailEscape($event)"
               (focusout)="onGridFocusOut($event)">
            <header class="flex items-center gap-2 px-4 py-2 border-b border-[var(--mat-sys-outline-variant)] shrink-0">
              <div class="min-w-0 flex-1">
                <h2 class="m-0 text-sm font-medium text-[var(--mat-sys-on-surface)]">{{ I18N.gallery.tooltip_mode.details | translate }}</h2>
                @if (panelPhoto(); as owner) {
                  <p data-inspector-owner class="m-0 truncate text-xs text-[var(--mat-sys-on-surface-variant)]" [title]="owner.filename">{{ owner.filename }}</p>
                }
              </div>
            </header>
            @if (hasActivePhoto()) {
              <button mat-button class="!min-w-0 !px-0 shrink-0 self-start mx-4 mt-2" (click)="deselectFromRail()">
                <mat-icon class="!ml-0">arrow_back</mat-icon> {{ I18N.gallery.tooltip_mode.panel_deselect | translate }}
              </button>
            }
            <div class="min-h-0 flex-1 overflow-y-auto">
            @if (panelPhoto(); as p) {
              <app-photo-tooltip [photo]="p" [docked]="true" [pinned]="true"
                                 [histogramDefaultMode]="tooltipHistogramDefaultMode()"
                                 [indicatorPercent]="clippingIndicatorPercent()"
                                 [explainable]="railCritiqueVisible()" (explain)="openRailCritique()"
                                 [personLinks]="!pinned()" [tagCollectionAvailable]="!store.filters().similar_to" (tagSelected)="navigateTag($event)"
        (personSelected)="store.updateFilter('person_id', $event)" />
            } @else {
              <div class="p-4 text-sm text-[var(--mat-sys-on-surface-variant)] text-center">
                {{ I18N.gallery.tooltip_mode.panel_empty | translate }}
              </div>
            }
            </div>
          </div>
        } @else {
          <!-- Usually closed, and heavy enough that building it eagerly holds up the grid's first paint. -->
          @defer (on idle; when store.filterDrawerOpen()) {
            <ng-container [ngTemplateOutlet]="collectionSettings.bodyContent()" />
          }
        }
      </mat-sidenav>

      <!-- Main content. The drawer reserves its own strip, so the grid gets
           exactly the width it has whenever the filters are open. -->
      <mat-sidenav-content [style.scroll-padding-top.px]="collectionHeaderHeight()">
        <header #collectionHeader data-collection-header class="sticky top-0 z-40 @container border-b border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container-lowest)] px-2 md:px-4">
          <div data-collection-bar class="-mx-2 flex flex-wrap items-center gap-x-2 gap-y-1 bg-[var(--mat-sys-surface-container)] px-2 py-2 md:-mx-4 md:px-4 @min-[480px]:@max-[639px]:grid @min-[480px]:@max-[639px]:grid-cols-[minmax(0,1fr)_auto]">
          <div class="min-w-40 flex-1 @min-[960px]:max-w-52 @min-[960px]:min-w-32 @min-[960px]:basis-0 @min-[1280px]:max-w-64 @min-[480px]:@max-[639px]:col-start-1 @min-[480px]:@max-[639px]:col-span-2 @min-[480px]:@max-[639px]:row-start-1 @min-[480px]:@max-[639px]:pr-48">
          <h1 class="m-0 min-w-0 text-lg font-medium leading-6 text-[var(--mat-sys-on-surface)] truncate" [title]="store.currentAlbum()?.name || (I18N.gallery.all_photos | translate)">
            {{ store.currentAlbum()?.name || (I18N.gallery.all_photos | translate) }}
          </h1>
          <p role="status" class="m-0 text-xs leading-5 tabular-nums text-[var(--mat-sys-on-surface-variant)]">
            @if (!pinned() && store.photoTotal() !== store.total()) {
              {{ I18N.gallery.collection_totals_compact | translate:{ photos: store.photoTotal(), items: store.total() } }}
            } @else {
              {{ (pinned() ? store.total() : store.photoTotal()) | pluralKey:I18N.gallery.photo_count_one:I18N.gallery.photo_count | translate:{ count: pinned() ? store.total() : store.photoTotal() } }}
            }
          </p>
          </div>
          <div data-collection-query role="search" [attr.aria-label]="I18N.gallery.search_placeholder | translate" class="order-last flex w-full min-w-0 flex-wrap items-center gap-1 @min-[960px]:order-none @min-[960px]:w-auto @min-[960px]:min-w-44 @min-[1120px]:min-w-56 @min-[960px]:flex-1 @min-[1280px]:max-w-[32rem] @min-[1600px]:max-w-[40rem] @min-[480px]:@max-[639px]:col-start-1 @min-[480px]:@max-[639px]:row-start-2" [class.!hidden]="compactCollectionControls() && !mediumCollectionControls() && !mobileSearchOpen() && !store.filters().search">
            <ng-container [ngTemplateOutlet]="galleryToolbar" />
          </div>
          <div data-collection-actions class="ml-auto flex shrink-0 items-center gap-0.5 @min-[960px]:gap-1 @max-[639px]:contents">
            @if (!pinned() && compactCollectionControls() && !mediumCollectionControls()) {
              <button #mobileSearchToggle mat-icon-button class="!min-h-11 !min-w-11 @max-[639px]:order-1" [attr.aria-label]="I18N.ui.filters.search | translate" [attr.aria-expanded]="mobileSearchOpen() || !!store.filters().search" (click)="focusCollectionSearch()"><mat-icon>search</mat-icon></button>
            }
            <button #collectionSelect mat-button data-mobile-select class="!min-h-11 !min-w-0 !px-2 @max-[639px]:order-1 @min-[480px]:@max-[639px]:col-start-2 @min-[480px]:@max-[639px]:row-start-1 @min-[480px]:@max-[639px]:justify-self-end" [class.!bg-[var(--mat-sys-secondary-container)]]="selectingPhotos()"
                    [attr.aria-label]="selectingPhotos() ? ((I18N.ui.buttons.cancel | translate) + ': ' + (I18N.gallery.selection.count | translate:{ count: selectionCount() })) : (I18N.gallery.selection.select | translate)"
                    [matTooltip]="I18N.ui.buttons.cancel | translate" [matTooltipDisabled]="!selectingPhotos()"
                    [attr.aria-pressed]="selectingPhotos()" (click)="toggleMobileSelection()">
              <mat-icon aria-hidden="true">{{ selectingPhotos() ? 'close' : 'check_box_outline_blank' }}</mat-icon>
              {{ selectingPhotos() ? (I18N.gallery.selection.count | translate:{ count: selectionCount() }) : (I18N.gallery.selection.select | translate) }}
            </button>
            <div data-collection-settings class="flex items-center gap-0.5 @min-[960px]:gap-1 @max-[639px]:order-3 @max-[479px]:basis-full @max-[639px]:justify-end @min-[480px]:@max-[639px]:col-start-2 @min-[480px]:@max-[639px]:row-start-2">
            @if (!compactCollectionControls()) {
              <div data-collection-primary-controls class="flex items-center gap-1">
                <ng-container [ngTemplateOutlet]="collectionViewControls.primaryControls()" />
              </div>
            }
            <ng-container [ngTemplateOutlet]="collectionViewControls.filterControls()" />
            <span aria-hidden="true" class="mx-1 h-5 border-l border-[var(--mat-sys-outline-variant)]"></span>
            <app-control-popover data-collection-review #collectionReview [keepOnQueryChange]="true" icon="rule" [disclosure]="true" [hint]="auth.isEdition() ? (I18N.gallery.review_controls_hint | translate) : ''"
                [label]="I18N.gallery.sidebar.tabs.review | translate" [content]="reviewSettings" (opened)="onCollectionReviewOpened()" (closed)="onCollectionReviewClosed()" />
            <ng-template #reviewSettings>
              <ng-container [ngTemplateOutlet]="collectionReviewCommands" />
              <ng-container [ngTemplateOutlet]="collectionSettings.reviewSettings()" />
              <label class="flex min-h-11 cursor-pointer items-center gap-2 px-3 text-sm">
                <input type="checkbox" data-review-progress-toggle class="size-4 accent-[var(--mat-sys-primary)]"
                       [checked]="reviewProgressToggleOn()" (change)="onReviewProgressToggle($any($event.target).checked)" />
                {{ I18N.gallery.review_progress.show_toggle | translate }}
              </label>
            </ng-template>
            <app-control-popover data-collection-options [keepOnQueryChange]="true" icon="tune" [disclosure]="true" [hint]="pinned() ? '' : (I18N.gallery.display_controls_hint | translate)"
                [label]="I18N.gallery.sidebar.tabs.display | translate" [content]="displaySettings" />
            </div>
            <ng-template #displaySettings>
              @if (compactCollectionControls()) {
                <div data-compact-collection-controls class="flex items-center gap-1">
                  <ng-container [ngTemplateOutlet]="collectionViewControls.primaryControls()" [ngTemplateOutletContext]="{ inPopover: true }" />
                </div>
              }
              <ng-container [ngTemplateOutlet]="collectionSettings.displayLayoutSettings()" />
              <ng-container [ngTemplateOutlet]="collectionStackControls" />
              <ng-container [ngTemplateOutlet]="collectionSettings.displaySettings()" />
              <ng-container [ngTemplateOutlet]="collectionCriteria.shortcuts()" />
            </ng-template>
          </div>
          </div>
          <app-gallery-criteria #collectionCriteria [portShortcuts]="true" [consolidatedSettings]="true" [searchPresented]="true" class="-mx-2 block min-w-0 border-[var(--mat-sys-outline-variant)] px-2 md:-mx-4 md:px-4 has-[>:not(:empty)]:border-t has-[>:not(:empty)]:pb-1" />
        </header>

        <!-- Set-scope chip: the photo-detail "open this set in the gallery" action.
             Never reflected in the URL (sequence_group_id is renumbered on every
             detection pass), so this is the only affordance out of it. -->
        @if (setScopeKind(); as kind) {
          <div class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex items-center gap-3 text-sm">
            <mat-icon class="opacity-70 !text-base !w-5 !h-5">{{ kind | photoSetKindIcon }}</mat-icon>
            <span class="flex-1">
              {{ I18N.gallery.set_scope.message | translate:{ kind: (kind | photoSetKindLabel | translate) } }}
              <!-- The hide toggles still apply inside a set (blinks above all), so say
                   what is missing rather than list fewer frames than the photo page counted. -->
              @if (setBarCounts().hidden > 0) {
                · {{ I18N.gallery.set_scope.partial | translate:{ shown: setBarCounts().shown, total: setBarCounts().total, reasons: hiddenReasons() } }}
              }
            </span>
            @if (setBarCounts().hidden > 0) {
              <button mat-button class="!min-w-0" (click)="showWholeSet()">
                {{ I18N.gallery.hidden_banner.show_all | translate }}
              </button>
            }
            <button mat-button class="!min-w-0" (click)="clearSetScope()">
              {{ I18N.ui.buttons.clear | translate }}
            </button>
          </div>
        }

        <!-- Pinned-list chip: the assistant's ui_show_photos list replaces the filtered
             view; this is the way back to it (any filter change drops the list too). -->
        @if (store.pinnedPaths() !== null) {
          <div data-pinned-summary role="status" class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
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
              data-photo-collection
              [attr.role]="listMode() ? 'list' : 'grid'"
              tabindex="0"
              [attr.aria-label]="(listMode() ? I18N.gallery.layout_list : I18N.gallery.photo_grid) | translate"
              [attr.aria-rowcount]="listMode() ? null : rowsModel().length"
              class="flex flex-col p-2 md:p-4 outline-none"
              (keydown)="onGridKeydown($event)"
              (focusout)="onGridFocusOut($event)"
            >
              <div [style.height.px]="topSpacer()" aria-hidden="true"></div>
              @for (row of visibleRows(); track row.photos[0].path) {
              <div class="flex gap-[8px] mb-[8px]" [class.items-start]="naturalGridFit()" [style.height.px]="row.height">
                @for (photo of row.photos; track photo.path; let i = $index) {
                  <app-photo-card
                [collapsedSetKinds]="collapsedSetKinds()"
                [burstFramesVisible]="burstFramesVisible()"
                    [tabStop]="photo.path === tabStopPath()"
                    [photo]="photo"
                    [attr.data-pidx]="row.startIndex + i"
                    [style.width.px]="row.widths[i]"
                    [style.height.px]="row.heights?.[i] ?? row.height"
                    [style.content-visibility]="'auto'"
                    class="shrink-0"
                    [naturalFit]="naturalGridFit()"
                    [hideDetails]="rowCardHideDetails()"
                    [mosaicMode]="effectiveGalleryMode() === 'mosaic'"
                    [listMode]="listMode()"
                    [attr.aria-setsize]="listMode() ? store.photos().length : null"
                    [attr.aria-posinset]="listMode() ? row.startIndex + i + 1 : null"
                    [config]="store.config()"
                    [isSelected]="photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()"
                    [showSelectionIndicators]="showSelectionIndicators()"
                    [isActive]="row.startIndex + i === activeIndex()"
                    [gridHasActiveCard]="hasActivePhoto()"
                    [currentSort]="store.filters().sort"
                    [metricRanges]="store.metricRangesByColumn()"
                    [thumbSize]="thumbSize()"
                    [isEditionMode]="auth.isEdition()"
                    [personFilterId]="store.filters().person_id"
                    [tooltipMode]="cardTooltipMode()"
                    [panelActivation]="panelActivation()"
                    (selectionChange)="toggleSelection($event.photo, $event.event, row.startIndex + i)"
                    (tooltipShow)="showTooltip($event.event, $event.photo)"
                    (tooltipHide)="hideTooltip()"
                    [filterLinks]="!pinned()"
                [tagCollectionAvailable]="!store.filters().similar_to" (tagClicked)="navigateTag($event)"
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
          } @else if (effectiveGalleryMode() === 'grid' || listMode()) {
            <div
              data-photo-collection
              [attr.role]="listMode() ? 'list' : 'grid'"
              tabindex="0"
              [attr.aria-label]="(listMode() ? I18N.gallery.layout_list : I18N.gallery.photo_grid) | translate"
              class="grid grid-cols-1 gap-[8px] p-2 md:p-4 outline-none"
              [class.items-start]="naturalGridFit()"
              [style.grid-template-columns]="listMode() ? 'minmax(0,1fr)' : galleryColsStyle()"
              (keydown)="onGridKeydown($event)"
              (focusout)="onGridFocusOut($event)"
            >
              @for (photo of store.photos(); track photo.path; let i = $index) {
                <app-photo-card
                  [collapsedSetKinds]="collapsedSetKinds()"
                  [burstFramesVisible]="burstFramesVisible()"
                  [tabStop]="photo.path === tabStopPath()"
                    [photo]="photo"
                  [attr.data-pidx]="i"
                  [config]="store.config()"
                  [isSelected]="photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()"
                  [showSelectionIndicators]="showSelectionIndicators()"
                  [isActive]="i === activeIndex()"
                  [gridHasActiveCard]="hasActivePhoto()"
                  [naturalFit]="naturalGridFit()"
                  [hideDetails]="effectiveHideDetails()"
                  [listMode]="listMode()"
                  [style.height.px]="listMode() ? listRowHeight() : null"
                  [attr.aria-setsize]="listMode() ? store.photos().length : null"
                  [attr.aria-posinset]="listMode() ? i + 1 : null"
                  [currentSort]="store.filters().sort"
                  [metricRanges]="store.metricRangesByColumn()"
                  [thumbSize]="thumbSize()"
                  [isEditionMode]="auth.isEdition()"
                  [personFilterId]="store.filters().person_id"
                  [tooltipMode]="cardTooltipMode()"
                      [panelActivation]="panelActivation()"
                  (selectionChange)="toggleSelection($event.photo, $event.event, i)"
                  (tooltipShow)="showTooltip($event.event, $event.photo)"
                  (tooltipHide)="hideTooltip()"
                  [filterLinks]="!pinned()"
                      [tagCollectionAvailable]="!store.filters().similar_to" (tagClicked)="navigateTag($event)"
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
              class="flex flex-col gap-[8px] p-2 md:p-4 outline-none"
              (keydown)="onGridKeydown($event)"
              (focusout)="onGridFocusOut($event)"
            >
              @for (row of mosaicRows(); track row.photos[0]?.path ?? $index) {
                <!-- Fixed row dimensions retain the layout; the current-photo
                     marker stays on the card host outside its clipped tile. -->
                <div class="flex gap-[8px]">
                  @for (photo of row.photos; track photo.path; let i = $index) {
                    <app-photo-card
                  [collapsedSetKinds]="collapsedSetKinds()"
                  [burstFramesVisible]="burstFramesVisible()"
                      [tabStop]="photo.path === tabStopPath()"
                    [photo]="photo"
                      [attr.data-pidx]="row.startIndex + i"
                      [style.width.px]="row.widths[i]"
                      [style.height.px]="row.height"
                      [style.content-visibility]="'auto'"
                      [hideDetails]="true"
                      [mosaicMode]="true"
                      [config]="store.config()"
                      [isSelected]="photo.path | isSelected:viewScoped():selectedPaths():excludedPaths()"
                      [showSelectionIndicators]="showSelectionIndicators()"
                      [isActive]="row.startIndex + i === activeIndex()"
                      [gridHasActiveCard]="hasActivePhoto()"
                      [currentSort]="store.filters().sort"
                      [metricRanges]="store.metricRangesByColumn()"
                      [thumbSize]="thumbSize()"
                      [isEditionMode]="auth.isEdition()"
                      [personFilterId]="store.filters().person_id"
                      [tooltipMode]="cardTooltipMode()"
                      [panelActivation]="panelActivation()"
                      (selectionChange)="toggleSelection($event.photo, $event.event, row.startIndex + i)"
                      (tooltipShow)="showTooltip($event.event, $event.photo)"
                      (tooltipHide)="hideTooltip()"
                      [filterLinks]="!pinned()"
                      [tagCollectionAvailable]="!store.filters().similar_to" (tagClicked)="navigateTag($event)"
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
        <div data-gallery-notices animate.leave="motion-safe:animate-notice-stack-out pointer-events-none [&_*]:!pointer-events-none" class="pointer-events-none absolute z-10 flex flex-col gap-2 w-[min(26rem,calc(100%-1rem))]"
             (pointerenter)="noticePointerChange(true)" (pointerleave)="noticePointerChange(false)"
             (focusout)="noticeFocusLeft($event)"
             [style.bottom.px]="noticeBottomPx()" [style.right.px]="noticeRightPx()" [style.maxWidth]="noticeMaxWidth()">
          @if (scrollTopShown()) {
            <ng-container *ngTemplateOutlet="scrollTopFab; context: { $implicit: 'pointer-events-auto self-end' }" />
          }
          @if (shownNoticeCount() > 1 || noticesCollapsed()) {
            <div class="flex flex-wrap items-center justify-end gap-2">
              @if (shownNoticeCount() > 1) {
                <button type="button" data-notice-dismiss-all
                        class="pointer-events-auto self-end min-h-11 rounded-full border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container-high)] px-3 text-xs font-medium shadow-sm hover:bg-[var(--mat-sys-surface-container-highest)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
                        (click)="dismissAllNotices()">{{ I18N.gallery.notices.dismiss_all | translate }}</button>
              }
              @if (noticesCollapsed()) {
                <button type="button" data-gallery-notices-pill animate.enter="motion-safe:animate-notice-in" animate.leave="motion-safe:animate-notice-out pointer-events-none [&_*]:!pointer-events-none"
                        class="pointer-events-auto self-end min-h-11 px-3 py-1.5 rounded-full bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] shadow-lg flex items-center gap-1.5 text-xs"
                        (click)="expandNotices($event)">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">notifications</mat-icon>
                  <span>{{ shownNoticeCount() | pluralKey:I18N.gallery.notices.collapsed:I18N.gallery.notices.collapsed_plural | translate:{ count: shownNoticeCount() } }}</span>
                </button>
              }
            </div>
          }
          @if (!noticesCollapsed()) {
            @if (reviewProgressShown()) {
              @if (store.reviewProgress(); as progress) {
                <section data-review-progress data-notice-kind="review_progress" animate.enter="motion-safe:animate-notice-in" animate.leave="motion-safe:animate-notice-out pointer-events-none [&_*]:!pointer-events-none" [class]="NOTICE_CARD_CLASS" [attr.aria-label]="I18N.gallery.review_progress.title | translate">
                  <mat-icon class="opacity-70 !text-base !w-5 !h-5 self-start">fact_check</mat-icon>
                  <div class="flex-1 min-w-0 flex flex-col gap-1">
                    <span id="notice-text-review_progress" class="flex flex-wrap gap-x-3 gap-y-0.5" role="status" aria-live="polite" aria-atomic="true">
                      <span>{{ I18N.gallery.review_progress.counts | translate:{ undecided: progress.undecided, kept: progress.kept, rejected: progress.rejected } }}</span>
                      <span class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.review_progress.complete | translate:{ percent: store.reviewPercent(), total: progress.total } }}</span>
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
              <div data-notice-kind="review_bookmark" animate.enter="motion-safe:animate-notice-in" animate.leave="motion-safe:animate-notice-out pointer-events-none [&_*]:!pointer-events-none" [class]="NOTICE_CARD_CLASS">
                <mat-icon class="opacity-70 !text-base !w-5 !h-5">bookmark</mat-icon>
                <span id="notice-text-review_bookmark" class="flex-1 opacity-80">{{ I18N.gallery.review_progress.browser | translate }}</span>
                <button mat-button class="!min-w-0" [disabled]="store.loading()" (click)="continueReview()">{{ I18N.gallery.review_progress.resume | translate }}</button>
                <ng-container *ngTemplateOutlet="noticeClose; context: { $implicit: 'review_bookmark' }" />
              </div>
            }
            @if (hiddenNoticeShown()) {
              <div role="status" data-notice-kind="hidden" animate.enter="motion-safe:animate-notice-in" animate.leave="motion-safe:animate-notice-out pointer-events-none [&_*]:!pointer-events-none" [class]="NOTICE_CARD_CLASS">
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
              <div role="status" data-notice-kind="restore_hidden" animate.enter="motion-safe:animate-notice-in" animate.leave="motion-safe:animate-notice-out pointer-events-none [&_*]:!pointer-events-none" [class]="NOTICE_CARD_CLASS">
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
            @if (showRenderMigrationBanner()) {
              <div role="status" data-notice-kind="render_migration" animate.enter="motion-safe:animate-notice-in" animate.leave="motion-safe:animate-notice-out pointer-events-none [&_*]:!pointer-events-none" [class]="NOTICE_CARD_CLASS">
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
        <div #selectionBar data-selection-bar appMovableToolbar
             [toolbarBoundary]="selectionToolbarBoundary()" [toolbarRightInset]="noticeRightPx()" [toolbarOwner]="auth.identity()"
             role="region" [attr.aria-label]="selectionStatus().key | translate:selectionStatus().params" [attr.aria-describedby]="viewScoped() ? 'whole-view-target-note' : null"
             class="absolute bottom-2 md:bottom-4 left-2 md:left-4 z-20 w-fit group/selection flex flex-wrap items-center gap-1 px-2 py-1 rounded-lg bg-[var(--mat-sys-surface-container)] border border-[var(--mat-sys-primary)] shadow-lg max-md:mb-[env(safe-area-inset-bottom)]"
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
            <p id="whole-view-target-note" class="sr-only">{{ I18N.stacks.folded_scope | translate }}</p>
            @if (excludedPaths().size) {
              <p data-selection-exclusions class="[contain:inline-size] text-xs basis-full m-0">{{ I18N.gallery.selection.exclusions | translate:{ count: excludedPaths().size } }}</p>
            }
          } @else if (selectionOutsideLoaded()) {
            <p data-selection-outside class="[contain:inline-size] text-xs basis-full m-0" aria-live="polite">{{ I18N.gallery.selection.outside_loaded | translate:{ count: selectionOutsideLoaded() } }}</p>
          }
          @if (!viewScoped() && selectedStackTiles()) {
            <p data-selection-cover-only class="[contain:inline-size] text-xs basis-full m-0">{{ I18N.gallery.selection.cover_only | translate }}</p>
          }
          <button mat-icon-button type="button" data-toolbar-drag-handle class="!h-11 !w-11 !min-w-11 touch-none cursor-grab active:cursor-grabbing shrink-0"
                  [attr.aria-label]="I18N.gallery.selection.move_bar | translate" aria-describedby="selection-bar-move-help"
                  [matTooltip]="I18N.gallery.selection.move_bar | translate">
            <mat-icon>drag_indicator</mat-icon>
          </button>
          <span id="selection-bar-move-help" class="sr-only">{{ I18N.gallery.selection.move_bar_help | translate }}</span>
          <span data-selection-status tabindex="-1" class="text-sm font-medium shrink-0 px-1">{{ selectionStatus().key | translate:selectionStatus().params }}</span>
          @if (viewScoped() || selectionGroupTargets().total) {
            <details #selectionTargets #selectionDisclosure name="gallery-selection-disclosures" data-selection-targets
              (keydown.escape)="closeDisclosure($event, selectionTargets, targetsSummary)">
              <summary #targetsSummary class="flex min-h-11 cursor-pointer list-none items-center gap-1 rounded-md px-2 text-sm focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"><mat-icon aria-hidden="true">ads_click</mat-icon>{{ I18N.gallery.selection.targets.title | translate }}</summary>
              <div data-toolbar-panel class="absolute bottom-full left-0 mb-3 group-data-[toolbar-down=true]/selection:bottom-auto group-data-[toolbar-down=true]/selection:top-full group-data-[toolbar-down=true]/selection:mb-0 group-data-[toolbar-down=true]/selection:mt-3 max-h-[60vh] w-full max-w-160 overflow-y-auto rounded-lg border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] p-3 shadow-lg text-sm">
                <p class="mt-0">{{ (viewScoped() ? I18N.gallery.selection.targets.view : I18N.gallery.selection.targets.explicit) | translate }}</p>
                @if (!viewScoped()) {
                  <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.selection.targets.loaded | translate:{ shown: selectionGroupTargets().rows.length, total: selectionGroupTargets().total } }}</p>
                  @for (target of selectionGroupTargets().rows; track target.photo.path) {
                    <div class="border-t border-[var(--mat-sys-outline-variant)] py-2">
                      <div class="font-medium truncate" [title]="target.photo.filename">{{ target.photo.filename }}</div>
                      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                        @if (target.photo.stack_id) {
                          <button mat-button class="!px-1 !text-xs" (click)="openStack(target.photo)"><mat-icon>layers</mat-icon>{{ I18N.gallery.selection.targets.manual | translate }}</button>
                          @if (target.photo.stack_count !== null && target.photo.stack_count !== undefined && target.photo.stack_total_count !== null && target.photo.stack_total_count !== undefined) {
                            <span>{{ I18N.gallery.selection.targets.stack_count | translate:{ matching: target.photo.stack_count, total: target.photo.stack_total_count } }}</span>
                          }
                        }
                        @for (kind of target.kinds; track kind) {
                          <span class="inline-flex items-center gap-1"><mat-icon class="!text-base !w-4 !h-4" aria-hidden="true">{{ kind | photoSetKindIcon }}</mat-icon>{{ kind | photoSetKindLabel | translate }}</span>
                        }
                      </div>
                    </div>
                  }
                }
              </div>
            </details>
          }
          <button mat-button disabledInteractive class="max-md:!min-h-11 max-md:!min-w-11 max-md:!w-11 max-md:!px-2" (click)="clearSelection()" [matTooltip]="I18N.gallery.selection.clear | translate" [attr.aria-label]="I18N.gallery.selection.clear | translate"><mat-icon class="max-md:!m-0">close</mat-icon><span class="hidden md:inline">{{ I18N.gallery.selection.clear | translate }}</span></button>
          @if (selectionCount() >= 2) {
            <button mat-button disabledInteractive class="max-md:!min-h-11 max-md:!min-w-11 max-md:!w-11 max-md:!px-2" [disabled]="!canCompareSelection()" (click)="compareSelection()" [matTooltip]="canCompareSelection() ? (I18N.gallery.selection.compare | translate) : ((selectionCount() > compareQueueLimit ? I18N.gallery.selection.compare_queue_limit : I18N.gallery.selection.compare_queue_requirements) | translate:{ max: compareQueueLimit })" [attr.aria-label]="I18N.gallery.selection.compare | translate" [attr.aria-describedby]="canCompareSelection() ? null : 'compare-selection-requirements'"><mat-icon class="max-md:!m-0">compare</mat-icon><span class="hidden md:inline">{{ I18N.gallery.selection.compare | translate }}</span></button>
            @if (!canCompareSelection()) {
              <span id="compare-selection-requirements" class="sr-only">{{ (selectionCount() > compareQueueLimit ? I18N.gallery.selection.compare_queue_limit : I18N.gallery.selection.compare_queue_requirements) | translate:{ max: compareQueueLimit } }}</span>
            }
          }
          @if (auth.isEdition()) {
            <button mat-button data-selection-keep class="max-md:!min-h-11 max-md:!min-w-11 max-md:!w-11 max-md:!px-2" [matTooltip]="I18N.review.keep | translate" (click)="selectionActions.batchReview('kept')" [attr.aria-label]="I18N.review.keep | translate"><mat-icon class="max-md:!m-0">check_circle</mat-icon><span class="hidden md:inline">{{ I18N.review.keep | translate }}</span></button>
            <button mat-button data-selection-reject class="max-md:!min-h-11 max-md:!min-w-11 max-md:!w-11 max-md:!px-2" [matTooltip]="I18N.gallery.selection.reject | translate" (click)="selectionActions.batchReject()" [attr.aria-label]="I18N.gallery.selection.reject | translate"><mat-icon class="max-md:!m-0">thumb_down</mat-icon><span class="hidden md:inline">{{ I18N.gallery.selection.reject | translate }}</span></button>
          }
          <button mat-icon-button class="md:!hidden !h-11 !w-11 !min-w-11 !p-2.5" (click)="openActionsSheet()" [disabled]="selectionActions.downloading()" [matTooltip]="I18N.gallery.selection.actions | translate" [attr.aria-label]="I18N.gallery.selection.actions | translate">
            @if (selectionActions.downloading()) { <mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate"></mat-spinner> } @else { <mat-icon>more_horiz</mat-icon> }
          </button>
          <details #selectionMore #selectionDisclosure name="gallery-selection-disclosures" data-selection-more class="max-md:hidden" (keydown.escape)="closeDisclosure($event, selectionMore, selectionMoreSummary)">
            <summary #selectionMoreSummary class="flex min-h-11 cursor-pointer list-none items-center gap-1 rounded-md px-2 text-sm font-medium hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"><mat-icon aria-hidden="true">more_horiz</mat-icon>{{ I18N.gallery.selection.actions | translate }}</summary>
            <div data-toolbar-panel role="presentation" (click)="closeSelectionMoreOnCommand($event)" class="absolute bottom-full left-0 mb-3 group-data-[toolbar-down=true]/selection:bottom-auto group-data-[toolbar-down=true]/selection:top-full group-data-[toolbar-down=true]/selection:mb-0 group-data-[toolbar-down=true]/selection:mt-3 flex max-h-[60vh] w-full max-w-160 flex-wrap items-center gap-2 overflow-y-auto rounded-lg border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] p-3 shadow-lg">
          @if (!allLoadedSelected()) {
            <button mat-button disabledInteractive (click)="selectAll()" [matTooltip]="I18N.gallery.selection.select_all | translate" [attr.aria-label]="I18N.gallery.selection.select_all | translate"><mat-icon>select_all</mat-icon><span>{{ I18N.gallery.selection.select_all | translate }}</span></button>
          }
          <button mat-button disabledInteractive (click)="invertSelection()" [matTooltip]="I18N.gallery.selection.invert | translate" [attr.aria-label]="I18N.gallery.selection.invert | translate"><mat-icon>flip</mat-icon><span>{{ I18N.gallery.selection.invert | translate }}</span></button>
          @if (auth.isEdition()) {
            <button mat-icon-button [disabled]="viewScoped() || selectionCount() > MAX_REFRESH_PATHS" (click)="refreshSelectedPhotos()"
              [matTooltip]="I18N.photo_refresh.title | translate" [attr.aria-label]="I18N.photo_refresh.title | translate"><mat-icon>refresh</mat-icon></button>
          }
          <!-- Mobile: single Actions trigger opening a touch-friendly bottom sheet -->
          @if (auth.isEdition()) {
            <button mat-button data-create-stack (click)="createStack()" [disabled]="!canCreateStack()"
              [matTooltip]="(canCreateStack() ? (stackShortcut() ? I18N.shortcuts.stack_hint : I18N.stacks.create) : I18N.stacks.explicit_only) | translate:{ key: stackShortcut() }"
              [attr.aria-label]="I18N.stacks.create | translate"><mat-icon>photo_library</mat-icon><span>{{ I18N.stacks.create | translate }}</span></button>
          }


            @if (auth.isEdition()) {
              <span aria-hidden="true" class="w-px h-6 mx-1 bg-[var(--mat-sys-outline-variant)]"></span>
              <button mat-button disabledInteractive (click)="selectionActions.batchFavorite()" [matTooltip]="I18N.gallery.selection.favorite | translate" [attr.aria-label]="I18N.gallery.selection.favorite | translate"><mat-icon>favorite</mat-icon><span>{{ I18N.gallery.selection.favorite | translate }}</span></button>
              <button mat-button disabledInteractive (click)="selectionActions.batchReview('undecided')" [matTooltip]="I18N.review.reset | translate" [attr.aria-label]="I18N.review.reset | translate"><mat-icon>restart_alt</mat-icon><span>{{ I18N.review.reset | translate }}</span></button>
              <button mat-button disabledInteractive [matMenuTriggerFor]="rateMenu" [matTooltip]="I18N.gallery.selection.rate | translate" [attr.aria-label]="I18N.gallery.selection.rate | translate"><mat-icon>star</mat-icon><span>{{ I18N.gallery.selection.rate | translate }}</span></button>
              <mat-menu #rateMenu="matMenu" (closed)="closeSelectionMoreAfterMenu($event)">
                @for (star of [1, 2, 3, 4, 5]; track star) {
                  <button mat-menu-item (click)="selectionActions.batchRate(star)">
                    {{ '★'.repeat(star) }}
                  </button>
                }
                <button mat-menu-item (click)="selectionActions.batchRate(0)">
                  {{ I18N.gallery.selection.clear | translate }}
                </button>
              </mat-menu>
            }
            @if (auth.isEdition() && store.config()?.features?.show_albums) {
              <button mat-button disabledInteractive [matMenuTriggerFor]="albumMenu" [matTooltip]="I18N.albums.add_photos | translate" [attr.aria-label]="I18N.albums.add_photos | translate"><mat-icon>photo_library</mat-icon><span>{{ I18N.albums.add_photos | translate }}</span></button>
              <mat-menu #albumMenu="matMenu" (closed)="closeSelectionMoreAfterMenu($event)">
                @for (album of albumOptions(); track album.id) {
                  <button mat-menu-item (click)="selectionActions.addToAlbum(album.id)">{{ album.name }}</button>
                }
                <button mat-menu-item (click)="selectionActions.createAlbumAndAdd()">
                  <mat-icon>add</mat-icon>
                  {{ I18N.albums.create | translate }}
                </button>
              </mat-menu>
            }
            <!-- The other half of the panorama correction: culling can only fix a
                 set the detector found, and an undetected sweep appears in no
                 culling group at all. Here the frames are in front of the user. -->
            @if (auth.isEdition()) {
              <button mat-button disabledInteractive [matMenuTriggerFor]="sequenceMenu" [matTooltip]="I18N.gallery.selection.mark_sequence | translate" [attr.aria-label]="I18N.gallery.selection.mark_sequence | translate"><mat-icon>panorama_photosphere</mat-icon><span>{{ I18N.gallery.selection.mark_sequence | translate }}</span></button>
              <mat-menu #sequenceMenu="matMenu" (closed)="closeSelectionMoreAfterMenu($event)">
                <button mat-menu-item (click)="selectionActions.markAsPanorama('panorama')">
                  <mat-icon>{{ 'panorama' | sequenceKindIcon }}</mat-icon>
                  {{ I18N.gallery.selection.mark_panorama | translate }}
                </button>
                <button mat-menu-item (click)="selectionActions.markAsPanorama('hdr_panorama')">
                  <mat-icon>{{ 'hdr_panorama' | sequenceKindIcon }}</mat-icon>
                  {{ I18N.gallery.selection.mark_hdr_panorama | translate }}
                </button>
                <button mat-menu-item (click)="selectionActions.markAsPanorama('bracket')">
                  <mat-icon>{{ 'bracket' | sequenceKindIcon }}</mat-icon>
                  {{ I18N.gallery.selection.mark_bracket | translate }}
                </button>
              </mat-menu>
            }
            <span aria-hidden="true" class="w-px h-6 mx-1 bg-[var(--mat-sys-outline-variant)]"></span>
            <button mat-button disabledInteractive (click)="selectionActions.copyPaths()" [matTooltip]="I18N.gallery.selection.copy_filenames | translate" [attr.aria-label]="I18N.gallery.selection.copy_filenames | translate"><mat-icon>content_copy</mat-icon><span>{{ I18N.gallery.selection.copy_filenames | translate }}</span></button>
            @if (auth.isEdition()) {
              <button mat-button (click)="selectionActions.openCaptureDateDialog()" [matTooltip]="I18N.capture_date.title | translate" [attr.aria-label]="I18N.capture_date.title | translate"><mat-icon>edit_calendar</mat-icon><span>{{ I18N.capture_date.title | translate }}</span></button>
              <button mat-button disabledInteractive (click)="selectionActions.openBatchGpsDialog()" [matTooltip]="I18N.photo_detail.gps.batch_title | translate" [attr.aria-label]="I18N.photo_detail.gps.batch_title | translate"><mat-icon>location_on</mat-icon><span>{{ I18N.photo_detail.gps.batch_title | translate }}</span></button>
              <button mat-button disabledInteractive (click)="selectionActions.openManualTagsDialog()" [matTooltip]="I18N.gallery.selection.edit_tags | translate" [attr.aria-label]="I18N.gallery.selection.edit_tags | translate"><mat-icon>sell</mat-icon><span>{{ I18N.gallery.selection.edit_tags | translate }}</span></button>
              <button mat-button disabledInteractive (click)="selectionActions.openExportDialog()" [matTooltip]="I18N.export.action | translate" [attr.aria-label]="I18N.export.action | translate"><mat-icon>drive_file_move</mat-icon><span>{{ I18N.export.action | translate }}</span></button>
              <button mat-button disabledInteractive (click)="selectionActions.openCullDialog()" [matTooltip]="I18N.cull.action | translate" [attr.aria-label]="I18N.cull.action | translate"><mat-icon>move_to_inbox</mat-icon><span>{{ I18N.cull.action | translate }}</span></button>
              <button mat-button (click)="selectionActions.removeSelectedFromCatalog()" [disabled]="viewScoped()"><mat-icon>hide_image</mat-icon><span>{{ I18N.photo_detail.remove_catalog.action | translate }}</span></button>
              @if (store.config()?.cull?.trash_available) {
                <button mat-icon-button disabledInteractive (click)="selectionActions.deleteSelected()"
                        [disabled]="viewScoped()"
                        [matTooltip]="(viewScoped() ? I18N.cull.delete_disabled_view_scope_tooltip : I18N.cull.delete_action) | translate"
                        [attr.aria-label]="I18N.cull.delete_action | translate">
                  <mat-icon>delete</mat-icon>
                </button>
              }
            }
            @if (auth.downloadProfiles().length) {
              <button mat-icon-button [matMenuTriggerFor]="dlMenu" [disabled]="selectionActions.downloading()" [matTooltip]="(selectionActions.downloading() ? I18N.photo_detail.downloading : I18N.gallery.selection.download) | translate" [attr.aria-label]="(selectionActions.downloading() ? I18N.photo_detail.downloading : I18N.gallery.selection.download) | translate">@if (selectionActions.downloading()) { <mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate"></mat-spinner> } @else { <mat-icon>download</mat-icon> }</button>
              <mat-menu #dlMenu="matMenu" (closed)="closeSelectionMoreAfterMenu($event)">
                <button mat-menu-item (click)="selectionActions.downloadSelected()"><mat-icon>image</mat-icon> {{ I18N.download.type_original | translate }}</button>
                @for (profile of auth.downloadProfiles(); track profile) {
                  <button mat-menu-item (click)="selectionActions.downloadSelected('darktable', profile)"><mat-icon>photo_filter</mat-icon> {{ profile }}</button>
                }
                <button mat-menu-item (click)="selectionActions.downloadSelected('raw')"><mat-icon>raw_on</mat-icon> {{ I18N.download.type_raw | translate }}</button>
              </mat-menu>
            } @else {
              <button mat-icon-button (click)="selectionActions.downloadSelected()" [disabled]="selectionActions.downloading()" [matTooltip]="(selectionActions.downloading() ? I18N.photo_detail.downloading : I18N.gallery.selection.download) | translate" [attr.aria-label]="(selectionActions.downloading() ? I18N.photo_detail.downloading : I18N.gallery.selection.download) | translate">@if (selectionActions.downloading()) { <mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate"></mat-spinner> } @else { <mat-icon>download</mat-icon> }</button>
            }
            </div>
          </details>
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
        (loadMore)="store.nextPage()"
        (closed)="store.slideshowActive.set(false)"
      />
    }

    <!-- Photo details tooltip (single instance, repositioned on hover). The docked
         rail renders its own, so the floating one stays away while the rail is up;
         wherever the rail cannot dock (narrow or touch viewports) the panel place
         falls back to this bubble, and hover mode still hides on pure touch. -->
    @if (!tooltipDisabled() && !panelMode() && (tooltipMode() === 'panel' || tooltipMode() === 'click' || (isDesktop() && !isTouchDevice()))) {
      <app-photo-tooltip
        [photo]="tooltipPhoto()"
        [x]="tooltipX()"
        [y]="tooltipY()"
        [flipped]="tooltipFlipped()"
        [pinned]="tooltipMode() === 'click'"
        [histogramDefaultMode]="tooltipHistogramDefaultMode()"
        [indicatorPercent]="clippingIndicatorPercent()"
        [personLinks]="!pinned()" [tagCollectionAvailable]="!store.filters().similar_to" (tagSelected)="navigateTag($event)"
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
      [downloading]="selectionActions.downloading()"
      (action)="onPhotoMenuAction($event)"
      (closed)="onPhotoMenuClosed($event)"
    />
  `,
  changeDetection: ChangeDetectionStrategy.Eager,
  host: {
    class: 'block h-full',
    '(focusin)': 'saveCurrentHistoryPosition()',
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
  private readonly comparisonSession = inject(ComparisonSessionService);
  private readonly albumService = inject(AlbumService);
  private readonly photoActions = inject(PhotoActionsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly positions = inject(GalleryVisitPositions);
  private readonly visitOwner = this.auth.identity();
  private readonly historyPosition = this.readHistoryPosition();
  private positionInterrupted = false;

  // Router.currentNavigation may be cleared before ngOnInit's first render.
  private readonly revisit = this.router.currentNavigation?.()?.extras.info === GALLERY_REVISIT
    || this.router.currentNavigation?.()?.trigger === 'popstate';
  private readonly stacks = inject(PhotoStackService);
  private readonly stackActions = inject(StackActionsService);
  private readonly outlet = inject(RouterOutlet, { optional: true });
  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly ngZone = inject(NgZone);
  private parked = false;
  // Initial config/album setup cannot resume a previous visit's loaded pages.
  private awaitingInitialScope = false;
  private resumeInitialization: (() => void) | null = null;
  private readonly reviewNavigation = inject(GalleryReviewNavigationService);
  private keyboardDecisionPending = false;
  private cursorRevision = 0;
  private resumeNavigation = 0;
  // Detaching loses the DOM scroll position and focus.
  private returnTo: ReturnTarget | null = null;
  private readonly api = inject(ApiService);
  private readonly pageHelp = inject(PageHelpService);
  private readonly viewControls = viewChild(GalleryViewControlsComponent);
  private readonly collectionPopovers = viewChildren(ControlPopoverComponent);
  private readonly criteria = viewChild(GalleryCriteriaComponent);
  private readonly liveAnnouncer = inject(LiveAnnouncer);
  private reviewCloseFocus: (() => void) | null = null;
  private reviewGeneration = 0;
  private readonly collectionReview = viewChild<ControlPopoverComponent>('collectionReview');
  private readonly keepTopDetails = viewChild<ElementRef<HTMLDetailsElement>>('keepTopDetails');
  private readonly collectionSelect = viewChild<unknown, ElementRef<HTMLButtonElement>>('collectionSelect', { read: ElementRef });
  private readonly toolbarSearch = viewChild<ElementRef<HTMLInputElement>>('toolbarSearch');

  protected async navigateTag(choice: TagNavigation): Promise<void> {
    if (choice.scope === 'library') {
      const query = refineTagQuery('', choice.tag);
      if (query === null) return;
      const owner = this.auth.identity();
      // Make the departing visit explicit before a new visit overwrites the
      // session-query slot. Back to a bare root must not restore the new tag.
      const params = { ...buildSyncParams(this.store.filters(), this.store.config()?.defaults, this.store.config()?.search_threshold_default, this.store.currentAlbum()?.smart_filter_json),
        ...(this.store.temporaryReviewQueue() ? { review_queue: '1' } : {}) };
      const captured = await this.router.navigate([], { relativeTo: this.route, queryParams: params, replaceUrl: true, onSameUrlNavigation: 'reload' });
      if (!captured || this.auth.identity() !== owner || this.destroyRef.destroyed) return;
      await this.router.navigate(['/'], { queryParams: { tag_groups: query }, info: GALLERY_REVISIT, onSameUrlNavigation: 'reload' });
      return;
    }
    if (this.store.pinnedPaths() !== null || this.store.filters().similar_to) return;
    const query = refineTagQuery(this.store.filters().tag_groups, choice.tag);
    if (query === null) {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
      return;
    }
    void this.store.updateFilter('tag_groups', query);
  }

  // Album options for "Add to album" menu
  protected readonly albumOptions = signal<Album[]>([]);
  readonly selectionActions = new GallerySelectionActions({
    isActive: () => !this.parked,
    clearSelection: () => this.clearSelection(),
    albumAdded: album => this.albumOptions.update(list => [album, ...list]),
  });

  // "Keep top N%" cull dial: keep the top N% of the current view, select the rest.
  protected readonly keepPercent = signal(20);
  protected readonly keepApplying = signal(false);
  protected readonly keepPreviewKeep = computed(() => Math.ceil(this.store.photoTotal() * this.keepPercent() / 100));
  protected readonly keepPreviewCut = computed(() => Math.max(0, this.store.photoTotal() - this.keepPreviewKeep()));

  private resizeObserver: ResizeObserver | null = null;
  private readonly collectionHeader = viewChild<ElementRef<HTMLElement>>('collectionHeader');
  protected readonly collectionHeaderHeight = signal(0);
  private readonly scrollDirective = viewChild(InfiniteScrollDirective);
  private readonly filterSidebar = viewChild(GalleryFilterSidebarComponent);
  private readonly filterDrawer = viewChild<MatSidenav>('filterDrawer');
  private readonly selectionBar = viewChild<ElementRef<HTMLElement>>('selectionBar');
  private readonly selectionDisclosures = viewChildren<ElementRef<HTMLDetailsElement>>('selectionDisclosure');
  private readonly noticeHost = viewChild<ElementRef<HTMLElement>>('noticeHost');
  protected readonly selectionToolbarBoundary = computed(() => this.noticeHost()?.nativeElement ?? null);
  private readonly destroyRef = inject(DestroyRef);
  private readonly staleness = inject(StalenessGuardFactory);
  private readonly injector = inject(Injector);
  private readonly document = inject(DOCUMENT);
  private readonly scrollContent = viewChild(MatSidenavContent);
  private readonly sidenavContainer = viewChild(MatSidenavContainer);
  private readonly ownTooltips = viewChildren(MatTooltip);
  private readonly menus = viewChildren(MatMenuTrigger);
  private readonly photoTooltips = viewChildren(PhotoTooltipComponent);
  private readonly photoMenu = viewChild(GalleryPhotoMenuComponent);
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
  private readonly selectionDetails = computed(() => {
    const selected = this.selectedPaths();
    const rows: { photo: Photo; kinds: string[] }[] = [];
    if (!selected.size) return { rows, total: 0, stackTiles: 0, outside: 0 };
    const matched = new Set<string>();
    let stackTiles = 0, total = 0;
    for (const photo of this.store.photos()) {
      if (!selected.has(photo.path)) continue;
      matched.add(photo.path);
      if (photo.stack_id && (photo.stack_count ?? 0) > 1) stackTiles++;
      const kinds = [
        ...(photo.sequence_kind && photo.sequence_group_id != null ? [photo.sequence_kind] : []),
        ...(photo.burst_group_id != null ? ['burst'] : []),
        ...(photo.duplicate_group_id != null ? ['duplicate'] : []),
      ];
      if (photo.stack_id || kinds.length) {
        total++;
        if (rows.length < 6) rows.push({ photo, kinds });
      }
    }
    return { rows, total, stackTiles, outside: selected.size - matched.size };
  });
  protected readonly selectionGroupTargets = computed(() => this.selectionDetails());
  protected readonly excludedPaths = this.store.excludedPaths;
  protected readonly selectionCount = this.store.selectionCount;
  protected readonly compareQueueLimit = MAX_COMPARE_QUEUE;
  protected readonly selectionOutsideLoaded = computed(() => {
    if (this.viewScoped()) return 0;
    return this.selectionDetails().outside;
  });
  /** True while the selection means "the whole filtered view", not a path list. */
  protected readonly viewScoped = this.store.viewScopeSelected;
  /** How the bar names its target: explicit photos, the whole view, or the whole view minus exclusions. */
  protected readonly selectedStackTiles = computed(() => this.selectionDetails().stackTiles);
  protected readonly selectionStatus = computed(() => {
    const count = this.selectionCount(), excluded = this.excludedPaths().size;
    const params: Record<string, number> = { count };
    if (!this.viewScoped()) return { key: I18N.gallery.selection.count, params };
    if (!excluded) return { key: I18N.gallery.selection.view_scope_active, params };
    return { key: I18N.gallery.selection.view_scope_except, params: { ...params, excluded } };
  });

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
  protected readonly selectionAffordance = signal(false);
  protected readonly mobileSearchOpen = signal(false);
  private readonly mobileSearchToggle = viewChild<unknown, ElementRef<HTMLButtonElement>>('mobileSearchToggle', { read: ElementRef });
  protected readonly selectingPhotos = computed(() => this.selectionAffordance() || this.selectionCount() > 0);
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
      : `repeat(${this.gridColumns()}, minmax(0, 1fr))`,
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
    this.store.galleryMode() === 'list' || this.containerWidth() > 0 ? this.store.galleryMode() : 'grid',
  );

  readonly listMode = computed(() => this.effectiveGalleryMode() === 'list');
  protected readonly showSelectionIndicators = computed(() =>
    this.selectionAffordance() || (this.selectingPhotos() && !this.isDesktop()),
  );
  protected readonly cardTooltipMode = computed(() =>
    this.selectingPhotos() && !this.isDesktop() ? 'off' : this.tooltipMode(),
  );

  /** Whether to hide photo details below the thumbnails */
  readonly effectiveHideDetails = computed(() => this.store.filters().hide_details);

  /** Tooltip mode signal — 'hover' | 'click' | 'off' */
  readonly tooltipMode = computed(() => this.store.filters().tooltip_mode);
  /** Leaving panel mode releases the held photo: the docked rail is going away
   *  (the Side panel switch hands the surface back to hover bubbles), so the dimming
   *  and the framed card cannot outlive the panel they belong to. Only a
   *  'panel' -> other transition releases: activeIndex is the keyboard cursor in every mode. */
  private readonly releaseOnModeLeave = (() => {
    let previous: string | undefined;
    return effect(() => {
      const mode = this.tooltipMode();
      untracked(() => {
        const left = previous === 'panel' && mode !== 'panel';
        previous = mode;
        if (left && this.hasActivePhoto()) this.releasePanel(false);
      });
    });
  })();
  /** Which gesture(s) retarget the docked panel — only meaningful when tooltipMode is 'panel'. */
  readonly panelActivation = computed(() => this.store.filters().panel_activation);
  /** Whether tooltip is fully disabled (off mode) — used for skipping rendering and hover handlers */
  readonly tooltipDisabled = computed(() => this.tooltipMode() === 'off' || (this.selectingPhotos() && !this.isDesktop()));

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
      this.selectionBarReservePx.set(Math.max(112, Math.ceil(barRect.height + this.floatMarginPx())));
      this.selectionBarOverlap.set(noticeLiftPx({
        hostBottom: hostRect.bottom,
        barTop: barRect.top,
        barBottom: barRect.bottom,
        noticeTop: notices ? hostRect.bottom - this.floatMarginPx() - notices.height : null,
        noticeBottom: notices ? hostRect.bottom - this.floatMarginPx() : null,
        barLeft: barRect.left - hostRect.left,
        barRight: barRect.right - hostRect.left,
        noticeLeft: notices ? notices.left - hostRect.left : null,
        noticeRight: notices ? notices.right - hostRect.left : null,
      }));
    };
    measure();
    if (noticesShown) afterNextRender(measure, { injector: this.injector });
    bar.addEventListener(TOOLBAR_POSITION_EVENT, measure);
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    observer.observe(host);
    if (content) observer.observe(content);
    onCleanup(() => {
      observer.disconnect();
      bar.removeEventListener(TOOLBAR_POSITION_EVENT, measure);
      this.selectionBarOverlap.set(0);
    });
  });

  /** Keeps the stack's left edge at least one margin from the host's left edge when the right inset is large. */
  protected readonly noticeMaxWidth = computed(() => `calc(100% - ${this.noticeRightPx() + this.floatMarginPx()}px)`);

  /** Gap between the gallery content's right edge (end drawer and scrollbar excluded) and the host's. */
  private readonly noticeInsetPx = signal(0);

  /** Right offset of the floating notices: a margin (16px md+, 8px below) plus the drawer/scrollbar gap. */
  protected readonly noticeRightPx = computed(() => {
    // ResizeObserver can retain the previous side-drawer inset after a viewport
    // or presentation change. An over drawer never reserves photo-canvas width.
    const reservesSpace = this.isDesktop() && (this.store.filterDrawerOpen() || this.detailsRailVisible());
    return (reservesSpace ? this.noticeInsetPx() : 0) + this.floatMarginPx();
  });

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

  /** Why photos are hidden, in words: "287 burst repeat(s), 23 blink(s)...". The summary counts
   *  every kind in scope, so a kind whose toggle is off is left out: an opened burst would
   *  otherwise list its own repeats as hidden while all of them are on screen. */
  protected readonly hiddenReasons = computed(() => {
    this.i18n.translations();
    const h = this.store.hiddenSummary();
    const f = this.store.filters();
    const reasons: [boolean, number, string][] = [
      [f.hide_bursts, h.bursts, I18N.gallery.hidden_banner.reason_bursts],
      [f.hide_blinks, h.blinks, I18N.gallery.hidden_banner.reason_blinks],
      [f.hide_duplicates, h.duplicates, I18N.gallery.hidden_banner.reason_duplicates],
      [f.hide_brackets, h.brackets, I18N.gallery.hidden_banner.reason_brackets],
      [f.hide_panoramas, h.panoramas, I18N.gallery.hidden_banner.reason_panoramas],
      [f.hide_rejected, h.rejected ?? 0, I18N.gallery.hidden_banner.reason_rejected],
    ];
    return reasons.filter(([on, n]) => on && n > 0).map(([, n, key]) => this.i18n.t(key, { n })).join(', ');
  });

  /** The set-scope bar's "showing X of Y": the summary's total plus the rejected frames, which
   *  count only while `hide_rejected` is on (the summary reports them apart from its total). */
  protected readonly setBarCounts = computed(() => {
    const hidden = this.store.hiddenSummary().total + (this.store.filters().hide_rejected ? (this.store.hiddenSummary().rejected ?? 0) : 0);
    return { hidden, shown: this.store.photoTotal(), total: this.store.photoTotal() + hidden };
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
    render_migration: String(this.renderMigrationPending()),
  }));

  private noticeClosed(kind: NoticeKind): boolean {
    return this.noticeDismissals()[kind]?.includes(this.noticeSignatures()[kind]) ?? false;
  }

  /** Close one notice for this tab, for as long as it stays the same notice. Nothing else changes. */
  protected dismissNotice(kind: NoticeKind): void {
    this.dismissNotices([kind]);
  }

  protected dismissAllNotices(): void {
    this.dismissNotices(this.shownNoticeKinds());
  }

  private dismissNotices(kinds: readonly NoticeKind[]): void {
    const host = this.noticeHost()?.nativeElement;
    const hadFocus = !!host?.contains(document.activeElement);
    const owner = this.auth.identity();
    let next = this.noticeDismissals();
    for (const kind of kinds) next = withDismissal(next, kind, this.noticeSignatures()[kind]);
    this.noticeDismissals.set(next);
    saveNoticeDismissals(next);
    if (hadFocus) afterNextRender(() => {
      if (this.destroyRef.destroyed || this.parked || owner !== this.auth.identity()) return;
      // Leaving cards remain in the DOM during their animation; never focus one.
      const visible = new Set(this.shownNoticeKinds());
      const close = Array.from(host?.querySelectorAll<HTMLElement>('[data-notice-close]') ?? [])
        .find(button => visible.has(button.closest<HTMLElement>('[data-notice-kind]')?.dataset['noticeKind'] as NoticeKind));
      const target = close ?? this.scrollContent()?.getElementRef().nativeElement;
      if (!target) return;
      if (!target.hasAttribute('tabindex') && !target.matches('button')) target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: true });
    }, { injector: this.injector });
  }

  /** The review-progress card: on in the user menu, counts loaded, and not closed in this tab. */
  /** An empty scope has nothing to review, so it gets no "0 of 0" card. */
  protected readonly reviewProgressShown = computed(() =>
    this.store.reviewProgressVisible() && !!this.store.reviewProgress()?.total && !this.noticeClosed('review_progress'));
  /** The Review popover's checkbox: on while the banner is wanted and not closed for this scope in this tab. */
  protected readonly reviewProgressToggleOn = computed(() =>
    this.store.reviewProgressVisible() && !this.noticeClosed('review_progress'));

  protected onReviewProgressToggle(on: boolean): void {
    if (on) this.showReviewProgress();
    else this.store.setReviewProgressVisible(false);
  }

  /** Bring the banner back: the × only closed it for this scope in this tab, so that memory goes too. */
  protected showReviewProgress(): void {
    const signature = this.noticeSignatures()['review_progress'];
    const next = { ...this.noticeDismissals() };
    const kept = next['review_progress']?.filter(entry => entry !== signature);
    if (kept?.length) next['review_progress'] = kept;
    else delete next['review_progress'];
    this.noticeDismissals.set(next);
    saveNoticeDismissals(next);
    this.store.setReviewProgressVisible(true);
  }
  protected readonly reviewBookmarkShown = computed(() => !!this.store.reviewBookmark() && !this.noticeClosed('review_bookmark'));
  protected readonly hiddenNoticeShown = computed(() => this.showHiddenBanner() && !this.noticeClosed('hidden'));
  protected readonly restoreNoticeShown = computed(() => this.canRestoreHidden() && !this.noticeClosed('restore_hidden'));

  /** The cards that are up right now, in stack order: the one list the stack's presence,
   *  the collapsed pill's count and the collapse lifecycle all derive from. */
  private readonly shownNoticeKinds = computed<NoticeKind[]>(() => ([
    ['review_progress', this.reviewProgressShown()], ['review_bookmark', this.reviewBookmarkShown()],
    ['hidden', this.hiddenNoticeShown()], ['restore_hidden', this.restoreNoticeShown()],
    ['render_migration', this.showRenderMigrationBanner()],
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

  private noticeLayoutWide: boolean | undefined;
  /** Fold/unfold the stack as its card set changes: the first cards arm the
   *  countdown, a new or dismissed card re-expands with a fresh window, an
   *  emptied stack resets so the next arrival starts expanded. The mobile
   *  'over' drawer hides the stack entirely, so the countdown waits and starts
   *  afresh when it closes. A stack that leaves the DOM fires no pointerleave,
   *  so it also clears the pointer hold. */
  private readonly noticeCollapseLifecycle = effect(() => {
    const signature = this.noticesSignature();
    const drawerOpen = this.overDrawerOpen();
    const wide = this.isDesktop();
    const becameNarrow = !wide && this.noticeLayoutWide !== false;
    this.noticeLayoutWide = wide;
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
      if (signature !== previous || becameNarrow) {
        this.noticesCollapsed.set(!wide);
        if (wide) this.armNoticeCollapse(); else this.disarmNoticeCollapse();
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
    const own = SET_KIND_TOGGLE[kind] ?? 'hide_panoramas';
    const updates: Partial<GalleryFilters> = {
      sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
    };
    const stored = loadDisplayOptionsFromStorage();
    const defaults = this.store.config()?.defaults;
    // A Show all pressed on the set bar was for the set alone: leaving puts back the options it
    // lifted, each only while still at its lifted value, so a toggle the user turned back on
    // in the meantime is never overwritten (the rule canRestoreHidden applies).
    Object.assign(updates, this.endSetShowAll(), { [own]: stored[own] ?? (defaults?.[own] ?? true) });
    void this.store.updateFilters(updates);
  }

  private readonly rootFontSize = signal(16);
  private readonly listContentWidth = computed(() => Math.max(0, this.containerWidth() - this.rootFontSize() * (this.isDesktop() ? 2 : 1)));
  protected readonly listRowHeight = computed(() => metadataRowHeight(this.listContentWidth(), this.rootFontSize()));

  /** Ends a set-bar Show all and returns the updates that undo it. */
  private endSetShowAll(): Partial<GalleryFilters> {
    const setShowAll = this.setShowAll;
    this.setShowAll = null;
    if (setShowAll && this.store.hiddenFiltersStash() === setShowAll.stash) this.store.hiddenFiltersStash.set(null);
    return this.store.takeTransientRestore();
  }

  /** The stash a set-bar Show all left in the store, to drop it together with the lift. */
  private setShowAll: { stash: HiddenFilterFlags | null } | null = null;

  /** Leaving the set by any other route (back, a sidebar change) ends its Show all too. */
  private readonly endSetShowAllOnLeave = effect(() => {
    if (this.setScopeKind()) return;
    untracked(() => {
      const restore = this.endSetShowAll();
      if (Object.keys(restore).length > 0) void this.store.updateFilters(restore);
    });
  });

  /** Show every frame of the open set, blinks and rejected frames included, until the set is
   *  cleared. Nothing is saved to the display preferences: a reload must not keep the lift. */
  showWholeSet(): void {
    this.store.showAllHidden({ persist: false, includeRejected: true });
    this.setShowAll = { stash: this.store.hiddenFiltersStash() };
  }

  /** Container width for mosaic layout (updated via ResizeObserver) */
  protected readonly containerWidth = signal(0);
  protected readonly compactCollectionControls = computed(() => this.containerWidth() - (this.isDesktop() ? 32 : 16) < 960);
  protected readonly mediumCollectionControls = computed(() => {
    const available = this.containerWidth() - (this.isDesktop() ? 32 : 16);
    return available >= 480 && available < 640;
  });

  // --- Virtual scrolling (row windowing with top/bottom spacers) ---

  /** Gap between cards/rows in pixels (matches gap-[8px] / mb-[8px], including enlarged root fonts). */
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
    && (this.effectiveGalleryMode() !== 'grid' || this.effectiveHideDetails()),
  );

  /** Cards in the row branch hide their details except in grid mode with details switched on. */
  protected readonly rowCardHideDetails = computed(
    () => this.effectiveGalleryMode() === 'mosaic' || this.effectiveHideDetails(),
  );

  /**
   * The natural tile fit as the grid renders it: grid mode with details hidden
   * only. Mosaic justifies every row to one height by construction, and cards
   * with details keep their equal-height rows, so both ignore the preference
   * (its menu entry is disabled in either case).
   */
  protected readonly naturalGridFit = computed(
    () => this.effectiveGalleryMode() === 'grid' && this.effectiveHideDetails()
      && this.store.filters().tile_fit === 'natural',
  );

  /** Unified row model for the active mode. */
  readonly rowsModel = computed<GalleryRow[]>(() => {
    const photos = this.store.photos();
    // Rows live inside the p-2 md:p-4 container - subtract its padding
    const width = this.listMode() ? this.listContentWidth() : this.containerWidth() - (this.isDesktop() ? 32 : 16);
    if (!photos.length || width <= 0) return [];
    const gap = GalleryComponent.ROW_GAP;
    if (this.listMode()) return buildListRows(photos, width, this.listRowHeight(), gap);
    const build = this.effectiveGalleryMode() === 'mosaic'
      ? (ps: Photo[]) => buildMosaicRows(ps, width, this.cardWidth(), gap)
      : (ps: Photo[]) => buildGridRows(ps, width, this.cardWidth(), gap, this.effectiveHideDetails(), this.isDesktop(), this.store.filters().tile_fit);
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
    let previousMode: string | null = null;
    effect(() => {
      const mode = this.effectiveGalleryMode();
      if (previousMode !== null && previousMode !== mode) untracked(() => this.preserveLayoutAnchor());
      previousMode = mode;
    });
    afterNextRender(() => {
      this.isTouchDevice.set(window.matchMedia('(hover: none)').matches);
      this.touchOnly.set(window.matchMedia('(hover: none) and (pointer: coarse)').matches);
      this.desktop.setup();
      this.railWide.setup();
      this.setupResizeObserver();
      this.setupScrollTracking();
    });

    // Capture before the outlet detaches the DOM and loses scroll and focus.
    this.router.events.pipe(filter(e => e instanceof NavigationStart), takeUntilDestroyed()).subscribe(event => {
      // A filter change only rewrites the query string: keep the popover that made it open.
      if (event.url.split(/[?#]/)[0] !== this.router.url.split(/[?#]/)[0]) this.closeCollectionPopovers();
      for (const disclosure of this.selectionDisclosures()) disclosure.nativeElement.open = false;
      if (!this.router.currentNavigation?.()?.extras?.state?.[REVIEW_RESUME_NAVIGATION]) this.resumeNavigation++;
      if (this.parked) return;
      this.returnTo = this.captureReturnTarget();
      // On popstate the browser already points at the destination entry.
      if (event.navigationTrigger !== 'popstate') this.saveHistoryPosition(this.returnTo);
    });
    if (this.historyPosition) {
      const interrupt = () => { this.positionInterrupted = true; };
      this.watchRestorationInput(interrupt);
    }
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
      closeOverlayDirectives(this.ownTooltips(), this.menus());
      // Context-menu triggers are separate from MatMenuTrigger; all cards share this panel.
      this.photoMenu()?.menu().closed.emit();
      for (const card of this.cards()) card.closeOverlays();
      for (const tooltip of this.photoTooltips()) tooltip.closeOverlays();
      this.filterSidebar()?.closeOverlays();
      this.setGalleryChrome(false);
    });
    this.outlet?.attachEvents.pipe(takeUntilDestroyed()).subscribe(component => {
      if (component !== this) return;
      this.parked = false;
      this.resumeInitialization?.();
      if (!this.awaitingInitialScope) void this.store.resumeListingReads();
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
      if (!this.awaitingInitialScope) this.refreshSideData();
    });

    // Sync store.filterDrawerOpen signal → mat-sidenav. The details rail shares
    // this drawer, so it keeps the strip open on its own once the filters close.
    effect(() => {
      // The persisted flag is left alone while pinned: the drawer only stays shut.
      const open = (this.store.filterDrawerOpen() && !this.pinned()) || this.detailsRailVisible();
      const drawer = this.filterDrawer();
      if (!drawer) return;
      if (open) drawer.open();
      else drawer.close();
    });

    // Re-check sentinel whenever photos, card width, gallery mode, or hide_details change
    effect(() => {
      const photos = this.store.photos(); // track dependency
      this.store.cardWidth(); // track dependency
      this.store.galleryMode(); // track dependency
      this.effectiveHideDetails(); // track dependency — toggling details changes card height
      this.scrollDirective()?.recheck();
      // Keep a docked photo while its row remains in the collection, including
      // when an appended page replaces the photos array.
      untracked(() => {
        const current = this.tooltipPhoto();
        const updated = this.panelMode() && current ? photos.find(photo => photo.path === current.path) : null;
        this.tooltipPhoto.set(updated ?? null);
      });
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
    // A view change clears the selection in the store; the Select affordance goes with it.
    effect(() => {
      this.store.viewChangeClears();
      untracked(() => this.selectionAffordance.set(false));
    });
    effect(() => {
      this.store.filters();
      untracked(() => {
        const details = this.selectionMoreRef()?.nativeElement;
        if (details) details.open = false;
      });
    });
    effect(() => {
      this.tooltipMode(); // track dependency
      this.panelMode(); // the rail breakpoint flips panel mode without a mode change
      untracked(() => this.tooltipPhoto.set(null));
    });
  }

  async ngOnInit(): Promise<void> {
    this.store.galleryMounts.update(n => n + 1);
    const mount = this.store.galleryMounts();
    const owner = this.auth.identity(), token = this.auth.token;
    // A detached gallery still owns its visit; a destroyed/replaced one does not.
    const current = () => !this.destroyRef.destroyed && mount === this.store.galleryMounts()
      && owner === this.auth.identity() && token === this.auth.token;
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
    if (this.revisit) this.store.viewSnapshot.set(null);
    if (!setScope && !this.revisit && this.tryRestoreView()) return;
    // Reset album state to avoid stale singleton data; loadConfig() resets filters from scratch
    this.store.currentAlbum.set(null);
    this.store.initializing.set(true);
    this.awaitingInitialScope = true;
    try {
      if (!await this.store.loadConfig(current)) return;
      if (!current()) return;
      // Record what THIS init resolved to: a plain URL entry must write its own
      // filters (syncUrl never runs for one); startup also loads defaults
      // but must never touch this memory. An album route skips the
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
          const album = await firstValueFrom(this.albumService.get(+albumId).pipe(takeUntilDestroyed(this.destroyRef)));
          if (!current()) return;
          if (album.smart_filter_json) {
            // Apply saved filters BEFORE setting currentAlbum (avoids effect saving defaults)
            const savedJson = album.smart_filter_json;
            this.store.filters.update(current => applyQueryParams(applySavedAlbumFilters(current, savedJson, albumId), this.route.snapshot.queryParams));
          } else {
            this.store.filters.update(current => ({ ...current, album_id: albumId }));
          }
          this.store.currentAlbum.set(album);
        } catch {
          if (!current()) return;
          this.store.filters.update(current => ({ ...current, album_id: albumId }));
        }
      }
      // Scope setup may finish after the outlet detached us. The first listing
      // belongs to this visit, but must wait for its own attachment to start.
      while (this.parked && current()) await new Promise<void>(resolve => { this.resumeInitialization = resolve; });
      this.resumeInitialization = null;
      if (!current()) return;
      this.awaitingInitialScope = false;
      // Photos first — a slow filter-option endpoint must never hold back the grid
      await this.store.loadPhotos(current);
      if (!current()) return;
      this.store.initializing.set(false);
      this.refreshSideData();
      await this.restoreHistoryPosition();
      if (!current()) return;
      // IntersectionObserver fires too early before DOM paint — defer recheck
      requestAnimationFrame(() => setTimeout(() => this.scrollDirective()?.recheck()));
      if (this.store.config()?.features?.show_albums) {
        firstValueFrom(this.albumService.list().pipe(takeUntilDestroyed(this.destroyRef))).then(res => {
          if (current()) this.albumOptions.set(res.albums.filter(a => !a.is_smart));
        }).catch(() => {});
      }
    } finally {
      this.awaitingInitialScope = false;
      this.resumeInitialization = null;
      if (mount === this.store.galleryMounts()) this.store.initializing.set(false);
    }
  }

  private indexOfPath(path: string): number {
    return this.store.photos().findIndex(photo => photo.path === path);
  }

  /** The rendered card's rect for a photo index, or null when it is not in the DOM. */
  private cardRect(index: number): DOMRect | null {
    return index >= 0 ? document.querySelector(`[data-pidx="${index}"]`)?.getBoundingClientRect() ?? null : null;
  }

  /** Keep a visible photo in place when changing presentation, without taking
   * focus away from the View control that the user is operating. */
  private preserveLayoutAnchor(): void {
    if (this.parked || this.store.initializing()) return;
    const content = this.scrollContent(); const viewport = content?.getElementRef().nativeElement;
    if (!content || !viewport) return;
    const box = viewport.getBoundingClientRect();
    const candidates = [...viewport.querySelectorAll<HTMLElement>('[data-pidx]')]
      .filter(node => { const rect = node.getBoundingClientRect(); return rect.bottom > box.top && rect.top < box.bottom; });
    const node = candidates.find(node => Number(node.dataset['pidx']) === this.activeIndex()) ?? candidates[0];
    const index = Number(node?.dataset['pidx']); const photos = this.store.photos();
    const path = photos[index]?.path;
    if (!node || !path || box.height <= 0) return;
    const offset = node.getBoundingClientRect().top - box.top;
    const active = this.activePath(); const mode = this.effectiveGalleryMode(); const navigation = this.resumeNavigation;
    const route = this.router.url.split('?')[0]; const query = this.store.filterKey();
    let interacted = false;
    const veto = () => { interacted = true; };
    const cleanup = this.watchRestorationInput(veto);
    const current = () => !interacted && !this.parked && !this.destroyRef.destroyed
      && (navigation === this.resumeNavigation || (!this.router.currentNavigation() && this.router.url.split('?')[0] === route))
      && query === this.store.filterKey() && mode === this.effectiveGalleryMode() && photos === this.store.photos();
    requestAnimationFrame(() => {
      if (!current()) { cleanup(); return; }
      if (this.virtualOn()) {
        this.updateWindowPosition();
        const row = this.rowsModel().find(row => row.photos.some(photo => photo.path === path));
        if (row) {
          const targetOffset = Math.max(24 - row.height, Math.min(offset, box.height - 24));
          content.scrollTo({ top: Math.max(0, content.measureScrollOffset('top') + row.offset - this.relScrollTop() - targetOffset) });
          this.updateWindowPosition();
        }
      }
      requestAnimationFrame(() => {
        try {
          if (!current()) return;
          const rect = this.cardRect(this.indexOfPath(path)); const now = viewport.getBoundingClientRect();
          if (!rect || now.height <= 0) return;
          const targetOffset = Math.max(24 - rect.height, Math.min(offset, now.height - 24));
          const delta = rect.top - now.top - targetOffset;
          if (Math.abs(delta) >= 1) content.scrollTo({ top: Math.max(0, content.measureScrollOffset('top') + delta) });
          if (active && this.activePath() === null) this.setCursor(this.indexOfPath(active));
        } finally { cleanup(); }
      });
    });
  }

  /** User input cancels automatic positioning; listeners end on completion or destruction. */
  private watchRestorationInput(interrupt: () => void): () => void {
    const events = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;
    const remove = () => {
      for (const event of events) this.document.removeEventListener(event, interrupt, true);
    };
    for (const event of events) this.document.addEventListener(event, interrupt, { capture: true, passive: true });
    const unregister = this.destroyRef.onDestroy(remove);
    return () => { remove(); unregister(); };
  }

  /** Re-anchor after drawer margins and card heights settle, including parked resizes. */
  private restoreReturnAnchor(path: string, anchor: ReturnAnchor, current: () => boolean = () => true): void {
    const url = this.router.url;
    const navigation = this.resumeNavigation;
    let interacted = false;
    const veto = () => { interacted = true; };
    const cleanup = this.watchRestorationInput(veto);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      try {
        if (interacted || !current() || this.parked || this.destroyRef.destroyed || navigation !== this.resumeNavigation
          || this.visitOwner !== this.auth.identity() || this.router.url !== url) return;
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
      } finally { cleanup(); }
    }));
  }

  protected onCollectionReviewOpened(): void {
    this.reviewGeneration++;
  }

  protected onCollectionReviewClosed(): void {
    const focus = this.reviewCloseFocus;
    this.reviewCloseFocus = null;
    if (focus) queueMicrotask(focus);
  }

  protected closeCollectionPopovers(restoreFocus = false): void {
    for (const popover of this.collectionPopovers()) popover.open.set(false);
    // The slideshow must capture a durable return target, not a button in the dismissed panel.
    if (restoreFocus) this.noticeHost()?.nativeElement.querySelector<HTMLElement>('[data-collection-options] button')?.focus({preventScroll: true});
  }

  private setGalleryChrome(active: boolean): void {
    if (!active) {
      this.closeCollectionPopovers();
    }
    this.pageHelp.setDescription(active ? I18N.gallery.help : null);
    this.viewControls()?.setActive(active);
    this.criteria()?.setActive(active);
  }

  private refreshSideData(): void {
    void this.store.loadTypeCounts();
    void this.store.loadFilterOptions();
  }

  ngOnDestroy(): void {
    this.store.slideshowActive.set(false);
    this.resumeInitialization?.();
    this.cancelToolbarSearch();
    this.disarmNoticeCollapse();
    this.setGalleryChrome(false);
    this.saveViewSnapshot();
    this.resizeObserver?.disconnect();
    this.desktop.cleanup();
    this.railWide.cleanup();
  }

  private captureReturnTarget(geometry = true): ReturnTarget {
    const focus = this.document.activeElement;
    const index = Number((focus?.closest('[data-pidx]') as HTMLElement | null)?.dataset['pidx']);
    const path = Number.isInteger(index) ? this.store.photos()[index]?.path ?? null : this.activePath();
    const viewport = geometry ? this.scrollContent()?.getElementRef().nativeElement.getBoundingClientRect() : null;
    const card = !geometry || path === null ? null : this.cardRect(this.indexOfPath(path));
    const scroll = this.scrollContent()?.measureScrollOffset('top') ?? 0;
    return path !== null && viewport && card && viewport.width > 0 && viewport.height > 0
      ? { scroll, focus, path, anchor: { offset: card.top - viewport.top, width: viewport.width, height: viewport.height } }
      : { scroll, focus, path, anchor: null };
  }

  protected saveCurrentHistoryPosition(geometry = false): void {
    if (this.parked || this.destroyRef.destroyed || this.router.currentNavigation?.()) return;
    this.saveHistoryPosition(this.captureReturnTarget(geometry));
  }

  private readHistoryPosition(): GalleryHistoryPosition | null {
    const navigation = this.router.currentNavigation?.();
    if (navigation?.trigger !== 'popstate') return null;
    return this.positions.restore(this.visitOwner, this.router.serializeUrl(navigation.extractedUrl), navigation.id);
  }

  private saveHistoryPosition(back: ReturnTarget): void {
    if (this.visitOwner !== this.auth.identity() || this.store.initializing() || this.store.loading()) return;
    const position: GalleryHistoryPosition = { owner: this.visitOwner, url: this.router.url,
      scroll: back.scroll, path: back.path, page: this.store.filters().page, anchor: back.anchor };
    this.positions.remember(position);
  }

  private async restoreHistoryPosition(): Promise<void> {
    const position = this.historyPosition;
    if (!position) return;
    const revision = this.resumeNavigation;
    const current = () => !this.positionInterrupted && !this.destroyRef.destroyed && !this.parked
      && revision === this.resumeNavigation && this.visitOwner === this.auth.identity() && this.router.url === position.url;
    // A fresh visit must reload its authorized collection. Fetch only as far as
    // its former anchor, never beyond the pages that visit had already loaded.
    while (current() && position.path && this.indexOfPath(position.path) < 0
      && this.store.hasMore() && this.store.filters().page < position.page) {
      const page = this.store.filters().page;
      await this.store.nextPage();
      if (this.store.filters().page <= page || this.store.loadError()) return;
    }
    if (!current() || this.store.loadError()) return;
    afterNextRender(() => {
      if (!current()) return;
      this.scrollContent()?.scrollTo({ top: position.scroll });
      this.updateWindowPosition();
      requestAnimationFrame(() => {
        if (!current()) return;
        const at = position.path === null ? -1 : this.indexOfPath(position.path);
        this.setCursor(at);
        if (at >= 0) {
          this.focusCard(at, false, false);
          if (position.anchor) this.restoreReturnAnchor(position.path!, position.anchor, current);
        }
      });
    }, { injector: this.injector });
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
    const selected = this.viewScoped() ? !this.excludedPaths().has(photo.path) : this.selectedPaths().has(photo.path);
    if (this.panelMode() && !selected) {
      this.tooltipPhoto.set(photo);
      this.setCursor(-1);
    } else this.setCursor(index);
    this.focusCard(index);
  }

  protected clearSelection(): void {
    this.store.clearSelection();
    this.selectionAffordance.set(false);
    this.restoreCursorFocus();
  }

  protected toggleMobileSelection(): void {
    if (this.parked || this.router.currentNavigation?.() || this.overDrawerOpen() || this.dialog.openDialogs.length || this.store.slideshowActive()) return;
    if (this.selectingPhotos()) {
      this.store.clearSelection();
      this.selectionAffordance.set(false);
    } else {
      this.tooltipPhoto.set(null);
      this.selectionAffordance.set(true);
    }
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
    if (document.activeElement?.closest('[role="grid"], [data-photo-collection], [data-collection-header]')) return;
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
    const { key, params } = this.selectionStatus();
    void this.liveAnnouncer.announce(this.i18n.t(key, params));
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

  /** Capture only a bounded explicit loaded queue; the workspace separately limits visible panes. */
  protected readonly canCompareSelection = computed(
    () => !this.viewScoped() && this.selectionCount() >= 2 && this.selectionCount() <= MAX_COMPARE_QUEUE
      && this.selectionOutsideLoaded() === 0,
  );

  protected async compareSelection(): Promise<void> {
    if (!this.canCompareSelection()) return;
    const selected = new Set(this.store.selectedLoadedPaths());
    // Keep the grid's order rather than selection order: comparing left-to-right
    // as they are laid out is what the user is already looking at.
    const photos = this.store.photos().filter(p => selected.has(p.path));
    if (photos.length < 2) return;
    if (this.parked || this.router.currentNavigation?.() || !this.comparisonSession.start(photos, this.router.url)) return;
    const browserUrl = location.pathname + location.search + location.hash;
    const originId = browserUrl === this.router.url ? history.state?.navigationId ?? null : null;
    if (!await this.router.navigateByUrl('/photo-compare', {
      state: { comparisonReturn: this.router.url, comparisonOriginId: originId },
    })) this.comparisonSession.clear();
  }

  /** Ctrl+A selects all loaded photos unless focus is in an input or a dialog is open. */
  protected onSelectAllShortcut(event: Event): void {
    if (this.parked) return;
    const target = event.target as HTMLElement | null;
    if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
    if (target?.isContentEditable) return;
    if (document.querySelector('mat-dialog-container, mat-bottom-sheet-container, [role="dialog"][aria-modal="true"]')) return;
    if (!this.store.photos().length) return;
    event.preventDefault();
    this.selectAll();
  }

  /**
   * "Keep top N%": ask the server for the bottom (100-N)% of the current view by
   * the current sort, select them, and let the user reject via the selection bar.
   */
  protected async applyKeepTop(): Promise<void> {
    if (this.keepApplying()) return;
    const identity = this.auth.identity();
    const details = this.keepTopDetails()?.nativeElement;
    const review = this.collectionReview();
    const generation = this.reviewGeneration;
    const live = () => !this.parked && !this.router.currentNavigation?.() && !this.destroyRef.destroyed && this.auth.identity() === identity;
    this.keepApplying.set(true);
    try {
      const res = await this.store.selectBottomPercent(this.keepPercent());
      if (!res || !live()) return;
      if (details?.open && details === this.keepTopDetails()?.nativeElement && review?.open() && generation === this.reviewGeneration) {
        this.reviewCloseFocus = () => { if (live() && !this.collectionPopovers().some(popover => popover.open())) this.collectionSelect()?.nativeElement.focus({ preventScroll: true }); };
        details.open = false;
        review.open.set(false);
      }
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
      case 'review': await this.selectionActions.reviewSingle(photo.path, action.decision); break;
      case 'toggle-favorite': this.store.toggleFavorite(photo.path); break;
      case 'toggle-reject': this.store.toggleRejected(photo.path); break;
      case 'rate': this.store.setRating(photo.path, action.rating); break;
      case 'open': this.downloadPhoto(photo); break;
      case 'similar': this.openSimilar(photo, action.mode); break;
      case 'critique': this.openCritique(photo); break;
      case 'refresh': await this.photoActions.refreshPhotos(paths); break;
      case 'embed': this.embedMetadata(photo); break;
      case 'assign-face': this.openAddPerson(photo); break;
      case 'album': await this.selectionActions.addToAlbum(action.albumId, paths); break;
      case 'create-album': await this.selectionActions.createAlbumAndAdd(paths); break;
      case 'copy': await this.selectionActions.copyPaths(paths); break;
      case 'export': this.selectionActions.openExportDialog(paths); break;
      case 'cull': await this.selectionActions.openCullDialog(paths); break;
      case 'delete': await this.selectionActions.deleteSelected(paths); break;
      case 'download': await this.selectionActions.downloadSelected(action.type, action.profile, paths); break;
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
    if (!photo.stack_id || this.parked || this.router.currentNavigation?.() || this.store.slideshowActive()) return;
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
      case 'review': await this.selectionActions.batchReview(action.decision); break;
      case 'favorite': await this.selectionActions.batchFavorite(); break;
      case 'reject': await this.selectionActions.batchReject(); break;
      case 'rate': await this.selectionActions.batchRate(action.rating); break;
      case 'album': await this.selectionActions.addToAlbum(action.albumId); break;
      case 'create-album': await this.selectionActions.createAlbumAndAdd(); break;
      case 'invert': this.invertSelection(); break;
      case 'compare': await this.compareSelection(); break;
      case 'export': this.selectionActions.openExportDialog(); break;
      case 'cull': await this.selectionActions.openCullDialog(); break;
      case 'capture-date': await this.selectionActions.openCaptureDateDialog(); break;
      case 'tags': await this.selectionActions.openManualTagsDialog(); break;
      case 'gps': await this.selectionActions.openBatchGpsDialog(); break;
      case 'delete': await this.selectionActions.deleteSelected(); break;
      case 'copy': await this.selectionActions.copyPaths(); break;
      case 'mark-panorama': await this.selectionActions.markAsPanorama(action.sequenceKind); break;
      case 'download': await this.selectionActions.downloadSelected(action.type, action.profile); break;
    }
  }


  protected openAlbumScoped(path: string, albumId: number): void {
    void this.router.navigate([path], { queryParams: { album: albumId } });
  }


  async openScanLauncher(): Promise<void> {
    if (await this.scan.openLauncher()) {
      await this.store.loadTypeCounts();
      await this.store.reloadPhotos();
    }
  }


  openCritique(photo: Photo): void {
    this.photoActions.openCritique(photo);
  }

  /** The docked rail's score-explainer button (on the assessment line) renders only while the rail
   *  holds a photo and the install shows the explainer at all — the same show_critique
   *  flag the card's hover bar and the photo detail toolbar gate theirs on. */
  protected readonly railCritiqueVisible = computed(
    () => !!this.panelPhoto() && !!this.store.config()?.features?.show_critique,
  );

  /** The docked rail's score-explainer entry: explains the photo the rail holds. */
  protected openRailCritique(): void {
    const p = this.panelPhoto();
    if (p) this.openCritique(p);
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
      if (!this.toolbarSearch()) return;
      event.preventDefault();
      this.focusCollectionSearch();
      return;
    }
    if (this.keymap.matches(event, 'toggleSidebar')) {
      event.preventDefault();
      this.store.setFilterDrawerOpen(!this.store.filterDrawerOpen());
      return;
    }
    if (this.keymap.matches(event, 'swapLayout')) {
      event.preventDefault();
      this.store.setGalleryMode(nextGalleryMode(this.effectiveGalleryMode()));
    }
  }

  protected focusCollectionSearch(): void {
    if (this.parked || this.router.currentNavigation?.() || this.destroyRef.destroyed) return;
    const focus = () => {
      if (this.parked || this.router.currentNavigation?.() || this.destroyRef.destroyed) return;
      const input = this.toolbarSearch()?.nativeElement;
      input?.focus(); input?.select();
    };
    if (this.compactCollectionControls() && !this.mediumCollectionControls() && !this.mobileSearchOpen()) {
      this.mobileSearchOpen.set(true);
      afterNextRender(focus, { injector: this.injector });
    } else focus();
  }

  protected readonly closeDisclosure = closeDetailsOnEscape;
  private readonly selectionMoreRef = viewChild<ElementRef<HTMLDetailsElement>>('selectionMore');

  /** The Actions disclosure is a menu: running one of its commands closes it, opening one of its menus does not. */
  protected closeSelectionMoreOnCommand(event: Event): void {
    const button = event.target instanceof Element ? event.target.closest('button') : null;
    if (button && !button.hasAttribute('aria-haspopup')) this.closeSelectionMore();
  }

  /** A command chosen from one of the disclosure's menus runs it; Escape or Tab only leaves the menu. */
  protected closeSelectionMoreAfterMenu(reason: MenuCloseReason): void {
    if (reason === 'click') this.closeSelectionMore();
  }

  private closeSelectionMore(): void {
    const details = this.selectionMoreRef()?.nativeElement;
    if (details) details.open = false;
  }

  protected closeMobileSearch(event: Event): void {
    if (!this.compactCollectionControls() || this.mediumCollectionControls()) return;
    event.preventDefault(); event.stopPropagation();
    this.mobileSearchOpen.set(false);
    this.mobileSearchToggle()?.nativeElement.focus();
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
    const measureListRow = () => {
      const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
      if (Number.isFinite(rem) && rem > 0) this.rootFontSize.set(rem);
    };
    measureListRow();
    this.resizeObserver = new ResizeObserver(entries => {
      // A parked gallery measures 0; keep its layout for the return.
      if (this.parked) return;
      measureListRow();
      const header = this.collectionHeader()?.nativeElement;
      for (const entry of entries) {
        if (header && entry.target === header) {
          this.collectionHeaderHeight.set(entry.target.getBoundingClientRect().height);
        } else this.containerWidth.set(Math.floor(entry.contentRect.width));
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
    const header = this.collectionHeader()?.nativeElement;
    if (header) {
      this.collectionHeaderHeight.set(header.getBoundingClientRect().height);
      this.resizeObserver.observe(header);
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
    this.cursorRevision++;
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
    if (next?.closest('[role="grid"], [data-photo-collection], [data-collection-header], [data-selection-bar], [data-details-rail], .cdk-overlay-container')) return;
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

  /** The one card in the page's tab order: the cursor's card, else the first. Arrow keys do the rest. */
  protected readonly tabStopPath = computed(() =>
    (this.hasActivePhoto() ? this.store.photos()[this.activeIndex()] : this.store.photos()[0])?.path ?? null);

  /** What the docked rail shows: the current photo while there is one, so
   *  crossing other cards on the way to the rail cannot retarget it, and the
   *  last hovered/clicked photo otherwise. */
  protected readonly panelPhoto = computed(() =>
    this.hasActivePhoto() ? this.store.photos()[this.activeIndex()] : this.tooltipPhoto());

  /** The rail's Deselect: drop the current photo, and with it the lock and the
   *  dimming, and take it out of the batch selection its click put it in.
   *  The rail keeps showing it until the next hover rather than jumping to
   *  whichever card the pointer crossed last. */
  protected releasePanel(deselect = true): void {
    const photo = this.panelPhoto();
    if (!this.hasActivePhoto() || !photo) return;
    this.tooltipPhoto.set(photo);
    // Same rule as IsSelectedPipe: a view-scoped selection is "all but excluded".
    const selected = this.viewScoped()
      ? !this.excludedPaths().has(photo.path)
      : this.selectedPaths().has(photo.path);
    if (selected && deselect) this.store.toggleSelection(photo);
    this.setCursor(-1);
  }

  protected deselectFromRail(): void {
    const index = this.activeIndex();
    this.releasePanel();
    this.focusCard(index, false, false);
    if (!document.activeElement?.closest('app-photo-card')) {
      (this.noticeHost()?.nativeElement.querySelector('[data-details-rail]') as HTMLElement | null)?.focus();
    }
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
    return gridColumnCount(width, this.cardWidth(), GalleryComponent.ROW_GAP, this.isDesktop(), this.effectiveHideDetails() ? MOBILE_MIN_COLUMNS : MOBILE_DETAILS_MIN_COLUMNS);
  }

  /** Vertical step for the active index: grid = ±columns, mosaic = same offset in adjacent row. */
  private verticalTarget(index: number, dir: 1 | -1): number {
    const count = this.store.photos().length;
    if (this.listMode()) return Math.max(0, Math.min(count - 1, index + dir));
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
        // A click-opened tooltip — and the panel place's floating fallback where
        // the rail cannot dock — is the innermost layer: close it before touching the selection.
        if ((this.tooltipMode() === 'click' || (this.tooltipMode() === 'panel' && !this.panelMode())) && this.tooltipPhoto()) {
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
   *  reject key (or 0) rejects (optional success-driven advance), the mapped favourite key
   *  toggles favorite (stays put — a tag-like toggle), the mapped keep key
   *  keeps (review queue). Edition-only and gated on the rating-controls
   *  feature flag, mirroring the card's own template guards. */
  private handleRatingKey(event: KeyboardEvent, photos: Photo[], index: number): void {
    if (isPageShortcutBlocked(event) || isImeOrRepeat(event) || this.parked
      || this.router.currentNavigation?.() || this.store.slideshowActive()) return;
    if (!this.auth.isEdition() || !this.store.config()?.features?.show_rating_controls) return;
    const photo = photos[index];
    if (!photo) return;
    let write: (() => Promise<unknown>) | null = null;
    if (event.key >= '1' && event.key <= '5') {
      write = () => this.store.setRating(photo.path, Number(event.key));
    } else if (this.keymap.matches(event, 'keep')) {
      write = () => this.selectionActions.reviewSingle(photo.path, 'kept');
    } else if (event.key === '0' || this.keymap.matches(event, 'reject')) {
      write = () => this.store.toggleRejected(photo.path);
    } else if (this.keymap.matches(event, 'favourite')) {
      event.preventDefault();
      if (!this.keyboardDecisionPending) void this.store.toggleFavorite(photo.path);
      return;
    } else return;
    event.preventDefault();
    if (this.keyboardDecisionPending || (this.store.loading() && !this.store.isPageAppending())) return;
    const token = this.auth.token;
    const query = () => JSON.stringify({ ...this.store.filters(), page: 1 });
    const filters = query();
    const cursor = this.cursorRevision;
    const focused = this.document.activeElement;
    const advance = this.reviewNavigation.capture();
    const guard = this.staleness.create(this.destroyRef, { track: 'status', valid: () =>
      !this.parked && token === this.auth.token && filters === query()
      && cursor === this.cursorRevision && (focused === this.document.activeElement
        || (focused instanceof HTMLElement && !focused.isConnected && this.document.activeElement === this.document.body)) });
    this.keyboardDecisionPending = true;
    void this.liveAnnouncer.announce(this.i18n.t(I18N.ui.buttons.saving));
    void (async () => {
      try {
        const accepted = await write();
        if (!accepted || !guard.current() || this.store.loading() || this.store.loadError()) return;
        if (advance()) this.focusAfterDecision(photos, index);
        else {
          // Keep the rated photo, even after a sort rebuild moved its DOM node.
          // If filtering removed it, repair at its former position without an extra skip.
          const at = this.store.photos().findIndex(item => item.path === photo.path);
          const target = at >= 0 ? at : Math.min(index, this.store.photos().length - 1);
          if (target >= 0) { this.setCursor(target); this.focusCard(target); }
        }
      } finally {
        this.keyboardDecisionPending = false;
        guard.dispose();
      }
    })();
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
      // Native focus scrolls toward the center first. Own the scroll once,
      // below, so moving the cursor cannot jump out and back into position.
      focusable.focus({ preventScroll: true });
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
    const revision = this.cursorRevision;
    const path = this.store.photos()[index]?.path;
    const owner = this.auth.identity();
    const url = this.router.url;
    const current = () => !this.destroyRef.destroyed && !this.parked && !this.router.currentNavigation?.()
      && this.cursorRevision === revision && this.auth.identity() === owner && this.router.url === url
      && this.store.photos()[index]?.path === path;
    requestAnimationFrame(() => {
      if (!current()) return;
      this.updateWindowPosition();
      requestAnimationFrame(() => { if (current()) this.focusCard(index, true); });
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
        this.saveCurrentHistoryPosition();
        if (!rafPending) {
          rafPending = true;
          requestAnimationFrame(() => {
            rafPending = false;
            this.updateWindowPosition();
            this.saveCurrentHistoryPosition(true);
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
