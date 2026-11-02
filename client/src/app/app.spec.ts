import { TestBed } from '@angular/core/testing';
import { DefaultUrlSerializer, Router, provideRouter } from '@angular/router';
import { Component, Provider, signal } from '@angular/core';
import { NEVER, Subject, of } from 'rxjs';
import { App } from './app';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS } from './features/gallery/gallery.store';
import { AuthService } from './core/services/auth.service';
import { ApiService } from './core/services/api.service';
import { I18nService } from './core/services/i18n.service';
import { ThemeService } from './core/services/theme.service';
import { CompareFiltersService } from './features/comparison/compare-filters.service';
import { StatsFiltersService } from './features/stats/stats-filters.service';
import { PersonsFiltersService } from './features/persons/persons-filters.service';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SwUpdate } from '@angular/service-worker';
import { I18N } from './core/i18n/keys';
import { ScanService } from './core/services/scan.service';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';

import { KeyboardMappingService, KEYMAP_STORAGE_KEY } from './core/services/keyboard-mapping.service';

@Component({ selector: 'app-navigation-fixture-page', template: '' })
class NavigationFixturePage {}

function createApp(routerUrl = '/', extraProviders: Provider[] = []) {
  const filtersSignal = signal<GalleryFilters>({ ...DEFAULT_FILTERS });
  const personsSignal = signal<{ id: number; name: string | null }[]>([]);
  const compareCategorySig = signal('');
  const selectionCountSignal = signal(0);
  const viewFilterParamsSignal = signal({
    hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
  });
  const mockStore = {
    filters: filtersSignal,
    persons: personsSignal,
    selectionCount: selectionCountSignal,
    updateFilter: vi.fn(),
    setUserSort: vi.fn(() => Promise.resolve()),
    resetFilters: vi.fn(() => Promise.resolve()),
    config: signal(null),
    types: signal<{ id: string; count: number }[]>([]),
    loadTypeCounts: vi.fn(() => Promise.resolve()),
    loadConfig: vi.fn(),
    viewFilterParams: viewFilterParamsSignal,
    pinnedPaths: signal<string[] | null>(null),
    showAllHidden: vi.fn(),
  };

  const mockRouter = { url: routerUrl, events: NEVER, navigate: vi.fn(), parseUrl: (url: string) => new DefaultUrlSerializer().parse(url) };

  TestBed.configureTestingModule({
    providers: [
      App,
      { provide: Router, useValue: mockRouter },
      { provide: GalleryStore, useValue: mockStore },
      { provide: AuthService, useValue: { identity: () => '0|', isAuthenticated: vi.fn(() => true), checkStatus: vi.fn(() => Promise.resolve()) } },
      { provide: I18nService, useValue: { load: vi.fn(() => Promise.resolve()), loadLanguages: vi.fn(() => Promise.resolve()), languages: signal([]), t: vi.fn((k: string) => k), translations: signal({}) } },
      { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      { provide: CompareFiltersService, useValue: { selectedCategory: compareCategorySig } },
      { provide: MatDialog, useValue: { open: vi.fn() } },
      { provide: ApiService, useValue: { get: vi.fn(() => NEVER), post: vi.fn(() => NEVER) } },
      { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], setTheme: vi.fn(), toggleDarkMode: vi.fn(), accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
      ...extraProviders,
    ],
  });

  return {
    app: TestBed.inject(App),
    filtersSignal,
    personsSignal,
    mockStore,
    mockRouter,
    compareCategorySig,
    selectionCountSignal,
    viewFilterParamsSignal,
    personsFilters: TestBed.inject(PersonsFiltersService),
  };
}

describe('App', () => {
  describe('help dialog shortcuts', () => {
    afterEach(() => {
      TestBed.inject(KeyboardMappingService).resetAll();
      localStorage.removeItem(KEYMAP_STORAGE_KEY);
    });

    it('shows only stack review decisions in Suggested stacks help', () => {
      const { app } = createApp('/culling?mode=stacks&filters=%7B%7D');
      (app as any).openHelpDialog();
      const open = TestBed.inject(MatDialog).open as unknown as ReturnType<typeof vi.fn>;
      const sections = open.mock.calls[0][1].data.shortcutSections as { rows: { keys: string[]; labelKey: string }[] }[];
      const rows = sections.flatMap(section => section.rows);
      expect(rows.some(row => row.keys.includes('S') && row.labelKey === 'stacks.stack_cover')).toBe(true);
      expect(rows.some(row => row.keys.includes('X'))).toBe(true);
      expect(rows.some(row => row.keys.includes('R') && row.labelKey === 'stacks.reject_focused')).toBe(true);
      expect(rows.map(row => row.labelKey)).not.toContain('culling.shortcuts.keep');
      expect(rows.map(row => row.labelKey)).not.toContain('culling.shortcuts.reject');
      expect(rows.map(row => row.labelKey)).not.toContain('culling.shortcuts.toggle');
    });

    it('shows manual editor navigation and explicit Reject without culling decisions', () => {
      const { app } = createApp('/stacks/edit');
      (app as any).openHelpDialog();
      const open = TestBed.inject(MatDialog).open as unknown as ReturnType<typeof vi.fn>;
      const sections = open.mock.calls[0][1].data.shortcutSections;
      expect(sections).toEqual([{ titleKey: 'stacks.create', rows: [{ keys: ['Esc'], labelKey: 'stacks.back_gallery' }, { keys: ['R'], labelKey: 'stacks.reject_focused' }, { keys: ['←', '→'], labelKey: 'culling.shortcuts.navigate' }] }]);
    });

    it('lists the remapped reject key on a gallery route, not the default', () => {
      const { app } = createApp('/');
      TestBed.inject(KeyboardMappingService).setKey('reject', 'r');
      (app as any).openHelpDialog();
      const open = TestBed.inject(MatDialog).open as unknown as ReturnType<typeof vi.fn>;
      const sections = open.mock.calls[0][1].data.shortcutSections as { rows: { keys: string[]; labelKey: string }[] }[];
      const reject = sections[0].rows.find(r => r.labelKey === I18N.shortcuts.reject)!;
      expect(reject.keys).toContain('R');
      expect(reject.keys).not.toContain('X');
    });
  });

  describe('route detection', () => {
    it('isGalleryRoute returns true for /', () => {
      const { app } = createApp('/');
      expect((app as any).isGalleryRoute()).toBe(true);
    });

    it('isGalleryRoute returns false for /compare', () => {
      const { app } = createApp('/compare');
      expect((app as any).isGalleryRoute()).toBe(false);
    });

    it('isCompareRoute returns true for /compare', () => {
      const { app } = createApp('/compare');
      expect((app as any).isCompareRoute()).toBe(true);
    });

    it('isCompareRoute returns false for /', () => {
      const { app } = createApp('/');
      expect((app as any).isCompareRoute()).toBe(false);
    });

    it('isStatsRoute returns true for /stats', () => {
      const { app } = createApp('/stats');
      expect((app as any).isStatsRoute()).toBe(true);
    });

    it('isGalleryRoute ignores query string', () => {
      const { app } = createApp('/?sort=aggregate&type=portrait');
      expect((app as any).isGalleryRoute()).toBe(true);
    });

    it('isCompareRoute ignores query string', () => {
      const { app } = createApp('/compare?category=portrait');
      expect((app as any).isCompareRoute()).toBe(true);
    });
  });

  describe('mobile timeline bottom bar — reachability affordance', () => {
    it('is false when every hide toggle is off', () => {
      const { app } = createApp('/timeline');
      expect((app as any).anyTimelinePhotosHiddenByFilters()).toBe(false);
    });

    it('is true when at least one hide toggle is on', () => {
      const { app, viewFilterParamsSignal } = createApp('/timeline');
      viewFilterParamsSignal.set({
        hide_blinks: '0', hide_bursts: '1', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
      });
      expect((app as any).anyTimelinePhotosHiddenByFilters()).toBe(true);
    });
  });

  describe('mobile bottom bar vs selection (issue #73)', () => {
    ;

    ;

    ;

    it('shows the persons bottom bar when nothing is selected', () => {
      const { app } = createApp('/persons');
      expect((app as any).mobilePersonsBarVisible()).toBe(true);
    });

    it('hides the persons bottom bar while persons are selected', () => {
      const { app, personsFilters } = createApp('/persons');
      personsFilters.selectedIds.set(new Set([1, 2]));
      expect((app as any).mobilePersonsBarVisible()).toBe(false);
    });

    it('leaves the persons bar alone when the gallery has a selection', () => {
      const { app, selectionCountSignal } = createApp('/persons');
      selectionCountSignal.set(5);
      expect((app as any).mobilePersonsBarVisible()).toBe(true);
    });
  });

  describe('onCompareCategoryChange', () => {
    it('sets selectedCategory on compareFilters service', () => {
      const { app, compareCategorySig } = createApp('/');
      (app as any).onCompareCategoryChange('portrait');
      expect(compareCategorySig()).toBe('portrait');
    });
  });

  ;

  describe('resetAllFilters', () => {
    it('navigates to / and calls store.resetFilters', () => {
      const { app, mockStore, mockRouter } = createApp('/');
      (app as any).resetAllFilters();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/']);
      expect(mockStore.resetFilters).toHaveBeenCalled();
    });

    it('navigates to / even when on a different route', () => {
      const { app, mockStore, mockRouter } = createApp('/stats');
      (app as any).resetAllFilters();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/']);
      expect(mockStore.resetFilters).toHaveBeenCalled();
    });
  });

  describe('service worker update toast', () => {
    function withSw(isEnabled: boolean) {
      const versionUpdates = new Subject<unknown>();
      const onAction = vi.fn(() => new Subject<void>());
      const open = vi.fn(() => ({ onAction }));
      const { app } = createApp('/', [
        { provide: SwUpdate, useValue: { isEnabled, versionUpdates } },
        { provide: MatSnackBar, useValue: { open } },
      ]);
      return { app, versionUpdates, open, onAction };
    }

    it('opens a reload snackbar and wires its action on VERSION_READY', () => {
      const { app, versionUpdates, open, onAction } = withSw(true);
      (app as any).setupUpdateNotifications();
      versionUpdates.next({ type: 'VERSION_READY' });
      expect(open).toHaveBeenCalledWith(I18N.pwa.update_available, I18N.pwa.reload);
      expect(onAction).toHaveBeenCalled();
    });

    it('ignores version events other than VERSION_READY', () => {
      const { app, versionUpdates, open } = withSw(true);
      (app as any).setupUpdateNotifications();
      versionUpdates.next({ type: 'VERSION_DETECTED' });
      expect(open).not.toHaveBeenCalled();
    });

    it('does nothing when the service worker is disabled', () => {
      const { app, versionUpdates, open } = withSw(false);
      (app as any).setupUpdateNotifications();
      versionUpdates.next({ type: 'VERSION_READY' });
      expect(open).not.toHaveBeenCalled();
    });
  });

  describe('new release notice', () => {
    const RELEASE_NOTICE_KEY = 'facet_release_notice_shown';

    function withRelease(payload: unknown, { edition = true } = {}) {
      const actionSubject = new Subject<void>();
      const onAction = vi.fn(() => actionSubject);
      const open = vi.fn(() => ({ onAction }));
      const get = vi.fn(() => of(payload));
      const t = vi.fn((key: string, vars?: Record<string, string>) => (vars ? `${key}:${vars['version']}` : key));
      const { app } = createApp('/', [
        {
          provide: AuthService,
          useValue: {
            identity: () => '0|',
            isAuthenticated: vi.fn(() => true),
            checkStatus: vi.fn(() => Promise.resolve()),
            isEdition: vi.fn(() => edition),
          },
        },
        { provide: ApiService, useValue: { get, post: vi.fn(() => NEVER) } },
        { provide: MatSnackBar, useValue: { open } },
        {
          provide: I18nService,
          useValue: {
            load: vi.fn(() => Promise.resolve()),
            loadLanguages: vi.fn(() => Promise.resolve()),
            languages: signal([]),
            t,
            translations: signal({}),
          },
        },
      ]);
      return { app, get, open, actionSubject };
    }

    const AVAILABLE = { update_available: true, latest: 'v9.9.9', release_url: 'https://example/r' };

    beforeEach(() => localStorage.clear());

    it('requests the endpoint path ApiService expects, not a doubled /api prefix', async () => {
      const { app, get } = withRelease(AVAILABLE);
      await (app as any).maybeAnnounceNewRelease();
      // ApiService prepends /api itself. Passing '/api/updates/check' here asked
      // for /api/api/updates/check, which 404s, and the catch below swallowed it
      // -- so the notice could never fire and no test noticed.
      expect(get).toHaveBeenCalledWith('/updates/check');
    });

    it('opens the notice with the interpolated version and a View action', async () => {
      const { app, open } = withRelease(AVAILABLE);
      await (app as any).maybeAnnounceNewRelease();
      expect(open).toHaveBeenCalledWith(
        `${I18N.updates.available}:${AVAILABLE.latest}`,
        I18N.updates.view,
        { duration: 15000 },
      );
    });

    it('drives window.open with the release URL when the View action fires', async () => {
      const { app, actionSubject } = withRelease(AVAILABLE);
      const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
      await (app as any).maybeAnnounceNewRelease();
      actionSubject.next();
      expect(openSpy).toHaveBeenCalledWith(AVAILABLE.release_url, '_blank', 'noopener');
      openSpy.mockRestore();
    });

    it('stamps the notice as shown once it fires, so a reload cannot re-show it', async () => {
      const { app } = withRelease(AVAILABLE);
      expect(localStorage.getItem(RELEASE_NOTICE_KEY)).toBeNull();
      await (app as any).maybeAnnounceNewRelease();
      expect(localStorage.getItem(RELEASE_NOTICE_KEY)).not.toBeNull();
    });

    it('stays quiet when the server reports no update', async () => {
      const { app, open } = withRelease({ update_available: false, latest: null, release_url: null });
      await (app as any).maybeAnnounceNewRelease();
      expect(open).not.toHaveBeenCalled();
    });

    it('does not stamp the notice when there is no update to report', async () => {
      const { app } = withRelease({ update_available: false, latest: null, release_url: null });
      await (app as any).maybeAnnounceNewRelease();
      expect(localStorage.getItem(RELEASE_NOTICE_KEY)).toBeNull();
    });

    it('never reaches the endpoint outside edition mode', async () => {
      const { app, get } = withRelease(AVAILABLE, { edition: false });
      await (app as any).maybeAnnounceNewRelease();
      expect(get).not.toHaveBeenCalled();
    });

    describe('on startup', () => {
      function withStartup(payload: unknown, { edition = true } = {}) {
        const onAction = vi.fn(() => new Subject<void>());
        const open = vi.fn(() => ({ onAction }));
        const get = vi.fn((path: string) => of(path === '/updates/check' ? payload : {}));
        const { app } = createApp('/', [
          {
            provide: AuthService,
            useValue: {
            identity: () => '0|',
              isAuthenticated: vi.fn(() => true),
              checkStatus: vi.fn(() => Promise.resolve()),
              isEdition: vi.fn(() => edition),
            },
          },
          { provide: ApiService, useValue: { get, post: vi.fn(() => NEVER) } },
          { provide: MatSnackBar, useValue: { open } },
        ]);
        return { app, get, open };
      }

      it('checks for a release when the app loads already in edition mode', async () => {
        const { app, get, open } = withStartup(AVAILABLE);
        await app.ngOnInit();
        expect(get).toHaveBeenCalledWith('/updates/check');
        expect(open).toHaveBeenCalled();
      });

      it('never reaches the endpoint when the app loads outside edition mode', async () => {
        const { app, get } = withStartup(AVAILABLE, { edition: false });
        await app.ngOnInit();
        expect(get).not.toHaveBeenCalledWith('/updates/check');
      });

      it('stays quiet when this week already had a notice', async () => {
        localStorage.setItem(RELEASE_NOTICE_KEY, String(Date.now()));
        const { app, get, open } = withStartup(AVAILABLE);
        await app.ngOnInit();
        expect(get).not.toHaveBeenCalledWith('/updates/check');
        expect(open).not.toHaveBeenCalled();
      });
    });
  });
  describe('read-only banner', () => {
    function render(isReadOnlyInstall: boolean) {
      const mockRouter = { url: '/', events: NEVER, navigate: vi.fn(), config: [] };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: GalleryStore, useValue: { filters: signal({ ...DEFAULT_FILTERS }), persons: signal([]), selectionCount: signal(0), config: signal(null), types: signal([]), loadTypeCounts: vi.fn(), loadConfig: vi.fn(), viewFilterParams: signal({}), pinnedPaths: signal<string[] | null>(null) } },
          { provide: AuthService, useValue: { identity: () => '0|', isAuthenticated: signal(false), hasFeature: () => false, isReadOnlyInstall: signal(isReadOnlyInstall), isEdition: signal(false), status: signal(null), editionPasswordRequired: signal(false), isMultiUser: signal(false), isInstallAdmin: signal(false), loginPasswordRequired: signal(false), checkStatus: vi.fn(() => Promise.resolve()) } },
          { provide: I18nService, useValue: { load: vi.fn(() => Promise.resolve()), loadLanguages: vi.fn(() => Promise.resolve()), languages: signal([]), t: vi.fn((k: string) => k), translations: signal({}) } },
          { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
          { provide: CompareFiltersService, useValue: { selectedCategory: signal('') } },
          { provide: MatDialog, useValue: { open: vi.fn() } },
          { provide: ApiService, useValue: { get: vi.fn(() => NEVER), post: vi.fn(() => NEVER) } },
          { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], setTheme: vi.fn(), toggleDarkMode: vi.fn(), accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
        ],
      });
      const fixture = TestBed.createComponent(App);
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    const BANNER = `a[href*="VIEWER.md#single-user-mode-default"]`;

    it('renders the hint on a read-only install', () => {
      expect(render(true).querySelector(BANNER)?.textContent).toContain(I18N.edition.read_only_hint);
    });

    it('does not render it otherwise', () => {
      expect(render(false).querySelector(BANNER)).toBeNull();
    });
  });

  describe('scan button in the header', () => {
    const TONAL = ['!bg-[var(--mat-sys-primary-container)]', '!text-[var(--mat-sys-on-primary-container)]'];

    function render(canLaunch: boolean, launched = true) {
      const canLaunchSig = signal(canLaunch);
      const openLauncher = vi.fn(() => Promise.resolve(launched));
      const reloadPhotos = vi.fn(() => Promise.resolve());
      const store = {
        filters: signal({ ...DEFAULT_FILTERS }), persons: signal([]), selectionCount: signal(0), config: signal(null),
        types: signal([]), total: signal(0), photoTotal: signal(0), loadTypeCounts: vi.fn(() => Promise.resolve()), reloadPhotos, loadConfig: vi.fn(),
        viewFilterParams: signal({}), activeFilterCount: signal(0), filterDrawerOpen: signal(false), hiddenFiltersStash: signal(null),
        reviewProgressVisible: signal(true), setReviewProgressVisible: vi.fn(),
        collapseStacks: signal(true), toggleStackCollapse: vi.fn(),
        slideshowActive: signal(false), pinnedPaths: signal<string[] | null>(null), setFilterDrawerOpen: vi.fn(), updateFilter: vi.fn(), resetFilters: vi.fn(), restoreHidden: vi.fn(), showAllHidden: vi.fn(),
      };
      TestBed.configureTestingModule({
        providers: [
          provideRouter([]),
          { provide: GalleryStore, useValue: store },
          { provide: ScanService, useValue: { canLaunch: canLaunchSig, openLauncher } },
          { provide: AuthService, useValue: { identity: () => '0|', isAuthenticated: signal(true), isReadOnlyInstall: signal(false), features: signal({}), user: signal(null), logout: vi.fn(), isEdition: signal(false), status: signal(null), editionPasswordRequired: signal(false), isMultiUser: signal(false), isInstallAdmin: signal(false), loginPasswordRequired: signal(false), checkStatus: vi.fn(() => Promise.resolve()) } },
          { provide: I18nService, useValue: { load: vi.fn(() => Promise.resolve()), loadLanguages: vi.fn(() => Promise.resolve()), languages: signal([]), t: vi.fn((k: string) => k), translations: signal({}) } },
          { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
          { provide: CompareFiltersService, useValue: { selectedCategory: signal('') } },
          { provide: MatDialog, useValue: { open: vi.fn() } },
          { provide: ApiService, useValue: { get: vi.fn(() => NEVER), post: vi.fn(() => NEVER) } },
          { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], setTheme: vi.fn(), toggleDarkMode: vi.fn(), accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
        ],
      });
      const fixture = TestBed.createComponent(App);
      fixture.detectChanges();
      const root = fixture.nativeElement as HTMLElement;
      const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>(`button[aria-label="${I18N.gallery.scan_action}"]`));
      return { fixture, root, buttons, store, openLauncher };
    }

    ;

    it('renders one scan button in the application bar immediately before the account menu', () => {
      const { buttons } = render(true);
      const desktop = buttons;
      expect(desktop).toHaveLength(1);
      expect(desktop[0].nextElementSibling?.getAttribute('aria-label')).toBe(I18N.auth.user_menu);
      expect(desktop[0].closest('[data-workspace-navigation]')).not.toBeNull();
      for (const cls of TONAL) expect(desktop[0].classList.contains(cls)).toBe(true);
    });

    ;

    it('labels the button with the scan action (tooltip message and aria-label)', () => {
      const { fixture, buttons } = render(true);
      expect(buttons.length).toBe(1);
      const tooltips = fixture.debugElement.queryAll(By.directive(MatTooltip))
        .filter((d) => buttons.includes(d.nativeElement as HTMLButtonElement));
      expect(tooltips).toHaveLength(1);
      for (const d of tooltips) expect(d.injector.get(MatTooltip).message).toBe(I18N.gallery.scan_action);
      for (const b of buttons) {
        expect(b.getAttribute('aria-label')).toBe(I18N.gallery.scan_action);
        expect(b.textContent).toContain('add_photo_alternate');
      }
    });

    ;

    it('reloads the type counts and the photos when the launcher reports a completed scan', async () => {
      const { buttons, store, openLauncher } = render(true, true);
      buttons[0].click();
      await vi.waitFor(() => expect(store.reloadPhotos).toHaveBeenCalledTimes(1));
      expect(openLauncher).toHaveBeenCalledTimes(1);
      expect(store.loadTypeCounts).toHaveBeenCalled();
    });

    it('reloads nothing when the launcher is dismissed', async () => {
      const { fixture, buttons, store, openLauncher } = render(true, false);
      await fixture.whenStable();
      store.loadTypeCounts.mockClear();
      buttons[0].click();
      await vi.waitFor(() => expect(openLauncher).toHaveBeenCalledTimes(1));
      await fixture.whenStable();
      expect(store.loadTypeCounts).not.toHaveBeenCalled();
      expect(store.reloadPhotos).not.toHaveBeenCalled();
    });

    it('renders no scan button anywhere when the user may not launch a scan', () => {
      expect(render(false).buttons).toHaveLength(0);
    });
  });

  ;


  describe('lockEdition', () => {
    it('leaves a page the route table flags data.edition, and only those', async () => {
      const config = [{ path: 'compare', data: { edition: true } }, { path: 'stats' }];
      const lock = async (url: string) => {
        TestBed.resetTestingModule();
        const { app, mockRouter } = createApp(url, [
          { provide: Router, useValue: { url, events: NEVER, navigate: vi.fn(), config } },
          { provide: AuthService, useValue: { identity: () => '0|', isAuthenticated: vi.fn(() => true), checkStatus: vi.fn(), dropEdition: vi.fn(() => Promise.resolve()) } },
        ]);
        await (app as any).lockEdition();
        return { app, router: TestBed.inject(Router) as unknown as { navigate: ReturnType<typeof vi.fn> }, mockRouter };
      };
      expect((await lock('/compare?x=1')).router.navigate).toHaveBeenCalledWith(['/']);
      expect((await lock('/stats')).router.navigate).not.toHaveBeenCalled();
    });
  });

  describe('header edition underline and user menu', () => {
    const historyRef = (restored: boolean) => ({
      componentInstance: { whenSettled: () => Promise.resolve(), wasRestored: () => restored }, afterClosed: () => of(undefined),
    });
    function render(edition: boolean, multiUser = false, superadmin = false) {
      TestBed.configureTestingModule({
        providers: [
          provideRouter([]),
          { provide: GalleryStore, useValue: { filters: signal({ ...DEFAULT_FILTERS }), persons: signal([]), selectionCount: signal(0), config: signal(null), types: signal([]), total: signal(0), photoTotal: signal(0), loadTypeCounts: vi.fn(() => Promise.resolve()), loadConfig: vi.fn(), viewFilterParams: signal({}), activeFilterCount: signal(0), filterDrawerOpen: signal(false), hiddenFiltersStash: signal(null), collapseStacks: signal(true), toggleStackCollapse: vi.fn(), slideshowActive: signal(false), pinnedPaths: signal<string[] | null>(null), setFilterDrawerOpen: vi.fn(), updateFilter: vi.fn(), resetFilters: vi.fn(), restoreHidden: vi.fn(), showAllHidden: vi.fn(), reviewProgressVisible: signal(true), setReviewProgressVisible: vi.fn(), notifyOrganizationRestored: vi.fn() } },
          { provide: ScanService, useValue: { canLaunch: signal(false), openLauncher: vi.fn() } },
          { provide: AuthService, useValue: { identity: () => '0|', isAuthenticated: signal(true), isReadOnlyInstall: signal(false), features: signal({}), user: signal(null), logout: vi.fn(), isEdition: signal(edition), status: signal(null), editionPasswordRequired: signal(false), isMultiUser: signal(multiUser), isSuperadmin: signal(superadmin), isInstallAdmin: signal(multiUser ? superadmin : edition), loginPasswordRequired: signal(false), checkStatus: vi.fn(() => Promise.resolve()) } },
          { provide: I18nService, useValue: { load: vi.fn(() => Promise.resolve()), loadLanguages: vi.fn(() => Promise.resolve()), languages: signal([]), t: vi.fn((k: string) => k), translations: signal({}) } },
          { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
          { provide: CompareFiltersService, useValue: { selectedCategory: signal('') } },
          { provide: MatDialog, useValue: { open: vi.fn(() => historyRef(false)) } },
          { provide: ApiService, useValue: { get: vi.fn(() => NEVER), post: vi.fn(() => NEVER) } },
          { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], setTheme: vi.fn(), toggleDarkMode: vi.fn(), accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
        ],
      });
      const fixture = TestBed.createComponent(App);
      fixture.detectChanges();
      return { fixture, root: fixture.nativeElement as HTMLElement };
    }

    const openUserMenu = (fixture: ReturnType<typeof render>['fixture'], root: HTMLElement) => {
      root.querySelector<HTMLButtonElement>(`button[aria-label="${I18N.auth.user_menu}"]`)!.click();
      fixture.detectChanges();
      return Array.from(document.querySelectorAll<HTMLButtonElement>('.mat-mdc-menu-panel button[mat-menu-item]'));
    };

    afterEach(() => document.querySelectorAll('.cdk-overlay-container').forEach(el => el.replaceChildren()));

    it.each([[true], [false]])('offers Organization history in the nav exactly while edition is %s', (edition) => {
      const { root } = render(edition);
      const buttons = root.querySelectorAll(`nav button[aria-label="${I18N.organization_history.title}"]`);
      expect(buttons.length).toBe(edition ? 1 : 0);
    });

    it.each([[true], [false]])('offers labeled mobile navigation with editing destinations gated by edition %s', (edition) => {
      const { fixture, root } = render(edition);
      const trigger = root.querySelector<HTMLButtonElement>('[data-mobile-navigation]');
      expect(trigger).not.toBeNull();
      trigger!.click();
      fixture.detectChanges();
      const menu = document.querySelector('.mat-mdc-menu-panel')!;
      expect(menu.textContent).toContain(I18N.nav.persons);
      expect(menu.querySelector('a[href="/culling"]') !== null).toBe(edition);
      expect(menu.querySelector('a[href="/compare"]') !== null).toBe(edition);
      expect(menu.querySelector('a[href="/stats"]')).not.toBeNull();
    });

    it('marks the gallery workspace current across real query and album navigation', async () => {
      const { fixture, root } = render(false);
      const app = fixture.componentInstance as any;
      app.navigationWide.isDesktop = signal(true);
      app.setNavigationMode('pinned');
      const router = TestBed.inject(Router);
      router.resetConfig([{ path: '', component: NavigationFixturePage }, { path: 'album/:albumId', component: NavigationFixturePage }, { path: 'other', component: NavigationFixturePage }]);
      await router.navigateByUrl('/?search=single'); fixture.detectChanges();
      const link = root.querySelector<HTMLAnchorElement>('[data-expandable-navigation] a[href="/"]')!;
      expect(link.getAttribute('aria-current')).toBe('page');
      await router.navigateByUrl('/album/17?tag=trip'); fixture.detectChanges();
      expect(link.getAttribute('aria-current')).toBe('page');
      await router.navigateByUrl('/other'); fixture.detectChanges();
      expect(link.getAttribute('aria-current')).toBeNull();
    });

    it('restores keyboard focus across navigation owners without latching pointer focus', () => {
      const { fixture, root } = render(false);
      const app = fixture.componentInstance as any;
      app.navigationWide.isDesktop = signal(true);
      const callbacks: FrameRequestCallback[] = [];
      const frame = vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { callbacks.push(callback); return 1; });
      try {
        app.setNavigationMode('compact', new MouseEvent('click', { detail: 0 }));
        const restoreFocus = callbacks.at(-1)!;
        fixture.detectChanges();
        restoreFocus(0);
        expect(document.activeElement).toBe(root.querySelector('[data-toggle-navigation]'));
        const beforePointer = callbacks.length;
        app.setNavigationMode('hidden', new MouseEvent('click', { detail: 1 }));
        fixture.detectChanges();
        for (const callback of callbacks.slice(beforePointer)) callback(0);
        expect(document.activeElement).not.toBe(root.querySelector('[data-toggle-navigation]'));
      } finally { frame.mockRestore(); }
    });

    it('keeps only the hamburger, brand and global controls when navigation is hidden', () => {
 const {root}=render(true);
 const header=root.querySelector<HTMLElement>('header[data-workspace-navigation]')!;
 expect(header).not.toBeNull();expect(root.querySelector('mat-toolbar')).toBeNull();
 expect(header.querySelector('[data-primary-navigation]')).toBeNull();
 expect(header.querySelector('[data-toggle-navigation]')?.getAttribute('aria-haspopup')).toBe('menu');
 expect(root.querySelector('[data-expandable-navigation]')).toBeNull();
 expect(header.querySelector('button[aria-label="'+I18N.auth.user_menu+'"]')).not.toBeNull();
 header.querySelector('a[aria-label="'+I18N.nav.gallery_tooltip+'"]')!.dispatchEvent(new MouseEvent('dblclick'));
 expect(TestBed.inject(GalleryStore).resetFilters).toHaveBeenCalledOnce();
});

    it('uses one navigation surface and lets the hamburger choose hidden, compact or pinned', async () => {
 const {fixture,root}=render(true);const app=fixture.componentInstance as any;
 app.navigationWide.isDesktop=signal(true);
 const choose=async(mode:string)=>{
  root.querySelector<HTMLButtonElement>('[data-toggle-navigation]')!.click();fixture.detectChanges();await fixture.whenStable();
  const button=document.querySelector<HTMLButtonElement>('[data-navigation-mode="'+mode+'"]')!;
  expect(button).not.toBeNull();button.click();fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
 };
 await choose('compact');
 let rail=root.querySelector<HTMLElement>('[data-expandable-navigation]')!;const main=root.querySelector('main')!;
 expect(root.querySelector('header[data-workspace-navigation]')).toBeNull();
 expect(rail.querySelector('[data-pin-navigation]')).toBeNull();
 expect(rail.querySelector('button[aria-label="'+I18N.auth.user_menu+'"]')).not.toBeNull();
 expect(main.classList.contains('lg:ml-14')).toBe(true);
 rail.dispatchEvent(new Event('mouseenter'));fixture.detectChanges();
 expect(rail.classList.contains('!w-48')).toBe(true);expect(main.classList.contains('lg:ml-48')).toBe(false);
 rail.dispatchEvent(new Event('mouseleave'));rail.dispatchEvent(new FocusEvent('focusout',{relatedTarget:document.body}));fixture.detectChanges();
 expect(rail.classList.contains('!w-48')).toBe(false);
 await choose('pinned');rail=root.querySelector('[data-expandable-navigation]')!;
 expect(main.classList.contains('lg:ml-48')).toBe(true);expect(rail.classList.contains('!w-48')).toBe(true);
 await choose('hidden');expect(root.querySelector('[data-expandable-navigation]')).toBeNull();
 expect(root.querySelector('header[data-workspace-navigation]')).not.toBeNull();expect(main.classList.contains('lg:ml-48')).toBe(false);
});

    it('removes editing destinations immediately when edition access is lost', async () => {
      const { fixture, root } = render(true);
      const auth = TestBed.inject(AuthService) as unknown as { isEdition: ReturnType<typeof signal<boolean>> };
      root.querySelector<HTMLButtonElement>('[data-toggle-navigation]')!.click();
      fixture.detectChanges(); await fixture.whenStable();
      expect(document.querySelector('.mat-mdc-menu-panel a[href="/culling"]')).not.toBeNull();
      auth.isEdition.set(false);
      fixture.detectChanges();
      expect(document.querySelector('.mat-mdc-menu-panel a[href="/culling"]')).toBeNull();
      expect(root.querySelector('[data-mobile-navigation]')).not.toBeNull();
    });

    it('removes navigation and its reserved desktop space after logout', () => {
      const { fixture, root } = render(false);
      const auth = TestBed.inject(AuthService) as unknown as { isAuthenticated: ReturnType<typeof signal<boolean>> };
      expect(root.querySelector('[data-workspace-navigation]')).not.toBeNull();
      auth.isAuthenticated.set(false);
      fixture.detectChanges();
      expect(root.querySelector('[data-workspace-navigation]')).toBeNull();
      expect(root.firstElementChild!.classList.contains('lg:pl-48')).toBe(false);
    });

    it.each([['kept', 1], ['lost', 0]])('opens the history dialog after the lazy load only while edition is %s', async (state, opens) => {
      const { fixture } = render(true);
      const app = fixture.componentInstance as unknown as { openOrganizationHistory: () => Promise<void> };
      const dialog = TestBed.inject(MatDialog);
      const auth = TestBed.inject(AuthService) as unknown as { isEdition: ReturnType<typeof signal<boolean>> };
      const opening = app.openOrganizationHistory();
      if (state === 'lost') auth.isEdition.set(false);
      await opening;
      expect(dialog.open).toHaveBeenCalledTimes(opens);
    });

    it.each([[true, 1], [false, 0]])('tells open views to refetch after the history dialog closes when restored is %s', async (restored, notifies) => {
      const { root } = render(true);
      const dialog = TestBed.inject(MatDialog) as unknown as { open: ReturnType<typeof vi.fn> };
      dialog.open.mockReturnValue(historyRef(restored));
      root.querySelector<HTMLButtonElement>(`nav button[aria-label="${I18N.organization_history.title}"]`)!.click();
      await vi.waitFor(() => expect(dialog.open).toHaveBeenCalledTimes(1));
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(TestBed.inject(GalleryStore).notifyOrganizationRestored).toHaveBeenCalledTimes(notifies);
    });

    it.each([[true], [false]])('draws the theme-accent 2px underline exactly while edition is %s', (edition) => {
      const { root } = render(edition);
      const bar = root.querySelector<HTMLElement>('[data-workspace-navigation]')!;
      expect(bar.style.borderBottomColor).toBe(edition ? 'var(--facet-accent)' : '');
      expect(bar.classList.contains('!border-b-2')).toBe(edition);
    });

    it('lists Card actions, Keyboard shortcuts, then the shell-level Help, and calls their handlers', () => {
      const { fixture, root } = render(false);
      const app = fixture.componentInstance as unknown as { openCardActionsDialog: () => void; openKeymapDialog: () => void; openHelpDialog: () => void };
      const openCardActions = vi.spyOn(app, 'openCardActionsDialog').mockImplementation(() => undefined);
      const openKeymap = vi.spyOn(app, 'openKeymapDialog').mockImplementation(() => undefined);
      const openHelp = vi.spyOn(app, 'openHelpDialog').mockImplementation(() => undefined);
      const items = openUserMenu(fixture, root);
      const labels = items.map(i => i.textContent!.replace(/\s+/g, ' ').trim());
      expect(labels.at(-3)).toContain(I18N.gallery.card_actions.title);
      expect(labels.at(-2)).toContain(I18N.shortcuts.keymap_title);
      expect(labels.at(-1)).toContain(I18N.nav.help);
      // The customisation group is separated from Help by a divider.
      const content = document.querySelector('.mat-mdc-menu-panel .mat-mdc-menu-content')!;
      const children = [...content.children];
      const helpIndex = children.findIndex(c => c.tagName === 'BUTTON' && c.textContent!.includes(I18N.nav.help));
      expect(children[helpIndex - 1].tagName).toBe('MAT-DIVIDER');
      items.at(-3)!.click();
      expect(openCardActions).toHaveBeenCalledOnce();
      items.at(-2)!.click();
      expect(openKeymap).toHaveBeenCalledOnce();
      items.at(-1)!.click();
      expect(openHelp).toHaveBeenCalledOnce();
    });

    it.each([[true, false, false, true], [false, false, false, false],
      [true, true, false, false], [true, true, true, true]])(
      'limits diagnostics menu to installation administrators (%s/%s/%s)', (edition, multi, admin, visible) => {
        const { fixture, root } = render(edition, multi, admin);
        const items = openUserMenu(fixture, root);
        expect(items.some(i => i.textContent?.includes(I18N.immich_diagnostics.title))).toBe(visible);
      },
    );

    it('does not open a late diagnostics chunk after edition access is lost', async () => {
      const { fixture } = render(true);
      const app = fixture.componentInstance as unknown as { openImmichDiagnostics(): Promise<void> };
      const opening = app.openImmichDiagnostics();
      (TestBed.inject(AuthService).isEdition as ReturnType<typeof signal<boolean>>).set(false);
      await opening;
      expect(TestBed.inject(MatDialog).open).not.toHaveBeenCalled();
    });

    it('puts Logout last in the menu', () => {
      const { fixture, root } = render(false, true);
      const items = openUserMenu(fixture, root);
      expect(items.at(-1)!.textContent).toContain(I18N.auth.logout);
    });
  });
});
