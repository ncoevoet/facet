import { Component, DestroyRef, Pipe, PipeTransform, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { DragDropModule, CdkDragDrop, moveItemInArray } from '@angular/cdk/drag-drop';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ScoringContextLabelPipe } from '../../shared/pipes/scoring-context-label.pipe';
import { EtaDurationPipe, FilterValueFormatPipe } from './comparison.pipes';

const DEFAULT_CATEGORY_NAME = 'default';
const JOB_KIND_RECOMPUTE = 'recompute';
const MAX_OVERLAP_PAIRS = 8;

interface CategoryPriorityEntry {
  name: string;
  priority: number;
  filters: Record<string, unknown>;
}

interface ScoringContextEntry {
  name: string;
  label_key: string;
  promote: string[];
  excluded: string[];
  suggest_from_moments: string[];
  effective_order: string[];
}

interface CategoryOverlapEntry {
  name: string;
  priority: number;
  assigned: number;
  matched: number;
  captured_by_higher: number;
}

interface CategoryOverlapResponse {
  overlaps: { pair: [string, string]; count: number }[];
  per_category: CategoryOverlapEntry[];
  uncategorized: number;
  total: number;
}

interface RecomputeProgress {
  phase: string;
  current?: number;
  total?: number;
  eta_seconds?: number;
}

interface RecomputeStatus {
  running: boolean;
  kind: string | null;
  progress: RecomputeProgress | null;
  exit_code: number | null;
}

interface FilterSummaryEntry {
  labelKey: string;
  text: string;
}

interface ExclusionChip {
  name: string;
  excluded: boolean;
}

const BOOLEAN_SUMMARY_KEYS = ['has_face', 'is_silhouette', 'is_group_portrait', 'is_monochrome'] as const;
const RANGE_SUMMARY_KEYS = ['face_ratio', 'face_count', 'iso', 'shutter_speed', 'focal_length', 'f_stop', 'luminance'] as const;

/** Condenses a category's filter config into short, translatable {label, value} entries for a one-line summary. */
@Pipe({ name: 'categoryFilterSummary', standalone: true, pure: true })
export class CategoryFilterSummaryPipe implements PipeTransform {
  private readonly valueFormat = new FilterValueFormatPipe();

  transform(filters: Record<string, unknown> | null | undefined): FilterSummaryEntry[] {
    if (!filters) return [];
    const entries: FilterSummaryEntry[] = [];

    for (const key of BOOLEAN_SUMMARY_KEYS) {
      const v = filters[key];
      if (v === true || v === false) {
        entries.push({ labelKey: `comparison.filter.${key}`, text: v ? '✓' : '✗' });
      }
    }

    for (const key of RANGE_SUMMARY_KEYS) {
      const min = filters[`${key}_min`];
      const max = filters[`${key}_max`];
      const minText = typeof min === 'number' ? this.valueFormat.transform(min, `${key}_min`) : '';
      const maxText = typeof max === 'number' ? this.valueFormat.transform(max, `${key}_max`) : '';
      if (minText || maxText) {
        entries.push({ labelKey: `comparison.filter.${key}`, text: [minText, maxText].filter(Boolean).join('–') });
      }
    }

    const requiredTags = filters['required_tags'];
    if (Array.isArray(requiredTags) && requiredTags.length > 0) {
      const shown = requiredTags.slice(0, 4).join(', ') + (requiredTags.length > 4 ? '…' : '');
      entries.push({ labelKey: 'comparison.filter.required_tags', text: shown });
    }

    const excludedTags = filters['excluded_tags'];
    if (Array.isArray(excludedTags) && excludedTags.length > 0) {
      const shown = excludedTags.slice(0, 4).join(', ') + (excludedTags.length > 4 ? '…' : '');
      entries.push({ labelKey: 'comparison.filter.excluded_tags', text: shown });
    }

    return entries;
  }
}

