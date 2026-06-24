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
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatSidenav, MatSidenavModule, MatSidenavContent } from '@angular/material/sidenav';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatBottomSheet, MatBottomSheetModule } from '@angular/material/bottom-sheet';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { GalleryStore, PhotoFlagSnapshot } from './gallery.store';
import { Photo } from '../../shared/models/photo.model';
import { isTypingContext } from '../../shared/utils/keyboard';
import { UndoService } from '../../core/services/undo.service';
import { AuthService } from '../../core/services/auth.service';
import { useDesktopSignal } from '../../shared/utils/media-query';
import { downloadAll } from '../../shared/utils/download';
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
  GalleryRow, buildGridRows, buildMosaicRows, gridColumnCount, totalRowsHeight, windowRange,
} from './gallery-rows.util';
import { AlbumService, Album } from '../../core/services/album.service';
import { CreateAlbumDialogComponent } from '../albums/create-album-dialog.component';
import { ExportEditorDialogComponent } from './export-editor-dialog.component';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';

@Component({
  selector: 'app-gallery',
  imports: [
    MatSidenavModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatButtonModule,
    MatDialogModule,
    MatMenuModule,
    MatTooltipModule,
    MatBottomSheetModule,
    TranslatePipe,
    MatSnackBarModule,
    PhotoTooltipComponent,
    SlideshowComponent,
    GalleryFilterSidebarComponent,
    PhotoCardComponent,
    PhotoSkeletonComponent,
    InfiniteScrollDirective,
  ],
  template: `
    <mat-sidenav-container class="h-full">
      <!-- Filter sidebar -->
      <mat-sidenav #filterDrawer disableClose="false" [mode]="isDesktop() ? 'side' : 'over'" position="end" class="w-[min(320px,100vw)] p-0"
        (openedChange)="onFilterDrawerChange($event)">
        <app-gallery-filter-sidebar />
      </mat-sidenav>

      <!-- Main content -->
      <mat-sidenav-content>
        <!-- Hidden-photos banner -->
        @if (showHiddenBanner()) {
          <div class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex items-center gap-3 text-sm">
            <mat-icon class="opacity-70 !text-base !w-5 !h-5">visibility_off</mat-icon>
            <span class="flex-1">
              {{ 'gallery.hidden_banner.message' | translate:{ n: store.hiddenSummary().total } }}
            </span>
            <button mat-button class="!min-w-0" (click)="showAllHidden()">
              {{ 'gallery.hidden_banner.show_all' | translate }}
            </button>
          </div>
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
              [attr.aria-label]="'gallery.photo_grid' | translate"
              [attr.aria-rowcount]="rowsModel().length"
              class="flex flex-col p-2 md:p-4 outline-none"
              (keydown)="onGridKeydown($event)"
            >
              <div [style.height.px]="topSpacer()" aria-hidden="true"></div>
              @for (row of visibleRows(); track row.photos[0].path) {
                <div class="flex gap-2 mb-2" [style.height.px]="row.height">
                  @for (photo of row.photos; track photo.path; let i = $index) {
                    <app-photo-card
                      [photo]="photo"
                      [attr.data-pidx]="row.startIndex + i"
                      [style.width.px]="row.widths[i]"
                      [style.height.px]="row.height"
                      class="shrink-0"
                      [hideDetails]="true"
                      [mosaicMode]="effectiveGalleryMode() === 'mosaic'"
                      [config]="store.config()"
                      [isSelected]="selectedPaths().has(photo.path)"
                      [currentSort]="store.filters().sort"
                      [thumbSize]="thumbSize()"
                      [isEditionMode]="auth.isEdition()"
                      [personFilterId]="store.filters().person_id"
                      [tooltipMode]="tooltipMode()"
                      (selectionChange)="toggleSelection($event.photo, $event.event)"
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
              [attr.aria-label]="'gallery.photo_grid' | translate"
              class="grid grid-cols-1 gap-2 p-2 md:p-4 gallery-grid outline-none"
              [style.--gallery-cols]="'repeat(auto-fill, minmax(' + cardWidth() + 'px, 1fr))'"
              (keydown)="onGridKeydown($event)"
            >
              @for (photo of store.photos(); track photo.path; let i = $index) {
                <app-photo-card
                  [photo]="photo"
                  [attr.data-pidx]="i"
                  [config]="store.config()"
                  [isSelected]="selectedPaths().has(photo.path)"
                  [hideDetails]="effectiveHideDetails()"
                  [currentSort]="store.filters().sort"
                  [thumbSize]="thumbSize()"
                  [isEditionMode]="auth.isEdition()"
                  [personFilterId]="store.filters().person_id"
                  [tooltipMode]="tooltipMode()"
                  [style.content-visibility]="'auto'"
                  [style.contain-intrinsic-size]="'auto ' + (cardWidth() + 80) + 'px'"
                  (selectionChange)="toggleSelection($event.photo, $event.event)"
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
              [attr.aria-label]="'gallery.photo_grid' | translate"
              class="flex flex-col gap-2 p-2 md:p-4 outline-none"
              (keydown)="onGridKeydown($event)"
            >
              @for (row of mosaicRows(); track row.photos[0]?.path ?? $index) {
                <div class="flex gap-2" style="content-visibility: auto; contain-intrinsic-size: auto 300px">
                  @for (photo of row.photos; track photo.path; let i = $index) {
                    <app-photo-card
                      [photo]="photo"
                      [attr.data-pidx]="row.startIndex + i"
                      [style.width.px]="row.widths[i]"
                      [style.height.px]="row.height"
                      [hideDetails]="true"
                      [mosaicMode]="true"
                      [config]="store.config()"
                      [isSelected]="selectedPaths().has(photo.path)"
                      [currentSort]="store.filters().sort"
                      [thumbSize]="thumbSize()"
                      [isEditionMode]="auth.isEdition()"
                      [personFilterId]="store.filters().person_id"
                      [tooltipMode]="tooltipMode()"
                      (selectionChange)="toggleSelection($event.photo, $event.event)"
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
          <div role="status" [attr.aria-label]="'gallery.loading_photos' | translate" aria-busy="true">
            @if (!store.photos().length) {
              <div
                class="grid grid-cols-1 gap-2 p-2 md:p-4 gallery-grid"
                [style.--gallery-cols]="'repeat(auto-fill, minmax(' + cardWidth() + 'px, 1fr))'"
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

        <!-- Empty state -->
        @if (!store.loading() && store.photos().length === 0 && store.total() === 0) {
          <div class="flex flex-col items-center justify-center gap-4 p-16 opacity-60">
            <mat-icon class="!text-6xl !w-16 !h-16">photo_library</mat-icon>
            <p class="text-lg">{{ 'gallery.no_photos' | translate }}</p>
            @if (store.activeFilterCount()) {
              <button mat-stroked-button (click)="store.resetFilters()">
                {{ 'gallery.reset_filters' | translate }}
              </button>
            } @else if (auth.isSuperadmin() && auth.hasFeature('show_scan_button')) {
              <button mat-flat-button color="primary" (click)="openScanLauncher()">
                <mat-icon>add_photo_alternate</mat-icon>
                {{ 'scan.get_started' | translate }}
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
        [matTooltip]="'gallery.scroll_to_top' | translate"
        [attr.aria-label]="'gallery.scroll_to_top' | translate"
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
    @if (!tooltipDisabled() && (tooltipMode() === 'click' || (isDesktop() && !isTouchDevice()))) {
      <app-photo-tooltip
        [photo]="tooltipPhoto()"
        [x]="tooltipX()"
        [y]="tooltipY()"
        [flipped]="tooltipFlipped()"
      />
    }

    <!-- Selection action bar -->
    @if (selectionCount()) {
      <div class="fixed bottom-[45px] lg:bottom-0 left-0 right-0 z-50 flex items-center justify-center gap-1 lg:gap-3 px-2 lg:px-6 py-1 lg:py-3 bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
        <span class="text-sm font-medium shrink-0">{{ 'gallery.selection.count' | translate:{ count: selectionCount() } }}</span>
        <div class="flex items-center gap-0 lg:gap-2">
          <button mat-icon-button class="lg:!hidden" (click)="clearSelection()" [matTooltip]="'gallery.selection.clear' | translate"><mat-icon>close</mat-icon></button>
          <button mat-button class="!hidden lg:!inline-flex" (click)="clearSelection()"><mat-icon>close</mat-icon> {{ 'gallery.selection.clear' | translate }}</button>
          @if (!allLoadedSelected()) {
            <button mat-icon-button class="lg:!hidden" (click)="selectAll()" [matTooltip]="'gallery.selection.select_all' | translate"><mat-icon>select_all</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="selectAll()"><mat-icon>select_all</mat-icon> {{ 'gallery.selection.select_all' | translate }}</button>
          }
          <!-- Mobile: single Actions trigger opening a touch-friendly bottom sheet -->
          <button mat-flat-button class="lg:!hidden" (click)="openActionsSheet()" [disabled]="downloading()">
            @if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>more_horiz</mat-icon> }
            {{ 'gallery.selection.actions' | translate }}
          </button>
          @if (auth.isEdition()) {
            <button mat-button class="!hidden lg:!inline-flex" (click)="batchFavorite()"><mat-icon>favorite</mat-icon> {{ 'gallery.selection.favorite' | translate }}</button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="batchReject()"><mat-icon>thumb_down</mat-icon> {{ 'gallery.selection.reject' | translate }}</button>
            <button mat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="rateMenu"><mat-icon>star</mat-icon> {{ 'gallery.selection.rate' | translate }}</button>
            <mat-menu #rateMenu="matMenu">
              @for (star of [1, 2, 3, 4, 5]; track star) {
                <button mat-menu-item (click)="batchRate(star)">
                  {{ '★'.repeat(star) }}
                </button>
              }
              <button mat-menu-item (click)="batchRate(0)">
                {{ 'gallery.selection.clear' | translate }}
              </button>
            </mat-menu>
          }
          @if (auth.isEdition() && store.config()?.features?.show_albums) {
            <button mat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="albumMenu"><mat-icon>photo_library</mat-icon> {{ 'albums.add_photos' | translate }}</button>
            <mat-menu #albumMenu="matMenu">
              @for (album of albumOptions(); track album.id) {
                <button mat-menu-item (click)="addToAlbum(album.id)">{{ album.name }}</button>
              }
              <button mat-menu-item (click)="createAlbumAndAdd()">
                <mat-icon>add</mat-icon>
                {{ 'albums.create' | translate }}
              </button>
            </mat-menu>
          }
          <button mat-button class="!hidden lg:!inline-flex" (click)="copyPaths()"><mat-icon>content_copy</mat-icon> {{ 'gallery.selection.copy_filenames' | translate }}</button>
          @if (auth.isEdition()) {
            <button mat-button class="!hidden lg:!inline-flex" (click)="openExportDialog()"><mat-icon>drive_file_move</mat-icon> {{ 'export.action' | translate }}</button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="openCullDialog()"><mat-icon>folder_move</mat-icon> {{ 'cull.action' | translate }}</button>
          }
          @if (auth.downloadProfiles().length) {
            <button mat-flat-button class="!hidden lg:!inline-flex" [matMenuTriggerFor]="dlMenu" [disabled]="downloading()">@if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> } {{ downloading() ? ('photo_detail.downloading' | translate) : ('gallery.selection.download' | translate) }}</button>
            <mat-menu #dlMenu="matMenu">
              <button mat-menu-item (click)="downloadSelected()"><mat-icon>image</mat-icon> {{ 'download.type_original' | translate }}</button>
              @for (profile of auth.downloadProfiles(); track profile) {
                <button mat-menu-item (click)="downloadSelected('darktable', profile)"><mat-icon>photo_filter</mat-icon> {{ profile }}</button>
              }
              <button mat-menu-item (click)="downloadSelected('raw')"><mat-icon>raw_on</mat-icon> {{ 'download.type_raw' | translate }}</button>
            </mat-menu>
          } @else {
            <button mat-flat-button class="!hidden lg:!inline-flex" (click)="downloadSelected()" [disabled]="downloading()">@if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline"></mat-spinner> } @else { <mat-icon>download</mat-icon> } {{ downloading() ? ('photo_detail.downloading' | translate) : ('gallery.selection.download' | translate) }}</button>
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
  protected readonly store = inject(GalleryStore);
  protected readonly auth = inject(AuthService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly bottomSheet = inject(MatBottomSheet);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialog);
  private readonly albumService = inject(AlbumService);
  private readonly photoActions = inject(PhotoActionsService);
  private readonly undoService = inject(UndoService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(ApiService);

  // Album options for "Add to album" menu
  protected readonly albumOptions = signal<Album[]>([]);
  protected readonly downloading = signal(false);

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
  protected readonly selectionCount = this.store.selectionCount;

  /** True when every loaded photo is already selected. */
  protected readonly allLoadedSelected = computed(() =>
    this.store.photos().length > 0 && this.selectionCount() >= this.store.photos().length,
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

  /** Effective gallery mode: force grid on small viewports */
  readonly effectiveGalleryMode = computed(() =>
    (this.isDesktop() && this.containerWidth() > 0) ? this.store.galleryMode() : 'grid',
  );

  /** Whether to hide photo details below the thumbnails */
  readonly effectiveHideDetails = computed(() => this.store.filters().hide_details);

  /** Tooltip mode signal — 'hover' | 'click' | 'off' */
  readonly tooltipMode = computed(() => this.store.filters().tooltip_mode);
  /** Whether tooltip is fully disabled (off mode) — used for skipping rendering and hover handlers */
  readonly tooltipDisabled = computed(() => this.tooltipMode() === 'off');

  /** Show the hidden-photos banner when filters are hiding rows and at least one is on. */
  readonly showHiddenBanner = computed(() => {
    const f = this.store.filters();
    return this.store.hiddenSummary().total > 0
      && (f.hide_blinks || f.hide_bursts || f.hide_duplicates);
  });

  showAllHidden(): void {
    void this.store.updateFilters({
      hide_blinks: false,
      hide_bursts: false,
      hide_duplicates: false,
    });
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
      this.effectiveHideDetails(), !this.isDesktop(),
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
      this.setupResizeObserver();
      this.setupScrollTracking();
    });

    // Sync store.filterDrawerOpen signal → mat-sidenav
    effect(() => {
      const open = this.store.filterDrawerOpen();
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
  }

  async ngOnInit(): Promise<void> {
    if (this.tryRestoreView()) return;
    // Reset album state to avoid stale singleton data; loadConfig() resets filters from scratch
    this.store.currentAlbum.set(null);
    this.store.initializing.set(true);
    await this.store.loadConfig();
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
    await Promise.all([this.store.loadFilterOptions(), this.store.loadTypeCounts()]);
    await this.store.loadPhotos();
    this.store.initializing.set(false);
    // IntersectionObserver fires too early before DOM paint — defer recheck
    requestAnimationFrame(() => setTimeout(() => this.scrollDirective()?.recheck()));
    if (this.store.config()?.features?.show_albums) {
      firstValueFrom(this.albumService.list()).then(res =>
        this.albumOptions.set(res.albums.filter(a => !a.is_smart)),
      ).catch(() => {});
    }
  }

  ngOnDestroy(): void {
    this.saveViewSnapshot();
    this.resizeObserver?.disconnect();
    this.desktop.cleanup();
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
   * Restore the previous gallery view if the route + filters are unchanged.
   * Skips loadConfig/loadPhotos entirely; background data stays fresh via
   * loadTypeCounts/loadFilterOptions.
   */
  private tryRestoreView(): boolean {
    const snap = this.store.viewSnapshot();
    this.store.viewSnapshot.set(null);
    if (!snap || !this.store.photos().length) return false;
    if (snap.albumId !== this.route.snapshot.paramMap.get('albumId')) return false;
    if (snap.filterKey !== this.store.filterKey()) return false;
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
    this.store.setFilterDrawerOpen(open);
    const sidebarEl = document.querySelector('app-gallery-filter-sidebar div[data-scroll]') as HTMLElement | null;
    if (!sidebarEl) return;

    if (!open) {
      this.savedFilterScroll = sidebarEl.scrollTop;
    } else {
      queueMicrotask(() => { sidebarEl.scrollTop = this.savedFilterScroll; });
    }
  }

  protected toggleSelection(photo: Photo, event?: MouseEvent): void {
    this.store.toggleSelection(photo, event);
  }

  protected clearSelection(): void {
    this.store.clearSelection();
  }

  protected selectAll(): void {
    this.store.selectAllLoaded();
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

  protected copyPaths(): void {
    const filenames = [...this.selectedPaths()]
      .map(p => p.split(/[\\/]/).pop() ?? p)
      .join('\n');
    navigator.clipboard.writeText(filenames).then(() => {
      this.snackBar.open(this.i18n.t('gallery.selection.copied'), '', { duration: 2000 });
    });
  }

  /** Above this size, undo (chunked per-photo inverse calls) is not offered. */
  private static readonly UNDO_MAX_PHOTOS = 500;

  private async executeBatchAction(
    action: (paths: string[]) => Promise<Map<string, PhotoFlagSnapshot> | null>,
    i18nKey: string,
    extraParams?: Record<string, string | number>,
  ): Promise<void> {
    const paths = [...this.selectedPaths()];
    const snapshot = await action(paths);
    if (snapshot === null) return; // store reverted and notified
    this.clearSelection();
    const params = { count: paths.length, ...extraParams };
    if (snapshot.size > 0 && snapshot.size <= GalleryComponent.UNDO_MAX_PHOTOS) {
      this.undoService.register({
        labelKey: i18nKey,
        labelParams: params,
        undo: async () => {
          await this.store.restoreSnapshot(snapshot);
          this.store.restoreSelection(paths);
        },
      });
    } else {
      this.snackBar.open(this.i18n.t(i18nKey, params), '', { duration: 2000 });
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
      case 'copy': this.copyPaths(); break;
      case 'download': await this.downloadSelected(action.type, action.profile); break;
    }
  }

  protected async downloadSelected(type = 'original', profile?: string): Promise<void> {
    this.downloading.set(true);
    try {
      await downloadAll(
        [...this.selectedPaths()],
        path => this.api.downloadUrl(path, type, profile),
        url => this.api.getRaw(url),
      );
    } finally {
      this.downloading.set(false);
    }
  }

  async addToAlbum(albumId: number): Promise<void> {
    const paths = [...this.selectedPaths()];
    if (!paths.length) return;
    await firstValueFrom(this.albumService.addPhotos(albumId, paths));
    this.snackBar.open(this.i18n.t('albums.photos_added'), '', { duration: 2000 });
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
    this.dialog.open(ExportEditorDialogComponent, {
      width: '420px',
      data: albumId
        ? { albumId: +albumId }
        : { paths: [...this.selectedPaths()] },
    });
  }

  async openCullDialog(): Promise<void> {
    const paths = [...this.selectedPaths()];
    if (!paths.length) return;
    const { CullDialogComponent } = await import('./cull-dialog.component');
    const ref = this.dialog.open(CullDialogComponent, { width: '32rem', data: { paths } });
    const applied = await firstValueFrom(ref.afterClosed());
    if (applied) {
      this.clearSelection();
      await this.store.loadPhotos();
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
    const isLandscape = photo.image_width > photo.image_height;
    const vh = window.innerHeight;
    const vw = window.innerWidth;

    const thumbImg = (card.querySelector('img') as HTMLImageElement | null);
    const tnw = thumbImg?.naturalWidth || photo.image_width || 4;
    const tnh = thumbImg?.naturalHeight || photo.image_height || 3;
    const thumbAspect = tnw / tnh;
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
        title: this.i18n.t('manage_persons.remove_person_title'),
        message: this.i18n.t('manage_persons.confirm_remove_person'),
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

  /** Columns per row in grid mode (mirrors the CSS auto-fill column math). */
  private gridColumns(): number {
    if (!this.isDesktop()) return 1;
    const width = this.containerWidth() - 32;
    return gridColumnCount(width, this.cardWidth(), GalleryComponent.ROW_GAP);
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
    this.activeIndex.set(next);
    this.focusCard(next);
  }

  /** Rate-and-advance shortcuts on the focused card: 1-5 set stars, 0/X reject
   * (both auto-advance), F toggles favorite (stays put — a tag-like toggle).
   * Edition-only and gated on the rating-controls feature flag, mirroring the
   * card's own template guards. */
  private handleRatingKey(event: KeyboardEvent, photos: Photo[], index: number): void {
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
      this.activeIndex.set(next);
      this.focusCard(next);
    }
  }

  /** Focus a card by photo index; if windowed out of the DOM, scroll its row
   * into view first and retry once the window has rendered it. */
  private focusCard(index: number, retried = false): void {
    const host = document.querySelector(`[data-pidx="${index}"]`) as HTMLElement | null;
    if (host) {
      const focusable = (host.querySelector('[tabindex]') as HTMLElement | null) ?? host;
      focusable.focus();
      focusable.scrollIntoView({ block: 'nearest' });
      return;
    }
    if (retried || !this.virtualOn()) return;
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
