import { TestBed } from '@angular/core/testing';
import { Router, ActivatedRoute } from '@angular/router';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import {
  GalleryStore,
  GalleryFilters,
  PhotosResponse,
  ViewerConfig,
  TypeCount,
} from './gallery.store';
import { Photo } from '../../shared/models/photo.model';

const DEFAULT_FILTERS: GalleryFilters = {
  page: 1,
  per_page: 64,
  sort: 'aggregate',
  sort_direction: 'DESC',
  type: '',
  camera: '',
  lens: '',
  tag: '',
  person_id: '',
  min_score: '',
  max_score: '',
  min_aesthetic: '',
  max_aesthetic: '',
  min_face_quality: '',
  max_face_quality: '',
  min_composition: '',
  max_composition: '',
  min_sharpness: '',
  max_sharpness: '',
  min_exposure: '',
  max_exposure: '',
  min_color: '',
  max_color: '',
  min_contrast: '',
  max_contrast: '',
  min_noise: '',
  max_noise: '',
  min_dynamic_range: '',
  max_dynamic_range: '',
  min_face_count: '',
  max_face_count: '',
  min_eye_sharpness: '',
  max_eye_sharpness: '',
  min_face_sharpness: '',
  max_face_sharpness: '',
  min_face_ratio: '',
  max_face_ratio: '',
  min_face_confidence: '',
  max_face_confidence: '',
  min_quality_score: '',
  max_quality_score: '',
  min_topiq: '',
  max_topiq: '',
  min_power_point: '',
  max_power_point: '',
  min_leading_lines: '',
  max_leading_lines: '',
  min_isolation: '',
  max_isolation: '',
  min_saturation: '',
  max_saturation: '',
  min_luminance: '',
  max_luminance: '',
  min_histogram_spread: '',
  max_histogram_spread: '',
  min_star_rating: '',
  max_star_rating: '',
  min_iso: '',
  max_iso: '',
  min_aperture: '',
  max_aperture: '',
  min_focal_length: '',
  max_focal_length: '',
  date_from: '',
  date_to: '',
  composition_pattern: '',
  similar_to: '',
  min_similarity: '70',
  min_aesthetic_iaa: '',
  max_aesthetic_iaa: '',
  min_face_quality_iqa: '',
  max_face_quality_iqa: '',
  min_liqe: '',
  max_liqe: '',
  min_subject_sharpness: '',
  max_subject_sharpness: '',
  min_subject_prominence: '',
  max_subject_prominence: '',
  min_subject_placement: '',
  max_subject_placement: '',
  min_bg_separation: '',
  max_bg_separation: '',
  hide_details: true,
  hide_blinks: true,
  hide_bursts: true,
  hide_duplicates: true,
  hide_rejected: true,
  favorites_only: false,
  is_monochrome: false,
  search: '',
};

function makePhoto(overrides: Partial<Photo> = {}): Photo {
  return {
    path: '/photos/test.jpg',
    filename: 'test.jpg',
    aggregate: 7.5,
    aesthetic: 8.0,
    face_quality: null,
    comp_score: null,
    tech_sharpness: null,
    color_score: null,
    exposure_score: null,
    quality_score: null,
    topiq_score: null,
    top_picks_score: null,
    isolation_bonus: null,
    histogram_spread: null,
    face_count: 0,
    face_ratio: 0,
    eye_sharpness: null,
    face_sharpness: null,
    face_confidence: null,
    is_blink: null,
    camera_model: null,
    lens_model: null,
    iso: null,
    f_stop: null,
    shutter_speed: null,
    focal_length: null,
    noise_sigma: null,
    contrast_score: null,
    dynamic_range_stops: null,
    mean_saturation: null,
    mean_luminance: null,
    composition_pattern: null,
    power_point_score: null,
    leading_lines_score: null,
    category: null,
    tags: null,
    tags_list: [],
    is_monochrome: null,
    is_silhouette: null,
    date_taken: null,
    image_width: 1920,
    image_height: 1080,
    is_best_of_burst: null,
    burst_group_id: null,
    duplicate_group_id: null,
    is_duplicate_lead: null,
    persons: [],
    unassigned_faces: 0,
    star_rating: null,
    is_favorite: null,
    is_rejected: null,
    aesthetic_iaa: null,
    face_quality_iqa: null,
    liqe_score: null,
    subject_sharpness: null,
    subject_prominence: null,
    subject_placement: null,
    bg_separation: null,
    ...overrides,
  };
}

function makePhotosResponse(overrides: Partial<PhotosResponse> = {}): PhotosResponse {
  return {
    photos: [makePhoto()],
    total: 1,
    page: 1,
    per_page: 64,
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
      hide_details: true,
      hide_rejected: true,
    },
    display: { tags_per_photo: 5, card_width_px: 300, image_width_px: 640 },
    sort_options_grouped: null,
    features: {
      show_similar_button: false,
      show_merge_suggestions: false,
      show_rating_controls: false,
      show_rating_badge: false,
    },
    quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
    ...overrides,
  };
}

describe('GalleryStore', () => {
  let store: GalleryStore;
  let apiGet: jest.Mock;
  let routerNavigate: jest.Mock;
  let queryParams: Record<string, string>;

  beforeEach(() => {
    apiGet = jest.fn();
    routerNavigate = jest.fn();
    queryParams = {};

    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: apiGet } },
        { provide: Router, useValue: { navigate: routerNavigate } },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParams } },
        },
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

    it('should not count non-filter fields like sort or type', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        sort: 'date_taken',
        sort_direction: 'ASC',
        type: 'portrait',
        hide_blinks: false,
      });
      expect(store.activeFilterCount()).toBe(0);
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
          hide_details: false,
          hide_rejected: false,
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

    it('should keep current state on error and clear loading', async () => {
      // Set initial state
      store.photos.set([makePhoto({ filename: 'existing.jpg' })]);
      store.total.set(50);
      store.hasMore.set(true);

      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadPhotos();

      expect(store.loading()).toBe(false);
      expect(store.photos().length).toBe(1);
      expect(store.photos()[0].filename).toBe('existing.jpg');
      expect(store.total()).toBe(50);
      expect(store.hasMore()).toBe(true);
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
          hide_details: true,
          hide_rejected: true,
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

  describe('loadTypeCounts()', () => {
    it('should fetch and set type counts', async () => {
      const counts: TypeCount[] = [
        { id: 'portrait', label: 'Portrait', count: 100 },
        { id: 'landscape', label: 'Landscape', count: 50 },
      ];
      apiGet.mockReturnValue(of({ types: counts }));

      await store.loadTypeCounts();

      expect(apiGet).toHaveBeenCalledWith('/type_counts');
      expect(store.types()).toEqual(counts);
    });

    it('should set empty array on error', async () => {
      store.types.set([{ id: 'old', label: 'Old', count: 1 }]);
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadTypeCounts();

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
