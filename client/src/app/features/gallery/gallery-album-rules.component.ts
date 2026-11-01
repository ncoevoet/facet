import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { firstValueFrom } from 'rxjs';
import { GalleryStore } from './gallery.store';
import { AlbumService } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuard, StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';
import { smartAlbumFilterJson } from './gallery-filters.util';
import { albumRuleRows, AlbumRuleRow, hasUnsavableAlbumMode, restoreAlbumRuleFields } from './album-rules.util';
import { AlbumRuleValuePipe } from './album-rule-value.pipe';

interface RulePlan { id: number; before: string | null; after: string; rows: AlbumRuleRow[]; }

@Component({
  selector: 'app-gallery-album-rules', changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatButtonModule, TranslatePipe, AlbumRuleValuePipe], host: { class: 'block' },
  template: `
    @if (store.currentAlbum(); as album) {
      <details data-album-rules class="my-1 max-h-[45dvh] overflow-y-auto text-xs text-[var(--mat-sys-on-surface-variant)]">
        <summary class="cursor-pointer py-2">{{ (album.is_smart ? I18N.albums.rules.smart : I18N.albums.rules.manual) | translate }}@if (album.is_smart) { · {{ (changed() ? I18N.albums.rules.temporary : I18N.albums.rules.saved) | translate }} }</summary>
        <p class="my-1">{{ (album.is_smart ? I18N.albums.rules.smart_hint : I18N.albums.rules.manual_hint) | translate }}</p>
        @if (album.is_smart) {
          @if (baseline()) {
            <div class="max-h-60 overflow-auto">
              <table class="w-full text-left text-xs"><thead><tr><th scope="col" class="p-1">{{ I18N.organization_history.field | translate }}</th><th scope="col" class="p-1">{{ I18N.albums.rules.saved | translate }}</th><th scope="col" class="p-1">{{ I18N.albums.rules.working | translate }}</th></tr></thead>
                <tbody>@for (row of rows(); track row.key) { <tr [class.font-semibold]="row.changed"><th scope="row" class="p-1">{{ row.label }}</th><td class="p-1 break-all">{{ row.saved | albumRuleValue:row.key | translate }}</td><td class="p-1 break-all">{{ row.working | albumRuleValue:row.key | translate }}</td></tr> }</tbody>
              </table>
            </div>
          } @else { <p role="alert">{{ I18N.albums.rules.invalid | translate }}</p><button mat-button data-album-reload [disabled]="!active() || busy()" (click)="reload()">{{ I18N.albums.rules.reload | translate }}</button> }
          <p class="my-1">{{ I18N.albums.rules.presentation | translate }}</p>
          @if (blocked()) { <p role="status">{{ I18N.albums.rules.unsupported | translate }}</p> }
          <div class="flex flex-wrap gap-1">
            <button mat-button data-album-reset [disabled]="!active() || busy() || blocked() || !changed() || !baseline()" (click)="reset()">{{ I18N.albums.rules.reset | translate }}</button>
            @if (auth.isEdition()) { <button mat-button data-album-preview [disabled]="!active() || busy() || blocked() || !changed() || !baseline()" (click)="preview()">{{ I18N.albums.rules.preview | translate }}</button> }
          </div>
          @if (plan(); as captured) {
            <section data-album-rule-preview class="my-2 rounded border border-[var(--mat-sys-outline-variant)] p-2">
              <p>{{ I18N.albums.rules.confirm | translate:{ count: captured.rows.length, name: album.name } }}</p>
              <ul class="m-0 max-h-48 overflow-auto pl-4">@for (row of captured.rows; track row.key) { <li>{{ row.label }}: {{ row.saved | albumRuleValue:row.key | translate }} → {{ row.working | albumRuleValue:row.key | translate }}</li> }</ul>
              <button mat-button [disabled]="busy()" (click)="cancel()">{{ I18N.ui.buttons.cancel | translate }}</button>
              <button mat-flat-button data-album-apply [disabled]="!active() || busy() || uncertain()" (click)="save()">{{ I18N.albums.rules.save | translate }}</button>
            </section>
          }
          @if (message(); as messageKey) { <p role="status">{{ messageKey | translate }}</p> }
          @if (error(); as errorKey) { <p role="alert">{{ errorKey | translate }}</p><button mat-button data-album-reload [disabled]="!active() || busy()" (click)="reload()">{{ I18N.albums.rules.reload | translate }}</button> }
        }
      </details>
    }
  `,
})
export class GalleryAlbumRulesComponent {
  readonly active = input.required<boolean>();
  protected readonly I18N = I18N;
  protected readonly store = inject(GalleryStore);
  protected readonly auth = inject(AuthService);
  private readonly albums = inject(AlbumService);
  private readonly guards = inject(StalenessGuardFactory);
  private readonly destroyRef = inject(DestroyRef);
  private guard: StalenessGuard | null = null;
  private token: string | null = null;
  protected readonly plan = signal<RulePlan | null>(null);
  protected readonly busy = signal(false);
  protected readonly uncertain = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly message = signal<string | null>(null);
  protected readonly baseline = computed(() => {
    const album = this.store.currentAlbum();
    if (!album?.is_smart) return null;
    try { return restoreAlbumRuleFields(this.store.filters(), album.smart_filter_json ?? '{}', this.store.config()?.defaults.sort, this.store.config()?.defaults.sort_direction, this.store.config()?.defaults.type); }
    catch { return null; }
  });
  protected readonly rows = computed(() => { const saved = this.baseline(); return saved ? albumRuleRows(saved, this.store.filters()) : []; });
  protected readonly changed = computed(() => this.rows().some(row => row.changed));
  protected readonly blocked = computed(() => this.store.temporaryReviewQueue() || hasUnsavableAlbumMode(this.store.filters(), this.store.pinnedPaths() !== null));

