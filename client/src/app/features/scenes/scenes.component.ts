import { Component, inject, signal, OnInit, HostListener } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { NgClass } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { isTypingContext } from '../../shared/utils/keyboard';
import { SceneRejectedPipe, SceneRejectCountPipe, SceneDatePipe } from './scenes.pipes';
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
  ],
  template: `
    <div class="px-4 pt-3 md:px-8 mx-auto w-full max-w-[96%]">
      <div class="flex items-center gap-3 mb-1">
        <h2 class="text-lg font-semibold">{{ I18N.scenes.title | translate }}</h2>
        <div class="flex items-center gap-2 ml-auto">
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
            <div class="flex gap-2 overflow-x-auto pb-1">
              @for (photo of scene.photos; track photo.path) {
                <button type="button" class="relative flex-shrink-0"
                        (click)="toggleReject(scene.scene_id, photo.path)"
                        [attr.aria-pressed]="rejected() | sceneRejected:scene.scene_id:photo.path">
                  <img [src]="photo.path | thumbnailUrl:320"
                       [appLoupe]="photo.path | imageUrl"
                       [loupeActive]="loupeActive()"
                       [loupeZoom]="loupeZoom()"
                       class="w-36 h-36 md:w-40 md:h-40 object-cover rounded border-2"
                       [ngClass]="(rejected() | sceneRejected:scene.scene_id:photo.path)
                         ? 'border-red-500 opacity-40'
                         : (photo.path === scene.best_path ? 'border-green-500' : 'border-white/20')"
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
  private readonly sceneDate = new SceneDatePipe();

  protected readonly scenes = signal<Scene[]>([]);
  protected readonly loading = signal(true);
  protected readonly total = signal(0);
  protected readonly hasMore = signal(false);
  // Per-scene set of paths marked for rejection (everything else is kept).
  protected readonly rejected = signal<Map<number, Set<string>>>(new Map());
  // Optional album scope from /scenes?album=ID.
  protected readonly albumId = signal<string | null>(null);
  // Hover-loupe (Photo-Mechanic-style Z key) state for the contact strip.
  protected readonly loupeActive = signal(false);
  protected readonly loupeZoom = signal(3);

  private page = 1;
  private readonly perPage = 20;

  async ngOnInit(): Promise<void> {
    this.albumId.set(this.route.snapshot.queryParamMap.get('album'));
    await this.load();
  }

  @HostListener('document:keydown.z', ['$event'])
  protected onZoomToggle(event: Event): void {
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.loupeActive.set(!this.loupeActive());
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    try {
      const params: Record<string, string | number> = { page: this.page, per_page: this.perPage };
      const album = this.albumId();
      if (album) params['album_id'] = album;
      const data = await firstValueFrom(
        this.api.get<ScenesResponse>('/scenes', params),
      );
      this.scenes.update(s => [...s, ...data.scenes]);
      this.total.set(data.total);
      this.hasMore.set(this.page < data.total_pages);
    } catch {
      this.snack.open(this.i18n.t(I18N.scenes.load_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
    } finally {
      this.loading.set(false);
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
    // Block loadMore for the whole confirm window (the POST + reload), so a
    // click during the network call can't append a soon-to-be-discarded page.
    this.loading.set(true);
    try {
      await firstValueFrom(
        this.api.post('/scenes/confirm', { paths: allPaths, keep_paths: keep }),
      );
      this.snack.open(this.i18n.t(I18N.scenes.culled, { count: rej.size }), undefined, { duration: 2000 });
      // Culling invalidates the server scene cache; reload from the top so
      // scene ids stay consistent with the recomputed list.
      this.page = 1;
      this.scenes.set([]);
      this.rejected.set(new Map());
      await this.load();
    } catch {
      this.snack.open(this.i18n.t(I18N.scenes.confirm_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
      this.loading.set(false);
    }
  }
}
