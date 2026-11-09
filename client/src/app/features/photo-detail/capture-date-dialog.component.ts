import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { Subscription, finalize, firstValueFrom, take } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { i18nKeys } from '../../core/i18n/keys';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { GalleryStore } from '../gallery/gallery.store';

export interface CaptureDateDialogData {
  paths: string[];
  count: number;
  filters?: Record<string, unknown> | null;
  exclude?: string[];
  manuallySet?: boolean;
  /** One target photo and its stored `date_taken` (`YYYY:MM:DD HH:MM:SS`), shown as the
   *  before/after example. With a dated reference, "set exact time" shifts every photo by
   *  the offset that gives it the typed time; without one it writes the typed time itself. */
  reference?: { path: string; date: string } | null;
}
type Preview = components['schemas']['CaptureDatePreview'];
export type CaptureDateResult = components['schemas']['CaptureDateReset'];
type Mode = 'shift' | 'exact';
interface OffsetParts { days: number; hours: number; minutes: number; seconds: number }

const MAX_OFFSET_SECONDS = 31622400;
export const PREVIEW_DEBOUNCE_MS = 300;
const UNIT_SECONDS: Record<keyof OffsetParts, number> = { days: 86400, hours: 3600, minutes: 60, seconds: 1 };
const UNITS = ['days', 'hours', 'minutes', 'seconds'] as const;
/** The stored forms the server's `parse_capture_date` accepts, whole-string only. */
const CAPTURE_DATE = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$|^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})$/;
const LOCAL_DATE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/;
const SEGMENT_ON = '!bg-[var(--mat-sys-secondary-container)] !text-[var(--mat-sys-on-secondary-container)]';

/** Walltime as epoch seconds read in UTC, so no timezone or DST shift ever applies;
 *  null for a date the calendar does not have (31 April, 25:00), as the server rejects it. */
