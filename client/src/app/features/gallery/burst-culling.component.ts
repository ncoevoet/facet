import { Component, inject, signal, computed, Pipe, PipeTransform } from '@angular/core';
import { Router } from '@angular/router';
import { DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatSliderModule } from '@angular/material/slider';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { I18nService } from '../../core/services/i18n.service';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { firstValueFrom } from 'rxjs';

@Pipe({ name: 'isKept' })
export class IsKeptPipe implements PipeTransform {
  transform(path: string, selectionsMap: Map<number, Set<string>>, burstId: number): boolean {
    const kept = selectionsMap.get(burstId);
    return kept?.has(path) ?? false;
  }
}

@Pipe({ name: 'isDecided' })
export class IsDecidedPipe implements PipeTransform {
  transform(path: string, selectionsMap: Map<number, Set<string>>, burstId: number): boolean {
    const kept = selectionsMap.get(burstId);
    return kept !== undefined && kept.size > 0 && !kept.has(path);
  }
}

interface CullingPhoto {
  path: string;
  filename: string;
  aggregate: number | null;
  aesthetic: number | null;
  tech_sharpness: number | null;
  is_blink: number;
  is_burst_lead: number;
  date_taken: string | null;
  burst_score: number;
}

interface CullingGroup {
  group_id: number;
  type: 'burst' | 'similar';
  reason: string;
  photos: CullingPhoto[];
  best_path: string;
  count: number;
}

@Pipe({ name: 'isConfirmed' })
export class IsConfirmedPipe implements PipeTransform {
  transform(group: CullingGroup, confirmedGroups: Set<string>): boolean {
    return confirmedGroups.has(`${group.group_id}_${group.type}`);
  }
}

interface CullingGroupsResponse {
  groups: CullingGroup[];
  total_groups: number;
  page: number;
  per_page: number;
  total_pages: number;
}

