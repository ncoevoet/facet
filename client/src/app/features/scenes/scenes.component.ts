import { Component, inject, signal, computed, OnInit, HostListener } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { NgClass } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { isTypingContext } from '../../shared/utils/keyboard';
import { SceneRejectedPipe, SceneRejectCountPipe, SceneDatePipe, MomentLabelPipe } from './scenes.pipes';
import { I18N } from '../../core/i18n/keys';

interface ScenePhoto {
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
    NgClass,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatProgressSpinnerModule,
    MatSliderModule,
    MatTooltipModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    ImageUrlPipe,
    LoupeDirective,
    SceneRejectedPipe,
    SceneRejectCountPipe,
    SceneDatePipe,
    MomentLabelPipe,
  ],
  template: `
    <div class="px-4 pt-3 md:px-8 mx-auto w-full max-w-[96%]">
      <div class="flex items-center gap-3 mb-1">
        <h2 class="text-lg font-semibold">{{ I18N.scenes.title | translate }}</h2>
        <div class="flex items-center gap-2 ml-auto">
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
      <p class="text-sm text-white/50 mb-4">{{ I18N.scenes.subtitle | translate }}</p>

      @if (loading() && scenes().length === 0) {
        <div class="flex justify-center py-10"><mat-spinner diameter="32" /></div>
      } @else if (scenes().length === 0) {
        <div class="text-white/50 py-10 text-center">{{ I18N.scenes.empty | translate }}</div>
      } @else {
        @for (scene of scenes(); track scene.scene_id) {
          <div class="mb-6 rounded-lg border border-white/10 p-3">
            <div class="flex items-center gap-2 mb-2">
              <mat-icon class="!text-base text-white/60">schedule</mat-icon>
              <span class="text-sm text-white/80">{{ scene.start | sceneDate }}</span>
              <span class="text-xs text-white/40">· {{ scene.count }} {{ I18N.scenes.photos | translate }}</span>
              @if (scene.moment | momentLabel; as momentLabel) {
                <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-[var(--mat-sys-primary)]/20 text-[var(--mat-sys-primary)]">
                  <mat-icon class="!text-sm !w-4 !h-4 !leading-4">auto_awesome</mat-icon>{{ momentLabel }}
                </span>
              }
              <button mat-flat-button color="primary" class="!ml-auto"
                      (click)="cullScene(scene)">
                <mat-icon>movie_filter</mat-icon>
                {{ I18N.scenes.cull_this_scene | translate }}
              </button>
              <button mat-stroked-button (click)="confirm(scene)">
                <mat-icon>auto_delete</mat-icon>
                {{ I18N.scenes.cull_action | translate:{ count: (rejected() | sceneRejectCount:scene.scene_id) } }}
              </button>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
              @for (photo of scene.photos; track photo.path) {
                <button type="button" class="group relative w-full aspect-[4/3] rounded-xl overflow-hidden border-2"
                        (click)="toggleReject(scene.scene_id, photo.path)"
                        [attr.aria-pressed]="rejected() | sceneRejected:scene.scene_id:photo.path"
                        [ngClass]="(rejected() | sceneRejected:scene.scene_id:photo.path)
                          ? 'border-red-500'
                          : (photo.path === scene.best_path ? 'border-green-500' : 'border-white/20')">
                  <img [src]="photo.path | thumbnailUrl:320"
                       [appLoupe]="photo.path | imageUrl:true"
                       [loupeActive]="loupeActive()"
                       [loupeZoom]="loupeZoom()"
                       class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                       [class.opacity-40]="rejected() | sceneRejected:scene.scene_id:photo.path"
                       [alt]="photo.filename" loading="lazy" />
                  @if (photo.path === scene.best_path) {
                    <span class="absolute top-1 left-1 bg-green-600/90 text-white text-[10px] px-1 rounded">{{ I18N.scenes.best | translate }}</span>
                  }
                  @if (rejected() | sceneRejected:scene.scene_id:photo.path) {
                    <mat-icon class="absolute inset-0 m-auto !text-3xl text-red-400">close</mat-icon>
                  }
                </button>
              }
            </div>
          </div>
        }
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
  protected readonly I18N = I18N;
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly albumService = inject(AlbumService);
  private readonly sceneDate = new SceneDatePipe();

  protected readonly scenes = signal<Scene[]>([]);
  protected readonly loading = signal(true);
  protected readonly total = signal(0);
  protected readonly hasMore = signal(false);
  // Per-scene set of paths marked for rejection (everything else is kept).
  protected readonly rejected = signal<Map<number, Set<string>>>(new Map());
  // Optional album scope from /scenes?album=ID.
  protected readonly albumId = signal<string | null>(null);
  // Non-smart albums for the header scope picker.
  protected readonly albums = signal<Album[]>([]);
  protected readonly currentAlbumName = computed(() =>
    AlbumService.nameById(this.albums(), this.albumId()));
  // Hover-loupe (Photo-Mechanic-style Z key) state for the contact strip.
  protected readonly loupeActive = signal(false);
  protected readonly loupeZoom = signal(3);

  private page = 1;
  private readonly perPage = 20;
  // Bumped on every load() so a slow in-flight request can't append its scenes
  // after the scope changed (fast album switching / ngOnInit race).
  private loadGeneration = 0;

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
    this.rejected.set(new Map());
    await this.load();
  }

  @HostListener('document:keydown.z', ['$event'])
  protected onZoomToggle(event: Event): void {
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.loupeActive.set(!this.loupeActive());
  }

  private async load(): Promise<void> {
    const gen = ++this.loadGeneration;
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

  /** Open the rich culling darkroom scoped to just this scene's capture window. */
  protected cullScene(scene: Scene): void {
    void this.router.navigate(['/culling'], {
      queryParams: {
        album: this.albumId() ?? undefined,
        from: scene.start ?? undefined,
        to: scene.end ?? undefined,
        scene: this.sceneDate.transform(scene.start),
      },
    });
  }

  protected toggleReject(sceneId: number, path: string): void {
    this.rejected.update(m => {
      const next = new Map(m);
      const set = new Set(next.get(sceneId) ?? []);
      if (set.has(path)) set.delete(path); else set.add(path);
      next.set(sceneId, set);
      return next;
    });
  }

  protected async confirm(scene: Scene): Promise<void> {
    const rej = this.rejected().get(scene.scene_id) ?? new Set<string>();
    if (rej.size === 0) {
      this.snack.open(this.i18n.t(I18N.scenes.nothing_to_cull), undefined, { duration: 2000 });
      return;
    }
    const allPaths = scene.photos.map(p => p.path);
    const keep = allPaths.filter(p => !rej.has(p));
    // Block loadMore for the confirm window so a click during the POST can't
    // append a page computed against the soon-to-be-stale server cache.
    this.loading.set(true);
    try {
      await firstValueFrom(
        this.api.post('/scenes/confirm', { paths: allPaths, keep_paths: keep }),
      );
      this.snack.open(this.i18n.t(I18N.scenes.culled, { count: rej.size }), undefined, { duration: 2000 });
      // Update only this scene in place: drop its rejected photos (a fully
      // emptied scene disappears) instead of reloading and re-numbering the
      // whole list. Scene ids stay stable for the session.
      this.scenes.update(list => list
        .map(s => s.scene_id === scene.scene_id ? this.pruneScene(s, rej) : s)
        .filter(s => s.photos.length > 0));
      this.rejected.update(m => {
        const next = new Map(m);
        next.delete(scene.scene_id);
        return next;
      });
    } catch {
      this.snack.open(this.i18n.t(I18N.scenes.confirm_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
    } finally {
      this.loading.set(false);
    }
  }

  /** Remove rejected photos from a scene, re-picking the best if it was culled. */
  private pruneScene(scene: Scene, rejected: Set<string>): Scene {
    const photos = scene.photos.filter(p => !rejected.has(p.path));
    const best = photos.some(p => p.path === scene.best_path)
      ? scene.best_path
      : photos.reduce((b, p) => (p.aggregate ?? -1) > (b.aggregate ?? -1) ? p : b,
          photos[0])?.path ?? scene.best_path;
    return { ...scene, photos, count: photos.length, best_path: best };
  }
}
