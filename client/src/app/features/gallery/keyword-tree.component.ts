import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { firstValueFrom, Subject, takeUntil } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';
import { GalleryStore } from './gallery.store';
import { KeywordHierarchyLabels } from './keyword-hierarchy-labels.service';
import { KeywordHierarchyEditorComponent } from './keyword-hierarchy-editor.component';

type Node = components['schemas']['KeywordTreeNode'];
type Tree = components['schemas']['KeywordTreeResponse'];
type Result = components['schemas']['HierarchyChangeResult'];

@Component({
  selector: 'app-keyword-tree', imports: [MatIconModule, TranslatePipe, ContextHelpComponent, KeywordHierarchyEditorComponent],
  changeDetection: ChangeDetectionStrategy.OnPush, host: { class: 'block min-w-0' },
  template: `
    <details #panel data-keyword-tree (toggle)="toggle(panel.open)" (keydown.escape)="escape($event, trigger)">
      <summary #trigger class="min-h-11 cursor-pointer py-2 text-sm font-medium">{{ I18N.keyword_hierarchy.title | translate }}</summary>
      @if (opened()) {
        <label class="block text-xs">{{ I18N.keyword_catalog.search | translate }}
          <input type="search" [value]="search()" (input)="search.set($any($event.target).value); limit.set(50)"
            class="mt-1 h-10 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-lowest)] px-2 text-base" />
        </label>
        @if (loading()) { <p role="status" class="text-xs">{{ I18N.ui.labels.loading | translate }}</p> }
        @if (error()) { <p role="alert" class="text-xs">{{ I18N.keyword_hierarchy.error | translate }}</p> }
        @if (nodes()) {
          <ul class="m-0 list-none p-0">
            @for (row of shownRows(); track row.node.id) {
              <li class="flex min-w-0 items-center gap-1 border-b border-[var(--mat-sys-outline-variant)]">
                @if (row.children && !search().trim()) {
                  <button type="button" data-keyword-expand class="flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded"
                    [attr.aria-expanded]="expanded().has(row.node.id)" [attr.aria-label]="I18N.keyword_hierarchy.expand | translate:{ name: row.path }" (click)="expand(row.node.id)">
                    <mat-icon aria-hidden="true">{{ expanded().has(row.node.id) ? 'expand_more' : 'chevron_right' }}</mat-icon>
                  </button>
                } @else { <span class="w-11 shrink-0" aria-hidden="true"></span> }
                <button type="button" data-keyword-branch class="min-h-11 min-w-0 flex-1 break-words py-2 text-start text-sm"
                  [attr.aria-pressed]="store.filters().keyword_branch === row.node.id"
                  [attr.aria-label]="I18N.keyword_hierarchy.filter | translate:{ name: row.path, count: row.node.branch_count }" (click)="filter(row.node.id)">
                  <bdi>{{ row.path }}</bdi><span class="ms-2 tabular-nums text-[var(--mat-sys-on-surface-variant)]">{{ row.node.branch_count }}</span>
                  @if (store.filters().keyword_branch === row.node.id) { <mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base">check</mat-icon> }
                </button>
                @if (auth.isEdition()) {
                  <button type="button" data-hierarchy-manage class="min-h-11 shrink-0 px-2 text-xs underline"
                    [disabled]="editorView()?.saving() || editorView()?.uncertain()"
                    [attr.aria-label]="I18N.keyword_catalog.manage_named | translate:{ name: row.path }" (click)="manage(row.node, $event)">{{ I18N.keyword_catalog.manage | translate }}</button>
                }
              </li>
            }
          </ul>
          @if (!rows().length) { <p class="text-xs">{{ I18N.keyword_hierarchy.empty | translate }}</p> }
          @if (rows().length > limit()) { <button type="button" class="min-h-11 text-xs underline" (click)="limit.set(limit() + 50)">{{ I18N.keyword_hierarchy.more | translate }}</button> }
        }
        <div class="flex flex-wrap gap-3">
          <button type="button" class="min-h-11 text-xs underline" [disabled]="loading() || editorView()?.saving()" (click)="reload()">{{ I18N.keyword_catalog.reload | translate }}</button>
          @if (auth.isEdition()) { <button type="button" data-hierarchy-add class="min-h-11 text-xs underline" [disabled]="editorView()?.saving() || editorView()?.uncertain()" (click)="manage(null, $event)">{{ I18N.keyword_hierarchy.edit.add_path | translate }}</button> }
        </div>
        @if (editor(); as entry) {
          @for (item of [entry]; track item.key) {
            <app-keyword-hierarchy-editor [node]="item.node" [nodes]="nodes() ?? []" (closed)="closeEditor()" (changed)="onChanged($event)" />
          }
        }
        @if (receipt(); as result) { <p role="status" class="text-xs">{{ I18N.keyword_hierarchy.edit.changed | translate:{ targets: result.target_photos, photos: result.affected_photos, assignments: result.changed_assignments } }}</p> }
        <app-context-help [label]="I18N.keyword_catalog.help" [keys]="[I18N.keyword_hierarchy.help]" />
      }
    </details>
  `,
})
export class KeywordTreeComponent {
  protected readonly I18N = I18N;
  protected readonly store = inject(GalleryStore);
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly labels = inject(KeywordHierarchyLabels);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly panel = viewChild<ElementRef<HTMLDetailsElement>>('panel');
  protected readonly editorView = viewChild(KeywordHierarchyEditorComponent);
  readonly editor = signal<{ key: number; node: Node | null } | null>(null);
  readonly receipt = signal<Result | null>(null);
  private editorKey = 0;
  private editorTrigger: HTMLElement | null = null;
  private readonly cancelled = new Subject<void>();
  private pending = false;
  private navigation = 0;
  private version = 0;
  private session = { owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
  readonly opened = signal(false);
  readonly nodes = signal<Node[] | null>(null);
  readonly search = signal('');
  readonly expanded = signal(new Set<string>());
  readonly limit = signal(50);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly rows = computed(() => {
    const nodes = this.nodes() ?? [];
    const byId = new Map(nodes.map(node => [node.id, node]));
    const parents = new Set(nodes.map(node => node.parent_id));
    const query = this.search().normalize('NFC').toLocaleLowerCase().trim();
    return nodes.filter(node => {
      if (query) return node.segments.join(' › ').normalize('NFC').toLocaleLowerCase().includes(query);
      let parent = node.parent_id;
      const visited = new Set<string>();
      while (parent) {
        if (visited.has(parent) || !this.expanded().has(parent)) return false;
        visited.add(parent); parent = byId.get(parent)?.parent_id ?? null;
      }
      return true;
    }).map(node => ({ node, path: node.segments.join(' › '), children: parents.has(node.id) }));
  });
  readonly shownRows = computed(() => this.rows().slice(0, this.limit()));

  constructor() {
    this.labels.changes.pipe(takeUntilDestroyed()).subscribe(() => {
      if (this.current()) void this.load();
    });
    effect(() => { this.auth.identity(); this.auth.status(); untracked(() => this.reset()); });
    effect(() => {
      const branch = this.store.filters().keyword_branch;
      this.auth.identity(); this.auth.status();
      if (branch) untracked(() => {
        this.session = { owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
        void this.load();
      });
    });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (!('id' in event) || event.id < this.navigation) return;
      if (event instanceof NavigationStart) { this.navigation = event.id; this.pending = true; this.reset(); }
      else if (event instanceof NavigationEnd || event instanceof NavigationError || event instanceof NavigationSkipped || event instanceof NavigationCancel) {
        if (event instanceof NavigationCancel && (event.code === NavigationCancellationCode.Redirect || event.code === NavigationCancellationCode.SupersededByNewNavigation)) return;
        this.navigation = event.id; this.pending = false;
      }
    });
    this.destroyRef.onDestroy(() => { this.stop(); this.cancelled.complete(); });
  }
  private current(): boolean {
    return !this.destroyRef.destroyed && !this.pending && (this.opened() || !!this.store.filters().keyword_branch)
      && this.session.owner === this.auth.identity() && this.session.status === this.auth.status() && this.session.token === this.auth.token
      && (this.router.url.split('?')[0] === '/' || /^\/album\/\d+$/.test(this.router.url.split('?')[0]));
  }
  private stop(): void { this.version++; this.cancelled.next(); this.loading.set(false); }
  private reset(): void {
    this.stop(); this.opened.set(false); this.nodes.set(null); this.search.set(''); this.expanded.set(new Set()); this.limit.set(50); this.error.set(false);
    const panel = this.panel()?.nativeElement; if (panel) panel.open = false;
    this.editor.set(null); this.receipt.set(null);
  }
  toggle(open: boolean): void {
    if (!open) this.reset();
    else {
      this.nodes.set(null);
      this.session = { owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
      this.opened.set(true); void this.load();
    }
  }
  escape(event: Event, trigger: HTMLElement): void {
    if (!this.opened()) return;
    event.preventDefault(); event.stopPropagation(); this.reset(); trigger.focus();
  }
  expand(id: string): void {
    if (!this.current() || !this.opened()) return;
    this.expanded.update(previous => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  filter(id: string): void {
    if (this.current() && this.opened() && this.nodes()?.some(node => node.id === id)) void this.store.updateFilter('keyword_branch', id);
  }
  manage(node: Node | null, event?: Event): void {
    if (!this.current() || !this.opened() || !this.auth.isEdition() || this.editorView()?.saving() || this.editorView()?.uncertain()) return;
    if (node && !this.nodes()?.some(item => item.id === node.id)) return;
    this.editorTrigger = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null;
    this.receipt.set(null); this.editor.set({ key: ++this.editorKey, node });
  }
  closeEditor(): void {
    this.editor.set(null);
    if (this.current() && this.editorTrigger?.isConnected) this.editorTrigger.focus();
  }
  reload(): void {
    if (this.editorView()?.saving()) return;
    this.editor.set(null); void this.load();
  }
  onChanged(result: Result): void {
    if (!this.current()) return;
    this.editor.set(null); this.receipt.set(result);
    this.panel()?.nativeElement.querySelector<HTMLElement>('summary')?.focus();
  }
  async load(): Promise<void> {
    if (!this.current()) return;
    this.stop(); const version = this.version;
    const owner = this.auth.identity(), status = this.auth.status(), token = this.auth.token;
    const current = () => this.current() && version === this.version && owner === this.auth.identity()
      && status === this.auth.status() && token === this.auth.token;
    this.loading.set(true); this.error.set(false);
    try {
      const tree = await firstValueFrom(this.api.get<Tree>('/manual_tags/hierarchy').pipe(takeUntil(this.cancelled)));
      if (current()) { this.nodes.set(tree.nodes); this.labels.remember(tree.nodes); }
    } catch { if (current()) this.error.set(true); }
    finally { if (current()) this.loading.set(false); }
  }
}
