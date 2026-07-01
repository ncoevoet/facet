import { Component, inject, signal, computed, OnInit } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

export interface ClientPicksDialogData {
  albumId: number;
  albumName: string;
}

interface ClientPick {
  path: string;
  picked: boolean;
  comment: string | null;
  client_name: string | null;
  updated_at: string;
}

interface ClientPicksResponse {
  picks: ClientPick[];
  count: number;
}

@Component({
  selector: 'app-client-picks-dialog',
  standalone: true,
  imports: [
    MatDialogModule, MatButtonModule, MatIconModule, MatProgressSpinnerModule,
    TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate">{{ 'proofing.client_picks' | translate }} — {{ data.albumName }}</h2>
    <mat-dialog-content>
      @if (loading()) {
        <div class="flex justify-center py-8">
          <mat-spinner diameter="36" />
        </div>
      } @else if (picks().length === 0) {
        <p class="opacity-60 py-4">{{ 'proofing.no_picks' | translate }}</p>
      } @else {
        <p class="text-sm opacity-70 mb-2">{{ 'proofing.picks_count' | translate:{ count: pickedCount() } }}</p>
        <div class="flex flex-col divide-y divide-[var(--mat-sys-outline-variant)]">
          @for (pick of picks(); track pick.path) {
            <div class="flex items-start gap-2 py-2">
              <mat-icon class="!text-lg !w-5 !h-5 !leading-5 shrink-0"
                        [class.text-red-400]="pick.picked"
                        [class.opacity-40]="!pick.picked">{{ pick.picked ? 'favorite' : 'favorite_border' }}</mat-icon>
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium truncate">{{ pick.filename }}</div>
                @if (pick.comment) {
                  <div class="text-sm opacity-80 break-words">{{ pick.comment }}</div>
                }
                <div class="text-xs opacity-50">
                  @if (pick.client_name) {
                    {{ pick.client_name }} —
                  }
                  {{ pick.updated_at }}
                </div>
              </div>
            </div>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (pickedCount()) {
        <button mat-button (click)="copyFilenames()">
          <mat-icon>content_copy</mat-icon>
          {{ I18N.gallery.selection.copy_filenames | translate }}
        </button>
      }
      <button mat-flat-button mat-dialog-close>{{ I18N.ui.buttons.back | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class ClientPicksDialogComponent implements OnInit {
  protected readonly I18N = I18N;
  protected readonly data = inject<ClientPicksDialogData>(MAT_DIALOG_DATA);
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly loading = signal(true);
  protected readonly picks = signal<(ClientPick & { filename: string })[]>([]);
  protected readonly pickedCount = computed(() => this.picks().filter(p => p.picked).length);

  async ngOnInit(): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.get<ClientPicksResponse>(`/albums/${this.data.albumId}/picks`),
      );
      this.picks.set(res.picks.map(pick => ({
        ...pick,
        filename: pick.path.split(/[\\/]/).pop() ?? pick.path,
      })));
    } catch {
      this.picks.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  protected copyFilenames(): void {
    const filenames = this.picks()
      .filter(pick => pick.picked)
      .map(pick => pick.filename)
      .join('\n');
    navigator.clipboard.writeText(filenames).then(() => {
      this.snackBar.open(this.i18n.t(I18N.gallery.selection.copied), '', { duration: 2000 });
    });
  }
}
