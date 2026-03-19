import { Component, inject, signal, effect, untracked, OnDestroy, afterNextRender } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { CapsuleFiltersService } from './capsule-filters.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { Photo } from '../../shared/models/photo.model';
import { SlideshowComponent } from '../gallery/slideshow.component';

interface Capsule {
  type: string;
  id: string;
  title: string;
  title_key: string;
  title_params: Record<string, string>;
  subtitle: string;
  cover_photo_path: string;
  photo_count: number;
  icon: string;
}

interface CapsulesResponse {
  capsules: Capsule[];
  total: number;
  page: number;
  per_page: number;
  has_more: boolean;
}

@Component({
  selector: 'app-capsules',
  standalone: true,
  host: { class: 'block px-4 pt-4 pb-4' },
  imports: [
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    MatSnackBarModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    InfiniteScrollDirective,
    SlideshowComponent,
  ],
  template: `
    @if (loading() && capsules().length === 0) {
      <div class="flex flex-col items-center justify-center py-16 gap-3">
        <mat-spinner diameter="48" />
        <p class="text-sm opacity-60">{{ 'capsules.loading' | translate }}</p>
      </div>
    }

    @if (capsules().length === 0 && !loading()) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">auto_stories</mat-icon>
        <p>{{ 'capsules.empty' | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      @for (capsule of capsules(); track capsule.id) {
        <div
          class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer text-left w-full"
          (click)="playCapsule(capsule)"
        >
          @if (capsule.cover_photo_path) {
            <div class="relative w-full aspect-[4/3] overflow-hidden">
              <img [src]="capsule.cover_photo_path | thumbnailUrl:320"
                   [alt]="capsule.title"
                   class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
              <div class="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent"></div>
              <div class="absolute bottom-2 right-2">
                <mat-icon class="!text-white opacity-0 group-hover:opacity-80 transition-opacity">play_circle</mat-icon>
              </div>
            </div>
          } @else {
            <div class="w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">{{ capsule.icon }}</mat-icon>
            </div>
          }
          <div class="p-3 flex items-start gap-1">
            <div class="flex-1 min-w-0">
              <div class="font-medium text-sm truncate">{{ capsule.title_key | translate:capsule.title_params }}</div>
              <div class="flex items-center gap-1 text-xs opacity-60">
                <mat-icon class="!text-xs !w-3 !h-3 !leading-3 inline-flex"
                          [matTooltip]="'capsules.type_' + capsule.type | translate">{{ capsule.icon }}</mat-icon>
                <span>{{ capsule.photo_count }}</span>
              </div>
            </div>
            @if (auth.isEdition()) {
              <button
                mat-icon-button
                class="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                [matTooltip]="'capsules.save_as_album' | translate"
                [disabled]="savingAlbum()"
                (click)="saveAsAlbumFromCard($event, capsule)"
              >
                <mat-icon class="opacity-60">playlist_add</mat-icon>
              </button>
            }
          </div>
        </div>
      }
    </div>

    <!-- Infinite scroll sentinel -->
    @if (hasMore()) {
      <div appInfiniteScroll (scrollReached)="loadMore()" class="flex justify-center py-8">
        @if (loading()) {
          <mat-spinner diameter="32" />
        }
      </div>
    }

    <!-- Slideshow overlay -->
    @if (slideshowActive()) {
      <app-slideshow
        [photos]="slideshowPhotos()"
        [hasMore]="false"
        [loading]="slideshowLoading()"
        [initialSlideIndex]="slideshowStartIndex()"
        [transitionType]="currentTransition()"
        (closed)="closeSlideshow()"
        (wrapped)="onSlideshowWrapped()"
        (slideIndexChanged)="onSlideIndexChanged($event)"
      />
    }

    <!-- Transition card between capsules -->
    @if (transitionVisible()) {
      <div class="fixed inset-0 z-[10000] bg-black flex items-center justify-center">
        <div class="text-center text-white animate-pulse">
          @if (nextCapsulePreview(); as next) {
            <mat-icon class="!text-5xl !w-12 !h-12 mb-4 opacity-60">{{ next.icon }}</mat-icon>
            <h2 class="text-2xl font-light mb-2">{{ next.title_key | translate:next.title_params }}</h2>
            <p class="text-sm opacity-60">{{ 'capsules.photos_count' | translate:{ count: next.photo_count } }}</p>
          }
        </div>
      </div>
    }
  `,
})
export class CapsulesComponent implements OnDestroy {
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly filters = inject(CapsuleFiltersService);

