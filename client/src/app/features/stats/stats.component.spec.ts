import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { ChartHeightPipe } from './chart-height.pipe';
import { StatsComponent } from './stats.component';
import { Router, ActivatedRoute } from '@angular/router';

describe('StatsComponent', () => {
  let component: StatsComponent;
  let mockApi: { get: jest.Mock };

  const mockOverview = {
    total_photos: 1000,
    total_persons: 50,
    avg_score: 6.5,
    avg_aesthetic: 7.2,
    avg_composition: 5.8,
    total_faces: 300,
    total_tags: 150,
    date_range_start: '2023-01-01',
    date_range_end: '2024-12-31',
  };

  const mockGear = {
    cameras: [{ name: 'Canon R5', count: 500, avg_aggregate: 7.1, avg_aesthetic: 7.5, avg_sharpness: 6.8, avg_composition: 7.0, avg_exposure: 6.5, avg_color: 7.2, avg_iso: 400, avg_f_stop: 4.0, avg_focal_length: 50, avg_face_count: 1, avg_monochrome: 0.1, avg_dynamic_range: 12.0, history: [{ date: '2025-01', count: 100 }] }],
    lenses: [{ name: 'RF 50mm', count: 200, avg_aggregate: 7.5, avg_aesthetic: 7.3, avg_sharpness: 7.0, avg_composition: 6.5, avg_exposure: 7.1, avg_color: 6.9, avg_iso: 200, avg_f_stop: 2.0, avg_focal_length: 50, avg_face_count: 1, avg_monochrome: 0.1, avg_dynamic_range: 12.0, history: [{ date: '2025-01', count: 50 }] }],
    combos: [{ name: 'Canon R5 + RF 50mm', count: 100, avg_aggregate: 7.2, avg_aesthetic: 7.4, avg_sharpness: 7.1, avg_composition: 6.8, avg_exposure: 7.0, avg_color: 7.1, avg_iso: 300, avg_f_stop: 2.8, avg_focal_length: 50, avg_face_count: 1.5, avg_monochrome: 0.2, avg_dynamic_range: 11.0, history: [{ date: '2025-01', count: 25 }] }],
    categories: [],
  };

  // Rich mock with all CategoryStat fields including new ones from this commit.
  // portrait: avg_score=7.0, f_stop=2.8, focal=85, iso=800 (full data)
  // landscape: avg_score=6.5, f_stop=0, focal=24, iso=0 (tests '—' display + aperture filter)
  // macro: avg_score=8.2, f_stop=5.6, focal=100, iso=400 (highest score, for sort order)
  const mockCategories = [
    {
      category: 'portrait',
      count: 300,
      percentage: 0.3,
      avg_score: 7.0,
      avg_aesthetic: 7.2,
      avg_composition: 6.8,
      avg_sharpness: 7.5,
      avg_color: 6.9,
      avg_exposure: 7.1,
      avg_iso: 800,
      avg_f_stop: 2.8,
      avg_focal_length: 85,
      top_camera: 'Canon R5',
      top_lens: 'RF 85mm',
    },
    {
      category: 'landscape',
      count: 200,
      percentage: 0.2,
      avg_score: 6.5,
      avg_aesthetic: 6.3,
      avg_composition: 7.0,
      avg_sharpness: 7.8,
      avg_color: 7.2,
      avg_exposure: 6.9,
      avg_iso: 0,
      avg_f_stop: 0,
      avg_focal_length: 24,
      top_camera: null,
      top_lens: null,
    },
    {
      category: 'macro',
      count: 50,
      percentage: 0.05,
      avg_score: 8.2,
      avg_aesthetic: 8.5,
      avg_composition: 7.9,
      avg_sharpness: 8.8,
      avg_color: 7.5,
      avg_exposure: 8.0,
      avg_iso: 400,
      avg_f_stop: 5.6,
      avg_focal_length: 100,
      top_camera: 'Sony A7R V',
      top_lens: 'FE 90mm Macro',
    },
  ];

  const mockScoreBins = [
    { range: '0-1', min: 0, max: 1, count: 10, percentage: 0.01 },
    { range: '9-10', min: 9, max: 10, count: 50, percentage: 0.05 },
  ];

  const mockTopCameras = [
    { name: 'Canon R5', count: 500, avg_score: 7.1, avg_aesthetic: 7.5 },
  ];

  /**
   * Create component with api.get mock pre-configured.
   * The constructor calls loadAll() immediately, so the mock must be ready.
   */
  /** Returns safe empty data for paths that feed into effects expecting arrays */
  function safeDefault(path: string) {
    if (path === '/stats/categories') return of([]);
    if (path === '/stats/score_distribution') return of([]);
    if (path === '/stats/top_cameras') return of([]);
    if (path === '/stats/gear') return of({ cameras: [], lenses: [], combos: [], categories: [] });
    return of({});
  }

  function createComponent(getMock?: jest.Mock): StatsComponent {
    mockApi = {
      get: getMock ?? jest.fn((path: string) => safeDefault(path)),
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: { t: (key: string) => key } },
        { provide: Router, useValue: { navigate: jest.fn() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
      ],
    });
    return TestBed.runInInjectionContext(() => new StatsComponent());
  }

  afterEach(() => {
    TestBed.resetTestingModule();
  });

  describe('loadAll()', () => {
    it('should fetch overview and set the signal', async () => {
      const getMock = jest.fn((path: string) => {
        if (path === '/stats/overview') return of(mockOverview);
        return safeDefault(path);
      });
      component = createComponent(getMock);

      // Wait for constructor's loadAll to complete
      await flushPromises();

      expect(mockApi.get).toHaveBeenCalledWith('/stats/overview', expect.any(Object));
      expect(component.overview()).toEqual(mockOverview);
      expect(component.loading()).toBe(false);
    });

    it('should set loading to false even when overview fails', async () => {
      const getMock = jest.fn((path: string) => {
        if (path === '/stats/overview') return throwError(() => new Error('fail'));
        return safeDefault(path);
      });
      component = createComponent(getMock);

      await flushPromises();

      expect(component.loading()).toBe(false);
      expect(component.overview()).toBeNull();
    });

    it('should kick off parallel loads after overview', async () => {
      const getMock = jest.fn((path: string) => safeDefault(path));
      component = createComponent(getMock);

      await flushPromises();

      expect(mockApi.get).toHaveBeenCalledWith('/stats/overview', expect.any(Object));
      expect(mockApi.get).toHaveBeenCalledWith('/stats/gear', expect.any(Object));
      expect(mockApi.get).toHaveBeenCalledWith('/stats/categories', expect.any(Object));
      expect(mockApi.get).toHaveBeenCalledWith('/stats/score_distribution', expect.any(Object));
      expect(mockApi.get).toHaveBeenCalledWith('/stats/top_cameras', expect.any(Object));
    });
  });

  describe('loadGear()', () => {
    it('should fetch gear stats and set cameras/lenses/combos signals', async () => {
      const getMock = jest.fn((path: string) => {
        if (path === '/stats/gear') return of(mockGear);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(component.cameras()).toEqual([{
        name: 'Canon R5', count: 500, avg_score: 7.1, avg_aesthetic: 7.5,
        avg_sharpness: 6.8, avg_composition: 7.0, avg_exposure: 6.5, avg_color: 7.2,
        avg_iso: 400, avg_f_stop: 4.0, avg_focal_length: 50,
        avg_face_count: 1, avg_monochrome: 0.1, avg_dynamic_range: 12.0, history: [{ date: '2025-01', count: 100 }],
      }]);
      expect(component.lenses()).toEqual([{
        name: 'RF 50mm', count: 200, avg_score: 7.5, avg_aesthetic: 7.3,
        avg_sharpness: 7.0, avg_composition: 6.5, avg_exposure: 7.1, avg_color: 6.9,
        avg_iso: 200, avg_f_stop: 2.0, avg_focal_length: 50,
        avg_face_count: 1, avg_monochrome: 0.1, avg_dynamic_range: 12.0, history: [{ date: '2025-01', count: 50 }],
      }]);
      expect(component.combos()).toEqual([{
        name: 'Canon R5 + RF 50mm', count: 100, avg_score: 7.2,
        avg_aesthetic: 7.4, avg_sharpness: 7.1, avg_composition: 6.8,
        avg_exposure: 7.0, avg_color: 7.1, avg_iso: 300, avg_f_stop: 2.8,
        avg_focal_length: 50,
        avg_face_count: 1.5, avg_monochrome: 0.2, avg_dynamic_range: 11.0, history: [{ date: '2025-01', count: 25 }],
      }]);
      expect(component.gearLoading()).toBe(false);
    });

    it('should set gearLoading to false on error', async () => {
      const getMock = jest.fn((path: string) => {
        if (path === '/stats/gear') return throwError(() => new Error('fail'));
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(component.gearLoading()).toBe(false);
    });
  });

  describe('loadCategories()', () => {
    it('should fetch categories and set the signal', async () => {
      const getMock = jest.fn((path: string) => {
        if (path === '/stats/categories') return of(mockCategories);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(component.categoryStats()).toEqual(mockCategories);
      expect(component.categoriesLoading()).toBe(false);
    });
  });

  describe('CategoryStat computed signals', () => {
    beforeEach(async () => {
      const getMock = jest.fn((path: string) => {
        if (path === '/stats/categories') return of(mockCategories);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();
    });

    it('categoryScoreProfile() filters avg_score > 0 and sorts by score DESC', () => {
      // macro(8.2) > portrait(7.0) > landscape(6.5) — all have avg_score > 0
      const profile = component.categoryScoreProfile();
      expect(profile.map(c => c.category)).toEqual(['macro', 'portrait', 'landscape']);
    });

    it('categoryApertureProfile() filters avg_f_stop > 0 and sorts ASC', () => {
      // landscape has avg_f_stop=0 → filtered; portrait(2.8) < macro(5.6)
      const aperture = component.categoryApertureProfile();
      expect(aperture.map(c => c.category)).toEqual(['portrait', 'macro']);
      expect(aperture.every(c => c.avg_f_stop > 0)).toBe(true);
    });

    it('categoryFocalData() filters avg_focal_length > 0 and sorts ASC', () => {
      // landscape(24) < portrait(85) < macro(100) — all have focal_length > 0
      const focal = component.categoryFocalData();
      expect(focal.map(c => c.category)).toEqual(['landscape', 'portrait', 'macro']);
      expect(focal.every(c => c.avg_focal_length > 0)).toBe(true);
    });

    it('gear table data: avg_iso=0 and top_camera=null for landscape', () => {
      const landscape = component.categoryScoreProfile().find(c => c.category === 'landscape');
      expect(landscape).toBeDefined();
      expect(landscape!.avg_iso).toBe(0);
      expect(landscape!.avg_f_stop).toBe(0);
      expect(landscape!.top_camera).toBeNull();
      expect(landscape!.top_lens).toBeNull();
    });
  });

  describe('loadScoreDistribution()', () => {
    it('should fetch score bins and set the signal', async () => {
      const getMock = jest.fn((path: string) => {
        if (path === '/stats/score_distribution') return of(mockScoreBins);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(component.scoreBins()).toEqual(mockScoreBins);
      expect(component.scoreLoading()).toBe(false);
    });
  });

  describe('loadTopCameras()', () => {
    it('should fetch top cameras and set the signal', async () => {
      const getMock = jest.fn((path: string) => {
        if (path === '/stats/top_cameras') return of(mockTopCameras);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(component.topCameras()).toEqual(mockTopCameras);
    });
  });

});

describe('ChartHeightPipe', () => {
  it('uses default rowHeight of 28', () => {
    const pipe = new ChartHeightPipe();
    expect(pipe.transform(new Array(10))).toBe(280);
  });

  it('accepts custom rowHeight', () => {
    const pipe = new ChartHeightPipe();
    expect(pipe.transform(new Array(4), 52)).toBe(208);
  });

  it('enforces minimum height of 200 with default rowHeight', () => {
    const pipe = new ChartHeightPipe();
    expect(pipe.transform([])).toBe(200);
    expect(pipe.transform(new Array(3))).toBe(200); // 3 * 28 = 84 < 200
  });

  it('enforces minimum height of 200 with custom rowHeight', () => {
    const pipe = new ChartHeightPipe();
    expect(pipe.transform(new Array(2), 52)).toBe(200); // 2 * 52 = 104 < 200
    expect(pipe.transform(new Array(4), 52)).toBe(208); // 4 * 52 = 208 > 200
  });
});

function flushPromises(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}
