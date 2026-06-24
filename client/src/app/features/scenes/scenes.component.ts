import { Component, inject, signal, OnInit } from '@angular/core';
import { NgClass } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { SceneRejectedPipe, SceneRejectCountPipe, SceneDatePipe } from './scenes.pipes';

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
    TranslatePipe,
    ThumbnailUrlPipe,
    SceneRejectedPipe,
    SceneRejectCountPipe,
    SceneDatePipe,
  ],
  template: `
    <div class="px-4 pt-3 md:px-8 mx-auto w-full max-w-[96%]">
      <h2 class="text-lg font-semibold mb-1">{{ 'scenes.title' | translate }}</h2>
      <p class="text-sm text-white/50 mb-4">{{ 'scenes.subtitle' | translate }}</p>

      @if (loading() && scenes().length === 0) {
        <div class="flex justify-center py-10"><mat-spinner diameter="32" /></div>
      } @else if (scenes().length === 0) {
        <div class="text-white/50 py-10 text-center">{{ 'scenes.empty' | translate }}</div>
      } @else {
        @for (scene of scenes(); track scene.scene_id) {
          <div class="mb-6 rounded-lg border border-white/10 p-3">
            <div class="flex items-center gap-2 mb-2">
              <mat-icon class="!text-base text-white/60">schedule</mat-icon>
              <span class="text-sm text-white/80">{{ scene.start | sceneDate }}</span>
              <span class="text-xs text-white/40">· {{ scene.count }} {{ 'scenes.photos' | translate }}</span>
              <button mat-flat-button color="primary" class="!ml-auto"
                      (click)="confirm(scene)">
                <mat-icon>auto_delete</mat-icon>
                {{ 'scenes.cull_action' | translate:{ count: (rejected() | sceneRejectCount:scene.scene_id) } }}
              </button>
            </div>
            <div class="flex gap-2 overflow-x-auto pb-1">
              @for (photo of scene.photos; track photo.path) {
                <button type="button" class="relative flex-shrink-0"
                        (click)="toggleReject(scene.scene_id, photo.path)"
                        [attr.aria-pressed]="rejected() | sceneRejected:scene.scene_id:photo.path">
                  <img [src]="photo.path | thumbnailUrl:240"
                       class="w-28 h-28 object-cover rounded border-2"
                       [ngClass]="(rejected() | sceneRejected:scene.scene_id:photo.path)
                         ? 'border-red-500 opacity-40'
                         : (photo.path === scene.best_path ? 'border-green-500' : 'border-white/20')"
                       [alt]="photo.filename" loading="lazy" />
                  @if (photo.path === scene.best_path) {
                    <span class="absolute top-1 left-1 bg-green-600/90 text-white text-[10px] px-1 rounded">{{ 'scenes.best' | translate }}</span>
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
            <button mat-stroked-button (click)="loadMore()" [disabled]="loading()">{{ 'scenes.load_more' | translate }}</button>
          </div>
        }
      }
    </div>
  `,
})
export class ScenesComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);

  protected readonly scenes = signal<Scene[]>([]);
  protected readonly loading = signal(true);
  protected readonly total = signal(0);
  protected readonly hasMore = signal(false);
  // Per-scene set of paths marked for rejection (everything else is kept).
  protected readonly rejected = signal<Map<number, Set<string>>>(new Map());

  private page = 1;
  private readonly perPage = 20;

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<ScenesResponse>('/scenes', { page: this.page, per_page: this.perPage }),
      );
      this.scenes.update(s => [...s, ...data.scenes]);
      this.total.set(data.total);
      this.hasMore.set(this.page < data.total_pages);
    } catch {
      this.snack.open(this.i18n.t('scenes.load_error'), this.i18n.t('common.dismiss'), { duration: 3000 });
    } finally {
      this.loading.set(false);
    }
  }

  protected async loadMore(): Promise<void> {
    if (!this.hasMore() || this.loading()) return;
    this.page++;
    await this.load();
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
      this.snack.open(this.i18n.t('scenes.nothing_to_cull'), undefined, { duration: 2000 });
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
      this.snack.open(this.i18n.t('scenes.culled', { count: rej.size }), undefined, { duration: 2000 });
      // Culling invalidates the server scene cache; reload from the top so
      // scene ids stay consistent with the recomputed list.
      this.page = 1;
      this.scenes.set([]);
      this.rejected.set(new Map());
      await this.load();
    } catch {
      this.snack.open(this.i18n.t('scenes.confirm_error'), this.i18n.t('common.dismiss'), { duration: 3000 });
      this.loading.set(false);
    }
  }
}
