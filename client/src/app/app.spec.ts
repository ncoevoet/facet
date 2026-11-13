import { TestBed } from '@angular/core/testing';
import { DefaultUrlSerializer, Router, TitleStrategy, provideRouter } from '@angular/router';
import { Component, Provider, TemplateRef, signal, viewChild } from '@angular/core';
import { NEVER, Subject, of } from 'rxjs';
import { App } from './app';
import { I18nTitleStrategy } from './core/i18n-title.strategy';
import { HeaderSlotService } from './core/services/header-slot.service';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS, ViewerConfig } from './features/gallery/gallery.store';
import { AuthService, AuthStatus } from './core/services/auth.service';
import { ApiService } from './core/services/api.service';
import { I18nService } from './core/services/i18n.service';
import { ThemeService } from './core/services/theme.service';
import { CompareFiltersService } from './features/comparison/compare-filters.service';
import { StatsFiltersService } from './features/stats/stats-filters.service';
import { PersonsFiltersService } from './features/persons/persons-filters.service';
import { AlbumsFiltersService } from './features/albums/albums-filters.service';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SwUpdate } from '@angular/service-worker';
import { I18N } from './core/i18n/keys';
import { ScanService } from './core/services/scan.service';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';

import { KeyboardMappingService, KEYMAP_STORAGE_KEY } from './core/services/keyboard-mapping.service';
import { FEATURE_MARK } from './shared/pipes/mark-tone.pipe';

@Component({ selector: 'app-navigation-fixture-page', template: '' })
class NavigationFixturePage {}