  protected readonly capsules = signal<Capsule[]>([]);
  protected readonly loading = signal(false);
  protected readonly hasMore = signal(false);
  protected readonly total = signal(0);

  protected readonly savingAlbum = signal(false);

  // Slideshow state
  protected readonly slideshowActive = signal(false);
  protected readonly slideshowPhotos = signal<Photo[]>([]);
  protected readonly slideshowLoading = signal(false);
  protected readonly transitionVisible = signal(false);
  protected readonly nextCapsulePreview = signal<Capsule | null>(null);
  protected readonly slideshowStartIndex = signal(0);
  protected readonly currentTransition = signal<string>('crossfade');

  private readonly typeTransitions: Record<string, string> = {
    journey: 'slide',
    location: 'slide',
    faces_of: 'zoom',
    golden: 'kenburns',
    seasonal: 'kenburns',
    color_story: 'blur',
    color_palette: 'blur',
    this_week: 'fade_black',
    progress: 'kenburns',
    star_rating: 'kenburns',
    favorites: 'kenburns',
    person_pair: 'zoom',
    rare_pair: 'flip',
  };

  // Per-capsule shuffle + resume state
  private capsuleShuffledPhotos = new Map<string, Photo[]>();
  private capsuleResumeIndex = new Map<string, number>();
  private currentPlayingCapsuleId = '';

  private shuffledOrder: Capsule[] = [];
  private currentCapsuleIndex = 0;
  private currentPage = 1;
  private readonly perPage = 24;
  private transitionTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;

  constructor() {
    afterNextRender(() => {
      this.loadCapsules();
    });
    // Watch for regenerate trigger from header button
    effect(() => {
      this.filters.regenerate();
      untracked(() => {
        if (this.capsules().length > 0) {
          this.currentPage = 1;
          this.loadCapsules(true);
        }
      });
    });
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.slideshowActive.set(false);
    this.clearTransitionTimer();
  }

