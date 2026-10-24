import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { NavigationStart, Router } from '@angular/router';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { firstValueFrom } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { GalleryStore } from '../gallery/gallery.store';

type Entry = components['schemas']['OrganizationEntry'];
type History = components['schemas']['OrganizationHistory'];
type Revert = components['schemas']['OrganizationRevert'];

@Component({
  selector: 'app-organization-history-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, TranslatePipe, DatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title>{{ I18N.organization_history.title | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm mb-4">{{ I18N.organization_history.hint | translate }}</p>
      @if (busy()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (error(); as failure) { <p role="alert" class="my-3">{{ I18N.organization_history[failure] | translate }}</p> }
      @if (changed() !== null) { <p role="status" class="my-3">{{ I18N.organization_history.success | translate:{ count: changed() ?? 0 } }}</p> }
      @for (entry of entries(); track entry.id) {
        <section class="border border-current/20 rounded-lg p-3 mb-3">
          <h3 class="font-medium">{{ I18N.organization_history[entry.kind] | translate }} · {{ entry.created_at | date:'medium' }}</h3>
          <p class="text-sm my-2">
            @if (entry.parts > 1) { {{ I18N.organization_history.part | translate:{ part: entry.part, parts: entry.parts, count: entry.changes.length } }} }
            @else { {{ I18N.organization_history.photo_count | translate:{ count: entry.changes.length } }} }
          </p>
          <details class="mb-2" (toggle)="toggleEntry(entry.id, $event)">
            <summary class="cursor-pointer">{{ I18N.capture_date.before | translate }} → {{ I18N.capture_date.after | translate }}</summary>
            @if (expanded().has(entry.id)) {
            @for (change of entry.changes; track change.path) {
              <p class="text-sm break-all font-medium mt-3">{{ change.path }}</p>
              @if (entry.kind === 'review') {
                <p class="text-sm">{{ I18N.organization_history.review | translate }}:
                  {{ (change.before[2] ? I18N.organization_history.rejected : change.before[3] ? I18N.organization_history.kept : I18N.culling.lightbox.undecided) | translate }}
                  → {{ (change.after[2] ? I18N.organization_history.rejected : change.after[3] ? I18N.organization_history.kept : I18N.culling.lightbox.undecided) | translate }}
                </p>
              }
              <table class="w-full text-sm"><thead><tr><th></th><th>{{ I18N.capture_date.before | translate }}</th><th>{{ I18N.capture_date.after | translate }}</th></tr></thead>
              <tbody>@for (field of fields[entry.kind]; track field.key; let i = $index) {
                <tr><th class="text-left p-1">{{ field.key | translate }}</th>
                  @for (value of [change.before[i], change.after[i]]; track $index) {
                    <td class="p-1 text-center">@if (value === null) { {{ I18N.organization_history.unknown | translate }} } @else if (field.flag) { {{ (value ? I18N.organization_history.yes : I18N.organization_history.no) | translate }} } @else { {{ value }} }</td>
                  }
                </tr>
              }</tbody></table>
            }
            }
          </details>
          <button mat-button [disabled]="busy() || entry.reverted" (click)="revert(entry)">{{ (entry.reverted ? I18N.organization_history.reverted : I18N.organization_history.revert) | translate }}</button>
        </section>
      } @empty { @if (!busy()) { <p>{{ I18N.organization_history.empty | translate }}</p> } }
    </mat-dialog-content>
    <mat-dialog-actions align="end"><button mat-button mat-dialog-close>{{ I18N.dialog.close | translate }}</button></mat-dialog-actions>
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
  private readonly owner = this.auth.status();
  private readonly url = this.router.url;
  private navigated = false;
  private closing = false;
  readonly wasRestored = signal(false);
  readonly expanded = signal(new Set<number>());
  readonly entries = signal<Entry[]>([]);
  readonly changed = signal<number | null>(null);
  readonly error = signal<'conflict' | 'unavailable' | 'error' | null>(null);
  readonly busy = signal(false);
  readonly fields = {
    gps: [{ key: this.I18N.organization_history.latitude, flag: false }, { key: this.I18N.organization_history.longitude, flag: false }, { key: this.I18N.organization_history.manual_gps, flag: true }],
    date: [{ key: this.I18N.organization_history.capture_date, flag: false }, { key: this.I18N.organization_history.manual_date, flag: true }],
    review: [{ key: this.I18N.organization_history.stars, flag: false }, { key: this.I18N.organization_history.favorite, flag: true }, { key: this.I18N.organization_history.rejected, flag: true }, { key: this.I18N.organization_history.kept, flag: true }],
  };

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
      if (this.auth.status() !== this.owner || !this.auth.isEdition()) {
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
    return !this.closing && !this.navigated && !this.destroyRef.destroyed && this.auth.status() === this.owner && this.auth.isEdition() && this.router.url === this.url;
  }

  async load(): Promise<void> {
    if (!this.current()) return;
    this.busy.set(true); this.error.set(null); this.entries.set([]);
    try {
      const result = await firstValueFrom(this.api.get<History>('/organization_history'));
      if (this.current()) this.entries.set(result.entries);
    } catch { if (this.current()) this.error.set('error'); }
    finally { if (this.current()) this.busy.set(false); }
  }

  async revert(entry: Entry): Promise<void> {
    if (!this.current() || this.busy() || entry.reverted) return;
    const id = entry.id;
    this.busy.set(true); this.error.set(null); this.changed.set(null);
    try {
      const result = await firstValueFrom(this.api.post<Revert>(`/organization_history/${id}/revert`, {}));
      if (!this.current()) return;
      this.wasRestored.set(true);
      this.changed.set(result.changed);
      void this.store.refreshPaths(null);
      await this.load();
    } catch (failure) {
      if (this.current()) {
        const status = (failure as { status?: number }).status;
        this.error.set(status === 409 ? 'conflict' : status === 404 ? 'unavailable' : 'error');
      }
    } finally { if (this.current()) this.busy.set(false); }
  }
}
