import { NgClass } from '@angular/common';
import { Component, inject, signal, Signal, OnInit, OnDestroy, ElementRef, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSliderModule } from '@angular/material/slider';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

interface SimilarPhoto {
  path: string;
  filename: string;
  similarity: number;
  aggregate: number | null;
  aesthetic: number | null;
  date_taken: string | null;
}

interface DialogData {
  photoPath: string;
  selectedPaths: Signal<Set<string>>;
  togglePath: (path: string) => void;
}

@Component({
  selector: 'app-similar-photos-dialog',
  imports: [
    NgClass,
    MatButtonModule,
    MatDialogModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSliderModule,
    ThumbnailUrlPipe,
    FixedPipe,
    TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title>{{ 'similar.title' | translate }}</h2>
    <div class="flex items-center gap-3 px-6 pb-3 border-b border-neutral-800">
      <span class="text-sm text-neutral-400 shrink-0">{{ 'similar.min_similarity' | translate }}</span>
      <mat-slider class="grow" [min]="0" [max]="90" [step]="5" [discrete]="true">
        <input matSliderThumb [value]="minSimilarity()" (valueChange)="onSimilarityChange($event)" />
      </mat-slider>
      <span class="text-sm font-medium w-10 text-right">{{ minSimilarity() }}%</span>
    </div>
    <mat-dialog-content class="!flex !flex-col gap-3 min-h-[200px]">
      @if (loading()) {
        <div class="flex items-center justify-center gap-3 py-8">
          <mat-spinner diameter="24"></mat-spinner>
          <span class="text-sm text-neutral-400">{{ 'similar.loading' | translate }}</span>
        </div>
      } @else if (!results().length) {
        <p class="text-sm text-neutral-500 text-center py-8">{{ 'similar.no_results' | translate }}</p>
      } @else {
        <div class="grid grid-cols-3 gap-2">
          @for (photo of results(); track photo.path) {
            @let selected = data.selectedPaths().has(photo.path);
            <div class="relative rounded-lg overflow-hidden bg-neutral-900 cursor-pointer"
                 [ngClass]="selected ? 'ring-2 ring-[var(--mat-sys-primary)]' : ''"
                 (click)="data.togglePath(photo.path)">
              <img [src]="photo.path | thumbnailUrl:320"
                   [alt]="photo.filename"
                   class="w-full aspect-square object-cover" />
              @if (selected) {
                <div class="absolute top-1.5 right-1.5 rounded-full bg-[var(--mat-sys-primary)] w-5 h-5 flex items-center justify-center">
                  <mat-icon class="!text-sm !leading-none !w-4 !h-4 text-white">check</mat-icon>
                </div>
              }
              <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5">
                <div class="text-xs text-white truncate">{{ photo.filename }}</div>
                <div class="flex items-center gap-2 text-[11px]">
                  <span class="text-green-400 font-medium">{{ (photo.similarity * 100) | fixed:0 }}% {{ 'similar.similarity' | translate }}</span>
                  @if (photo.aggregate != null) {
                    <span class="text-neutral-400">{{ photo.aggregate | fixed:1 }}</span>
                  }
                </div>
              </div>
            </div>
          }
          @if (loadingMore()) {
            <div class="col-span-3 flex justify-center py-4">
              <mat-spinner diameter="20"></mat-spinner>
            </div>
          }
          <div #scrollSentinel class="h-1 col-span-3"></div>
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close()">{{ 'dialog.cancel' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class SimilarPhotosDialogComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  readonly data: DialogData = inject(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<SimilarPhotosDialogComponent>);

  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly results = signal<SimilarPhoto[]>([]);
  readonly minSimilarity = signal(70);

  private offset = 0;
  private readonly perPage = 20;
  private allLoaded = false;
  private observer: IntersectionObserver | null = null;

  readonly scrollSentinel = viewChild<ElementRef<HTMLElement>>('scrollSentinel');

  async ngOnInit(): Promise<void> {
    await this.loadMore();
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }

  async loadMore(): Promise<void> {
    if (this.loadingMore() || this.allLoaded) return;
    const isInitial = this.offset === 0;
    if (!isInitial) this.loadingMore.set(true);
    try {
      const res = await firstValueFrom(
        this.api.get<{ similar: SimilarPhoto[]; total: number; has_more: boolean }>(
          `/similar_photos/${encodeURIComponent(this.data.photoPath)}`,
          { limit: this.perPage, offset: this.offset, min_similarity: this.minSimilarity() / 100 },
        ),
      );
      const batch = res.similar ?? [];
      this.results.update((prev) => [...prev, ...batch]);
      this.offset += batch.length;
      if (!res.has_more || batch.length === 0) this.allLoaded = true;
    } catch {
      this.allLoaded = true;
    } finally {
      if (isInitial) {
        this.loading.set(false);
        setTimeout(() => this.setupInfiniteScroll(), 0);
      } else {
        this.loadingMore.set(false);
      }
    }
  }

  onSimilarityChange(value: number): void {
    this.minSimilarity.set(value);
    this.observer?.disconnect();
    this.observer = null;
    this.offset = 0;
    this.allLoaded = false;
    this.results.set([]);
    this.loading.set(true);
    this.loadMore();
  }

  private setupInfiniteScroll(): void {
    const sentinel = this.scrollSentinel();
    if (!sentinel) return;
    const root = sentinel.nativeElement.closest('mat-dialog-content') as HTMLElement | null;
    this.observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !this.loadingMore() && !this.allLoaded) {
          this.loadMore();
        }
      },
      { root, rootMargin: '100px' },
    );
    this.observer.observe(sentinel.nativeElement);
  }
}