function wallSeconds(fields: (string | undefined)[] | null): number | null {
  if (!fields) return null;
  const [y, mo, d, h, mi, se] = fields.map(field => +(field ?? 0));
  const date = new Date(Date.UTC(y, mo - 1, d, h, mi, se));
  const same = date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d
    && date.getUTCHours() === h && date.getUTCMinutes() === mi && date.getUTCSeconds() === se;
  return same ? date.getTime() / 1000 : null;
}
function captureDateSeconds(date: string): number | null {
  const m = CAPTURE_DATE.exec(date);
  return m ? wallSeconds(m[1] ? m.slice(1, 7) : m.slice(7, 13)) : null;
}
/** Seconds as the `datetime-local` input's value. */
function localInput(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(0, 19);
}
function formatExif(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(0, 19).replace(/-/g, ':').replace('T', ' ');
}
function splitOffset(abs: number): OffsetParts {
  let rest = abs;
  const parts = {} as OffsetParts;
  for (const unit of UNITS) { parts[unit] = Math.floor(rest / UNIT_SECONDS[unit]); rest %= UNIT_SECONDS[unit]; }
  return parts;
}

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
      <div class="inline-flex mb-3 rounded-full border border-[var(--mat-sys-outline-variant)] overflow-hidden" role="group" [attr.aria-label]="I18N.capture_date.mode | translate">
        <button mat-button type="button" data-mode="shift" class="!rounded-none" [class]="mode() === 'shift' ? SEGMENT_ON : ''"
          [attr.aria-pressed]="mode() === 'shift'" [disabled]="busy()" (click)="setMode('shift')">{{ I18N.capture_date.mode_shift | translate }}</button>
        <button mat-button type="button" data-mode="exact" class="!rounded-none" [class]="mode() === 'exact' ? SEGMENT_ON : ''"
          [attr.aria-pressed]="mode() === 'exact'" [disabled]="busy()" (click)="setMode('exact')">{{ I18N.capture_date.mode_exact | translate }}</button>
      </div>
      @if (mode() === 'shift') {
        <div class="flex flex-wrap items-end gap-3 mb-3">
          <div class="inline-flex rounded-full border border-[var(--mat-sys-outline-variant)] overflow-hidden" role="group" [attr.aria-label]="I18N.capture_date.direction | translate">
            <button mat-button type="button" data-direction="earlier" class="!rounded-none" [class]="direction() < 0 ? SEGMENT_ON : ''"
              [attr.aria-pressed]="direction() < 0" [disabled]="busy()" (click)="setDirection(-1)">{{ I18N.capture_date.earlier | translate }}</button>
            <button mat-button type="button" data-direction="later" class="!rounded-none" [class]="direction() > 0 ? SEGMENT_ON : ''"
              [attr.aria-pressed]="direction() > 0" [disabled]="busy()" (click)="setDirection(1)">{{ I18N.capture_date.later | translate }}</button>
          </div>
          @for (unit of UNITS; track unit) {
            <label class="flex flex-col text-xs w-20">{{ I18N.capture_date[unit] | translate }}
              <input class="mt-1 w-full border rounded p-2 bg-transparent text-sm" type="number" min="0" step="1" [attr.data-unit]="unit"
                [ngModel]="parts()[unit]" (ngModelChange)="setPart(unit, $event)" [disabled]="busy()"
                [attr.aria-invalid]="!valid()" [attr.aria-describedby]="valid() ? null : 'capture-date-offset-error'">
            </label>
          }
        </div>
        <div class="flex flex-wrap items-center gap-2 mb-3">
          <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.capture_date.quick | translate }}</span>
          @for (step of QUICK_STEPS; track step.seconds) {
            <button mat-stroked-button type="button" class="!min-w-0 !px-3 !h-8" [attr.data-quick]="step.seconds" [disabled]="busy()" (click)="addOffset(step.seconds)">
              {{ step.seconds < 0 ? '−' : '+' }}1 {{ step.unit | translate }}
            </button>
          }
        </div>
      } @else {
        <label class="block mb-3 text-sm">{{ (absolute() ? I18N.capture_date.exact_label_set : I18N.capture_date.exact_label) | translate }}
          <input class="block w-full mt-1 border rounded p-2 bg-transparent" type="datetime-local" step="1" data-exact
            [ngModel]="exactValue()" (ngModelChange)="setExact($event)" [disabled]="busy()"
            [attr.aria-invalid]="!valid()" [attr.aria-describedby]="valid() ? null : 'capture-date-offset-error'">
        </label>
      }
      @if (!valid()) {
        <p id="capture-date-offset-error" role="alert" class="text-sm mb-3">{{ (absolute() ? I18N.capture_date.invalid_set : I18N.capture_date.invalid) | translate }}</p>
      } @else {
        <p class="text-sm font-medium mb-1" data-summary>{{ summaryKey() | translate:{ amount: amount() } }}</p>
      }
      @if (reference) {
        <p class="text-sm mb-3" data-reference>
          <span class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.capture_date.reference | translate }}</span>
          {{ reference.date }} → {{ referenceAfter() ?? '—' }}
        </p>
      }
      @if (result(); as preview) {
        <p role="status" class="my-3">{{ I18N.capture_date.counts | translate:{ changed: preview.changed, skipped: preview.skipped } }}</p>
        <p class="text-sm mb-2">{{ I18N.capture_date.samples | translate }}</p>
        <div class="overflow-x-auto"><table class="w-full text-sm">
          <thead><tr><th scope="col" class="text-left p-1">{{ I18N.capture_date.photo | translate }}</th><th scope="col" class="text-left p-1">{{ I18N.capture_date.before | translate }}</th><th scope="col" class="text-left p-1">{{ I18N.capture_date.after | translate }}</th></tr></thead>
          <tbody>@for (sample of preview.samples; track sample.path) {
            <tr><td class="p-1 max-w-48 truncate" [title]="sample.path">{{ sample.path }}</td><td class="p-1 whitespace-nowrap">{{ sample.old_date ?? (I18N.gallery.no_capture_date | translate) }}</td><td class="p-1 whitespace-nowrap">{{ sample.new_date }}</td></tr>
          }</tbody>
        </table></div>
      }
      @if (failed()) {
        <div class="flex items-center gap-2 my-3">
          <p role="alert" class="flex-1">{{ I18N.capture_date.error | translate }}</p>
          <button mat-button type="button" [disabled]="busy() || !valid()" (click)="preview()">{{ I18N.capture_date.preview | translate }}</button>
        </div>
      }
      @if (data.manuallySet && data.paths.length === 1) { <p class="text-sm my-3">{{ I18N.capture_date.reset_hint | translate }}</p> }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (data.manuallySet && data.paths.length === 1) { <button mat-button [disabled]="busy()" (click)="useFileDate()">{{ I18N.capture_date.use_file | translate }}</button> }
      <button mat-button mat-dialog-close [disabled]="busy()">{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button [disabled]="busy() || !result()?.changed" (click)="apply()">{{ I18N.capture_date.apply | translate:{ count: result()?.changed ?? 0 } }}</button>
    </mat-dialog-actions>
  `,
})
export class CaptureDateDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly UNITS = UNITS;
  protected readonly SEGMENT_ON = SEGMENT_ON;
  protected readonly QUICK_STEPS = [
    { seconds: -3600, unit: this.I18N.capture_date.unit_h }, { seconds: 3600, unit: this.I18N.capture_date.unit_h },
    { seconds: -86400, unit: this.I18N.capture_date.unit_d }, { seconds: 86400, unit: this.I18N.capture_date.unit_d },
  ];
  readonly data: CaptureDateDialogData = inject(MAT_DIALOG_DATA);
  private readonly api = inject(ApiService);
  private readonly store = inject(GalleryStore);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialogRef<CaptureDateDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(AuthService);
  private readonly owner = this.auth.status();
  private readonly staleness = inject(StalenessGuardFactory).create(this.destroyRef, { track: 'status', onNavigate: () => this.invalidate() });
  private closing = false;
  private previewTimer: ReturnType<typeof setTimeout> | undefined;
  private previewRequest: Subscription | undefined;
  private readonly target = this.data.filters
    ? { filters: structuredClone(this.data.filters), exclude: [...(this.data.exclude ?? [])] }
    : { photo_paths: [...this.data.paths], exclude: [...(this.data.exclude ?? [])] };
  private readonly referenceSeconds = this.data.reference ? captureDateSeconds(this.data.reference.date) : null;
  protected readonly reference = this.referenceSeconds === null ? null : this.data.reference;
  readonly mode = signal<Mode>(!this.reference && this.data.paths.length === 1 && !this.data.filters ? 'exact' : 'shift');
  readonly direction = signal<1 | -1>(1);
  readonly parts = signal<OffsetParts>({ days: 0, hours: 1, minutes: 0, seconds: 0 });
  readonly exactValue = signal(this.referenceSeconds === null ? '' : localInput(this.referenceSeconds));
  readonly offset = computed<number | null>(() => {
    if (this.mode() === 'exact') {
      const target = wallSeconds(LOCAL_DATE.exec(this.exactValue() ?? '')?.slice(1) ?? null);
      return target === null || this.referenceSeconds === null ? null : target - this.referenceSeconds;
    }
    const parts = this.parts();
    if (UNITS.some(unit => !Number.isInteger(parts[unit]) || parts[unit] < 0)) return null;
    return this.direction() * UNITS.reduce((sum, unit) => sum + parts[unit] * UNIT_SECONDS[unit], 0);
  });
  readonly busy = signal(false);
  readonly failed = signal(false);
  readonly result = signal<Preview | null>(null);
  /** Exact mode without a dated reference: the typed walltime is sent as-is (`set_date`), not as an offset. */
  readonly absolute = computed(() => this.mode() === 'exact' && this.referenceSeconds === null);
  private readonly absoluteSeconds = computed(() => this.absolute() ? wallSeconds(LOCAL_DATE.exec(this.exactValue() ?? '')?.slice(1) ?? null) : null);
  /** The request's mode and value; two requests with the same key preview the same change. */
  private readonly change = computed<{ offset_seconds: number | null } | { set_date: string }>(() => {
    const seconds = this.absoluteSeconds();
    return this.absolute() ? { set_date: seconds === null ? '' : localInput(seconds) } : { offset_seconds: this.offset() };
  });
  readonly valid = computed(() => {
    if (this.absolute()) return this.data.count <= 1000 && this.absoluteSeconds() !== null;
    const offset = this.offset();
    return this.data.count <= 1000 && offset !== null && offset !== 0 && Math.abs(offset) <= MAX_OFFSET_SECONDS;
  });
  protected readonly summaryKey = computed(() => {
    if (this.absolute()) return this.I18N.capture_date.summary_set;
    return this.offset()! < 0 ? this.I18N.capture_date.summary_earlier : this.I18N.capture_date.summary_later;
  });
  protected readonly amount = computed(() => {
    if (this.absolute()) return this.absoluteSeconds() === null ? '' : formatExif(this.absoluteSeconds()!);
    const parts = splitOffset(Math.abs(this.offset() ?? 0));
    const units = { days: this.I18N.capture_date.unit_d, hours: this.I18N.capture_date.unit_h, minutes: this.I18N.capture_date.unit_min, seconds: this.I18N.capture_date.unit_s };
    return UNITS.filter(unit => parts[unit]).map(unit => `${parts[unit]} ${this.i18n.t(units[unit])}`).join(' ');
  });
  protected readonly referenceAfter = computed(() =>
    this.referenceSeconds !== null && this.valid() ? formatExif(this.referenceSeconds + this.offset()!) : null);

  constructor() {
    this.dialog.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closing = true; this.cancelPreview(); this.result.set(null); });
    this.destroyRef.onDestroy(() => this.cancelPreview());
    effect(() => {
      if (this.auth.status() !== this.owner || !this.auth.isEdition()) this.invalidate();
    });
    this.schedulePreview();
  }

  private invalidate(): void {
    this.closing = true;
    this.cancelPreview();
    this.result.set(null);
    this.dialog.close();
  }

  private current(): boolean {
    return !this.closing && this.staleness.current();
  }

  /** Drops the pending debounce and aborts a request still in flight: only the latest offset is ever previewed. */
  private cancelPreview(): void {
    clearTimeout(this.previewTimer);
    this.previewTimer = undefined;
    this.previewRequest?.unsubscribe();
    this.previewRequest = undefined;
  }

  /** Any change of the offset drops the shown preview and its error, and refreshes it once the input settles. */
  private schedulePreview(): void {
    this.result.set(null);
    this.failed.set(false);
    this.cancelPreview();
    if (!this.current() || !this.valid()) return;
    this.previewTimer = setTimeout(() => { this.previewTimer = undefined; void this.preview(); }, PREVIEW_DEBOUNCE_MS);
  }

  /** Sets a signed offset in seconds, shown split into direction and day/hour/minute/second fields. */
  setOffset(value: number): void {
    this.mode.set('shift');
    this.showOffset(value);
    this.schedulePreview();
  }

  /** Projects a signed offset onto the direction toggle and unit fields; zero keeps the current direction. */
  private showOffset(value: number): void {
    if (value !== 0) this.direction.set(value < 0 ? -1 : 1);
    this.parts.set(splitOffset(Math.abs(value)));
  }

  addOffset(delta: number): void { this.setOffset(Math.max(-MAX_OFFSET_SECONDS, Math.min(MAX_OFFSET_SECONDS, (this.offset() ?? 0) + delta))); }

  setPart(unit: keyof OffsetParts, value: number | null): void {
    this.parts.update(parts => ({ ...parts, [unit]: value ?? NaN }));
    this.schedulePreview();
  }

  setDirection(direction: 1 | -1): void { this.direction.set(direction); this.schedulePreview(); }

  setMode(mode: Mode): void {
    if (mode === 'exact' && this.valid() && this.referenceSeconds !== null) {
      this.exactValue.set(localInput(this.referenceSeconds + this.offset()!));
    }
    if (mode === 'shift' && this.offset() !== null && this.valid()) this.showOffset(this.offset()!);
    this.mode.set(mode);
    this.schedulePreview();
  }

  setExact(value: string): void { this.exactValue.set(value); this.schedulePreview(); }

  async preview(): Promise<void> {
    if (!this.current() || this.busy() || !this.valid()) return;
    const change = JSON.stringify(this.change());
    const body = this.change();
    this.cancelPreview();
    this.failed.set(false); this.result.set(null);
    // Settles on the reply, or on cancellation when a newer offset supersedes this request.
    await new Promise<void>(settled => {
      this.previewRequest = this.api.post<Preview>('/photos/capture_date/preview', { ...this.target, ...body })
        .pipe(take(1), finalize(settled))
        .subscribe({
          next: result => { if (this.current() && JSON.stringify(this.change()) === change) this.result.set(result); },
          error: () => { if (this.current() && JSON.stringify(this.change()) === change) this.failed.set(true); },
        });
    });
  }

  async apply(): Promise<void> {
    const preview = this.result();
    if (!this.current() || this.busy() || !preview?.changed || !this.valid()) return;
    this.busy.set(true); this.failed.set(false); this.dialog.disableClose = true;
    try {
      await firstValueFrom(this.api.post<Preview>('/photos/capture_date/apply', { ...this.target, ...this.change(), preview_token: preview.preview_token }));
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
