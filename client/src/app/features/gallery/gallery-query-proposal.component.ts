import { trackPendingNavigation } from '../../shared/utils/navigation-settled';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, effect, inject, input, signal, untracked, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { galleryFilterLabel } from './gallery-filter-label.pipe';
import { ADDITIONAL_FILTERS } from './gallery-metric-filters';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { ViewActionRegistry } from '../../core/agent/view-action-registry.service';
import { UiToolError, type JsonSchema, type UiToolContractFile } from '../../core/agent/ui-tool.types';
import { validateAgainstSchema } from '../../core/agent/schema-validate';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { GalleryStore } from './gallery.store';
import type { GalleryFilters } from './gallery-filters.util';

interface Proposal {
  id: number;
  source: string;
  unrepresented: string[];
  replace: boolean;
  patch: Record<string, unknown>;
  reset: Partial<GalleryFilters>;
  normalize: (patch: Record<string, unknown>) => Partial<GalleryFilters>;
  schema: JsonSchema;
  current: () => boolean;
  sessionCurrent: () => boolean;
  routePath: string;
}

interface Calculation {
  updates: Partial<GalleryFilters>;
  next: GalleryFilters;
  changes: { key: string; label: string; before: string; after: string }[];
  conflicts: string[];
  conflictText: string;
}

