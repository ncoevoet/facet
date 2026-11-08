import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { NavigationStart, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { components } from '../../core/api/schema';

type Diagnostics = components['schemas']['ImmichDiagnosticsResponse'];

@Component({
  selector: 'app-immich-diagnostics-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, MatButtonModule, MatDialogModule, MatProgressSpinnerModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ I18N.immich_diagnostics.title | translate }}</h2>
    <mat-dialog-content>
      <p class="mb-3 text-sm">{{ I18N.immich_diagnostics.read_only | translate }}</p>
      @if (busy()) { <mat-spinner diameter="24" [attr.aria-label]="I18N.ui.labels.loading | translate" /> }
      @if (failed()) { <p role="alert">{{ I18N.immich_diagnostics.failed | translate }}</p> }
      @if (status(); as value) {
        <dl class="grid grid-cols-2 gap-2 text-sm">
          <dt>{{ I18N.immich_diagnostics.configuration | translate }}</dt>
          <dd>{{ (value.configured ? I18N.immich_diagnostics.configured : I18N.immich_diagnostics.not_configured) | translate }}</dd>
          <dt>{{ I18N.immich_diagnostics.mapping_rules | translate }}</dt><dd>{{ value.mapping_rules }}</dd>
          <dt>{{ I18N.immich_diagnostics.mapping_sample | translate }}</dt><dd>{{ value.mapped_photos }} / {{ value.sampled_photos }}</dd>
          <dt>{{ I18N.immich_diagnostics.last_push | translate }}</dt>
          <dd>{{ value.last_push_at ? (value.last_push_at | date:'dd/MM/yyyy HH:mm') : (I18N.immich_diagnostics.unknown | translate) }}</dd>
        </dl>
        <p class="mt-2 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.immich_diagnostics.sample_hint | translate:{ limit: value.sample_limit } }}</p>
        <p class="mt-3 text-sm" role="status">{{ connectionLabel() | translate }}</p>
        @if (value.version) {
          <p class="mt-2 text-sm">{{ I18N.immich_diagnostics.version | translate:{ version: value.version } }}</p>
          <p class="mt-1 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ (value.stack_version_supported ? I18N.immich_diagnostics.stack_version_ok : I18N.immich_diagnostics.stack_version_old) | translate }}</p>
        }
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.dialog.close | translate }}</button>
      <button mat-stroked-button [disabled]="busy()" (click)="load(false)">{{ I18N.immich_diagnostics.refresh | translate }}</button>
      <button mat-flat-button [disabled]="busy() || !status()?.configured" (click)="load(true)">{{ I18N.immich_diagnostics.test | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class ImmichDiagnosticsDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly ref = inject(MatDialogRef<ImmichDiagnosticsDialogComponent>);
  private readonly router = inject(Router);
  private readonly owner = this.auth.identity();
  private closed = false;
  protected readonly status = signal<Diagnostics | null>(null);
  protected readonly busy = signal(false);
  protected readonly failed = signal(false);
  protected readonly connectionLabel = computed(() => {
    const labels = {
      not_checked: I18N.immich_diagnostics.not_checked, not_configured: I18N.immich_diagnostics.not_configured,
      invalid_config: I18N.immich_diagnostics.invalid_config, connected: I18N.immich_diagnostics.connected,
      access_denied: I18N.immich_diagnostics.access_denied, unreachable: I18N.immich_diagnostics.unreachable,
      invalid_response: I18N.immich_diagnostics.invalid_response,
    };
    return labels[this.status()?.connection ?? 'not_checked'];
  });

  constructor() {
    effect(() => { if (!this.current()) { this.status.set(null); this.ref.close(); } });
    this.ref.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closed = true; this.status.set(null); });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) { this.closed = true; this.status.set(null); this.ref.close(); }
    });
    void this.load(false);
  }

  private current(): boolean {
    return !this.closed && !this.destroyRef.destroyed && this.owner === this.auth.identity()
      && this.auth.isInstallAdmin();
  }

  async load(checkConnection: boolean): Promise<void> {
    if (!this.current() || this.busy()) return;
    this.busy.set(true); this.failed.set(false); this.status.set(null);
    try {
      const value = await firstValueFrom(this.api.get<Diagnostics>('/immich/diagnostics',
        { check_connection: String(checkConnection) }).pipe(takeUntilDestroyed(this.destroyRef)));
      if (this.current()) this.status.set(value);
    } catch {
      if (this.current()) this.failed.set(true);
    } finally { this.busy.set(false); }
  }
}
