import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Router, ActivatedRoute } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { Album, AlbumService } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import {
  GalleryStore,
  DEFAULT_FILTERS,
  FILTER_OPTIONS_TIMEOUT_MS,
  PhotosResponse,
  ViewerConfig,
  TypeCount,
} from './gallery.store';
import { Photo } from '../../shared/models/photo.model';
import { makePhoto } from '../../../testing/photo.fixture';

function makePhotosResponse(overrides: Partial<PhotosResponse> = {}): PhotosResponse {
  return {
    photos: [makePhoto()],
    total: 1,
    page: 1,
    per_page: 64,
    total_pages: 1,
    has_more: false,
    ...overrides,
  };
}

function makeConfig(overrides: Partial<ViewerConfig> = {}): ViewerConfig {
  return {
    pagination: { default_per_page: 64 },
    defaults: {
      type: '',
      sort: 'aggregate',
      sort_direction: 'DESC',
      hide_blinks: true,
      hide_bursts: true,
      hide_duplicates: true,
      hide_brackets: true,
      hide_panoramas: true,
      hide_details: true,
      tooltip_mode: "hover",
      panel_activation: "both",
      hide_rejected: true,
      gallery_mode: 'mosaic',
    },
    display: { tags_per_photo: 5, card_width_px: 300, image_width_px: 640 },
    sort_options_grouped: null,
    features: {
      show_similar_button: false,
      show_merge_suggestions: false,
      show_rating_controls: false,
      show_semantic_search: false,
      show_albums: false,
      show_critique: false,
      show_vlm_critique: false,
      show_memories: false,
      show_captions: false,
      show_timeline: false,
      show_map: false,
      show_capsules: false,
      show_folders: false,
    },
    quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
    ...overrides,
  };
}