@Component({
  selector: 'app-comparison-priority-tab',
  standalone: true,
  imports: [
    DragDropModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatProgressBarModule,
    MatTooltipModule,
    TranslatePipe,
    ScoringContextLabelPipe,
    CategoryFilterSummaryPipe,
    EtaDurationPipe,
  ],
  template: `
    <div class="grid grid-cols-1 gap-6 mt-4 pb-20 lg:pb-0">
      <!-- Context picker -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>{{ 'comparison.context.tab_label' | translate }}</mat-card-title>
          <mat-card-subtitle>{{ 'comparison.context.picker_description' | translate }}</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          <mat-form-field class="w-full max-w-sm">
            <mat-label>{{ 'comparison.context.context_picker' | translate }}</mat-label>
            <mat-select [value]="selectedContext()" [disabled]="savingContext()"
                        (selectionChange)="selectContext($event.value)">
              @for (ctx of contexts(); track ctx.name) {
                <mat-option [value]="ctx.name">{{ ctx | scoringContextLabel }}</mat-option>
              }
            </mat-select>
          </mat-form-field>
        </mat-card-content>
      </mat-card>

      @if (isDefaultContext()) {
        <!-- Default: drag-to-reorder global priority list -->
        <mat-card>
          <mat-card-header class="!flex !items-start">
            <div class="flex-1">
              <mat-card-title>{{ 'comparison.context.global_order_title' | translate }}</mat-card-title>
              <mat-card-subtitle>{{ 'comparison.context.global_order_description' | translate }}</mat-card-subtitle>
            </div>
            <div class="flex gap-1 shrink-0">
              <button mat-icon-button
                [disabled]="!hasOrderChanges() || saving()"
                (click)="resetOrder()"
                [matTooltip]="'comparison.reset' | translate"
                [attr.aria-label]="'comparison.reset' | translate">
                <mat-icon>refresh</mat-icon>
              </button>
              <button mat-icon-button
                [disabled]="saveDisabled()"
                (click)="saveOrder()"
                [matTooltip]="'comparison.save' | translate"
                [attr.aria-label]="'comparison.save' | translate">
                @if (saving()) {
                  <mat-spinner diameter="20" [attr.aria-label]="'ui.labels.loading' | translate" />
                } @else {
                  <mat-icon>save</mat-icon>
                }
              </button>
            </div>
          </mat-card-header>
          <mat-card-content class="!pt-4">
            @if (categoriesLoading()) {
              <div class="flex justify-center py-8"><mat-spinner diameter="40" [attr.aria-label]="'ui.labels.loading' | translate" /></div>
            } @else {
              <div cdkDropList class="flex flex-col gap-1.5" (cdkDropListDropped)="drop($event)">
                @for (cat of orderedCategories(); track cat.name; let i = $index) {
                  <div cdkDrag class="flex items-center gap-3 rounded-lg border border-[var(--mat-sys-outline-variant)] px-3 py-2 bg-[var(--mat-sys-surface-container)]">
                    <mat-icon cdkDragHandle class="text-gray-400 cursor-move shrink-0">drag_indicator</mat-icon>
                    <span class="w-8 shrink-0 text-xs font-mono text-gray-400">{{ i + 1 }}</span>
                    <span class="w-40 shrink-0 text-sm font-medium">{{ ('category_names.' + cat.name) | translate }}</span>
                    <span class="w-14 shrink-0 text-xs font-mono text-gray-500">#{{ cat.priority }}</span>
                    <div class="flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-gray-500 min-w-0">
                      @for (entry of (cat.filters | categoryFilterSummary); track entry.labelKey) {
                        <span>{{ entry.labelKey | translate }}: {{ entry.text }}</span>
                      }
                    </div>
                  </div>
                }
                @if (defaultCategory(); as def) {
                  <div class="flex items-center gap-3 rounded-lg border border-dashed border-[var(--mat-sys-outline-variant)] px-3 py-2 opacity-60">
                    <mat-icon class="text-gray-400 shrink-0">lock</mat-icon>
                    <span class="w-8 shrink-0 text-xs font-mono text-gray-400">{{ orderedCategories().length + 1 }}</span>
                    <span class="w-40 shrink-0 text-sm font-medium">{{ ('category_names.' + def.name) | translate }}</span>
                    <span class="text-xs text-gray-500">{{ 'comparison.context.pinned_default_note' | translate }}</span>
                  </div>
                }
              </div>
            }
          </mat-card-content>
        </mat-card>
      } @else if (selectedContextEntry(); as ctx) {
        <!-- Named context: editable delta (promoted head order + exclusions) -->
        <mat-card>
          <mat-card-header class="!flex !items-start">
            <div class="flex-1">
              <mat-card-title>{{ ctx | scoringContextLabel }}</mat-card-title>
              <mat-card-subtitle>{{ 'comparison.context.delta_description' | translate }}</mat-card-subtitle>
            </div>
            <div class="flex gap-1 shrink-0">
              <button mat-icon-button
                [disabled]="!hasContextChanges() || savingContext()"
                (click)="resetContextDraft()"
                [matTooltip]="'comparison.reset' | translate"
                [attr.aria-label]="'comparison.reset' | translate">
                <mat-icon>refresh</mat-icon>
              </button>
              <button mat-icon-button
                [disabled]="contextSaveDisabled()"
                (click)="saveContext()"
                [matTooltip]="'comparison.save' | translate"
                [attr.aria-label]="'comparison.save' | translate">
                @if (savingContext()) {
                  <mat-spinner diameter="20" [attr.aria-label]="'ui.labels.loading' | translate" />
                } @else {
                  <mat-icon>save</mat-icon>
                }
              </button>
            </div>
          </mat-card-header>
        </mat-card>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <mat-card>
            <mat-card-header>
              <mat-card-title>{{ 'comparison.context.promote_title' | translate }}</mat-card-title>
              <mat-card-subtitle>{{ 'comparison.context.promote_description' | translate }}</mat-card-subtitle>
            </mat-card-header>
            <mat-card-content class="!pt-4">
              @if (draftPromote().length > 0) {
                <div cdkDropList class="flex flex-col gap-1.5" (cdkDropListDropped)="dropPromoted($event)">
                  @for (name of draftPromote(); track name; let i = $index) {
                    <div cdkDrag class="flex items-center gap-3 rounded-lg border border-[var(--mat-sys-outline-variant)] px-3 py-2 bg-[var(--mat-sys-surface-container)]">
                      <mat-icon cdkDragHandle class="text-gray-400 cursor-move shrink-0">drag_indicator</mat-icon>
                      <span class="w-8 shrink-0 text-xs font-mono text-gray-400">{{ i + 1 }}</span>
                      <span class="flex-1 text-sm">{{ ('category_names.' + name) | translate }}</span>
                      <button mat-icon-button class="shrink-0"
                        [disabled]="i === 0"
                        (click)="movePromotedUp(i)"
                        [matTooltip]="'comparison.context.move_up' | translate"
                        [attr.aria-label]="'comparison.context.move_up' | translate">
                        <mat-icon>arrow_upward</mat-icon>
                      </button>
                      <button mat-icon-button class="shrink-0"
                        [disabled]="i === draftPromote().length - 1"
                        (click)="movePromotedDown(i)"
                        [matTooltip]="'comparison.context.move_down' | translate"
                        [attr.aria-label]="'comparison.context.move_down' | translate">
                        <mat-icon>arrow_downward</mat-icon>
                      </button>
                      <button mat-icon-button class="shrink-0"
                        (click)="unpromoteCategory(name)"
                        [matTooltip]="'comparison.context.remove_promotion' | translate"
                        [attr.aria-label]="'comparison.context.remove_promotion' | translate">
                        <mat-icon>close</mat-icon>
                      </button>
                    </div>
                  }
                </div>
              } @else {
                <p class="text-sm text-gray-500">{{ 'comparison.context.no_promotions' | translate }}</p>
              }
              @if (promotableCategories().length > 0) {
                <div class="mt-4 pt-3 border-t border-[var(--mat-sys-outline-variant)]">
                  <h4 class="text-xs uppercase tracking-wide text-gray-500 mb-2">{{ 'comparison.context.add_promotion' | translate }}</h4>
                  <div class="flex flex-wrap gap-2">
                    @for (name of promotableCategories(); track name) {
                      <button type="button"
                        class="px-2 py-1 rounded-full text-xs border border-[var(--mat-sys-outline-variant)] text-gray-400 hover:text-gray-200 cursor-pointer"
                        (click)="promoteCategory(name)">
                        {{ ('category_names.' + name) | translate }}
                      </button>
                    }
                  </div>
                </div>
              }
            </mat-card-content>
          </mat-card>

          <mat-card>
            <mat-card-header>
              <mat-card-title>{{ 'comparison.context.excluded_title' | translate }}</mat-card-title>
              <mat-card-subtitle>{{ 'comparison.context.excluded_description' | translate }}</mat-card-subtitle>
            </mat-card-header>
            <mat-card-content class="!pt-4">
              <div class="flex flex-wrap gap-2">
                @for (chip of exclusionChips(); track chip.name) {
                  <button type="button"
                    class="cursor-pointer"
                    [class]="chip.excluded
                      ? 'px-2 py-1 rounded-full text-xs border border-red-500/30 bg-red-500/10 text-red-400'
                      : 'px-2 py-1 rounded-full text-xs border border-[var(--mat-sys-outline-variant)] text-gray-400 hover:text-gray-200'"
                    [attr.aria-pressed]="chip.excluded"
                    (click)="toggleExcluded(chip.name)">
                    {{ ('category_names.' + chip.name) | translate }}
                  </button>
                }
              </div>
              @if (draftExcluded().length === 0) {
                <p class="mt-3 text-sm text-gray-500">{{ 'comparison.context.no_exclusions' | translate }}</p>
              }
            </mat-card-content>
          </mat-card>
        </div>

        <mat-card>
          <mat-card-header>
            <mat-card-title>{{ 'comparison.context.effective_order_title' | translate }}</mat-card-title>
          </mat-card-header>
          <mat-card-content class="!pt-4">
            <div class="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-gray-400">
              @for (name of contextEffectiveOrder(); track name; let i = $index; let last = $last) {
                <span>{{ i + 1 }}.&nbsp;{{ ('category_names.' + name) | translate }}</span>
                @if (!last) { <span class="text-gray-600">&rarr;</span> }
              }
            </div>
          </mat-card-content>
        </mat-card>
      }

      <!-- Recompute affordance: available regardless of which context is selected. -->
      @if (stale()) {
        <mat-card>
          <mat-card-content class="!py-4 flex flex-col gap-3">
            <div class="flex items-center gap-2 text-sm text-amber-400">
              <mat-icon class="!text-base !w-4 !h-4">warning</mat-icon>
              {{ 'comparison.context.stale_notice' | translate }}
            </div>
            @if (recomputeMessageKey(); as messageKey) {
              <div class="text-sm text-red-400">{{ messageKey | translate }}</div>
            }
            @if (recomputing()) {
              <div class="flex flex-col gap-1.5">
                <mat-progress-bar [mode]="recomputeProgressPercent() === null ? 'indeterminate' : 'determinate'"
                  [value]="recomputeProgressPercent() ?? 0" />
                @if (recomputeStatus()?.progress; as p) {
                  <span class="text-xs text-gray-500">
                    {{ 'comparison.context.recompute_progress' | translate:{ current: p.current ?? 0, total: p.total ?? 0 } }}
                    @if (p.eta_seconds !== null && p.eta_seconds !== undefined) {
                      &middot; {{ 'comparison.context.recompute_eta' | translate:{ time: (p.eta_seconds | etaDuration) } }}
                    }
                  </span>
                }
              </div>
            } @else {
              <button mat-flat-button
                [disabled]="recomputeDisabled()"
                (click)="startRecompute()">
                <span class="inline-flex items-center gap-1.5">
                  <mat-icon class="!m-0">calculate</mat-icon>
                  {{ 'comparison.context.recompute_now' | translate }}
                </span>
              </button>
            }
          </mat-card-content>
        </mat-card>
      }

      <!-- Overlap panel (lazy: loaded when the tab is first activated) -->
      <mat-card>
        <mat-card-header class="!flex !items-start">
          <div class="flex-1">
            <mat-card-title>{{ 'comparison.context.overlap_title' | translate }}</mat-card-title>
            <mat-card-subtitle>{{ 'comparison.context.overlap_description' | translate }}</mat-card-subtitle>
          </div>
          <button mat-icon-button class="shrink-0"
            [disabled]="overlapLoading()"
            (click)="refreshOverlap()"
            [matTooltip]="'comparison.context.refresh_overlap' | translate"
            [attr.aria-label]="'comparison.context.refresh_overlap' | translate">
            <mat-icon>refresh</mat-icon>
          </button>
        </mat-card-header>
        <mat-card-content class="!pt-4 overflow-x-auto">
          @if (overlapLoading()) {
            <div class="flex justify-center py-8"><mat-spinner diameter="40" [attr.aria-label]="'ui.labels.loading' | translate" /></div>
          } @else if (sortedOverlapCategories().length > 0) {
            <table class="w-full text-sm">
              <thead>
                <tr class="text-gray-400 text-left border-b border-[var(--mat-sys-outline-variant)]">
                  <th class="pb-2 pr-4">{{ 'comparison.context.overlap_column_category' | translate }}</th>
                  <th class="pb-2 pr-4">{{ 'comparison.context.overlap_column_assigned' | translate }}</th>
                  <th class="pb-2 pr-4">{{ 'comparison.context.overlap_column_matched' | translate }}</th>
                  <th class="pb-2">{{ 'comparison.context.overlap_column_captured' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (cat of sortedOverlapCategories(); track cat.name) {
                  <tr class="border-b border-[var(--mat-sys-outline-variant)] hover:bg-[var(--mat-sys-surface-container)]">
                    <td class="py-1.5 pr-4 font-medium">{{ ('category_names.' + cat.name) | translate }}</td>
                    <td class="py-1.5 pr-4 text-gray-300">{{ cat.assigned }}</td>
                    <td class="py-1.5 pr-4 text-gray-300">{{ cat.matched }}</td>
                    <td class="py-1.5" [class.text-amber-400]="cat.captured_by_higher > 0" [class.font-semibold]="cat.captured_by_higher > 0">
                      {{ cat.captured_by_higher }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          } @else if (overlapLoaded()) {
            <p class="text-sm text-gray-500">{{ 'comparison.context.overlap_empty' | translate }}</p>
          }
          @if (topOverlapPairs().length > 0) {
            <div class="mt-4 pt-3 border-t border-[var(--mat-sys-outline-variant)]">
              <h4 class="text-xs uppercase tracking-wide text-gray-500 mb-2">{{ 'comparison.context.overlap_pairs_title' | translate }}</h4>
              <ul class="flex flex-col gap-1 text-sm">
                @for (pair of topOverlapPairs(); track pair.pair[0] + pair.pair[1]) {
                  <li class="flex items-center justify-between gap-2">
                    <span class="text-gray-300">
                      {{ ('category_names.' + pair.pair[0]) | translate }} + {{ ('category_names.' + pair.pair[1]) | translate }}
                    </span>
                    <span class="font-mono text-amber-400 shrink-0">{{ pair.count }}</span>
                  </li>
                }
              </ul>
            </div>
          }
        </mat-card-content>
      </mat-card>
    </div>
  `,
})
export class ComparisonPriorityTabComponent {
  protected readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  readonly contexts = signal<ScoringContextEntry[]>([]);
  readonly selectedContext = signal<string>(DEFAULT_CATEGORY_NAME);

