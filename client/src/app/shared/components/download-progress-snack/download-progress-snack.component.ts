import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MAT_SNACK_BAR_DATA, MatSnackBarAction, MatSnackBarActions, MatSnackBarLabel } from '@angular/material/snack-bar';
import type { DownloadProgressState } from '../../../core/services/download-progress.service';
import { i18nKeys } from '../../../core/i18n/keys';
import { TranslatePipe } from '../../pipes/translate.pipe';

/** Snackbar body for a batch download: running count, a determinate bar and Cancel. */
@Component({
  selector: 'app-download-progress-snack',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatButtonModule, MatProgressBarModule, MatSnackBarLabel, MatSnackBarActions, MatSnackBarAction, TranslatePipe],
  host: { class: 'flex items-center gap-2' },
  template: `
    <div matSnackBarLabel class="flex min-w-56 flex-col gap-2">
      <span>
        {{ I18N.gallery.selection.download_progress | translate: counts() }}
        @if (state.failed()) {
          · {{ I18N.gallery.selection.download_progress_failed | translate: failedVars() }}
        }
      </span>
      <mat-progress-bar mode="determinate" [value]="percent()"
        class="[--mat-progress-bar-active-indicator-color:var(--mat-sys-inverse-primary)]"
        [attr.aria-label]="I18N.photo_detail.downloading | translate" />
    </div>
    <div matSnackBarActions>
      <button mat-button matSnackBarAction (click)="state.cancel()">{{ I18N.ui.buttons.cancel | translate }}</button>
    </div>
  `,
})
export class DownloadProgressSnackComponent {
  protected readonly I18N = i18nKeys();
  protected readonly state = inject<DownloadProgressState>(MAT_SNACK_BAR_DATA);
  /** Names the file in flight ("1 of 12" while the first downloads); the bar shows what has finished. */
  protected readonly counts = computed(() => ({ done: Math.min(this.state.done() + 1, this.state.total), total: this.state.total }));
  protected readonly failedVars = computed(() => ({ failed: this.state.failed() }));
  protected readonly percent = computed(() => Math.round(100 * this.state.done() / this.state.total));
}
