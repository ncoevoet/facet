import { ApplicationRef, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpRequest, provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router, NavigationEnd } from '@angular/router';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatDialog } from '@angular/material/dialog';
import { MatTooltip } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, filter, firstValueFrom, take, of } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService } from '../../core/services/scan.service';
import { AssistantChangesService, AssistantChangeBatch } from '../../core/agent/assistant-changes.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { GalleryComponent } from './gallery.component';
import { GalleryStore } from './gallery.store';
import { App } from '../../app';
import { KeyboardMappingService, DEFAULT_KEYMAP } from '../../core/services/keyboard-mapping.service';
import { StackDialogComponent } from './stack-dialog.component';
import { RouterTestingHarness } from '@angular/router/testing';
import { StackEditorPageComponent } from './stack-editor-page.component';
import { STACK_EDITOR_HISTORY } from './stack-editor-history';
import { GalleryReuseStrategy } from '../../core/gallery-reuse.strategy';
import { RouteReuseStrategy } from '@angular/router';
import { Location } from '@angular/common';
import { ThemeService } from '../../core/services/theme.service';

const counts = { total: 2, undecided: 2, kept: 0, rejected: 0 };
const rows = [makePhoto({ path: '/trip/a.jpg' }), makePhoto({ path: '/trip/b.jpg' })];
const page = { photos: rows, total: 2, page: 1, per_page: 64, total_pages: 1, has_more: false };
const config = {
  pagination: { default_per_page: 64 },
  defaults: { sort: 'star_rating', sort_direction: 'ASC', gallery_mode: 'grid', hide_details: true },
  display: { card_width_px: 168, image_width_px: 640, tags_per_photo: 5 },
  features: { show_rating_controls: true }, cull: { trash_available: true },
  quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
  sort_options_grouped: [], search_threshold_default: 0.15,
};