  readonly categories = signal<CategoryPriorityEntry[]>([]);
  readonly orderedCategories = signal<CategoryPriorityEntry[]>([]);
  readonly savedOrder = signal<string[]>([]);
  readonly categoriesLoading = signal(false);
  readonly saving = signal(false);

  readonly draftPromote = signal<string[]>([]);
  readonly draftExcluded = signal<string[]>([]);
  readonly savingContext = signal(false);

  readonly overlap = signal<CategoryOverlapResponse | null>(null);
  readonly overlapLoading = signal(false);
  readonly overlapLoaded = signal(false);

  readonly stale = signal(false);
  readonly recomputing = signal(false);
  readonly recomputeStatus = signal<RecomputeStatus | null>(null);
  readonly recomputeMessageKey = signal<string | null>(null);
  private recomputePollTimer: ReturnType<typeof setInterval> | null = null;

  readonly isDefaultContext = computed(() => this.selectedContext() === DEFAULT_CATEGORY_NAME);
  readonly selectedContextEntry = computed(() =>
    this.contexts().find(c => c.name === this.selectedContext()) ?? null,
  );
  readonly defaultCategory = computed(() =>
    this.categories().find(c => c.name === DEFAULT_CATEGORY_NAME) ?? null,
  );
  readonly hasOrderChanges = computed(() =>
    JSON.stringify(this.orderedCategories().map(c => c.name)) !== JSON.stringify(this.savedOrder()),
  );
  readonly saveDisabled = computed(() =>
    this.saving() || !this.hasOrderChanges() || !this.auth.isEdition(),
  );
  readonly nonDefaultCategoryNames = computed(() =>
    this.categories().filter(c => c.name !== DEFAULT_CATEGORY_NAME).map(c => c.name),
  );
  readonly promotableCategories = computed(() => {
    const promoted = new Set(this.draftPromote());
    return this.nonDefaultCategoryNames().filter(name => !promoted.has(name));
  });
  readonly exclusionChips = computed<ExclusionChip[]>(() => {
    const excluded = new Set(this.draftExcluded());
    return this.nonDefaultCategoryNames().map(name => ({ name, excluded: excluded.has(name) }));
  });
  /**
   * Mirrors `ScoringConfig.resolve_context_order`: the promoted head (minus anything
   * also excluded) → the global priority order minus promoted and excluded → the pinned
   * `default` last. Computed from the DRAFT delta so the resulting order stays visible
   * while editing; falls back to the server's saved order when the global priority list
   * isn't loaded.
   */
  readonly contextEffectiveOrder = computed(() => {
    const globalNames = this.nonDefaultCategoryNames();
    if (globalNames.length === 0) return this.selectedContextEntry()?.effective_order ?? [];
    const excluded = new Set(this.draftExcluded());
    const promoted = this.draftPromote().filter(name => !excluded.has(name));
    const promotedSet = new Set(promoted);
    const rest = globalNames.filter(name => !excluded.has(name) && !promotedSet.has(name));
    return [...promoted, ...rest, DEFAULT_CATEGORY_NAME];
  });
  readonly hasContextChanges = computed(() => {
    const ctx = this.selectedContextEntry();
    if (!ctx) return false;
    return JSON.stringify(this.draftPromote()) !== JSON.stringify(ctx.promote)
      || JSON.stringify(this.draftExcluded()) !== JSON.stringify(ctx.excluded);
  });
  readonly contextSaveDisabled = computed(() =>
    this.savingContext() || !this.hasContextChanges() || !this.auth.isEdition(),
  );
  readonly recomputeDisabled = computed(() =>
    this.recomputing() || !this.auth.isEdition(),
  );
  readonly sortedOverlapCategories = computed(() =>
    [...(this.overlap()?.per_category ?? [])]
      .filter(c => c.name !== DEFAULT_CATEGORY_NAME)
      .sort((a, b) => b.captured_by_higher - a.captured_by_higher),
  );
  readonly topOverlapPairs = computed(() =>
    [...(this.overlap()?.overlaps ?? [])]
      .filter(p => !p.pair.includes(DEFAULT_CATEGORY_NAME))
      .sort((a, b) => b.count - a.count)
      .slice(0, MAX_OVERLAP_PAIRS),
  );
  readonly recomputeProgressPercent = computed(() => {
    const p = this.recomputeStatus()?.progress;
    if (!p || !p.total) return null;
    return Math.min(100, Math.round(((p.current ?? 0) / p.total) * 100));
  });

