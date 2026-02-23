import {
  Component,
  inject,
  computed,
  signal,
  OnInit,
  OnDestroy,
  ElementRef,
  viewChild,
  afterNextRender,
  effect,
} from '@angular/core';
import { MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { GalleryStore } from './gallery.store';
import { Photo } from '../../shared/models/photo.model';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { FaceSelectorDialogComponent } from './face-selector-dialog.component';
import { PersonSelectorDialogComponent } from './person-selector-dialog.component';
import { SimilarPhotosDialogComponent } from './similar-photos-dialog.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { SlideshowComponent } from './slideshow.component';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { PhotoCardComponent } from '../../shared/components/photo-card/photo-card.component';

@Component({
  selector: 'app-gallery',
  imports: [
    MatSidenavModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatButtonModule,
    MatDialogModule,
    TranslatePipe,
    MatSnackBarModule,
    PhotoTooltipComponent,
    SlideshowComponent,
    GalleryFilterSidebarComponent,
    PhotoCardComponent,
  ],
  template: `
    <mat-sidenav-container class="h-full">
      <!-- Filter sidebar -->
      <mat-sidenav #filterDrawer disableClose="false" mode="side" position="end" class="w-[min(320px,100vw)] p-0"
        (openedChange)="onFilterDrawerChange($event)">
        <app-gallery-filter-sidebar />
      </mat-sidenav>

      <!-- Main content -->
      <mat-sidenav-content>
        <!-- Photo grid -->
        @if (store.photos().length) {
          <div
            class="grid grid-cols-1 gap-2 p-2 md:p-4 gallery-grid"
            [style.--gallery-cols]="'repeat(auto-fill, minmax(' + cardWidth() + 'px, 1fr))'"
          >
            @for (photo of store.photos(); track photo.path) {
              <app-photo-card
                [photo]="photo"
                [config]="store.config()"
                [isSelected]="selectedPaths().has(photo.path)"
                [hideDetails]="store.filters().hide_details"
                [currentSort]="store.filters().sort"
                [thumbSize]="thumbSize()"
                [isEditionMode]="auth.isEdition()"
                [hoverStar]="hoverStars()[photo.path]"
                [personFilterId]="store.filters().person_id"
                (selectionChange)="toggleSelection($event)"
                (tooltipShow)="showTooltip($event.event, $event.photo)"
                (tooltipHide)="hideTooltip(); clearHoverStar(photo.path)"
                (tagClicked)="store.updateFilter('tag', $event)"
                (personFilterClicked)="filterByPerson($event)"
                (personRemoveClicked)="removePerson($event.photo, $event.personId)"
                (openSimilarClicked)="openSimilar($event)"
                (openAddPersonClicked)="openAddPerson($event)"
                (favoriteToggled)="store.toggleFavorite($event)"
                (rejectedToggled)="store.toggleRejected($event)"
                (starHoverChanged)="$event.star !== null ? setHoverStar($event.path, $event.star) : clearHoverStar($event.path)"
                (starClicked)="onStarClick($event.photo, $event.star)"
              />
            }
          </div>
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
        <div #scrollSentinel class="h-1"></div>
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

    <!-- Photo details tooltip (single instance, repositioned on hover, hidden on touch devices) -->
    @if (!isTouchDevice()) {
      <app-photo-tooltip
        [photo]="tooltipPhoto()"
        [x]="tooltipX()"
        [y]="tooltipY()"
      />
    }

    <!-- Selection action bar -->
    @if (selectionCount()) {
      <div class="fixed bottom-14 lg:bottom-0 left-0 right-0 z-50 flex flex-col lg:flex-row items-center justify-center gap-2 lg:gap-3 px-4 lg:px-6 py-2 lg:py-3 bg-[var(--mat-sys-surface-container-high)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
        <span class="text-sm font-medium">{{ 'gallery.selection.count' | translate:{ count: selectionCount() } }}</span>
        <div class="flex items-center gap-2">
          <button mat-button (click)="clearSelection()">
            <mat-icon>close</mat-icon>
            {{ 'gallery.selection.clear' | translate }}
          </button>
          <button mat-button (click)="copyPaths()">
            <mat-icon>content_copy</mat-icon>
            {{ 'gallery.selection.copy_filenames' | translate }}
          </button>
          <button mat-flat-button (click)="downloadSelected()">
            <mat-icon>download</mat-icon>
            {{ 'gallery.selection.download' | translate }}
          </button>
        </div>
      </div>
    }
  `,
  host: { class: 'block h-full' },
})
export class GalleryComponent implements OnInit, OnDestroy {
  store = inject(GalleryStore);
  api = inject(ApiService);
  auth = inject(AuthService);
  private snackBar = inject(MatSnackBar);
  private i18n = inject(I18nService);
  private dialog = inject(MatDialog);

  private observer: IntersectionObserver | null = null;
  readonly scrollSentinel = viewChild<ElementRef<HTMLDivElement>>('scrollSentinel');
  private readonly filterDrawer = viewChild<MatSidenav>('filterDrawer');

  // Sidebar state preservation
  private savedFilterScroll = 0;
  private savedDetailStates: boolean[] = [];

  // Tooltip state
  readonly tooltipPhoto = signal<Photo | null>(null);
  readonly tooltipX = signal(0);
  readonly tooltipY = signal(0);

  // Selection state
  readonly selectedPaths = signal<Set<string>>(new Set());
  readonly selectionCount = computed(() => this.selectedPaths().size);

  /** True when the device has no hover capability (touch device) */
  readonly isTouchDevice = signal(false);

  /** Thumbnail request size derived from config (2x for retina, capped at 640). Returns 640 on mobile (full-width cards). */
  readonly thumbSize = computed(() => {
    if (this.isTouchDevice()) return 640;
    const imgWidth = this.store.config()?.display?.image_width_px ?? 160;
    return Math.min(imgWidth * 2, 640);
  });

  /** Card min-width from config for the responsive grid */
  readonly cardWidth = computed(() => {
    return this.store.config()?.display?.card_width_px ?? 168;
  });

  private isBrowser = false;

  constructor() {
    afterNextRender(() => {
      this.isBrowser = true;
      this.isTouchDevice.set(window.matchMedia('(hover: none)').matches);
      this.setupIntersectionObserver();
    });

    // Sync store.filterDrawerOpen signal → mat-sidenav
    effect(() => {
      const open = this.store.filterDrawerOpen();
      const drawer = this.filterDrawer();
      if (!drawer) return;
      if (open) drawer.open();
      else drawer.close();
    });

    // Re-check sentinel whenever photos change (filter change, page load, etc.)
    effect(() => {
      this.store.photos(); // track dependency
      this.recheckSentinel();
    });
  }

  async ngOnInit(): Promise<void> {
    await this.store.loadConfig();
    await Promise.all([this.store.loadFilterOptions(), this.store.loadTypeCounts()]);
    await this.store.loadPhotos();
    this.recheckSentinel();
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }

  /** Save/restore sidebar state on drawer open/close */
  onFilterDrawerChange(open: boolean): void {
    this.store.filterDrawerOpen.set(open);
    // The sidebar manages its own scroll area via filterScrollArea viewChild
    // We hook a sidebar element via DOM query after open since the sidebar is a child component
    const sidebarEl = document.querySelector('app-gallery-filter-sidebar div[data-scroll]') as HTMLElement | null;
    if (!sidebarEl) return;

    if (!open) {
      this.savedFilterScroll = sidebarEl.scrollTop;
      this.savedDetailStates = Array.from(sidebarEl.querySelectorAll('details')).map(d => d.open);
    } else {
      queueMicrotask(() => {
        const details = sidebarEl.querySelectorAll('details');
        this.savedDetailStates.forEach((wasOpen, i) => {
          if (details[i]) details[i].open = wasOpen;
        });
        sidebarEl.scrollTop = this.savedFilterScroll;
      });
    }
  }

  toggleSelection(photo: Photo): void {
    const current = this.selectedPaths();
    const next = new Set(current);
    if (next.has(photo.path)) {
      next.delete(photo.path);
    } else {
      next.add(photo.path);
    }
    this.selectedPaths.set(next);
  }

  clearSelection(): void {
    this.selectedPaths.set(new Set());
  }

  copyPaths(): void {
    const filenames = [...this.selectedPaths()]
      .map(p => p.split(/[\\/]/).pop() ?? p)
      .join('\n');
    navigator.clipboard.writeText(filenames).then(() => {
      this.snackBar.open(this.i18n.t('gallery.selection.copied'), '', { duration: 2000 });
    });
  }

  async downloadSelected(): Promise<void> {
    const paths = [...this.selectedPaths()];
    for (const path of paths) {
      const url = `/api/download?path=${encodeURIComponent(path)}`;
      const a = document.createElement('a');
      a.href = url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      if (paths.length > 1) {
        await new Promise(resolve => setTimeout(resolve, 300));
      }
    }
  }

  showTooltip(event: MouseEvent, photo: Photo): void {
    if (this.isTouchDevice()) return;
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
      tooltipHeight = Math.ceil(imgH) + 140;
    } else {
      const imgH = Math.min(tooltipNatH, vh * 0.5);
      const imgW = imgH * thumbAspect;
      tooltipWidth = Math.ceil(imgW) + 260 + 12 + 24;
      tooltipHeight = Math.max(Math.ceil(imgH), 300) + 24;
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

    this.tooltipX.set(x);
    this.tooltipY.set(y);
    this.tooltipPhoto.set(photo);

    setTimeout(() => {
      if (this.tooltipPhoto() !== photo) return;
      const el = document.querySelector('app-photo-tooltip > div') as HTMLElement | null;
      if (!el) return;
      const { width: actualWidth } = el.getBoundingClientRect();
      const wouldOverflowRightActual = rect.right + padding + actualWidth > vw - padding;
      const newX = wouldOverflowRightActual
        ? rect.left - actualWidth - padding
        : rect.right + padding;
      if (Math.abs(newX - this.tooltipX()) > 1) this.tooltipX.set(newX);
    }, 0);
  }

  hideTooltip(): void {
    this.tooltipPhoto.set(null);
  }

  // --- Hover star state ---
  readonly hoverStars = signal<Record<string, number | null>>({});

  setHoverStar(path: string, star: number): void {
    this.hoverStars.update(s => ({ ...s, [path]: star }));
  }

  clearHoverStar(path: string): void {
    this.hoverStars.update(s => {
      const next = { ...s };
      delete next[path];
      return next;
    });
  }

  onStarClick(photo: Photo, star: number): void {
    const newRating = photo.star_rating === star ? 0 : star;
    this.store.setRating(photo.path, newRating);
  }

  // --- Card action handlers ---

  openSimilar(photo: Photo): void {
    this.dialog.open(SimilarPhotosDialogComponent, {
      data: {
        photoPath: photo.path,
        selectedPaths: this.selectedPaths,
        togglePath: (path: string) => {
          const next = new Set(this.selectedPaths());
          if (next.has(path)) next.delete(path); else next.add(path);
          this.selectedPaths.set(next);
        },
      },
      width: '95vw',
      maxWidth: '640px',
    });
  }

  openAddPerson(photo: Photo): void {
    const faceRef = this.dialog.open(FaceSelectorDialogComponent, {
      data: { photoPath: photo.path },
      width: '95vw',
      maxWidth: '400px',
    });
    faceRef.afterClosed().subscribe(face => {
      if (!face) return;
      const persons = this.store.persons().filter(p => p.name);
      const personRef = this.dialog.open(PersonSelectorDialogComponent, {
        data: persons,
        width: '95vw',
        maxWidth: '400px',
      });
      personRef.afterClosed().subscribe(async selected => {
        if (selected) {
          await this.store.assignFace(face.id, selected.id, photo.path, selected.name);
          this.snackBar.open(this.i18n.t('notifications.faces_assigned'), '', { duration: 2000 });
        }
      });
    });
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

  private setupIntersectionObserver(): void {
    const sentinel = this.scrollSentinel();
    if (!sentinel) return;

    this.observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting && this.store.hasMore() && !this.store.loading()) {
          this.store.nextPage().then(() => this.recheckSentinel());
        }
      },
      { rootMargin: '200px' },
    );
    this.observer.observe(sentinel.nativeElement);
  }

  /** Re-observe sentinel to trigger another load if it's still visible after content change */
  private recheckSentinel(): void {
    if (!this.isBrowser || !this.observer) return;
    const sentinel = this.scrollSentinel();
    if (!sentinel) return;
    this.observer.unobserve(sentinel.nativeElement);
    this.observer.observe(sentinel.nativeElement);
  }
}
