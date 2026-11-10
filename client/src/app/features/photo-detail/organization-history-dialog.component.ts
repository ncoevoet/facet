import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe, NgTemplateOutlet, SlicePipe } from '@angular/common';
import { NavigationStart, Router, RouterLink } from '@angular/router';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { firstValueFrom } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { i18nKeys } from '../../core/i18n/keys';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { GalleryStore } from '../gallery/gallery.store';
import { HistoryDiffPipe } from './organization-history-diff.pipe';

type Entry = components['schemas']['OrganizationEntry'];
type History = components['schemas']['OrganizationHistory'];
type Revert = components['schemas']['OrganizationRevert'];

/** Thumbnails shown per entry before the rest are counted as "+N". */
const PHOTO_PREVIEWS = 6;
const REVERT_ERROR_BY_STATUS: Record<number, 'conflict' | 'unavailable'> = { 409: 'conflict', 404: 'unavailable' };

@Component({
  selector: 'app-organization-history-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, RouterLink, NgTemplateOutlet, TranslatePipe, DatePipe, SlicePipe, PluralKeyPipe, FilenamePipe, ThumbnailUrlPipe, HistoryDiffPipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title>{{ I18N.organization_history.title | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm mb-4">{{ I18N.organization_history.hint | translate }}</p>
      <details class="mb-3 text-sm"><summary class="cursor-pointer py-1">{{ I18N.organization_history.limits_title | translate }}</summary><p>{{ I18N.organization_history.limits | translate }}</p></details>
      <button mat-button data-history-reload [disabled]="busy()" (click)="load()">{{ I18N.organization_history.reload | translate }}</button>
      @if (busy()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (error() && failedEntryId() === null) { <p role="alert" class="my-3">{{ I18N.organization_history[error()!] | translate }}</p> }
      @if (changed() !== null) { <p role="status" class="my-3">{{ I18N.organization_history.success | translate:{ count: changed() ?? 0 } }}</p> }
      @for (entry of entries(); track entry.id) {
        @let diff = entry | historyDiff;
        <section class="border border-current/20 rounded-lg p-3 mb-3">
          @if (failedEntryId() === entry.id && error(); as failure) { <p role="alert">{{ I18N.organization_history[failure] | translate }}</p> }
          <h3 class="font-medium">{{ I18N.organization_history[entry.kind] | translate }} · {{ entry.created_at | date:'dd/MM/yyyy HH:mm' }}</h3>
          @if (diff.summary.length) {
            <p data-history-summary class="text-sm mt-1 break-words">@for (change of diff.summary; track change.label; let last = $last) {<ng-container [ngTemplateOutlet]="changeText" [ngTemplateOutletContext]="{ $implicit: change }" />@if (!last) { · }}</p>
          }
          @if (entry.parts > 1) { <p class="text-sm mt-1">{{ I18N.organization_history.part | translate:{ part: entry.part, parts: entry.parts, count: entry.changes.length } }}</p> }
          <div data-history-photos class="flex flex-wrap items-center gap-2 my-2">
            @for (photo of diff.photos | slice:0:previews; track photo.path) {
              <a data-history-photo routerLink="/photo" [queryParams]="{ path: photo.path }" target="_blank" rel="noopener" [title]="photo.path" [attr.aria-label]="I18N.organization_history.open_photo | translate:{ name: (photo.path | filename) }"
                class="block size-10 pointer-coarse:size-11 shrink-0 overflow-hidden rounded focus-visible:outline-2">
                <img [src]="photo.path | thumbnailUrl:96" alt="" loading="lazy" decoding="async" class="size-full object-cover" />
              </a>
            }
            @if (diff.photos.length === 1) { <span class="min-w-0 break-all text-sm" [title]="diff.photos[0].path">{{ diff.photos[0].path | filename }}</span> }
            @else {
              <span class="text-sm text-[var(--mat-sys-on-surface-variant)]">@if (diff.photos.length > previews) {+{{ diff.photos.length - previews }} · }{{ I18N.organization_history.photo_count | translate:{ count: diff.photos.length } }}</span>
            }
          </div>
          <details class="mb-2" (toggle)="toggleEntry(entry.id, $event)">
            <summary class="cursor-pointer">{{ I18N.organization_history.photo_changes | translate }}</summary>
            @if (expanded().has(entry.id)) {
              <ul class="mt-2">
                @for (photo of diff.photos; track photo.path) {
                  <li data-history-photo-changes class="flex items-start gap-2 py-1 text-sm">
                    <img [src]="photo.path | thumbnailUrl:96" alt="" loading="lazy" decoding="async" class="size-8 shrink-0 rounded object-cover" />
                    <p class="min-w-0 break-words">
                      <span class="block break-all font-medium" [title]="photo.path">{{ photo.path | filename }}</span>
                      @for (change of photo.changes; track change.label; let last = $last) {<ng-container [ngTemplateOutlet]="changeText" [ngTemplateOutletContext]="{ $implicit: change }" />@if (!last) { · }}
                      @empty { {{ I18N.organization_history.unchanged | translate }} }
                    </p>
                  </li>
                }
              </ul>
            }
          </details>
          <button mat-button [disabled]="busy() || entry.reverted || entry.superseded" [attr.aria-describedby]="entry.superseded && !entry.reverted ? 'history-superseded-' + entry.id : null" (click)="previewRestore(entry)"
            [attr.aria-label]="I18N.organization_history.entry_action | translate:{ action: ((entry.reverted ? I18N.organization_history.reverted : I18N.organization_history.preview_action) | translate), kind: (I18N.organization_history[entry.kind] | translate), date: ((entry.created_at | date:'dd/MM/yyyy HH:mm') ?? ''), id: entry.id }">{{ (entry.reverted ? I18N.organization_history.reverted : I18N.organization_history.preview_action) | translate }}</button>
          @if (entry.superseded && !entry.reverted) { <p data-history-superseded [id]="'history-superseded-' + entry.id" class="my-1 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.organization_history.superseded | translate }}</p> }
          @if (restorePlan()?.id === entry.id) {
            <section data-history-preview class="my-2 rounded border border-[var(--mat-sys-outline-variant)] p-3 text-sm">
              <p>{{ (entry.changes.length | pluralKey:I18N.organization_history.restore_preview:I18N.organization_history.restore_preview_plural) | translate:{ count: entry.changes.length } }}</p>
              <button mat-button [disabled]="busy()" (click)="restorePlan.set(null)">{{ I18N.ui.buttons.cancel | translate }}</button>
              <button mat-flat-button data-history-apply [disabled]="busy()" (click)="confirmRestore()">{{ I18N.organization_history.revert | translate }}</button>
            </section>
          }
        </section>
      } @empty { @if (!busy() && !error()) { <p>{{ I18N.organization_history.empty | translate }}</p> } }
    </mat-dialog-content>
    <mat-dialog-actions align="end"><button mat-button mat-dialog-close>{{ I18N.dialog.close | translate }}</button></mat-dialog-actions>
    <ng-template #changeText let-change><span data-history-change>{{ change.label | translate }}:
      @if (change.before === null && change.after === null) { {{ I18N.organization_history.various | translate }} }
      @else {<ng-container [ngTemplateOutlet]="historyValue" [ngTemplateOutletContext]="{ $implicit: change.before }" /> → <span class="font-medium"><ng-container [ngTemplateOutlet]="historyValue" [ngTemplateOutletContext]="{ $implicit: change.after }" /></span>}
    </span></ng-template>
    <ng-template #historyValue let-value>@if (value === null) { {{ I18N.organization_history.various | translate }} } @else if (value.key) { {{ value.key | translate }} } @else { {{ value.text }} }</ng-template>
  `,
})
export class OrganizationHistoryDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly store = inject(GalleryStore);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialogRef<OrganizationHistoryDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly owner = this.auth.identity();
  private readonly url = this.router.url;
  private navigated = false;
  private closing = false;
  private ownerInvalidated = false;
  private pendingRestore: Promise<void> | null = null;
  readonly wasRestored = signal(false);

  whenSettled(): Promise<void> { return this.pendingRestore ?? Promise.resolve(); }
  readonly expanded = signal(new Set<number>());
  readonly entries = signal<Entry[]>([]);
  readonly changed = signal<number | null>(null);
  readonly error = signal<'conflict' | 'unavailable' | 'error' | null>(null);
  readonly failedEntryId = signal<number | null>(null);
  readonly restorePlan = signal<Entry | null>(null);
  private loadGeneration = 0;
  readonly busy = signal(false);
  protected readonly previews = PHOTO_PREVIEWS;

  constructor() {
    this.dialog.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closing = true; });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) {
        this.navigated = true;
        this.entries.set([]);
        this.dialog.close();
      }
    });
    effect(() => {
      if (this.auth.identity() !== this.owner || !this.auth.isEdition()) {
        this.ownerInvalidated = true;
        this.entries.set([]);
        this.dialog.close();
      }
    });
  }

  toggleEntry(id: number, event: Event): void {
    const open = (event.target as HTMLDetailsElement).open;
    this.expanded.update(previous => {
      const next = new Set(previous);
      if (open) next.add(id); else next.delete(id);
      return next;
    });
  }

  ngOnInit(): void { void this.load(); }

  private current(): boolean {
    return !this.closing && !this.destroyRef.destroyed && this.sessionCurrent();
  }

  private sessionCurrent(): boolean {
    return !this.ownerInvalidated && !this.navigated && this.auth.identity() === this.owner && this.auth.isEdition() && this.router.url === this.url;
  }

  async load(): Promise<void> {
    if (!this.current()) return;
    const generation = ++this.loadGeneration;
    this.restorePlan.set(null); this.failedEntryId.set(null);
    this.busy.set(true); this.error.set(null); this.entries.set([]);
    try {
      const result = await firstValueFrom(this.api.get<History>('/organization_history'));
      if (this.current() && generation === this.loadGeneration) this.entries.set(result.entries);
    } catch { if (this.current() && generation === this.loadGeneration) this.error.set('error'); }
    finally { if (this.current() && generation === this.loadGeneration) this.busy.set(false); }
  }

  previewRestore(entry: Entry): void {
    if (this.current() && !this.busy() && !entry.reverted && !entry.superseded) this.restorePlan.set(structuredClone(entry));
  }

  async confirmRestore(): Promise<void> {
    const entry = this.restorePlan();
    if (!entry) return;
    this.restorePlan.set(null);
    await this.revert(entry);
  }

  async revert(entry: Entry): Promise<void> {
    if (!this.current() || this.busy() || entry.reverted || entry.superseded) return;
    this.pendingRestore = this.performRevert(entry);
    await this.pendingRestore;
  }

  private async performRevert(entry: Entry): Promise<void> {
    // Keep watching navigation until the write settles, even if the dialog is destroyed.
    const navigation = this.router.events.subscribe(event => {
      if (event instanceof NavigationStart) this.navigated = true;
    });
    const id = entry.id;
    this.busy.set(true); this.error.set(null); this.changed.set(null);
    this.failedEntryId.set(null);
    try {
      const result = await firstValueFrom(this.api.post<Revert>(`/organization_history/${id}/revert`, {}));
      if (!this.sessionCurrent()) return;
      this.wasRestored.set(true);
      void this.store.refreshPaths(null);
      if (this.current()) {
        this.changed.set(result.changed);
        await this.load();
      }
    } catch (failure) {
      if (this.current()) {
        const status = (failure as { status?: number }).status;
        this.failedEntryId.set(id);
        this.error.set((status !== undefined && REVERT_ERROR_BY_STATUS[status]) || 'error');
      }
    } finally {
      navigation.unsubscribe();
      if (this.current()) this.busy.set(false);
    }
  }
}