  constructor() {
    void this.loadContexts();
    void this.loadCategories();
    this.destroyRef.onDestroy(() => this.stopRecomputePolling());
  }

  /** Loads the overlap panel once; safe to call repeatedly (e.g. on every tab activation). */
  activateOverlap(): void {
    void this.loadOverlapLazily();
  }

  selectContext(name: string): void {
    this.selectedContext.set(name);
    this.resetContextDraft();
  }

  resetContextDraft(): void {
    const ctx = this.selectedContextEntry();
    this.draftPromote.set([...(ctx?.promote ?? [])]);
    this.draftExcluded.set([...(ctx?.excluded ?? [])]);
  }

  dropPromoted(event: CdkDragDrop<string[]>): void {
    this.movePromoted(event.previousIndex, event.currentIndex);
  }

  movePromotedUp(index: number): void {
    if (index <= 0) return;
    this.movePromoted(index, index - 1);
  }

  movePromotedDown(index: number): void {
    if (index >= this.draftPromote().length - 1) return;
    this.movePromoted(index, index + 1);
  }

  private movePromoted(from: number, to: number): void {
    const arr = [...this.draftPromote()];
    moveItemInArray(arr, from, to);
    this.draftPromote.set(arr);
  }

  promoteCategory(name: string): void {
    if (this.draftPromote().includes(name)) return;
    this.draftPromote.set([...this.draftPromote(), name]);
  }