  private async loadCapsules(refresh = false): Promise<void> {
    if (this.loading()) return;
    this.loading.set(true);
    try {
      const res = await firstValueFrom(
        this.api.get<CapsulesResponse>('/capsules', {
          page: this.currentPage,
          per_page: this.perPage,
          date_from: this.filters.dateFrom(),
          date_to: this.filters.dateTo(),
          ...(refresh ? { refresh: true } : {}),
        }),
      );
      const resolved = res.capsules.map(c => this.resolveParams(c));
      if (this.currentPage === 1) {
        this.capsules.set(resolved);
      } else {
        this.capsules.update(prev => [...prev, ...resolved]);
      }
      this.hasMore.set(res.has_more);
      this.total.set(res.total);
    } catch {
      if (this.currentPage === 1) this.capsules.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  protected loadMore(): void {
    if (this.loading() || !this.hasMore()) return;
    this.currentPage++;
    this.loadCapsules();
  }

  protected async playCapsule(capsule: Capsule): Promise<void> {
    // Shuffle capsule order for auto-chaining, starting with the selected one
    const all = [...this.capsules()];
    const idx = all.findIndex(c => c.id === capsule.id);
    const rest = [...all.slice(0, idx), ...all.slice(idx + 1)];
    this.shuffleArray(rest);
    this.shuffledOrder = [capsule, ...rest];
    this.currentCapsuleIndex = 0;

    await this.loadAndStartCapsule(capsule);
  }

  private async loadAndStartCapsule(capsule: Capsule): Promise<void> {
    this.currentPlayingCapsuleId = capsule.id;
    this.currentTransition.set(this.typeTransitions[capsule.type] || 'crossfade');
    this.slideshowLoading.set(true);
    this.slideshowActive.set(true);

    // Resume from cached shuffled photos if available
    const existing = this.capsuleShuffledPhotos.get(capsule.id);
    if (existing) {
      this.slideshowStartIndex.set(this.capsuleResumeIndex.get(capsule.id) ?? 0);
      this.slideshowPhotos.set(existing);
      this.slideshowLoading.set(false);
      return;
    }

    try {
      const res = await firstValueFrom(
        this.api.get<{ photos: Photo[]; capsule: Capsule }>(`/capsules/${capsule.id}/photos`),
      );
      if (this.destroyed) return;

      // Shuffle photos for playback variety
      const shuffled = [...res.photos];
      this.shuffleArray(shuffled);
      this.capsuleShuffledPhotos.set(capsule.id, shuffled);
      this.slideshowStartIndex.set(0);
      this.slideshowPhotos.set(shuffled);
    } catch {
      this.slideshowPhotos.set([]);
    } finally {
      this.slideshowLoading.set(false);
    }
  }

  protected async saveAsAlbumFromCard(event: Event, capsule: Capsule): Promise<void> {
    event.stopPropagation();
    if (this.savingAlbum()) return;
    this.savingAlbum.set(true);
    try {
      await firstValueFrom(
        this.api.post<{ album_id: number; name: string }>(`/capsules/${capsule.id}/save-album`),
      );
      this.snackBar.open(
        this.i18n.t('capsules.saved_as_album'),
        '', { duration: 3000, horizontalPosition: 'right', verticalPosition: 'bottom' },
      );
    } catch {
      this.snackBar.open(
        this.i18n.t('capsules.save_album_error'), '', { duration: 3000 },
      );
    } finally {
      this.savingAlbum.set(false);
    }
  }

  protected onSlideIndexChanged(index: number): void {
    if (this.currentPlayingCapsuleId) {
      this.capsuleResumeIndex.set(this.currentPlayingCapsuleId, index);
    }
  }

  protected closeSlideshow(): void {
    this.slideshowActive.set(false);
    this.slideshowPhotos.set([]);
    this.transitionVisible.set(false);
    this.clearTransitionTimer();
  }

  protected onSlideshowWrapped(): void {
    if (this.transitionVisible()) return;
    this.chainNextCapsule();
  }

  private async chainNextCapsule(): Promise<void> {
    this.currentCapsuleIndex++;
    if (this.currentCapsuleIndex >= this.shuffledOrder.length) {
      // All capsules played — stop instead of looping
      this.closeSlideshow();
      return;
    }

    const next = this.shuffledOrder[this.currentCapsuleIndex];

    // Show transition card
    this.slideshowActive.set(false);
    this.nextCapsulePreview.set(next);
    this.transitionVisible.set(true);

    await new Promise<void>(resolve => {
      this.transitionTimer = setTimeout(resolve, 2000);
    });

    if (this.destroyed) return;

    this.transitionVisible.set(false);
    this.nextCapsulePreview.set(null);

    // Load next capsule
    await this.loadAndStartCapsule(next);
  }

  private clearTransitionTimer(): void {
    if (this.transitionTimer !== null) {
      clearTimeout(this.transitionTimer);
      this.transitionTimer = null;
    }
  }

  /** Resolve i18n-dependent title params (e.g. translate season names). */
  private resolveParams(capsule: Capsule): Capsule {
    if ((capsule.type === 'seasonal' || capsule.type === 'favorites') && capsule.title_params['season']) {
      const seasonKey = 'capsules.season_' + capsule.title_params['season'];
      return {
        ...capsule,
        title_params: {
          ...capsule.title_params,
          season: this.i18n.t(seasonKey),
        },
      };
    }
    return capsule;
  }

  private shuffleArray<T>(arr: T[]): void {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
  }
}