describe('GalleryStore', () => {
  let store: GalleryStore;
  let apiGet: Mock;
  let apiPost: Mock;
  let snackOpen: Mock;
  let routerNavigate: Mock;
  let queryParams: Record<string, string>;

  beforeEach(() => {
    apiGet = vi.fn();
    apiPost = vi.fn(() => of({}));
    snackOpen = vi.fn();
    routerNavigate = vi.fn();
    queryParams = {};

    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: apiGet, post: apiPost } },
        { provide: Router, useValue: { navigate: routerNavigate } },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParams } },
        },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });

    store = TestBed.inject(GalleryStore);
  });

  describe('initial state', () => {
    it('should have DEFAULT_FILTERS as initial filters', () => {
      expect(store.filters()).toEqual(DEFAULT_FILTERS);
    });

    it('should have empty photos array', () => {
      expect(store.photos()).toEqual([]);
    });

    it('should have total 0', () => {
      expect(store.total()).toBe(0);
    });

    it('should have loading false', () => {
      expect(store.loading()).toBe(false);
    });

    it('should have hasMore false', () => {
      expect(store.hasMore()).toBe(false);
    });

    it('should have config null', () => {
      expect(store.config()).toBeNull();
    });
  });

  describe('activeFilterCount', () => {
    it('should return 0 with default filters', () => {
      expect(store.activeFilterCount()).toBe(0);
    });

    it('should count camera filter', () => {
      store.filters.set({ ...DEFAULT_FILTERS, camera: 'Canon EOS R5' });
      expect(store.activeFilterCount()).toBe(1);
    });

    it('should count multiple active filters', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        camera: 'Canon',
        lens: '50mm',
        tag: 'landscape',
        person_id: '5',
        min_score: '7',
        search: 'sunset',
      });
      expect(store.activeFilterCount()).toBe(6);
    });

    it('should count all 13 possible filter fields', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        camera: 'Canon',
        lens: '50mm',
        tag: 'landscape',
        person_id: '5',
        min_score: '7',
        max_score: '10',
        min_aesthetic: '6',
        max_aesthetic: '9',
        min_face_quality: '5',
        max_face_quality: '10',
        min_composition: '4',
        max_composition: '10',
        search: 'sunset',
      });
      expect(store.activeFilterCount()).toBe(13);
    });

    it('should not count non-filter fields like sort', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        sort: 'date_taken',
        sort_direction: 'ASC',
        hide_blinks: false,
      });
      expect(store.activeFilterCount()).toBe(0);
    });

    it('should count type as an active filter', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        type: 'portrait',
      });
      expect(store.activeFilterCount()).toBe(1);
    });
  });

  describe('loadConfig()', () => {
    it('should fetch config and apply defaults to filters', async () => {
      const cfg = makeConfig({
        pagination: { default_per_page: 32 },
        defaults: {
          type: 'portrait',
          sort: 'date_taken',
          sort_direction: 'ASC',
          hide_blinks: false,
          hide_bursts: false,
          hide_duplicates: false,
          hide_brackets: false,
          hide_panoramas: false,
          hide_details: false,
          tooltip_mode: "hover",
          panel_activation: "both",
          hide_rejected: false,
          gallery_mode: 'mosaic',
        },
      });
      apiGet.mockReturnValue(of(cfg));

      await store.loadConfig();

      expect(apiGet).toHaveBeenCalledWith('/config');
      expect(store.config()).toEqual(cfg);
      expect(store.filters().per_page).toBe(32);
      expect(store.filters().sort).toBe('date_taken');
      expect(store.filters().sort_direction).toBe('ASC');
      expect(store.filters().type).toBe('portrait');
      expect(store.filters().hide_blinks).toBe(false);
      expect(store.filters().hide_bursts).toBe(false);
      expect(store.filters().hide_duplicates).toBe(false);
    });

    it('should overlay URL query params on top of config defaults', async () => {
      const cfg = makeConfig();
      apiGet.mockReturnValue(of(cfg));

      // Simulate URL params via the ActivatedRoute snapshot
      Object.assign(queryParams, { camera: 'Sony A7', min_score: '8' });

      await store.loadConfig();

      expect(store.filters().camera).toBe('Sony A7');
      expect(store.filters().min_score).toBe('8');
      // Config defaults still apply for non-overridden fields
      expect(store.filters().sort).toBe('aggregate');
    });

    it('should use DEFAULT_FILTERS on error', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadConfig();

      expect(store.config()).toBeNull();
      expect(store.filters()).toEqual(DEFAULT_FILTERS);
    });

    it('should apply URL query params even on config error', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      Object.assign(queryParams, { tag: 'landscape', hide_blinks: 'false' });

      await store.loadConfig();

      expect(store.filters().tag).toBe('landscape');
      expect(store.filters().hide_blinks).toBe(false);
    });
  });

  describe('loadPhotos()', () => {
    it('should set loading, fetch photos, and update state', async () => {
      const response = makePhotosResponse({
        photos: [makePhoto({ filename: 'a.jpg' }), makePhoto({ filename: 'b.jpg' })],
        total: 100,
        has_more: true,
      });
      apiGet.mockReturnValue(of(response));

      const promise = store.loadPhotos();
      expect(store.loading()).toBe(true);

      await promise;

      expect(store.loading()).toBe(false);
      expect(store.photos()).toEqual(response.photos);
      expect(store.total()).toBe(100);
      expect(store.hasMore()).toBe(true);
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ page: 1, per_page: 64 }));
    });

    it('coerces the 0/1 flag columns the API sends into real booleans', async () => {
      // The API serialises these straight out of SQLite, so the wire carries 1/0
      // while Photo declares booleans. Without the normalisation at ingest this
      // assertion sees the integers.
      apiGet.mockReturnValue(of(makePhotosResponse({
        photos: [{
          ...makePhoto({ filename: 'a.jpg' }),
          is_favorite: 1,
          is_rejected: 0,
          is_burst_lead: 1,
        } as unknown as Photo],
      })));

      await store.loadPhotos();

      const p = store.photos()[0];
      expect(p.is_favorite).toBe(true);
      expect(p.is_rejected).toBe(false);
      expect(p.is_burst_lead).toBe(true);
    });

    it('keeps a null flag null instead of turning it into false', async () => {
      // NULL means "no stored value" — the state of is_favorite/is_rejected on
      // all but a handful of rows in a real library.
      apiGet.mockReturnValue(of(makePhotosResponse({
        photos: [makePhoto({ filename: 'a.jpg', is_favorite: null, is_rejected: null })],
      })));

      await store.loadPhotos();

      expect(store.photos()[0].is_favorite).toBeNull();
      expect(store.photos()[0].is_rejected).toBeNull();
    });

    it('should surface the error and NOT restore the previous photos on failure', async () => {
      // Set initial state
      store.photos.set([makePhoto({ filename: 'existing.jpg' })]);
      store.total.set(50);
      store.hasMore.set(true);

      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadPhotos();

      expect(store.loading()).toBe(false);
      expect(store.photos()).toEqual([]);
      expect(store.total()).toBe(0);
      expect(store.hasMore()).toBe(false);
      expect(store.loadError()).toBe(true);
    });

    it('should surface the error when the similar-photos branch fails', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, similar_to: '/a.jpg' });
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledWith(
        `/similar_photos/${encodeURIComponent('/a.jpg')}`, expect.any(Object),
      );
      expect(store.photos()).toEqual([]);
      expect(store.loadError()).toBe(true);
      expect(store.loading()).toBe(false);
    });

    it('should surface the error when the semantic-search branch fails', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: 'sunset' });
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledWith('/search', expect.objectContaining({ q: 'sunset' }));
      expect(store.photos()).toEqual([]);
      expect(store.loadError()).toBe(true);
      expect(store.loading()).toBe(false);
    });

    it('should clear the error when a retried load succeeds', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      await store.loadPhotos();
      expect(store.loadError()).toBe(true);

      const response = makePhotosResponse({ photos: [makePhoto({ filename: 'retried.jpg' })], total: 1 });
      apiGet.mockReturnValue(of(response));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledTimes(2);
      expect(store.loadError()).toBe(false);
      expect(store.photos()).toEqual(response.photos);
      expect(store.total()).toBe(1);
    });

    it('should clear a previous error at the start of a new load', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      await store.loadPhotos();
      expect(store.loadError()).toBe(true);

      apiGet.mockReturnValue(NEVER);
      void store.loadPhotos();

      expect(store.loadError()).toBe(false);
      expect(store.loading()).toBe(true);
    });

    it('should ignore a superseded load failure', async () => {
      const pending = new Subject<PhotosResponse>();
      apiGet.mockReturnValueOnce(pending.asObservable());
      const stale = store.loadPhotos();

      const response = makePhotosResponse({ photos: [makePhoto({ filename: 'fresh.jpg' })], total: 1 });
      apiGet.mockReturnValue(of(response));
      await store.loadPhotos();

      pending.error(new Error('Network error'));
      await stale;

      expect(store.loadError()).toBe(false);
      expect(store.photos()).toEqual(response.photos);
      expect(store.total()).toBe(1);
      expect(store.loading()).toBe(false);
    });

    it('should pass non-empty filter values as API params', async () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        camera: 'Canon',
        tag: 'landscape',
        min_score: '7',
        hide_blinks: true,
      });
      apiGet.mockReturnValue(of(makePhotosResponse()));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledWith(
        '/photos',
        expect.objectContaining({
          camera: 'Canon',
          tag: 'landscape',
          min_score: '7',
          hide_blinks: true,
        }),
      );
    });

    it('should omit empty string filter values from API params', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));

      await store.loadPhotos();

      const params = apiGet.mock.calls[0][1];
      expect(params).not.toHaveProperty('camera');
      expect(params).not.toHaveProperty('lens');
      expect(params).not.toHaveProperty('tag');
      expect(params).not.toHaveProperty('person_id');
      expect(params).not.toHaveProperty('search');
    });
  });

  describe('fetchKeeperHints (via loadPhotos)', () => {
    it('posts the loaded photo paths to /photos/keeper_hints and patches the matching photo', async () => {
      const response = makePhotosResponse({
        photos: [makePhoto({ path: '/a.jpg', filename: 'a.jpg' }), makePhoto({ path: '/b.jpg', filename: 'b.jpg' })],
        total: 2,
      });
      apiGet.mockReturnValue(of(response));
      apiPost.mockReturnValue(of({ '/a.jpg': { has_better: true, best_path: '/b.jpg', keeper_prob: 0.4 } }));

      await store.loadPhotos();

      await vi.waitFor(() =>
        expect(apiPost).toHaveBeenCalledWith('/photos/keeper_hints', { paths: ['/a.jpg', '/b.jpg'] }),
      );
      await vi.waitFor(() =>
        expect(store.photos().find(p => p.path === '/a.jpg')?.keeper_hint).toEqual({
          has_better: true, best_path: '/b.jpg', keeper_prob: 0.4,
        }),
      );
      // Assert /b.jpg is still THERE before asserting it has no hint: with `?.`
      // a bug that dropped every unhinted photo from the store read the same as
      // "this photo correctly has no hint".
      expect(store.photos()).toHaveLength(2);
      const unhinted = store.photos().find(p => p.path === '/b.jpg');
      expect(unhinted).toBeDefined();
      expect(unhinted!.keeper_hint).toBeUndefined();
    });

    it('leaves photos untouched when the keeper-hints request fails', async () => {
      const response = makePhotosResponse({
        photos: [makePhoto({ path: '/a.jpg', filename: 'a.jpg' })],
        total: 1,
      });
      apiGet.mockReturnValue(of(response));
      apiPost.mockReturnValue(throwError(() => new Error('boom')));

      await store.loadPhotos();

      await vi.waitFor(() =>
        expect(apiPost).toHaveBeenCalledWith('/photos/keeper_hints', { paths: ['/a.jpg'] }),
      );
      expect(store.loading()).toBe(false);
      expect(store.photos()).toEqual(response.photos);
      expect(store.photos()[0].keeper_hint).toBeUndefined();
    });
  });

  describe('nextPage()', () => {
    it('should increment page and append photos', async () => {
      const existingPhotos = [makePhoto({ filename: 'a.jpg' })];
      const newPhotos = [makePhoto({ filename: 'b.jpg' })];
      store.photos.set(existingPhotos);
      store.hasMore.set(true);

      apiGet.mockReturnValue(
        of(makePhotosResponse({ photos: newPhotos, total: 2, has_more: false })),
      );

      await store.nextPage();

      expect(store.filters().page).toBe(2);
      expect(store.photos().length).toBe(2);
      expect(store.photos()[0].filename).toBe('a.jpg');
      expect(store.photos()[1].filename).toBe('b.jpg');
      expect(store.hasMore()).toBe(false);
      expect(store.loading()).toBe(false);
    });

    it('should skip when hasMore is false', async () => {
      store.hasMore.set(false);

      await store.nextPage();

      expect(apiGet).not.toHaveBeenCalled();
      expect(store.filters().page).toBe(1);
    });

    it('should skip when already loading', async () => {
      store.hasMore.set(true);
      store.loading.set(true);

      await store.nextPage();

      expect(apiGet).not.toHaveBeenCalled();
    });

    it('should revert page on error', async () => {
      store.hasMore.set(true);
      store.filters.set({ ...DEFAULT_FILTERS, page: 3 });

      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.nextPage();

      expect(store.filters().page).toBe(3);
      expect(store.loading()).toBe(false);
    });

    it('should notify on error and keep the already-loaded photos', async () => {
      const existingPhotos = [makePhoto({ filename: 'a.jpg' })];
      store.photos.set(existingPhotos);
      store.hasMore.set(true);

      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.nextPage();

      expect(snackOpen).toHaveBeenCalledWith('gallery.load_error.page_failed', '', expect.anything());
      expect(store.photos()).toEqual(existingPhotos);
      expect(store.loadError()).toBe(false);
      expect(store.hasMore()).toBe(true);
    });
  });

  describe('updateFilter()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should update a single filter and reset page to 1', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, page: 5 });

      await store.updateFilter('camera', 'Canon EOS R5');

      expect(store.filters().camera).toBe('Canon EOS R5');
      expect(store.filters().page).toBe(1);
    });

    it('should sync URL and reload photos', async () => {
      await store.updateFilter('tag', 'landscape');

      expect(routerNavigate).toHaveBeenCalledWith([], {
        queryParams: expect.objectContaining({ tag: 'landscape' }),
        replaceUrl: true,
      });
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.any(Object));
    });

    it('should clear favorites_only when hide_rejected is enabled', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: true, hide_rejected: false });

      await store.updateFilter('hide_rejected', true);

      expect(store.filters().hide_rejected).toBe(true);
      expect(store.filters().favorites_only).toBe(false);
    });

    it('should clear hide_rejected when favorites_only is enabled', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: false, hide_rejected: true });

      await store.updateFilter('favorites_only', true);

      expect(store.filters().favorites_only).toBe(true);
      expect(store.filters().hide_rejected).toBe(false);
    });

    it('should not affect the other flag when disabling hide_rejected', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, hide_rejected: true, favorites_only: false });

      await store.updateFilter('hide_rejected', false);

      expect(store.filters().hide_rejected).toBe(false);
      expect(store.filters().favorites_only).toBe(false);
    });

    it('should not affect the other flag when disabling favorites_only', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: true, hide_rejected: false });

      await store.updateFilter('favorites_only', false);

      expect(store.filters().favorites_only).toBe(false);
      expect(store.filters().hide_rejected).toBe(false);
    });
  });

  describe('updateFilterDebounced()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should update the filter and URL synchronously without an immediate reload', () => {
      store.updateFilterDebounced('min_score', '7');

      expect(store.filters().min_score).toBe('7');
      expect(store.filters().page).toBe(1);
      expect(routerNavigate).toHaveBeenCalled();
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('should coalesce rapid range updates into a single reload', async () => {
      vi.useFakeTimers();
      try {
        store.updateFilterDebounced('min_score', '5');
        store.updateFilterDebounced('min_score', '6');
        store.updateFilterDebounced('min_score', '7');
        expect(apiGet).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(300);
      } finally {
        vi.useRealTimers();
      }

      expect(apiGet).toHaveBeenCalledTimes(1);
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ min_score: '7' }));
    });

    it('should let an immediate updateFilter cancel a pending debounced reload', async () => {
      vi.useFakeTimers();
      try {
        store.updateFilterDebounced('min_score', '7');
        await store.updateFilter('camera', 'Canon');
        await vi.advanceTimersByTimeAsync(300);
      } finally {
        vi.useRealTimers();
      }

      expect(apiGet).toHaveBeenCalledTimes(1);
    });
  });

  describe('updateFilters()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should merge multiple updates and reset page to 1', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, page: 3 });

      await store.updateFilters({ camera: 'Sony', lens: '85mm', min_score: '7' });

      expect(store.filters().camera).toBe('Sony');
      expect(store.filters().lens).toBe('85mm');
      expect(store.filters().min_score).toBe('7');
      expect(store.filters().page).toBe(1);
    });

    it('should sync URL and reload photos', async () => {
      await store.updateFilters({ sort: 'date_taken', sort_direction: 'ASC' });

      expect(routerNavigate).toHaveBeenCalled();
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.any(Object));
    });

    it('should clear favorites_only when hide_rejected is enabled', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: true, hide_rejected: false });

      await store.updateFilters({ hide_rejected: true });

      expect(store.filters().hide_rejected).toBe(true);
      expect(store.filters().favorites_only).toBe(false);
    });

    it('should clear hide_rejected when favorites_only is enabled', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: false, hide_rejected: true });

      await store.updateFilters({ favorites_only: true });

      expect(store.filters().favorites_only).toBe(true);
      expect(store.filters().hide_rejected).toBe(false);
    });
  });

  describe('resetFilters()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should restore config defaults when config is loaded', async () => {
      const cfg = makeConfig({
        pagination: { default_per_page: 32 },
        defaults: {
          type: '',
          sort: 'date_taken',
          sort_direction: 'ASC',
          hide_blinks: false,
          hide_bursts: true,
          hide_duplicates: true,
          hide_brackets: true,
          hide_panoramas: true,
          hide_details: true,
          tooltip_mode: "hover",
          panel_activation: "both",
          hide_rejected: true,
          gallery_mode: 'mosaic',
        },
      });
      store.config.set(cfg);
      store.filters.set({
        ...DEFAULT_FILTERS,
        camera: 'Canon',
        min_score: '7',
        page: 5,
      });

      await store.resetFilters();

      expect(store.filters().per_page).toBe(32);
      expect(store.filters().sort).toBe('date_taken');
      expect(store.filters().sort_direction).toBe('ASC');
      expect(store.filters().hide_blinks).toBe(false);
      expect(store.filters().camera).toBe('');
      expect(store.filters().min_score).toBe('');
      expect(store.filters().page).toBe(1);
    });

    it('should use DEFAULT_FILTERS when no config is loaded', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, camera: 'Canon', page: 3 });

      await store.resetFilters();

      expect(store.filters()).toEqual(DEFAULT_FILTERS);
    });

    it('should sync URL and reload photos', async () => {
      await store.resetFilters();

      expect(routerNavigate).toHaveBeenCalled();
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.any(Object));
    });
  });

  describe('viewFilterParams', () => {
    it('projects the five hide toggles as explicit "1"/"0" strings', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: false, hide_panoramas: true,
      });

      expect(store.viewFilterParams()).toEqual({
        hide_blinks: '1', hide_bursts: '0', hide_duplicates: '1', hide_brackets: '0', hide_panoramas: '1',
      });
    });

    it('stays referentially stable across an unrelated filter change', () => {
      const before = store.viewFilterParams();
      store.filters.update(f => ({ ...f, camera: 'Canon', page: 2, sort: 'date_taken' }));
      expect(store.viewFilterParams()).toBe(before);
    });

    it('produces a new value once a hide toggle actually changes', () => {
      const before = store.viewFilterParams();
      store.filters.update(f => ({ ...f, hide_bursts: false }));
      const after = store.viewFilterParams();
      expect(after).not.toBe(before);
      expect(after.hide_bursts).toBe('0');
    });
  });

  describe('showAllHidden() / restoreHidden()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('stashes the current hide toggles and clears all five', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });

      store.showAllHidden();

      expect(store.hiddenFiltersStash()).toEqual({
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      expect(store.filters().hide_blinks).toBe(false);
      expect(store.filters().hide_bursts).toBe(false);
      expect(store.filters().hide_duplicates).toBe(false);
      expect(store.filters().hide_brackets).toBe(false);
      expect(store.filters().hide_panoramas).toBe(false);
    });

    it('restoreHidden() brings back the stashed toggles and clears the stash', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      store.showAllHidden();

      store.restoreHidden();

      expect(store.filters().hide_blinks).toBe(true);
      expect(store.filters().hide_bursts).toBe(false);
      expect(store.filters().hide_duplicates).toBe(true);
      expect(store.filters().hide_brackets).toBe(true);
      expect(store.filters().hide_panoramas).toBe(true);
      expect(store.hiddenFiltersStash()).toBeNull();
    });

    it('restoreHidden() is a no-op without a prior showAllHidden()', () => {
      const before = store.filters();
      store.restoreHidden();
      expect(store.filters()).toBe(before);
    });
  });

  describe('loadTypeCounts()', () => {
    it('should fetch and set type counts', async () => {
      const counts: TypeCount[] = [
        { id: 'portrait', label: 'Portrait', count: 100 },
        { id: 'landscape', label: 'Landscape', count: 50 },
      ];
      apiGet.mockReturnValue(of({ types: counts }));

      await store.loadTypeCounts();

      expect(apiGet).toHaveBeenCalledWith('/type_counts', {
        hide_blinks: '1', hide_bursts: '1', hide_duplicates: '1', hide_brackets: '1', hide_panoramas: '1',
      });
      expect(store.types()).toEqual(counts);
    });

    it('sends the EFFECTIVE hide-toggle state, not the config default', async () => {
      apiGet.mockReturnValue(of({ types: [] }));
      store.filters.update(f => ({ ...f, hide_bursts: false }));

      await store.loadTypeCounts();

      expect(apiGet).toHaveBeenCalledWith('/type_counts', expect.objectContaining({ hide_bursts: '0' }));
    });

    it('should set empty array on error', async () => {
      store.types.set([{ id: 'old', label: 'Old', count: 1 }]);
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadTypeCounts();

      expect(store.types()).toEqual([]);
    });

    it('should set empty array when the request never responds', async () => {
      store.types.set([{ id: 'old', label: 'Old', count: 1 }]);
      apiGet.mockReturnValue(NEVER);

      vi.useFakeTimers();
      try {
        const pending = store.loadTypeCounts();
        await vi.advanceTimersByTimeAsync(FILTER_OPTIONS_TIMEOUT_MS + 1);
        await pending;
      } finally {
        vi.useRealTimers();
      }

      expect(store.types()).toEqual([]);
    });
  });

  describe('loadFilterOptions()', () => {
    it('should load all options in parallel', async () => {
      apiGet.mockImplementation((path: string) => {
        switch (path) {
          case '/filter_options/cameras':
            return of({ cameras: [['Canon EOS R5', 50]] });
          case '/filter_options/lenses':
            return of({ lenses: [['RF 50mm', 30]] });
          case '/filter_options/tags':
            return of({ tags: [['landscape', 20]] });
          case '/filter_options/persons':
            return of({ persons: [[1, 'Alice', 15]] });
          case '/filter_options/patterns':
            return of({ patterns: [['rule_of_thirds', 40]] });
          case '/filter_options/apertures':
            return of({ apertures: [] });
          case '/filter_options/focal_lengths':
            return of({ focal_lengths: [] });
          default:
            return throwError(() => new Error(`Unexpected path: ${path}`));
        }
      });

      await store.loadFilterOptions();

      expect(store.cameras()).toEqual([{ value: 'Canon EOS R5', count: 50 }]);
      expect(store.lenses()).toEqual([{ value: 'RF 50mm', count: 30 }]);
      expect(store.tags()).toEqual([{ value: 'landscape', count: 20 }]);
      expect(store.persons()).toEqual([{ id: 1, name: 'Alice', face_count: 15 }]);
      expect(store.patterns()).toEqual([{ value: 'rule_of_thirds', count: 40 }]);
    });

    it('should use empty array for individual failures', async () => {
      apiGet.mockImplementation((path: string) => {
        if (path === '/filter_options/cameras') {
          return of({ cameras: [['Canon', 10]] });
        }
        return throwError(() => new Error('Failed'));
      });

      await store.loadFilterOptions();

      expect(store.cameras()).toEqual([{ value: 'Canon', count: 10 }]);
      expect(store.lenses()).toEqual([]);
      expect(store.tags()).toEqual([]);
      expect(store.persons()).toEqual([]);
      expect(store.patterns()).toEqual([]);
    });

    it('should time out a hung endpoint and still populate the other dropdowns', async () => {
      apiGet.mockImplementation((path: string) => {
        switch (path) {
          case '/filter_options/cameras':
            return of({ cameras: [['Canon EOS R5', 50]] });
          case '/filter_options/lenses':
            return of({ lenses: [['RF 50mm', 30]] });
          case '/filter_options/tags':
            return of({ tags: [['landscape', 20]] });
          case '/filter_options/persons':
            return of({ persons: [[1, 'Alice', 15]] });
          case '/filter_options/patterns':
            return of({ patterns: [['rule_of_thirds', 40]] });
          case '/filter_options/colors':
            return of({ temps: [['warm', 12]], hue_buckets: [['blue', 8]] });
          default:
            return NEVER;
        }
      });

      vi.useFakeTimers();
      try {
        const pending = store.loadFilterOptions();
        await vi.advanceTimersByTimeAsync(FILTER_OPTIONS_TIMEOUT_MS + 1);
        await pending;
      } finally {
        vi.useRealTimers();
      }

      expect(store.metricRanges()).toEqual({});
      expect(store.cameras()).toEqual([{ value: 'Canon EOS R5', count: 50 }]);
      expect(store.lenses()).toEqual([{ value: 'RF 50mm', count: 30 }]);
      expect(store.tags()).toEqual([{ value: 'landscape', count: 20 }]);
      expect(store.persons()).toEqual([{ id: 1, name: 'Alice', face_count: 15 }]);
      expect(store.patterns()).toEqual([{ value: 'rule_of_thirds', count: 40 }]);
      expect(store.colorTemps()).toEqual([{ value: 'warm', count: 12 }]);
      expect(store.hueBuckets()).toEqual([{ value: 'blue', count: 8 }]);
    });
  });

  describe('syncUrl (via updateFilter)', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should only include non-default params in URL', async () => {
      await store.updateFilter('camera', 'Canon');

      expect(routerNavigate).toHaveBeenCalledWith([], {
        queryParams: { camera: 'Canon' },
        replaceUrl: true,
      });
    });

    it('should include sort when it differs from config defaults', async () => {
      const cfg = makeConfig();
      store.config.set(cfg);

      await store.updateFilter('sort', 'date_taken');

      expect(routerNavigate).toHaveBeenCalledWith([], {
        queryParams: expect.objectContaining({ sort: 'date_taken' }),
        replaceUrl: true,
      });
    });

    it('should include hide_blinks when it differs from config defaults', async () => {
      const cfg = makeConfig();
      store.config.set(cfg);

      await store.updateFilter('hide_blinks', false);

      expect(routerNavigate).toHaveBeenCalledWith([], {
        queryParams: expect.objectContaining({ hide_blinks: 'false' }),
        replaceUrl: true,
      });
    });

    it('should not include hide_blinks when it matches config default', async () => {
      const cfg = makeConfig();
      store.config.set(cfg);

      await store.updateFilter('camera', 'Canon');

      const params = routerNavigate.mock.calls[0][1].queryParams;
      expect(params).not.toHaveProperty('hide_blinks');
    });
  });
});