  unpromoteCategory(name: string): void {
    this.draftPromote.set(this.draftPromote().filter(n => n !== name));
  }

  toggleExcluded(name: string): void {
    const current = this.draftExcluded();
    this.draftExcluded.set(
      current.includes(name) ? current.filter(n => n !== name) : [...current, name],
    );
  }

  drop(event: CdkDragDrop<CategoryPriorityEntry[]>): void {
    const arr = [...this.orderedCategories()];
    moveItemInArray(arr, event.previousIndex, event.currentIndex);
    this.orderedCategories.set(arr);
  }

  resetOrder(): void {
    const byName = new Map(this.categories().map(c => [c.name, c]));
    const restored = this.savedOrder()
      .map(name => byName.get(name))
      .filter((c): c is CategoryPriorityEntry => !!c);
    this.orderedCategories.set(restored);
  }

  /** `reseedContext` scopes the draft re-seed to that one context: a selection that
   *  moved on while a save was in flight keeps its own unsaved edits. */
  async loadContexts(reseedContext?: string): Promise<void> {
    try {
      const data = await firstValueFrom(
        this.api.get<{ contexts: ScoringContextEntry[] }>('/config/scoring_contexts'),
      );
      this.contexts.set(data.contexts ?? []);
      if (reseedContext === undefined || reseedContext === this.selectedContext()) {
        this.resetContextDraft();
      }
    } catch {
      this.snackBar.open(this.i18n.t('comparison.context.error_loading_contexts'), '', { duration: 4000 });
    }
  }