@Component({
  selector: 'app-gallery-query-proposal', imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush, host: { class: 'block min-w-0' },
  template: `
    @if (proposal(); as value) {
      <section data-query-proposal tabindex="-1" class="my-2 space-y-2 rounded border border-[var(--mat-sys-outline-variant)] p-3" (keydown.escape)="close($event)">
        <div class="flex items-start justify-between gap-2">
          <h2 #heading tabindex="-1" class="m-0 text-sm font-medium">{{ I18N.gallery.proposal.title | translate }}</h2>
          <button type="button" class="min-h-11 px-2 text-sm underline" [disabled]="applying()" (click)="close()">{{ (applied() ? I18N.dialog.close : I18N.ui.buttons.cancel) | translate }}</button>
        </div>
        <blockquote class="m-0 break-words text-sm">{{ value.source }}</blockquote>
        <p class="m-0 text-xs">{{ (value.replace ? I18N.gallery.proposal.replace : I18N.gallery.proposal.merge) | translate }}</p>
        @if (!applied()) { <div class="grid gap-2 sm:grid-cols-2">
          @for (row of rows(); track row.key) {
            <div class="flex min-w-0 items-end gap-2">
              <div class="min-w-0 flex-1 text-xs">
                @if (row.value === null) {
                  <span>{{ row.label }}</span><span class="block min-h-11 py-3">{{ I18N.gallery.proposal.reset | translate }}</span>
                } @else {
                  <label [attr.for]="'query-proposal-' + row.key">{{ row.label }}
                  @if (row.fraction) { <span class="block">{{ I18N.gallery.proposal.fraction | translate }}</span> }
                  @if (row.kind === 'boolean') {
                    <input [id]="'query-proposal-' + row.key" type="checkbox" class="ms-2 h-5 w-5" [checked]="row.value" [disabled]="applying()" (change)="edit(row.key, $any($event.target).checked)" />
                  } @else {
                  <input [id]="'query-proposal-' + row.key" [type]="row.kind" class="mt-1 min-h-11 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] px-2 text-base"
                    [value]="row.value" [disabled]="applying()" (input)="edit(row.key, $any($event.target).value, row.kind)" />
                  }
                  </label>
                }
              </div>
              <button type="button" class="min-h-11 px-2 text-xs underline" [disabled]="applying()" [attr.aria-label]="I18N.gallery.proposal.remove_named | translate:{ name: row.label }" (click)="remove(row.key)">{{ I18N.gallery.proposal.remove | translate }}</button>
            </div>
          }
        </div> }
        @if (calculation(); as result) {
          <h3 class="m-0 text-sm font-medium">{{ I18N.gallery.proposal.effective | translate }}</h3>
          <dl data-effective-changes class="m-0 max-h-60 overflow-auto text-xs">
            @for (change of result.changes; track change.key) {
              <div [attr.data-effective-field]="change.key" class="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-2 border-b border-[var(--mat-sys-outline-variant)] py-2">
                <dt class="break-words font-medium">{{ change.label }}</dt><dd class="m-0 break-all"><span>{{ change.before || (I18N.gallery.proposal.empty | translate) }}</span> → <strong>{{ change.after || (I18N.gallery.proposal.empty | translate) }}</strong></dd>
              </div>
            }
          </dl>
          @if (result.conflicts.length) { <p role="alert" class="m-0 text-sm">{{ I18N.gallery.proposal.conflict | translate }} {{ result.conflictText }}</p> }
        } @else if (!applied()) {
          <p role="alert" class="m-0 text-sm">{{ I18N.gallery.proposal.invalid | translate }}</p>
        }
        @if (value.unrepresented.length) {
          <div class="border-t border-[var(--mat-sys-outline-variant)] pt-2 text-sm">
            <h3 class="m-0 text-sm font-medium">{{ I18N.gallery.proposal.unrepresented | translate }}</h3>
            <ul class="my-1 list-disc pl-5">@for (clause of value.unrepresented; track $index) { <li class="break-words">{{ clause }}</li> }</ul>
            <label class="flex min-h-11 items-center gap-2"><input type="checkbox" [checked]="acknowledged()" [disabled]="applying()" (change)="acknowledged.set($any($event.target).checked)" />{{ I18N.gallery.proposal.acknowledge | translate }}</label>
          </div>
        }
        @if (store.viewScopeSelected()) { <p class="m-0 text-xs">{{ I18N.gallery.proposal.whole_view | translate }}</p> }
        @if (applied()) {
          <button type="button" data-retry-query-results class="min-h-11 underline" [disabled]="applying()" (click)="retry()">{{ I18N.gallery.proposal.retry | translate }}</button>
        } @else { <button data-apply-query-proposal type="button" class="min-h-11 rounded bg-[var(--mat-sys-primary)] px-3 text-sm text-[var(--mat-sys-on-primary)]"
          [disabled]="applying() || !valid() || store.viewScopeSelected() || (!!value.unrepresented.length && !acknowledged())" (click)="apply()">{{ I18N.gallery.proposal.apply | translate }}</button>
        }
      </section>
    }
    @if (error()) { <p role="alert" class="my-2 text-sm">{{ error() | translate }}</p> }
  `,
})
export class GalleryQueryProposalComponent {
  readonly active = input(false);
  protected readonly I18N = I18N;
  protected readonly store = inject(GalleryStore);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private fieldLabel(key: string): string {
    return galleryFilterLabel(key, value => this.i18n.t(value));
  }
  private readonly router = inject(Router);
  private readonly actions = inject(ViewActionRegistry);
  private readonly destroyRef = inject(DestroyRef);
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');
  readonly proposal = signal<Proposal | null>(null);
  readonly applying = signal(false);
  readonly applied = signal(false);
  private readonly accepted = signal<Calculation | null>(null);
  readonly acknowledged = signal(false);
  readonly error = signal('');
  private version = 0;
  private readonly pending = trackPendingNavigation({ started: event => {
    const plan = this.proposal();
    if (!this.applying() || !plan?.sessionCurrent() || event.url.split('?')[0] !== plan.routePath) this.clear();
  } });

