import { Component, inject, signal, computed, OnInit, HostListener, ChangeDetectionStrategy } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { NgClass } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { registerPageContext } from '../../core/agent/page-context.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { GalleryStore } from '../gallery/gallery.store';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, ThumbnailSrcsetPipe, ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { createLoupeState } from '../../shared/utils/loupe-state';
import { SceneDatePipe, MomentLabelPipe, MomentUncertainPipe } from './scenes.pipes';
import { sceneCullParams } from './scene-cull-link';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { MarkTonePipe } from '../../shared/pipes/mark-tone.pipe';

interface ScenePhoto {
  preview_revision?: string | null;
  path: string;
  filename: string;
  aggregate: number | null;
  date_taken: string | null;
}

interface Scene {
  scene_id: number;
  start: string | null;
  end: string | null;
  count: number;
  best_path: string;
  photos: ScenePhoto[];
  moment?: string | null;
  moment_confidence?: number | null;
}

interface ScenesResponse {
  scenes: Scene[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

@Component({
  selector: 'app-scenes',
  host: { class: 'block h-full overflow-y-auto' },
  imports: [
    MarkTonePipe,
    NgClass,
    MatIconModule,
    MatButtonModule,
    MatCardModule,
    MatMenuModule,
    MatProgressSpinnerModule,
    MatSliderModule,
    MatTooltipModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    ThumbnailSrcsetPipe,
    ImageUrlPipe,
    LoupeDirective,
    SceneDatePipe,
    MomentLabelPipe,
    MomentUncertainPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div class="px-4 pt-3 w-full">
      <div class="flex flex-wrap items-center gap-3 mb-1">
        <h1 class="sr-only">{{ I18N.scenes.title | translate }}</h1>
        <div class="flex flex-wrap items-center gap-2 ml-auto">
          <button mat-stroked-button [matMenuTriggerFor]="albumMenu"
                  [matTooltip]="I18N.scenes.album | translate">
            <mat-icon>photo_library</mat-icon>
            {{ currentAlbumName() ?? (I18N.scenes.whole_library | translate) }}
          </button>
          <mat-menu #albumMenu="matMenu">
            <button mat-menu-item (click)="selectAlbum(null)">{{ I18N.scenes.whole_library | translate }}</button>
            @for (a of albums(); track a.id) {
              <button mat-menu-item (click)="selectAlbum(a.id.toString())">{{ a.name }}</button>
            }
          </mat-menu>
          <button mat-stroked-button (click)="loupeActive.set(!loupeActive())"
                  [class.!border-[var(--mat-sys-primary)]]="loupeActive()"
                  [matTooltip]="I18N.scenes.loupe_hint | translate">
            <mat-icon>{{ loupeActive() ? 'zoom_in' : 'search' }}</mat-icon>
            {{ I18N.scenes.loupe | translate }}
          </button>
          @if (loupeActive()) {
            <mat-slider class="!w-28 !min-w-0" [min]="2" [max]="8" [step]="1" [discrete]="true">
              <input matSliderThumb [value]="loupeZoom()" (valueChange)="loupeZoom.set($event)"
                     [attr.aria-label]="I18N.scenes.loupe | translate" />
            </mat-slider>
          }
        </div>
      </div>
      <p class="text-sm text-[var(--mat-sys-on-surface-variant)] mb-4">{{ I18N.scenes.subtitle | translate }}</p>

      @if (loading() && scenes().length === 0) {
        <div class="flex justify-center py-10"><mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" /></div>
      } @else if (scenes().length === 0) {
        <div class="text-[var(--mat-sys-on-surface-variant)] py-10 text-center">{{ I18N.scenes.empty | translate }}</div>
      } @else {
        <div data-scene-grid class="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-6">
        @for (scene of scenes(); track scene.scene_id) {
          <mat-card class="!p-3">
            <div class="flex items-center gap-2 mb-2">
              <mat-icon aria-hidden="true" class="!text-base text-[var(--mat-sys-on-surface-variant)]">schedule</mat-icon>
              <span class="text-sm text-[var(--mat-sys-on-surface)]">{{ scene.start | sceneDate }}</span>
              <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">· {{ scene.count }} {{ I18N.scenes.photos | translate }}</span>
              @if (scene.moment | momentLabel; as momentLabel) {
                <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-[var(--mat-sys-primary)]/12 text-[var(--mat-sys-primary)]"
                      [class.!opacity-50]="scene.moment_confidence | momentUncertain:momentConfidenceMin()">
                  <mat-icon class="!text-sm !w-4 !h-4 !leading-4" [class]="'moment' | markTone">✦</mat-icon>{{ momentLabel }}@if (scene.moment_confidence | momentUncertain:momentConfidenceMin()) { <span class="opacity-80">({{ I18N.moments.uncertain | translate }})</span> }
                </span>
              }
              @if (auth.isEdition()) {
                <button mat-flat-button color="primary" class="!ml-auto"
                        (click)="cullScene(scene)">
                  <mat-icon>movie_filter</mat-icon>
                  {{ I18N.scenes.cull_this_scene | translate }}
                </button>
              }
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-3 gap-4">
              @for (photo of scene.photos; track photo.path) {
                <div class="group relative w-full aspect-[4/3] rounded-xl overflow-hidden border-2"
                     [ngClass]="photo.path === scene.best_path ? 'border-green-500' : 'border-[var(--mat-sys-outline-variant)]'">
                  <img [src]="photo.path | thumbnailUrl:320:photo.preview_revision" [srcset]="photo.path | thumbnailSrcset:photo.preview_revision" sizes="(min-width: 1280px) 17vw, (min-width: 1024px) 20vw, (min-width: 768px) 25vw, (min-width: 640px) 34vw, 50vw"
                       [appLoupe]="photo.path | imageUrl:true:photo.preview_revision"
                       [loupeActive]="loupeActive()"
                       [loupeZoom]="loupeZoom()"
                       class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                       [alt]="photo.filename" loading="lazy" />
                  @if (photo.path === scene.best_path) {
                    <span class="absolute top-1 left-1 bg-green-700 text-white text-[11px] px-1 rounded">{{ I18N.scenes.best | translate }}</span>
                  }
                </div>
              }
            </div>
          </mat-card>
        }
        </div>
        @if (hasMore()) {
          <div class="flex justify-center py-4">
            <button mat-stroked-button (click)="loadMore()" [disabled]="loading()">{{ I18N.scenes.load_more | translate }}</button>
          </div>
        }
      }
    </div>
  `,
})
export class ScenesComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly albumService = inject(AlbumService);
  protected readonly auth = inject(AuthService);
  private readonly store = inject(GalleryStore);

  protected readonly scenes = signal<Scene[]>([]);
  protected readonly loading = signal(true);
  protected readonly total = signal(0);
  protected readonly hasMore = signal(false);
  // Optional album scope from /scenes?album=ID.
  protected readonly albumId = signal<string | null>(null);
  // Non-smart albums for the header scope picker.
  protected readonly albums = signal<Album[]>([]);
  protected readonly currentAlbumName = computed(() =>
    AlbumService.nameById(this.albums(), this.albumId()));
  // Hover-loupe (Photo-Mechanic-style Z key) state for the contact strip.
  private readonly loupe = createLoupeState();
  protected readonly loupeActive = this.loupe.loupeActive;
  protected readonly loupeZoom = this.loupe.loupeZoom;
  /** Min posterior below which a moment label is shown dimmed + "(uncertain)". */
  protected readonly momentConfidenceMin = computed(
    () => this.store.config()?.moment_confidence_min ?? 0,
  );

  private page = 1;
  private readonly perPage = 20;
  // Bumped on every load() so a slow in-flight request can't append its scenes
  // after the scope changed (fast album switching / ngOnInit race).
  private loadGeneration = 0;

  constructor() {
    registerPageContext('scenes', () => ({ album_id: this.albumId(), total: this.total() }));
  }

  async ngOnInit(): Promise<void> {
    this.albumId.set(this.route.snapshot.queryParamMap.get('album'));
    void this.loadAlbums();
    await this.load();
  }

  private async loadAlbums(): Promise<void> {
    try {
      this.albums.set(await firstValueFrom(this.albumService.listNonSmart()));
    } catch {
      // Picker stays at "Whole library" if albums fail to load.
    }
  }

  /** Re-scope the scenes feed to an album (or the whole library when null). */
  protected async selectAlbum(id: string | null): Promise<void> {
    if (id === this.albumId()) return;
    this.albumId.set(id);
    void this.router.navigate(['/scenes'], { queryParams: { album: id ?? null } });
    this.page = 1;
    this.scenes.set([]);
    await this.load();
  }

  @HostListener('document:keydown.z', ['$event'])
  protected onZoomToggle(event: Event): void {
    this.loupe.toggle(event);
  }

  private async load(): Promise<void> {
    const gen = ++this.loadGeneration;
    const page = this.page;
    this.loading.set(true);
    try {
      const params: Record<string, string | number> = { page: this.page, per_page: this.perPage };
      const album = this.albumId();
      if (album) params['album_id'] = album;
      const data = await firstValueFrom(
        this.api.get<ScenesResponse>('/scenes', params),
      );
      if (gen !== this.loadGeneration) return;
      this.scenes.update(s => [...s, ...data.scenes]);
      this.total.set(data.total);
      this.hasMore.set(this.page < data.total_pages);
    } catch {
      if (gen !== this.loadGeneration) return;
      // Give the page back: loadMore already incremented it, and a failed
      // append must be refetched, not skipped.
      if (page > 1) this.page = page - 1;
      this.snack.open(this.i18n.t(I18N.scenes.load_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
    } finally {
      if (gen === this.loadGeneration) this.loading.set(false);
    }
  }

  protected async loadMore(): Promise<void> {
    if (!this.hasMore() || this.loading()) return;
    this.page++;
    await this.load();
  }

  /** Open the rich culling darkroom scoped to just this scene's capture window
   *  (edition only — the button is gated on auth.isEdition()). */
  protected cullScene(scene: Scene): void {
    void this.router.navigate(['/culling'], { queryParams: sceneCullParams(scene, this.albumId()) });
  }
}