@Component({ selector: 'app-header-slot-host', template: '<ng-template #slot><span>slot</span></ng-template>' })
class HeaderSlotHost {
  readonly slot = viewChild.required<TemplateRef<unknown>>('slot');
}

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
    refreshConfig: vi.fn(() => Promise.resolve()),
    viewFilterParams: viewFilterParamsSignal,
    pinnedPaths: signal<string[] | null>(null),
    galleryMode: signal('grid'),
    showAllHidden: vi.fn(),
  };

  const mockRouter = { url: routerUrl, events: NEVER, navigate: vi.fn(), parseUrl: (url: string) => new DefaultUrlSerializer().parse(url) };

  TestBed.configureTestingModule({
    providers: [
      App,
      { provide: Router, useValue: mockRouter },
      { provide: GalleryStore, useValue: mockStore },
      { provide: AuthService, useValue: { identity: () => '0|', session: () => '0|', isAuthenticated: vi.fn(() => true), checkStatus: vi.fn(() => Promise.resolve()) } },
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

    it('isGalleryRoute ignores query string', () => {
      const { app } = createApp('/?sort=aggregate&type=portrait');
      expect((app as any).isGalleryRoute()).toBe(true);
    });

    it('isCompareRoute ignores query string', () => {
      const { app } = createApp('/compare?category=portrait');
      expect((app as any).isCompareRoute()).toBe(true);
    });
  });

  describe('mobile bottom bar vs selection (issue #73)', () => {
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
            identity: () => '0|', session: () => '0|',
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
            identity: () => '0|', session: () => '0|',
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
          { provide: AuthService, useValue: { identity: () => '0|', session: () => '0|', isAuthenticated: signal(false), hasFeature: () => false, isReadOnlyInstall: signal(isReadOnlyInstall), isEdition: signal(false), status: signal(null), editionPasswordRequired: signal(false), isMultiUser: signal(false), isInstallAdmin: signal(false), loginPasswordRequired: signal(false), checkStatus: vi.fn(() => Promise.resolve()) } },
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

    function render(canLaunch: boolean, launched = true, saved: number | null = 6) {
      const canLaunchSig = signal(canLaunch);
      const openLauncher = vi.fn(() => Promise.resolve(launched));
      const reloadPhotos = vi.fn(() => Promise.resolve());
      const store = {
        filters: signal({ ...DEFAULT_FILTERS }), galleryMode: signal('grid'), persons: signal([]), selectionCount: signal(0), config: signal(null),
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
          { provide: ScanService, useValue: { canLaunch: canLaunchSig, openLauncher, status: signal({ progress: { phase: 'done', saved: saved ?? undefined } }) } },
          { provide: AuthService, useValue: { identity: () => '0|', session: () => '0|', isAuthenticated: signal(true), isReadOnlyInstall: signal(false), features: signal({}), user: signal(null), logout: vi.fn(), isEdition: signal(false), status: signal(null), editionPasswordRequired: signal(false), isMultiUser: signal(false), isInstallAdmin: signal(false), loginPasswordRequired: signal(false), checkStatus: vi.fn(() => Promise.resolve()) } },
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
    it('renders one scan button in the application bar immediately before the account menu', () => {
      const { buttons } = render(true);
      const desktop = buttons;
      expect(desktop).toHaveLength(1);
      expect(desktop[0].nextElementSibling?.getAttribute('aria-label')).toBe(I18N.auth.user_menu);
      expect(desktop[0].closest('[data-workspace-navigation]')).not.toBeNull();
      for (const cls of TONAL) expect(desktop[0].classList.contains(cls)).toBe(true);
    });
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
    it('reloads the type counts and the photos when the launcher reports a completed scan', async () => {
      const { buttons, store, openLauncher } = render(true, true);
      buttons[0].click();
      await vi.waitFor(() => expect(store.reloadPhotos).toHaveBeenCalledTimes(1));
      expect(openLauncher).toHaveBeenCalledTimes(1);
      expect(store.loadTypeCounts).toHaveBeenCalled();
    });

    it.each([[6, I18N.scan.added_plural], [1, I18N.scan.added], [0, I18N.scan.none_new]])('says what a finished scan added (%s saved)', async (saved, key) => {
      const { fixture, buttons, store } = render(true, true, saved);
      const open = vi.spyOn(fixture.debugElement.injector.get(MatSnackBar), 'open');
      const translate = vi.spyOn(fixture.debugElement.injector.get(I18nService), 't');
      buttons[0].click();
      await vi.waitFor(() => expect(store.reloadPhotos).toHaveBeenCalledTimes(1));
      expect(open).toHaveBeenCalledWith(key, '', { duration: 5000 });
      if (saved > 0) expect(translate).toHaveBeenCalledWith(key, { count: saved });
      else expect(translate).toHaveBeenCalledWith(key);
    });

    it('stays quiet when the finished job reported no count', async () => {
      const { fixture, buttons, store } = render(true, true, null);
      const open = vi.spyOn(fixture.debugElement.injector.get(MatSnackBar), 'open');
      buttons[0].click();
      await vi.waitFor(() => expect(store.reloadPhotos).toHaveBeenCalledTimes(1));
      expect(open).not.toHaveBeenCalled();
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

  describe('account configuration', () => {
    it('refreshes when another account with the same role loads through a pending status', () => {
      const alice: AuthStatus = {
        authenticated: true, multi_user: true, edition_enabled: true,
        edition_authenticated: false, edition_password_required: false,
        login_password_required: true, user_id: 'alice', user_role: 'user',
        display_name: 'Alice', features: {}, download_profiles: [],
      };
      const status = signal<AuthStatus | null>(alice);
      const { mockStore } = createApp('/', [
        { provide: AuthService, useValue: {
          identity: () => '1|alice', session: () => '1|alice', status, hasFeature: () => false, isMultiUser: () => true, isSuperadmin: () => false,
          editionPasswordRequired: () => false, loginPasswordRequired: () => true, isEdition: () => false,
        } },
      ]);
      TestBed.tick();
      expect(mockStore.refreshConfig).not.toHaveBeenCalled();

      status.set(null);
      TestBed.tick();
      expect(mockStore.refreshConfig).not.toHaveBeenCalled();
      status.set({ ...alice, user_id: 'bob', display_name: 'Bob' });
      TestBed.tick();
      expect(mockStore.refreshConfig).toHaveBeenCalledTimes(1);
    });
  });

  describe('lockEdition', () => {
    it('leaves a page the route table flags data.edition, and only those', async () => {
      const config = [{ path: 'compare', data: { edition: true } }, { path: 'stats' }];
      const lock = async (url: string) => {
        TestBed.resetTestingModule();
        const { app, mockRouter } = createApp(url, [
          { provide: Router, useValue: { url, events: NEVER, navigate: vi.fn(), config } },
          { provide: AuthService, useValue: { identity: () => '0|', session: () => '0|', isAuthenticated: vi.fn(() => true), checkStatus: vi.fn(), dropEdition: vi.fn(() => Promise.resolve(true)) } },
        ]);
        await (app as any).lockEdition();
        return { app, router: TestBed.inject(Router) as unknown as { navigate: ReturnType<typeof vi.fn> }, mockRouter };
      };
      expect((await lock('/compare?x=1')).router.navigate).toHaveBeenCalledWith(['/']);
      expect((await lock('/stats')).router.navigate).not.toHaveBeenCalled();
    });

    it('reports a failed lock without navigating away as though it succeeded', async () => {
      const router = { url: '/compare', events: NEVER, navigate: vi.fn(), config: [{ path: 'compare', data: { edition: true } }] };
      const snackBar = { open: vi.fn() };
      const { app } = createApp('/compare', [
        { provide: Router, useValue: router },
        { provide: MatSnackBar, useValue: snackBar },
        { provide: AuthService, useValue: { identity: () => '0|', session: () => '0|', isAuthenticated: vi.fn(() => true), checkStatus: vi.fn(), dropEdition: vi.fn(() => Promise.resolve(false)) } },
      ]);
      await (app as unknown as { lockEdition: () => Promise<void> }).lockEdition();
      expect(router.navigate).not.toHaveBeenCalled();
      expect(snackBar.open).toHaveBeenCalledWith(I18N.edition.lock_failed, '', { duration: 5000 });
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
          { provide: TitleStrategy, useExisting: I18nTitleStrategy },
          { provide: GalleryStore, useValue: { filters: signal({ ...DEFAULT_FILTERS }), galleryMode: signal('grid'), persons: signal([]), selectionCount: signal(0), config: signal(null), types: signal([]), total: signal(0), photoTotal: signal(0), loadTypeCounts: vi.fn(() => Promise.resolve()), loadConfig: vi.fn(), viewFilterParams: signal({}), activeFilterCount: signal(0), filterDrawerOpen: signal(false), hiddenFiltersStash: signal(null), collapseStacks: signal(true), toggleStackCollapse: vi.fn(), slideshowActive: signal(false), pinnedPaths: signal<string[] | null>(null), setFilterDrawerOpen: vi.fn(), updateFilter: vi.fn(), resetFilters: vi.fn(), restoreHidden: vi.fn(), showAllHidden: vi.fn(), reviewProgressVisible: signal(true), setReviewProgressVisible: vi.fn(), notifyOrganizationRestored: vi.fn() } },
          { provide: ScanService, useValue: { canLaunch: signal(false), openLauncher: vi.fn() } },
          { provide: AuthService, useValue: { identity: () => '0|', session: () => '0|', isAuthenticated: signal(true), isReadOnlyInstall: signal(false), features: signal({}), user: signal(null), logout: vi.fn(), isEdition: signal(edition), status: signal(null), editionPasswordRequired: signal(false), isMultiUser: signal(multiUser), isSuperadmin: signal(superadmin), isInstallAdmin: signal(multiUser ? superadmin : edition), loginPasswordRequired: signal(false), checkStatus: vi.fn(() => Promise.resolve()) } },
          { provide: I18nService, useValue: { isLoaded: () => true, load: vi.fn(() => Promise.resolve()), loadLanguages: vi.fn(() => Promise.resolve()), languages: signal([]), t: vi.fn((k: string) => k), translations: signal({}) } },
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
      const buttons = root.querySelectorAll(`header button[aria-label="${I18N.organization_history.title}"]`);
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

    it('marks the gallery tab current across real query navigation, but not on an album page', async () => {
      const { fixture, root } = render(false);
      const router = TestBed.inject(Router);
      router.resetConfig([{ path: '', component: NavigationFixturePage }, { path: 'album/:albumId', component: NavigationFixturePage }, { path: 'other', component: NavigationFixturePage }]);
      await router.navigateByUrl('/?search=single'); fixture.detectChanges();
      const link = root.querySelector<HTMLAnchorElement>('[data-destination-tabs] a[href="/"]')!;
      expect(link.getAttribute('aria-current')).toBe('page');
      await router.navigateByUrl('/album/17?tag=trip'); fixture.detectChanges();
      expect(link.getAttribute('aria-current')).toBeNull();
      await router.navigateByUrl('/other'); fixture.detectChanges();
      expect(link.getAttribute('aria-current')).toBeNull();
    });

    it('fits all destinations, overflows only the tail, and remeasures changed label widths', async () => {
      let available = 600;
      let labelWidth = 100;
      const callbacks: (() => void)[] = [];
      const disconnect = vi.fn();
      const originalRect = HTMLElement.prototype.getBoundingClientRect;
      const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
        const width = this.matches('[data-navigation-space]') ? available
          : this.matches('[data-navigation-measure]') ? labelWidth
          : this.matches('[data-more-measure]') ? 60 : null;
        return width === null ? originalRect.call(this) : new DOMRect(0, 0, width, 48);
      });
      vi.stubGlobal('ResizeObserver', class {
        constructor(callback: () => void) { callbacks.push(callback); }
        observe() {} disconnect = disconnect;
      });
      const { fixture, root } = render(true);
      try {
        await fixture.whenStable(); fixture.detectChanges();
        const tabs = () => root.querySelector('[data-destination-tabs]')!;
        expect(tabs().querySelectorAll('a').length).toBe(5);
        expect(root.querySelector('[data-more-destinations]')).toBeNull();
        available = 350; callbacks.forEach(callback => callback()); fixture.detectChanges();
        expect(tabs().querySelectorAll('a').length).toBe(2);
        expect(tabs().querySelector('a[href="/culling"]')).toBeNull();
        root.querySelector<HTMLButtonElement>('[data-more-destinations]')!.click();
        fixture.detectChanges(); await fixture.whenStable();
        const menu = document.querySelector('.mat-mdc-menu-panel')!;
        expect(menu.querySelector('a[href="/culling"]')).not.toBeNull();
        expect(menu.querySelector('a[href="/"]')).toBeNull();
        available = 600; callbacks.forEach(callback => callback()); fixture.detectChanges();
        expect(tabs().querySelectorAll('a').length).toBe(5);
        expect(root.querySelector('[data-more-destinations]')).toBeNull();
        labelWidth = 150; callbacks.forEach(callback => callback()); fixture.detectChanges();
        expect(tabs().querySelectorAll('a').length).toBe(3);
        expect(root.querySelector('[data-more-destinations]')).not.toBeNull();
      } finally {
        fixture.destroy(); rect.mockRestore(); vi.unstubAllGlobals();
      }
      expect(disconnect).toHaveBeenCalled();
    });

    it('opens mobile album search and Escape closes it with focus returned to the trigger', async () => {
      const { fixture, root } = render(true);
      document.body.appendChild(root);
      const router = TestBed.inject(Router);
      router.resetConfig([{ path: 'albums', component: NavigationFixturePage }]);
      await router.navigateByUrl('/albums'); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      const trigger = root.querySelector<HTMLButtonElement>(`button[aria-label="${I18N.ui.filters.search}"]`)!;
      trigger.focus(); trigger.click(); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      const input = root.querySelector<HTMLInputElement>(`input[placeholder="${I18N.albums.search}"]`)!;
      expect(input).not.toBeNull();
      expect(document.activeElement).toBe(input);
      input.value = 'Family'; input.dispatchEvent(new Event('input', { bubbles: true })); fixture.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
      fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      expect(root.querySelector(`input[placeholder="${I18N.albums.search}"]`)).toBeNull();
      expect(document.activeElement).toBe(trigger);
      expect(TestBed.inject(AlbumsFiltersService).search()).toBe('Family');
      trigger.click(); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      root.querySelector<HTMLButtonElement>(`button[aria-label="${I18N.albums.clear_search}"]`)!.click();
      fixture.detectChanges();
      expect(TestBed.inject(AlbumsFiltersService).search()).toBe('');
      fixture.destroy(); root.remove();
    });

    it('shows the album type icons in the mobile album type menu', async () => {
      const { fixture, root } = render(true);
      document.body.appendChild(root);
      const router = TestBed.inject(Router);
      router.resetConfig([{ path: 'albums', component: NavigationFixturePage }]);
      await router.navigateByUrl('/albums'); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      root.querySelector<HTMLButtonElement>(`button[aria-label="${I18N.albums.filter_type}"]`)!.click();
      fixture.detectChanges();
      const items = Array.from(document.querySelectorAll<HTMLButtonElement>('.mat-mdc-menu-panel button[mat-menu-item]'));
      expect(items.map(item => item.querySelector('mat-icon')?.textContent?.trim())).toEqual(['photo_library', 'photo_album', FEATURE_MARK]);
      fixture.destroy(); root.remove();
    });

    it('updates primary destination tabs when configured features change', () => {
      const { fixture, root } = render(false);
      const store = TestBed.inject(GalleryStore) as unknown as { config: ReturnType<typeof signal<unknown>> };
      expect(root.querySelector('[data-destination-tabs] a[href="/albums"]')).toBeNull();
      store.config.set({ features: { show_albums: true, show_timeline: true } });
      fixture.detectChanges();
      expect(root.querySelector('[data-destination-tabs] a[href="/albums"]')).not.toBeNull();
      expect(root.querySelector('[data-destination-tabs] a[href="/timeline"]')).not.toBeNull();
      expect(root.querySelector('[data-destination-tabs] a[href="/folders"]')).toBeNull();
    });

    it('removes editing destinations immediately when edition access is lost', async () => {
      const { fixture, root } = render(true);
      const auth = TestBed.inject(AuthService) as unknown as { isEdition: ReturnType<typeof signal<boolean>> };
      root.querySelector<HTMLButtonElement>('[data-mobile-navigation]')!.click();
      fixture.detectChanges(); await fixture.whenStable();
      expect(document.querySelector('.mat-mdc-menu-panel a[href="/culling"]')).not.toBeNull();
      auth.isEdition.set(false);
      fixture.detectChanges();
      expect(document.querySelector('.mat-mdc-menu-panel a[href="/culling"]')).toBeNull();
      expect(root.querySelector('[data-mobile-navigation]')).not.toBeNull();
    });

    it('names the current page in the phone header behind a constant menu icon, with no Facet mark', async () => {
      const { fixture, root } = render(true);
      const router = TestBed.inject(Router);
      router.resetConfig([
        { path: '', component: NavigationFixturePage, title: I18N.nav.gallery },
        { path: 'stats', component: NavigationFixturePage, title: I18N.stats.title },
        { path: 'album/:id', component: NavigationFixturePage },
        { path: 'merge-suggestions', component: NavigationFixturePage, title: I18N.merge_suggestions.title },
        { path: 'scenes', component: NavigationFixturePage, title: I18N.scenes.title },
        { path: '**', component: NavigationFixturePage },
      ]);
      const config = TestBed.inject(GalleryStore).config as unknown as ReturnType<typeof signal>;
      config.set({ features: { show_albums: true } });
      const header = async (url: string) => {
        await router.navigateByUrl(url); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
        return {
          icon: root.querySelector('[data-mobile-navigation] mat-icon')?.textContent?.trim(),
          brand: !!root.querySelector('[data-mobile-brand]'),
          title: root.querySelector('[data-mobile-page-title]')?.textContent?.trim() ?? null,
        };
      };
      expect(await header('/')).toEqual({ icon: 'menu', brand: false, title: I18N.nav.gallery });
      expect(await header('/stats')).toEqual({ icon: 'menu', brand: false, title: I18N.nav.stats });
      expect(await header('/album/17')).toEqual({ icon: 'menu', brand: false, title: I18N.nav.albums });
      expect(await header('/merge-suggestions')).toEqual({ icon: 'menu', brand: false, title: I18N.merge_suggestions.title });
      expect(await header('/scenes')).toEqual({ icon: 'menu', brand: false, title: I18N.scenes.title });
      config.set({ features: { show_albums: true, show_scenes: true } });
      expect(await header('/scenes')).toEqual({ icon: 'menu', brand: false, title: I18N.nav.scenes });
      expect(await header('/nowhere')).toEqual({ icon: 'menu', brand: false, title: 'Facet' });
      expect(root.querySelector('[data-mobile-navigation]')!.getAttribute('aria-label')).toBe(I18N.nav.navigation);
    });

    it('keeps the filter reset on a double-click of the phone gallery title', () => {
      const { root } = render(true);
      root.querySelector('[data-mobile-page-title]')!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      expect(TestBed.inject(GalleryStore).resetFilters).toHaveBeenCalled();
    });

    it('leaves the filters alone on a double-click of the phone title outside the gallery', async () => {
      const { fixture, root } = render(true);
      const router = TestBed.inject(Router);
      router.resetConfig([
        { path: '', component: NavigationFixturePage },
        { path: 'stats', component: NavigationFixturePage, title: I18N.stats.title },
      ]);
      await router.navigateByUrl('/stats'); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      root.querySelector('[data-mobile-page-title]')!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      expect(TestBed.inject(GalleryStore).resetFilters).not.toHaveBeenCalled();
    });

    it('lists Scenes right after Culling, as a tool, only while show_scenes is on', () => {
      const { fixture, root } = render(true);
      const store = TestBed.inject(GalleryStore).config as unknown as ReturnType<typeof signal>;
      const hrefs = () => Array.from(root.querySelectorAll<HTMLAnchorElement>('[data-destination-tabs] a')).map(a => a.getAttribute('href'));
      store.set({ features: { show_junk_sweep: true } });
      fixture.detectChanges();
      expect(hrefs()).not.toContain('/scenes');
      store.set({ features: { show_junk_sweep: true, show_scenes: true } });
      fixture.detectChanges();
      expect(hrefs().indexOf('/scenes')).toBe(hrefs().indexOf('/culling') + 1);
      const link = root.querySelector<HTMLAnchorElement>('[data-destination-tabs] a[href="/scenes"]')!;
      expect(link.classList.contains('!font-normal')).toBe(true);
      expect(link.querySelector('mat-icon')!.textContent!.trim()).toBe('movie_filter');
      expect(link.textContent).toContain(I18N.nav.scenes);
      expect(fixture.debugElement.query(By.css('[data-destination-tabs] a[href="/scenes"]')).injector.get(MatTooltip).message).toBe(I18N.nav.tooltips.scenes);
    });

    it('insets the page-actions bar and its first control 16px, with no extra margin on the control', async () => {
      const { fixture, root } = render(true);
      const router = TestBed.inject(Router);
      router.resetConfig([{ path: 'compare', component: NavigationFixturePage }]);
      await router.navigateByUrl('/compare'); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      const bar = root.querySelector<HTMLElement>('[data-page-actions]')!;
      expect(bar.classList.contains('!px-4')).toBe(true);
      expect(bar.classList.contains('!px-2')).toBe(false);
      expect(bar.querySelector('mat-form-field')!.classList.contains('ml-2')).toBe(false);
      const host = TestBed.createComponent(HeaderSlotHost);
      host.detectChanges();
      TestBed.inject(HeaderSlotService).set(host.componentInstance.slot());
      fixture.detectChanges();
      const wrapper = bar.querySelector<HTMLElement>('.overflow-x-clip')!;
      expect(wrapper.classList.contains('ml-2')).toBe(false);
    });

    describe('mobile bottom bars', () => {
      const open = async (url: string, edition = true) => {
        const view = render(edition);
        const router = TestBed.inject(Router);
        router.resetConfig([{ path: '**', component: NavigationFixturePage }]);
        await router.navigateByUrl(url); view.fixture.detectChanges(); await view.fixture.whenStable(); view.fixture.detectChanges();
        return view;
      };
      const button = (root: HTMLElement, key: string) => root.querySelector<HTMLElement>(`[aria-label="${key}"]`)!;
      const label = (root: HTMLElement, key: string) => button(root, key).querySelector('span.max-md\\:hidden')?.textContent?.trim() ?? null;

      it.each([['/albums', I18N.albums.filter_type], ['/persons', I18N.gallery.sort], ['/capsules', I18N.capsules.regenerate]])(
        'puts the %s bar on the shared 56px row', async (url, key) => {
          const { root } = await open(url);
          const row = button(root, key).parentElement!;
          for (const cls of ['flex', 'min-h-14', 'items-center', 'gap-1', 'px-2', 'py-1']) expect(row.classList.contains(cls)).toBe(true);
          expect(row.classList.contains('gap-0')).toBe(false);
          expect(root.querySelector('main')!.classList.contains('pb-15')).toBe(true);
          expect(root.querySelector('main')!.classList.contains('pb-14')).toBe(false);
        });

      it('labels the albums bar buttons from md and tells the filter and sort icons apart', async () => {
        const { root } = await open('/albums');
        expect(label(root, I18N.albums.filter_type)).toBe(I18N.albums.filter_type);
        expect(label(root, I18N.albums.sort_by)).toBe(I18N.albums.sort_by);
        expect(label(root, I18N.ui.filters.search)).toBe(I18N.ui.filters.search);
        expect(label(root, I18N.albums.create)).toBe(I18N.albums.create);
        const icon = (key: string) => button(root, key).querySelector('mat-icon')!.textContent!.trim();
        expect(icon(I18N.albums.filter_type)).not.toBe(icon(I18N.albums.sort_by));
      });

      it('labels the persons bar buttons from md, but not the two whose text is longer than 14 characters', async () => {
        const { root } = await open('/persons');
        expect(label(root, I18N.gallery.sort)).toBe(I18N.gallery.sort);
        expect(label(root, I18N.ui.filters.search)).toBe(I18N.ui.filters.search);
        expect(label(root, I18N.persons.show_hidden)).toBe(I18N.persons.show_hidden);
        expect(label(root, I18N.manage_persons.new_person)).toBe(I18N.manage_persons.new_person);
        expect(label(root, I18N.persons.merge_suggestions)).toBeNull();
      });

      it('keeps the capsules refresh button icon-only', async () => {
        const { root } = await open('/capsules');
        expect(label(root, I18N.capsules.regenerate)).toBeNull();
      });
    });

    it('removes authenticated navigation after logout', () => {
      const { fixture, root } = render(false);
      const auth = TestBed.inject(AuthService) as unknown as { isAuthenticated: ReturnType<typeof signal<boolean>> };
      expect(root.querySelector('[data-workspace-navigation]')).not.toBeNull();
      auth.isAuthenticated.set(false);
      fixture.detectChanges();
      expect(root.querySelector('[data-workspace-navigation]')).toBeNull();
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
      root.querySelector<HTMLButtonElement>(`header button[aria-label="${I18N.organization_history.title}"]`)!.click();
      await vi.waitFor(() => expect(dialog.open).toHaveBeenCalledTimes(1));
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(TestBed.inject(GalleryStore).notifyOrganizationRestored).toHaveBeenCalledTimes(notifies);
    });

    it.each([[true], [false]])('draws no edition accent underline on either header while edition is %s', (edition) => {
      const { root } = render(edition);
      const navigation = root.querySelector<HTMLElement>('[data-workspace-navigation]');
      expect(navigation).not.toBeNull();
      // The page-actions bar renders only on pages that project one; the navigation always does.
      for (const bar of [navigation!, root.querySelector<HTMLElement>('[data-page-actions]')].filter(found => found !== null)) {
        expect(bar.style.borderBottomColor).toBe('');
        expect(bar.classList.contains('!border-b-2')).toBe(false);
      }
    });

    it('makes the page scroller the containing block, so an absolutely placed sr-only label cannot stretch the document', () => {
      const { root } = render(true);
      expect(root.querySelector('main')!.classList.contains('relative')).toBe(true);
    });

    const menuLabels = (items: HTMLElement[]) => items.map(i => i.textContent!.replace(/\s+/g, ' ').trim());
    const openSubmenu = (fixture: ReturnType<typeof render>['fixture'], items: HTMLElement[], label: string) => {
      items.find(i => i.textContent!.includes(label))!.click();
      fixture.detectChanges();
      return Array.from(document.querySelectorAll<HTMLButtonElement>('.mat-mdc-menu-panel button[mat-menu-item]'));
    };

    it('orders the user menu Shortcuts, Help, Display, Jobs & diagnostics, Logout and calls the handlers', () => {
      const { fixture, root } = render(true, true, true);
      const app = fixture.componentInstance as unknown as { openKeymapDialog: () => void; openHelpDialog: () => void };
      const openKeymap = vi.spyOn(app, 'openKeymapDialog').mockImplementation(() => undefined);
      const openHelp = vi.spyOn(app, 'openHelpDialog').mockImplementation(() => undefined);
      const items = openUserMenu(fixture, root);
      const labels = menuLabels(items);
      expect(labels).toHaveLength(5);
      expect(labels[0]).toContain(I18N.shortcuts.keymap_title);
      expect(labels[1]).toContain(I18N.nav.help);
      expect(labels[2]).toContain(I18N.ui.display_menu);
      expect(labels[3]).toContain(I18N.ui.jobs_diagnostics);
      expect(labels[4]).toContain(I18N.auth.logout);
      expect(labels.some(l => l.includes(I18N.gallery.card_actions.title))).toBe(false);
      expect(labels.some(l => l.includes(I18N.gallery.review_progress.show_toggle))).toBe(false);
      items[0].click();
      expect(openKeymap).toHaveBeenCalledOnce();
      items[1].click();
      expect(openHelp).toHaveBeenCalledOnce();
    });

    it('nests language, dark mode and theme under Display', () => {
      const { fixture, root } = render(false);
      const items = openUserMenu(fixture, root);
      const sub = menuLabels(openSubmenu(fixture, items, I18N.ui.display_menu));
      expect(sub.some(l => l.includes(I18N.ui.switch_language))).toBe(true);
      expect(sub.some(l => l.includes(I18N.ui.light_mode))).toBe(true);
      expect(sub.some(l => l.includes(I18N.ui.theme))).toBe(true);
    });

    it.each([[true, false, false, true], [false, false, false, false],
      [true, true, false, false], [true, true, true, true]])(
      'limits diagnostics menu to installation administrators (%s/%s/%s)', (edition, multi, admin, visible) => {
        const { fixture, root } = render(edition, multi, admin);
        const items = openUserMenu(fixture, root);
        const hasJobs = items.some(i => i.textContent?.includes(I18N.ui.jobs_diagnostics));
        expect(hasJobs).toBe(edition || (multi && admin));
        if (!hasJobs) { expect(visible).toBe(false); return; }
        const sub = openSubmenu(fixture, items, I18N.ui.jobs_diagnostics);
        expect(sub.some(i => i.textContent?.includes(I18N.immich_diagnostics.title))).toBe(visible);
      },
    );

    it('omits Jobs & diagnostics when the user has no rights for any child', () => {
      const { fixture, root } = render(false);
      const items = openUserMenu(fixture, root);
      expect(menuLabels(items).some(l => l.includes(I18N.ui.jobs_diagnostics))).toBe(false);
    });

    it('carries a descriptive tooltip on a destination tab and the reset hint on Gallery', () => {
      const { fixture } = render(false);
      const message = (href: string) => fixture.debugElement
        .query(By.css(`[data-destination-tabs] a[href="${href}"]`)).injector.get(MatTooltip).message;
      expect(message('/persons')).toBe(I18N.nav.tooltips.persons);
      expect(message('/')).toBe(I18N.nav.gallery_tooltip);
    });

    it('marks Albums, not Gallery, current on /album/:id', async () => {
      const { fixture, root } = render(false);
      (TestBed.inject(GalleryStore).config as unknown as ReturnType<typeof signal>).set({ features: { show_albums: true } });
      const router = TestBed.inject(Router);
      router.resetConfig([{ path: '', component: NavigationFixturePage }, { path: 'album/:albumId', component: NavigationFixturePage }]);
      await router.navigateByUrl('/album/1'); fixture.detectChanges();
      expect(root.querySelector('[data-destination-tabs] a[href="/albums"]')!.getAttribute('aria-current')).toBe('page');
      expect(root.querySelector('[data-destination-tabs] a[href="/"]')!.getAttribute('aria-current')).toBeNull();
    });

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
  describe('copy version (user menu)', () => {
    afterEach(() => {
      Reflect.deleteProperty(navigator, 'clipboard');
      Reflect.deleteProperty(document, 'execCommand');
    });

    async function copy(config: Partial<ViewerConfig> | null, writeText = vi.fn(() => Promise.resolve())) {
      const open = vi.fn();
      const { app, mockStore } = createApp('/', [{ provide: MatSnackBar, useValue: { open } }]);
      // Interpolate like the real bundle ("Facet {version}"), so the copied text proves the version is in it.
      vi.mocked(TestBed.inject(I18nService).t).mockImplementation(
        (key: string, params?: Record<string, string | number>) => (params?.['version'] ? `Facet ${params['version']}` : key));
      (mockStore.config as unknown as { set(v: unknown): void }).set(config);
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
      await (app as unknown as { copyVersion(): Promise<void> }).copyVersion();
      return { write: writeText, open };
    }

    it('copies the version with the build and confirms', async () => {
      const { write, open } = await copy({ version: '1.28.0', build: 'local/win-test@cf81f0b8' });
      expect(write).toHaveBeenCalledWith('Facet 1.28.0 (local/win-test@cf81f0b8)');
      expect(open).toHaveBeenCalledWith(I18N.notifications.copied, '', { duration: 2000 });
    });

    it('copies the version alone when the server sends no build', async () => {
      const { write } = await copy({ version: '1.28.0' });
      expect(write).toHaveBeenCalledWith('Facet 1.28.0');
    });

    it('confirms nothing when neither the clipboard nor the fallback copy works', async () => {
      Object.defineProperty(document, 'execCommand', { value: vi.fn(() => false), configurable: true });
      const { open } = await copy({ version: '1.28.0' }, vi.fn(() => Promise.reject(new Error('denied'))));
      expect(document.execCommand).toHaveBeenCalledWith('copy');
      expect(open).not.toHaveBeenCalled();
    });

    it('does nothing before the config has loaded', async () => {
      const { write, open } = await copy(null);
      expect(write).not.toHaveBeenCalled();
      expect(open).not.toHaveBeenCalled();
    });
  });
});