describe('stack representative repairs through rendered gallery and HTTP', () => {
  let fixture: ComponentFixture<GalleryComponent>;
  let store: GalleryStore;
  let http: HttpTestingController;
  let auth: AuthService;
  let requests: Subject<HttpRequest<unknown>>;
  let assistantBatches: Subject<AssistantChangeBatch>;
  const requested = (url: string) => firstValueFrom(requests.pipe(filter(request => request.url === url), take(1)));
  const progressRequests = () => http.match(request => request.url === '/api/photos/review_progress');
  const flushSideData = () => {
    for (const request of http.match(request => request.url.startsWith('/api/filter_options/') || request.url === '/api/type_counts')) {
      request.flush({ types: [], cameras: [], lenses: [], tags: [], persons: [], patterns: [], temps: [], hue_buckets: [], ranges: {} });
    }
    for (const request of http.match('/api/photos/keeper_hints')) request.flush({});
  };

  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear();
    requests = new Subject();
    assistantBatches = new Subject();
    TestBed.configureTestingModule({ providers: [
      { provide: RouteReuseStrategy, useClass: GalleryReuseStrategy },
      provideHttpClient(withXhr(), withInterceptors([(request, next) => { requests.next(request); return next(request); }])), provideHttpClientTesting(), provideRouter([]), provideNativeDateAdapter(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {}, paramMap: convertToParamMap({}) } } },
      { provide: ScanService, useValue: { canLaunch: signal(false) } },
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', languages: signal([]), t: (key: string, params?: unknown) => `${key} ${JSON.stringify(params ?? {})}` } },
      { provide: AssistantChangesService, useValue: { batch$: assistantBatches.asObservable(), active: signal(false), activity: signal([]) } },
      { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
      { provide: MatSnackBar, useValue: { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) } },
    ] });
    auth = TestBed.inject(AuthService);
    auth.status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    http = TestBed.inject(HttpTestingController);
    store = TestBed.inject(GalleryStore);
    fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    const photosStarted = requested('/api/photos');
    http.expectOne('/api/config').flush(config);
    await photosStarted;
    const sideDataStarted = requested('/api/filter_options/metric_ranges');
    http.expectOne(request => request.url === '/api/photos').flush(page);
    progressRequests().forEach(request => request.flush(counts));
    await sideDataStarted;
    flushSideData();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(store.photos()).toHaveLength(2);
  });

  afterEach(() => {
    fixture.destroy();
    TestBed.resetTestingModule();
    http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });


  it('retains the real routed gallery and cards on unchanged editor Back without listing reads', async () => {
    fixture.destroy();
    const router = TestBed.inject(Router);
    router.resetConfig([{ path: '', component: GalleryComponent }, { path: 'stacks/edit', component: StackEditorPageComponent }]);
    const routed = await RouterTestingHarness.create('/');
    flushSideData(); await routed.fixture.whenStable(); routed.detectChanges();
    store.hasMore.set(true);
    const paging = store.nextPage();
    const extra = [makePhoto({ path: '/trip/c.jpg' }), makePhoto({ path: '/trip/d.jpg' })];
    http.expectOne(request => request.url === '/api/photos').flush({ ...page, page: 2, photos: extra, total: 4 });
    await paging; flushSideData(); await routed.fixture.whenStable(); routed.detectChanges();
    const gallery = routed.routeDebugElement!.componentInstance;
    const node = routed.routeNativeElement!;
    const cards = [...node.querySelectorAll('app-photo-card')];
    expect(cards).toHaveLength(4);
    const scroll = node.querySelector<HTMLElement>('mat-sidenav-content')!;
    scroll.scrollTop = 180;
    const scrollTo = vi.fn(); Object.defineProperty(scroll, 'scrollTo', { value: scrollTo, configurable: true });
    const sort = store.filters().sort;
    store.restoreSelection(rows.map(photo => photo.path)); routed.detectChanges();
    node.querySelector<HTMLButtonElement>('[data-create-stack]')!.click();
    await vi.waitFor(() => expect(router.url).toBe('/stacks/edit')); routed.detectChanges();
    http.expectOne('/api/stacks/regroup/preview').flush({ selected_paths: rows.map(photo => photo.path), mode: 'combine', paths: rows.map(photo => photo.path), cover_path: rows[0].path, source_stacks: [], unstacked_paths: rows.map(photo => photo.path), affected_paths: rows.map(photo => photo.path), expected_state: 'a'.repeat(64) });
    await routed.fixture.whenStable(); routed.detectChanges();
    routed.routeNativeElement!.querySelector<HTMLButtonElement>('[data-stack-back]')!.click();
    await vi.waitFor(() => expect(router.url).toBe('/')); flushSideData();
    await routed.fixture.whenStable(); routed.detectChanges();
    expect(routed.routeDebugElement!.componentInstance).toBe(gallery);
    expect(routed.routeNativeElement).toBe(node);
    expect([...node.querySelectorAll('app-photo-card')]).toEqual(cards);
    expect(store.photos().map(photo => photo.path)).toEqual([...rows, ...extra].map(photo => photo.path));
    expect(store.filters().page).toBe(2); expect(store.filters().sort).toBe(sort);
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 180 }));
    expect(store.selectedPaths().size).toBe(2);
    http.expectNone(request => request.url === '/api/photos');
    http.expectNone('/api/photos/review_progress');
    routed.fixture.destroy();
  });

  describe('Stack shortcut through document/grid and HTTP', () => {
    let routed: RouterTestingHarness;
    beforeEach(async () => {
      TestBed.inject(Router).resetConfig([{ path: 'stacks/edit', component: StackEditorPageComponent }, { path: 'blocked', children: [], canActivate: [() => false] }]);
      routed = await RouterTestingHarness.create();
      document.body.appendChild(fixture.nativeElement);
      galleryToasts = vi.spyOn(fixture.debugElement.injector.get(MatSnackBar), 'open')
        .mockReturnValue({ onAction: () => NEVER, afterDismissed: () => NEVER } as never) as unknown as ReturnType<typeof vi.fn>;
    });
    const key = (init: KeyboardEventInit = {}, target: EventTarget = document) => {
      const event = new KeyboardEvent('keydown', { key: 's', bubbles: true, cancelable: true, ...init });
      target.dispatchEvent(event);
      return event;
    };
    const select = () => { store.toggleSelection(rows[0]); store.toggleSelection(rows[1]); fixture.detectChanges(); };
    const chord = (modifier: 'ctrl' | 'meta' = 'ctrl', init: KeyboardEventInit = {}) =>
      key({ key: 'S', shiftKey: true, ctrlKey: modifier === 'ctrl', metaKey: modifier === 'meta', ...init });
    // The gallery imports MatSnackBarModule, so its toasts go through its own injector, not the root mock.
    const snackTexts = () => galleryToasts.mock.calls.map(call => String(call[0]));
    let galleryToasts: ReturnType<typeof vi.fn>;
    const noEditor = () => {
      expect(document.querySelector('app-stack-dialog')).toBeNull();
      http.expectNone('/api/stacks/regroup/preview');
    };
    const closeEditor = async () => {
      TestBed.inject(MatDialog).closeAll();
      routed.fixture.destroy();
      await fixture.whenStable();
    };
    afterEach(async () => { await closeEditor(); });

    it('quick stacks explicit paths in selection order without navigation and clears success', async () => {
      store.restoreSelection([rows[1].path, rows[0].path]); fixture.detectChanges();
      const event = chord();
      expect(event.defaultPrevented).toBe(true);
      const paths = [rows[1].path, rows[0].path];
      http.expectOne('/api/stacks/regroup/preview').flush({ selected_paths: paths, mode: 'selected', paths, source_stacks: [] });
      await fixture.whenStable();
      const write = http.expectOne('/api/stacks');
      expect(write.request.body).toEqual({ paths, cover_path: paths[0] });
      expect([...store.selectedPaths()]).toEqual(paths);
      write.flush({ undo: { entry_id: 71 } });
      await fixture.whenStable(); flushSideData();
      await vi.waitFor(() => expect(store.selectedPaths().size).toBe(0));
      expect(TestBed.inject(Router).url).toBe('/');
      http.expectNone('/api/stacks/regroup/apply');
    });

    it('cancels a quick-stack preview on a real cancelled navigation without writing', async () => {
      select();
      chord();
      const preview = http.expectOne('/api/stacks/regroup/preview');
      expect(await TestBed.inject(Router).navigateByUrl('/blocked')).toBe(false);
      expect(preview.cancelled).toBe(true);
      await fixture.whenStable();
      http.expectNone('/api/stacks');
      expect(store.selectedPaths().size).toBe(2);
    });

    it('refuses a deferred quick-stack preview after a new same-content selection', async () => {
      select();
      chord();
      const preview = http.expectOne('/api/stacks/regroup/preview');
      store.restoreSelection(rows.map(photo => photo.path));
      preview.flush({ source_stacks: [] });
      await fixture.whenStable(); await Promise.resolve();
      http.expectNone('/api/stacks');
      expect(store.selectedPaths().size).toBe(2);
    });

    it('opens the editor for an existing stack member without writing', async () => {
      select();
      chord();
      http.expectOne('/api/stacks/regroup/preview').flush({ source_stacks: [{ id: 'existing' }] });
      await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe('/stacks/edit')); routed.detectChanges();
      http.expectOne('/api/stacks/regroup/preview').flush({}, { status: 403, statusText: 'Unavailable' });
      http.expectNone('/api/stacks');
      expect(store.selectedPaths().size).toBe(2);
    });

    it.each(['failure', 'new selection'])('retains selection on quick-stack %s', async outcome => {
      select();
      chord();
      http.expectOne('/api/stacks/regroup/preview').flush({ source_stacks: [] });
      await fixture.whenStable();
      const write = http.expectOne('/api/stacks');
      if (outcome === 'new selection') store.restoreSelection([rows[0].path]);
      write.flush(outcome === 'failure' ? {} : { undo: { entry_id: 72 } }, outcome === 'failure' ? { status: 409, statusText: 'Conflict' } : {});
      await fixture.whenStable(); await Promise.resolve(); await Promise.resolve();
      expect([...store.selectedPaths()]).toEqual(outcome === 'failure' ? rows.map(row => row.path) : [rows[0].path]);
      flushSideData();
    });

    it.each(['ctrl', 'meta'] as const)('quick stacks with %s+Shift+S on every platform', modifier => {
      select();
      expect(chord(modifier).defaultPrevented).toBe(true);
      http.expectOne('/api/stacks/regroup/preview');
    });

    it.each([
      ['Ctrl and Meta together', { ctrlKey: true, metaKey: true }],
      ['Alt', { altKey: true }],
      ['an auto-repeat', { repeat: true }],
      ['an IME composition', { isComposing: true }],
    ])('ignores the quick-stack chord with %s', (_name, init) => {
      select();
      expect(chord('ctrl', init).defaultPrevented).toBe(false);
      http.expectNone('/api/stacks/regroup/preview');
    });

    it('ignores the quick-stack chord while a dialog is open', () => {
      select();
      const dialog = document.body.appendChild(document.createElement('mat-dialog-container'));
      try {
        expect(chord().defaultPrevented).toBe(false);
        http.expectNone('/api/stacks/regroup/preview');
      } finally { dialog.remove(); }
    });

    it('reports a create conflict as an existing stack member', async () => {
      select(); chord();
      http.expectOne('/api/stacks/regroup/preview').flush({ source_stacks: [] });
      await fixture.whenStable();
      http.expectOne('/api/stacks').flush({}, { status: 409, statusText: 'Conflict' });
      await vi.waitFor(() => expect(snackTexts()).toContain('stacks.stack_failed {}'));
    });

    it('reports a failed preview as a generic failure, not a stack conflict', async () => {
      select(); chord();
      http.expectOne('/api/stacks/regroup/preview').flush({}, { status: 500, statusText: 'Server Error' });
      await vi.waitFor(() => expect(snackTexts()).toContain('errors.action_failed {}'));
      expect(snackTexts()).not.toContain('stacks.stack_failed {}');
      http.expectNone('/api/stacks');
    });

    it('leaves a rate-limited preview to the interceptor toast', async () => {
      select(); chord();
      http.expectOne('/api/stacks/regroup/preview').flush({}, { status: 429, statusText: 'Too Many Requests' });
      await fixture.whenStable(); await Promise.resolve();
      expect(snackTexts()).toEqual([]);
      http.expectNone('/api/stacks');
    });

    it('stays silent when a navigation cancels the preview', async () => {
      select(); chord();
      http.expectOne('/api/stacks/regroup/preview');
      expect(await TestBed.inject(Router).navigateByUrl('/blocked')).toBe(false);
      await fixture.whenStable(); await Promise.resolve();
      expect(snackTexts()).toEqual([]);
    });

    it('restores the cleared selection in its order when the quick stack is undone', async () => {
      const action = new Subject<void>();
      (TestBed.inject(MatSnackBar).open as unknown as ReturnType<typeof vi.fn>)
        .mockImplementation(() => ({ onAction: () => action, afterDismissed: () => NEVER }));
      const paths = [rows[1].path, rows[0].path];
      store.restoreSelection(paths); fixture.detectChanges();
      chord();
      http.expectOne('/api/stacks/regroup/preview').flush({ source_stacks: [] });
      await fixture.whenStable();
      http.expectOne('/api/stacks').flush({ undo: { entry_id: 73 } });
      await vi.waitFor(() => expect(store.selectedPaths().size).toBe(0));
      flushSideData();
      action.next();
      http.expectOne('/api/organization_history/73/revert').flush({});
      await fixture.whenStable(); await Promise.resolve();
      // Undo refreshes the listing before its onUndone runs.
      await vi.waitFor(() => {
        http.match(request => request.url === '/api/photos').forEach(request => request.flush(page));
        progressRequests().filter(request => !request.cancelled).forEach(request => request.flush(counts));
        flushSideData();
        expect([...store.selectedPaths()]).toEqual(paths);
      });
      flushSideData();
    });

    it.each(['document', 'grid'])('opens one editor via %s with exactly the explicit paths and never writes on S', async target => {
      select();
      // Stacking does not depend on the rating-controls feature.
      store.config.update(value => value ? { ...value, features: { ...value.features, show_rating_controls: false } } : value);
      const node = target === 'document' ? document : fixture.nativeElement.querySelector('[role="grid"]');
      expect(node).not.toBeNull();
      const event = key({}, node);
      key({}, node); // Two immediate presses cannot start duplicate navigations.
      expect(event.defaultPrevented).toBe(true);
      await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe('/stacks/edit'));
      routed.detectChanges();
      fixture.detectChanges();
      const request = http.expectOne('/api/stacks/regroup/preview');
      expect(request.request.body).toEqual({ selected_paths: rows.map(row => row.path), mode: 'combine' });
      request.flush({ selected_paths: rows.map(row => row.path), mode: 'combine', paths: rows.map(row => row.path),
        cover_path: rows[0].path, source_stacks: [], unstacked_paths: rows.map(row => row.path),
        affected_paths: rows.map(row => row.path), expected_state: 'a'.repeat(64) });
      await fixture.whenStable(); fixture.detectChanges(); routed.detectChanges();
      expect(document.querySelectorAll('app-stack-dialog')).toHaveLength(0);
      expect(routed.routeNativeElement?.querySelector('[data-stack-save]')).not.toBeNull();
      expect((TestBed.inject(Location).getState() as Record<string, unknown>)[STACK_EDITOR_HISTORY]).toEqual({ version: 1, identity: auth.identity(), paths: rows.map(row => row.path), activePath: undefined, returnUrl: '/' });
      http.expectNone('/api/stacks/regroup/apply');
      http.expectNone('/api/stacks');
    });

    it('routes the toolbar maximum of 1000 explicitly selected photos without a dialog', async () => {
      const paths = Array.from({ length: 1000 }, (_, index) => `/selected/${index}.jpg`);
      store.selectedPaths.set(new Set(paths)); fixture.detectChanges();
      fixture.nativeElement.querySelector('[data-create-stack]').click();
      await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe('/stacks/edit')); routed.detectChanges();
      const request = http.expectOne('/api/stacks/regroup/preview'); expect(request.request.body.selected_paths).toEqual(paths);
      expect(TestBed.inject(MatDialog).openDialogs).toHaveLength(0);
      request.flush({}, { status: 403, statusText: 'Unavailable' }); await fixture.whenStable();
    });

    it.each(['S', '+'])('honours the case-insensitive or shifted printable binding %s', async pressed => {
      select();
      if (pressed === '+') expect(TestBed.inject(KeyboardMappingService).setKey('stack', '+')).toBeNull();
      expect(key({ key: pressed, shiftKey: true }).defaultPrevented).toBe(true);
      await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe('/stacks/edit'));
      routed.detectChanges();
      fixture.detectChanges();
      const request = http.expectOne('/api/stacks/regroup/preview');
      expect(request.request.body.selected_paths).toEqual(rows.map(row => row.path));
      request.flush({}, { status: 500, statusText: 'Failed' });
      await fixture.whenStable();
    });

    it.each([{ repeat: true }, { isComposing: true }, { keyCode: 229 }, { ctrlKey: true }, { metaKey: true }, { altKey: true }])('preserves modified/repeated/composing S: %j', async init => {
      select();
      expect(key(init).defaultPrevented).toBe(false);
      await fixture.whenStable(); noEditor();
    });

    it.each(['input', 'textarea', 'select', 'editable', 'menu'])('suppresses S in a %s typing context', async kind => {
      select();
      const target = document.createElement(['editable', 'menu'].includes(kind) ? 'div' : kind);
      if (kind === 'editable') Object.defineProperty(target, 'isContentEditable', { value: true });
      if (kind === 'menu') target.setAttribute('role', 'menu');
      document.body.appendChild(target);
      try { expect(key({}, target).defaultPrevented).toBe(false); await fixture.whenStable(); noEditor(); }
      finally { target.remove(); }
    });

    it.each(['none', 'one', 'whole-view', 'too-many', 'readonly', 'slideshow', 'parked'])('suppresses S for %s', async state => {
      if (state !== 'none') select();
      if (state === 'one') store.toggleSelection(rows[1]);
      if (state === 'whole-view') store.selectWholeView();
      if (state === 'too-many') store.selectedPaths.set(new Set(Array.from({ length: 1001 }, (_, i) => `/p${i}.jpg`)));
      if (state === 'readonly') auth.status.update(status => ({ ...status!, edition_authenticated: false, user_role: 'viewer' }));
      if (state === 'slideshow') store.slideshowActive.set(true);
      if (state === 'parked') fixture.componentInstance['parked'] = true;
      expect(key().defaultPrevented).toBe(false);
      await fixture.whenStable(); noEditor();
    });

    it('stands down for a real Material dialog and native button activation', async () => {
      select();
      const ref = TestBed.inject(MatDialog).open(StackDialogComponent, { data: { paths: rows.map(row => row.path) } });
      TestBed.inject(ApplicationRef).tick();
      http.expectOne('/api/stacks/regroup/preview').flush({}, { status: 500, statusText: 'Failed' });
      await fixture.whenStable();
      expect(key().defaultPrevented).toBe(false);
      expect(document.querySelectorAll('app-stack-dialog')).toHaveLength(1);
      http.expectNone('/api/stacks/regroup/preview');
      ref.close(); await fixture.whenStable();
      const button = fixture.nativeElement.querySelector('[data-create-stack]')!;
      expect(key({ key: 'Enter' }, button).defaultPrevented).toBe(false);
      expect(key({ key: ' ' }, button).defaultPrevented).toBe(false);
      noEditor();
    });

    it('fires only the saved competing action when Stack is unassigned', async () => {
      select();
      TestBed.inject(KeyboardMappingService).keymap.set({ ...DEFAULT_KEYMAP, toggleSidebar: 's', stack: '' });
      fixture.detectChanges();
      expect(store.filterDrawerOpen()).toBe(false);
      expect(key().defaultPrevented).toBe(true);
      expect(store.filterDrawerOpen()).toBe(true);
      await fixture.whenStable(); noEditor();
      const button = fixture.debugElement.queryAllNodes(node => node.nativeNode?.hasAttribute?.('data-create-stack'))[0];
      expect(button.injector.get(MatTooltip).message).toBe('stacks.create {"key":""}');
    });

    it('does not navigate when the gallery is already parked', async () => {
      select(); fixture.componentInstance['parked'] = true;
      expect(key().defaultPrevented).toBe(false);
      await fixture.whenStable(); noEditor();
    });

    it('ignores an event already consumed by another control', async () => {
      select();
      const event = new KeyboardEvent('keydown', { key: 's', bubbles: true, cancelable: true });
      event.preventDefault(); document.dispatchEvent(event);
      await fixture.whenStable(); noEditor();
    });

    it('honours remapping and displays the actual key in the toolbar tooltip', async () => {
      select();
      const mapping = TestBed.inject(KeyboardMappingService);
      expect(mapping.setKey('stack', 'g')).toBeNull();
      fixture.detectChanges();
      expect(key().defaultPrevented).toBe(false);
      await fixture.whenStable(); noEditor();
      const button = fixture.debugElement.queryAllNodes(node => node.nativeNode?.hasAttribute?.('data-create-stack'))[0];
      expect(button).toBeDefined();
      // The real translated tooltip includes the currently mapped binding.
      expect(button.injector.get(MatTooltip).message).toContain('G');
      key({ key: 'g' });
      await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe('/stacks/edit'));
      routed.detectChanges();
      fixture.detectChanges(); http.expectOne('/api/stacks/regroup/preview').flush({}, { status: 500, statusText: 'Failed' });
      await fixture.whenStable();
    });
  });

  it('stack badge opens the normal viewer directly without opening the editor or replacing scope', async () => {
    const router = TestBed.inject(Router);
    router.resetConfig([{ path: 'photo', children: [] }]);
    const originalFilters = store.filters();
    const photo = makePhoto({ path: '/trip/b.jpg', stack_id: 's1', stack_count: 3, stack_total_count: 3 });
    store.photos.set([photo]); fixture.detectChanges();
    const dialog = vi.spyOn(fixture.debugElement.injector.get(MatDialog), 'open');
    const navigation = firstValueFrom(router.events.pipe(filter(event => event instanceof NavigationEnd), take(1)));
    const badge = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-stack-badge]')!;
    expect(badge).not.toBeNull(); badge.click();
    await navigation;
    expect(router.url).toBe('/photo?path=%2Ftrip%2Fb.jpg');
    expect(dialog).not.toHaveBeenCalled();
    expect(store.pinnedPaths()).toBeNull();
    expect(store.filters()).toEqual(originalFilters);
    expect(store.photos()).toEqual([photo]);
  });

  it.each(['grid', 'mosaic'] as const)('expands and collapses %s via the mobile shell button through HTTP without losing photo totals or paging', async mode => {
    store.setGalleryMode(mode);
    store.filters.update(filters => ({ ...filters, per_page: 2 }));
    fixture.componentInstance['containerWidth'].set(768);
    const a = makePhoto({ path: '/a.jpg', stack_id: 's1', stack_count: 3, stack_total_count: 3 });
    const b = makePhoto({ path: '/b.jpg', stack_id: 's1', stack_count: 3, stack_total_count: 3 });
    const c = makePhoto({ path: '/c.jpg', stack_id: 's1', stack_count: 3, stack_total_count: 3 });
    const d = makePhoto({ path: '/d.jpg' });
    const loading = store.reloadPhotos();
    http.expectOne(req => req.url === '/api/photos').flush({ ...page, per_page: 2, photos: [a,d], total: 2, photo_total: 4 });
    progressRequests().forEach(req => req.flush({ ...counts, total: 4 }));
    await loading; flushSideData(); fixture.detectChanges();
    // Gallery startup has completed above; render the real shell with its shared
    // store, without running a second copy of application startup HTTP.
    const startup = vi.spyOn(App.prototype, 'ngOnInit').mockResolvedValue();
    const shell = TestBed.createComponent(App);
    shell.detectChanges(); startup.mockRestore();
    try {
      const root = shell.nativeElement as HTMLElement;
      const button = root.querySelector<HTMLButtonElement>('[data-stack-collapse-mobile]');
      expect(button).not.toBeNull();
      expect(button?.closest('.lg\\:hidden')).not.toBeNull();
      expect(fixture.componentInstance.effectiveGalleryMode()).toBe(mode);
      expect((fixture.nativeElement as HTMLElement).querySelectorAll('app-photo-card')).toHaveLength(2);
      button!.click();
      const expand = http.expectOne(req => req.url === '/api/photos');
      expect(expand.request.params.get('collapse_stacks')).toBe('0');
      expect(expand.request.params.get('page')).toBe('1');
      expect(expand.request.params.get('per_page')).toBe('2');
      expand.flush({ ...page, per_page: 2, photos: [a,b], total: 4, photo_total: 4, has_more: true, total_pages: 2 });
      progressRequests().forEach(req => req.flush({ ...counts, total: 4 }));
      await fixture.whenStable(); flushSideData(); fixture.detectChanges(); shell.detectChanges();
      expect(store.total()).toBe(4); expect(store.photoTotal()).toBe(4);
      expect(button!.hasAttribute('aria-pressed')).toBe(false);
      const paging = store.nextPage();
      const next = http.expectOne(req => req.url === '/api/photos');
      expect(next.request.params.get('collapse_stacks')).toBe('0');
      expect(next.request.params.get('page')).toBe('2');
      next.flush({ ...page, per_page: 2, photos: [c,d], total: 4, photo_total: 4, page: 2, total_pages: 2 });
      await paging; flushSideData(); fixture.detectChanges();
      expect(store.photos().map(photo => photo.path)).toEqual(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
      expect((fixture.nativeElement as HTMLElement).querySelectorAll('app-photo-card')).toHaveLength(4);
      button!.click();
      const collapse = http.expectOne(req => req.url === '/api/photos');
      expect(collapse.request.params.get('collapse_stacks')).toBe('1');
      expect(collapse.request.params.get('page')).toBe('1');
      collapse.flush({ ...page, per_page: 2, photos: [a,d], total: 2, photo_total: 4 });
      progressRequests().forEach(req => req.flush({ ...counts, total: 4 }));
      await fixture.whenStable(); flushSideData(); fixture.detectChanges(); shell.detectChanges();
      expect(store.total()).toBe(2); expect(store.photoTotal()).toBe(4);
      expect(store.photos().map(photo => photo.path)).toEqual(['/a.jpg', '/d.jpg']);
      expect((fixture.nativeElement as HTMLElement).querySelectorAll('app-photo-card')).toHaveLength(2);
      expect(button!.hasAttribute('aria-pressed')).toBe(false);
      // Existing bottom-bar actions remain reachable alongside the new control.
      const slideshow = root.querySelector<HTMLButtonElement>('button[aria-label^="slideshow.start"]');
      expect(slideshow).not.toBeNull(); slideshow!.click();
      expect(store.slideshowActive()).toBe(true);
    } finally { shell.destroy(); }
  });

  it.each([true, false])('refreshes projected stack counts after an assistant changes an offscreen member (collapsed=%s)', async collapsed => {
    store.collapseStacks.set(collapsed);
    store.filters.update(filters => ({ ...filters, review_status: 'kept', per_page: 1 }));
    const cover = makePhoto({ path: '/trip/a.jpg', stack_id: 's1', stack_count: 3, stack_total_count: 3 });
    const loading = store.reloadPhotos();
    http.expectOne(req => req.url === '/api/photos').flush({ ...page, photos: [cover], per_page: 1,
      total: collapsed ? 1 : 3, photo_total: 3, has_more: !collapsed, total_pages: collapsed ? 1 : 3 });
    progressRequests().forEach(req => req.flush({ ...counts, total: 3, kept: 3 }));
    await loading; flushSideData();
    store.selectWholeView();
    const filters = store.filters();
    const started = requested('/api/photos');
    assistantBatches.next({ paths: ['/trip/b.jpg'] });
    await started;
    const repair = http.expectOne(req => req.url === '/api/photos');
    expect(repair.request.params.get('collapse_stacks')).toBe(collapsed ? '1' : '0');
    repair.flush({ ...page, photos: [{ ...cover, stack_count: 2 }], per_page: 1,
      total: collapsed ? 1 : 2, photo_total: 2, has_more: !collapsed, total_pages: collapsed ? 1 : 2 });
    progressRequests().forEach(req => req.flush({ ...counts, kept: 2 }));
    await fixture.whenStable(); flushSideData();
    expect(store.photos()[0].stack_count).toBe(2);
    expect(store.photoTotal()).toBe(2);
    expect(store.selectionCount()).toBe(2);
    expect(store.filters()).toEqual(filters);
    http.expectNone(req => req.url === '/api/photos/by_paths');
  });

  it('defers an offscreen stack member repair while parked and updates it on Back', async () => {
    const cover = makePhoto({ path: '/trip/a.jpg', stack_id: 's1', stack_count: 3, stack_total_count: 3 });
    const loading = store.reloadPhotos();
    http.expectOne(req => req.url === '/api/photos').flush({ ...page, photos: [cover], total: 1, photo_total: 3 });
    progressRequests().forEach(req => req.flush({ ...counts, total: 3 }));
    await loading; flushSideData();
    store.parkListingReads();
    assistantBatches.next({ paths: ['/trip/b.jpg'] });
    http.expectNone(req => req.url === '/api/photos' || req.url === '/api/photos/by_paths');
    const started = requested('/api/photos');
    const returning = store.resumeListingReads();
    await started;
    http.expectOne(req => req.url === '/api/photos').flush({ ...page, photos: [{ ...cover, stack_count: 2 }], total: 1, photo_total: 2 });
    progressRequests().forEach(req => req.flush(counts));
    await returning; flushSideData();
    expect(store.photoTotal()).toBe(2);
    expect(store.photos()[0].stack_count).toBe(2);
  });

  it.each(['review', 'delete'] as const)('repairs retained stack badges after an expanded member %s', async action => {
    store.collapseStacks.set(false);
    store.filters.update(filters => ({ ...filters, review_status: 'kept' }));
    const members = ['/trip/a.jpg', '/trip/b.jpg', '/trip/c.jpg'].map(path => makePhoto({
      path, stack_id: 's1', stack_count: 3, stack_total_count: 3,
    }));
    const loading = store.reloadPhotos();
    http.expectOne(req => req.url === '/api/photos').flush({ ...page, photos: members, total: 3, photo_total: 3 });
    progressRequests().forEach(req => req.flush({ ...counts, total: 3 }));
    await loading; flushSideData();
    store.restoreSelection([members[2].path]);
    const started = requested('/api/photos');
    if (action === 'review') {
      const targeted = requested('/api/photos/by_paths');
      assistantBatches.next({ paths: [members[1].path] });
      await targeted;
      http.expectOne('/api/photos/by_paths').flush({ photos: [], missing: [members[1].path] });
    } else store.removePhotos([members[1].path]);
    await started;
    http.expectOne(req => req.url === '/api/photos').flush({ ...page,
      photos: [members[0], members[2]].map(photo => ({ ...photo, stack_count: 2, stack_total_count: action === 'delete' ? 2 : 3 })),
      total: 2, photo_total: 2,
    });
    progressRequests().forEach(req => req.flush(counts));
    await fixture.whenStable(); flushSideData(); fixture.detectChanges();
    expect(store.photoTotal()).toBe(2);
    expect(store.photos().map(photo => photo.stack_count)).toEqual([2, 2]);
    expect([...store.selectedPaths()]).toEqual([members[2].path]);
    const badges = [...(fixture.nativeElement as HTMLElement).querySelectorAll('[data-stack-badge]')];
    expect(badges).toHaveLength(2);
    expect(badges.every(badge => badge.textContent?.includes('2'))).toBe(true);
  });

  it('still expands through HTTP when persisting the browser preference fails', async () => {
    const original = Storage.prototype.setItem;
    const blocked = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function(this: Storage, key: string, value: string) {
      if (key === 'facet_collapse_stacks') throw new DOMException('Storage full', 'QuotaExceededError');
      original.call(this, key, value);
    });
    try {
      const expanding = store.toggleStackCollapse();
      const request = http.expectOne(req => req.url === '/api/photos');
      expect(request.request.params.get('collapse_stacks')).toBe('0');
      request.flush({ ...page, photo_total: 2 });
      progressRequests().forEach(req => req.flush(counts));
      await expanding;
      flushSideData();
      expect(store.collapseStacks()).toBe(false);
      expect(store.photos()).toEqual(rows);
    } finally { blocked.mockRestore(); }
  });

  it.each(['cover', 'hidden-member', 'two-member-dissolve'] as const)('reconciles %s deletion without expanding the requested targets', async scenario => {
    const paths = ['/trip/a.jpg', '/trip/b.jpg', '/trip/c.jpg'];
    const members = scenario === 'two-member-dissolve' ? paths.slice(0, 2) : paths;
    const reloading = store.reloadPhotos();
    http.expectOne(req => req.url === '/api/photos').flush({ ...page, total: 1, photo_total: members.length,
      photos: [{ ...rows[0], stack_id: 's1', stack_count: members.length, stack_total_count: members.length }] });
    progressRequests().forEach(req => req.flush(counts)); await reloading; flushSideData();
    // Select only the one deletion target.
    const target = scenario === 'hidden-member' ? paths[1] : paths[0];
    store.restoreSelection([target]); fixture.detectChanges();
    vi.spyOn(fixture.debugElement.injector.get(MatDialog), 'open').mockReturnValue({ afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false, removeMissing: true }) } as never);
    const deletion = vi.spyOn(fixture.componentInstance, 'deleteSelected');
    const refresh = vi.spyOn(store, 'refreshPaths');
    const started = requested('/api/photo/delete');
    const deleteButton = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('[data-selection-bar] button')]
      .find(button => button.getAttribute('aria-label')?.startsWith('cull.delete_action'))!;
    expect(deleteButton).toBeDefined(); expect(deleteButton.disabled).toBe(false); deleteButton.click();
    await started;
    expect(deletion).toHaveBeenCalled();
    expect(fixture.debugElement.injector.get(MatDialog).open).toHaveBeenCalled();
    const write = http.expectOne('/api/photo/delete');
    expect(write.request.body).toEqual({ paths: [target], include_companions: false, include_sequence_siblings: false, remove_missing: true, dry_run: false });
    const repaired = requested('/api/photos');
    write.flush({ deleted: [target], removed_missing: [], refused_bracket_lead: [], not_found: [], not_visible: [], skipped: [], errors: {}, trashed: 1 });
    await repaired;
    const survivor = target === paths[0] ? paths[1] : paths[0];
    const remaining = members.length - 1;
    http.expectOne(req => req.url === '/api/photos').flush({ ...page, total: 1, photo_total: remaining,
      photos: [makePhoto({ path: survivor, ...(remaining > 1 ? { stack_id: 's1', stack_count: remaining, stack_total_count: remaining } : {}) })] });
    progressRequests().forEach(req => req.flush(counts));
    await refresh.mock.results[0].value; await deletion.mock.results[0].value; flushSideData(); fixture.detectChanges();
    expect(store.photos().map(photo => photo.path)).toEqual([survivor]);
    expect(store.total()).toBe(1); expect(store.photoTotal()).toBe(remaining);
    expect(store.selectedPaths().size).toBe(0);
    expect((fixture.nativeElement as HTMLElement).querySelectorAll('app-photo-card')).toHaveLength(1);
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-stack-badge]') !== null).toBe(remaining > 1);
    http.expectNone(req => req.url === '/api/photo/delete');
  });

  it('repairs both loaded pages when Keep elects an earlier fallback and preserves explicit selection and later paging', async () => {
    const a = makePhoto({ path: '/a.jpg', stack_id: 's1', stack_count: 2, stack_total_count: 2 });
    const a2 = makePhoto({ path: '/a2.jpg', stack_id: 's1', stack_count: 1, stack_total_count: 2 });
    const b = makePhoto({ path: '/b.jpg' }), c = makePhoto({ path: '/c.jpg' }), d = makePhoto({ path: '/d.jpg' }), e = makePhoto({ path: '/e.jpg' });
    store.filters.update(f => ({ ...f, page: 2, per_page: 2, review_status: 'undecided' }));
    store.photos.set([a, b, c, d]); store.restoreSelection([b.path]);
    const keeping = store.batchReview([a.path], 'kept', false);
    const firstStarted = requested('/api/photos');
    http.expectOne('/api/photos/batch_review').flush({ count: 1 }); await firstStarted;
    const first = http.expectOne(req => req.url === '/api/photos');
    expect(first.request.params.get('page')).toBe('1');
    const nextStarted = requested('/api/photos');
    first.flush({ ...page, page: 1, per_page: 2, total: 5, photo_total: 5, photos: [b,a2], has_more: true }); await nextStarted;
    const second = http.expectOne(req => req.url === '/api/photos'); expect(second.request.params.get('page')).toBe('2');
    second.flush({ ...page, page: 2, per_page: 2, total: 5, photo_total: 5, photos: [c,d], has_more: true });
    progressRequests().forEach(req => req.flush(counts)); const result = await keeping; flushSideData();
    expect(store.photos().map(photo => photo.path)).toEqual(['/b.jpg', '/a2.jpg', '/c.jpg', '/d.jpg']);
    expect(new Set(store.photos().map(photo => photo.path)).size).toBe(4);
    expect([...store.selectedPaths()]).toEqual(['/b.jpg']); expect(store.photoTotal()).toBe(5);
    const paging = store.nextPage();
    const third = http.expectOne(req => req.url === '/api/photos'); expect(third.request.params.get('page')).toBe('3');
    third.flush({ ...page, page: 3, per_page: 2, total: 5, photo_total: 5, photos: [e], has_more: false }); await paging; flushSideData();
    expect(store.photos().map(photo => photo.path)).toEqual(['/b.jpg', '/a2.jpg', '/c.jpg', '/d.jpg', '/e.jpg']);
    expect(store.total()).toBe(5); expect(store.hasMore()).toBe(false);
    const undoStarted = requested('/api/photos/batch_review');
    const undoing = store.restoreSnapshot(result!.snapshot); await undoStarted;
    const undo = http.expectOne('/api/photos/batch_review');
    expect(undo.request.body).toEqual({ photo_paths: ['/a.jpg'], decision: 'undecided' });
    const restoreStarted = requested('/api/photos'); undo.flush({ count: 1 }); await restoreStarted;
    for (const [index, photos] of [[a,b], [c,d], [e]].entries()) {
      const request = http.expectOne(req => req.url === '/api/photos');
      expect(request.request.params.get('page')).toBe(String(index + 1));
      const next = index < 2 ? requested('/api/photos') : null;
      request.flush({ ...page, page: index + 1, per_page: 2, total: 5, photo_total: 6, photos, has_more: index < 2 });
      if (next) await next;
    }
    progressRequests().forEach(req => req.flush(counts)); await undoing; flushSideData();
    expect(store.photos().map(photo => photo.path)).toEqual(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg', '/e.jpg']);
    expect(store.photoTotal()).toBe(6);
  });
  it('cancels the replacement-prefix read on a real navigation and refuses late rows', async () => {
    const router = TestBed.inject(Router);
    router.resetConfig([{ path: 'away', children: [] }]);
    const a = makePhoto({ path: '/a.jpg', stack_id: 's1', stack_count: 2, stack_total_count: 2 });
    store.filters.update(f => ({ ...f, page: 2, per_page: 2, review_status: 'undecided' }));
    store.photos.set([a, makePhoto({ path: '/b.jpg' }), makePhoto({ path: '/c.jpg' }), makePhoto({ path: '/d.jpg' })]);
    const keeping = store.batchReview([a.path], 'kept', false);
    const started = requested('/api/photos'); http.expectOne('/api/photos/batch_review').flush({ count: 1 }); await started;
    const read = http.expectOne(req => req.url === '/api/photos');
    expect(read.request.params.get('page')).toBe('1');
    await router.navigateByUrl('/away');
    expect(read.cancelled).toBe(true);
    store.photos.set([makePhoto({ path: '/new-view.jpg' })]);
    await keeping; flushSideData();
    expect(store.photos().map(photo => photo.path)).toEqual(['/new-view.jpg']);
    http.expectNone(req => req.url === '/api/photos');
  });
});
