import { isNavigationSettled } from '../../shared/utils/navigation-settled';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { firstValueFrom, Subject, takeUntil } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';
import { GalleryStore } from './gallery.store';

type Catalog = components['schemas']['KeywordCatalogResponse'];
type Preview = components['schemas']['KeywordChangePreview'];
type Result = components['schemas']['KeywordChangeResult'];

@Component({
  selector: 'app-keyword-catalog', imports: [TranslatePipe, ContextHelpComponent],
  changeDetection: ChangeDetectionStrategy.OnPush, host: { class: 'block min-w-0' },
  template: `
    <details #panel data-keyword-catalog (toggle)="toggle(panel.open)" (keydown.escape)="escape($event, panel, trigger)">
      <summary #trigger class="flex min-h-11 cursor-pointer items-center text-sm font-medium">{{ I18N.keyword_catalog.title | translate }}</summary>
      @if (opened()) {
        <form class="flex gap-2" (submit)="$event.preventDefault(); load()">
          <label class="min-w-0 flex-1 text-xs">{{ I18N.keyword_catalog.search | translate }}
            <input #searchInput data-keyword-search type="search" maxlength="64" [value]="search()" (input)="search.set($any($event.target).value); catalog.set(null)"
              class="mt-1 h-10 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-lowest)] px-2 text-base" />
          </label>
          <button type="submit" class="self-end min-h-11 rounded border border-[var(--mat-sys-outline)] px-2 text-xs" [disabled]="busy()">{{ I18N.keyword_catalog.find | translate }}</button>
        </form>
        @if (error()) { <p role="alert" class="text-xs">{{ I18N.keyword_catalog.error | translate }}</p> }
        @if (loading()) { <p role="status" class="text-xs">{{ I18N.ui.labels.loading | translate }}</p> }
        @if (catalog(); as page) {
          <p role="status" class="text-xs">{{ I18N.keyword_catalog.count | translate:{ count: page.total } }}</p>
          <ul class="m-0 list-none p-0">
            @for (item of page.items; track item.tag) {
              <li class="flex min-w-0 items-center gap-1 border-b border-[var(--mat-sys-outline-variant)]">
                <button data-keyword-filter type="button" class="min-h-11 min-w-0 flex-1 break-words text-left text-sm" (click)="filter(item.tag)"><bdi>{{ item.tag }}</bdi><span class="ml-2 tabular-nums text-[var(--mat-sys-on-surface-variant)]">{{ item.count }}</span></button>
                @if (auth.isEdition()) {
                  <button type="button" data-keyword-manage class="min-h-11 shrink-0 px-2 text-xs underline" [disabled]="busy()"
                    [attr.aria-label]="I18N.keyword_catalog.manage_named | translate:{ name: item.tag }" (click)="manage(item.tag)">{{ I18N.keyword_catalog.manage | translate }}</button>
                }
              </li>
            }
          </ul>
          <div class="flex justify-between gap-2">
            <button type="button" class="min-h-11 text-xs underline" [disabled]="busy()" (click)="load()">{{ I18N.keyword_catalog.reload | translate }}</button>
            @if (page.next_after) { <button type="button" class="min-h-11 text-xs underline" [disabled]="busy()" (click)="load(page.next_after)">{{ I18N.keyword_catalog.next | translate }}</button> }
          </div>
        }
        @if (source(); as name) {
          <section class="mt-2 space-y-2 border-t border-[var(--mat-sys-outline-variant)] pt-2" data-keyword-editor>
            <h3 class="m-0 break-words text-sm font-medium"><bdi>{{ name }}</bdi></h3>
            <label class="block text-xs">{{ I18N.keyword_catalog.target | translate }}
              <input #targetInput data-keyword-target type="text" maxlength="64" [disabled]="saving() || uncertain()" [value]="target()" (input)="target.set($any($event.target).value); plan.set(null)"
                class="mt-1 h-10 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-lowest)] px-2 text-base" />
            </label>
            @if (plan(); as captured) {
              <p class="text-xs" data-keyword-preview>{{ I18N.keyword_catalog.preview | translate:{ count: captured.paths.length, renamed: captured.renamed, merged: captured.merged, ai: captured.ai_matches, removed: captured.removed } }}</p>
              <details><summary class="min-h-11 cursor-pointer text-xs">{{ I18N.keyword_catalog.targets | translate:{ count: captured.paths.length } }}</summary>
                <ul class="m-0 list-none break-all p-0 text-xs">@for (path of previewPaths(); track path) { <li class="py-1"><bdi>{{ path }}</bdi></li> }</ul>
                <div class="flex justify-between gap-2">
                  <button type="button" class="min-h-11 text-xs underline" [disabled]="targetPage() === 0" (click)="targetPage.set(targetPage() - 1)">{{ I18N.keyword_catalog.previous | translate }}</button>
                  <button type="button" class="min-h-11 text-xs underline" [disabled]="(targetPage() + 1) * 25 >= captured.paths.length" (click)="targetPage.set(targetPage() + 1)">{{ I18N.keyword_catalog.next | translate }}</button>
                </div>
              </details>
              <button #applyButton type="button" data-keyword-apply class="min-h-11 rounded bg-[var(--mat-sys-primary)] px-3 text-sm text-[var(--mat-sys-on-primary)]" [disabled]="busy() || uncertain()" (click)="apply()">{{ I18N.ui.buttons.apply | translate }}</button>
            } @else {
              <div class="flex flex-wrap gap-2">
                <button type="button" class="min-h-11 rounded border border-[var(--mat-sys-outline)] px-2 text-xs" [disabled]="busy() || uncertain() || !target().trim()" (click)="preview(false)">{{ I18N.keyword_catalog.rename_preview | translate }}</button>
                <button type="button" class="min-h-11 rounded border border-[var(--mat-sys-outline)] px-2 text-xs" [disabled]="busy() || uncertain()" (click)="preview(true)">{{ I18N.keyword_catalog.remove_preview | translate }}</button>
              </div>
            }
          </section>
        }
        @if (uncertain()) { <p role="alert" class="text-xs">{{ I18N.keyword_catalog.uncertain | translate }}</p> }
        @if (result(); as change) { <p role="status" class="text-xs">{{ I18N.keyword_catalog.changed | translate:{ count: change.changed } }}</p> }
        <app-context-help [label]="I18N.keyword_catalog.help" [keys]="[I18N.keyword_catalog.boundary, I18N.keyword_catalog.literal]" />
      }
    </details>
  `,
})
export class KeywordCatalogComponent {
  protected readonly I18N = I18N;
  protected readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly store = inject(GalleryStore);
  private readonly guards = inject(StalenessGuardFactory);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly panel = viewChild<ElementRef<HTMLDetailsElement>>('panel');
  private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');
  private readonly targetInput = viewChild<ElementRef<HTMLInputElement>>('targetInput');
  private readonly applyButton = viewChild<ElementRef<HTMLButtonElement>>('applyButton');
  private readonly cancelled = new Subject<void>();
  private version = 0;
  private navigation = 0;
  private pending = false;
  private previewInput: string | null = null;
  private session = { owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
  readonly opened = signal(false);
  readonly search = signal('');
  readonly catalog = signal<Catalog | null>(null);
  readonly source = signal('');
  readonly target = signal('');
  readonly plan = signal<Preview | null>(null);
  readonly targetPage = signal(0);
  readonly previewPaths = computed(() => (this.plan()?.paths ?? []).slice(this.targetPage() * 25, (this.targetPage() + 1) * 25));
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly busy = computed(() => this.loading() || this.saving());
  readonly error = signal(false);
  readonly uncertain = signal(false);
  readonly result = signal<Result | null>(null);

  constructor() {
    effect(() => { this.auth.status(); this.auth.identity(); untracked(() => this.reset()); });
    effect(() => { const input = this.targetInput(); if (input && this.source() && this.current()) untracked(() => input.nativeElement.focus()); });
    effect(() => { const button = this.applyButton(); if (button && this.current()) untracked(() => button.nativeElement.focus()); });
    this.destroyRef.onDestroy(() => this.stop());
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (!('id' in event)) return;
      if (event.id < this.navigation) return;
      if (event instanceof NavigationStart) { this.navigation = event.id; this.pending = true; this.reset(); }
      else if (isNavigationSettled(event)) {
        this.navigation = event.id; this.pending = false;
      }
    });
  }

  private current(): boolean { return !this.destroyRef.destroyed && !this.pending && this.opened()
    && this.session.owner === this.auth.identity() && this.session.status === this.auth.status() && this.session.token === this.auth.token
    && (this.router.url.split('?')[0] === '/' || /^\/album\/\d+$/.test(this.router.url.split('?')[0])); }
  private stop(): void { this.version++; this.cancelled.next(); this.loading.set(false); }
  private reset(): void {
    this.stop(); this.opened.set(false); this.catalog.set(null); this.source.set(''); this.target.set('');
    this.plan.set(null); this.result.set(null); this.error.set(false); this.uncertain.set(false); this.search.set('');
    this.previewInput = null;
    const panel = this.panel()?.nativeElement; if (panel) panel.open = false;
  }
  private context(edition = false) {
    const token = this.auth.token;
    return this.guards.create(this.destroyRef, { track: 'status', requireEdition: edition,
      valid: () => this.current() && this.auth.token === token });
  }

  toggle(open: boolean): void {
    if (!open) { this.reset(); return; }
    this.session = { owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
    this.opened.set(true); void this.load();
  }
  escape(event: Event, panel: HTMLDetailsElement, trigger: HTMLElement): void {
    if (!panel.open) return;
    event.preventDefault(); event.stopPropagation(); this.reset(); trigger.focus();
  }
  async load(after = ''): Promise<void> {
    if (!this.current() || this.saving()) return;
    this.stop(); const version = this.version; const guard = this.context();
    this.loading.set(true); this.error.set(false);
    const query = this.search();
    try {
      const response = await firstValueFrom(this.api.get<Catalog>('/manual_tags/catalog', { search: query, after, limit: 50 }).pipe(takeUntil(this.cancelled)));
      if (guard.current() && version === this.version && query === this.search()) {
        this.catalog.set(response); this.uncertain.set(false); this.plan.set(null);
      }
    } catch { if (guard.current() && version === this.version) this.error.set(true); }
    finally { if (guard.current() && version === this.version) this.loading.set(false); guard.dispose(); }
  }
  filter(tag: string): void { if (this.current() && !this.saving()) void this.store.updateFilter('tag', tag); }
  manage(tag: string): void {
    if (!this.current() || this.busy() || this.uncertain() || !this.auth.isEdition()) return;
    this.source.set(tag); this.target.set(''); this.plan.set(null); this.result.set(null); this.error.set(false);
  }
  async preview(remove: boolean): Promise<void> {
    if (!this.current() || !this.auth.isEdition() || this.busy() || this.uncertain() || !this.source()) return;
    const body = { source: this.source(), target: remove ? null : this.target() };
    const input = JSON.stringify([this.source(), this.target()]);
    if (body.target !== null && !body.target.trim()) return;
    const guard = this.context(true); const version = this.version;
    this.loading.set(true); this.error.set(false); this.plan.set(null);
    try {
      const response = await firstValueFrom(this.api.post<Preview>('/manual_tags/manage/preview', body).pipe(takeUntil(this.cancelled)));
      if (guard.current() && version === this.version && input === JSON.stringify([this.source(), this.target()])) {
        this.previewInput = input; this.plan.set(response); this.targetPage.set(0);
      }
    } catch { if (guard.current() && version === this.version) this.error.set(true); }
    finally { if (guard.current() && version === this.version) this.loading.set(false); guard.dispose(); }
  }
  async apply(): Promise<void> {
    const plan = this.plan();
    if (!this.current() || !this.auth.isEdition() || this.busy() || this.uncertain() || !plan
      || this.previewInput !== JSON.stringify([this.source(), this.target()])) return;
    const guard = this.context(true); const owner = this.auth.identity(); const token = this.auth.token;
    this.saving.set(true); this.error.set(false);
    let refresh = false;
    try {
      const result = await firstValueFrom(this.api.post<Result>('/manual_tags/manage/apply', {
        source: plan.source, target: plan.target, preview_token: plan.preview_token,
      }));
      refresh = true;
      if (guard.current()) {
        this.result.set(result); this.plan.set(null); this.source.set(''); this.searchInput()?.nativeElement.focus();
      }
    } catch (error) {
      const uncertain = !(error instanceof HttpErrorResponse && error.status >= 400 && error.status < 500);
      refresh = uncertain;
      if (guard.current()) { this.error.set(true); this.uncertain.set(uncertain); if (!uncertain) this.plan.set(null); }
    } finally {
      this.saving.set(false);
      try {
        if (refresh && this.auth.identity() === owner && this.auth.token === token) {
          const filters = this.store.filters();
          const membership = !!filters.tag || !!filters.tag_groups || !!filters.search || !!this.store.currentAlbum()?.is_smart;
          await this.store.refreshPaths(membership ? null : plan.paths);
        }
        if (refresh && guard.current() && !this.uncertain()) await this.load();
      } finally { guard.dispose(); }
    }
  }
}
