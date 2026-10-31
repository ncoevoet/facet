import { ApplicationRef, Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { Location } from '@angular/common';
import { PageHelpService } from '../../core/services/page-help.service';
import { UndoService } from '../../core/services/undo.service';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { PageContextService } from '../../core/agent/page-context.service';
import { GalleryStore } from './gallery.store';
import { StackEditorPageComponent } from './stack-editor-page.component';
import { STACK_EDITOR_HISTORY } from './stack-editor-history';
import { PersonHideService } from '../persons/person-hide.service';

@Component({ template: 'Gallery' })
class GalleryOrigin {}
const paths = ['/private/a.jpg', '/private/b.jpg'];
const preview = { selected_paths: paths, mode: 'combine', paths, cover_path: paths[0], source_stacks: [],
  unstacked_paths: paths, affected_paths: paths, expected_state: 'a'.repeat(64) };
const input = (overrides = {}) => ({ version: 1, identity: 'alice', paths, activePath: paths[1], returnUrl: '/album/17?sort=date#position', ...overrides });

describe('manual stack workspace with Router, HTTP and Material', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let identity: ReturnType<typeof signal<string>>;
  let edition: ReturnType<typeof signal<boolean>>;
  let selection: { clear: ReturnType<typeof vi.fn>; restore: ReturnType<typeof vi.fn> };
  const root = () => harness.routeNativeElement!;
  const button = (selector: string) => root().querySelector<HTMLButtonElement>(selector)!;
  async function render() { harness.detectChanges(); await Promise.resolve(); await Promise.resolve(); TestBed.inject(ApplicationRef).tick(); harness.detectChanges(); }
  beforeEach(async () => {
    identity = signal('alice'); edition = signal(true); selection = { clear: vi.fn(), restore: vi.fn() };
    TestBed.configureTestingModule({ providers: [provideHttpClient(withXhr()), provideHttpClientTesting(),
      provideRouter([{ path: 'stacks/edit', component: StackEditorPageComponent }, { path: '', component: GalleryOrigin },
        { path: 'album/:albumId', component: GalleryOrigin }, { path: 'blocked', component: GalleryOrigin, canActivate: [() => false] },
        { path: 'broken', loadComponent: () => Promise.reject(new Error('load failed')) }]),
      { provide: AuthService, useValue: { identity, isEdition: edition } },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
      { provide: GalleryStore, useValue: { captureSelectionClear: vi.fn(() => selection), pinnedPaths: signal(null), refreshPaths: vi.fn(async () => undefined), restoreSelection: vi.fn() } },
    ] });
    http = TestBed.inject(HttpTestingController); harness = await RouterTestingHarness.create();
  });
  afterEach(() => { http.verify({ ignoreCancelled: true }); TestBed.resetTestingModule(); history.replaceState({}, ''); });
  async function open(state: unknown = input()) {
    await TestBed.inject(Router).navigateByUrl('/stacks/edit', { state: { [STACK_EDITOR_HISTORY]: state } });
    harness.detectChanges();
  }
  async function ready() { await open(); http.expectOne('/api/stacks/regroup/preview').flush(preview); await render(); }
  it('uses the rendered Reject control and actual snackbar Undo without saving grouping', async () => {
    await ready(); button('[data-stack-reject]').click();
    const read = http.expectOne(request => request.url === '/api/photo'); expect(read.request.params.get('path')).toBe(paths[1]);
    read.flush({ path: paths[1], is_kept: true, star_rating: 4 }); await render();
    http.expectOne('/api/photos/batch_review').flush({ success: true, count: 1, undo_entry_id: 91 }); await render();
    expect(root().querySelector(`[data-stack-focus="${paths[1]}"]`)).toBeNull();
    expect(button('[data-stack-save]').disabled).toBe(true);
    expect(TestBed.inject(UserActivityJournal).since().items).toEqual([expect.objectContaining({ kind: 'reject', paths: [paths[1]], value: true })]);
    const undo = document.querySelector<HTMLButtonElement>('mat-snack-bar-container button')!; expect(undo).not.toBeNull(); undo.click();
    http.expectOne('/api/organization_history/91/revert').flush({ changed: 1 }); await render();
    expect(root().querySelector(`[data-stack-focus="${paths[1]}"]`)).not.toBeNull();
    expect(button('[data-stack-save]').disabled).toBe(false); http.expectNone('/api/stacks/regroup/apply');
  });
  it('keeps R out of native controls, overlays, repeated and modified events, then rejects the focused frame', async () => {
    await ready();
    for (const init of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: true }, { isComposing: true }, { keyCode: 229 }, { repeat: true }]) {
      button('[data-stack-reject]').dispatchEvent(new KeyboardEvent('keydown', { key: 'r', bubbles: true, ...init }));
    }
    for (const kind of ['dialog', 'bottom_sheet', 'slideshow'] as const) {
      const clear = TestBed.inject(PageContextService).registerOverlay(kind);
      button('[data-stack-reject]').dispatchEvent(new KeyboardEvent('keydown', { key: 'r', bubbles: true })); clear();
    }
    const control = document.createElement('input'); root().append(control);
    control.dispatchEvent(new KeyboardEvent('keydown', { key: 'r', bubbles: true })); control.remove();
    http.expectNone(request => request.url === '/api/photo');
    button('[data-stack-reject]').dispatchEvent(new KeyboardEvent('keydown', { key: 'r', bubbles: true }));
    http.expectOne(request => request.url === '/api/photo').flush({ path: paths[1], is_rejected: true }); await render();
    http.expectNone('/api/photos/batch_review'); expect(root().querySelector(`[data-stack-focus="${paths[1]}"]`)).toBeNull();
  });
  it.each(['read', 'write'])('does not revive a departed workspace after Reject %s completes through the real Router', async phase => {
    await ready(); button('[data-stack-reject]').click();
    let pending = http.expectOne(request => request.url === '/api/photo');
    if (phase === 'write') {
      pending.flush({ path: paths[1], is_kept: true }); await render();
      pending = http.expectOne('/api/photos/batch_review');
    }
    await TestBed.inject(Router).navigateByUrl('/album/17'); await render();
    pending.flush(phase === 'write' ? { count: 1, undo_entry_id: 92 } : { path: paths[1] }); await render();
    expect(TestBed.inject(Router).url).toBe('/album/17');
    expect(root().querySelector('[data-stack-reject], [data-stack-focus]')).toBeNull();
    expect(TestBed.inject(UserActivityJournal).since().items.filter(entry => entry.kind === 'reject')).toEqual([]);
    expect(TestBed.inject(GalleryStore).refreshPaths).not.toHaveBeenCalled();
    expect(document.querySelector('mat-snack-bar-container')).toBeNull();
    http.expectNone('/api/photos/batch_review');
  });
  it('returns from the empty workspace on Escape', async () => {
    await open(null); await render();
    button('[data-stack-back]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await TestBed.inject(ApplicationRef).whenStable();
    expect(TestBed.inject(Router).url).toBe('/');
  });
  it.each(['empty', 'loaded'])('keeps Escape out of typing, overlays and controls in the %s workspace', async workspace => {
    if (workspace === 'empty') { await open(null); await render(); } else await ready();
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl');
    const target = button('[data-stack-back]');
    const menu = document.createElement('div'); menu.setAttribute('role', 'menu'); root().append(menu);
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); menu.remove();
    const slider = document.createElement('div'); slider.setAttribute('role', 'slider'); root().append(slider);
    slider.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); slider.remove();
    for (const kind of ['dialog', 'bottom_sheet', 'slideshow'] as const) {
      const clear = TestBed.inject(PageContextService).registerOverlay(kind);
      target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); clear();
    }
    for (const init of [{ isComposing: true }, { keyCode: 229 }, { repeat: true }, { shiftKey: true }, { ctrlKey: true }]) {
      target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, ...init }));
    }
    expect(navigate).not.toHaveBeenCalled();
    target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(navigate).toHaveBeenCalledTimes(1);
  });
  it('clears the committed selection only on save and restores it on Undo', async () => {
    await ready();
    const page = harness.routeDebugElement!.componentInstance as StackEditorPageComponent;
    page.finish('skip'); expect(selection.clear).not.toHaveBeenCalled();
    page.finish('saved'); expect(selection.clear).toHaveBeenCalledTimes(1);
    page.onUndone(); expect(selection.restore).toHaveBeenCalledTimes(1);
    await render(); http.match('/api/stacks/regroup/preview').forEach(request => request.flush(preview));
  });
  it('keeps Escape out of typing, overlays and in-flight saves', async () => {
    await ready();
    const target = button('[data-stack-back]');
    const menu = document.createElement('div'); menu.setAttribute('role', 'menu'); root().append(menu);
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); menu.remove();
    const input = document.createElement('input'); root().append(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); input.remove();
    for (const kind of ['dialog', 'bottom_sheet', 'slideshow'] as const) {
      const clear = TestBed.inject(PageContextService).registerOverlay(kind);
      target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); clear();
    }
    for (const init of [{ isComposing: true }, { keyCode: 229 }, { repeat: true }, { shiftKey: true }]) {
      target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, ...init }));
    }
    expect(TestBed.inject(Router).url).toBe('/stacks/edit');
    button('[data-stack-save]').click();
    const write = http.expectOne('/api/stacks/regroup/apply');
    target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(TestBed.inject(Router).url).toBe('/stacks/edit');
    write.flush({}, { status: 409, statusText: 'Conflict' }); await render();
    target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await TestBed.inject(ApplicationRef).whenStable();
    expect(TestBed.inject(Router).url).toBe('/album/17?sort=date#position');
  });
  it('returns to the originating album on Escape without saving', async () => {
    await ready();
    button('[data-stack-back]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await TestBed.inject(ApplicationRef).whenStable(); await render();
    expect(TestBed.inject(Router).url).toBe('/album/17?sort=date#position');
    http.expectNone('/api/stacks/regroup/apply');
  });
  it('authorizes history before exposing private names and uses a real page zoom workspace', async () => {
    await open(); expect(root().textContent).not.toContain('a.jpg'); expect(root().querySelector('img')).toBeNull();
    http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
    expect(root().querySelector('app-synced-zoom')).not.toBeNull();
    expect(root().querySelector('mat-dialog-content, mat-dialog-actions, [mat-dialog-title]')).toBeNull();
    expect(TestBed.inject(MatDialog).openDialogs).toHaveLength(0);
    expect(root().querySelector('[data-stack-focus="/private/b.jpg"]')?.getAttribute('aria-pressed')).toBe('true');
    button('[data-stack-back]').click(); await TestBed.inject(ApplicationRef).whenStable(); await render();
    expect(TestBed.inject(Router).url).toBe('/album/17?sort=date#position');
  });
  it.each([
    ['absent', undefined],
    ['foreign identity', input({ identity: 'bob' })],
    ['duplicate paths', input({ paths: [paths[0], paths[0]] })],
    ['an active path outside the set', input({ activePath: '/secret.jpg' })],
    ['an unknown version', input({ version: 2 })],
  ])('refuses %s history without a preview or filename', async (_name, state) => {
    await open(state === undefined ? null : state); await render();
    http.expectNone('/api/stacks/regroup/preview'); expect(root().textContent).not.toContain('a.jpg');
    expect(root().querySelector('[data-stack-back]')).not.toBeNull();
  });
  describe('browser history traversal', () => {
    // The testing platform swaps in a mock history, so push entries through Location and step back onto the wanted one.
    async function traverseBackOnto(state: unknown) {
      const location = TestBed.inject(Location);
      location.go('/stacks/edit?from=history', '', state);
      location.go('/stacks/edit?away=1', '', {});
      // Tests never bootstrap, so nothing has subscribed the router to popstate yet.
      TestBed.inject(Router).setUpLocationChangeListener();
      location.back();
      await new Promise(resolve => setTimeout(resolve));
      await render();
    }
    it('refuses a popstate onto a stateless entry: no preview, no filename, no image, Back offered', async () => {
      await ready();
      await traverseBackOnto({});
      http.expectNone('/api/stacks/regroup/preview');
      expect(TestBed.inject(Router).url).toBe('/stacks/edit?from=history');
      expect(root().textContent).not.toContain('a.jpg'); expect(root().querySelector('img')).toBeNull();
      expect(root().querySelector('[data-stack-back]')).not.toBeNull();
    });
    it('requests a fresh preview for a popstate onto an entry that carries state', async () => {
      await ready();
      await traverseBackOnto({ [STACK_EDITOR_HISTORY]: input() });
      http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
      expect(button('[data-stack-save]').disabled).toBe(false);
    });
  });
  it('does not navigate from Back while a mutation is in flight', async () => {
    await ready(); button('[data-stack-save]').click(); const apply = http.expectOne('/api/stacks/regroup/apply');
    TestBed.inject(Router).navigateByUrl = vi.fn(async () => true);
    harness.routeDebugElement!.componentInstance.back();
    expect(TestBed.inject(Router).navigateByUrl).not.toHaveBeenCalled();
    apply.flush({ changed: false }); await render();
  });
  it('refuses a server visibility failure before rendering images', async () => {
    await open(); http.expectOne('/api/stacks/regroup/preview').flush({}, { status: 403, statusText: 'Forbidden' }); await render();
    expect(root().querySelector('img')).toBeNull(); expect(root().textContent).not.toContain('private');
  });
  it('keeps Save on the same URL, journals once, and actual snackbar Undo fetches a fresh editable preview', async () => {
    await ready(); button('[data-stack-save]').click();
    http.expectOne('/api/stacks/regroup/apply').flush({ changed: true, affected_paths: paths, undo: { entry_id: 81 } }); await render();
    expect(TestBed.inject(Router).url).toBe('/stacks/edit'); expect(root().querySelector('[data-stack-save]')).toBeNull();
    expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(1);
    const undo = document.querySelector<HTMLButtonElement>('mat-snack-bar-container button')!; expect(undo).not.toBeNull(); undo.click();
    http.expectOne('/api/organization_history/81/revert').flush({ changed: 2 }); await render();
    http.expectOne('/api/stacks/regroup/preview').flush({ ...preview, expected_state: 'b'.repeat(64) }); await render();
    expect(button('[data-stack-save]').disabled).toBe(false);
    expect(TestBed.inject(UserActivityJournal).since().items.at(-1)?.value).toBe('undo');
  });
  it('shares the Undo slot with People Ignore without replaying a superseded stack or person action', async () => {
    const snack = vi.spyOn(TestBed.inject(MatSnackBar), 'open');
    const personRestored = vi.fn(async () => undefined);
    const undoShown = async (label: string) => {
      await vi.waitFor(() => {
        const containers = document.querySelectorAll('mat-snack-bar-container');
        expect(containers).toHaveLength(1);
        expect(containers[0].textContent).toContain(label);
      });
      document.querySelector<HTMLButtonElement>('mat-snack-bar-container button')!.click();
    };
    await ready(); button('[data-stack-save]').click();
    http.expectOne('/api/stacks/regroup/apply').flush({ changed: true, affected_paths: paths, undo: { entry_id: 81 } }); await render();
    expect(snack).toHaveBeenLastCalledWith('stacks.saved', 'undo.action', { duration: 7000 });

    const hiding = TestBed.inject(PersonHideService).setHidden(7, true, personRestored);
    http.expectOne('/api/persons/7/hide').flush({}); await hiding; await render();
    expect(snack).toHaveBeenLastCalledWith('persons.hidden_done', 'undo.action', { duration: 10_000 });
    await undoShown('persons.hidden_done');
    http.expectOne('/api/persons/7/unhide').flush({}); await render();
    expect(personRestored).toHaveBeenCalledTimes(1);
    http.expectNone('/api/organization_history/81/revert');

    const hidingAgain = TestBed.inject(PersonHideService).setHidden(7, true, personRestored);
    http.expectOne('/api/persons/7/hide').flush({}); await hidingAgain; await render();
    button('[data-stack-continue]').click();
    http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
    button('[data-stack-save]').click();
    http.expectOne('/api/stacks/regroup/apply').flush({ changed: true, affected_paths: paths, undo: { entry_id: 82 } }); await render();
    expect(snack).toHaveBeenLastCalledWith('stacks.saved', 'undo.action', { duration: 7000 });
    await undoShown('stacks.saved');
    http.expectOne('/api/organization_history/82/revert').flush({ changed: 2 }); await render();
    http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
    http.expectNone('/api/persons/7/unhide');
    expect(personRestored).toHaveBeenCalledTimes(1);
    expect(button('[data-stack-save]').disabled).toBe(false);
  });
  it('requires a fresh preview after no-op Continue and invents no journal or Undo', async () => {
    await ready(); button('[data-stack-save]').click(); http.expectOne('/api/stacks/regroup/apply').flush({ changed: false, affected_paths: [] }); await render();
    expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(0);
    expect(document.querySelector('mat-snack-bar-container')).toBeNull();
    button('[data-stack-continue]').click(); http.expectOne('/api/stacks/regroup/preview').flush({ ...preview, expected_state: 'c'.repeat(64) }); await render();
    button('[data-stack-save]').click(); const apply = http.expectOne('/api/stacks/regroup/apply'); expect(apply.request.body.expected_state).toBe('c'.repeat(64)); apply.flush({ changed: false }); await render();
  });
  it('blocks native controls, modifiers, repeat, composing and every overlay from page shortcuts', async () => {
    await ready();
    button('[data-stack-focus="/private/a.jpg"]').click(); await render();
    const expectFirstFocused = () => {
      expect(button('[data-stack-focus="/private/a.jpg"]').getAttribute('aria-pressed')).toBe('true');
      expect(button('[data-stack-focus="/private/b.jpg"]').getAttribute('aria-pressed')).toBe('false');
    };
    const blocked = [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: true },
      { isComposing: true }, { keyCode: 229 }, { repeat: true }];
    for (const init of blocked) {
      button('[data-stack-focus="/private/a.jpg"]').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, ...init }));
      await render(); expectFirstFocused();
    }
    for (const kind of ['dialog', 'bottom_sheet', 'slideshow'] as const) {
      const clear = TestBed.inject(PageContextService).registerOverlay(kind);
      button('[data-stack-focus="/private/a.jpg"]').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      await render(); expectFirstFocused(); clear();
    }
    for (const key of ['Enter', ' ']) {
      button('[data-stack-back]').dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
      await render(); expectFirstFocused();
    }
    http.expectNone('/api/stacks/regroup/apply');
    button('[data-stack-focus="/private/a.jpg"]').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    await render();
    expect(button('[data-stack-focus="/private/b.jpg"]').getAttribute('aria-pressed')).toBe('true');
    expect(button('[data-stack-focus="/private/a.jpg"]').getAttribute('aria-pressed')).toBe('false');
  });
  it('recovers a cancelled navigation through fresh server authorization', async () => {
    await ready(); await TestBed.inject(Router).navigateByUrl('/blocked'); harness.detectChanges();
    expect(root().querySelector('img')).toBeNull(); http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
    expect(button('[data-stack-save]').disabled).toBe(false);
  });
  it('clears private state on account loss and ignores a late server completion', async () => {
    await open(); const request = http.expectOne('/api/stacks/regroup/preview'); identity.set('bob');
    request.flush(preview); await render();
    expect(root().querySelector('img')).toBeNull(); expect(root().textContent).not.toContain('a.jpg');
    expect((TestBed.inject(Location).getState() as Record<string, unknown>)[STACK_EDITOR_HISTORY]).toBeUndefined();
  });
  it('reconstructs the same-account page from persisted history using a fresh preview', async () => {
    await ready();
    const stored = TestBed.inject(Location).getState() as Record<string, unknown>;
    expect(Object.keys(stored[STACK_EDITOR_HISTORY] as object).sort()).toEqual(['activePath', 'identity', 'paths', 'returnUrl', 'version']);
    harness.fixture.destroy();
    const reloaded = TestBed.createComponent(StackEditorPageComponent); reloaded.detectChanges();
    expect(reloaded.nativeElement.querySelector('img')).toBeNull();
    http.expectOne('/api/stacks/regroup/preview').flush({}, { status: 404, statusText: 'Unavailable' });
    await Promise.resolve(); reloaded.detectChanges();
    expect(reloaded.nativeElement.textContent).not.toContain('a.jpg');
    reloaded.destroy();
  });
  it('revalidates the same component on a query navigation and retains input-only history', async () => {
    await ready(); await TestBed.inject(Router).navigateByUrl('/stacks/edit?review=1'); harness.detectChanges();
    expect(root().querySelector('img')).toBeNull();
    http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
    expect(button('[data-stack-save]').disabled).toBe(false);
    expect((TestBed.inject(Location).getState() as Record<string, unknown>)[STACK_EDITOR_HISTORY]).toEqual(input());
  });
  it('recovers failed lazy navigation through a fresh preview without redirecting to Back', async () => {
    await ready(); await expect(TestBed.inject(Router).navigateByUrl('/broken')).rejects.toThrow('load failed'); harness.detectChanges();
    expect(TestBed.inject(Router).url).toBe('/stacks/edit');
    http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
    expect(button('[data-stack-save]').disabled).toBe(false);
  });
  it.each(['identity', 'edition'])('refuses a mutation completing after %s loss before reactive cleanup', async loss => {
    await ready(); button('[data-stack-save]').click(); const apply = http.expectOne('/api/stacks/regroup/apply');
    if (loss === 'identity') identity.set('bob'); else edition.set(false);
    apply.flush({ changed: true, affected_paths: paths, undo: { entry_id: 81 } }); await render();
    expect(root().querySelector('img')).toBeNull(); expect(root().textContent).not.toContain('a.jpg');
    expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(0);
    expect(document.querySelector('mat-snack-bar-container')).toBeNull();
    expect((TestBed.inject(Location).getState() as Record<string, unknown>)[STACK_EDITOR_HISTORY]).toBeUndefined();
  });
  it('never revives a saved Undo after cancelled navigation starts a new visit', async () => {
    const register = vi.spyOn(TestBed.inject(UndoService), 'register');
    await ready(); button('[data-stack-save]').click(); http.expectOne('/api/stacks/regroup/apply').flush({ changed: true, affected_paths: paths, undo: { entry_id: 81 } }); await render();
    const oldUndo = register.mock.calls[0][0].undo;
    await TestBed.inject(Router).navigateByUrl('/blocked'); harness.detectChanges();
    http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
    await expect(oldUndo()).rejects.toThrow('Stack session expired'); http.expectNone('/api/organization_history/81/revert');
  });
  it('resets My Taste help and publishes the manual editor description', async () => {
    TestBed.inject(PageHelpService).note.set({ key: 'old-note' }); await ready();
    expect(TestBed.inject(PageHelpService).descriptionKey()).toBe('stacks.manual_help');
    expect(TestBed.inject(PageHelpService).note()).toBeNull();
  });

  it('loads only the focused original on explicit zoom and resets fit when changing members', async () => {
    await ready();
    const image = () => root().querySelector<HTMLImageElement>('app-synced-zoom img')!;
    expect(image().getAttribute('src')).toContain('/thumbnail?');
    button('[data-stack-zoom]').click(); await render();
    expect(image().getAttribute('src')).toContain('/image?path=%2Fprivate%2Fb.jpg');
    button('[data-stack-focus="/private/a.jpg"]').click(); await render();
    expect(image().getAttribute('src')).toContain('/thumbnail?path=%2Fprivate%2Fa.jpg');
    expect(button('[data-stack-zoom]').getAttribute('aria-pressed')).toBe('false');
  });

});
