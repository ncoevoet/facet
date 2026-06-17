import { Component, inject, signal, computed, OnDestroy, WritableSignal, HostListener } from '@angular/core';
import { Router } from '@angular/router';
import { DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatSliderModule } from '@angular/material/slider';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, FaceThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { I18nService } from '../../core/services/i18n.service';
import { UndoService } from '../../core/services/undo.service';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { firstValueFrom } from 'rxjs';
import {
  IsKeptPipe, IsDecidedPipe, IsConfirmedPipe, IsPassingPipe, PassCountdownPipe,
  CullReasonPipe, FacesForPathPipe, IsEyesClosedPipe,
  CullingGroup, CullingFace,
} from './burst-culling.pipes';

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
    MatCheckboxModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    FaceThumbnailUrlPipe,
    IsKeptPipe,
    IsDecidedPipe,
    IsConfirmedPipe,
    IsPassingPipe,
    PassCountdownPipe,
    CullReasonPipe,
    FacesForPathPipe,
    IsEyesClosedPipe,
    InfiniteScrollDirective,
  ],
  template: `
    <div class="px-4 pt-2 pb-2 md:px-8 md:pt-3 md:pb-4 mx-auto w-full max-w-screen-xl">
      <!-- Header -->
      <div class="flex items-center gap-3 shrink-0 mb-3">
        <h2 class="text-lg font-semibold">{{ 'culling.title' | translate }}</h2>
        <div class="flex flex-wrap items-center gap-3 md:gap-4 ml-auto">
          <mat-checkbox [checked]="excludeRejected()" (change)="onExcludeRejectedChange($event.checked)"
                        [aria-label]="'culling.exclude_rejected' | translate"
                        class="text-xs opacity-80">
            {{ 'culling.exclude_rejected' | translate }}
          </mat-checkbox>
          <div class="flex items-center gap-2">
            <span class="text-xs opacity-60">{{ 'culling.threshold' | translate }}</span>
            <mat-slider class="!w-28 !min-w-0" [min]="70" [max]="95" [step]="5" [discrete]="true">
              <input matSliderThumb [value]="similarityThreshold()" (valueChange)="onThresholdChange($event)" [attr.aria-label]="'culling.threshold' | translate" />
            </mat-slider>
            <span class="text-xs font-medium w-8">{{ similarityThreshold() }}%</span>
          </div>
          <div class="flex items-center gap-2" [matTooltip]="'culling.strictness_tooltip' | translate">
            <span class="text-xs opacity-60">{{ 'culling.strictness' | translate }}</span>
            <mat-slider class="!w-28 !min-w-0" [min]="0" [max]="100" [step]="10" [discrete]="true">
              <input matSliderThumb [value]="strictness()" (valueChange)="onStrictnessChange($event)" [attr.aria-label]="'culling.strictness' | translate" />
            </mat-slider>
            <span class="text-xs font-medium w-8">{{ strictness() }}%</span>
          </div>
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
      } @else if (visibleGroups().length === 0) {
        <p class="text-center py-20 opacity-60">{{ 'culling.no_bursts' | translate }}</p>
      } @else {
        <div class="space-y-6 pb-4">
          @for (group of visibleGroups(); track group.group_id + '_' + group.type; let i = $index) {
            <div class="rounded-xl border border-[var(--mat-sys-outline-variant)] overflow-hidden transition-opacity duration-300"
                 [class.opacity-40]="(group | isConfirmed:confirmedGroups())"
                 [class.pointer-events-none]="(group | isConfirmed:confirmedGroups())">
              <!-- Photos -->
              <div class="flex gap-2 md:gap-3 overflow-x-auto p-3 items-center">
                @for (photo of group.photos; track photo.path; let pIdx = $index) {
                  <div class="group/photo relative cursor-pointer rounded-lg overflow-hidden border-2 transition-colors flex-shrink-0 h-full max-w-[480px]"
                       [class.border-green-500]="photo.path | isKept:selectionsMap():group.group_id"
                       [class.border-red-500]="!(photo.path | isKept:selectionsMap():group.group_id) && (photo.path | isDecided:selectionsMap():group.group_id)"
                       [class.border-transparent]="!(photo.path | isDecided:selectionsMap():group.group_id)"
                       role="button"
                       tabindex="0"
                       [attr.aria-label]="photo.filename"
                       (click)="openLightbox(group, pIdx)"
                       (keydown.enter)="openLightbox(group, pIdx)"
                       (keydown.space)="openLightbox(group, pIdx); $event.preventDefault()"
                       (dblclick)="selectExclusive(photo.path, group); $event.stopPropagation()">
                    <img [src]="photo.path | thumbnailUrl:640"
                         class="h-72 md:h-96 w-auto object-contain" [alt]="photo.filename" loading="lazy" />
                    @if (photo.path === group.best_path) {
                      <div class="absolute top-2 left-2 px-2 py-0.5 rounded bg-green-600 text-white text-xs font-bold">
                        {{ 'culling.auto_best' | translate }}
                      </div>
                    } @else if (photo.cull_reason; as reason) {
                      <div class="absolute top-2 left-2 px-2 py-0.5 rounded bg-black/70 text-white text-xs font-medium max-w-[160px] truncate">
                        {{ reason | cullReason }}
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
                  @if (group | isPassing:passingGroups()) {
                    <div class="relative overflow-hidden rounded-full">
                      <button mat-stroked-button (click)="cancelPass(group)" class="!h-8 !text-sm relative z-10">
                        {{ 'culling.cancel_pass' | translate }} ({{ group | passCountdown:passingGroups() }}s)
                      </button>
                      <div class="absolute inset-0 bg-[var(--mat-sys-outline-variant)] opacity-30 origin-right transition-transform duration-1000 ease-linear"
                           [style.transform]="'scaleX(' + ((group | passCountdown:passingGroups()) / 5) + ')'"></div>
                    </div>
                  } @else {
                    <button mat-stroked-button (click)="skipGroup(group)" class="!h-8 !text-sm">
                      {{ 'culling.skip' | translate }}
                    </button>
                    <button mat-flat-button (click)="confirmGroup(group)" [disabled]="confirming()"
                            class="!h-8 !text-sm inline-flex items-center">
                      <mat-icon class="inline-flex !text-base !w-4 !h-4 !leading-4 mr-1">check_circle</mat-icon>
                      {{ 'culling.confirm' | translate }}
                    </button>
                  }
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

    <!-- Lightbox overlay -->
    @if (lightboxGroup(); as lbGroup) {
      <div class="fixed inset-0 z-[100] bg-black/95 flex flex-col"
           role="dialog"
           aria-modal="true"
           tabindex="-1"
           (click)="closeLightbox()"
           (keydown.escape)="closeLightbox()">
        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-2 text-white text-sm">
          <div class="opacity-70">
            {{ lightboxIndex() + 1 }} / {{ lbGroup.photos.length }}
          </div>
          <div class="flex items-center gap-4 opacity-70 text-xs">
            <span>← → {{ 'culling.lightbox.navigate' | translate }}</span>
            <span>↑ {{ 'culling.lightbox.keep' | translate }}</span>
            <span>↓ {{ 'culling.lightbox.reject' | translate }}</span>
            <span>Space {{ 'culling.confirm' | translate }}</span>
            <span>Esc {{ 'dialog.cancel' | translate }}</span>
          </div>
          <button mat-icon-button
                  [attr.aria-label]="'dialog.cancel' | translate"
                  (click)="closeLightbox(); $event.stopPropagation()" class="!text-white">
            <mat-icon>close</mat-icon>
          </button>
        </div>
        <!-- Image -->
        @if (lbGroup.photos[lightboxIndex()]; as lbPhoto) {
          <div class="flex-1 flex items-center justify-center overflow-hidden"
               role="presentation"
               (click)="$event.stopPropagation()"
               (keydown)="$event.stopPropagation()">
            <img [src]="lbPhoto.path | thumbnailUrl:1920"
                 class="max-h-full max-w-full object-contain"
                 [alt]="lbPhoto.filename" />
          </div>
          <!-- Footer status -->
          <div class="px-4 py-3 text-center"
               role="presentation"
               (click)="$event.stopPropagation()"
               (keydown)="$event.stopPropagation()">
            @if (lbPhoto.path | isKept:selectionsMap():lbGroup.group_id) {
              <span class="inline-flex items-center gap-1 text-green-400 text-sm">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">check</mat-icon>
                {{ 'culling.lightbox.kept' | translate }}
              </span>
            } @else if (lbPhoto.path | isDecided:selectionsMap():lbGroup.group_id) {
              <span class="inline-flex items-center gap-1 text-red-400 text-sm">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">close</mat-icon>
                {{ 'culling.lightbox.rejected' | translate }}
              </span>
            } @else {
              <span class="text-white/40 text-sm">{{ 'culling.lightbox.undecided' | translate }}</span>
            }
          </div>
        }

        <!-- Face / expression close-up grid -->
        @if (faceGridHasFaces()) {
          <div class="border-t border-white/10 px-4 py-3 overflow-x-auto"
               role="presentation"
               (click)="$event.stopPropagation()"
               (keydown)="$event.stopPropagation()">
            <div class="text-white/50 text-xs mb-2">{{ 'culling.face_grid_title' | translate }}</div>
            <div class="flex gap-3 items-start">
              @for (photo of lbGroup.photos; track photo.path) {
                @if ((photo.path | facesForPath:faceMap()).length > 0) {
                  <div class="flex flex-col items-center gap-1 flex-shrink-0">
                    <div class="flex gap-1">
                      @for (face of photo.path | facesForPath:faceMap(); track face.id) {
                        <div class="relative">
                          <img [src]="face.id | faceThumbnailUrl"
                               class="w-16 h-16 rounded object-cover border-2 border-white/20"
                               [class.border-green-500]="photo.path === lbGroup.best_path"
                               [class.border-red-500]="(photo | isEyesClosed)"
                               [alt]="photo.filename" loading="lazy" />
                          @if (photo | isEyesClosed) {
                            <div class="absolute bottom-0 inset-x-0 bg-yellow-600/90 text-white text-[10px] leading-tight text-center font-bold py-0.5">
                              {{ 'ui.badges.blink' | translate }}
                            </div>
                          }
                        </div>
                      }
                    </div>
                    @if (photo.path === lbGroup.best_path) {
                      <span class="text-green-400 text-[10px] font-bold">{{ 'culling.auto_best' | translate }}</span>
                    } @else if (photo.cull_reason; as reason) {
                      <span class="text-white/60 text-[10px] max-w-[80px] truncate">{{ reason | cullReason }}</span>
                    }
                  </div>
                }
              }
            </div>
          </div>
        }
      </div>
    }
  `,
  host: { class: 'block' },
})
export class BurstCullingComponent implements OnDestroy {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly undoService = inject(UndoService);

