import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, effect, inject, input, output, signal, untracked, viewChild } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom, Subject, takeUntil } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';
import { GalleryStore } from './gallery.store';
import { KeywordHierarchyLabels } from './keyword-hierarchy-labels.service';

type Node = components['schemas']['KeywordTreeNode'];
type Request = components['schemas']['HierarchyChangeRequest'];
type Preview = components['schemas']['HierarchyChangePreview'];
type Result = components['schemas']['HierarchyChangeResult'];
type Action = Request['action'];

@Component({
  selector: 'app-keyword-hierarchy-editor', imports: [TranslatePipe, ContextHelpComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    <section data-hierarchy-editor tabindex="-1" class="mt-3 space-y-2 border-t border-[var(--mat-sys-outline-variant)] pt-3" (keydown.escape)="close($event)">
      <div class="flex items-start justify-between gap-2">
        <h3 #editorHeading tabindex="-1" class="m-0 break-words text-sm font-medium">{{ sourcePath() || (I18N.keyword_hierarchy.edit.add_path | translate) }}</h3>
        <button type="button" class="min-h-11 shrink-0 px-2 text-xs underline" (click)="close()">{{ I18N.dialog.close | translate }}</button>
      </div>
      @if (node()) {
        <label class="block text-xs">{{ I18N.keyword_hierarchy.edit.operation | translate }}
          <select data-hierarchy-action class="mt-1 min-h-11 w-full rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] px-2 text-sm" [value]="action()" [disabled]="saving() || uncertain()" (change)="setAction($any($event.target).value)">
            @for (option of actions; track option.id) { <option [value]="option.id" [selected]="action() === option.id">{{ option.label | translate }}</option> }
          </select>
        </label>
      }
      @if (action() === 'rename') {
        <label class="block text-xs">{{ I18N.keyword_hierarchy.edit.name | translate }}
          <input data-hierarchy-name maxlength="64" class="mt-1 min-h-11 w-full rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] px-2 text-base" [value]="name()" [disabled]="saving() || uncertain()" (input)="name.set($any($event.target).value); invalidate()" />
        </label>
      }
      @if (action() === 'move') {
        <label class="block text-xs">{{ I18N.keyword_hierarchy.edit.parent | translate }}
          <select data-hierarchy-parent class="mt-1 min-h-11 w-full rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] px-2 text-sm" [value]="parent()" [disabled]="saving() || uncertain()" (change)="parent.set($any($event.target).value); invalidate()">
            <option value="" [selected]="!parent()">{{ I18N.keyword_hierarchy.edit.root | translate }}</option>
            @for (option of parents(); track option.id) { <option [value]="option.id" [selected]="parent() === option.id">{{ option.path }}</option> }
          </select>
        </label>
      }
      @if (action() === 'create_assign') {
        <label class="block text-xs">{{ I18N.keyword_hierarchy.edit.levels | translate }}
          <textarea data-hierarchy-levels rows="3" class="mt-1 w-full rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] p-2 text-base" [value]="levels()" [disabled]="saving() || uncertain()" (input)="levels.set($any($event.target).value); invalidate()"></textarea>
        </label>
      }
      @if (usesSelection()) { <p class="m-0 text-xs">{{ I18N.keyword_hierarchy.edit.selection | translate:{ count: store.selectionCount() } }}</p> }
      @if (loading()) { <p role="status" class="text-xs">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (saving()) { <p role="status" class="text-xs">{{ I18N.keyword_hierarchy.edit.applying | translate }}</p> }
      @if (error()) { <p role="alert" class="text-xs">{{ error() | translate }}</p> }
      @if (plan(); as preview) {
        <div data-hierarchy-preview class="space-y-2 rounded border border-[var(--mat-sys-outline-variant)] p-2 text-xs">
          @if (beforePath()) { <p class="m-0 break-words">{{ I18N.keyword_hierarchy.edit.before | translate }}: {{ beforePath() }}</p> }
          @if (afterPath()) { <p class="m-0 break-words">{{ I18N.keyword_hierarchy.edit.after | translate }}: {{ afterPath() }}</p> }
          <p class="m-0">{{ I18N.keyword_hierarchy.edit.summary | translate:{ photos: preview.paths.length, added: preview.new_assignments, updated: preview.updated_assignments, removed: preview.removed_assignments } }}</p>
          @if (preview.definition_change === null) { <p class="m-0">{{ I18N.keyword_hierarchy.edit.spelling | translate }}</p> }
          <details><summary class="min-h-11 cursor-pointer">{{ I18N.keyword_catalog.targets | translate:{ count: preview.paths.length } }}</summary>
            <ul class="m-0 list-none break-all p-0">@for (path of previewPaths(); track path) { <li class="py-1"><bdi>{{ path }}</bdi></li> }</ul>
            <div class="flex justify-between gap-2">
              <button type="button" class="min-h-11 underline" [disabled]="page() === 0" (click)="page.set(page() - 1)">{{ I18N.keyword_catalog.previous | translate }}</button>
              <button type="button" class="min-h-11 underline" [disabled]="(page() + 1) * 25 >= preview.paths.length" (click)="page.set(page() + 1)">{{ I18N.keyword_catalog.next | translate }}</button>
            </div>
          </details>
          <p class="m-0">{{ I18N.keyword_hierarchy.edit.boundary | translate }}</p>
          <button #applyButton data-hierarchy-apply type="button" class="min-h-11 rounded bg-[var(--mat-sys-primary)] px-3 text-sm text-[var(--mat-sys-on-primary)]" [disabled]="loading() || saving() || uncertain()" (click)="apply()">{{ I18N.ui.buttons.apply | translate }}</button>
        </div>
      } @else {
        <button data-hierarchy-preview type="button" class="min-h-11 rounded border border-[var(--mat-sys-outline)] px-3 text-sm" [disabled]="loading() || saving() || uncertain() || !hasChange() || (usesSelection() && !store.selectionCount())" (click)="preview()">{{ I18N.keyword_hierarchy.edit.preview | translate }}</button>
      }
      @if (uncertain()) { <p role="alert" class="text-xs">{{ I18N.keyword_hierarchy.edit.uncertain | translate }}</p> }
      <app-context-help [label]="I18N.keyword_catalog.help" [keys]="[I18N.keyword_hierarchy.edit.help]" />
    </section>
  `,
})
export class KeywordHierarchyEditorComponent {
  protected readonly I18N = I18N;
  protected readonly store = inject(GalleryStore);
  private readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly labels = inject(KeywordHierarchyLabels);
  private readonly destroyRef = inject(DestroyRef);
  private readonly heading = viewChild<ElementRef<HTMLElement>>('editorHeading');
  private readonly applyButton = viewChild<ElementRef<HTMLButtonElement>>('applyButton');
  readonly node = input<Node | null>(null);
  readonly nodes = input<Node[]>([]);
  readonly changed = output<Result>();
  readonly closed = output<void>();
  readonly action = signal<Action>('rename');
  readonly name = signal('');
  readonly parent = signal('');
  readonly levels = signal('');
  readonly plan = signal<Preview | null>(null);
  readonly page = signal(0);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly uncertain = signal(false);
  readonly error = signal('');
  private readonly cancelled = new Subject<void>();
  private version = 0;
  private readonly owner = this.auth.identity();
  private readonly token = this.auth.token;
  private readonly guard = inject(StalenessGuardFactory).create(this.destroyRef, {
    track: 'status', valid: () => this.auth.identity() === this.owner && this.auth.token === this.token,
    onNavigate: () => this.invalidate(),
  });
  private capturedScope: (() => boolean) | null = null;
  private preparedDraft = '';
  readonly actions: { id: Action; label: string }[] = [
    { id: 'assign', label: I18N.keyword_hierarchy.edit.assign }, { id: 'remove', label: I18N.keyword_hierarchy.edit.remove },
    { id: 'rename', label: I18N.keyword_hierarchy.edit.rename }, { id: 'move', label: I18N.keyword_hierarchy.edit.move },
    { id: 'delete_branch', label: I18N.keyword_hierarchy.edit.delete_branch },
  ];
  readonly usesSelection = computed(() => ['assign', 'remove', 'create_assign'].includes(this.action()));
  readonly hasChange = computed(() => this.action() === 'rename' ? this.name().normalize('NFC').trim().replace(/\s+/g, ' ') !== this.node()?.name
    : this.action() === 'move' ? this.parent() !== (this.node()?.parent_id ?? '')
    : this.action() === 'create_assign' ? !!this.levels().trim() : true);
  readonly sourcePath = computed(() => this.node()?.segments.join(' › ') ?? '');
  readonly parents = computed(() => {
    const nodes = this.nodes(), byId = new Map(nodes.map(node => [node.id, node]));
    return nodes.filter(node => {
      let current: Node | undefined = node;
      const visited = new Set<string>();
      while (current) {
        if (current.id === this.node()?.id || visited.has(current.id)) return false;
        visited.add(current.id); current = current.parent_id ? byId.get(current.parent_id) : undefined;
      }
      return true;
    }).map(node => ({ id: node.id, path: node.segments.join(' › ') }));
  });
  readonly beforePath = computed(() => this.plan()?.before_path?.join(' › ') ?? '');
  readonly afterPath = computed(() => this.plan()?.after_path?.join(' › ') ?? '');
  readonly previewPaths = computed(() => this.plan()?.paths.slice(this.page() * 25, (this.page() + 1) * 25) ?? []);

  constructor() {
    effect(() => { const heading = this.heading(); if (heading && this.current()) untracked(() => heading.nativeElement.focus()); });
    effect(() => { const button = this.applyButton(); if (button && this.current()) untracked(() => button.nativeElement.focus()); });
    effect(() => {
      const node = this.node();
      untracked(() => { this.action.set(node ? 'rename' : 'create_assign'); this.name.set(node?.name ?? ''); this.parent.set(node?.parent_id ?? ''); this.invalidate(); });
    });
    effect(() => {
      this.auth.identity(); this.auth.status(); this.auth.isEdition();
      untracked(() => { if (!this.current()) this.invalidate(); });
    });
    effect(() => {
      this.store.filters(); this.store.selectedPaths(); this.store.excludedPaths(); this.store.viewScopeSelected(); this.store.pinnedPaths();
      untracked(() => { if (!this.saving() && this.plan() && this.capturedScope && !this.capturedScope()) { this.invalidate(); this.error.set(I18N.keyword_hierarchy.edit.scope_changed); } });
    });
    this.destroyRef.onDestroy(() => { this.guard.dispose(); this.cancelReads(); this.cancelled.complete(); });
  }
  private current(): boolean {
    return this.guard.current();
  }
  private cancelReads(): void { this.version++; this.cancelled.next(); this.loading.set(false); }
  invalidate(): void { this.cancelReads(); this.plan.set(null); this.preparedDraft = ''; this.capturedScope = null; this.error.set(''); }
  setAction(action: Action): void { if (!this.saving() && !this.uncertain()) { this.action.set(action); this.invalidate(); } }
  close(event?: Event): void { event?.preventDefault(); event?.stopPropagation(); this.closed.emit(); }
  private draft(): string { return JSON.stringify([this.action(), this.node()?.id, this.name(), this.parent(), this.levels()]); }
  private selection() {
    const view = this.store.viewScopeSelected(), selected = this.store.selectedPaths(), excluded = this.store.excludedPaths(), pins = this.store.pinnedPaths();
    const key = this.store.filterKey({ ...this.store.filters(), page: 1 });
    const values = JSON.stringify([[...selected].sort(), [...excluded].sort(), pins]);
    return { view, paths: [...selected], current: () => this.store.viewScopeSelected() === view
      && this.store.selectedPaths() === selected && this.store.excludedPaths() === excluded && this.store.pinnedPaths() === pins
      && this.store.filterKey({ ...this.store.filters(), page: 1 }) === key
      && JSON.stringify([[...selected].sort(), [...excluded].sort(), pins]) === values };
  }
  async preview(): Promise<void> {
    if (!this.current() || this.loading() || this.saving() || this.uncertain() || !this.hasChange()) return;
    this.invalidate(); const version = this.version, draft = this.draft(), selected = this.selection(), usesSelection = this.usesSelection();
    const current = () => this.current() && version === this.version && draft === this.draft() && (!usesSelection || selected.current());
    this.loading.set(true);
    try {
      const paths = usesSelection ? (selected.view ? await this.store.pathsInView() : selected.paths) : null;
      if (!current() || (usesSelection && !paths?.length)) return;
      const action = this.action();
      const body: Request = action === 'create_assign' ? { action, paths, segments: this.levels().split(/\r?\n/) }
        : { action, node_id: this.node()?.id,
            ...(usesSelection ? { paths } : {}), ...(action === 'rename' ? { name: this.name() } : {}),
            ...(action === 'move' ? { parent_id: this.parent() || null } : {}) };
      const plan = await firstValueFrom(this.api.post<Preview>('/manual_tags/hierarchy/preview', body).pipe(takeUntil(this.cancelled)));
      if (current()) { this.preparedDraft = draft; this.capturedScope = usesSelection ? selected.current : () => true; this.plan.set(plan); this.page.set(0); }
    } catch { if (current()) this.error.set(I18N.keyword_hierarchy.edit.error); }
    finally { if (version === this.version) this.loading.set(false); }
  }
  async apply(): Promise<void> {
    const plan = this.plan();
    if (!this.current() || this.loading() || this.saving() || this.uncertain() || !plan) return;
    if (this.preparedDraft !== this.draft() || !this.capturedScope?.() || plan.expires_at * 1000 <= Date.now()) {
      this.invalidate(); this.error.set(I18N.keyword_hierarchy.edit.scope_changed); return;
    }
    this.saving.set(true); this.error.set('');
    let result: Result | null = null, repair = false;
    try {
      result = await firstValueFrom(this.api.post<Result>('/manual_tags/hierarchy/apply', { ...plan.request, preview_token: plan.preview_token }));
      repair = true;
    } catch (error) {
      const uncertain = !(error instanceof HttpErrorResponse && error.status >= 400 && error.status < 500);
      repair = uncertain;
      if (this.current()) { this.error.set(I18N.keyword_hierarchy.edit.error); this.uncertain.set(uncertain); if (!uncertain) this.plan.set(null); }
    } finally {
      try {
        if (repair && this.auth.identity() === this.owner) {
          const membership = !!this.store.filters().keyword_branch || !!this.store.currentAlbum()?.is_smart;
          await this.store.refreshPaths(membership ? null : plan.paths);
        }
      } catch {
        if (this.current()) this.error.set(I18N.keyword_hierarchy.edit.error);
      } finally {
        this.saving.set(false);
        if (result && this.current()) this.changed.emit(result);
        // Accepted writes outlive the editor. Repair visible taxonomy even when
        // Close destroyed its output subscription before the response settled.
        if (repair) this.labels.invalidate(this.owner);
      }
    }
  }
}