@Component({
  selector: 'app-burst-culling',
  imports: [
    DecimalPipe,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatSliderModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    IsKeptPipe,
    IsDecidedPipe,
    IsConfirmedPipe,
    InfiniteScrollDirective,
  ],
  template: `
    <div class="px-4 pt-2 pb-2 md:px-8 md:pt-3 md:pb-4 mx-auto w-full max-w-screen-xl">
      <!-- Header -->
      <div class="flex items-center gap-3 shrink-0 mb-3">
        <h2 class="text-lg font-semibold">{{ 'culling.title' | translate }}</h2>
        <div class="flex items-center gap-2 ml-auto">
          <span class="text-xs opacity-60">{{ 'culling.threshold' | translate }}</span>
          <mat-slider class="!w-28 !min-w-0" [min]="70" [max]="95" [step]="5" [discrete]="true">
            <input matSliderThumb [value]="similarityThreshold()" (valueChange)="onThresholdChange($event)" />
          </mat-slider>
          <span class="text-xs font-medium w-8">{{ similarityThreshold() }}%</span>
          <button mat-icon-button (click)="showHelp.set(!showHelp())" class="!w-8 !h-8 !p-0"
                  [matTooltip]="'culling.help' | translate">
            <mat-icon class="!text-lg !w-5 !h-5 !leading-5 opacity-60">help_outline</mat-icon>
          </button>
        </div>
      </div>

      @if (showHelp()) {
        <p class="text-sm opacity-60 shrink-0 p-3 mb-3 rounded-lg bg-[var(--mat-sys-surface-container)]">
          {{ 'culling.help_text' | translate }}
        </p>
      }

      <!-- Content -->
      @if (loading()) {
        <div class="flex justify-center items-center py-20">
          <mat-spinner diameter="40" />
        </div>
      } @else if (groups().length === 0) {
        <p class="text-center py-20 opacity-60">{{ 'culling.no_bursts' | translate }}</p>
      } @else {
        <div class="space-y-6 pb-4">
          @for (group of groups(); track group.group_id + '_' + group.type; let i = $index) {
            <div class="rounded-xl border border-[var(--mat-sys-outline-variant)] overflow-hidden transition-opacity duration-300"
                 [class.opacity-40]="(group | isConfirmed:confirmedGroups())"
                 [class.pointer-events-none]="(group | isConfirmed:confirmedGroups())">
              <!-- Photos -->
              <div class="flex gap-2 md:gap-3 overflow-x-auto p-3 items-center">
                @for (photo of group.photos; track photo.path) {
                  <div class="group/photo relative cursor-pointer rounded-lg overflow-hidden border-2 transition-colors flex-shrink-0 h-full max-w-[320px]"
                       [class.border-green-500]="photo.path | isKept:selectionsMap():group.group_id"
                       [class.border-red-500]="!(photo.path | isKept:selectionsMap():group.group_id) && (photo.path | isDecided:selectionsMap():group.group_id)"
                       [class.border-transparent]="!(photo.path | isDecided:selectionsMap():group.group_id)"
                       (click)="toggleSelection(photo.path, group)"
                       (dblclick)="selectExclusive(photo.path, group); $event.stopPropagation()">
                    <img [src]="photo.path | thumbnailUrl:640"
                         class="h-48 md:h-56 w-auto object-contain" [alt]="photo.filename" loading="lazy" />
                    @if (photo.path === group.best_path) {
                      <div class="absolute top-2 left-2 px-2 py-0.5 rounded bg-green-600 text-white text-xs font-bold">
                        {{ 'culling.auto_best' | translate }}
                      </div>
                    }
                    @if (photo.path | isKept:selectionsMap():group.group_id) {
                      <div class="absolute top-2 right-2 w-7 h-7 rounded-full bg-green-600 inline-flex items-center justify-center">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-white">check</mat-icon>
                      </div>
                    }
                    <div class="absolute bottom-2 left-2 px-2 py-0.5 rounded bg-black/60 text-white text-xs font-medium">
                      {{ photo.aggregate | number:'1.1-1' }}
                    </div>
                    @if (photo.is_blink) {
                      <div class="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-yellow-600 text-white text-xs font-bold">
                        {{ 'ui.badges.blink' | translate }}
                      </div>
                    }
                    @if (!(photo.path | isKept:selectionsMap():group.group_id)) {
                      <button class="absolute top-2 right-2 w-7 h-7 rounded-full bg-black/60 inline-flex items-center justify-center opacity-0 group-hover/photo:opacity-100 transition-opacity"
                              [matTooltip]="'culling.view_detail' | translate"
                              (click)="openDetail($event, photo.path)">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-white">info</mat-icon>
                      </button>
                    }
                  </div>
                }
              </div>

              <!-- Group actions -->
              <div class="flex items-center gap-2 px-4 py-2 border-t border-[var(--mat-sys-outline-variant)]">
                <span class="text-xs opacity-50">{{ group.count }} {{ 'culling.photos' | translate }}</span>
                @if ((group | isConfirmed:confirmedGroups())) {
                  <span class="inline-flex items-center gap-1 text-xs text-green-500 font-medium">
                    <mat-icon class="inline-flex !text-sm !w-4 !h-4 !leading-4">check_circle</mat-icon>
                    {{ 'culling.confirmed_badge' | translate }}
                  </span>
                }
                <div class="flex gap-2 ml-auto">
                  <button mat-stroked-button (click)="skipGroup(group)" class="!h-8 !text-sm">
                    {{ 'culling.skip' | translate }}
                  </button>
                  <button mat-flat-button (click)="confirmGroup(group)" [disabled]="confirming()"
                          class="!h-8 !text-sm inline-flex items-center">
                    <mat-icon class="inline-flex !text-base !w-4 !h-4 !leading-4 mr-1">check_circle</mat-icon>
                    {{ 'culling.confirm' | translate }}
                  </button>
                </div>
              </div>
            </div>
          }

          <!-- Confirm All Remaining -->
          @if (unconfirmedCount() > 0) {
            <div class="flex justify-center py-4">
              <button mat-flat-button (click)="confirmAllRemaining()" [disabled]="confirming()"
                      class="!px-6">
                <mat-icon>done_all</mat-icon>
                {{ 'culling.confirm_all' | translate }} ({{ unconfirmedCount() }})
              </button>
            </div>
          }

          <!-- Infinite scroll sentinel -->
          @if (hasMore()) {
            <div appInfiniteScroll (scrollReached)="onScrollReached()" class="flex justify-center py-6">
              @if (loadingMore()) {
                <mat-spinner diameter="32" />
              }
            </div>
          }
        </div>
      }
    </div>
  `,
  host: { class: 'block' },
})
export class BurstCullingComponent {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);

  protected readonly showHelp = signal(false);
  protected readonly similarityThreshold = signal(85);
  protected readonly groups = signal<CullingGroup[]>([]);
  protected readonly totalGroups = signal(0);
  protected readonly loading = signal(true);
  protected readonly loadingMore = signal(false);
  protected readonly confirming = signal(false);

  /** group_id -> set of kept paths */
  protected readonly selectionsMap = signal<Map<number, Set<string>>>(new Map());

  /** Set of confirmed group keys (group_id + '_' + type) */
  protected readonly confirmedGroups = signal<Set<string>>(new Set());

  protected readonly currentPage = signal(1);
  protected readonly totalPages = signal(1);
  private readonly similarSeed = Math.floor(Math.random() * 1_000_000);

  protected readonly hasMore = computed(() => this.currentPage() < this.totalPages());

  protected readonly unconfirmedCount = computed(() => {
    const confirmed = this.confirmedGroups();
    return this.groups().filter(g => !confirmed.has(this.groupKey(g))).length;
  });

  constructor() {
    void this.loadGroups();
  }

  protected groupKey(group: CullingGroup): string {
    return `${group.group_id}_${group.type}`;
  }

  private buildParams(page: number): Record<string, string | number> {
    return {
      page,
      per_page: 20,
      similarity_threshold: (this.similarityThreshold() / 100).toString(),
      seed: this.similarSeed,
    };
  }

  private autoSelectBest(groups: CullingGroup[], base?: Map<number, Set<string>>): Map<number, Set<string>> {
    const map = base ? new Map(base) : new Map<number, Set<string>>();
    for (const group of groups) {
      if (group.best_path) {
        map.set(group.group_id, new Set([group.best_path]));
      }
    }
    return map;
  }

  protected onThresholdChange(value: number): void {
    this.similarityThreshold.set(value);
    this.currentPage.set(1);
    this.groups.set([]);
    this.confirmedGroups.set(new Set());
    this.selectionsMap.set(new Map());
    void this.loadGroups();
  }

  protected async loadGroups(): Promise<void> {
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<CullingGroupsResponse>('/culling-groups', this.buildParams(1)),
      );
      this.groups.set(data.groups);
      this.totalGroups.set(data.total_groups);
      this.totalPages.set(data.total_pages);
      this.currentPage.set(1);
      this.selectionsMap.set(this.autoSelectBest(data.groups));
    } catch {
      this.snackBar.open(this.i18n.t('culling.error_loading'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.loading.set(false);
    }
  }

  protected async loadMore(): Promise<void> {
    if (!this.hasMore()) return;
    this.loadingMore.set(true);
    try {
      const nextPage = this.currentPage() + 1;
      const data = await firstValueFrom(
        this.api.get<CullingGroupsResponse>('/culling-groups', this.buildParams(nextPage)),
      );
      this.groups.update(existing => [...existing, ...data.groups]);
      this.totalPages.set(data.total_pages);
      this.currentPage.set(nextPage);
      this.selectionsMap.set(this.autoSelectBest(data.groups, this.selectionsMap()));
    } catch {
      this.snackBar.open(this.i18n.t('culling.error_loading'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.loadingMore.set(false);
    }
  }

  protected onScrollReached(): void {
    if (this.hasMore() && !this.loadingMore()) {
      this.loadMore();
    }
  }

  protected openDetail(event: Event, path: string): void {
    event.stopPropagation();
    this.router.navigate(['/photo'], { queryParams: { path } });
  }

  protected toggleSelection(path: string, group: CullingGroup): void {
    const map = new Map(this.selectionsMap());
    const kept = new Set(map.get(group.group_id) ?? []);

    if (kept.has(path)) {
      kept.delete(path);
    } else {
      kept.add(path);
    }
    map.set(group.group_id, kept);
    this.selectionsMap.set(map);
  }

  protected selectExclusive(path: string, group: CullingGroup): void {
    const map = new Map(this.selectionsMap());
    map.set(group.group_id, new Set([path]));
    this.selectionsMap.set(map);
  }

  protected async confirmGroup(group: CullingGroup): Promise<void> {
    const kept = this.selectionsMap().get(group.group_id);
    if (!kept || kept.size === 0) return;

    this.confirming.set(true);
    try {
      await firstValueFrom(this.api.post('/culling-groups/confirm', {
        group_id: group.group_id,
        type: group.type,
        paths: group.photos.map(p => p.path),
        keep_paths: [...kept],
      }));
      this.confirmedGroups.update(s => {
        const next = new Set(s);
        next.add(this.groupKey(group));
        return next;
      });
      this.snackBar.open(this.i18n.t('culling.confirmed'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } catch {
      this.snackBar.open(this.i18n.t('culling.error_confirming'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.confirming.set(false);
    }
  }

  protected skipGroup(group: CullingGroup): void {
    this.confirmedGroups.update(s => {
      const next = new Set(s);
      next.add(this.groupKey(group));
      return next;
    });
  }

  protected async confirmAllRemaining(): Promise<void> {
    this.confirming.set(true);
    try {
      const confirmed = this.confirmedGroups();
      const remaining = this.groups().filter(g => !confirmed.has(this.groupKey(g)));
      const toConfirm = remaining.filter(g => {
        const kept = this.selectionsMap().get(g.group_id);
        return kept && kept.size > 0;
      });

      // Process in batches of 5 to avoid overwhelming the server
      const batchSize = 5;
      for (let i = 0; i < toConfirm.length; i += batchSize) {
        const batch = toConfirm.slice(i, i + batchSize);
        await Promise.all(batch.map(g => {
          const kept = this.selectionsMap().get(g.group_id)!;
          return firstValueFrom(this.api.post('/culling-groups/confirm', {
            group_id: g.group_id,
            type: g.type,
            paths: g.photos.map(p => p.path),
            keep_paths: [...kept],
          }));
        }));
      }

      this.confirmedGroups.update(s => {
        const next = new Set(s);
        for (const g of remaining) {
          next.add(this.groupKey(g));
        }
        return next;
      });
      this.snackBar.open(this.i18n.t('culling.confirmed'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } catch {
      this.snackBar.open(this.i18n.t('culling.error_auto_select'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.confirming.set(false);
    }
  }
}