  protected readonly showHelp = signal(false);
  protected readonly similarityThreshold = signal(85);
  /** Auto-keep strictness (0-100): higher keeps fewer photos below the best. */
  protected readonly strictness = signal(100);
  protected readonly excludeRejected = signal(true);
  protected readonly groups = signal<CullingGroup[]>([]);
  protected readonly totalGroups = signal(0);
  protected readonly loading = signal(true);
  protected readonly loadingMore = signal(false);
  protected readonly confirming = signal(false);

  /** Monotonic id bumped on every filter change; loadGroups/loadMore drop late responses whose generation no longer matches. */
  private loadGenerationId = 0;

  /** group_id -> set of kept paths */
  protected readonly selectionsMap = signal<Map<number, Set<string>>>(new Map());

  /** Set of confirmed group keys (group_id + '_' + type) */
  protected readonly confirmedGroups = signal<Set<string>>(new Set());

  /** Map of group key -> remaining countdown seconds for groups being passed */
  protected readonly passingGroups = signal<Map<string, number>>(new Map());

  /** Set of group keys hidden after pass timeout */
  private readonly hiddenGroups = signal<Set<string>>(new Set());

  /** Active timers for passing groups (for cleanup) */
  private readonly passTimers = new Map<string, { timeoutId: ReturnType<typeof setTimeout>; intervalId: ReturnType<typeof setInterval> }>();

