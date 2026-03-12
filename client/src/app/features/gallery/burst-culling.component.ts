import { Component, inject, signal, computed, Pipe, PipeTransform } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { I18nService } from '../../core/services/i18n.service';
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

interface BurstPhoto {
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

interface BurstGroup {
  burst_id: number;
  photos: BurstPhoto[];
  best_path: string;
  count: number;
}

interface BurstGroupsResponse {
  groups: BurstGroup[];
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
    TranslatePipe,
    ThumbnailUrlPipe,
    IsKeptPipe,
    IsDecidedPipe,
  ],
  template: `
    <div class="flex flex-col h-full p-2 md:p-6">
      <h1 class="text-lg md:text-2xl font-semibold mb-2 md:mb-4 flex items-center gap-2 shrink-0">
        <mat-icon>burst_mode</mat-icon>
        {{ 'culling.title' | translate }}
      </h1>

      @if (loading()) {
        <div class="flex justify-center items-center flex-1">
          <mat-spinner diameter="40" />
        </div>
      } @else if (groups().length === 0) {
        <p class="text-center flex-1 flex items-center justify-center opacity-60">{{ 'culling.no_bursts' | translate }}</p>
      } @else {
        <!-- Current burst group -->
        <div class="mb-2 md:mb-3 flex items-center justify-between shrink-0">
          <span class="text-sm opacity-70">{{ 'culling.group_progress' | translate:{ current: currentIndex() + 1, total: totalGroups() } }}</span>
          <div class="flex gap-2">
            <button mat-stroked-button [disabled]="currentIndex() === 0" (click)="prev()">
              <mat-icon>navigate_before</mat-icon>
              {{ 'culling.previous' | translate }}
            </button>
            <button mat-stroked-button [disabled]="currentIndex() >= groups().length - 1 && !hasMore()" (click)="next()">
              {{ 'culling.next' | translate }}
              <mat-icon>navigate_next</mat-icon>
            </button>
          </div>
        </div>

        <!-- Photo strip — fills remaining vertical space and width -->
        <div class="flex gap-2 md:gap-3 overflow-x-auto flex-1 min-h-0 pb-2 items-stretch justify-center">
          @for (photo of currentGroup().photos; track photo.path) {
            <div class="relative flex-1 min-w-0 cursor-pointer rounded-lg overflow-hidden border-2 transition-colors h-full"
                 [class.border-green-500]="photo.path | isKept:selectionsMap():currentGroup().burst_id"
                 [class.border-red-500]="!(photo.path | isKept:selectionsMap():currentGroup().burst_id) && (photo.path | isDecided:selectionsMap():currentGroup().burst_id)"
                 [class.border-transparent]="!(photo.path | isDecided:selectionsMap():currentGroup().burst_id)"
                 (click)="toggleSelection(photo.path)">
              <img [src]="photo.path | thumbnailUrl:640"
                   class="h-full w-full object-cover" [alt]="photo.filename" />
              <!-- Best badge -->
              @if (photo.path === currentGroup().best_path) {
                <div class="absolute top-2 left-2 px-2 py-0.5 rounded bg-green-600 text-white text-xs font-bold">
                  {{ 'culling.auto_best' | translate }}
                </div>
              }
              <!-- Keep overlay -->
              @if (photo.path | isKept:selectionsMap():currentGroup().burst_id) {
                <div class="absolute top-2 right-2 w-8 h-8 rounded-full bg-green-600 flex items-center justify-center">
                  <mat-icon class="!text-lg text-white">check</mat-icon>
                </div>
              }
              <!-- Score -->
              <div class="absolute bottom-2 left-2 px-2 py-0.5 rounded bg-black/60 text-white text-xs font-medium">
                {{ photo.aggregate | number:'1.1-1' }}
              </div>
              <!-- Blink warning -->
              @if (photo.is_blink) {
                <div class="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-yellow-600 text-white text-xs font-bold">
                  {{ 'ui.badges.blink' | translate }}
                </div>
              }
            </div>
          }
        </div>

        <!-- Action buttons -->
        <div class="flex gap-2 md:gap-3 mt-2 md:mt-3 shrink-0 justify-center">
          <button mat-flat-button (click)="confirmGroup()" [disabled]="confirming()"
                  [matTooltip]="'culling.confirm_tooltip' | translate">
            <mat-icon>check_circle</mat-icon>
            {{ 'culling.confirm' | translate }}
          </button>
          <button mat-stroked-button (click)="skipGroup()"
                  [matTooltip]="'culling.skip_tooltip' | translate">
            {{ 'culling.skip' | translate }}
          </button>
          <button mat-stroked-button (click)="autoSelectAll()" [disabled]="confirming()"
                  [matTooltip]="'culling.auto_select_all_tooltip' | translate">
            <mat-icon>auto_fix_high</mat-icon>
            {{ 'culling.auto_select_all' | translate }}
          </button>
        </div>
      }
    </div>
  `,
  host: { class: 'block h-full' },
})
export class BurstCullingComponent {
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);

  protected readonly groups = signal<BurstGroup[]>([]);
  protected readonly currentIndex = signal(0);
  protected readonly totalGroups = signal(0);
  protected readonly loading = signal(true);
  protected readonly confirming = signal(false);

  /** burst_id -> set of kept paths */
  protected readonly selectionsMap = signal<Map<number, Set<string>>>(new Map());

  protected readonly currentGroup = computed(() => this.groups()[this.currentIndex()]);

  private readonly currentPage = signal(1);
  private readonly totalPages = signal(1);

  protected readonly hasMore = computed(() => {
    return this.currentIndex() < this.groups().length - 1 || this.currentPage() < this.totalPages();
  });

  constructor() {
    void this.loadGroups();
  }

  async loadGroups(): Promise<void> {
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<BurstGroupsResponse>('/burst-groups', {
          page: this.currentPage(),
          per_page: 20,
        }),
      );
      this.groups.set(data.groups);
      this.totalGroups.set(data.total_groups);
      this.totalPages.set(data.total_pages);
      this.currentIndex.set(0);

      // Auto-select best photo in each group
      const newSelections = new Map<number, Set<string>>();
      for (const group of data.groups) {
        if (group.best_path) {
          newSelections.set(group.burst_id, new Set([group.best_path]));
        }
      }
      this.selectionsMap.set(newSelections);
    } catch {
      this.snackBar.open(this.i18n.t('culling.error_loading'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.loading.set(false);
    }
  }

  protected toggleSelection(path: string): void {
    const group = this.currentGroup();
    if (!group) return;
    const map = new Map(this.selectionsMap());
    const kept = new Set(map.get(group.burst_id) ?? []);

    if (kept.has(path)) {
      kept.delete(path);
    } else {
      kept.add(path);
    }
    map.set(group.burst_id, kept);
    this.selectionsMap.set(map);
  }

  protected async confirmGroup(): Promise<void> {
    const group = this.currentGroup();
    if (!group) return;

    const kept = this.selectionsMap().get(group.burst_id);
    if (!kept || kept.size === 0) return;

    this.confirming.set(true);
    try {
      await firstValueFrom(
        this.api.post('/burst-groups/select', {
          burst_id: group.burst_id,
          keep_paths: [...kept],
        }),
      );
      this.snackBar.open(this.i18n.t('culling.confirmed'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
      this.moveToNext();
    } catch {
      this.snackBar.open(this.i18n.t('culling.error_confirming'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.confirming.set(false);
    }
  }

  protected skipGroup(): void {
    this.moveToNext();
  }

  protected async autoSelectAll(): Promise<void> {
    this.confirming.set(true);
    try {
      const groups = this.groups();
      const requests = groups.slice(this.currentIndex())
        .filter(g => g.best_path)
        .map(g => firstValueFrom(
          this.api.post('/burst-groups/select', {
            burst_id: g.burst_id,
            keep_paths: [g.best_path],
          }),
        ));
      await Promise.all(requests);
      this.snackBar.open(this.i18n.t('culling.confirmed'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
      // Move to last group
      this.currentIndex.set(groups.length - 1);
    } catch {
      this.snackBar.open(this.i18n.t('culling.error_auto_select'), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.confirming.set(false);
    }
  }

  protected prev(): void {
    if (this.currentIndex() > 0) {
      this.currentIndex.update(i => i - 1);
    }
  }

  protected next(): void {
    this.moveToNext();
  }

  private moveToNext(): void {
    if (this.currentIndex() < this.groups().length - 1) {
      this.currentIndex.update(i => i + 1);
    } else if (this.currentPage() < this.totalPages()) {
      this.currentPage.update(p => p + 1);
      void this.loadGroups();
    }
  }
}
