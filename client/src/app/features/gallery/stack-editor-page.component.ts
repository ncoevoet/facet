import { ChangeDetectionStrategy, Component, DestroyRef, HostListener, effect, forwardRef, inject, signal, viewChild } from '@angular/core';
import { Location } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationEnd, NavigationError, NavigationStart, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PageContextService } from '../../core/agent/page-context.service';
import { isImeOrRepeat, isPageShortcutBlocked } from '../../shared/utils/keyboard';
import { GalleryStore } from './gallery.store';
import { StackEditorComponent } from './stack-editor.component';
import { STACK_EDITOR_HOST, StackEditorHost, StackEditorData } from './stack-editor-host';
import { STACK_EDITOR_HISTORY, StackEditorHistory, readStackEditorHistory } from './stack-editor-history';

/** Routed host owns visit/history lifetime, never a fabricated Material dialog. */
@Component({
  selector: 'app-stack-editor-page',
  imports: [StackEditorComponent, MatButtonModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex flex-col h-full min-h-0 min-w-0 overflow-hidden' },
  providers: [{ provide: STACK_EDITOR_HOST, useExisting: forwardRef(() => StackEditorPageComponent) }],
  template: `
    @for (visit of visits(); track visit.id) {
      <app-stack-editor class="flex-1 min-h-0" />
    } @empty {
      <section class="p-4">
        <h1 class="text-xl mb-2">{{ I18N.stacks.create | translate }}</h1>
        <p role="status">{{ I18N.stacks.manual_empty | translate }}</p>
        <button mat-button data-stack-back (click)="back()">{{ I18N.stacks.back_gallery | translate }}</button>
      </section>
    }
  `,
})
export class StackEditorPageComponent implements StackEditorHost {
  protected readonly I18N = i18nKeys();
  private readonly pageContext = inject(PageContextService);
  private readonly store = inject(GalleryStore);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly location = inject(Location);
  private readonly stacks = inject(PhotoStackService);
  private readonly help = inject(PageHelpService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly editor = viewChild(StackEditorComponent);
  readonly presentation = 'page' as const;
  readonly keydown$ = new Subject<KeyboardEvent>();
  readonly closing$ = new Subject<void>();
  readonly visits = signal<{ id: number; data: StackEditorData }[]>([]);
  private source: StackEditorHistory | null = null;
  private selectionClear: { clear: () => void; restore: () => void } = { clear: () => undefined, restore: () => undefined };
  private epoch = 0;
  private owner = this.auth.identity();
  private returnUrl = '/';
  private busy = false;
  private navigating = false;
  private navigationTrigger: 'imperative' | 'popstate' | 'hashchange' = 'imperative';
  get data(): StackEditorData { return this.visits()[0].data; }
  get onUndone(): () => void {
    const epoch = this.epoch;
    const owner = this.owner;
    const session = this.stacks.context();
    const selection = this.selectionClear;
    return () => {
      selection.restore();
      if (!this.destroyRef.destroyed && !this.navigating && epoch === this.epoch
        && owner === this.auth.identity() && this.auth.isEdition() && session()) void this.editor()?.continueEditing();
    };
  }
  constructor() {
    this.restore((this.router.currentNavigation()?.extras.state ?? this.location.getState() as Record<string, unknown>)?.[STACK_EDITOR_HISTORY]);
    this.help.setDescription(this.I18N.stacks.manual_help);
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) {
        this.navigating = true; this.navigationTrigger = event.navigationTrigger ?? 'imperative'; this.clearView();
      } else if (event instanceof NavigationCancel || event instanceof NavigationError || event instanceof NavigationEnd) {
        if (!this.navigating) return;
        this.navigating = false;
        if (this.router.url.split(/[?#]/)[0] !== '/stacks/edit') { this.source = null; return; }
        // A cancelled/failed navigation has a fresh root context. Never revive old Undo.
        const historyState = this.location.getState() as Record<string, unknown>;
        let state: unknown = this.source;
        if (event instanceof NavigationEnd) {
          if (Object.hasOwn(historyState, STACK_EDITOR_HISTORY)) state = historyState[STACK_EDITOR_HISTORY];
          else if (this.navigationTrigger !== 'imperative') state = undefined;
        }
        this.restore(state);
      }
    });
    effect(() => {
      if (this.auth.identity() !== this.owner || !this.auth.isEdition()) this.invalidate();
    });
    this.destroyRef.onDestroy(() => { this.clearView(); this.source = null; this.help.setDescription(null); });
  }
  @HostListener('document:keydown', ['$event'])
  onKeydown(event: KeyboardEvent): void {
    if (this.navigating) return;
    // The one Escape handler for the whole page: the editor only ever sees what this forwards.
    if (event.key === 'Escape' && !event.defaultPrevented && !event.shiftKey && !isImeOrRepeat(event)
      && !isPageShortcutBlocked(event) && !this.pageContext.overlays().length
      && !(event.target instanceof HTMLElement && event.target.closest('[role="slider"], [role="radiogroup"]'))) {
      event.preventDefault(); event.stopPropagation(); this.back(); return;
    }
    this.keydown$.next(event);
  }
  setBusy(busy: boolean): void { this.busy = busy; }
  finish(result: 'saved' | 'skip' | 'close'): void {
    if (result === 'saved') this.selectionClear.clear();
    if (result === 'close') this.back();
  }
  back(): void { if (!this.busy) void this.router.navigateByUrl(this.returnUrl); }
  invalidate(): void {
    this.clearView(); this.source = null; this.returnUrl = '/';
    const state = { ...this.location.getState() as Record<string, unknown> }; delete state[STACK_EDITOR_HISTORY];
    this.location.replaceState(this.location.path(true), '', state);
  }
  private clearView(): void {
    this.epoch++; this.closing$.next(); this.visits.set([]); this.busy = false;
  }
  private restore(value: unknown): void {
    if (this.destroyRef.destroyed || this.auth.identity() !== this.owner || !this.auth.isEdition()) { this.invalidate(); return; }
    const source = readStackEditorHistory(value, this.auth.identity(), this.router);
    if (!source) { this.invalidate(); return; }
    this.selectionClear = this.store.captureSelectionClear(source.paths);
    this.source = source; this.returnUrl = source.returnUrl;
    this.location.replaceState(this.location.path(true), '', { ...this.location.getState() as Record<string, unknown>, [STACK_EDITOR_HISTORY]: source });
    this.visits.set([{ id: ++this.epoch, data: { paths: source.paths, activePath: source.activePath } }]);
  }
}