  protected readonly currentPage = signal(1);
  protected readonly totalPages = signal(1);
  private readonly similarSeed = Math.floor(Math.random() * 1_000_000);

  protected readonly hasMore = computed(() => this.currentPage() < this.totalPages());

  /** Lightbox state — group being viewed, and current photo index inside it. */
  protected readonly lightboxGroupId = signal<string | null>(null);
  protected readonly lightboxIndex = signal(0);
  protected readonly lightboxGroup = computed<CullingGroup | null>(() => {
    const key = this.lightboxGroupId();
    if (!key) return null;
    return this.groups().find(g => this.groupKey(g) === key) ?? null;
  });

  /** photo path -> detected faces, loaded lazily when a lightbox group opens. */
  protected readonly faceMap = signal<Map<string, CullingFace[]>>(new Map());

  /** True when at least one photo in the focused group has loaded faces. */
  protected readonly faceGridHasFaces = computed(() => {
    const group = this.lightboxGroup();
    if (!group) return false;
    const map = this.faceMap();
    return group.photos.some(p => (map.get(p.path)?.length ?? 0) > 0);
  });

  /** Groups visible in the UI (excludes hidden groups that completed pass timeout) */
  protected readonly visibleGroups = computed(() => {
    const hidden = this.hiddenGroups();
    return this.groups().filter(g => !hidden.has(this.groupKey(g)));
  });

