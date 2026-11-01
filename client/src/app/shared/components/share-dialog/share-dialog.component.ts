import { Component, inject, signal, computed, OnInit, ChangeDetectionStrategy, DestroyRef, effect } from '@angular/core';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { firstValueFrom } from 'rxjs';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../../core/services/api.service';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { i18nKeys } from '../../../core/i18n/keys';
import { copyText } from '../../utils/clipboard';
import { AuthService } from '../../../core/services/auth.service';
import { StalenessGuardFactory } from '../../../core/services/staleness-guard.service';
import type { components } from '../../../core/api/schema';

export interface ShareDialogData {
  entityType: 'album' | 'person';
  entityId: number;
  autoGenerate: boolean;
  i18nPrefix: string;
  /** API config for generating a share link. */
  generateApi: {
    method: 'post' | 'get';
    url: string;
    body?: Record<string, unknown>;
    extractUrl: (res: Record<string, unknown>) => string;
  };
  /** Optional API config for revoking a share link. */
  revokeApi?: {
    url: string;
  };
}

@Component({
  selector: 'app-share-dialog',
  standalone: true,
  imports: [
    MatDialogModule, MatButtonModule, MatIconModule,
    MatInputModule, MatFormFieldModule, MatTooltipModule, TranslatePipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="titleKey | translate">{{ titleKey | translate }}</h2>
    <mat-dialog-content>
      @if (shareUrl()) {
        <p class="text-sm mb-3 opacity-70">{{ descriptionKey | translate }}</p>
        @if (policy(); as policy) {
          <section class="mb-3 text-sm" [attr.aria-label]="I18N.albums.recipient_policy | translate">
            <p>{{ (policy.membership === 'smart' ? I18N.albums.share_smart_scope : I18N.albums.share_manual_scope) | translate:{ count: recipientCount() } }}</p>
            <p>{{ I18N.albums.share_access_policy | translate }}</p>
            <p>{{ (policy.proofing ? I18N.albums.share_proofing_on : I18N.albums.share_proofing_off) | translate }}</p>
            <details>
              <summary class="min-h-11 cursor-pointer">{{ I18N.albums.share_data_disclosure | translate }}</summary>
              <p>{{ I18N.albums.share_metadata_disclosure | translate }}</p>
              <p>{{ I18N.albums.share_private_exclusions | translate }}</p>
            </details>
            <a mat-button [href]="fullShareUrl()" target="_blank" rel="noopener noreferrer">{{ I18N.albums.open_recipient_view | translate }}</a>
          </section>
        }
        <mat-form-field class="w-full">
          <mat-label>{{ linkLabelKey | translate }}</mat-label>
          <input matInput [value]="fullShareUrl()" readonly />
        </mat-form-field>
        @if (copied()) {
          <p class="text-sm text-green-600 dark:text-green-400 mt-1">
            {{ copiedKey | translate }}
          </p>
        }
      } @else if (loading()) {
        <p class="text-sm opacity-70">{{ I18N.ui.labels.loading | translate }}</p>
      }
      @if (error()) { <p role="alert">{{ I18N.albums.share_operation_error | translate }}</p> }
      @if (shareUrl() && data.entityType === 'album' && !policy()) {
        <button mat-button [disabled]="loading()" (click)="readPolicy()">{{ I18N.albums.reload_recipient_policy | translate }}</button>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (shareUrl()) {
        @if (data.revokeApi) {
          <button mat-button color="warn" (click)="revoke()" [disabled]="loading()">
            <mat-icon>link_off</mat-icon>
            {{ revokeKey | translate }}
          </button>
        } @else {
          <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
        }
        <button mat-flat-button (click)="copyLink()" [disabled]="loading() || (data.entityType === 'album' && !policy())">
          <mat-icon>content_copy</mat-icon>
          {{ copyKey | translate }}
        </button>
      } @else {
        <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
        <button mat-flat-button (click)="generateLink()" [disabled]="loading()">
          <mat-icon>share</mat-icon>
          {{ generateKey | translate }}
        </button>
      }
    </mat-dialog-actions>
  `,
})
export class ShareDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly token = this.auth.token;
  private readonly context = inject(StalenessGuardFactory).create(this.destroyRef, {
    track: 'status', valid: () => this.auth.token === this.token,
    onNavigate: () => this.dialogRef.close(),
  });
  private readonly dialogRef = inject(MatDialogRef<ShareDialogComponent>);
  protected data = inject<ShareDialogData>(MAT_DIALOG_DATA);

  protected readonly shareUrl = signal('');
  protected readonly fullShareUrl = computed(() => `${window.location.origin}${this.shareUrl()}`);
  protected readonly loading = signal(false);
  protected readonly copied = signal(false);
  protected readonly error = signal(false);
  protected readonly policy = signal<components['schemas']['SharedAlbumPolicy'] | null>(null);
  protected readonly recipientCount = signal(0);
  private copyTimer?: ReturnType<typeof setTimeout>;

  constructor() {
    effect(() => {
      this.auth.identity(); this.auth.status(); this.auth.isEdition();
      if (!this.context.current()) {
        this.shareUrl.set(''); this.policy.set(null); this.dialogRef.close();
      }
    });
    this.destroyRef.onDestroy(() => { this.context.dispose(); clearTimeout(this.copyTimer); });
  }

  protected readonly titleKey = `${this.data.i18nPrefix}.share`;
  protected readonly descriptionKey = `${this.data.i18nPrefix}.share_description`;
  protected readonly linkLabelKey = `${this.data.i18nPrefix}.share_link`;
  protected readonly copiedKey = `${this.data.i18nPrefix}.link_copied`;
  protected readonly revokeKey = `${this.data.i18nPrefix}.revoke_share`;
  protected readonly copyKey = `${this.data.i18nPrefix}.copy_link`;
  protected readonly generateKey = `${this.data.i18nPrefix}.generate_link`;

  async ngOnInit(): Promise<void> {
    if (this.data.autoGenerate) {
      await this.generateLink();
    }
  }

  protected async generateLink(): Promise<void> {
    if (this.loading() || !this.context.current()) return;
    this.loading.set(true); this.error.set(false);
    try {
      const { method, url, body, extractUrl } = this.data.generateApi;
      const res = await firstValueFrom(
        method === 'post'
          ? this.api.post<Record<string, unknown>>(url, body ?? {})
          : this.api.get<Record<string, unknown>>(url),
      );
      if (!this.context.current()) return;
      this.shareUrl.set(extractUrl(res));
      if (this.data.entityType === 'album') await this.fetchPolicy();
    } catch {
      if (this.context.current()) this.error.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  protected async readPolicy(): Promise<void> {
    if (this.loading() || !this.context.current() || !this.shareUrl()) return;
    this.loading.set(true); this.error.set(false);
    try { await this.fetchPolicy(); }
    catch { if (this.context.current()) this.error.set(true); }
    finally { this.loading.set(false); }
  }

  private async fetchPolicy(): Promise<void> {
    const token = new URL(this.shareUrl(), window.location.origin).searchParams.get('token');
    if (!token) throw new Error('Missing share token');
    const result = await firstValueFrom(this.api.get<components['schemas']['SharedAlbumResponse']>(
      `/shared/album/${this.data.entityId}`, { token, per_page: 1 },
    ));
    if (!this.context.current()) return;
    this.policy.set(result.sharing_policy); this.recipientCount.set(result.total);
  }

  protected async copyLink(): Promise<void> {
    if (!this.context.current() || this.loading() || (this.data.entityType === 'album' && !this.policy())) return;
    if (!await copyText(this.fullShareUrl())) return;
    if (!this.context.current()) return;
    this.copied.set(true);
    clearTimeout(this.copyTimer);
    this.copyTimer = setTimeout(() => this.copied.set(false), 2000);
  }

  protected async revoke(): Promise<void> {
    if (!this.data.revokeApi || this.loading() || !this.context.current()) return;
    this.loading.set(true); this.error.set(false);
    try {
      await firstValueFrom(this.api.delete(this.data.revokeApi.url));
      if (!this.context.current()) return;
      this.shareUrl.set(''); this.policy.set(null); this.dialogRef.close('revoked');
    } catch { if (this.context.current()) this.error.set(true); }
    finally { this.loading.set(false); }
  }
}
