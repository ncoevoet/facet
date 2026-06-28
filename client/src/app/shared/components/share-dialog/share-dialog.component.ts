import { Component, inject, signal, computed, OnInit } from '@angular/core';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { firstValueFrom } from 'rxjs';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../../core/services/api.service';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { I18N } from '../../../core/i18n/keys';

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
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="titleKey | translate">{{ titleKey | translate }}</h2>
    <mat-dialog-content>
      @if (shareUrl()) {
        <p class="text-sm mb-3 opacity-70">{{ descriptionKey | translate }}</p>
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
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (shareUrl()) {
        @if (data.revokeApi) {
          <button mat-button color="warn" (click)="revoke()">
            <mat-icon>link_off</mat-icon>
            {{ revokeKey | translate }}
          </button>
        } @else {
          <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
        }
        <button mat-flat-button (click)="copyLink()">
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
  protected readonly I18N = I18N;
  private readonly api = inject(ApiService);
  private readonly dialogRef = inject(MatDialogRef<ShareDialogComponent>);
  protected data = inject<ShareDialogData>(MAT_DIALOG_DATA);

  protected readonly shareUrl = signal('');
  protected readonly fullShareUrl = computed(() => `${window.location.origin}${this.shareUrl()}`);
  protected readonly loading = signal(false);
  protected readonly copied = signal(false);

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
    this.loading.set(true);
    try {
      const { method, url, body, extractUrl } = this.data.generateApi;
      const res = await firstValueFrom(
        method === 'post'
          ? this.api.post<Record<string, unknown>>(url, body ?? {})
          : this.api.get<Record<string, unknown>>(url),
      );
      this.shareUrl.set(extractUrl(res));
    } finally {
      this.loading.set(false);
    }
  }

  protected async copyLink(): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.fullShareUrl());
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    } catch {
      // Fallback: select and copy via execCommand for older browsers
      const input = document.querySelector<HTMLInputElement>('mat-dialog-content input');
      if (input) {
        input.select();
        document.execCommand('copy');
        this.copied.set(true);
        setTimeout(() => this.copied.set(false), 2000);
      }
    }
  }

  protected async revoke(): Promise<void> {
    if (!this.data.revokeApi) return;
    await firstValueFrom(
      this.api.delete(this.data.revokeApi.url),
    );
    this.shareUrl.set('');
    this.dialogRef.close('revoked');
  }
}