  protected readonly unconfirmedCount = computed(() => {
    const confirmed = this.confirmedGroups();
    return this.visibleGroups().filter(g => !confirmed.has(this.groupKey(g))).length;
  });

  constructor() {
    void this.loadGroups();
  }

  /** Update a signal holding a Map by cloning and setting a key. */
  private updateMapSignal<K, V>(sig: WritableSignal<Map<K, V>>, key: K, value: V): void {
    sig.update(m => { const next = new Map(m); next.set(key, value); return next; });
  }

  /** Update a signal holding a Map by cloning and deleting a key. */
  private deleteMapKey<K, V>(sig: WritableSignal<Map<K, V>>, key: K): void {
    sig.update(m => { if (!m.has(key)) return m; const next = new Map(m); next.delete(key); return next; });
  }

  /** Update a signal holding a Set by cloning and adding a value. */
  private addToSetSignal<V>(sig: WritableSignal<Set<V>>, value: V): void {
    sig.update(s => { const next = new Set(s); next.add(value); return next; });
  }

  ngOnDestroy(): void {
    this.clearAllPassTimers();
  }

  protected groupKey(group: CullingGroup): string {
    return `${group.group_id}_${group.type}`;
  }

  private buildParams(page: number): Record<string, string | number | boolean> {
    return {
      page,
      per_page: 20,
      similarity_threshold: (this.similarityThreshold() / 100).toString(),
      seed: this.similarSeed,
      exclude_rejected: this.excludeRejected(),
    };
  }

  private autoSelectBest(groups: CullingGroup[], base?: Map<number, Set<string>>): Map<number, Set<string>> {
    const map = base ? new Map(base) : new Map<number, Set<string>>();
    for (const group of groups) {
      if (!map.has(group.group_id)) {
        const kept = this.computeAutoKeep(group);
        if (kept.size > 0) {
          map.set(group.group_id, kept);
        }
      }
    }
    return map;
  }

  /**
   * Derive the auto-keep set for a group from the current strictness (0-100).
   * The best photo is always kept; additional photos whose burst_score falls
   * within a strictness-derived margin of the best are also kept. At strictness
   * 100 only the single best survives; at 0 everything within ~5 points stays.
   */
  private computeAutoKeep(group: CullingGroup): Set<string> {
    const best = group.best_path || group.photos[0]?.path;
    if (!best) return new Set<string>();
    const kept = new Set<string>([best]);

    const bestScore = group.photos.find(p => p.path === best)?.burst_score
      ?? Math.max(0, ...group.photos.map(p => p.burst_score));
    // strictness 100 -> margin 0 (only the best); strictness 0 -> margin 5.
    const margin = (100 - this.strictness()) / 100 * 5;
    if (margin > 0) {
      for (const photo of group.photos) {
        if (bestScore - photo.burst_score <= margin) {
          kept.add(photo.path);
        }
      }
    }
    return kept;
  }

  protected onThresholdChange(value: number): void {
    this.similarityThreshold.set(value);
    this.resetForReload();
  }

  /**
   * Re-derive the auto-keep selection for every loaded group from the new
   * strictness. Purely client-side over the burst_score values already
   * returned — no backend round-trip. Confirmed groups are left untouched.
   */
  protected onStrictnessChange(value: number): void {
    this.strictness.set(value);
    const confirmed = this.confirmedGroups();
    const map = new Map<number, Set<string>>();
    for (const group of this.groups()) {
      if (confirmed.has(this.groupKey(group))) {
        const existing = this.selectionsMap().get(group.group_id);
        if (existing) map.set(group.group_id, existing);
        continue;
      }
      const kept = this.computeAutoKeep(group);
      if (kept.size > 0) map.set(group.group_id, kept);
    }
    this.selectionsMap.set(map);
  }

