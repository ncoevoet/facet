import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS } from './gallery.store';
import { buildApiParams } from './gallery-filters.util';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumService } from '../../core/services/album.service';
import { GalleryComponent } from './gallery.component';
import { ScoreClassPipe } from '../../shared/pipes/score.pipes';
import { MAX_COMPARE_PANES } from './synced-zoom.component';

describe('GalleryComponent', () => {
  let component: GalleryComponent;

   
  let mockStore: any;
  let mockApi: { thumbnailUrl: Mock };
  let mockAuth: Record<string, unknown>;
  let mockI18n: { t: Mock };
  let routeMock: { snapshot: { paramMap: { get: Mock }; queryParams: Record<string, string> } };

  beforeEach(() => {
    mockStore = {
      filters: signal<GalleryFilters>({ ...DEFAULT_FILTERS }),
      types: signal([
        { id: 'portrait', label: 'Portrait', count: 100 },
        { id: 'landscape', label: 'Landscape', count: 200 },
        { id: 'macro', label: 'Macro', count: 50 },
      ]),
      photos: signal([]),
      total: signal(0),
      loading: signal(false),
      loadError: signal(false),
      hasMore: signal(false),
      cameras: signal([]),
      lenses: signal([]),
      tags: signal([]),
      persons: signal([]),
      config: signal(null),
      activeFilterCount: signal(0),
      filterDrawerOpen: signal(false),
      currentAlbum: signal(null),
      initializing: signal(false),
      galleryMode: signal('mosaic'),
      cardWidth: signal(300),
      virtualScroll: signal(false),
      setFilterDrawerOpen: vi.fn(),
      loadConfig: vi.fn(() => Promise.resolve()),
      loadFilterOptions: vi.fn(() => Promise.resolve()),
      loadTypeCounts: vi.fn(() => Promise.resolve()),
      loadPhotos: vi.fn(() => Promise.resolve()),
      updateFilter: vi.fn(() => Promise.resolve()),
      resetFilters: vi.fn(() => Promise.resolve()),
      nextPage: vi.fn(() => Promise.resolve()),
      toggleFavorite: vi.fn(),
      toggleRejected: vi.fn(),
      selectedPaths: signal(new Set<string>()),
      selectionCount: signal(0),
      toggleSelection: vi.fn(),
      selectAllLoaded: vi.fn(),
      clearSelection: vi.fn(),
      restoreSelection: vi.fn(),
      restoreSnapshot: vi.fn(() => Promise.resolve()),
      viewSnapshot: signal(null),
      filterKey: vi.fn((f?: GalleryFilters) => JSON.stringify(buildApiParams(f ?? mockStore.filters(), false))),
      hiddenSummary: signal({ total: 0, blinks: 0, bursts: 0, duplicates: 0 }),
      updateFilters: vi.fn(() => Promise.resolve()),
      setRating: vi.fn(),
      batchFavorite: vi.fn(() => Promise.resolve(new Map())),
      batchReject: vi.fn(() => Promise.resolve(new Map())),
      batchRating: vi.fn(() => Promise.resolve(new Map())),
    };

    mockApi = {
      thumbnailUrl: vi.fn((path: string) => `/thumbnail?path=${path}`),
    };

    mockAuth = { isEdition: vi.fn(() => false) };

    mockI18n = {
      t: vi.fn((key: string) => key),
    };

    routeMock = { snapshot: { paramMap: { get: vi.fn(() => null) }, queryParams: {} } };

    TestBed.configureTestingModule({
      providers: [
        { provide: GalleryStore, useValue: mockStore },
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), get: vi.fn(() => of({})) } },
        { provide: ActivatedRoute, useValue: routeMock },
        { provide: MatDialog, useValue: { open: vi.fn() } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
      ],
    });
    component = TestBed.runInInjectionContext(() => new GalleryComponent());
  });

  describe('ScoreClassPipe', () => {
    let pipe: ScoreClassPipe;

    beforeEach(() => {
      pipe = new ScoreClassPipe();
    });

    it('should return green class for score >= 8 (no config)', () => {
      expect(pipe.transform(8, null)).toBe('bg-green-600 text-white');
      expect(pipe.transform(9.5, null)).toBe('bg-green-600 text-white');
      expect(pipe.transform(10, null)).toBe('bg-green-600 text-white');
    });

    it('should return yellow class for score >= 6 and < 8 (no config)', () => {
      expect(pipe.transform(6, null)).toBe('bg-yellow-600 text-white');
      expect(pipe.transform(7.9, null)).toBe('bg-yellow-600 text-white');
    });

    it('should return orange class for score >= 4 and < 6 (no config)', () => {
      expect(pipe.transform(4, null)).toBe('bg-orange-600 text-white');
      expect(pipe.transform(5.9, null)).toBe('bg-orange-600 text-white');
    });

    it('should return red class for score < 4 (no config)', () => {
      expect(pipe.transform(3.9, null)).toBe('bg-red-600 text-white');
      expect(pipe.transform(0, null)).toBe('bg-red-600 text-white');
      expect(pipe.transform(1, null)).toBe('bg-red-600 text-white');
    });

    it('should use config thresholds when provided', () => {
      const config = { quality_thresholds: { excellent: 9, great: 7, good: 5, best: 10 } };
      expect(pipe.transform(9, config)).toBe('bg-green-600 text-white');
      expect(pipe.transform(7, config)).toBe('bg-yellow-600 text-white');
      expect(pipe.transform(5, config)).toBe('bg-orange-600 text-white');
      expect(pipe.transform(4, config)).toBe('bg-red-600 text-white');
    });
  });

  describe('keyboard rate-and-advance (onGridKeydown)', () => {
    function keyEvent(key: string, target: Partial<HTMLElement> | null = null): KeyboardEvent {
      const ev = new KeyboardEvent('keydown', { key });
      Object.defineProperty(ev, 'target', { value: target, configurable: true });
      return ev;
    }

    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(0);
    });

    function fire(ev: KeyboardEvent) {
      (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
    }

    function activeIndex(): number {
      return (component as unknown as { activeIndex(): number }).activeIndex();
    }

    it('sets the star rating and advances on digit keys', () => {
      fire(keyEvent('3'));
      expect(mockStore.setRating).toHaveBeenCalledWith('/a.jpg', 3);
      expect(activeIndex()).toBe(1);
    });

    it('rejects and advances on X', () => {
      fire(keyEvent('x'));
      expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
      expect(activeIndex()).toBe(1);
    });

    it('toggles favorite WITHOUT advancing on F', () => {
      fire(keyEvent('f'));
      expect(mockStore.toggleFavorite).toHaveBeenCalledWith('/a.jpg');
      expect(activeIndex()).toBe(0);
    });

    it('ignores rating keys while typing in an input', () => {
      fire(keyEvent('1', { tagName: 'INPUT' } as HTMLElement));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    it('ignores rating keys for non-edition users', () => {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => false);
      fire(keyEvent('1'));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    it('ignores rating keys when the feature flag is off', () => {
      mockStore.config.set({ features: { show_rating_controls: false } });
      fire(keyEvent('1'));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });
  });

  describe('ngOnInit()', () => {
    it('should call store.loadConfig, loadFilterOptions, loadTypeCounts, and loadPhotos', async () => {
      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadFilterOptions).toHaveBeenCalled();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('should call loadConfig before loadFilterOptions and loadTypeCounts', async () => {
      const callOrder: string[] = [];
      mockStore.loadConfig.mockImplementation(() => {
        callOrder.push('loadConfig');
        return Promise.resolve();
      });
      mockStore.loadFilterOptions.mockImplementation(() => {
        callOrder.push('loadFilterOptions');
        return Promise.resolve();
      });
      mockStore.loadTypeCounts.mockImplementation(() => {
        callOrder.push('loadTypeCounts');
        return Promise.resolve();
      });
      mockStore.loadPhotos.mockImplementation(() => {
        callOrder.push('loadPhotos');
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(callOrder.indexOf('loadConfig')).toBeLessThan(
        callOrder.indexOf('loadFilterOptions'),
      );
      expect(callOrder.indexOf('loadConfig')).toBeLessThan(
        callOrder.indexOf('loadTypeCounts'),
      );
    });

    it('should call loadPhotos before loadFilterOptions and loadTypeCounts', async () => {
      const callOrder: string[] = [];
      mockStore.loadConfig.mockImplementation(() => {
        callOrder.push('loadConfig');
        return Promise.resolve();
      });
      mockStore.loadFilterOptions.mockImplementation(() => {
        callOrder.push('loadFilterOptions');
        return Promise.resolve();
      });
      mockStore.loadTypeCounts.mockImplementation(() => {
        callOrder.push('loadTypeCounts');
        return Promise.resolve();
      });
      mockStore.loadPhotos.mockImplementation(() => {
        callOrder.push('loadPhotos');
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(callOrder.indexOf('loadPhotos')).toBeLessThan(
        callOrder.indexOf('loadFilterOptions'),
      );
      expect(callOrder.indexOf('loadPhotos')).toBeLessThan(
        callOrder.indexOf('loadTypeCounts'),
      );
    });

    it('reloads instead of restoring when the URL carries different query params (issue #70)', async () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });
      routeMock.snapshot.queryParams = {
        date_from: '2026-01-01', date_to: '2026-01-01', sort: 'date_taken', sort_direction: 'DESC',
      };

      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('restores the previous view when the URL matches the snapshot', async () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });

      await component.ngOnInit();

      expect(mockStore.loadConfig).not.toHaveBeenCalled();
      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });

    it('should show photos and stop initializing when a filter-option request never resolves', async () => {
      mockStore.loadFilterOptions.mockImplementation(() => new Promise<void>(() => {}));
      mockStore.loadPhotos.mockImplementation(() => {
        mockStore.photos.set([{ path: '/a.jpg' }]);
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(mockStore.loadPhotos).toHaveBeenCalled();
      expect(mockStore.photos()).toHaveLength(1);
      expect(mockStore.initializing()).toBe(false);
    });
  });

  describe('hidden-photos banner toggle', () => {
    it('stashes the hide flags and offers to restore them', async () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true });

      component.showAllHidden();
      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        hide_blinks: false, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false,
      });

      // The store is mocked, so mirror the write the real one would have made.
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: false, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false });
      expect(component.canRestoreHidden()).toBe(true);

      component.restoreHidden();
      expect(mockStore.updateFilters).toHaveBeenLastCalledWith({
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
    });

    it('offers no restore before Show all has been used', () => {
      expect(component.canRestoreHidden()).toBe(false);
    });

    it('withdraws the restore once a hide filter is switched back on by hand', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true });
      component.showAllHidden();
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: true, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false });
      expect(component.canRestoreHidden()).toBe(false);
    });
  });

  describe('docked details panel (tooltip_mode = panel)', () => {
    const hoverEvent = { currentTarget: null } as unknown as MouseEvent;

    /** Force the rail's width gate on, the way a >=1280px viewport would. */
    function widenForRail() {
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: true, media, addEventListener() {}, removeEventListener() {},
      }));
      (component as unknown as { railWide: { setup(): void } }).railWide.setup();
    }

    beforeEach(() => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'panel' });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('needs a wide viewport as well as the setting, not the setting alone', () => {
      expect(component['tooltipMode']()).toBe('panel');
      expect(component.panelMode()).toBe(false);
    });

    describe('with a viewport wide enough for the rail', () => {
      beforeEach(() => widenForRail());

      it('is active', () => {
        expect(component.panelMode()).toBe(true);
      });

      it('hovering a photo feeds the rail without any placement maths', () => {
        const photo = { path: '/a.jpg' } as never;
        component.showTooltip(hoverEvent, photo);
        expect(component['tooltipPhoto']()).toBe(photo);
        expect(component['tooltipX']()).toBe(0);
        expect(component['tooltipY']()).toBe(0);
      });

      it('keeps the last photo when the cursor leaves the grid', () => {
        const photo = { path: '/a.jpg' } as never;
        component.showTooltip(hoverEvent, photo);
        component.hideTooltip();
        expect(component['tooltipPhoto']()).toBe(photo);
      });

      it('yields the shared drawer to the filters while they are open', () => {
        mockStore.filterDrawerOpen.set(true);
        expect(component.detailsRailVisible()).toBe(false);
      });
    });

    it('still clears on mouse-out in hover mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      component.hideTooltip();
      expect(component['tooltipPhoto']()).toBeNull();
    });

    it('falls back to a positioned floating tooltip when the rail cannot be shown', () => {
      // Selecting the mode on a viewport too narrow for the rail used to skip
      // the placement maths and leave the floating box at a stale coordinate.
      const card = document.createElement('div');
      card.className = 'relative rounded-lg';
      document.body.appendChild(card);
      const photo = { path: '/a.jpg', image_width: 4000, image_height: 3000 } as never;
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);
      expect(component['tooltipPhoto']()).toBe(photo);
      card.remove();
    });

    it('clears on mouse-out while the rail is unavailable, like hover does', () => {
      const photo = { path: '/a.jpg' } as never;
      component['tooltipPhoto'].set(photo);
      component.hideTooltip();
      expect(component['tooltipPhoto']()).toBeNull();
    });
  });

  describe('compare selection', () => {
    const photo = (path: string) => ({ path, filename: path.slice(1) });

    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    // The dialog itself is covered by its own spec; this is the wiring — which
    // photos it is handed, in which order, and when the action is offered.
    it('is offered from two photos up to the pane limit', () => {
      const c = component as unknown as { canCompareSelection: () => boolean };
      for (const n of [0, 1]) {
        select(Array.from({ length: n }, (_, i) => `/p${i}.jpg`));
        expect(c.canCompareSelection()).toBe(false);
      }
      for (let n = 2; n <= MAX_COMPARE_PANES; n++) {
        select(Array.from({ length: n }, (_, i) => `/p${i}.jpg`));
        expect(c.canCompareSelection()).toBe(true);
      }
      select(Array.from({ length: MAX_COMPARE_PANES + 1 }, (_, i) => `/p${i}.jpg`));
      expect(c.canCompareSelection()).toBe(false);
    });

    it('hands over the grid order, not the order they were picked in', async () => {
      mockStore.photos.set(['/a.jpg', '/b.jpg', '/c.jpg'].map(photo));
      select(['/c.jpg', '/a.jpg']);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.photos.map((p: { path: string }) => p.path)).toEqual(['/a.jpg', '/c.jpg']);
    });

    it('caps the panes even if more photos are somehow selected', async () => {
      const paths = Array.from({ length: MAX_COMPARE_PANES + 2 }, (_, i) => `/p${i}.jpg`);
      mockStore.photos.set(paths.map(photo));
      select(paths);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      expect((dialog.open as Mock).mock.calls[0][1].data.photos.length).toBe(MAX_COMPARE_PANES);
    });

    it('does nothing when fewer than two selected photos are loaded', async () => {
      mockStore.photos.set([photo('/a.jpg')]);
      select(['/a.jpg', '/gone.jpg']);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      expect(dialog.open).not.toHaveBeenCalled();
    });
  });
});
