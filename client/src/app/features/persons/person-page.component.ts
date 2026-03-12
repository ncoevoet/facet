import { Component, inject, input, signal, computed, OnInit, OnDestroy, ElementRef, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';

interface PersonPhoto {
  path: string;
  filename: string;
  aggregate: number;
  aesthetic: number;
  date_taken: string;
}

interface PersonPhotosResponse {
  photos: PersonPhoto[];
  total: number;
  person: { id: number; name: string; face_count: number };
}

@Component({
  selector: 'app-person-page',
  imports: [
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    PersonThumbnailUrlPipe,
    FixedPipe,
  ],
  template: `
    <div class="p-4 md:p-6 max-w-screen-2xl mx-auto">
      <!-- Header -->
      <div class="flex items-center gap-4 mb-6">
        <a mat-icon-button routerLink="/persons">
          <mat-icon>arrow_back</mat-icon>
        </a>

        @if (person()) {
          <img
            [src]="+personId() | personThumbnailUrl"
            class="w-16 h-16 rounded-full object-cover"
            alt=""
          />
          <div>
            <h1 class="text-2xl font-medium">
              {{ person()!.name || ('persons.unnamed' | translate) }}
            </h1>
            <p class="text-sm opacity-70">
              {{ 'persons.photo_count' | translate:{ count: total() } }}
            </p>
          </div>
        }
      </div>

      <!-- Photo grid -->
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
        @for (photo of photos(); track photo.path) {
          <div class="group relative aspect-square overflow-hidden rounded-lg bg-[var(--mat-sys-surface-container)]">
            <img
              [src]="photo.path | thumbnailUrl:320"
              [alt]="photo.filename"
              class="w-full h-full object-cover"
              loading="lazy"
            />
            <div
              class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent
                     p-2 pt-6 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <p class="text-xs truncate">{{ photo.filename }}</p>
              @if (photo.aggregate) {
                <p class="text-xs opacity-70">{{ photo.aggregate | fixed:1 }}</p>
              }
            </div>
          </div>
        }
      </div>

      <!-- Loading spinner -->
      @if (loading()) {
        <div class="flex justify-center py-8">
          <mat-spinner diameter="40" />
        </div>
      }

      <!-- Empty state -->
      @if (!loading() && photos().length === 0) {
        <div class="text-center py-16 opacity-50">
          <mat-icon class="!text-5xl !w-12 !h-12 mb-4">photo_library</mat-icon>
          <p>{{ 'persons.no_photos' | translate }}</p>
        </div>
      }

      <!-- Scroll sentinel -->
      <div #scrollSentinel class="h-1"></div>
    </div>
  `,
})
export class PersonPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);

  /** Route param bound via withComponentInputBinding() */
  readonly personId = input.required<string>();

  readonly photos = signal<PersonPhoto[]>([]);
  readonly person = signal<PersonPhotosResponse['person'] | null>(null);
  readonly total = signal(0);
  readonly loading = signal(false);

  private page = 1;
  private readonly perPage = 48;
  private allLoaded = false;
  private observer: IntersectionObserver | null = null;

  readonly scrollSentinel = viewChild<ElementRef<HTMLElement>>('scrollSentinel');

  readonly hasMore = computed(() => this.photos().length < this.total());

  async ngOnInit(): Promise<void> {
    await this.loadPage();
    this.setupInfiniteScroll();
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }

  private setupInfiniteScroll(): void {
    const sentinel = this.scrollSentinel();
    if (!sentinel) return;

    const scrollRoot = sentinel.nativeElement.closest('main');
    this.observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !this.loading() && !this.allLoaded) {
          this.loadPage();
        }
      },
      { root: scrollRoot, rootMargin: '200px' },
    );
    this.observer.observe(sentinel.nativeElement);
  }

  private async loadPage(): Promise<void> {
    if (this.loading() || this.allLoaded) return;
    this.loading.set(true);

    try {
      const res = await firstValueFrom(
        this.api.get<PersonPhotosResponse>(`/persons/${this.personId()}/photos`, {
          page: this.page,
          per_page: this.perPage,
        }),
      );

      this.person.set(res.person);
      this.total.set(res.total);
      this.photos.update((prev) => [...prev, ...res.photos]);
      this.page++;

      if (this.photos().length >= res.total) {
        this.allLoaded = true;
      }
    } catch {
      // Network error — stop loading
      this.allLoaded = true;
    } finally {
      this.loading.set(false);
    }
  }
}