describe('GalleryStore selection', () => {
  let store: GalleryStore;
  let apiGet: Mock;
  let apiPost: Mock;

  beforeEach(() => {
    apiGet = vi.fn(() => of(makePhotosResponse()));
    apiPost = vi.fn(() => of({}));
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: apiGet, post: apiPost } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.photos.set([
      makePhoto({ path: '/a.jpg' }),
      makePhoto({ path: '/b.jpg' }),
      makePhoto({ path: '/c.jpg' }),
      makePhoto({ path: '/d.jpg' }),
    ]);
    // Four rows on screen out of a 650-row view: the whole point of the
    // 'view' scope is that those two numbers differ.
    store.total.set(650);
  });

  it('toggles a single photo', () => {
    store.toggleSelection(store.photos()[1]);
    expect([...store.selectedPaths()]).toEqual(['/b.jpg']);
    store.toggleSelection(store.photos()[1]);
    expect(store.selectionCount()).toBe(0);
  });

  it('shift-click extends the range from the last selected index', () => {
    store.toggleSelection(store.photos()[0]);
    store.toggleSelection(store.photos()[2], { shiftKey: true } as MouseEvent);
    expect([...store.selectedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
  });

  it('selectAllLoaded selects every loaded photo as an explicit path set', () => {
    store.selectAllLoaded();
    expect(store.selectionCount()).toBe(4);
    expect(store.selectionScope()).toBe('paths');
    expect([...store.selectedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
  });

  it('selectAllLoaded is idempotent, and stays on the loaded photos', () => {
    store.selectAllLoaded();
    store.selectAllLoaded();
    expect(store.selectionCount()).toBe(4);
    expect(store.selectionScope()).toBe('paths');
  });

  it('clearSelection empties both sets, returns to path scope and resets the anchor', () => {
    store.selectWholeView();
    store.toggleSelection(store.photos()[0]);
    store.clearSelection();
    expect(store.selectionCount()).toBe(0);
    expect(store.selectionScope()).toBe('paths');
    expect(store.excludedPaths().size).toBe(0);
    store.toggleSelection(store.photos()[2], { shiftKey: true } as MouseEvent);
    expect([...store.selectedPaths()]).toEqual(['/c.jpg']);
  });

  it('restoreSelection rehydrates a saved set', () => {
    store.restoreSelection(['/a.jpg', '/d.jpg']);
    expect([...store.selectedPaths()].sort()).toEqual(['/a.jpg', '/d.jpg']);
    expect(store.selectionScope()).toBe('paths');
  });

  it('invertSelection swaps the selection for its complement', () => {
    store.toggleSelection(store.photos()[0]);
    store.toggleSelection(store.photos()[2]);
    store.invertSelection();
    expect([...store.selectedPaths()].sort()).toEqual(['/b.jpg', '/d.jpg']);
  });

  it('invertSelection twice returns the original selection', () => {
    store.toggleSelection(store.photos()[1]);
    store.invertSelection();
    store.invertSelection();
    expect([...store.selectedPaths()]).toEqual(['/b.jpg']);
  });

  it('invertSelection resets the range anchor so the next shift-click starts fresh', () => {
    store.toggleSelection(store.photos()[0]);
    store.invertSelection();
    store.toggleSelection(store.photos()[2], { shiftKey: true } as MouseEvent);
    expect([...store.selectedPaths()].sort()).toEqual(['/b.jpg', '/d.jpg']);
  });

  describe('whole-view scope', () => {
    it('select-all on an empty selection covers the view, not the loaded page', () => {
      store.selectAll();

      expect(store.selectionScope()).toBe('view');
      expect(store.selectionCount()).toBe(650);
    });

    // The whole feature: the filter the grid was already fetched with IS the
    // selection, so declaring it costs nothing.
    it('makes no request to do it', () => {
      store.selectAll();

      expect(apiGet).not.toHaveBeenCalled();
      expect(apiPost).not.toHaveBeenCalled();
    });

    // Was 'invertSelection on an empty selection selects everything', where
    // "everything" meant the four loaded rows.
    it('invertSelection on an empty selection covers the view too, still without a request', () => {
      store.invertSelection();

      expect(store.selectionScope()).toBe('view');
      expect(store.selectionCount()).toBe(650);
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('select-all over an existing view selection re-ticks what was unticked', () => {
      store.selectWholeView();
      store.toggleSelection(store.photos()[1]);

      store.selectAll();

      expect(store.selectionScope()).toBe('view');
      expect(store.excludedPaths().size).toBe(0);
      expect(store.selectionCount()).toBe(650);
    });

    it('select-all from a PARTIAL selection stays on the loaded photos', () => {
      store.toggleSelection(store.photos()[0]);

      store.selectAll();

      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(4);
    });

    it('counts the view minus what the user unticked', () => {
      store.selectWholeView();

      store.toggleSelection(store.photos()[1]);

      expect([...store.excludedPaths()]).toEqual(['/b.jpg']);
      expect(store.selectedPaths().size).toBe(0);
      expect(store.selectionCount()).toBe(649);
    });

    it('re-ticking an unticked photo puts it back', () => {
      store.selectWholeView();
      store.toggleSelection(store.photos()[1]);

      store.toggleSelection(store.photos()[1]);

      expect(store.excludedPaths().size).toBe(0);
      expect(store.selectionCount()).toBe(650);
    });

    it('shift-click unticks a whole range', () => {
      store.selectWholeView();

      store.toggleSelection(store.photos()[0]);
      store.toggleSelection(store.photos()[2], { shiftKey: true } as MouseEvent);

      expect([...store.excludedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
      expect(store.selectionCount()).toBe(647);
    });

    it('inverting it yields exactly what was unticked, with no round trip', () => {
      store.selectWholeView();
      store.toggleSelection(store.photos()[1]);

      store.invertSelection();

      expect(store.selectionScope()).toBe('paths');
      expect([...store.selectedPaths()]).toEqual(['/b.jpg']);
      expect(store.excludedPaths().size).toBe(0);
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('a filter change drops it — the view it named is gone', async () => {
      store.selectWholeView();
      apiGet.mockReturnValue(of(makePhotosResponse({ total: 12 })));

      await store.updateFilter('camera', 'Canon');

      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(0);
    });

    it('survives paging — appending a page does not change what the view IS', async () => {
      store.selectWholeView();
      store.hasMore.set(true);
      apiGet.mockReturnValue(of(makePhotosResponse({ total: 650, has_more: true })));

      await store.nextPage();

      expect(store.selectionScope()).toBe('view');
    });

    // Both rank server-side outside the gallery WHERE clause, so no filter
    // payload reproduces them. Falling back to the loaded photos beats a
    // shortcut that does nothing at all.
    it('falls back to the loaded photos under a similarity view', () => {
      store.filters.update(f => ({ ...f, similar_to: '/x.jpg' }));

      store.selectAll();

      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(4);
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('falls back to the loaded photos under a semantic search', () => {
      store.filters.update(f => ({ ...f, semanticQuery: 'sunset' }));

      store.invertSelection();

      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(4);
      expect(apiGet).not.toHaveBeenCalled();
    });
  });

  describe('resolving a whole-view selection to numbers and paths', () => {
    it('countInView asks the server rather than trusting the last page response', async () => {
      apiGet.mockReturnValue(of({ total: 650 }));

      expect(await store.countInView()).toBe(650);
      expect(apiGet).toHaveBeenCalledWith('/photos/count', expect.objectContaining({ page: '1' }));
    });

    it('pathsInView drops the unticked photos', async () => {
      store.selectWholeView();
      store.toggleSelection(store.photos()[0]);
      apiGet.mockReturnValue(of({ total: 3, paths: ['/a.jpg', '/b.jpg', '/c.jpg'] }));

      expect(await store.pathsInView()).toEqual(['/b.jpg', '/c.jpg']);
    });

    it('both refuse a view that cannot be expressed as a filter', async () => {
      store.filters.update(f => ({ ...f, similar_to: '/x.jpg' }));

      expect(await store.countInView()).toBeNull();
      expect(await store.pathsInView()).toBeNull();
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('countInView resolves null and notifies when the server request fails', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      expect(await store.countInView()).toBeNull();

      expect(apiGet).toHaveBeenCalledWith('/photos/count', expect.any(Object));
      expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
    });

    it('pathsInView resolves null and notifies when the server request fails', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      expect(await store.pathsInView()).toBeNull();

      expect(apiGet).toHaveBeenCalledWith('/photos/paths', expect.any(Object));
      expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
    });
  });
});

describe('GalleryStore batch mutations by selection scope', () => {
  let store: GalleryStore;
  let apiPost: Mock;

  beforeEach(() => {
    apiPost = vi.fn(() => of({ success: true, count: 2 }));
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: vi.fn(() => of(makePhotosResponse())), post: apiPost } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.photos.set([makePhoto({ path: '/a.jpg' }), makePhoto({ path: '/b.jpg' })]);
    store.total.set(650);
  });

  const lastBody = () => apiPost.mock.calls.at(-1)![1] as Record<string, unknown>;

  it('sends an explicit path list under path scope', async () => {
    store.selectAllLoaded();

    await store.batchFavorite(['/a.jpg', '/b.jpg']);

    expect(apiPost).toHaveBeenCalledWith('/photos/batch_favorite', { photo_paths: ['/a.jpg', '/b.jpg'] });
  });

  it('sends the filter and the exclusions under view scope, never a path list', async () => {
    store.selectWholeView();
    store.toggleSelection(store.photos()[0]);

    await store.batchReject([]);

    expect(apiPost.mock.calls.at(-1)![0]).toBe('/photos/batch_reject');
    // The server takes exactly one target form and 422s on both.
    expect(lastBody()['photo_paths']).toBeUndefined();
    expect(lastBody()['exclude']).toEqual(['/a.jpg']);
  });

  // GalleryParams types the hide toggles as `str`, so a raw JSON `true` --
  // which is what buildApiParams holds -- would 422 where 'true' parses.
  it('stringifies the filter values, exactly as the query string does', async () => {
    store.filters.update(f => ({ ...f, hide_bursts: true, camera: 'Canon' }));
    store.selectWholeView();

    await store.batchFavorite([]);

    const filters = lastBody()['filters'] as Record<string, unknown>;
    expect(filters['hide_bursts']).toBe('true');
    expect(filters['page']).toBe('1');
    expect(filters['camera']).toBe('Canon');
  });

  it('carries the rating alongside the filter', async () => {
    store.selectWholeView();

    await store.batchRating([], 4);

    expect(lastBody()['rating']).toBe(4);
    expect(lastBody()['filters']).toBeDefined();
  });

  it('patches the loaded photos optimistically under view scope', async () => {
    store.selectWholeView();
    store.toggleSelection(store.photos()[0]);

    await store.batchReject([]);

    expect(store.photos()[0].is_rejected).toBeFalsy(); // unticked
    expect(store.photos()[1].is_rejected).toBe(true);
  });

  it('reports how far the action reached versus how much the snapshot covers', async () => {
    // A "Keep top N%" selection: 5,000 paths, two of them on screen. Five
    // requests of BATCH_PATHS_PER_REQUEST, so five times whatever the server
    // says each one changed.
    const paths = ['/a.jpg', ...Array.from({ length: 4999 }, (_, i) => `/p${i}.jpg`)];

    const res = await store.batchReject(paths);

    expect(res!.targeted).toBe(5000);
    expect(res!.snapshot.size).toBe(1);
    expect(res!.count).toBe(10); // whatever the server says it changed
  });

  it('reports the whole view as targeted under view scope', async () => {
    store.selectWholeView();
    store.toggleSelection(store.photos()[0]);

    const res = await store.batchFavorite([]);

    expect(res!.targeted).toBe(649);
    expect(res!.snapshot.size).toBe(1);
  });

  // "Keep top N%" restores up to _SELECT_BOTTOM_MAX (5,000) paths, and the
  // server binds photo_paths to BATCH_PATHS_PER_REQUEST (1,000): one POST of
  // the whole selection is a 422, so the documented workflow breaks on exactly
  // the large library it exists for.
  describe('a path selection larger than the server cap', () => {
    const paths = Array.from({ length: 2500 }, (_, i) => `/p${i}.jpg`);

    const sentChunks = () => apiPost.mock.calls.map(c => (c[1] as { photo_paths: string[] }).photo_paths);

    it('splits it into one request per chunk, none over the cap', async () => {
      await store.batchReject(paths);

      const chunks = sentChunks();
      expect(chunks.map(c => c.length)).toEqual([1000, 1000, 500]);
      expect(chunks.flat()).toEqual(paths);
      expect(apiPost.mock.calls.every(c => c[0] === '/photos/batch_reject')).toBe(true);
    });

    it('sums what every chunk changed into one count', async () => {
      apiPost
        .mockReturnValueOnce(of({ count: 1000 }))
        .mockReturnValueOnce(of({ count: 1000 }))
        .mockReturnValueOnce(of({ count: 500 }));

      const res = await store.batchRating(paths, 4);

      expect(res!.count).toBe(2500);
      expect(res!.targeted).toBe(2500);
      // The rating rides along on every chunk, not just the first.
      expect(apiPost.mock.calls.every(c => (c[1] as { rating: number }).rating === 4)).toBe(true);
    });

    // The chunks that landed are the server's truth now: reverting them would
    // put the UI back to a state the database no longer holds.
    it('keeps the chunks that landed and reverts only the ones that did not', async () => {
      store.photos.set([
        makePhoto({ path: '/p0.jpg' }),     // first chunk — written
        makePhoto({ path: '/p1500.jpg' }),  // second chunk — the one that fails
        makePhoto({ path: '/p2400.jpg' }),  // third chunk — never sent
      ]);
      apiPost
        .mockReturnValueOnce(of({ count: 1000 }))
        .mockReturnValueOnce(throwError(() => new Error('Network error')));

      const res = await store.batchReject(paths);

      expect(res).toBeNull();
      expect(apiPost).toHaveBeenCalledTimes(2); // stops at the failure
      expect(store.photos()[0].is_rejected).toBe(true);
      expect(store.photos()[1].is_rejected).toBeFalsy();
      expect(store.photos()[2].is_rejected).toBeFalsy();
    });

    it('names how many photos did change instead of a blanket failure', async () => {
      apiPost
        .mockReturnValueOnce(of({ count: 1000 }))
        .mockReturnValueOnce(throwError(() => new Error('Network error')));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await store.batchReject(paths);

      expect(snackOpen).toHaveBeenCalledWith('gallery.selection.batch_partial', '', expect.anything());
      expect(snackOpen.mock.calls.some(c => c[0] === 'errors.action_failed')).toBe(false);
    });

    it('falls back to the plain failure when the very first chunk fails', async () => {
      apiPost.mockReturnValueOnce(throwError(() => new Error('Network error')));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await store.batchReject(paths);

      expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
      expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.batch_partial')).toBe(false);
    });
  });
});

describe('GalleryStore optimistic mutations', () => {
  let store: GalleryStore;
  let apiPost: Mock;
  let snackOpen: Mock;

  beforeEach(() => {
    apiPost = vi.fn(() => of({}));
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: vi.fn(), post: apiPost } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.photos.set([
      makePhoto({ path: '/a.jpg', is_favorite: false, is_rejected: false, star_rating: 3 }),
      makePhoto({ path: '/b.jpg', is_favorite: true, is_rejected: false, star_rating: null }),
    ]);
  });

  it('toggleFavorite applies the flag synchronously before the API resolves', () => {
    apiPost.mockReturnValue(of({ is_favorite: true }));
    void store.toggleFavorite('/a.jpg');
    expect(store.photos()[0].is_favorite).toBe(true);
  });

  it('toggleFavorite reverts and notifies on API error', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('boom')));
    await store.toggleFavorite('/a.jpg');
    expect(store.photos()[0].is_favorite).toBe(false);
    expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
  });

  it('toggleFavorite reconciles with server truth', async () => {
    apiPost.mockReturnValue(of({ is_favorite: false }));
    await store.toggleFavorite('/a.jpg');
    expect(store.photos()[0].is_favorite).toBe(false);
  });

  it('toggleRejected clears favorite optimistically', () => {
    apiPost.mockReturnValue(of({ is_rejected: true }));
    void store.toggleRejected('/b.jpg');
    expect(store.photos()[1].is_rejected).toBe(true);
    expect(store.photos()[1].is_favorite).toBe(false);
  });

  it('toggleRejected clears the star rating, not just is_rejected/is_favorite', () => {
    apiPost.mockReturnValue(of({ is_rejected: true, star_rating: 0 }));
    void store.toggleRejected('/a.jpg'); // starts at star_rating: 3
    expect(store.photos()[0].star_rating).toBeNull();
  });

  it('toggleRejected reconciles the star rating from the server response', async () => {
    apiPost.mockReturnValue(of({ is_rejected: true, star_rating: 0 }));
    await store.toggleRejected('/a.jpg');
    expect(store.photos()[0].star_rating).toBe(0);
  });

  it('un-rejecting keeps the prior star rating (server sends null = unchanged)', async () => {
    store.photos.update(photos =>
      photos.map(p => p.path === '/a.jpg' ? { ...p, is_rejected: true, star_rating: null } : p));
    apiPost.mockReturnValue(of({ is_rejected: false, star_rating: null }));
    await store.toggleRejected('/a.jpg');
    expect(store.photos()[0].is_rejected).toBe(false);
    expect(store.photos()[0].star_rating).toBeNull();
  });

  it('ignores a second toggleFavorite call for the same path while the first is still in flight', async () => {
    const response = new Subject<{ is_favorite: boolean }>();
    apiPost.mockReturnValue(response.asObservable());

    const first = store.toggleFavorite('/a.jpg');
    const second = store.toggleFavorite('/a.jpg'); // dropped -- a call for this path is already in flight

    response.next({ is_favorite: true });
    response.complete();
    await Promise.all([first, second]);

    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(store.photos()[0].is_favorite).toBe(true);
  });

  it('does not let an in-flight toggleFavorite block a later call once it has settled', async () => {
    apiPost.mockReturnValue(of({ is_favorite: true }));
    await store.toggleFavorite('/a.jpg');
    apiPost.mockReturnValue(of({ is_favorite: false }));
    await store.toggleFavorite('/a.jpg');

    expect(apiPost).toHaveBeenCalledTimes(2);
    expect(store.photos()[0].is_favorite).toBe(false);
  });

  it('a pending toggleFavorite also blocks a toggleRejected for the same path (shared guard)', async () => {
    const response = new Subject<{ is_favorite: boolean }>();
    apiPost.mockReturnValue(response.asObservable());

    const first = store.toggleFavorite('/a.jpg');
    const second = store.toggleRejected('/a.jpg'); // dropped -- overlapping fields, same path in flight

    response.next({ is_favorite: true });
    response.complete();
    await Promise.all([first, second]);

    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(store.photos()[0].is_rejected).toBe(false);
  });

  it('batchReject returns the pre-mutation snapshot on success', async () => {
    const res = await store.batchReject(['/a.jpg', '/b.jpg']);
    expect(res).not.toBeNull();
    expect(res!.snapshot.get('/a.jpg')).toEqual({ is_favorite: false, is_rejected: false, star_rating: 3 });
    expect(res!.snapshot.get('/b.jpg')).toEqual({ is_favorite: true, is_rejected: false, star_rating: null });
    expect(store.photos()[0].is_rejected).toBe(true);
    expect(store.photos()[0].star_rating).toBeNull();
  });

  it('batchReject reverts everything and returns null on error', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('boom')));
    const res = await store.batchReject(['/a.jpg', '/b.jpg']);
    expect(res).toBeNull();
    expect(store.photos()[0].is_rejected).toBe(false);
    expect(store.photos()[0].star_rating).toBe(3);
    expect(store.photos()[1].is_favorite).toBe(true);
    expect(snackOpen).toHaveBeenCalled();
  });

  it('batchRating applies optimistically and reverts on error', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('boom')));
    const result = await store.batchRating(['/a.jpg'], 5);
    expect(result).toBeNull();
    expect(store.photos()[0].star_rating).toBe(3);
  });

  it('setRating reverts on error', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('boom')));
    await store.setRating('/a.jpg', 5);
    expect(store.photos()[0].star_rating).toBe(3);
  });
});

