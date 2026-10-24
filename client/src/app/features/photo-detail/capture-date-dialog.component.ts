import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { firstValueFrom } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { GalleryStore } from '../gallery/gallery.store';

export interface CaptureDateDialogData {
  paths: string[];
  count: number;
  filters?: Record<string, unknown> | null;
  exclude?: string[];
  manuallySet?: boolean;
}
type Preview = components['schemas']['CaptureDatePreview'];
export type CaptureDateResult = components['schemas']['CaptureDateReset'];

@Component({
  selector: 'app-capture-date-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatButtonModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title>{{ I18N.capture_date.title | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm mb-3">{{ I18N.capture_date.hint | translate }}</p>
      <p class="text-sm mb-3">{{ I18N.gallery.selection.count | translate:{ count: data.count } }}</p>
      <label class="block mb-3">{{ I18N.capture_date.offset | translate }}
        <input class="block w-full border rounded p-2 bg-transparent" type="number" min="-31622400" max="31622400" step="1"
          [ngModel]="offset()" (ngModelChange)="setOffset($event)" [disabled]="busy()">
      </label>
      @if (!valid()) { <p role="alert">{{ I18N.capture_date.invalid | translate }}</p> }
      @if (result(); as preview) {
        <p role="status" class="my-3">{{ I18N.capture_date.counts | translate:{ changed: preview.changed, skipped: preview.skipped } }}</p>
        <p class="text-sm mb-2">{{ I18N.capture_date.samples | translate }}</p>
        <div class="overflow-x-auto"><table class="w-full text-sm">
          <thead><tr><th class="text-left p-1">{{ I18N.capture_date.photo | translate }}</th><th class="text-left p-1">{{ I18N.capture_date.before | translate }}</th><th class="text-left p-1">{{ I18N.capture_date.after | translate }}</th></tr></thead>
          <tbody>@for (sample of preview.samples; track sample.path) {
            <tr><td class="p-1 max-w-48 truncate" [title]="sample.path">{{ sample.path }}</td><td class="p-1 whitespace-nowrap">{{ sample.old_date }}</td><td class="p-1 whitespace-nowrap">{{ sample.new_date }}</td></tr>
          }</tbody>
        </table></div>
      }
      @if (failed()) { <p role="alert" class="my-3">{{ I18N.capture_date.error | translate }}</p> }
      @if (data.manuallySet && data.paths.length === 1) { <p class="text-sm my-3">{{ I18N.capture_date.reset_hint | translate }}</p> }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (data.manuallySet && data.paths.length === 1) { <button mat-button [disabled]="busy()" (click)="useFileDate()">{{ I18N.capture_date.use_file | translate }}</button> }
      <button mat-button mat-dialog-close [disabled]="busy()">{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-button [disabled]="busy() || !valid()" (click)="preview()">{{ I18N.capture_date.preview | translate }}</button>
      <button mat-flat-button [disabled]="busy() || !result()?.changed" (click)="apply()">{{ I18N.capture_date.apply | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class CaptureDateDialogComponent {
  protected readonly I18N = i18nKeys();
  readonly data: CaptureDateDialogData = inject(MAT_DIALOG_DATA);
  private readonly api = inject(ApiService);
  private readonly store = inject(GalleryStore);
  private readonly dialog = inject(MatDialogRef<CaptureDateDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly owner = this.auth.status();
  private readonly url = this.router.url;
  private closing = false;
  private navigated = false;
  private readonly target = this.data.filters
    ? { filters: structuredClone(this.data.filters), exclude: [...(this.data.exclude ?? [])] }
    : { photo_paths: [...this.data.paths], exclude: [...(this.data.exclude ?? [])] };
  readonly offset = signal<number | null>(3600);
  readonly busy = signal(false);
  readonly failed = signal(false);
  readonly result = signal<Preview | null>(null);
  readonly valid = computed(() => this.data.count <= 1000 && this.offset() !== null && Number.isInteger(this.offset()) && this.offset() !== 0 && Math.abs(this.offset()!) <= 31622400);

  constructor() {
    this.dialog.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closing = true; this.result.set(null); });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) { this.navigated = true; this.invalidate(); }
    });
    effect(() => {
      if (this.auth.status() !== this.owner || !this.auth.isEdition()) this.invalidate();
    });
  }

  private invalidate(): void {
    this.closing = true;
    this.result.set(null);
    this.dialog.close();
  }

  private current(): boolean {
    return !this.closing && !this.navigated && !this.destroyRef.destroyed && this.auth.status() === this.owner && this.auth.isEdition() && this.router.url === this.url;
  }

  setOffset(value: number | null): void { this.offset.set(value); this.result.set(null); }

  async preview(): Promise<void> {
    if (!this.current() || this.busy() || !this.valid()) return;
    const offset = this.offset();
    this.busy.set(true); this.failed.set(false); this.result.set(null);
    try {
      const result = await firstValueFrom(this.api.post<Preview>('/photos/capture_date/preview', { ...this.target, offset_seconds: offset }));
      if (this.current() && this.offset() === offset) this.result.set(result);
    } catch { if (this.current()) this.failed.set(true); }
    finally { if (this.current()) this.busy.set(false); }
  }

  async apply(): Promise<void> {
    const preview = this.result();
    if (!this.current() || this.busy() || !preview?.changed || !this.valid()) return;
    this.busy.set(true); this.failed.set(false); this.dialog.disableClose = true;
    try {
      await firstValueFrom(this.api.post<Preview>('/photos/capture_date/apply', { ...this.target, offset_seconds: this.offset(), preview_token: preview.preview_token }));
      if (!this.current()) return;
      const sample = this.data.paths.length === 1 && !this.data.filters ? preview.samples.find(p => p.path === this.data.paths[0]) : undefined;
      const result = sample ? { date_taken: sample.new_date, date_manually_set: 1 } : undefined;
      if (sample && result) {
        this.store.patchPhoto(sample.path, result);
      }
      void this.store.refreshPaths(null);
      if (this.current()) this.dialog.close(result);
    } catch { if (this.current()) { this.failed.set(true); this.result.set(null); } }
    finally { if (this.current()) { this.busy.set(false); this.dialog.disableClose = false; } }
  }

  async useFileDate(): Promise<void> {
    if (!this.current() || this.busy() || !this.data.manuallySet || this.data.paths.length !== 1 || this.data.filters) return;
    const path = this.data.paths[0];
    this.busy.set(true); this.failed.set(false); this.dialog.disableClose = true;
    try {
      const result = await firstValueFrom(this.api.delete<CaptureDateResult>(`/photo/capture_date?path=${encodeURIComponent(path)}`));
      if (!this.current()) return;
      this.store.patchPhoto(path, result);
      void this.store.refreshPaths(null);
      if (this.current()) this.dialog.close(result);
    } catch { if (this.current()) this.failed.set(true); }
    finally { if (this.current()) { this.busy.set(false); this.dialog.disableClose = false; } }
  }
}
