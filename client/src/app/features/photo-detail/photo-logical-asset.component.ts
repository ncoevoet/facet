import { LogicalAssetApplied } from '../../shared/models/logical-asset-change';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18N } from '../../core/i18n/keys';
import type { components } from '../../core/api/schema';
import type { Photo } from '../../shared/models/photo.model';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

type Context = components['schemas']['LogicalAssetContext'];
type Change = components['schemas']['LogicalAssetChange'];
type Preview = components['schemas']['LogicalAssetPreview'];
type Result = components['schemas']['LogicalAssetResult'];

@Component({
  selector: 'app-photo-logical-asset',
  imports: [TranslatePipe],
  host: { class: 'block min-w-0' },
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <details data-logical-asset [open]="expanded()" tabindex="-1" (keydown.escape)="expanded() && close($event, trigger)">
      <summary #trigger (click)="toggle($event)" class="flex min-h-10 cursor-pointer items-center text-xs font-medium focus-visible:outline-2">{{ I18N.logical_assets.title | translate }}</summary>
      @if (expanded()) {
        <div class="space-y-2 pb-2 text-xs">
          @if (busy()) { <p role="status" class="m-0">{{ I18N.ui.labels.loading | translate }}</p> }
          @if (error()) { <p role="alert" class="m-0">{{ error() | translate }}</p> }
          @if (updated()) { <p role="status" class="m-0">{{ I18N.logical_assets.updated | translate }}</p> }
          @if (context(); as state) {
            @if (state.asset || state.can_group) {
              <p class="m-0 text-[var(--mat-sys-on-surface-variant)]">{{ I18N.logical_assets.preserve | translate }}</p>
              @if (state.asset && !state.asset.primary_path) { <p role="status" class="m-0">{{ I18N.logical_assets.primary_missing | translate }}</p> }
              <fieldset class="m-0 min-w-0 border-0 p-0" [disabled]="busy() || !auth.isEdition()">
                <legend class="sr-only">{{ I18N.logical_assets.choose_files | translate }}</legend>
                <div class="flex items-center justify-between gap-2 text-[var(--mat-sys-on-surface-variant)]"><span>{{ I18N.logical_assets.choose_files | translate }}</span><span>{{ I18N.logical_assets.primary | translate }}</span></div>
                @for (row of rows(); track row.path) {
                  <div class="flex min-w-0 items-center gap-2">
                    @if (!state.asset) {
                      <label class="flex min-h-10 min-w-0 flex-1 cursor-pointer items-center gap-2">
                        <input type="checkbox" [checked]="row.selected" [disabled]="row.path === photo().path || (atLimit() && !row.selected)" (change)="selectFile(row.path, $any($event.target).checked)" />
                        <bdi class="min-w-0 break-all">{{ row.name }}</bdi>
                      </label>
                    } @else { <bdi class="min-w-0 flex-1 break-all">{{ row.name }}</bdi> }
                    <label class="flex min-h-10 min-w-10 cursor-pointer items-center justify-center">
                      <span class="sr-only">{{ I18N.logical_assets.primary_for | translate:{ name: row.name } }}</span>
                      <input type="radio" [name]="'logical-primary-' + photo().path" [value]="row.path" [checked]="primary() === row.path" [disabled]="!row.selected" (change)="choosePrimary(row.path)" />
                    </label>
                  </div>
                }
              </fieldset>
              @if (!state.asset && auth.isEdition() && atLimit()) { <p role="status" class="m-0">{{ I18N.logical_assets.member_limit | translate }}</p> }
              @if (auth.isEdition()) {
                <div class="flex flex-wrap gap-2">
                  <button type="button" data-review-group class="min-h-10 cursor-pointer rounded border border-[var(--mat-sys-outline)] px-3 disabled:cursor-default disabled:opacity-50" [disabled]="busy() || !ready()" (click)="review(state.asset ? 'primary' : 'create')">{{ (state.asset ? I18N.logical_assets.review_primary : I18N.logical_assets.review_group) | translate }}</button>
                  @if (state.asset) { <button type="button" data-review-ungroup class="min-h-10 cursor-pointer rounded px-3 underline disabled:opacity-50" [disabled]="busy()" (click)="review('dissolve')">{{ I18N.logical_assets.ungroup | translate }}</button> }
                </div>
              }
            } @else { <p class="m-0 text-[var(--mat-sys-on-surface-variant)]">{{ I18N.logical_assets.no_candidates | translate }}</p> }
          } @else if (!busy()) { <button type="button" class="min-h-10 cursor-pointer underline" (click)="load()">{{ I18N.gallery.load_error.retry | translate }}</button> }
          @if (preview(); as plan) {
            <section data-group-preview class="space-y-2 rounded border border-[var(--mat-sys-outline-variant)] p-2" [attr.aria-label]="previewLabel() | translate">
              <p class="m-0 font-medium">{{ previewLabel() | translate }}</p>
              <dl class="m-0 space-y-2">
                @for (member of plan.members; track member.path) {
                  <div class="min-w-0"><dt class="break-all font-medium">{{ member.name }}</dt><dd class="m-0 flex flex-wrap gap-x-2">
                    <span>{{ I18N.logical_assets.rating | translate }}: {{ member.star_rating ?? '—' }}</span>
                    @if (member.is_kept) { <span>{{ I18N.review.kept | translate }}</span> }
                    @if (member.is_rejected) { <span>{{ I18N.review.rejected | translate }}</span> }
                    @if (member.is_favorite) { <span>{{ I18N.logical_assets.favorite | translate }}</span> }
                    @if (member.path === plan.primary_path) { <span>{{ I18N.logical_assets.primary | translate }}</span> }
                  </dd></div>
                }
              </dl>
              @if (plan.review_conflicts.length) { <label class="flex min-h-10 cursor-pointer items-center gap-2"><input data-conflict-ack type="checkbox" [checked]="acknowledged()" [disabled]="busy() || !auth.isEdition()" (change)="acknowledged.set($any($event.target).checked)" /><span>{{ I18N.logical_assets.acknowledge | translate }}</span></label> }
              <div class="flex flex-wrap gap-2">
                @if (auth.isEdition()) { <button type="button" data-apply-group class="min-h-10 cursor-pointer rounded border border-[var(--mat-sys-outline)] px-3 disabled:opacity-50" [disabled]="busy() || (plan.review_conflicts.length > 0 && !acknowledged())" (click)="apply(trigger)">{{ confirmLabel() | translate }}</button> }
                <button type="button" class="min-h-10 cursor-pointer px-3 underline disabled:opacity-50" [disabled]="busy()" (click)="cancelPreview(trigger)">{{ I18N.dialog.cancel | translate }}</button>
              </div>
            </section>
          }
        </div>
      }
    </details>
  `,
})
export class PhotoLogicalAssetComponent {
  readonly photo = input.required<Photo>();
  readonly applied = output<LogicalAssetApplied>();
  protected readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  protected readonly I18N = I18N;
  protected readonly expanded = signal(false);
  protected readonly context = signal<Context | null>(null);
  protected readonly primary = signal('');
  private readonly selected = signal(new Set<string>());
  protected readonly busy = signal(false);
  protected readonly atLimit = computed(() => this.selected().size >= 16);
  protected readonly error = signal('');
  protected readonly updated = signal(false);
  protected readonly preview = signal<Preview | null>(null);
  protected readonly acknowledged = signal(false);
  protected readonly previewLabel = computed(() => this.preview()?.operation === 'dissolve' ? I18N.logical_assets.preview_ungroup
    : this.preview()?.operation === 'primary' ? I18N.logical_assets.review_primary : I18N.logical_assets.review_group);
  protected readonly confirmLabel = computed(() => this.preview()?.operation === 'dissolve' ? I18N.logical_assets.confirm_ungroup
    : this.preview()?.operation === 'primary' ? I18N.logical_assets.confirm_primary : I18N.logical_assets.confirm_group);
  private change: Change | null = null;
  private request?: Subscription;
  private revision = 0;
  private navigating = false;
  private loadedScope: (() => boolean) | null = null;
  protected readonly rows = computed(() => {
    const state = this.context();
    return (state?.asset?.members ?? state?.candidates ?? []).map(row => ({ ...row, selected: !!state?.asset || this.selected().has(row.path) }));
  });
  protected readonly ready = computed(() => {
    const state = this.context();
    if (!state || !this.primary() || !this.selected().has(this.primary())) return false;
    if (state.asset) return this.primary() !== state.asset.primary_path;
    const selected = state.candidates.filter(row => this.selected().has(row.path));
    return selected.some(row => row.kind === 'raw') && selected.some(row => row.kind === 'jpeg');
  });

  constructor() {
    effect(() => { this.photo(); this.auth.status(); untracked(() => this.reset()); });
    this.router.events.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(event => {
      if (event instanceof NavigationStart) { this.navigating = true; this.reset(); }
      if (event instanceof NavigationEnd || event instanceof NavigationCancel || event instanceof NavigationError || event instanceof NavigationSkipped) this.navigating = false;
    });
    this.destroyRef.onDestroy(() => this.reset());
  }

  protected toggle(event: Event): void {
    event.preventDefault();
    if (this.expanded()) this.reset();
    else if (!this.navigating && this.auth.status()) { this.expanded.set(true); this.load(); }
  }
  protected close(event: Event, trigger: HTMLElement): void {
    event.preventDefault(); event.stopPropagation(); this.reset(); trigger.focus();
  }
  private scope(): () => boolean {
    const revision = this.revision, photo = this.photo(), owner = this.auth.status(), token = this.auth.token;
    return () => !this.destroyRef.destroyed && this.expanded() && !this.navigating && revision === this.revision
      && this.photo() === photo && this.auth.status() === owner && this.auth.token === token;
  }
  protected load(message = ''): void {
    if (!this.expanded() || this.navigating || !this.auth.status()) return;
    this.request?.unsubscribe(); this.revision++;
    const current = this.scope();
    this.loadedScope = current; this.context.set(null); this.clearPreview(); this.busy.set(true); this.error.set(message);
    this.request = this.api.get<Context>('/logical_assets/by-photo', { path: this.photo().path }).subscribe({
      next: state => {
        if (!current()) return;
        this.context.set(state); this.selected.set(new Set(state.asset?.members.map(row => row.path) ?? [this.photo().path]));
        this.primary.set(state.asset?.primary_path ?? ''); this.busy.set(false);
      },
      error: () => { if (current()) { this.busy.set(false); this.error.set(I18N.logical_assets.load_error); } },
    });
  }
  protected clearPreview(): void { this.preview.set(null); this.change = null; this.acknowledged.set(false); }
  protected cancelPreview(trigger: HTMLElement): void { if (!this.busy()) { this.clearPreview(); trigger.focus(); } }
  protected selectFile(path: string, included: boolean): void {
    if (this.busy() || path === this.photo().path) return;
    const selected = new Set(this.selected());
    if (included && selected.size >= 16) return;
    if (included) selected.add(path); else selected.delete(path);
    this.selected.set(selected); if (!selected.has(this.primary())) this.primary.set(''); this.clearPreview(); this.updated.set(false);
  }
  protected choosePrimary(path: string): void {
    if (this.busy() || !this.selected().has(path)) return;
    this.primary.set(path); this.clearPreview(); this.updated.set(false);
  }
  protected review(operation: Change['operation']): void {
    if (this.busy() || !this.auth.isEdition() || !this.loadedScope?.()) { if (!this.busy()) this.reset(); return; }
    const asset = this.context()?.asset;
    if (operation !== 'dissolve' && !this.ready() || operation !== 'create' && !asset) return;
    const change: Change = operation === 'create'
      ? { operation, paths: [...this.selected()], primary_path: this.primary() }
      : { operation, asset_id: asset!.asset_id, revision: asset!.revision, ...(operation === 'primary' ? { primary_path: this.primary() } : {}) };
    this.clearPreview(); this.busy.set(true); this.error.set(''); this.updated.set(false);
    const current = this.scope();
    this.request = this.api.post<Preview>('/logical_assets/preview', change).subscribe({
      next: plan => { if (current()) { this.change = change; this.preview.set(plan); this.busy.set(false); } },
      error: () => { if (current()) { this.busy.set(false); this.error.set(I18N.logical_assets.review_error); } },
    });
  }
  protected apply(trigger: HTMLElement): void {
    const plan = this.preview(), change = this.change;
    if (this.busy() || !plan || !change || !this.auth.isEdition() || !this.loadedScope?.()
      || plan.review_conflicts.length && !this.acknowledged()) return;
    this.busy.set(true); const current = this.scope();
    const document = this.host.nativeElement.ownerDocument, focused = document.activeElement;
    const restoreFocus = () => { if (document.activeElement === focused || document.activeElement === document.body) trigger.focus(); };
    this.request = this.api.post<Result>('/logical_assets/apply', { change, preview_token: plan.preview_token, acknowledge_review_conflicts: this.acknowledged() }).subscribe({
      next: result => { if (current()) { restoreFocus(); this.updated.set(true); this.load();
        this.applied.emit({ operation: change.operation, assetId: result.asset_id, primaryPath: plan.primary_path, members: plan.members.map(member => member.path) });
      } },
      error: () => { if (current()) { restoreFocus(); this.load(I18N.logical_assets.apply_error); } },
    });
  }
  private reset(): void {
    this.revision++; this.request?.unsubscribe(); this.request = undefined; this.loadedScope = null;
    this.expanded.set(false); this.context.set(null); this.clearPreview(); this.busy.set(false); this.error.set(''); this.updated.set(false);
  }
}
