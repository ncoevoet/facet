import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { GalleryStore, GalleryFilters } from './gallery.store';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryComponent } from './gallery.component';
import { ScoreClassPipe } from '../../shared/pipes/score.pipes';

describe('GalleryComponent', () => {
  let component: GalleryComponent;

  const defaultFilters: GalleryFilters = {
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
    hide_details: true,
    hide_blinks: true,
    hide_bursts: true,
    hide_duplicates: true,
    hide_rejected: true,
    favorites_only: false,
    is_monochrome: false,
    search: '',
  };

  let mockStore: {
    filters: ReturnType<typeof signal<GalleryFilters>>;
    types: ReturnType<typeof signal>;
    photos: ReturnType<typeof signal>;
    total: ReturnType<typeof signal>;
    loading: ReturnType<typeof signal>;
    hasMore: ReturnType<typeof signal>;
    cameras: ReturnType<typeof signal>;
    lenses: ReturnType<typeof signal>;
    tags: ReturnType<typeof signal>;
    persons: ReturnType<typeof signal>;
    config: ReturnType<typeof signal>;
    activeFilterCount: ReturnType<typeof signal>;
    filterDrawerOpen: ReturnType<typeof signal>;
    loadConfig: jest.Mock;
    loadFilterOptions: jest.Mock;
    loadTypeCounts: jest.Mock;
    loadPhotos: jest.Mock;
    updateFilter: jest.Mock;
    resetFilters: jest.Mock;
    nextPage: jest.Mock;
  };
  let mockApi: { thumbnailUrl: jest.Mock };
  let mockAuth: Record<string, unknown>;
  let mockI18n: { t: jest.Mock };

  beforeEach(() => {
    mockStore = {
      filters: signal<GalleryFilters>({ ...defaultFilters }),
      types: signal([
        { id: 'portrait', label: 'Portrait', count: 100 },
        { id: 'landscape', label: 'Landscape', count: 200 },
        { id: 'macro', label: 'Macro', count: 50 },
      ]),
      photos: signal([]),
      total: signal(0),
      loading: signal(false),
      hasMore: signal(false),
      cameras: signal([]),
      lenses: signal([]),
      tags: signal([]),
      persons: signal([]),
      config: signal(null),
      activeFilterCount: signal(0),
      filterDrawerOpen: signal(false),
      loadConfig: jest.fn(() => Promise.resolve()),
      loadFilterOptions: jest.fn(() => Promise.resolve()),
      loadTypeCounts: jest.fn(() => Promise.resolve()),
      loadPhotos: jest.fn(() => Promise.resolve()),
      updateFilter: jest.fn(() => Promise.resolve()),
      resetFilters: jest.fn(() => Promise.resolve()),
      nextPage: jest.fn(() => Promise.resolve()),
    };

    mockApi = {
      thumbnailUrl: jest.fn((path: string) => `/thumbnail?path=${path}`),
    };

    mockAuth = {};

    mockI18n = {
      t: jest.fn((key: string) => key),
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: GalleryStore, useValue: mockStore },
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
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

    it('should call loadPhotos after loadFilterOptions and loadTypeCounts', async () => {
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

      expect(callOrder.indexOf('loadPhotos')).toBeGreaterThan(
        callOrder.indexOf('loadFilterOptions'),
      );
      expect(callOrder.indexOf('loadPhotos')).toBeGreaterThan(
        callOrder.indexOf('loadTypeCounts'),
      );
    });
  });
});
