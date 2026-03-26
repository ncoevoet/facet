import {
  Component,
  ElementRef,
  OnDestroy,
  WritableSignal,
  inject,
  input,
  output,
  signal,
  computed,
  effect,
  untracked,
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
      class="fixed inset-0 z-[9999] bg-black overflow-hidden select-none"
      [class.cursor-none]="!controlsVisible()"
      (mousemove)="showControls()"
      (click)="showControls()"
    >
      <div
        [class]="autoRotate() ? 'flex flex-col absolute top-1/2 left-1/2' : 'flex flex-col w-full h-full'"
        [style.width]="autoRotate() ? '100vh' : '100%'"
        [style.height]="autoRotate() ? '100vw' : '100%'"
        [style.transform]="autoRotate() ? 'translate(-50%, -50%) rotate(90deg)' : 'none'"
        style="transition: transform 300ms ease, width 300ms ease, height 300ms ease"
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
          class="absolute inset-0 flex gap-0.5 overflow-hidden"
          [style.transition]="layerATransition()"
          [style.opacity]="layerAOpacity()"
          [style.transform]="layerATransform()"
          [style.filter]="layerAFilter()"
          [style.z-index]="frontLayer() === 'a' ? 1 : 0"
        >
          @if (layerASlide(); as slide) {
            @for (photo of slide.photos; track photo.path; let i = $index) {
              <div class="flex-1 min-w-0 h-full overflow-hidden">
                <img
                  [src]="photo.path | imageUrl"
                  [alt]="photo.filename"
                  class="w-full h-full object-cover"
                  [style.transform]="layerAImgTransforms()[i]"
                  [style.transition]="layerAImgTransitions()[i]"
                  (error)="onImageError($event, photo.path)"
                />
              </div>
            }
          }
        </div>

        <!-- Layer B -->
        <div
          class="absolute inset-0 flex gap-0.5 overflow-hidden"
          [style.transition]="layerBTransition()"
          [style.opacity]="layerBOpacity()"
          [style.transform]="layerBTransform()"
          [style.filter]="layerBFilter()"
          [style.z-index]="frontLayer() === 'b' ? 1 : 0"
        >
          @if (layerBSlide(); as slide) {
            @for (photo of slide.photos; track photo.path; let i = $index) {
              <div class="flex-1 min-w-0 h-full overflow-hidden">
                <img
                  [src]="photo.path | imageUrl"
                  [alt]="photo.filename"
                  class="w-full h-full object-cover"
                  [style.transform]="layerBImgTransforms()[i]"
                  [style.transition]="layerBImgTransitions()[i]"
                  (error)="onImageError($event, photo.path)"
                />
              </div>
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
    </div>
  `,
})
export class SlideshowComponent implements OnDestroy {
  private store = inject(GalleryStore);

  readonly photos = input<Photo[]>([]);
  readonly hasMore = input<boolean>(false);
  readonly loading = input<boolean>(false);
  readonly initialSlideIndex = input<number>(0);
  readonly transitionType = input<string>('crossfade');

  /** Emitted when the slideshow requests closing. */
  readonly closed = output<void>();
  /** Emitted when the slideshow wraps around (all slides exhausted). */
  readonly wrapped = output<void>();
  /** Emitted when the current slide index changes (for resume tracking). */
  readonly slideIndexChanged = output<number>();

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

  /** Rotate the entire slideshow UI when a landscape photo is shown on a portrait viewport. */
  readonly autoRotate = computed(() => {
    const slide = this.currentSlide();
    if (!slide || slide.photos.length !== 1) return false;
    const photo = slide.photos[0];
    if (!photo.image_width || !photo.image_height) return false;
    const isPhotoLandscape = photo.image_width > photo.image_height;
    const isViewportPortrait = this.viewportHeight() > this.viewportWidth();
    return isPhotoLandscape && isViewportPortrait;
  });

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

  // Two-layer crossfade + transitions
  readonly layerASlide = signal<Slide | null>(null);
  readonly layerBSlide = signal<Slide | null>(null);
  readonly layerAOpacity = signal(1);
  readonly layerBOpacity = signal(0);
  readonly layerATransform = signal('none');
  readonly layerBTransform = signal('none');
  readonly layerATransition = signal('opacity 300ms ease');
  readonly layerBTransition = signal('opacity 300ms ease');
  readonly layerAFilter = signal('none');
  readonly layerBFilter = signal('none');
  readonly frontLayer = signal<'a' | 'b'>('a');

  // Per-image Ken Burns transforms (independent motion per image)
  readonly layerAImgTransforms = signal<string[]>([]);
  readonly layerBImgTransforms = signal<string[]>([]);
  readonly layerAImgTransitions = signal<string[]>([]);
  readonly layerBImgTransitions = signal<string[]>([]);

  private readonly kenBurnsPatterns: Array<{ start: string; end: string }> = [
    // Zoom in + pan variations
    { start: 'scale(1.0)', end: 'scale(1.06) translate(1.5%, 0.8%)' },
    { start: 'scale(1.0)', end: 'scale(1.06) translate(-1.5%, -0.8%)' },
    { start: 'scale(1.0)', end: 'scale(1.06) translate(-1.5%, 0.8%)' },
    { start: 'scale(1.0)', end: 'scale(1.06) translate(1.5%, -0.8%)' },
    // Zoom out + pan variations (start is set before crossfade while layer is invisible)
    { start: 'scale(1.06) translate(1.5%, 0.8%)', end: 'scale(1.0)' },
    { start: 'scale(1.06) translate(-1.5%, -0.8%)', end: 'scale(1.0)' },
    { start: 'scale(1.06) translate(0%, 1.5%)', end: 'scale(1.0)' },
    { start: 'scale(1.06) translate(0%, -1.5%)', end: 'scale(1.0)' },
  ];
  private kenBurnsPatternIndex = 0;

  /** True when the user prefers reduced motion (WCAG 2.2). */
  private readonly prefersReducedMotion = signal(
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );

  /** Compute the animated transition CSS for the current transitionType. */
  private getAnimateTransition(): string {
    if (this.prefersReducedMotion()) return 'opacity 150ms ease';
    switch (this.transitionType()) {
      case 'slide': return 'transform 500ms ease, opacity 300ms ease';
      case 'zoom': return 'transform 500ms ease, opacity 400ms ease';
      case 'kenburns': return 'opacity 300ms ease';
      case 'fade_black': return 'opacity 400ms ease';
      case 'blur': return 'filter 400ms ease, opacity 400ms ease';
      case 'flip': return 'transform 500ms ease, opacity 250ms ease';
      default: return 'opacity 300ms ease';
    }
  }

  /** Duration in ms for the active part of the transition. */
  private getTransitionDuration(): number {
    if (this.prefersReducedMotion()) return 150;
    switch (this.transitionType()) {
      case 'slide': case 'flip': return 500;
      case 'zoom': case 'fade_black': case 'blur': return 400;
      default: return 300;
    }
  }

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
  private boundOrientationHandler!: () => void;

  /** Track the previous maxPortraitsPerSlide to detect regrouping. */
  private prevMaxPortraits = 0;

  constructor() {
    // Watch for slides to become available (handles async photo loading)
    effect(() => {
      const slides = this.slides();
      if (slides.length > 0 && !untracked(() => this.layerASlide()) && !untracked(() => this.layerBSlide())) {
        const startIdx = untracked(() => this.initialSlideIndex());
        const idx = startIdx < slides.length ? startIdx : 0;
        const slide = slides[idx];
        untracked(() => this.currentSlideIndex.set(idx));
        this.layerASlide.set(slide);
        this.layerAOpacity.set(1);
        this.frontLayer.set('a');
      }
    });

    // Re-sync displayed slide when orientation/resize causes regrouping
    effect(() => {
      const max = this.maxPortraitsPerSlide();
      const slides = this.slides();
      const prev = this.prevMaxPortraits;
      this.prevMaxPortraits = max;

      // Skip initial run (prev === 0) or if grouping didn't change
      if (prev === 0 || prev === max || slides.length === 0) return;

      untracked(() => {
        // Find which photo was at the start of the current slide
        const frontLayer = this.frontLayer();
        const currentSlide = frontLayer === 'a' ? this.layerASlide() : this.layerBSlide();
        if (!currentSlide?.photos.length) return;

        const firstPath = currentSlide.photos[0].path;

        // Find the new slide containing that photo
        let newIdx = 0;
        for (let i = 0; i < slides.length; i++) {
          if (slides[i].photos.some(p => p.path === firstPath)) {
            newIdx = i;
            break;
          }
        }

        const newSlide = slides[newIdx];
        if (!newSlide) return;

        // Update instantly (no transition)
        this.currentSlideIndex.set(newIdx);
        const activeSlide = frontLayer === 'a' ? this.layerASlide : this.layerBSlide;
        activeSlide.set(newSlide);
      });
    });

    afterNextRender(() => {
      // Show initial slide immediately in layer A (if already available)
      const slides = this.slides();
      const startIdx = this.initialSlideIndex();
      const idx = startIdx < slides.length ? startIdx : 0;
      const slide = slides[idx];
      if (slide) {
        this.currentSlideIndex.set(idx);
        this.layerASlide.set(slide);
        this.layerAOpacity.set(1);
        this.frontLayer.set('a');
        const kbPatterns = this.pickKenBurnsPatterns(slide.photos.length);
        this.initKenBurns(this.layerAImgTransforms, this.layerAImgTransitions, kbPatterns);
        this.animateKenBurns(this.layerAImgTransforms, this.layerAImgTransitions, kbPatterns);
      }

      this.boundKeyHandler = (e: KeyboardEvent) => this.onKeyDown(e);
      window.addEventListener('keydown', this.boundKeyHandler);

      this.boundFullscreenHandler = () => this.isFullscreen.set(!!document.fullscreenElement);
      document.addEventListener('fullscreenchange', this.boundFullscreenHandler);

      // Read fresh dimensions now that DOM is ready
      this.updateViewportDimensions();

      this.boundResizeHandler = () => this.updateViewportDimensions();
      window.addEventListener('resize', this.boundResizeHandler);

      // orientationchange fires on mobile when device is rotated
      // (resize may not fire, or may fire with stale innerWidth/Height)
      this.boundOrientationHandler = () => {
        // Delay read — dimensions aren't updated until after the event
        setTimeout(() => this.updateViewportDimensions(), 100);
      };
      screen.orientation?.addEventListener('change', this.boundOrientationHandler);

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
    if (this.kenburnsTimer) {
      clearTimeout(this.kenburnsTimer);
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
    if (this.boundOrientationHandler) {
      screen.orientation?.removeEventListener('change', this.boundOrientationHandler);
    }
  }

  private updateViewportDimensions(): void {
    this.viewportWidth.set(window.innerWidth);
    this.viewportHeight.set(window.innerHeight);
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
    this.closed.emit();
    this.store.slideshowActive.set(false);
  }

  toggleFullscreen(): void {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      this.container().nativeElement.requestFullscreen().then(() => {
        // Unlock orientation so device rotation works in fullscreen
        screen.orientation?.unlock?.();
      }).catch(() => {});
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

    // Preload all images in the slide (waits for full image to be browser-cached)
    const preloadPromises = slide.photos.map(
      (photo) =>
        new Promise<void>((resolve) => {
          const img = new Image();
          img.onload = () => resolve();
          img.onerror = () => {
            // Full image failed — preload thumbnail as fallback
            const thumb = new Image();
            thumb.onload = () => resolve();
            thumb.onerror = () => resolve();
            thumb.src = `/thumbnail?${new URLSearchParams({ path: photo.path })}`;
          };
          img.src = `/image?${new URLSearchParams({ path: photo.path })}`;
        }),
    );

    Promise.all(preloadPromises).then(() => {
      this.currentSlideIndex.set(slideIndex);
      this.slideIndexChanged.emit(slideIndex);
      this.crossfadeTo(slide).then(() => {
        if (this.isPlaying()) this.startInterval();
      });
    });
  }

  /** Pick N Ken Burns patterns from the cycle (one per image in the slide). */
  private pickKenBurnsPatterns(count: number): Array<{ start: string; end: string }> {
    const result: Array<{ start: string; end: string }> = [];
    for (let i = 0; i < count; i++) {
      result.push(this.kenBurnsPatterns[this.kenBurnsPatternIndex % this.kenBurnsPatterns.length]);
      this.kenBurnsPatternIndex++;
    }
    return result;
  }

  /** Set Ken Burns start positions instantly (no transition). */
  private initKenBurns(
    imgTransforms: WritableSignal<string[]>,
    imgTransitions: WritableSignal<string[]>,
    patterns: Array<{ start: string; end: string }>,
  ): void {
    imgTransitions.set(patterns.map(() => 'none'));
    imgTransforms.set(patterns.map(p => p.start));
  }

  /** Animate Ken Burns from current position to end position. */
  private animateKenBurns(
    imgTransforms: WritableSignal<string[]>,
    imgTransitions: WritableSignal<string[]>,
    patterns: Array<{ start: string; end: string }>,
  ): void {
    if (this.prefersReducedMotion()) return;
    if (this.kenburnsTimer) clearTimeout(this.kenburnsTimer);
    const dur = this.slideDuration();
    imgTransitions.set(patterns.map(() => `transform ${dur}s ease-out`));
    this.kenburnsTimer = setTimeout(() => {
      imgTransforms.set(patterns.map(p => p.end));
    }, 50);
  }

  private crossfadeTo(slide: Slide): Promise<void> {
    // Cancel any in-progress crossfade and reset to clean state
    if (this.crossfadeTimer) {
      clearTimeout(this.crossfadeTimer);
      this.crossfadeTimer = null;
    }
    if (this.kenburnsTimer) {
      clearTimeout(this.kenburnsTimer);
      this.kenburnsTimer = null;
    }

    return new Promise<void>((resolve) => {
      const isAFront = this.frontLayer() === 'a';
      const standbySlide = isAFront ? this.layerBSlide : this.layerASlide;
      const standbyOpacity = isAFront ? this.layerBOpacity : this.layerAOpacity;
      const standbyTransform = isAFront ? this.layerBTransform : this.layerATransform;
      const standbyTransition = isAFront ? this.layerBTransition : this.layerATransition;
      const standbyFilter = isAFront ? this.layerBFilter : this.layerAFilter;
      const activeOpacity = isAFront ? this.layerAOpacity : this.layerBOpacity;
      const activeTransform = isAFront ? this.layerATransform : this.layerBTransform;
      const activeTransition = isAFront ? this.layerATransition : this.layerBTransition;
      const activeFilter = isAFront ? this.layerAFilter : this.layerBFilter;
      const standbyImgTransforms = isAFront ? this.layerBImgTransforms : this.layerAImgTransforms;
      const standbyImgTransitions = isAFront ? this.layerBImgTransitions : this.layerAImgTransitions;
      const activeImgTransforms = isAFront ? this.layerAImgTransforms : this.layerBImgTransforms;
      const activeImgTransitions = isAFront ? this.layerAImgTransitions : this.layerBImgTransitions;
      const newFront: 'a' | 'b' = isAFront ? 'b' : 'a';

      const transition = this.transitionType();
      const animateCSS = this.getAnimateTransition();
      const duration = this.getTransitionDuration();

      // 1. Disable transition on standby so positioning is instant (no flash)
      standbyTransition.set('none');
      standbyOpacity.set(0);
      standbyFilter.set('none');

      // Position standby layer for entry
      switch (transition) {
        case 'slide':   standbyTransform.set('translateX(100%)'); break;
        case 'zoom':    standbyTransform.set('scale(1.05)'); break;
        case 'flip':    standbyTransform.set('perspective(1200px) rotateY(-90deg)'); break;
        default:        standbyTransform.set('none'); break;
      }

      // Load slide into standby layer (still invisible, still behind)
      standbySlide.set(slide);

      // Set Ken Burns start positions on images (invisible — layer at opacity 0)
      const kbPatterns = this.pickKenBurnsPatterns(slide.photos.length);
      this.initKenBurns(standbyImgTransforms, standbyImgTransitions, kbPatterns);

      // 2. Wait one frame for DOM to paint the new content, then animate
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          // Now bring standby to front and enable transitions
          this.frontLayer.set(newFront);
          standbyTransition.set(animateCSS);
          activeTransition.set(animateCSS);

          // Animate standby in
          standbyOpacity.set(1);
          standbyFilter.set('none');

          switch (transition) {
            case 'slide':
              standbyTransform.set('translateX(0)');
              activeTransform.set('translateX(-100%)');
              break;
            case 'zoom':
              standbyTransform.set('scale(1.0)');
              break;
            case 'flip':
              standbyTransform.set('perspective(1200px) rotateY(0deg)');
              activeTransform.set('perspective(1200px) rotateY(90deg)');
              break;
            case 'fade_black':
              // Active fades out first, then standby fades in
              activeOpacity.set(0);
              break;
            case 'blur':
              activeFilter.set('blur(12px)');
              activeOpacity.set(0);
              break;
          }

          this.crossfadeTimer = setTimeout(() => {
            // Clean up active layer
            activeOpacity.set(0);
            activeTransition.set('none');
            activeTransform.set('none');
            activeFilter.set('none');
            activeImgTransitions.set([]);
            activeImgTransforms.set([]);
            this.crossfadeTimer = null;

            // Start per-image Ken Burns zoom+pan on the new front layer
            this.animateKenBurns(standbyImgTransforms, standbyImgTransitions, kbPatterns);

            resolve();
          }, duration);
        });
      });
    });
  }

  private kenburnsTimer: ReturnType<typeof setTimeout> | null = null;

  private startInterval(): void {
    this.clearTimerInterval();
    this.progress.set(0);
    this.intervalId = setInterval(() => {
      const tickIncrement = 100 / (this.slideDuration() * 10);
      const newProgress = this.progress() + tickIncrement;
      if (newProgress >= 100) {
        this.progress.set(100);
        this.clearTimerInterval();
        const prevIdx = this.currentSlideIndex();
        const nextIdx = this.nextSlideIndex();
        // Emit wrapped only on auto-advance (not manual next/prev)
        if (nextIdx === 0 && prevIdx > 0) {
          this.wrapped.emit();
        }
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
    // Ensure next page is requested (covers edge case where nextSlideIndex() skipped it)
    if (this.hasMore() && !this.loading()) {
      this.store.nextPage();
    }
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
      } else if (!this.loading()) {
        // Retry if previous request failed or was not triggered
        this.store.nextPage();
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

  /** Fallback to thumbnail when full image fails to load (e.g. RAW without rawpy). */
  onImageError(event: Event, path: string): void {
    const img = event.target as HTMLImageElement;
    const thumbUrl = `/thumbnail?${new URLSearchParams({ path })}`;
    if (!img.src.includes('/thumbnail?')) {
      img.src = thumbUrl;
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
