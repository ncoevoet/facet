import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

type CullAction = 'copy_keeps' | 'trash_rejects' | 'move_rejects';

interface CullResponse {
  would_copy?: string[];
  would_move?: string[];
  would_trash?: string[];
  skipped?: string[];
  copied?: number;
  moved?: number;
  trashed?: number;
}

/**
 * Edition-only "Cull to folder…" dialog. Defaults to the additive copy action
 * and always previews (dry-run) before any destructive apply. Move/trash need a
 * second, explicit click after the preview.
 */
@Component({
  selector: 'app-cull-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatCheckboxModule,
            MatProgressSpinnerModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ 'cull.title' | translate }}</h2>
    <mat-dialog-content class="!pt-2 min-w-[22rem] max-w-[32rem]">
      <p class="text-sm opacity-70 mb-3">{{ count }} {{ 'cull.selected' | translate }}</p>

      <div class="flex flex-col gap-1 mb-3">
        @for (a of actions; track a) {
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="cullAction" [value]="a"
                   [checked]="action() === a" (change)="setAction(a)" />
            <span class="text-sm">{{ 'cull.' + a | translate }}</span>
          </label>
        }
      </div>

      @if (needsTarget()) {
        <label for="cullTargetDir" class="block text-xs opacity-60 mb-1">{{ 'cull.target_dir' | translate }}</label>
        <input id="cullTargetDir" type="text" [value]="targetDir()" (input)="onTargetInput($event)"
               class="w-full text-sm font-mono rounded border border-[var(--mat-sys-outline-variant)] bg-transparent px-2 py-1.5 mb-3"
               placeholder="/path/to/folder" />
      }

      <mat-checkbox [checked]="includeCompanions()" (change)="includeCompanions.set($event.checked)"
                    class="text-sm">
        {{ 'cull.include_companions' | translate }}
      </mat-checkbox>

      @if (preview(); as p) {
        <div class="mt-3 p-2 rounded bg-[var(--mat-sys-surface-container)] text-sm">
          <p>{{ p.affected.length }} {{ 'cull.would_affect' | translate }}</p>
          @if (p.skipped.length) {
            <p class="opacity-60">{{ p.skipped.length }} {{ 'cull.skipped' | translate }}</p>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'cull.cancel' | translate }}</button>
      <button mat-stroked-button [disabled]="busy() || (needsTarget() && !targetDir())"
              (click)="runPreview()">
        @if (busy()) { <mat-spinner diameter="16" class="!inline-block !align-middle !mr-1" /> }
        {{ 'cull.preview' | translate }}
      </button>
      <button mat-flat-button color="primary"
              [disabled]="busy() || !preview() || (needsTarget() && !targetDir())"
              (click)="apply()">
        {{ 'cull.apply' | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class CullDialogComponent {
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly dialogRef = inject(MatDialogRef<CullDialogComponent>);
  private readonly data = inject<{ paths: string[] }>(MAT_DIALOG_DATA);

  protected readonly actions: CullAction[] = ['copy_keeps', 'move_rejects', 'trash_rejects'];
  protected readonly action = signal<CullAction>('copy_keeps');
  protected readonly targetDir = signal('');
  protected readonly includeCompanions = signal(false);
  protected readonly preview = signal<{ affected: string[]; skipped: string[] } | null>(null);
  protected readonly busy = signal(false);

  protected readonly needsTarget = computed(() => this.action() !== 'trash_rejects');
  protected get count(): number {
    return this.data.paths.length;
  }

  protected setAction(a: CullAction): void {
    this.action.set(a);
    this.preview.set(null);
  }

  protected onTargetInput(event: Event): void {
    this.targetDir.set((event.target as HTMLInputElement).value);
    this.preview.set(null);
  }

  private body(dryRun: boolean) {
    return {
      paths: this.data.paths,
      action: this.action(),
      target_dir: this.needsTarget() ? this.targetDir() : null,
      include_companions: this.includeCompanions(),
      dry_run: dryRun,
    };
  }

  async runPreview(): Promise<void> {
    this.busy.set(true);
    try {
      const res = await firstValueFrom(this.api.post<CullResponse>('/cull/apply', this.body(true)));
      const affected = res.would_copy ?? res.would_move ?? res.would_trash ?? [];
      this.preview.set({ affected, skipped: res.skipped ?? [] });
    } catch {
      this.snackBar.open(this.i18n.t('cull.error'), '', { duration: 3000 });
    } finally {
      this.busy.set(false);
    }
  }

  async apply(): Promise<void> {
    this.busy.set(true);
    try {
      await firstValueFrom(this.api.post<CullResponse>('/cull/apply', this.body(false)));
      this.snackBar.open(this.i18n.t('cull.done'), '', { duration: 2500 });
      this.dialogRef.close(true);
    } catch {
      this.snackBar.open(this.i18n.t('cull.error'), '', { duration: 3000 });
    } finally {
      this.busy.set(false);
    }
  }
}