  private readonly date = new CaptureDatePipe();
  private trigger: HTMLElement | null = null;
  readonly rows = computed(() => Object.entries(this.proposal()?.patch ?? {}).map(([key, value]) => ({
    key, value, label: this.fieldLabel(key), fraction: key === 'semantic_threshold' || key === 'min_similarity' || ADDITIONAL_FILTERS.some(row => (row.minKey === key || row.maxKey === key) && row.sliderMax === 1),
    kind: typeof value === 'boolean' ? 'boolean' : typeof value === 'number' ? 'number' : ['date_from', 'date_to'].includes(key) ? 'date' : 'text',
  })));
  readonly calculation = computed<Calculation | null>(() => {
    const accepted = this.accepted();
    if (accepted) return { ...accepted, changes: accepted.changes.map(change => ({ ...change, label: this.fieldLabel(change.key) })) };
    const plan = this.proposal();
    if (!plan || (!plan.replace && !Object.keys(plan.patch).length) || Object.values(plan.patch).some(value => typeof value === 'number' && !Number.isFinite(value)) || validateAgainstSchema(plan.schema, plan.patch).length) return null;
    try {
      const requested = plan.normalize(plan.patch);
      const updates = { ...(plan.replace ? plan.reset : {}), ...requested };
      const next = this.store.previewFilters(updates), before = this.store.filters();
      for (const date of [next.date_from, next.date_to]) {
        if (date && (!/^\d{4}-\d{2}-\d{2}$/.test(date) || this.date.transform(date) === date)) return null;
      }
      if (next.date_from && next.date_to && next.date_from > next.date_to) return null;
      const keys = Object.keys(next) as (keyof GalleryFilters)[];
      const conflicts = (Object.keys(requested) as (keyof GalleryFilters)[]).filter(key => requested[key] !== next[key]).map(key => this.fieldLabel(key));
      return { updates, next,
        changes: keys.filter(key => key !== 'page' && next[key] !== before[key]).map(key => ({ key, label: this.fieldLabel(key),
          before: key === 'date_from' || key === 'date_to' ? this.date.transform(String(before[key])) : String(before[key]),
          after: key === 'date_from' || key === 'date_to' ? this.date.transform(String(next[key])) : String(next[key]) })),
        conflicts, conflictText: conflicts.join(', ') };
    } catch { return null; }
  });
  readonly valid = computed(() => !!this.calculation() && !this.calculation()!.conflicts.length);