describe('GalleryStore restoreSnapshot', () => {
  let store: GalleryStore;
  let apiPost: Mock;
  let snackOpen: Mock;

  beforeEach(() => {
    apiPost = vi.fn(() => of({}));
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: vi.fn(), post: apiPost } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
  });

  it('undoes a batch reject: clears rejected, restores favorite and rating', async () => {
    store.photos.set([
      makePhoto({ path: '/a.jpg', is_rejected: true, is_favorite: false, star_rating: null }),
      makePhoto({ path: '/b.jpg', is_rejected: true, is_favorite: false, star_rating: null }),
    ]);
    const snap = new Map([
      ['/a.jpg', { is_favorite: true, is_rejected: false, star_rating: 4 }],
      ['/b.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
    ]);

    await store.restoreSnapshot(snap);

    const calls = apiPost.mock.calls.map(c => [c[0], c[1]]);
    expect(calls).toContainEqual(['/photo/toggle_rejected', { photo_path: '/a.jpg' }]);
    expect(calls).toContainEqual(['/photo/toggle_rejected', { photo_path: '/b.jpg' }]);
    expect(calls).toContainEqual(['/photos/batch_favorite', { photo_paths: ['/a.jpg'] }]);
    expect(calls).toContainEqual(['/photos/batch_rating', { photo_paths: ['/a.jpg'], rating: 4 }]);
    expect(store.photos()[0].is_rejected).toBe(false);
    expect(store.photos()[0].is_favorite).toBe(true);
    expect(store.photos()[0].star_rating).toBe(4);
    expect(store.photos()[1].is_rejected).toBe(false);
  });

  it('undoes a batch favorite: un-favorites only previously-unfavorited photos', async () => {
    store.photos.set([
      makePhoto({ path: '/a.jpg', is_favorite: true }),
      makePhoto({ path: '/b.jpg', is_favorite: true }),
    ]);
    const snap = new Map([
      ['/a.jpg', { is_favorite: true, is_rejected: false, star_rating: null }],
      ['/b.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
    ]);

    await store.restoreSnapshot(snap);

    const calls = apiPost.mock.calls.map(c => [c[0], c[1]]);
    expect(calls).toEqual([['/photo/toggle_favorite', { photo_path: '/b.jpg' }]]);
    expect(store.photos()[0].is_favorite).toBe(true);
    expect(store.photos()[1].is_favorite).toBe(false);
  });

  it('no-ops when state already matches the snapshot', async () => {
    store.photos.set([makePhoto({ path: '/a.jpg', is_favorite: false, is_rejected: false, star_rating: null })]);
    await store.restoreSnapshot(new Map([
      ['/a.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
    ]));
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('reverts only the photos whose restore call succeeded, and notifies on partial failure', async () => {
    store.photos.set([
      makePhoto({ path: '/a.jpg', is_rejected: true, is_favorite: false, star_rating: null }),
      makePhoto({ path: '/b.jpg', is_rejected: true, is_favorite: false, star_rating: null }),
    ]);
    const snap = new Map([
      ['/a.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
      ['/b.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
    ]);
    // /b.jpg's inverse call fails server-side; /a.jpg's succeeds.
    apiPost.mockImplementation((url: string, body: { photo_path?: string }) => {
      if (url === '/photo/toggle_rejected' && body.photo_path === '/b.jpg') {
        return throwError(() => new Error('boom'));
      }
      return of({});
    });

    await store.restoreSnapshot(snap);

    // /a.jpg's call succeeded server-side, so local state is reverted to match.
    expect(store.photos().find(p => p.path === '/a.jpg')!.is_rejected).toBe(false);
    // /b.jpg's call failed server-side (still rejected there), so local state must
    // NOT be blindly reverted to "unrejected" -- that would disagree with the server.
    expect(store.photos().find(p => p.path === '/b.jpg')!.is_rejected).toBe(true);
    expect(snackOpen).toHaveBeenCalled();
  });
});

describe('GalleryStore smart-album auto-save', () => {
  let store: GalleryStore;
  let albumUpdate: Mock;
  let snackOpen: Mock;

  const smartAlbum: Album = {
    id: 7,
    name: 'Keepers',
    description: '',
    cover_photo_path: null,
    first_photo_path: null,
    is_smart: true,
    is_shared: false,
    smart_filter_json: '{}',
    scoring_context: null,
    photo_count: 3,
    created_at: '',
    updated_at: '',
  };

  beforeEach(() => {
    albumUpdate = vi.fn(() => of({}));
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: vi.fn(() => of({})), post: vi.fn(() => of({})) } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => true) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: albumUpdate } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.currentAlbum.set(smartAlbum);
  });

  async function changeFiltersAndSettle(): Promise<void> {
    store.filters.set({ ...DEFAULT_FILTERS, camera: 'Canon' });
    TestBed.tick();
    await vi.advanceTimersByTimeAsync(500);
  }

  it('persists the filters without a snackbar when the write succeeds', async () => {
    vi.useFakeTimers();
    try {
      await changeFiltersAndSettle();
    } finally {
      vi.useRealTimers();
    }

    expect(albumUpdate).toHaveBeenCalledTimes(1);
    const [albumId, body] = albumUpdate.mock.calls[0];
    expect(albumId).toBe(7);
    expect(JSON.parse(body.smart_filter_json)).toMatchObject({ camera: 'Canon' });
    expect(snackOpen).not.toHaveBeenCalled();
  });

  it('reports a rejected write instead of letting it pass for a save', async () => {
    albumUpdate.mockReturnValue(throwError(() => new Error('403')));

    vi.useFakeTimers();
    try {
      await changeFiltersAndSettle();
    } finally {
      vi.useRealTimers();
    }

    expect(snackOpen).toHaveBeenCalledWith('albums.smart_save_failed', '', { duration: 5000 });
  });
});