  async saveContext(): Promise<void> {
    const ctx = this.selectedContextEntry();
    if (!ctx || !this.hasContextChanges()) return;
    this.savingContext.set(true);
    try {
      await firstValueFrom(
        this.api.put(`/config/scoring_contexts/${ctx.name}`, {
          promote: this.draftPromote(),
          excluded: this.draftExcluded(),
        }),
      );
      this.stale.set(true);
      this.recomputeMessageKey.set(null);
      this.snackBar.open(this.i18n.t('comparison.context.context_saved'), '', { duration: 3000 });
      await this.loadContexts(ctx.name);
    } catch {
      this.snackBar.open(this.i18n.t('comparison.context.error_saving_context'), '', { duration: 4000 });
    } finally {
      this.savingContext.set(false);
    }
  }

  async loadCategories(): Promise<void> {
    this.categoriesLoading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<{ categories: CategoryPriorityEntry[] }>('/config/category_priorities'),
      );
      const cats = data.categories ?? [];
      this.categories.set(cats);
      const nonDefault = cats.filter(c => c.name !== DEFAULT_CATEGORY_NAME);
      this.orderedCategories.set(nonDefault);
      this.savedOrder.set(nonDefault.map(c => c.name));
    } catch {
      this.snackBar.open(this.i18n.t('comparison.context.error_loading_categories'), '', { duration: 4000 });
    } finally {
      this.categoriesLoading.set(false);
    }
  }

  async saveOrder(): Promise<void> {
    if (!this.hasOrderChanges()) return;
    this.saving.set(true);
    try {
      await firstValueFrom(
        this.api.post('/config/category_priorities', { order: this.orderedCategories().map(c => c.name) }),
      );
      this.savedOrder.set(this.orderedCategories().map(c => c.name));
      this.stale.set(true);
      this.recomputeMessageKey.set(null);
      this.snackBar.open(this.i18n.t('comparison.context.priorities_saved'), '', { duration: 3000 });
      void this.loadCategories();
      this.overlapLoaded.set(false);
    } catch {
      this.snackBar.open(this.i18n.t('comparison.context.error_saving_priorities'), '', { duration: 4000 });
    } finally {
      this.saving.set(false);
    }
  }

  async loadOverlapLazily(): Promise<void> {
    if (this.overlapLoaded() || this.overlapLoading()) return;
    this.overlapLoading.set(true);
    try {
      const data = await firstValueFrom(this.api.get<CategoryOverlapResponse>('/stats/categories/overlap'));
      this.overlap.set(data);
      this.overlapLoaded.set(true);
    } catch {
      this.snackBar.open(this.i18n.t('comparison.context.error_loading_overlap'), '', { duration: 4000 });
    } finally {
      this.overlapLoading.set(false);
    }
  }

  refreshOverlap(): void {
    this.overlapLoaded.set(false);
    void this.loadOverlapLazily();
  }

  async startRecompute(): Promise<void> {
    if (this.recomputing()) return;
    this.recomputing.set(true);
    this.recomputeMessageKey.set(null);
    this.recomputeStatus.set(null);
    try {
      await firstValueFrom(this.api.post('/scan/recompute', { confirm: true }));
      void this.pollRecomputeStatus();
      this.recomputePollTimer = setInterval(() => void this.pollRecomputeStatus(), 1500);
    } catch (err) {
      this.recomputing.set(false);
      if (err instanceof HttpErrorResponse && err.status === 409) {
        this.recomputeMessageKey.set('comparison.context.recompute_conflict');
      } else {
        this.recomputeMessageKey.set('comparison.context.error_recompute');
      }
    }
  }

  private async pollRecomputeStatus(): Promise<void> {
    try {
      const status = await firstValueFrom(this.api.get<RecomputeStatus>('/scan/recompute_status'));
      this.recomputeStatus.set(status);
      if (!status.running) {
        this.stopRecomputePolling();
        this.recomputing.set(false);
        // `_scan_state` is a per-PROCESS module global on a multi-worker
        // deployment: a poll served by a worker that never saw the POST (or
        // that is reporting on a concurrent scan, kind !== 'recompute')
        // cannot be trusted as either success or failure -- report it as
        // indeterminate rather than guessing.
        if (status.kind !== JOB_KIND_RECOMPUTE || status.exit_code === null) {
          this.recomputeMessageKey.set('comparison.context.recompute_unknown');
        } else if (status.exit_code === 0) {
          this.stale.set(false);
          this.snackBar.open(this.i18n.t('comparison.context.recompute_done'), '', { duration: 4000 });
        } else {
          this.recomputeMessageKey.set('comparison.context.recompute_failed');
        }
      }
    } catch {
      this.stopRecomputePolling();
      this.recomputing.set(false);
      this.recomputeMessageKey.set('comparison.context.recompute_unknown');
    }
  }

  private stopRecomputePolling(): void {
    if (this.recomputePollTimer) {
      clearInterval(this.recomputePollTimer);
      this.recomputePollTimer = null;
    }
  }
}
