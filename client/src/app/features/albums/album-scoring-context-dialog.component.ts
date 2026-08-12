import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumService, AlbumScoringContextResult, AlbumSuggestedContext } from '../../core/services/album.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ScoringContextLabelPipe, resolveScoringContextLabel } from '../../shared/pipes/scoring-context-label.pipe';

export interface AlbumScoringContextDialogData {
  albumId: number;
  albumName: string;
  currentContext: string | null;
}

interface ScoringContextOption {
  name: string;
  label_key: string;
}

interface RecomputeProgress {
  phase: string;
  current?: number;
  total?: number;
  eta_seconds?: number;
}

interface RecomputeStatusResponse {
  running: boolean;
  kind: string | null;
  progress: RecomputeProgress | null;
  exit_code: number | null;
}

type Phase = 'select' | 'saving' | 'saved' | 'recomputing' | 'recompute_done' | 'recompute_error';

const DEFAULT_CONTEXT = 'default';

/**
 * Edition-only "Scoring context" dialog for an album: pick from the configured
 * contexts (suggested from the album's dominant narrative moment, never
 * auto-applied), save via the dedicated materializing endpoint, then offer an
 * in-place recompute with a polled progress bar.
 */
@Component({
  selector: 'app-album-scoring-context-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MatDialogModule, MatButtonModule, MatFormFieldModule, MatSelectModule,
    MatProgressSpinnerModule, MatProgressBarModule, TranslatePipe, ScoringContextLabelPipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate">{{ 'albums.scoring_context.dialog_title' | translate:{ name: data.albumName } }}</h2>
    <mat-dialog-content class="!pt-2 min-w-[20rem] max-w-[28rem]">
      @if (loading()) {
        <div class="flex justify-center py-6">
          <mat-spinner diameter="28" />
        </div>
      } @else {
        <p class="text-sm opacity-70 mb-3">{{ 'albums.scoring_context.description' | translate }}</p>

        <mat-form-field class="w-full">
          <mat-label>{{ 'albums.scoring_context.label' | translate }}</mat-label>
          <mat-select [value]="selectedContext()" [disabled]="phase() !== 'select'"
                      (selectionChange)="selectedContext.set($event.value)">
            @for (context of contexts(); track context.name) {
              <mat-option [value]="context.name">{{ context | scoringContextLabel }}</mat-option>
            }
          </mat-select>
        </mat-form-field>

        @if (suggestion(); as s) {
          @if (s.suggested && s.moment && s.suggested !== selectedContext()) {
            <div class="flex items-center gap-2 text-xs opacity-70 -mt-2 mb-3">
              <span>
                {{ 'albums.scoring_context.suggested_hint' | translate:{ context: suggestedLabel(), percent: '' + suggestedPercent(), moment: s.moment } }}
              </span>
              <button mat-button class="!min-w-0 !px-2" (click)="selectedContext.set(s.suggested!)">
                {{ 'albums.scoring_context.apply_suggestion' | translate }}
              </button>
            </div>
          }
        }

        @if (phase() === 'saved' || phase() === 'recomputing' || phase() === 'recompute_done' || phase() === 'recompute_error') {
          <div class="rounded-lg bg-[var(--mat-sys-surface-container)] p-3 text-sm mt-2">
            @if (warning(); as w) {
              <p class="text-amber-400 mb-2">{{ w | translate }}</p>
            }
            @if (conflicts() > 0) {
              <p class="text-amber-400 mb-2">
                {{ 'albums.scoring_context.conflict_warning' | translate:{ count: '' + conflicts() } }}
              </p>
            }
            @if (manualSkipped() > 0) {
              <p class="text-amber-400 mb-2">
                {{ 'albums.scoring_context.manual_skipped_note' | translate:{ count: '' + manualSkipped() } }}
              </p>
            }
            <p class="opacity-70 mb-2">
              {{ (cleared() ? 'albums.scoring_context.cleared_success' : 'albums.scoring_context.saved_success') | translate:{ count: '' + updatedCount() } }}
            </p>
            <p class="opacity-60 text-xs mb-2">{{ 'albums.scoring_context.membership_note' | translate }}</p>

            @if (phase() === 'saved') {
              <p class="mb-2">{{ 'albums.scoring_context.recompute_prompt' | translate }}</p>
              @if (recomputeError(); as e) {
                <p class="text-red-400 text-xs mb-2">
                  {{ (e === 'busy' ? 'albums.scoring_context.recompute_busy' : 'albums.scoring_context.recompute_failed') | translate }}
                </p>
              }
              <div class="flex gap-2 justify-end">
                <button mat-button (click)="close()">{{ 'albums.scoring_context.recompute_skip' | translate }}</button>
                <button mat-flat-button (click)="recompute()">{{ 'albums.scoring_context.recompute_button' | translate }}</button>
              </div>
            }

            @if (phase() === 'recomputing') {
              <p class="mb-2">{{ 'albums.scoring_context.recomputing' | translate }}</p>
              <mat-progress-bar [mode]="progressValue() === null ? 'indeterminate' : 'determinate'"
                                [value]="progressValue() ?? 0" />
            }

            @if (phase() === 'recompute_done') {
              <p class="text-green-400">{{ 'albums.scoring_context.recompute_done' | translate }}</p>
            }

            @if (phase() === 'recompute_error') {
              <p class="text-red-400">{{ 'albums.scoring_context.recompute_failed' | translate }}</p>
            }
          </div>
        }
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (phase() === 'select' || phase() === 'saving') {
        <button mat-button (click)="cancel()">{{ 'ui.buttons.cancel' | translate }}</button>
        @if (data.currentContext) {
          <button mat-button [disabled]="loading() || phase() === 'saving'" (click)="clear()">
            {{ 'albums.scoring_context.clear_button' | translate }}
          </button>
        }
        <button mat-flat-button [disabled]="loading() || phase() === 'saving'" (click)="save()">
          {{ phase() === 'saving' ? ('ui.buttons.saving' | translate) : ('ui.buttons.save' | translate) }}
        </button>
      } @else {
        <button mat-button (click)="close()">{{ 'albums.scoring_context.close' | translate }}</button>
      }
    </mat-dialog-actions>
  `,
})
export class AlbumScoringContextDialogComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly albumService = inject(AlbumService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialogRef = inject(MatDialogRef<AlbumScoringContextDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly data = inject<AlbumScoringContextDialogData>(MAT_DIALOG_DATA);

  protected readonly loading = signal(true);
  protected readonly contexts = signal<ScoringContextOption[]>([]);
  protected readonly suggestion = signal<AlbumSuggestedContext | null>(null);
  protected readonly selectedContext = signal(this.data.currentContext ?? DEFAULT_CONTEXT);

  protected readonly phase = signal<Phase>('select');
  protected readonly updatedCount = signal(0);
  protected readonly conflicts = signal(0);
  protected readonly manualSkipped = signal(0);
  protected readonly warning = signal<string | null>(null);
  protected readonly cleared = signal(false);
  private persisted = false;
  private persistedContext: string | null = null;
  private closeRequested = false;
  protected readonly recomputeError = signal<'busy' | 'failed' | null>(null);
  protected readonly recomputeProgress = signal<RecomputeProgress | null>(null);

  protected readonly suggestedLabel = computed(() => {
    const suggested = this.suggestion()?.suggested;
    if (!suggested) return '';
    const context = this.contexts().find(c => c.name === suggested);
    return context ? resolveScoringContextLabel(context, this.i18n.t(context.label_key)) : suggested;
  });
  protected readonly suggestedPercent = computed(() => Math.round((this.suggestion()?.share ?? 0) * 100));

  protected readonly progressValue = computed(() => {
    const p = this.recomputeProgress();
    if (!p || !p.total) return null;
    return Math.round(((p.current ?? 0) / p.total) * 100);
  });

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    const contextsPromise = firstValueFrom(this.api.get<{ contexts: ScoringContextOption[] }>('/config/scoring_contexts'));
    const suggestionPromise = firstValueFrom(this.albumService.getSuggestedContext(this.data.albumId)).catch(() => null);

    try {
      this.contexts.set((await contextsPromise).contexts);
    } catch {
      this.contexts.set([{ name: DEFAULT_CONTEXT, label_key: 'albums.scoring_context.label' }]);
      this.snackBar.open(this.i18n.t('notifications.connection_error'), '', { duration: 3000 });
    }

    this.suggestion.set(await suggestionPromise);

    this.loading.set(false);
  }

  private applySavedResult(res: AlbumScoringContextResult, context: string | null, cleared: boolean): void {
    this.updatedCount.set(res.updated);
    this.conflicts.set(res.conflicts);
    this.manualSkipped.set(res.manual_skipped);
    this.warning.set(res.warning ? 'albums.scoring_context.empty_warning' : null);
    this.cleared.set(cleared);
    this.persistedContext = context;
    this.persisted = true;
    this.phase.set('saved');
  }

  protected async save(): Promise<void> {
    if (this.phase() === 'saving') return;
    this.phase.set('saving');
    const context = this.selectedContext();
    try {
      const res = await firstValueFrom(this.albumService.setScoringContext(this.data.albumId, context));
      this.applySavedResult(res, context, false);
    } catch {
      this.phase.set('select');
      if (!this.closeRequested) {
        this.snackBar.open(this.i18n.t('errors.action_failed'), '', { duration: 3000 });
      }
    }
    if (this.closeRequested) this.close();
  }

  protected async clear(): Promise<void> {
    if (this.phase() === 'saving') return;
    this.phase.set('saving');
    try {
      const res = await firstValueFrom(this.albumService.clearScoringContext(this.data.albumId));
      this.applySavedResult({ updated: res.cleared, conflicts: 0, manual_skipped: 0 }, null, true);
    } catch {
      this.phase.set('select');
      if (!this.closeRequested) {
        this.snackBar.open(this.i18n.t('errors.action_failed'), '', { duration: 3000 });
      }
    }
    if (this.closeRequested) this.close();
  }

  protected cancel(): void {
    if (this.phase() === 'saving') {
      this.closeRequested = true;
      return;
    }
    this.close();
  }

  protected async recompute(): Promise<void> {
    if (this.phase() !== 'saved') return;
    this.phase.set('recomputing');
    this.recomputeError.set(null);
    try {
      await firstValueFrom(this.api.post('/scan/recompute', { confirm: true }));
    } catch (err: unknown) {
      this.phase.set('saved');
      this.recomputeError.set(err instanceof HttpErrorResponse && err.status === 409 ? 'busy' : 'failed');
      return;
    }
    this.pollTimer = setInterval(() => this.pollRecomputeStatus(), 1000);
    this.pollRecomputeStatus();
  }

  private async pollRecomputeStatus(): Promise<void> {
    try {
      const status = await firstValueFrom(this.api.get<RecomputeStatusResponse>('/scan/recompute_status'));
      this.recomputeProgress.set(status.progress);
      if (!status.running) {
        this.stopPolling();
        this.phase.set(status.exit_code === 0 ? 'recompute_done' : 'recompute_error');
      }
    } catch {
      this.stopPolling();
      this.phase.set('recompute_error');
    }
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  protected close(): void {
    this.dialogRef.close(this.persisted ? this.persistedContext : undefined);
  }
}
