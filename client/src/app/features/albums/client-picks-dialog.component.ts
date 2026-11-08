import { Component, DestroyRef, ElementRef, Injector, afterNextRender, inject, signal, computed, effect, viewChild, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { defaultIfEmpty, filter, firstValueFrom } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { SceneDatePipe } from '../scenes/scenes.pipes';
import { basename, copyLines } from '../../shared/utils/clipboard';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { AuthService } from '../../core/services/auth.service';
import { Router } from '@angular/router';
import { AlbumDialogContext } from './album-dialog-context';
import { isNavigationSettled } from '../../shared/utils/navigation-settled';

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
    TranslatePipe, PluralKeyPipe, SceneDatePipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 #heading tabindex="-1" mat-dialog-title class="truncate">{{ I18N.proofing.client_picks | translate }} — {{ data.albumName }}</h2>
    <mat-dialog-content>
      @if (loading() && !retrying()) {
        <div class="flex justify-center py-8">
          <mat-spinner diameter="36" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      } @else if (loadFailed() || retrying()) {
        <div role="alert" class="py-4">
          <p>{{ (retrying() ? I18N.ui.labels.loading : I18N.proofing.load_error) | translate }}</p>
          <button #retryButton mat-button class="max-lg:!min-h-11" [attr.aria-disabled]="retrying()" (click)="load(true)">{{ I18N.gallery.load_error.retry | translate }}</button>
        </div>
      } @else if (picks().length === 0) {
        <p class="text-[var(--mat-sys-on-surface-variant)] py-4">{{ I18N.proofing.no_picks | translate }}</p>
      } @else {
        <p class="text-sm text-[var(--mat-sys-on-surface-variant)] mb-2">{{ pickedCount() | pluralKey:I18N.proofing.picks_count:I18N.proofing.picks_count_plural | translate:{ count: pickedCount() } }}</p>
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
                <div class="text-xs text-[var(--mat-sys-on-surface-variant)]">
                  @if (pick.client_name) {
                    {{ pick.client_name }} —
                  }
                  {{ pick.updated_at | sceneDate }}
                </div>
              </div>
            </div>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (pickedCount()) {
        <button mat-button class="max-sm:!min-h-11" (click)="copyFilenames()">
          <mat-icon>content_copy</mat-icon>
          {{ I18N.gallery.selection.copy_filenames | translate }}
        </button>
      }
      <button mat-flat-button mat-dialog-close class="max-sm:!min-h-11">{{ I18N.ui.buttons.back | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class ClientPicksDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  protected readonly data = inject<ClientPicksDialogData>(MAT_DIALOG_DATA);
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly injector = inject(Injector);
  private readonly document = inject(DOCUMENT);
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');
  private readonly retryButton = viewChild('retryButton', { read: ElementRef<HTMLButtonElement> });
  private readonly auth = inject(AuthService);
  private readonly openingOwner = this.auth.identity();
  private readonly dialogRef = inject(MatDialogRef<ClientPicksDialogComponent>);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly guard = new AlbumDialogContext(this.auth, this.router, this.destroyRef, false);

  protected readonly loading = signal(true);
  protected readonly loadFailed = signal(false);
  protected readonly retrying = signal(false);
  protected readonly picks = signal<(ClientPick & { filename: string })[]>([]);
  protected readonly pickedCount = computed(() => this.picks().filter(p => p.picked).length);

  constructor() {
    effect(() => {
      if (this.auth.identity() !== this.openingOwner) {
        this.guard.invalidate();
        this.picks.set([]);
        this.dialogRef.close();
      }
    });
  }

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  protected async load(isRetry = false): Promise<void> {
    if (this.loading() && isRetry) return;
    while (this.guard.current() && !this.guard.canStart()) {
      await firstValueFrom(this.router.events.pipe(filter(isNavigationSettled), takeUntilDestroyed(this.destroyRef), defaultIfEmpty(null)));
    }
    if (!this.guard.current()) {
      // The navigation left the page this dialog was opened on: nothing left to load for.
      if (!this.destroyRef.destroyed) this.dialogRef.close();
      return;
    }
    const retryButton = isRetry ? this.retryButton()?.nativeElement : undefined;
    this.retrying.set(isRetry);
    this.loading.set(true);
    this.loadFailed.set(false);
    try {
      const res = await firstValueFrom(
        this.api.get<ClientPicksResponse>(`/albums/${this.data.albumId}/picks`),
      );
      if (!await this.guard.settled()) return;
      const shouldRestoreFocus = !!retryButton && this.document.activeElement === retryButton;
      this.picks.set(res.picks.map(pick => ({
        ...pick,
        filename: basename(pick.path),
      })));
      if (shouldRestoreFocus) afterNextRender(() => {
        if (this.guard.current() && (this.document.activeElement === this.document.body || this.document.activeElement === retryButton))
          this.heading()?.nativeElement.focus();
      }, { injector: this.injector });
    } catch {
      if (await this.guard.settled()) this.loadFailed.set(true);
    } finally {
      if (await this.guard.settled()) { this.loading.set(false); this.retrying.set(false); }
    }
  }

  protected copyFilenames(): void {
    const filenames = this.picks()
      .filter(pick => pick.picked)
      .map(pick => pick.filename);
    copyLines(filenames).then(() => {
      this.snackBar.open(this.i18n.t(I18N.gallery.selection.copied), '', { duration: 2000 });
    });
  }
}