  constructor() {
    effect(() => {
      const plan = this.plan();
      if (plan && (!this.active() || !this.guard?.current() || this.store.currentAlbum()?.id !== plan.id || !this.auth.isEdition()
        || smartAlbumFilterJson(this.store.filters()) !== plan.after || this.blocked())) this.cancel();
    });
    this.destroyRef.onDestroy(() => this.guard?.dispose());
  }

  protected cancel(): void { this.guard?.dispose(); this.guard = null; this.plan.set(null); }

  protected preview(): void {
    const album = this.store.currentAlbum();
    if (!this.active() || !album?.is_smart || !this.auth.isEdition() || this.busy() || this.blocked() || !this.baseline() || !this.changed()) return;
    this.cancel(); this.error.set(null); this.message.set(null); this.uncertain.set(false);
    this.token = this.auth.token;
    this.guard = this.guards.create(this.destroyRef, { track: 'status', valid: () => this.token === this.auth.token, onNavigate: () => this.cancel() });
    this.plan.set({ id: album.id, before: album.smart_filter_json, after: smartAlbumFilterJson(this.store.filters()), rows: this.rows().filter(row => row.changed) });
  }

  private current(plan: RulePlan): boolean {
    const album = this.store.currentAlbum();
    return this.active() && !!this.guard?.current() && album?.id === plan.id && album.is_smart && album.smart_filter_json === plan.before
      && this.token === this.auth.token && !this.blocked() && smartAlbumFilterJson(this.store.filters()) === plan.after;
  }

  protected async save(): Promise<void> {
    const plan = this.plan();
    if (!plan || this.busy() || this.uncertain() || !this.current(plan)) return;
    this.busy.set(true); this.error.set(null);
    let submitted = false;
    const guard = this.guard!;
    try {
      const latest = await firstValueFrom(this.albums.get(plan.id));
      if (!this.current(plan)) return;
      if (!latest.is_smart || latest.smart_filter_json !== plan.before) { this.error.set(I18N.albums.rules.conflict); return; }
      submitted = true;
      const saved = await firstValueFrom(this.albums.update(plan.id, { smart_filter_json: plan.after }));
      // A newer working query remains theirs; only repair the saved album's metadata.
      if (!guard.current() || this.store.currentAlbum()?.id !== plan.id || this.store.currentAlbum()?.smart_filter_json !== plan.before) return;
      this.store.currentAlbum.set(saved); this.message.set(I18N.albums.rules.success); this.cancel();
    } catch {
      if (guard.current()) { this.uncertain.set(submitted); this.error.set(submitted ? I18N.albums.rules.uncertain : I18N.albums.rules.failed); }
    } finally { if (!this.destroyRef.destroyed) this.busy.set(false); }
  }

  protected async reset(): Promise<void> {
    const filters = this.baseline();
    if (!this.active() || !filters || this.blocked() || this.busy()) return;
    this.cancel(); this.error.set(null); this.message.set(null);
    await this.store.restoreAlbumRules(filters);
  }

  protected async reload(): Promise<void> {
    const album = this.store.currentAlbum();
    if (!this.active() || !album?.is_smart || this.busy()) return;
    this.cancel(); this.busy.set(true); this.error.set(null);
    const token = this.auth.token;
    const guard = this.guards.create(this.destroyRef, { requireEdition: false, track: 'status', valid: () => this.active() && token === this.auth.token });
    try {
      const latest = await firstValueFrom(this.albums.get(album.id));
      if (guard.current() && this.store.currentAlbum()?.id === album.id) { this.store.currentAlbum.set(latest); this.uncertain.set(false); }
    } catch { if (guard.current()) this.error.set(I18N.albums.rules.failed); }
    finally { guard.dispose(); if (!this.destroyRef.destroyed) this.busy.set(false); }
  }
}
