import { ComponentFixture, TestBed } from '@angular/core/testing';
import { DefaultUrlSerializer, Router, provideRouter } from '@angular/router';
import { Provider, signal, WritableSignal } from '@angular/core';
import { NEVER, Subject, of } from 'rxjs';
import { App } from './app';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS, ViewerConfig } from './features/gallery/gallery.store';
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
import { MatMenuTrigger } from '@angular/material/menu';
import { KeyboardMappingService, KEYMAP_STORAGE_KEY } from './core/services/keyboard-mapping.service';

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
    it('shows the gallery bottom bar when nothing is selected', () => {
      const { app } = createApp('/');
      expect((app as any).mobileGalleryBarVisible()).toBe(true);
    });

    it('hides the gallery bottom bar while photos are selected', () => {
      const { app, selectionCountSignal } = createApp('/');
      selectionCountSignal.set(3);
      expect((app as any).mobileGalleryBarVisible()).toBe(false);
    });

    it('hides the gallery bottom bar on an album route while photos are selected', () => {
      const { app, selectionCountSignal } = createApp('/album/12');
      selectionCountSignal.set(1);
      expect((app as any).mobileGalleryBarVisible()).toBe(false);
    });

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

  describe('activeFilterChips', () => {
    it('returns empty array when not on gallery route', () => {
      const { app, filtersSignal } = createApp('/compare');
      filtersSignal.set({ ...DEFAULT_FILTERS, tag: 'nature' });
      expect((app as any).activeFilterChips()).toEqual([]);
    });

    it('returns empty array when no active filters', () => {
      const { app } = createApp('/');
      expect((app as any).activeFilterChips()).toEqual([]);
    });

    it('produces chip for active tag filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, tag: 'nature' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'tag');
      expect(chip).toBeDefined();
      expect(chip?.value).toBe('nature');
    });

    it('produces chip for active search filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, search: 'paris' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'search');
      expect(chip?.value).toBe('paris');
    });

    it('produces chip for active camera filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, camera: 'Canon R5' });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'camera' && c.value === 'Canon R5')).toBe(true);
    });

    it('produces one chip per person in comma-separated person_id', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1,2,3' });
      const personChips = (app as any).activeFilterChips().filter((c: any) => c.id.startsWith('person_'));
      expect(personChips).toHaveLength(3);
      expect(personChips.map((c: any) => c.id)).toEqual(['person_1', 'person_2', 'person_3']);
    });

    it('uses person name when available', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([{ id: 1, name: 'Alice' }]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_1');
      expect(chip?.value).toBe('Alice');
    });

    it('falls back to #pid when person name is null', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([{ id: 2, name: null }]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '2' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_2');
      expect(chip?.value).toBe('#2');
    });

    it('falls back to #pid when person is not in persons list', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '99' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_99');
      expect(chip?.value).toBe('#99');
    });

    it('shows min–max format when both range bounds are set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '6', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('6–9');
    });

    it('shows ≥min format when only min bound is set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '7', max_score: '' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('≥7');
    });

    it('shows ≤max format when only max bound is set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '', max_score: '8' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('≤8');
    });

    it('range chip clearKeys includes both min and max keys', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '5', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.clearKeys).toEqual(['min_score', 'max_score']);
    });

    it('produces chip for favorites_only = true', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, favorites_only: true });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'favorites_only')).toBe(true);
    });

    it('does not produce chip for favorites_only = false', () => {
      const { app } = createApp('/');
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'favorites_only')).toBe(false);
    });

    it('produces chip for is_monochrome = true', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, is_monochrome: true });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'is_monochrome')).toBe(true);
    });

    it('shows the manual-face review filter only while it is active', () => {
      const { app, filtersSignal } = createApp('/');
      expect((app as any).activeFilterChips().some((chip: { id: string }) => chip.id === 'manual_faces_need_review')).toBe(false);
      filtersSignal.update(filters => ({ ...filters, manual_faces_need_review: true }));
      expect((app as any).activeFilterChips()).toContainEqual({
        id: 'manual_faces_need_review', labelKey: I18N.gallery.manual_faces_need_review,
        value: '', clearKeys: ['manual_faces_need_review'],
      });
      filtersSignal.update(filters => ({ ...filters, manual_faces_need_review: false }));
      expect((app as any).activeFilterChips().some((chip: { id: string }) => chip.id === 'manual_faces_need_review')).toBe(false);
    });

    it('topiq chip uses gallery.topiq_range (not aesthetic_range)', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_topiq: '5', max_topiq: '' });
      const topiqChip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_topiq');
      expect(topiqChip?.labelKey).toBe('gallery.topiq_range');
    });

    it('aesthetic chip uses gallery.aesthetic_range', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_aesthetic: '5', max_aesthetic: '' });
      const aestheticChip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_aesthetic');
      expect(aestheticChip?.labelKey).toBe('gallery.aesthetic_range');
    });

    it('topiq and aesthetic chips have distinct label keys', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_topiq: '5', min_aesthetic: '5', max_topiq: '', max_aesthetic: '' });
      const chips = (app as any).activeFilterChips();
      const topiq = chips.find((c: any) => c.id === 'min_topiq');
      const aesthetic = chips.find((c: any) => c.id === 'min_aesthetic');
      expect(topiq?.labelKey).not.toBe(aesthetic?.labelKey);
    });
  });

  describe('clearFilterChip', () => {
    it('clears the manual-face review flag as a boolean and preserves other filters', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, manual_faces_need_review: true, person_id: '7', min_score: '5' });
      mockStore.updateFilter.mockImplementation((key: keyof GalleryFilters, value: GalleryFilters[keyof GalleryFilters]) => {
        filtersSignal.update(filters => ({ ...filters, [key]: value }));
      });
      const chip = (app as any).activeFilterChips().find((item: { id: string }) => item.id === 'manual_faces_need_review');
      expect(chip).toBeDefined();
      (app as any).clearFilterChip(chip);
      expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('manual_faces_need_review', false);
      expect(filtersSignal()).toMatchObject({ manual_faces_need_review: false, person_id: '7', min_score: '5' });
      expect((app as any).activeFilterChips().map((item: { id: string }) => item.id)).toEqual(['person_7', 'min_score']);
    });
    it('removes one person without affecting other person ids', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1,2,3' });
      (app as any).clearFilterChip({ id: 'person_2', clearKeys: ['person_2'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('person_id', '1,3');
    });

    it('sets person_id to empty string when last person is removed', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '5' });
      (app as any).clearFilterChip({ id: 'person_5', clearKeys: ['person_5'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('person_id', '');
    });

    it('calls updateFilter with false for favorites_only', () => {
      const { app, mockStore } = createApp('/');
      (app as any).clearFilterChip({ id: 'favorites_only', clearKeys: ['favorites_only'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('favorites_only', false);
    });

    it('calls updateFilter with false for is_monochrome', () => {
      const { app, mockStore } = createApp('/');
      (app as any).clearFilterChip({ id: 'is_monochrome', clearKeys: ['is_monochrome'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('is_monochrome', false);
    });

    it('calls updateFilter with empty string for string filters', () => {
      const { app, mockStore } = createApp('/');
      (app as any).clearFilterChip({ id: 'tag', clearKeys: ['tag'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('tag', '');
    });

    it('calls updateFilter for both min and max keys of a range chip', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '5', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score')!;
      (app as any).clearFilterChip(chip);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('min_score', '');
      expect(mockStore.updateFilter).toHaveBeenCalledWith('max_score', '');
    });
  });

  describe('activeFilterChips with unavailable metrics', () => {
    it('shows a LIQE chip in default mode', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_liqe: '4' });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'min_liqe')).toBe(true);
    });

    it('skips chips for metrics the licensing policy hides', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      (mockStore.config as any).set({ unavailable_metrics: ['liqe_score', 'aesthetic_iaa'] });
      filtersSignal.set({ ...DEFAULT_FILTERS, min_liqe: '4', min_aesthetic_iaa: '5', min_score: '6' });
      const ids = (app as any).activeFilterChips().map((c: any) => c.id);
      expect(ids).toContain('min_score');
      expect(ids).not.toContain('min_liqe');
      expect(ids).not.toContain('min_aesthetic_iaa');
    });
  });

  describe('onCompareCategoryChange', () => {
    it('sets selectedCategory on compareFilters service', () => {
      const { app, compareCategorySig } = createApp('/');
      (app as any).onCompareCategoryChange('portrait');
      expect(compareCategorySig()).toBe('portrait');
    });
  });

  describe('onSortChange', () => {
    it('goes through setUserSort, the one path that remembers the sort', () => {
      const { app, mockStore } = createApp('/');
      (app as any).onSortChange('date_taken');
      expect(mockStore.setUserSort).toHaveBeenCalledExactlyOnceWith('date_taken');
      expect(mockStore.updateFilter).not.toHaveBeenCalledWith('sort', 'date_taken');
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
          { provide: AuthService, useValue: { identity: () => '0|', isAuthenticated: signal(false), isReadOnlyInstall: signal(isReadOnlyInstall), isEdition: signal(false), status: signal(null), editionPasswordRequired: signal(false), isMultiUser: signal(false), isInstallAdmin: signal(false), loginPasswordRequired: signal(false), checkStatus: vi.fn(() => Promise.resolve()) } },
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

    it('announces matching photo totals in the gallery header and exact item totals for pinned lists', () => {
      const { fixture, root, store } = render(false);
      vi.mocked(TestBed.inject(I18nService).t).mockImplementation((key, params) =>
        key === I18N.gallery.photo_count ? `${params?.['count']} photos` : key);
      store.total.set(2); store.photoTotal.set(4); fixture.detectChanges();
      expect(root.textContent).toContain('4 photos');
      store.pinnedPaths.set(['/a.jpg', '/b.jpg']); fixture.detectChanges();
      expect(root.textContent).toContain('2 photos');
    });

    it('renders one desktop button just before the account menu, in the tonal colour', () => {
      const { buttons } = render(true);
      const desktop = buttons.filter((b) => b.classList.contains('lg:!inline-flex'));
      expect(desktop).toHaveLength(1);
      expect(desktop[0].nextElementSibling?.getAttribute('aria-label')).toBe(I18N.auth.user_menu);
      expect(desktop[0].classList.contains('!hidden')).toBe(true);
      for (const cls of TONAL) expect(desktop[0].classList.contains(cls)).toBe(true);
    });

    it('renders the mobile-bar copy pushed to the far right of the bar', () => {
      const { buttons } = render(true);
      const mobile = buttons.filter((b) => !b.classList.contains('lg:!inline-flex'));
      expect(mobile).toHaveLength(1);
      expect(mobile[0].nextElementSibling).toBeNull();
      expect(mobile[0].previousElementSibling?.getAttribute('aria-label')).toBe(I18N.slideshow.start);
      expect(mobile[0].classList.contains('ml-auto')).toBe(true);
      expect(mobile[0].closest('.lg\\:hidden')).not.toBeNull();
      for (const cls of TONAL) expect(mobile[0].classList.contains(cls)).toBe(true);
    });

    it('labels the button with the scan action (tooltip message and aria-label)', () => {
      const { fixture, buttons } = render(true);
      expect(buttons.length).toBe(2);
      const tooltips = fixture.debugElement.queryAll(By.directive(MatTooltip))
        .filter((d) => buttons.includes(d.nativeElement as HTMLButtonElement));
      expect(tooltips).toHaveLength(2);
      for (const d of tooltips) expect(d.injector.get(MatTooltip).message).toBe(I18N.gallery.scan_action);
      for (const b of buttons) {
        expect(b.getAttribute('aria-label')).toBe(I18N.gallery.scan_action);
        expect(b.textContent).toContain('add_photo_alternate');
      }
    });

    it('opens the launcher from the mobile-bar copy too', async () => {
      const { buttons, store, openLauncher } = render(true, true);
      const mobile = buttons.find((b) => !b.classList.contains('lg:!inline-flex'));
      mobile?.click();
      await vi.waitFor(() => expect(store.reloadPhotos).toHaveBeenCalledTimes(1));
      expect(openLauncher).toHaveBeenCalledTimes(1);
    });

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

  describe('filter bar while an assistant-pinned list is shown', () => {
    function render(config: { features?: { show_my_taste?: boolean }; sort_options_grouped?: ViewerConfig['sort_options_grouped'] } | null = null) {
      const store = {
        filters: signal({ ...DEFAULT_FILTERS }), persons: signal([]), selectionCount: signal(0), config: signal(config),
        types: signal([]), total: signal(0), photoTotal: signal(0), loadTypeCounts: vi.fn(() => Promise.resolve()), reloadPhotos: vi.fn(), loadConfig: vi.fn(),
        viewFilterParams: signal({}), activeFilterCount: signal(0), filterDrawerOpen: signal(true), hiddenFiltersStash: signal(null),
        reviewProgressVisible: signal(true), setReviewProgressVisible: vi.fn(),
        collapseStacks: signal(true), toggleStackCollapse: vi.fn(),
        slideshowActive: signal(false), pinnedPaths: signal<string[] | null>(null), setFilterDrawerOpen: vi.fn(), updateFilter: vi.fn(),
        setUserSort: vi.fn(() => Promise.resolve()), resetFilters: vi.fn(), restoreHidden: vi.fn(), showAllHidden: vi.fn(),
      };
      TestBed.configureTestingModule({
        providers: [
          provideRouter([]),
          { provide: GalleryStore, useValue: store },
          { provide: ScanService, useValue: { canLaunch: signal(true), openLauncher: vi.fn() } },
          { provide: AuthService, useValue: { identity: () => '0|', isAuthenticated: signal(true), isReadOnlyInstall: signal(false), features: signal({}), user: signal(null), logout: vi.fn(), isEdition: signal(false), status: signal(null), editionPasswordRequired: signal(false), isMultiUser: signal(false), isInstallAdmin: signal(false), loginPasswordRequired: signal(false), checkStatus: vi.fn(() => Promise.resolve()) } },
          { provide: I18nService, useValue: { load: vi.fn(() => Promise.resolve()), loadLanguages: vi.fn(() => Promise.resolve()), languages: signal([]), t: vi.fn((k: string, vars?: Record<string, string | number>) => vars ? `${k}(${Object.values(vars).join(',')})` : k), translations: signal({}) } },
          { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
          { provide: CompareFiltersService, useValue: { selectedCategory: signal('') } },
          { provide: MatDialog, useValue: { open: vi.fn() } },
          { provide: ApiService, useValue: { get: vi.fn(() => NEVER), post: vi.fn(() => NEVER) } },
          { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], setTheme: vi.fn(), toggleDarkMode: vi.fn(), accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
        ],
      });
      const fixture = TestBed.createComponent(App);
      fixture.detectChanges();
      return { fixture, root: fixture.nativeElement as HTMLElement, store };
    }

    const sortButtons = (root: HTMLElement) => Array.from(root.querySelectorAll<HTMLButtonElement>('button[aria-haspopup="menu"]'))
      .filter(el => el.getAttribute('aria-label')?.startsWith(`${I18N.gallery.sort_current}(`));
    const sortLabel = (key: string) => `${I18N.gallery.sort_current}(${key})`;
    const byLabel = (root: HTMLElement, key: string) => root.querySelectorAll(`button[aria-label="${key}"]`);
    const menuItems = () => Array.from(document.querySelectorAll<HTMLElement>('.mat-mdc-menu-panel [role="menuitemradio"]'));
    const iconOf = (el: Element) => el.querySelector('mat-icon')?.textContent?.trim();
    const openMenu = async (fixture: ComponentFixture<App>, button: HTMLButtonElement) => {
      button.click();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
    };

    it('offers stack expansion in the mobile bar to read-only users and hides it for exact pinned lists', () => {
      const { fixture, root, store } = render();
      const button = root.querySelector<HTMLButtonElement>('[data-stack-collapse-mobile]');
      expect(button).not.toBeNull();
      expect(button?.closest('.lg\\:hidden')).not.toBeNull();
      expect(button?.getAttribute('aria-label')).toBe(I18N.stacks.expand_all);
      expect(button?.hasAttribute('aria-pressed')).toBe(false);
      button?.click();
      expect(store.toggleStackCollapse).toHaveBeenCalledOnce();
      store.collapseStacks.set(false); fixture.detectChanges();
      expect(button?.getAttribute('aria-label')).toBe(I18N.stacks.collapse);
      expect(button?.hasAttribute('aria-pressed')).toBe(false);
      store.pinnedPaths.set(['/a.jpg']); fixture.detectChanges();
      expect(root.querySelector('[data-stack-collapse-mobile]')).toBeNull();
      store.pinnedPaths.set(null); fixture.detectChanges();
      expect(root.querySelector('[data-stack-collapse-mobile]')).not.toBeNull();
    });

    it('shows the sort button, sort direction and filter toggle (header and mobile bar) otherwise', () => {
      const { root } = render();
      expect(sortButtons(root)).toHaveLength(2);
      expect(byLabel(root, I18N.gallery.sort_desc)).toHaveLength(2);
      expect(byLabel(root, I18N.gallery.filters)).toHaveLength(1);
      expect(byLabel(root, I18N.ui.buttons.filters)).toHaveLength(1);
      expect(byLabel(root, I18N.ui.filters.search)).toHaveLength(1);
    });

    it('puts the direction toggle, then the filter toggle, right after the sort button in both layouts', () => {
      const { root } = render();
      const [desktop, mobile] = sortButtons(root);
      for (const [button, filtersLabel] of [[desktop, I18N.gallery.filters], [mobile, I18N.ui.buttons.filters]] as const) {
        expect(button.nextElementSibling?.getAttribute('aria-label')).toBe(I18N.gallery.sort_desc);
        expect(button.nextElementSibling?.nextElementSibling?.getAttribute('aria-label')).toBe(filtersLabel);
      }
    });

    it('shows the current sort icon and labels the button "Sort by: <current label>"', () => {
      const { fixture, root, store } = render();
      for (const button of sortButtons(root)) {
        expect(iconOf(button)).toBe('leaderboard');
        expect(button.getAttribute('aria-label')).toBe(sortLabel(I18N.gallery.sort_aggregate));
      }
      store.filters.update(filters => ({ ...filters, sort: 'aesthetic_iaa' }));
      fixture.detectChanges();
      for (const button of sortButtons(root)) {
        expect(iconOf(button)).toBe('IAA');
        expect(button.querySelector('mat-icon')?.classList.contains('!font-sans')).toBe(true);
        expect(button.getAttribute('aria-label')).toBe(sortLabel('sort_options.aesthetic_iaa'));
      }
    });

    it.each(['constructor', 'toString', '__proto__'])('keeps an unknown %s sort label a string rather than reading Object.prototype', sort => {
      const { fixture, root, store } = render();
      store.filters.update(filters => ({ ...filters, sort }));
      fixture.detectChanges();
      for (const button of sortButtons(root)) {
        expect(button.getAttribute('aria-label')).toBe(sortLabel(`sort_options.${sort}`));
      }
    });

    it('gives current model labels the same width as their menu markers in both layouts', () => {
      const { fixture, root, store } = render();
      store.filters.update(filters => ({ ...filters, sort: 'deqa_score' }));
      fixture.detectChanges();
      for (const button of sortButtons(root)) {
        const icon = button.querySelector('mat-icon')!;
        expect(icon.textContent?.trim()).toBe('DeQA');
        expect(icon.classList.contains('!w-8')).toBe(true);
        expect(icon.classList.contains('text-center')).toBe(true);
        expect(icon.classList.contains('-mx-1')).toBe(true);
        expect(icon.getAttribute('aria-hidden')).toBe('true');
        expect(button.getAttribute('aria-label')).toBe(sortLabel('sort_options.deqa_score'));
      }
    });

    it('lists the fallback sorts with icons, marks the current one and runs the saved-sort handler on click', async () => {
      const { fixture, root, store } = render();
      await openMenu(fixture, sortButtons(root)[0]);
      const items = menuItems();
      expect(items.map(item => item.textContent?.replace(iconOf(item) ?? '', '').replace('check', '').trim())).toEqual([
        I18N.gallery.sort_aggregate, I18N.gallery.sort_aesthetic, I18N.gallery.sort_date,
      ]);
      expect(items.map(item => iconOf(item))).toEqual(['leaderboard', 'auto_awesome', 'event']);
      expect(items.map(item => item.getAttribute('aria-checked'))).toEqual(['true', 'false', 'false']);
      expect(items.map(item => !!Array.from(item.querySelectorAll('mat-icon')).find(i => i.textContent?.trim() === 'check'))).toEqual([true, false, false]);
      items[2].click();
      expect(store.setUserSort).toHaveBeenLastCalledWith('date_taken');
      fixture.detectChanges();
      await fixture.whenStable();
      expect(menuItems()).toHaveLength(0);
    });

    it('labels a sort the menu does not list with its own label, never a raw sort_options key', () => {
      const { fixture, root, store } = render();
      for (const [sort, labelKey] of [
        ['top_picks_score', I18N.photo_types.top_picks],
        ['learned_score', I18N.gallery.sort_my_taste],
        ['relevance', I18N.gallery.sort_relevance],
      ] as const) {
        store.filters.update(filters => ({ ...filters, sort }));
        fixture.detectChanges();
        for (const button of sortButtons(root)) expect(button.getAttribute('aria-label')).toBe(sortLabel(labelKey));
      }
    });

    it('moves the check to the current sort', async () => {
      const { fixture, root, store } = render();
      store.filters.update(filters => ({ ...filters, sort: 'aesthetic' }));
      fixture.detectChanges();
      await openMenu(fixture, sortButtons(root)[1]);
      expect(menuItems().map(item => item.getAttribute('aria-checked'))).toEqual(['false', 'true', 'false']);
    });

    it('does not reload when the already-current sort is picked again', async () => {
      const { fixture, root, store } = render();
      await openMenu(fixture, sortButtons(root)[0]);
      menuItems()[0].click();
      expect(store.setUserSort).not.toHaveBeenCalled();
    });

    it('lists configured groups under non-interactive headers, with conditional sorts and model labels', async () => {
      const { fixture, root, store } = render({
        features: { show_my_taste: true },
        sort_options_grouped: {
          General: [
            { column: 'date_taken', label: 'Date Taken' },
            { column: 'aesthetic_iaa', label: 'Aesthetic IAA' },
            { column: 'qrealign_score', label: 'Q-ReAlign' },
          ],
          'Face Metrics': [{ column: 'future_metric', label: 'Future metric' }],
        },
      });
      store.filters.update(filters => ({ ...filters, semanticQuery: 'sunset' }));
      fixture.detectChanges();
      await openMenu(fixture, sortButtons(root)[1]);
      const items = menuItems();
      expect(items.map(item => iconOf(item))).toEqual(['search', 'psychology', 'event', 'IAA', 'Q-R', 'sort']);
      const panel = items[0].closest('.mat-mdc-menu-panel')!;
      const groups = Array.from(panel.querySelectorAll('[role="group"]'));
      const headers = groups.map(group => document.getElementById(group.getAttribute('aria-labelledby')!)?.textContent?.trim());
      expect(headers).toEqual(['sort_groups.general', 'sort_groups.face_metrics']);
      expect(groups.map(group => group.querySelectorAll('[role="menuitemradio"]').length)).toEqual([3, 1]);
      for (const item of items) expect(item.querySelector('mat-icon')?.getAttribute('aria-hidden')).toBe('true');
      items[3].click();
      expect(store.setUserSort).toHaveBeenLastCalledWith('aesthetic_iaa');
    });

    it('offers the tooltip modes as one shared radio menu with the current mode checked', async () => {
      const { fixture, root, store } = render();
      store.filters.update(filters => ({ ...filters, tooltip_mode: 'click' }));
      fixture.detectChanges();
      const triggers = Array.from(byLabel(root, I18N.gallery.tooltip_mode.label)) as HTMLButtonElement[];
      expect(triggers).toHaveLength(2);
      const menus = fixture.debugElement.queryAll(By.directive(MatMenuTrigger))
        .filter(d => triggers.includes(d.nativeElement as HTMLButtonElement))
        .map(d => d.injector.get(MatMenuTrigger).menu);
      expect(menus[0]).toBe(menus[1]);
      await openMenu(fixture, triggers[1]);
      const items = menuItems();
      expect(items.map(item => item.getAttribute('aria-checked'))).toEqual(['false', 'true', 'false']);
      expect(items.map(item => item.textContent?.includes('check'))).toEqual([false, true, false]);
      items[2].click();
      expect(store.updateFilter).toHaveBeenCalledWith('tooltip_mode', 'off');
    });

    it('toggles the docked rail: clicking the checked 侧边面板 hands details back to hover', async () => {
      // The panel item only renders when the viewport can dock the rail (>= 1280px).
      const mqlSpy = vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
        matches: query.includes('1280'), media: query, onchange: null,
        addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false,
      } as unknown as MediaQueryList));
      try {
        const { fixture, root, store } = render();
        store.filters.update(filters => ({ ...filters, tooltip_mode: 'panel' }));
        fixture.detectChanges();
        const triggers = Array.from(byLabel(root, I18N.gallery.tooltip_mode.label)) as HTMLButtonElement[];
        await openMenu(fixture, triggers[1]);
        const panelItem = menuItems().find(i => i.textContent?.includes(I18N.gallery.tooltip_mode.panel))!;
        expect(panelItem).toBeDefined();
        panelItem.click();
        expect(store.updateFilter).toHaveBeenLastCalledWith('tooltip_mode', 'hover');
        // Selecting it while unchecked docks the rail again.
        store.filters.update(filters => ({ ...filters, tooltip_mode: 'hover' }));
        fixture.detectChanges();
        await openMenu(fixture, triggers[1]);
        menuItems().find(i => i.textContent?.includes(I18N.gallery.tooltip_mode.panel))!.click();
        expect(store.updateFilter).toHaveBeenLastCalledWith('tooltip_mode', 'panel');
      } finally {
        mqlSpy.mockRestore();
      }
    });

    it('is one shared menu for both triggers', () => {
      const { fixture, root } = render();
      const buttons = sortButtons(root);
      const menus = fixture.debugElement.queryAll(By.directive(MatMenuTrigger))
        .filter(d => buttons.includes(d.nativeElement as HTMLButtonElement))
        .map(d => d.injector.get(MatMenuTrigger).menu);
      expect(menus).toHaveLength(2);
      expect(menus[0]).toBe(menus[1]);
    });

    it('hides them all while pinned, and brings them back when the pin clears', () => {
      const { fixture, root, store } = render();
      store.pinnedPaths.set(['/a.jpg']);
      fixture.detectChanges();
      expect(sortButtons(root)).toHaveLength(0);
      expect(byLabel(root, I18N.gallery.sort_desc)).toHaveLength(0);
      expect(byLabel(root, I18N.gallery.filters)).toHaveLength(0);
      expect(byLabel(root, I18N.ui.buttons.filters)).toHaveLength(0);
      expect(byLabel(root, I18N.ui.filters.search)).toHaveLength(0);
      expect(byLabel(root, I18N.gallery.scan_action).length).toBeGreaterThan(0);
      expect(byLabel(root, I18N.slideshow.start).length).toBeGreaterThan(0);
      expect(byLabel(root, I18N.gallery.tooltip_mode.label).length).toBeGreaterThan(0);
      store.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(sortButtons(root)).toHaveLength(2);
      expect(byLabel(root, I18N.gallery.filters)).toHaveLength(1);
      expect(store.setFilterDrawerOpen).not.toHaveBeenCalled();
    });
  });


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
      expect(buttons.length).toBe(edition ? 2 : 0);
    });

    it('folds the secondary destinations into one More menu below 1680px and keeps the inline set above it', () => {
      const { root } = render(true);
      const more = root.querySelector<HTMLButtonElement>(`nav button[aria-label="${I18N.nav.more}"]`)!;
      expect(more.classList.contains('!hidden')).toBe(true);
      expect(more.classList.contains('lg:max-[1679px]:!inline-flex')).toBe(true);
      const stats = root.querySelector<HTMLElement>(`nav a[aria-label="${I18N.nav.stats}"].\\!hidden`)!;
      expect(stats.classList.contains('min-[1680px]:!inline-flex')).toBe(true);
      const persons = root.querySelector<HTMLElement>(`nav a[aria-label="${I18N.nav.persons}"].\\!hidden`)!;
      expect(persons.classList.contains('lg:!inline-flex')).toBe(true);
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
      const bar = root.querySelector<HTMLElement>('mat-toolbar')!;
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