  constructor() {
    effect(cleanup => {
      const active = this.active(); this.auth.identity(); this.auth.status();
      untracked(() => { if (!this.applying() || !this.proposal()?.sessionCurrent()) this.clear(); });
      if (active) cleanup(this.actions.register('gallery_filter_proposal', args => this.present(args)));
    });
    effect(() => { const heading = this.heading(); if (heading) untracked(() => heading.nativeElement.focus()); });
    effect(() => {
      this.store.filters(); this.store.config(); this.store.pinnedPaths(); this.store.currentAlbum();
      untracked(() => {
        const plan = this.proposal();
        if (!plan || this.applying()) return;
        const accepted = this.accepted();
        if (!(accepted ? this.settlementCurrent(plan, accepted) : plan.current())) {
          this.clear(); this.error.set(I18N.gallery.proposal.changed);
        }
      });
    });

  }
  private clear(): void { this.version++; this.proposal.set(null); this.acknowledged.set(false); this.error.set(''); this.applied.set(false); this.accepted.set(null); }
  close(event?: Event): void {
    if (this.applying()) return;
    event?.preventDefault(); event?.stopPropagation(); this.clear();
    if (this.trigger?.isConnected) this.trigger.focus();
  }
  private async present(args: Record<string, unknown>): Promise<unknown> {
    if (this.pending() || !this.active() || !/^(\/|\/album\/\d+)$/.test(this.router.url.split('?')[0]) || this.store.pinnedPaths() !== null || this.proposal() || this.applying()) {
      throw new UiToolError('no_active_view', 'Close the current proposal and use an active, unpinned gallery.');
    }
    const owner = this.auth.identity(), status = this.auth.status(), token = this.auth.token, route = this.router.url;
    const config = this.store.config(), album = this.store.currentAlbum(), key = this.store.filterKey({ ...this.store.filters(), page: 1 });
    const version = ++this.version;
    const sessionCurrent = () => !this.destroyRef.destroyed && owner === this.auth.identity() && status === this.auth.status() && token === this.auth.token;
    const current = () => !this.destroyRef.destroyed && !this.pending() && this.active() && version === this.version
      && owner === this.auth.identity() && status === this.auth.status() && token === this.auth.token
      && route === this.router.url && config === this.store.config() && album === this.store.currentAlbum() && this.store.pinnedPaths() === null
      && key === this.store.filterKey({ ...this.store.filters(), page: 1 });
    const contract = (await import('../../core/agent/ui-tools.schema.json')).default as unknown as UiToolContractFile;
    if (!current()) throw new UiToolError('plan_changed', 'The gallery changed while preparing the proposal.');
    const schema = contract.tools.find(tool => tool.name === 'ui_set_gallery_filters')?.inputSchema.properties?.['patch'];
    const proposal = args['proposal'] as { source_query?: unknown; unrepresented?: unknown } | undefined;
    if (!schema || !proposal || typeof proposal.source_query !== 'string' || !Array.isArray(proposal.unrepresented)
      || typeof args['normalize'] !== 'function') throw new UiToolError('invalid_input', 'Invalid query proposal.');
    const normalize = args['normalize'] as Proposal['normalize'];
    const patch = structuredClone(args['patch'] as Record<string, unknown>);
    if (validateAgainstSchema(schema, patch).length) throw new UiToolError('invalid_input', 'Invalid proposed criteria.');
    normalize(patch);
    this.trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.proposal.set({ id: version, source: proposal.source_query, unrepresented: [...proposal.unrepresented] as string[],
      replace: args['replace'] === true, patch, reset: structuredClone(args['reset'] as Partial<GalleryFilters>), normalize, schema, current, sessionCurrent, routePath: route.split('?')[0] });
    this.acknowledged.set(false); this.error.set('');
    return { proposal_id: version, status: 'awaiting_user', applied: false };
  }
  edit(key: string, value: unknown, kind?: string): void {
    if (this.applying() || this.applied()) return;
    this.proposal.update(plan => plan ? { ...plan, patch: { ...plan.patch, [key]: kind === 'number' ? (value === '' ? NaN : Number(value)) : value } } : null);
    this.error.set('');
  }
  remove(key: string): void {
    if (this.applying() || this.applied()) return;
    this.proposal.update(plan => { if (!plan) return null; const patch = { ...plan.patch }; delete patch[key]; return { ...plan, patch }; });
  }
  async apply(): Promise<void> {
    const plan = this.proposal();
    if (!plan || this.applied() || this.applying() || !this.valid() || this.store.viewScopeSelected() || (plan.unrepresented.length && !this.acknowledged())) return;
    if (!plan.current()) { this.clear(); this.error.set(I18N.gallery.proposal.changed); return; }
    this.applying.set(true);
    const result = this.calculation()!;
    this.accepted.set(result); this.applied.set(true);
    try {
      await this.store.updateFilters(result.updates);
      if (this.proposal()?.id === plan.id) {
        if (!this.settlementCurrent(plan, result)) { this.clear(); return; }
        if (this.store.loadError()) this.error.set(I18N.gallery.proposal.load_error);
        else this.closeAfterApply();
      }
    } catch { if (this.proposal()?.id === plan.id) this.error.set(I18N.gallery.proposal.load_error); }
    finally { this.applying.set(false); }
  }
  private settlementCurrent(plan: Proposal, result: Calculation): boolean {
    return plan.sessionCurrent() && this.router.url.split('?')[0] === plan.routePath && this.store.pinnedPaths() === null
      && this.store.filterKey({ ...this.store.filters(), page: 1 }) === this.store.filterKey({ ...result.next, page: 1 });
  }
  async retry(): Promise<void> {
    const plan = this.proposal(), result = this.accepted();
    if (!plan || !result || !this.applied() || this.applying() || this.pending() || !this.active()) return;
    if (!this.settlementCurrent(plan, result)) { this.clear(); this.error.set(I18N.gallery.proposal.changed); return; }
    this.applying.set(true);
    try {
      await this.store.loadPhotos();
      if (this.proposal()?.id === plan.id && this.settlementCurrent(plan, result)) {
        if (this.store.loadError()) this.error.set(I18N.gallery.proposal.load_error);
        else this.closeAfterApply();
      }
    } catch { if (this.proposal()?.id === plan.id && this.settlementCurrent(plan, result)) this.error.set(I18N.gallery.proposal.load_error); }
    finally { this.applying.set(false); }
  }
  private closeAfterApply(): void {
    this.clear();
    if (this.trigger?.isConnected) this.trigger.focus();
  }
}
