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
import { AlbumService, AlbumSuggestedContext } from '../../core/services/album.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

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
    MatProgressSpinnerModule, MatProgressBarModule, TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate">{{ I18N.albums.scoring_context.dialog_title | translate:{ name: data.albumName } }}</h2>
    <mat-dialog-content class="!pt-2 min-w-[20rem] max-w-[28rem]">
      @if (loading()) {
        <div class="flex justify-center py-6">
          <mat-spinner diameter="28" />
        </div>
      } @else {
        <p class="text-sm opacity-70 mb-3">{{ I18N.albums.scoring_context.description | translate }}</p>

        <mat-form-field class="w-full">
          <mat-label>{{ I18N.albums.scoring_context.label | translate }}</mat-label>
          <mat-select [value]="selectedContext()" [disabled]="phase() !== 'select'"
                      (selectionChange)="selectedContext.set($event.value)">
            @for (context of contexts(); track context.name) {
              <mat-option [value]="context.name">{{ context.label_key | translate }}</mat-option>
            }
          </mat-select>
        </mat-form-field>

        @if (suggestion(); as s) {
          @if (s.suggested && s.moment && s.suggested !== selectedContext()) {
            <div class="flex items-center gap-2 text-xs opacity-70 -mt-2 mb-3">
              <span>
                {{ I18N.albums.scoring_context.suggested_hint | translate:{ context: suggestedLabel(), percent: '' + suggestedPercent(), moment: s.moment } }}
              </span>
              <button mat-button class="!min-w-0 !px-2" (click)="selectedContext.set(s.suggested!)">
                {{ I18N.albums.scoring_context.apply_suggestion | translate }}
              </button>
            </div>
          }
        }

        @if (phase() === 'saved' || phase() === 'recomputing' || phase() === 'recompute_done' || phase() === 'recompute_error') {
          <div class="rounded-lg bg-[var(--mat-sys-surface-container)] p-3 text-sm mt-2">
            @if (conflicts() > 0) {
              <p class="text-amber-400 mb-2">
                {{ I18N.albums.scoring_context.conflict_warning | translate:{ count: '' + conflicts() } }}
              </p>
            }
            <p class="opacity-70 mb-2">{{ I18N.albums.scoring_context.saved_success | translate:{ count: '' + updatedCount() } }}</p>

            @if (phase() === 'saved') {
              <p class="mb-2">{{ I18N.albums.scoring_context.recompute_prompt | translate }}</p>
              @if (recomputeError(); as e) {
                <p class="text-red-400 text-xs mb-2">
                  {{ (e === 'busy' ? I18N.albums.scoring_context.recompute_busy : I18N.albums.scoring_context.recompute_failed) | translate }}
                </p>
              }
              <div class="flex gap-2 justify-end">
                <button mat-button (click)="close()">{{ I18N.albums.scoring_context.recompute_skip | translate }}</button>
                <button mat-flat-button (click)="recompute()">{{ I18N.albums.scoring_context.recompute_button | translate }}</button>
              </div>
            }

            @if (phase() === 'recomputing') {
              <p class="mb-2">{{ I18N.albums.scoring_context.recomputing | translate }}</p>
              <mat-progress-bar [mode]="progressValue() === null ? 'indeterminate' : 'determinate'"
                                [value]="progressValue() ?? 0" />
            }

            @if (phase() === 'recompute_done') {
              <p class="text-green-400">{{ I18N.albums.scoring_context.recompute_done | translate }}</p>
            }

            @if (phase() === 'recompute_error') {
              <p class="text-red-400">{{ I18N.albums.scoring_context.recompute_failed | translate }}</p>
            }
          </div>
        }
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (phase() === 'select' || phase() === 'saving') {
        <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
        <button mat-flat-button [disabled]="loading() || phase() === 'saving'" (click)="save()">
          {{ phase() === 'saving' ? (I18N.ui.buttons.saving | translate) : (I18N.ui.buttons.save | translate) }}
        </button>
      } @else if (phase() === 'recompute_done' || phase() === 'recompute_error') {
        <button mat-button (click)="close()">{{ I18N.albums.scoring_context.close | translate }}</button>
      }
    </mat-dialog-actions>
  `,
})
export class AlbumScoringContextDialogComponent implements OnInit {
  protected readonly I18N = I18N;
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
  private persistedContext: string | null = null;
  protected readonly recomputeError = signal<'busy' | 'failed' | null>(null);
  protected readonly recomputeProgress = signal<RecomputeProgress | null>(null);

  protected readonly suggestedLabel = computed(() => {
    const suggested = this.suggestion()?.suggested;
    if (!suggested) return '';
    const context = this.contexts().find(c => c.name === suggested);
    return context ? this.i18n.t(context.label_key) : suggested;
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
    const suggestionPromise = firstValueFrom(this.albumService.getSuggestedContext(this.data.albumId));

    try {
      this.contexts.set((await contextsPromise).contexts);
    } catch {
      this.contexts.set([{ name: DEFAULT_CONTEXT, label_key: I18N.albums.scoring_context.label }]);
      this.snackBar.open(this.i18n.t(I18N.notifications.connection_error), '', { duration: 3000 });
    }

    try {
      this.suggestion.set(await suggestionPromise);
    } catch {
      this.suggestion.set(null);
    }

    this.loading.set(false);
  }

  protected async save(): Promise<void> {
    if (this.phase() === 'saving') return;
    this.phase.set('saving');
    const context = this.selectedContext();
    try {
      const res = await firstValueFrom(this.albumService.setScoringContext(this.data.albumId, context));
      this.updatedCount.set(res.updated);
      this.conflicts.set(res.conflicts);
      this.persistedContext = context;
      this.phase.set('saved');
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
      this.phase.set('select');
    }
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
    this.dialogRef.close(this.persistedContext);
  }
}