  protected onExcludeRejectedChange(value: boolean): void {
    this.excludeRejected.set(value);
    this.resetForReload();
  }

  private resetForReload(): void {
    this.loadGenerationId++;
    this.currentPage.set(1);
    this.groups.set([]);
    this.confirmedGroups.set(new Set());
    this.selectionsMap.set(new Map());
    this.clearAllPassTimers();
    void this.loadGroups();
  }

  protected async loadGroups(): Promise<void> {
    const gen = this.loadGenerationId;
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<CullingGroupsResponse>('/culling-groups', this.buildParams(1)),
      );
      if (gen !== this.loadGenerationId) return;
      this.groups.set(data.groups);
      this.totalGroups.set(data.total_groups);
      this.totalPages.set(data.total_pages);
      this.currentPage.set(1);
      this.selectionsMap.set(this.autoSelectBest(data.groups));
    } catch {
      if (gen !== this.loadGenerationId) return;
      this.snackBar.open(this.i18n.t('culling.error_loading'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      if (gen === this.loadGenerationId) this.loading.set(false);
    }
  }

  protected async loadMore(): Promise<void> {
    if (!this.hasMore()) return;
    const gen = this.loadGenerationId;
    this.loadingMore.set(true);
    try {
      const nextPage = this.currentPage() + 1;
      const data = await firstValueFrom(
        this.api.get<CullingGroupsResponse>('/culling-groups', this.buildParams(nextPage)),
      );
      if (gen !== this.loadGenerationId) return;
      this.groups.update(existing => [...existing, ...data.groups]);
      this.totalPages.set(data.total_pages);
      this.currentPage.set(nextPage);
      this.selectionsMap.set(this.autoSelectBest(data.groups, this.selectionsMap()));
    } catch {
      if (gen !== this.loadGenerationId) return;
      this.snackBar.open(this.i18n.t('culling.error_loading'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      if (gen === this.loadGenerationId) this.loadingMore.set(false);
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

  // --- Lightbox handlers ---

  protected openLightbox(group: CullingGroup, index: number): void {
    this.lightboxGroupId.set(this.groupKey(group));
    this.lightboxIndex.set(index);
    void this.loadFacesForGroup(group);
  }

  protected closeLightbox(): void {
    this.lightboxGroupId.set(null);
  }

  /**
   * Lazily fetch detected faces for each photo in the focused group via the
   * existing per-photo faces endpoint, so the lightbox can tile face crops.
   * Results are cached in faceMap; already-loaded paths are skipped.
   */
  private async loadFacesForGroup(group: CullingGroup): Promise<void> {
    const missing = group.photos.filter(p => !this.faceMap().has(p.path));
    if (missing.length === 0) return;
    await Promise.all(missing.map(async photo => {
      try {
        const data = await firstValueFrom(
          this.api.get<{ faces: CullingFace[] }>('/photo/faces', { path: photo.path }),
        );
        this.faceMap.update(m => {
          const next = new Map(m);
          next.set(photo.path, data.faces ?? []);
          return next;
        });
      } catch {
        // Best-effort: record an empty result so we don't refetch on every open.
        this.faceMap.update(m => {
          const next = new Map(m);
          next.set(photo.path, []);
          return next;
        });
      }
    }));
  }

  private clampIndex(value: number, max: number): number {
    if (max <= 0) return 0;
    return Math.max(0, Math.min(max - 1, value));
  }

  @HostListener('document:keydown.arrowleft', ['$event'])
  protected onArrowLeft(event: Event): void {
    const group = this.lightboxGroup();
    if (!group) return;
    event.preventDefault();
    this.lightboxIndex.update(i => this.clampIndex(i - 1, group.photos.length));
  }

  @HostListener('document:keydown.arrowright', ['$event'])
  protected onArrowRight(event: Event): void {
    const group = this.lightboxGroup();
    if (!group) return;
    event.preventDefault();
    this.lightboxIndex.update(i => this.clampIndex(i + 1, group.photos.length));
  }

  private setCurrentLightboxPhotoKept(group: CullingGroup, keep: boolean): void {
    const photo = group.photos[this.lightboxIndex()];
    if (!photo) return;
    const map = new Map(this.selectionsMap());
    const kept = new Set(map.get(group.group_id) ?? []);
    if (keep) kept.add(photo.path); else kept.delete(photo.path);
    map.set(group.group_id, kept);
    this.selectionsMap.set(map);
  }

  @HostListener('document:keydown.arrowup', ['$event'])
  protected onArrowUp(event: Event): void {
    const group = this.lightboxGroup();
    if (!group) return;
    event.preventDefault();
    this.setCurrentLightboxPhotoKept(group, true);
  }

  @HostListener('document:keydown.arrowdown', ['$event'])
  protected onArrowDown(event: Event): void {
    const group = this.lightboxGroup();
    if (!group) return;
    event.preventDefault();
    this.setCurrentLightboxPhotoKept(group, false);
  }

  @HostListener('document:keydown.space', ['$event'])
  protected onSpace(event: Event): void {
    const group = this.lightboxGroup();
    if (!group) return;
    event.preventDefault();
    void this.confirmGroup(group).then(() => this.closeLightbox());
  }

  @HostListener('document:keydown.escape', ['$event'])
  protected onEscape(event: Event): void {
    if (this.lightboxGroup()) {
      event.preventDefault();
      this.closeLightbox();
    }
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
    this.updateMapSignal(this.selectionsMap, group.group_id, new Set([path]));
  }

  protected async confirmGroup(group: CullingGroup): Promise<void> {
    const kept = this.selectionsMap().get(group.group_id);
    if (!kept || kept.size === 0) return;

    // Deferred commit: the group disappears instantly and the API call only
    // fires when the undo window elapses - culling confirms have no inverse
    // endpoint, so this is the only way to offer undo
    const key = this.groupKey(group);
    this.addToSetSignal(this.confirmedGroups, key);
    this.undoService.register({
      labelKey: 'culling.confirmed',
      commit: async () => {
        try {
          await firstValueFrom(this.api.post('/culling-groups/confirm', {
            group_id: group.group_id,
            type: group.type,
            paths: group.photos.map(p => p.path),
            keep_paths: [...kept],
          }));
        } catch {
          this.unconfirmGroup(key);
          this.snackBar.open(this.i18n.t('culling.error_confirming'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
        }
      },
      undo: async () => {
        this.unconfirmGroup(key);
      },
    });
  }

  private unconfirmGroup(key: string): void {
    this.confirmedGroups.update(s => {
      const next = new Set(s);
      next.delete(key);
      return next;
    });
  }

  protected skipGroup(group: CullingGroup): void {
    const key = this.groupKey(group);

    // Clear any existing timer for this group before starting a new one
    this.clearPassTimer(key);

    // Start the 5-second countdown
    this.updateMapSignal(this.passingGroups, key, 5);

    const intervalId = setInterval(() => {
      this.passingGroups.update(m => {
        const current = m.get(key);
        if (current === undefined) return m;
        const next = new Map(m);
        next.set(key, current - 1);
        return next;
      });
    }, 1000);

    const timeoutId = setTimeout(() => {
      this.clearPassTimer(key);
      // Hide the group after timeout
      this.addToSetSignal(this.hiddenGroups, key);
    }, 5000);

    this.passTimers.set(key, { timeoutId, intervalId });
  }

  protected cancelPass(group: CullingGroup): void {
    const key = this.groupKey(group);
    this.clearPassTimer(key);
  }

  private clearPassTimer(key: string): void {
    const timers = this.passTimers.get(key);
    if (timers) {
      clearTimeout(timers.timeoutId);
      clearInterval(timers.intervalId);
      this.passTimers.delete(key);
    }
    this.deleteMapKey(this.passingGroups, key);
  }

  private clearAllPassTimers(): void {
    for (const { timeoutId, intervalId } of this.passTimers.values()) {
      clearTimeout(timeoutId);
      clearInterval(intervalId);
    }
    this.passTimers.clear();
    this.passingGroups.set(new Map());
    this.hiddenGroups.set(new Set());
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
        for (const g of remaining) next.add(this.groupKey(g));
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
