import {
  Component,
  OnDestroy,
  inject,
  input,
  signal,
  computed,
  afterNextRender,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { GalleryStore } from './gallery.store';
import { Photo } from '../../shared/models/photo.model';
import { ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

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
    <div class="fixed inset-0 z-[9999] bg-black flex flex-col select-none">
      <!-- Top bar -->
      <div class="absolute top-0 left-0 right-0 flex items-center justify-between py-2 px-3 z-10 bg-gradient-to-b from-black/70 to-transparent">
        <button mat-icon-button (click)="close()" [matTooltip]="'slideshow.close' | translate">
          <mat-icon class="!text-white">close</mat-icon>
        </button>
        <span class="text-white text-sm opacity-70">{{ currentIndex() + 1 }} / {{ photos().length }}</span>
      </div>

      <!-- Image area -->
      <div class="flex-1 flex items-center justify-center overflow-hidden relative">
        @if (currentPhoto(); as photo) {
          <img
            [src]="photo.path | imageUrl"
            [alt]="photo.filename"
            class="max-w-full max-h-full object-contain"
          />
        }

        <!-- Left arrow -->
        <button
          mat-icon-button
          class="absolute left-2 top-1/2 -translate-y-1/2 !bg-black/40 hover:!bg-black/70"
          (click)="prev()"
          [matTooltip]="'slideshow.prev' | translate"
        >
          <mat-icon class="!text-white">chevron_left</mat-icon>
        </button>

        <!-- Right arrow -->
        <button
          mat-icon-button
          class="absolute right-2 top-1/2 -translate-y-1/2 !bg-black/40 hover:!bg-black/70"
          (click)="next()"
          [matTooltip]="'slideshow.next' | translate"
        >
          <mat-icon class="!text-white">chevron_right</mat-icon>
        </button>
      </div>

      <!-- Bottom bar -->
      <div class="absolute bottom-0 left-0 right-0 bg-black/70 px-4 py-3">
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
          @if (currentPhoto(); as photo) {
            <span class="text-white text-sm truncate max-w-xs opacity-80">{{ photo.filename }}</span>
          }
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

  readonly currentIndex = signal(0);
  readonly isPlaying = signal(true);
  readonly duration = signal(4);
  readonly progress = signal(0);

  readonly currentPhoto = computed(() => {
    const photos = this.photos();
    return photos[this.currentIndex()] ?? null;
  });

  private intervalId: ReturnType<typeof setInterval> | null = null;
  private boundKeyHandler!: (e: KeyboardEvent) => void;

  constructor() {
    afterNextRender(() => {
      this.boundKeyHandler = (e: KeyboardEvent) => this.onKeyDown(e);
      window.addEventListener('keydown', this.boundKeyHandler);
      this.startInterval();
    });
  }

  ngOnDestroy(): void {
    this.clearTimerInterval();
    if (this.boundKeyHandler) {
      window.removeEventListener('keydown', this.boundKeyHandler);
    }
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
    this.advanceNext();
    if (this.isPlaying()) this.startInterval();
  }

  prev(): void {
    this.clearTimerInterval();
    this.progress.set(0);
    const photos = this.photos();
    const idx = this.currentIndex() === 0 ? Math.max(0, photos.length - 1) : this.currentIndex() - 1;
    this.currentIndex.set(idx);
    if (this.isPlaying()) this.startInterval();
  }

  close(): void {
    this.store.slideshowActive.set(false);
  }

  onDurationChange(value: number): void {
    this.duration.set(value);
    this.progress.set(0);
    if (this.isPlaying()) {
      this.clearTimerInterval();
      this.startInterval();
    }
  }

  private advanceNext(): void {
    const photos = this.photos();
    let idx = this.currentIndex() + 1;
    if (idx >= photos.length - 5 && this.hasMore() && !this.loading()) {
      this.store.nextPage();
    }
    if (idx >= photos.length) {
      idx = 0;
    }
    this.currentIndex.set(idx);
  }

  private startInterval(): void {
    this.clearTimerInterval();
    this.intervalId = setInterval(() => {
      const tickIncrement = 100 / (this.duration() * 10);
      const newProgress = this.progress() + tickIncrement;
      if (newProgress >= 100) {
        this.progress.set(0);
        this.advanceNext();
      } else {
        this.progress.set(newProgress);
      }
    }, 100);
  }

  private clearTimerInterval(): void {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId);
      this.intervalId = null;
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
      case 'Escape':
        this.close();
        break;
    }
  }
}
