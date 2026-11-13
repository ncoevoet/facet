import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '../../core/services/auth.service';
import { ApiService } from '../../core/services/api.service';
import { GeoPhotosService } from '../../core/services/geo-photos.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import type { components } from '../../core/api/schema';
import { extractErrorDetail } from '../../core/utils/http-error.util';
import { i18nKeys } from '../../core/i18n/keys';

type RefreshResult = components['schemas']['PhotoRefreshResponse'];

@Component({
  selector: 'app-photo-refresh-dialog',
  imports: [MatDialogModule, MatButtonModule, MatProgressSpinnerModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ I18N.photo_refresh.title | translate }}</h2>
    <mat-dialog-content>
      <p>{{ I18N.photo_refresh.description | translate }}</p>
      <p class="mt-3">{{ (data.length === 1 ? I18N.photo_refresh.one : I18N.photo_refresh.many) | translate:{ count: data.length } }}</p>
      @if (busy()) { <mat-spinner diameter="24" [attr.aria-label]="I18N.photo_refresh.title | translate" /> }
      @if (completed().length) { <p class="mt-3" role="status">{{ I18N.photo_refresh.completed | translate:{ count: completed().length } }}</p> }
      @if (failed()) { <p class="mt-3 text-[var(--mat-sys-error)]" role="alert">{{ I18N.photo_refresh.failed | translate }}</p> }
      @if (errorDetail(); as detail) { <p class="mt-2 text-sm text-[var(--mat-sys-error)]" role="alert">{{ detail }}</p> }
      @for (item of failures(); track item.path) {
        <p class="mt-2 text-sm break-all">{{ item.path }} — {{ reasonKeys[item.reason] | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [disabled]="busy()" (click)="close()">{{ I18N.dialog.close | translate }}</button>
      <button mat-flat-button [disabled]="busy() || !pending().length" (click)="run()">{{ I18N.photo_refresh.start | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class PhotoRefreshDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly reasonKeys: Record<RefreshResult['failed'][number]['reason'], string> = {
    unavailable: this.I18N.photo_refresh.reasons.unavailable,
    changed: this.I18N.photo_refresh.reasons.changed,
    busy: this.I18N.photo_refresh.reasons.busy,
    failed: this.I18N.photo_refresh.reasons.failed,
  };
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly geoPhotos = inject(GeoPhotosService);
  private readonly ref = inject(MatDialogRef<PhotoRefreshDialogComponent>);
  protected readonly data = inject<string[]>(MAT_DIALOG_DATA);
  private readonly destroyRef = inject(DestroyRef);
  private closed = false;
  private readonly owner = this.auth.identity();
  protected readonly pending = signal([...this.data]);
  readonly completed = signal<string[]>([]);
  protected readonly busy = signal(false);
  protected readonly failed = signal(false);
  protected readonly failures = signal<RefreshResult['failed']>([]);
  protected readonly errorDetail = signal<string | null>(null);

  constructor() {
    this.ref.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closed = true; });
    effect(() => { if (!this.current()) this.ref.close(); });
  }

  private current(): boolean { return !this.closed && !this.destroyRef.destroyed && this.auth.identity() === this.owner && this.auth.isEdition(); }

  async run(): Promise<void> {
    if (!this.current() || this.busy() || !this.pending().length) return;
    this.busy.set(true); this.failed.set(false); this.errorDetail.set(null); this.failures.set([]); this.ref.disableClose = true;
    try {
      const result = await firstValueFrom(this.api.post<RefreshResult>('/photos/refresh', { paths: this.pending() }));
      if (!this.current()) return;
      this.completed.update(paths => [...new Set([...paths, ...result.refreshed])]);
      if (result.refreshed.length) void this.geoPhotos.refresh();
      this.pending.set(result.failed.map(item => item.path));
      this.failed.set(result.failed.length > 0);
      this.failures.set(result.failed);
    } catch (error) {
      if (this.current()) { this.failed.set(true); this.errorDetail.set(extractErrorDetail(error) ?? null); }
    } finally { this.busy.set(false); this.ref.disableClose = false; }
  }

  protected close(): void { if (!this.busy()) this.ref.close(this.completed()); }
}
