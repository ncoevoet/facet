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
} from '@angular/core';
import { MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { GalleryStore } from './gallery.store';
import { Photo } from '../../shared/models/photo.model';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { SlideshowComponent } from './slideshow.component';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { PhotoCardComponent } from '../../shared/components/photo-card/photo-card.component';
import { AlbumService, Album } from '../../core/services/album.service';
import { CreateAlbumDialogComponent } from '../albums/create-album-dialog.component';
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
    TranslatePipe,
    MatSnackBarModule,
    PhotoTooltipComponent,
    SlideshowComponent,
    GalleryFilterSidebarComponent,
    PhotoCardComponent,
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
        <!-- Photo grid / mosaic -->
        @if (store.photos().length) {
          @if (effectiveGalleryMode() === 'grid') {
            <div
              class="grid grid-cols-1 gap-2 p-2 md:p-4 gallery-grid"
              [style.--gallery-cols]="'repeat(auto-fill, minmax(' + cardWidth() + 'px, 1fr))'"
            >
              @for (photo of store.photos(); track photo.path) {
                <app-photo-card
                  [photo]="photo"
                  [config]="store.config()"
                  [isSelected]="selectedPaths().has(photo.path)"
                  [hideDetails]="effectiveHideDetails()"
                  [currentSort]="store.filters().sort"
                  [thumbSize]="thumbSize()"
                  [isEditionMode]="auth.isEdition()"
                  [personFilterId]="store.filters().person_id"
                  (selectionChange)="toggleSelection($event.photo, $event.event)"
                  (tooltipShow)="showTooltip($event.event, $event.photo)"
                  (tooltipHide)="hideTooltip()"
                  (tagClicked)="store.updateFilter('tag', $event)"
                  (personFilterClicked)="filterByPerson($event)"
                  (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                  (openSimilarClicked)="openSimilar($event.photo, $event.mode)"
                  (openCritiqueClicked)="openCritique($event)"
                  (openAddPersonClicked)="openAddPerson($event)"
                  (favoriteToggled)="store.toggleFavorite($event)"
                  (rejectedToggled)="store.toggleRejected($event)"
                  (starClicked)="store.setRating($event.photo.path, $event.star)"
                  (doubleClicked)="downloadPhoto($event)"
                />
              }
            </div>
          } @else {
            <div class="flex flex-col gap-2 p-2 md:p-4">
              @for (row of mosaicRows(); track $index) {
                <div class="flex gap-2">
                  @for (photo of row.photos; track photo.path; let i = $index) {
                    <app-photo-card
                      [photo]="photo"
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
                      (selectionChange)="toggleSelection($event.photo, $event.event)"
                      (tooltipShow)="showTooltip($event.event, $event.photo)"
                      (tooltipHide)="hideTooltip()"
                      (tagClicked)="store.updateFilter('tag', $event)"
                      (personFilterClicked)="filterByPerson($event)"
                      (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                      (openSimilarClicked)="openSimilar($event.photo, $event.mode)"
                      (openCritiqueClicked)="openCritique($event)"
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

        <!-- Loading spinner -->
        @if (store.loading()) {
          <div class="flex justify-center p-8">
            <mat-spinner diameter="40"></mat-spinner>
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
            }
          </div>
        }

        <!-- Infinite scroll sentinel -->
        <div appInfiniteScroll (scrollReached)="onScrollReached()" class="h-1"></div>
      </mat-sidenav-content>
    </mat-sidenav-container>

    <!-- Slideshow overlay -->
    @if (store.slideshowActive()) {
      <app-slideshow
        [photos]="store.photos()"
        [hasMore]="store.hasMore()"
        [loading]="store.loading()"
      />
    }

    <!-- Photo details tooltip (single instance, repositioned on hover, hidden on small/touch devices) -->
    @if (!isTouchDevice() && isDesktop() && !effectiveHideTooltip()) {
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
          @if (auth.isEdition()) {
            <button mat-icon-button class="lg:!hidden" (click)="batchFavorite()" [matTooltip]="'gallery.selection.favorite' | translate"><mat-icon>favorite</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="batchFavorite()"><mat-icon>favorite</mat-icon> {{ 'gallery.selection.favorite' | translate }}</button>
            <button mat-icon-button class="lg:!hidden" (click)="batchReject()" [matTooltip]="'gallery.selection.reject' | translate"><mat-icon>thumb_down</mat-icon></button>
            <button mat-button class="!hidden lg:!inline-flex" (click)="batchReject()"><mat-icon>thumb_down</mat-icon> {{ 'gallery.selection.reject' | translate }}</button>
            <button mat-icon-button class="lg:!hidden" [matMenuTriggerFor]="rateMenu" [matTooltip]="'gallery.selection.rate' | translate"><mat-icon>star</mat-icon></button>
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
          @if (store.config()?.features?.show_albums) {
            <button mat-icon-button class="lg:!hidden" [matMenuTriggerFor]="albumMenu" [matTooltip]="'albums.add_photos' | translate"><mat-icon>photo_library</mat-icon></button>
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
          <button mat-icon-button class="lg:!hidden" (click)="copyPaths()" [matTooltip]="'gallery.selection.copy_filenames' | translate"><mat-icon>content_copy</mat-icon></button>
          <button mat-button class="!hidden lg:!inline-flex" (click)="copyPaths()"><mat-icon>content_copy</mat-icon> {{ 'gallery.selection.copy_filenames' | translate }}</button>
          <button mat-icon-button class="lg:!hidden" (click)="downloadSelected()" [matTooltip]="'gallery.selection.download' | translate"><mat-icon>download</mat-icon></button>
          <button mat-flat-button class="!hidden lg:!inline-flex" (click)="downloadSelected()"><mat-icon>download</mat-icon> {{ 'gallery.selection.download' | translate }}</button>
        </div>
      </div>
    }
  `,
  host: { class: 'block h-full' },
})
export class GalleryComponent implements OnInit, OnDestroy {
  protected readonly store = inject(GalleryStore);
  protected readonly auth = inject(AuthService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialog);
  private readonly albumService = inject(AlbumService);
  private readonly photoActions = inject(PhotoActionsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  // Album options for "Add to album" menu
  protected readonly albumOptions = signal<Album[]>([]);

  private resizeObserver: ResizeObserver | null = null;
  private readonly scrollDirective = viewChild(InfiniteScrollDirective);
  private readonly filterDrawer = viewChild<MatSidenav>('filterDrawer');

  // Sidebar scroll preservation
  private savedFilterScroll = 0;

  // Tooltip state
  protected readonly tooltipPhoto = signal<Photo | null>(null);
  protected readonly tooltipX = signal(0);
  protected readonly tooltipY = signal(0);
  protected readonly tooltipFlipped = signal(false);

  // Selection state
  protected readonly selectedPaths = signal<Set<string>>(new Set());
  protected readonly selectionCount = computed(() => this.selectedPaths().size);
  private lastSelectedIndex = -1;

  /** True when the device has no hover capability (touch device) */
  protected readonly isTouchDevice = signal(false);

  /** Thumbnail request size derived from card width (2x for retina, capped at 640). Returns 640 on mobile (full-width cards). */
  readonly thumbSize = computed(() => {
    if (this.isTouchDevice()) return 640;
    return Math.min(this.store.cardWidth() * 2, 640);
  });

  /** Card min-width from store for the responsive grid */
  readonly cardWidth = computed(() => this.store.cardWidth() || 168);

  /** Whether the viewport is md+ (768px) — mosaic is only available on desktop */
  protected readonly isDesktop = signal(false);

  /** Effective gallery mode: force grid on small viewports */
  readonly effectiveGalleryMode = computed(() =>
    (this.isDesktop() && this.containerWidth() > 0) ? this.store.galleryMode() : 'grid',
  );

  /** Whether to hide photo details below the thumbnails */
  readonly effectiveHideDetails = computed(() => this.store.filters().hide_details);

  /** Cached hide_tooltip signal — avoids re-reading store.filters() per card in @for */
  readonly effectiveHideTooltip = computed(() => this.store.filters().hide_tooltip);

  /** Container width for mosaic layout (updated via ResizeObserver) */
  protected readonly containerWidth = signal(0);

  /** Mosaic row layout: justified rows of photos preserving aspect ratios */
  readonly mosaicRows = computed(() => {
    const photos = this.store.photos();
    const width = this.containerWidth();
    const targetHeight = this.store.cardWidth() || 168;
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
        // Finalize this row
        const widths = rowAspects.map(a => Math.floor(a * rowHeight));
        // Distribute rounding remainder to last photo
        const usedWidth = widths.reduce((a, b) => a + b, 0) + (widths.length - 1) * gap;
        widths[widths.length - 1] += width - usedWidth;
        rows.push({ photos: [...rowPhotos], widths, height: Math.floor(rowHeight) });
        rowPhotos = [];
        rowAspects = [];
      }
    }

    // Last incomplete row: use target height, left-aligned
    if (rowPhotos.length) {
      const widths = rowAspects.map(a => Math.floor(a * targetHeight));
      rows.push({ photos: [...rowPhotos], widths, height: targetHeight });
    }

    return rows;
  });

  private isBrowser = false;
  private desktopMql: MediaQueryList | null = null;
  private desktopMqlHandler: ((e: MediaQueryListEvent) => void) | null = null;

  constructor() {
    afterNextRender(() => {
      this.isBrowser = true;
      this.isTouchDevice.set(window.matchMedia('(hover: none)').matches);

      const mql = window.matchMedia('(min-width: 768px)');
      this.isDesktop.set(mql.matches);
      this.desktopMql = mql;
      this.desktopMqlHandler = (e: MediaQueryListEvent) => {
        this.isDesktop.set(e.matches);
        if (!e.matches) this.tooltipPhoto.set(null);
      };
      mql.addEventListener('change', this.desktopMqlHandler);

      this.setupResizeObserver();
    });

    // Sync store.filterDrawerOpen signal → mat-sidenav
    effect(() => {
      const open = this.store.filterDrawerOpen();
      const drawer = this.filterDrawer();
      if (!drawer) return;
      if (open) drawer.open();
      else drawer.close();
    });

    // Re-check sentinel whenever photos, card width, or gallery mode change
    effect(() => {
      this.store.photos(); // track dependency
      this.store.cardWidth(); // track dependency
      this.store.galleryMode(); // track dependency
      this.scrollDirective()?.recheck();
      // Clear tooltip when photos change (prevents stale tooltips after filter changes)
      untracked(() => this.tooltipPhoto.set(null));
    });
  }

  async ngOnInit(): Promise<void> {
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
    this.scrollDirective()?.recheck();
    if (this.store.config()?.features?.show_albums) {
      firstValueFrom(this.albumService.list()).then(res =>
        this.albumOptions.set(res.albums.filter(a => !a.is_smart)),
      ).catch(() => {});
    }
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    if (this.desktopMql && this.desktopMqlHandler) {
      this.desktopMql.removeEventListener('change', this.desktopMqlHandler);
    }
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
    const photos = this.store.photos();
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
  }

  protected copyPaths(): void {
    const filenames = [...this.selectedPaths()]
      .map(p => p.split(/[\\/]/).pop() ?? p)
      .join('\n');
    navigator.clipboard.writeText(filenames).then(() => {
      this.snackBar.open(this.i18n.t('gallery.selection.copied'), '', { duration: 2000 });
    });
  }

  private async executeBatchAction(
    action: (paths: string[]) => Promise<void>,
    i18nKey: string,
    extraParams?: Record<string, unknown>,
  ): Promise<void> {
    const paths = [...this.selectedPaths()];
    await action(paths);
    this.clearSelection();
    this.snackBar.open(this.i18n.t(i18nKey, { count: paths.length, ...extraParams }), '', { duration: 2000 });
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

  private triggerDownload(path: string): void {
    const a = document.createElement('a');
    a.href = `/api/download?path=${encodeURIComponent(path)}`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  protected downloadPhoto(photo: Photo): void {
    this.router.navigate(['/photo'], {
      queryParams: { path: photo.path },
      state: { photo },
    });
  }

  protected async downloadSelected(): Promise<void> {
    const paths = [...this.selectedPaths()];
    for (const path of paths) {
      this.triggerDownload(path);
      if (paths.length > 1) {
        await new Promise(resolve => setTimeout(resolve, 300));
      }
    }
  }

  async addToAlbum(albumId: number): Promise<void> {
    const paths = [...this.selectedPaths()];
    if (!paths.length) return;
    await firstValueFrom(this.albumService.addPhotos(albumId, paths));
    this.snackBar.open(this.i18n.t('albums.photos_added'), '', { duration: 2000 });
    this.clearSelection();
  }

  createAlbumAndAdd(): void {
    const ref = this.dialog.open(CreateAlbumDialogComponent, { width: '400px' });
    ref.afterClosed().subscribe(async (album: Album | undefined) => {
      if (!album) return;
      this.albumOptions.update(list => [album, ...list]);
      await this.addToAlbum(album.id);
    });
  }

  openCritique(photo: Photo): void {
    this.photoActions.openCritique(photo);
  }

  showTooltip(event: MouseEvent, photo: Photo): void {
    if (this.isTouchDevice() || this.effectiveHideTooltip()) return;
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

  removePerson(photo: Photo, personId: number): void {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t('manage_persons.remove_person_title'),
        message: this.i18n.t('manage_persons.confirm_remove_person'),
      },
    });
    ref.afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.store.unassignPerson(photo.path, personId);
      }
    });
  }

  filterByPerson(personId: number): void {
    this.store.updateFilter('person_id', String(personId));
  }

  private setupResizeObserver(): void {
    this.resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        this.containerWidth.set(Math.floor(entry.contentRect.width));
      }
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
}
