import {
  Component,
  ElementRef,
  OnDestroy,
  inject,
  input,
  signal,
  computed,
  afterNextRender,
  viewChild,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { GalleryStore } from './gallery.store';
import { Photo } from '../../shared/models/photo.model';
import { ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

interface Slide {
  photos: Photo[];
}

@Component({
  selector: 'app-slideshow',
  imports: [
    MatIconModule,
    MatButtonModule,
    MatSliderModule,
    MatTooltipModule,
    ImageUrlPipe,
    TranslatePipe,
  ],
  template: `
    <div
      #slideshowContainer
      class="fixed inset-0 z-[9999] bg-black flex flex-col select-none"
      [class.cursor-none]="!controlsVisible()"
      (mousemove)="showControls()"
      (click)="showControls()"
    >
      <!-- Top bar -->
      <div
        class="absolute top-0 left-0 right-0 flex items-center justify-between py-2 px-3 z-30 bg-gradient-to-b from-black/70 to-transparent transition-opacity duration-300"
        [class.opacity-0]="!controlsVisible()"
        [class.pointer-events-none]="!controlsVisible()"
        (click)="$event.stopPropagation()"
        (mousemove)="$event.stopPropagation()"
      >
        @if (photoCounter(); as c) {
          <span class="text-white text-sm opacity-70">
            @if (c.start === c.end) { {{ c.start }} } @else { {{ c.start }}-{{ c.end }} }
            / {{ c.total }}
          </span>
        }
        <button mat-icon-button (click)="close()" [matTooltip]="'slideshow.close' | translate">
          <mat-icon class="!text-white">close</mat-icon>
        </button>
      </div>

      <!-- Image area -->
      <div class="flex-1 overflow-hidden relative">
        <!-- Layer A -->
        <div
          class="absolute inset-0 flex gap-0.5"
          style="transition: opacity 300ms ease"
          [style.opacity]="layerAOpacity()"
          [style.z-index]="frontLayer() === 'a' ? 1 : 0"
        >
          @if (layerASlide(); as slide) {
            @for (photo of slide.photos; track photo.path) {
              <img
                [src]="photo.path | imageUrl"
                [alt]="photo.filename"
                class="flex-1 min-w-0 h-full object-cover"
              />
            }
          }
        </div>

        <!-- Layer B -->
        <div
          class="absolute inset-0 flex gap-0.5"
          style="transition: opacity 300ms ease"
          [style.opacity]="layerBOpacity()"
          [style.z-index]="frontLayer() === 'b' ? 1 : 0"
        >
          @if (layerBSlide(); as slide) {
            @for (photo of slide.photos; track photo.path) {
              <img
                [src]="photo.path | imageUrl"
                [alt]="photo.filename"
                class="flex-1 min-w-0 h-full object-cover"
              />
            }
          }
        </div>

        <!-- Left arrow -->
        <button
          mat-icon-button
          class="absolute left-2 top-1/2 -translate-y-1/2 z-20 !bg-black/40 hover:!bg-black/70 transition-opacity duration-300"
          [class.opacity-0]="!controlsVisible()"
          [class.pointer-events-none]="!controlsVisible()"
          (click)="prev()"
          [matTooltip]="'slideshow.prev' | translate"
        >
          <mat-icon class="!text-white">chevron_left</mat-icon>
        </button>

        <!-- Right arrow -->
        <button
          mat-icon-button
          class="absolute right-2 top-1/2 -translate-y-1/2 z-20 !bg-black/40 hover:!bg-black/70 transition-opacity duration-300"
          [class.opacity-0]="!controlsVisible()"
          [class.pointer-events-none]="!controlsVisible()"
          (click)="next()"
          [matTooltip]="'slideshow.next' | translate"
        >
          <mat-icon class="!text-white">chevron_right</mat-icon>
        </button>
      </div>

      <!-- Bottom bar -->
      <div
        class="absolute bottom-0 left-0 right-0 z-30 bg-black/70 px-4 py-3 transition-opacity duration-300"
        [class.opacity-0]="!controlsVisible()"
        [class.pointer-events-none]="!controlsVisible()"
        (click)="$event.stopPropagation()"
        (mousemove)="$event.stopPropagation()"
      >
        <!-- Progress bar -->
        <div class="h-0.5 bg-white/20 rounded-full overflow-hidden mb-3">
          <div class="h-full bg-white" [style.width.%]="progress()"></div>
        </div>
        <div class="flex items-center gap-3">
          <button
            mat-icon-button
            (click)="togglePlay()"
            [matTooltip]="(isPlaying() ? 'slideshow.pause' : 'slideshow.play') | translate"
          >
            <mat-icon class="!text-white">{{ isPlaying() ? 'pause' : 'play_arrow' }}</mat-icon>
          </button>
          <mat-slider min="1" max="15" step="1" class="flex-1" [matTooltip]="'slideshow.duration_label' | translate">
            <input matSliderThumb [value]="duration()" (valueChange)="onDurationChange($event)" />
          </mat-slider>
          <span class="text-white text-xs opacity-70 shrink-0 w-8 text-right">{{ duration() }}s</span>
          @if (currentSlide(); as slide) {
            @if (slide.photos.length === 1) {
              <span class="text-white text-sm truncate max-w-xs opacity-80">{{ slide.photos[0].filename }}</span>
            }
          }
          <button
            mat-icon-button
            (click)="toggleFullscreen()"
            [matTooltip]="'slideshow.fullscreen' | translate"
          >
            <mat-icon class="!text-white">{{ isFullscreen() ? 'fullscreen_exit' : 'fullscreen' }}</mat-icon>
          </button>
        </div>
      </div>
    </div>
  `,
})
export class SlideshowComponent implements OnDestroy {
  private store = inject(GalleryStore);

  readonly photos = input<Photo[]>([]);
  readonly hasMore = input<boolean>(false);
  readonly loading = input<boolean>(false);

  private readonly container = viewChild.required<ElementRef<HTMLElement>>('slideshowContainer');

  // Viewport dimensions for adaptive grouping
  private readonly viewportWidth = signal(typeof window !== 'undefined' ? window.innerWidth : 1920);
  private readonly viewportHeight = signal(typeof window !== 'undefined' ? window.innerHeight : 1080);

  // Slide grouping
  private readonly maxPortraitsPerSlide = computed(() => {
    const ar = this.viewportWidth() / this.viewportHeight();
    return Math.max(1, Math.min(3, Math.round(ar / (2 / 3))));
  });

  readonly slides = computed<Slide[]>(() => {
    const photos = this.photos();
    const max = this.maxPortraitsPerSlide();
    const result: Slide[] = [];
    const buf: Photo[] = [];

    for (const p of photos) {
      const isPortrait = p.image_width && p.image_height && p.image_height > p.image_width;
      if (isPortrait) {
        buf.push(p);
        if (buf.length >= max) {
          result.push({ photos: buf.splice(0, max) });
        }
      } else {
        result.push({ photos: [p] });
      }
    }

    // Flush remaining buffered portraits
    while (buf.length >= 2) {
      result.push({ photos: buf.splice(0, Math.min(buf.length, max)) });
    }
    if (buf.length === 1) {
      result.push({ photos: [buf[0]] });
    }

    return result;
  });

  readonly currentSlideIndex = signal(0);
  readonly currentSlide = computed(() => this.slides()[this.currentSlideIndex()] ?? null);

  /** Photo range for the current slide (1-based). */
  readonly photoCounter = computed(() => {
    const slides = this.slides();
    const idx = this.currentSlideIndex();
    let start = 0;
    for (let i = 0; i < idx && i < slides.length; i++) {
      start += slides[i].photos.length;
    }
    const count = slides[idx]?.photos.length ?? 0;
    return { start: start + 1, end: start + count, total: this.photos().length };
  });

  // Two-layer crossfade
  readonly layerASlide = signal<Slide | null>(null);
  readonly layerBSlide = signal<Slide | null>(null);
  readonly layerAOpacity = signal(1);
  readonly layerBOpacity = signal(0);
  readonly frontLayer = signal<'a' | 'b'>('a');

  // Playback state
  readonly isPlaying = signal(true);
  readonly duration = signal(4);

  /** Effective duration = base duration * number of photos in current slide. */
  readonly slideDuration = computed(() => {
    const count = this.currentSlide()?.photos.length ?? 1;
    return this.duration() * count;
  });
  readonly progress = signal(0);
  readonly controlsVisible = signal(true);
  readonly isFullscreen = signal(false);

  private intervalId: ReturnType<typeof setInterval> | null = null;
  private hideControlsTimer: ReturnType<typeof setTimeout> | null = null;
  private crossfadeTimer: ReturnType<typeof setTimeout> | null = null;
  private boundKeyHandler!: (e: KeyboardEvent) => void;
  private boundFullscreenHandler!: () => void;
  private boundResizeHandler!: () => void;

  constructor() {
    afterNextRender(() => {
      // Show first slide immediately in layer A
      const firstSlide = this.slides()[0];
      if (firstSlide) {
        this.layerASlide.set(firstSlide);
        this.layerAOpacity.set(1);
        this.frontLayer.set('a');
      }

      this.boundKeyHandler = (e: KeyboardEvent) => this.onKeyDown(e);
      window.addEventListener('keydown', this.boundKeyHandler);

      this.boundFullscreenHandler = () => this.isFullscreen.set(!!document.fullscreenElement);
      document.addEventListener('fullscreenchange', this.boundFullscreenHandler);

      this.boundResizeHandler = () => {
        this.viewportWidth.set(window.innerWidth);
        this.viewportHeight.set(window.innerHeight);
      };
      window.addEventListener('resize', this.boundResizeHandler);

      this.startInterval();
      this.scheduleHideControls();
    });
  }

  ngOnDestroy(): void {
    this.clearTimerInterval();
    this.clearHideControlsTimer();
    if (this.crossfadeTimer) {
      clearTimeout(this.crossfadeTimer);
    }
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
    if (this.boundKeyHandler) {
      window.removeEventListener('keydown', this.boundKeyHandler);
    }
    if (this.boundFullscreenHandler) {
      document.removeEventListener('fullscreenchange', this.boundFullscreenHandler);
    }
    if (this.boundResizeHandler) {
      window.removeEventListener('resize', this.boundResizeHandler);
    }
  }

  showControls(): void {
    this.controlsVisible.set(true);
    this.scheduleHideControls();
  }

  togglePlay(): void {
    const playing = !this.isPlaying();
    this.isPlaying.set(playing);
    if (playing) {
      this.startInterval();
    } else {
      this.clearTimerInterval();
    }
  }

  next(): void {
    this.clearTimerInterval();
    this.progress.set(0);
    const nextIdx = this.nextSlideIndex();
    if (nextIdx >= 0) {
      this.preloadAndAdvance(nextIdx);
    } else {
      this.waitForMoreSlides();
    }
  }

  prev(): void {
    this.clearTimerInterval();
    this.progress.set(0);
    const slides = this.slides();
    const idx = this.currentSlideIndex() === 0 ? Math.max(0, slides.length - 1) : this.currentSlideIndex() - 1;
    this.preloadAndAdvance(idx);
  }

  close(): void {
    this.store.slideshowActive.set(false);
  }

  toggleFullscreen(): void {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      this.container().nativeElement.requestFullscreen();
    }
  }

  onDurationChange(value: number): void {
    this.duration.set(value);
    this.progress.set(0);
    if (this.isPlaying()) {
      this.clearTimerInterval();
      this.startInterval();
    }
  }

  /** Returns next slide index, or -1 when waiting for more data to load. */
  private nextSlideIndex(): number {
    const slides = this.slides();
    let idx = this.currentSlideIndex() + 1;
    if (idx >= slides.length - 5 && this.hasMore() && !this.loading()) {
      this.store.nextPage();
    }
    if (idx >= slides.length) {
      if (this.hasMore()) return -1;
      idx = 0;
    }
    return idx;
  }

  private preloadAndAdvance(slideIndex: number): void {
    const slide = this.slides()[slideIndex];
    if (!slide) {
      this.currentSlideIndex.set(slideIndex);
      if (this.isPlaying()) this.startInterval();
      return;
    }

    // Preload all images in the slide
    const preloadPromises = slide.photos.map(
      (photo) =>
        new Promise<void>((resolve) => {
          const img = new Image();
          img.onload = () => resolve();
          img.onerror = () => resolve();
          img.src = `/image?${new URLSearchParams({ path: photo.path })}`;
        }),
    );

    Promise.all(preloadPromises).then(() => {
      this.currentSlideIndex.set(slideIndex);
      this.crossfadeTo(slide).then(() => {
        if (this.isPlaying()) this.startInterval();
      });
    });
  }

  private crossfadeTo(slide: Slide): Promise<void> {
    // Cancel any in-progress crossfade
    if (this.crossfadeTimer) {
      clearTimeout(this.crossfadeTimer);
      this.crossfadeTimer = null;
    }

    return new Promise<void>((resolve) => {
      const isAFront = this.frontLayer() === 'a';
      const standbySlide = isAFront ? this.layerBSlide : this.layerASlide;
      const standbyOpacity = isAFront ? this.layerBOpacity : this.layerAOpacity;
      const activeOpacity = isAFront ? this.layerAOpacity : this.layerBOpacity;
      const newFront: 'a' | 'b' = isAFront ? 'b' : 'a';

      // Load slide into standby layer (invisible)
      standbySlide.set(slide);
      standbyOpacity.set(0);
      this.frontLayer.set(newFront);

      // Wait for DOM paint, then fade in
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          standbyOpacity.set(1);
          this.crossfadeTimer = setTimeout(() => {
            activeOpacity.set(0);
            this.crossfadeTimer = null;
            resolve();
          }, 300);
        });
      });
    });
  }

  private startInterval(): void {
    this.clearTimerInterval();
    this.progress.set(0);
    this.intervalId = setInterval(() => {
      const tickIncrement = 100 / (this.slideDuration() * 10);
      const newProgress = this.progress() + tickIncrement;
      if (newProgress >= 100) {
        this.progress.set(100);
        this.clearTimerInterval();
        const nextIdx = this.nextSlideIndex();
        if (nextIdx >= 0) {
          this.preloadAndAdvance(nextIdx);
        } else {
          this.waitForMoreSlides();
        }
      } else {
        this.progress.set(newProgress);
      }
    }, 100);
  }

  /** Poll until new slides appear from a loading next page. */
  private waitForMoreSlides(): void {
    this.clearTimerInterval();
    this.intervalId = setInterval(() => {
      const slides = this.slides();
      const nextIdx = this.currentSlideIndex() + 1;
      if (nextIdx < slides.length) {
        this.clearTimerInterval();
        this.progress.set(0);
        this.preloadAndAdvance(nextIdx);
      } else if (!this.hasMore()) {
        // No more data — wrap to beginning
        this.clearTimerInterval();
        this.progress.set(0);
        this.preloadAndAdvance(0);
      }
    }, 200);
  }

  private clearTimerInterval(): void {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  private scheduleHideControls(delay = 2000): void {
    this.clearHideControlsTimer();
    this.hideControlsTimer = setTimeout(() => this.controlsVisible.set(false), delay);
  }

  private clearHideControlsTimer(): void {
    if (this.hideControlsTimer !== null) {
      clearTimeout(this.hideControlsTimer);
      this.hideControlsTimer = null;
    }
  }

  private onKeyDown(e: KeyboardEvent): void {
    switch (e.key) {
      case ' ':
        e.preventDefault();
        this.togglePlay();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        this.prev();
        break;
      case 'ArrowRight':
        e.preventDefault();
        this.next();
        break;
      case 'f':
      case 'F':
        e.preventDefault();
        this.toggleFullscreen();
        break;
      case 'Escape':
        this.close();
        break;
    }
  }
}
