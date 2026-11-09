import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { AuthService } from '../../core/services/auth.service';
import { GalleryStore } from '../gallery/gallery.store';
import { NEVER, of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { ChartHeightPipe } from './chart-height.pipe';
import { StatsComponent } from './stats.component';
import { StatsNumberPipe } from './stats-locale-number.pipe';
import { PageContextService } from '../../core/agent/page-context.service';
import { Router, ActivatedRoute } from '@angular/router';
import { HeaderSlotService } from '../../core/services/header-slot.service';

describe('StatsComponent', () => {
  let component: StatsComponent;
  // Cast to `any` for test access to protected signals
  const c = () => component as any;
  let mockApi: { get: Mock };
  let mockAuth: { identity: ReturnType<typeof signal<string>>; isAuthenticated: ReturnType<typeof signal<boolean>>; status: ReturnType<typeof signal<object>>; token: string | null };

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

  /**
   * Create component with api.get mock pre-configured.
   * The constructor calls loadAll() immediately, so the mock must be ready.
   */
  /** Returns safe empty data for paths that feed into effects expecting arrays */
  function safeDefault(path: string) {
    if (path === '/stats/categories') return of([]);
    if (path === '/stats/score_distribution') return of([]);
    if (path === '/stats/gear') return of({ cameras: [], lenses: [], combos: [], categories: [] });
    return of({});
  }

  function createComponent(getMock?: Mock): StatsComponent {
    mockAuth = { identity: signal('owner-a'), isAuthenticated: signal(true), status: signal({}), token: 'token-a' };
    mockApi = {
      get: getMock ?? vi.fn((path: string) => safeDefault(path)),
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: mockAuth },
        { provide: GalleryStore, useValue: { types: signal([]), loadTypeCounts: vi.fn(() => Promise.resolve()) } },
        { provide: I18nService, useValue: { t: (key: string) => key, locale: signal('en') } },
        { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
      ],
    });
    return TestBed.runInInjectionContext(() => new StatsComponent());
  }

  afterEach(() => {
    TestBed.resetTestingModule();
  });

  describe('page context', () => {
    it('registers the stats page and reads its filters live', () => {
      const component = createComponent();
      const context = TestBed.inject(PageContextService);
      expect(context.snapshot()).toEqual({ id: 'stats', tab: 0, category: '', date_from: '', date_to: '' });
      component.statsFilters.filterCategory.set('portrait');
      component.statsFilters.dateFrom.set('2026-01-01');
      expect(context.snapshot()).toMatchObject({ category: 'portrait', date_from: '2026-01-01' });
    });
  });

  it('formats overview numbers using the viewer language', () => {
    const pipe = new StatsNumberPipe();
    expect(pipe.transform(18432, 'de')).toBe('18.432');
    expect(pipe.transform(6.5, 'de', 1)).toBe('6,5');
    expect(pipe.transform(18432, 'en')).toBe('18,432');
    expect(pipe.transform(null, 'de', 1)).toBe('—');
    expect(pipe.transform(undefined, 'de')).toBe('—');
    expect(pipe.transform(Number.NaN, 'de')).toBe('—');
  });

  it('localizes score-bin labels when the viewer language changes', () => {
    component = createComponent();
    c().scoreBins.set([{ range: '1.5', min: 1.5, max: 2, count: 1234, percentage: 1 }]);
    expect(c().scoreDisplayBins()[0].displayRange).toBe('1.5');
    TestBed.inject(I18nService).locale.set('de');
    expect(c().scoreDisplayBins()[0].displayRange).toBe('1,5');
    // The backend rounds a 1.26 score to bucket 1.5, despite reporting
    // min=1.5 and max=2. Those numbers do not define the bucket's interval.
    expect(c().scoreDisplayBins()[0]).not.toHaveProperty('displayBounds');
  });

  it('retains empty score positions without changing the API data used by CSV', () => {
    component = createComponent();
    c().scoreBins.set([
      { range: '1.0', min: 1, max: 1.5, count: 2, percentage: 0.5 },
      { range: '9.5', min: 9.5, max: 10, count: 2, percentage: 0.5 },
    ]);
    const chart = c().scoreChartBins();
    expect(chart).toHaveLength(21);
    expect(chart.find((b: { range: string }) => b.range === '1.0').count).toBe(2);
    expect(chart.find((b: { range: string }) => b.range === '5').count).toBe(0);
    expect(chart.find((b: { range: string }) => b.range === '9.5').count).toBe(2);
    expect(c().scoreBins()).toHaveLength(2);
  });

  it('does not allocate fabricated buckets for unsupported or extreme ranges', () => {
    component = createComponent();
    c().scoreBins.set([{ range: '0.3', min: 0.3, max: 0.8, count: 1, percentage: 1 }]);
    expect(c().scoreChartBins()).toHaveLength(1);
    c().scoreBins.set([{ range: '-1000', min: -1000, max: -999.5, count: 1, percentage: 0.5 },
      { range: '1000', min: 1000, max: 1000.5, count: 1, percentage: 0.5 }]);
    expect(c().scoreChartBins()).toHaveLength(2);
  });

  it('uses whole values for ISO and focal length, and one decimal for scores and aperture', () => {
    component = createComponent();
    c().categoryMetric.set('avg_iso');
    expect(c().categoryMetricDigits()).toBe(0);
    c().categoryMetric.set('avg_focal_length');
    expect(c().categoryMetricDigits()).toBe(0);
    c().categoryMetric.set('avg_f_stop');
    expect(c().categoryMetricDigits()).toBe(1);
  });

  it('keeps an unknown category query visible until the matching type is available', () => {
    component = createComponent();
    vi.spyOn(TestBed.inject(I18nService), 't').mockImplementation(key => key === 'category_names.astro' ? 'Astrofotografie' : key);
    const types = TestBed.inject(GalleryStore).types as ReturnType<typeof signal<{ id: string; count: number }[]>>;
    component.statsFilters.filterCategory.set('astro');
    component.statsFilters.dateFrom.set('2026-11-06');
    expect(c().unknownCategory()).toBe('astro');
    expect(c().unknownCategoryLabel()).toBe('Astrofotografie');
    expect(c().filterSummary()).toBe('Astrofotografie · 06/11/2026');
    types.set([{ id: 'astro', count: 1 }]);
    expect(c().unknownCategory()).toBeNull();
  });

  describe('loadAll()', () => {
    it('should fetch overview and set the signal', async () => {
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/overview') return of(mockOverview);
        return safeDefault(path);
      });
      component = createComponent(getMock);

      // Wait for constructor's loadAll to complete
      await flushPromises();

      expect(mockApi.get).toHaveBeenCalledWith('/stats/overview', expect.any(Object), expect.any(Object));
      expect(component.statsFilters.overview()).toEqual(mockOverview);
      expect(c().loading()).toBe(false);
    });

    it('should set loading to false even when overview fails', async () => {
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/overview') return throwError(() => new Error('fail'));
        return safeDefault(path);
      });
      component = createComponent(getMock);

      await flushPromises();

      expect(c().loading()).toBe(false);
      expect(component.statsFilters.overview()).toBeNull();
      expect(c().loadFailed()).toBe(true);
      expect(mockApi.get).not.toHaveBeenCalledWith('/stats/gear', expect.anything(), expect.anything());
      expect(mockApi.get).not.toHaveBeenCalledWith('/stats/categories', expect.anything(), expect.anything());
      expect(mockApi.get).not.toHaveBeenCalledWith('/stats/score_distribution', expect.anything(), expect.anything());
      expect(mockApi.get).not.toHaveBeenCalledWith('/stats/top_cameras', expect.anything(), expect.anything());
    });

    it('does not start obsolete chart reads after a newer overview completes', async () => {
      const first = new Subject<typeof mockOverview>();
      const second = new Subject<typeof mockOverview>();
      let overviewCalls = 0;
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/overview') return ++overviewCalls === 1 ? first : second;
        return safeDefault(path);
      });
      component = createComponent(getMock);
      const oldLoad = component.loadAll();
      const newLoad = component.loadAll();
      second.next(mockOverview); second.complete();
      await newLoad;
      first.next(mockOverview); first.complete();
      await oldLoad;
      expect(getMock.mock.calls.filter(([path]) => path === '/stats/gear')).toHaveLength(1);
      expect(component.statsFilters.overview()).toEqual(mockOverview);
    });

    it('ignores an earlier gear response immediately when a new filtered load starts', async () => {
      const pendingGear = new Subject<typeof mockGear>();
      const pendingOverview = new Subject<typeof mockOverview>();
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/gear') return pendingGear;
        if (path === '/stats/overview') return pendingOverview;
        return safeDefault(path);
      });
      component = createComponent(getMock);
      const oldGear = component.loadGear();
      const newLoad = component.loadAll();
      pendingGear.next(mockGear); pendingGear.complete();
      await oldGear;
      expect(c().cameras()).toEqual([]);
      pendingOverview.next(mockOverview); pendingOverview.complete();
      await newLoad;
    });

    it('should kick off parallel loads after overview', async () => {
      const getMock = vi.fn((path: string) => safeDefault(path));
      component = createComponent(getMock);

      await flushPromises();

      expect(mockApi.get).toHaveBeenCalledWith('/stats/overview', expect.any(Object), expect.any(Object));
      expect(mockApi.get).toHaveBeenCalledWith('/stats/gear', expect.any(Object), expect.any(Object));
      expect(mockApi.get).toHaveBeenCalledWith('/stats/categories', expect.any(Object), expect.any(Object));
      expect(mockApi.get).toHaveBeenCalledWith('/stats/score_distribution', expect.any(Object), expect.any(Object));
      // Nothing renders the top cameras, so they are no longer read.
      expect(mockApi.get).not.toHaveBeenCalledWith('/stats/top_cameras', expect.any(Object), expect.any(Object));
    });
  });

  describe('loadGear()', () => {
    it('should fetch gear stats and set cameras/lenses/combos signals', async () => {
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/gear') return of(mockGear);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(c().cameras()).toEqual([{
        name: 'Canon R5', count: 500, avg_score: 7.1, avg_aesthetic: 7.5,
        avg_sharpness: 6.8, avg_composition: 7.0, avg_exposure: 6.5, avg_color: 7.2,
        avg_iso: 400, avg_f_stop: 4.0, avg_focal_length: 50,
        avg_face_count: 1, avg_monochrome: 0.1, avg_dynamic_range: 12.0, history: [{ date: '2025-01', count: 100 }],
      }]);
      expect(c().lenses()).toEqual([{
        name: 'RF 50mm', count: 200, avg_score: 7.5, avg_aesthetic: 7.3,
        avg_sharpness: 7.0, avg_composition: 6.5, avg_exposure: 7.1, avg_color: 6.9,
        avg_iso: 200, avg_f_stop: 2.0, avg_focal_length: 50,
        avg_face_count: 1, avg_monochrome: 0.1, avg_dynamic_range: 12.0, history: [{ date: '2025-01', count: 50 }],
      }]);
      expect(c().combos()).toEqual([{
        name: 'Canon R5 + RF 50mm', count: 100, avg_score: 7.2,
        avg_aesthetic: 7.4, avg_sharpness: 7.1, avg_composition: 6.8,
        avg_exposure: 7.0, avg_color: 7.1, avg_iso: 300, avg_f_stop: 2.8,
        avg_focal_length: 50,
        avg_face_count: 1.5, avg_monochrome: 0.2, avg_dynamic_range: 11.0, history: [{ date: '2025-01', count: 25 }],
      }]);
      expect(c().gearLoading()).toBe(false);
    });

    it('should set gearLoading to false on error', async () => {
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/gear') return throwError(() => new Error('fail'));
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(c().gearLoading()).toBe(false);
      expect(c().gearFailed()).toBe(true);
      expect(c().loadFailed()).toBe(false);
    });
  });

  describe('loadCategories()', () => {
    it('should fetch categories and set the signal', async () => {
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/categories') return of(mockCategories);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(c().categoryStats()).toEqual(mockCategories);
      expect(c().categoriesLoading()).toBe(false);
    });
  });

  describe('CategoryStat computed signals', () => {
    beforeEach(async () => {
      const getMock = vi.fn((path: string) => {
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

    it('categoryMetricData() filters avg_f_stop > 0 and sorts DESC', () => {
      // landscape has avg_f_stop=0 → filtered; macro(5.6) > portrait(2.8)
      (component as any).categoryMetric.set('avg_f_stop');
      const data = (component as any).categoryMetricData();
      expect(data.map((c: any) => c.category)).toEqual(['macro', 'portrait']);
      expect(data.every((c: any) => c.avg_f_stop > 0)).toBe(true);
    });

    it('categoryMetricData() filters avg_focal_length > 0 and sorts DESC', () => {
      // macro(100) > portrait(85) > landscape(24) — all have focal_length > 0
      (component as any).categoryMetric.set('avg_focal_length');
      const data = (component as any).categoryMetricData();
      expect(data.map((c: any) => c.category)).toEqual(['macro', 'portrait', 'landscape']);
      expect(data.every((c: any) => c.avg_focal_length > 0)).toBe(true);
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

  describe('score profile series (U17)', () => {
    beforeEach(async () => {
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/categories') return of(mockCategories);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();
    });

    function lastProfileCall(spy: ReturnType<typeof vi.spyOn>): { label: string; data: number[]; color: string }[] {
      const calls = spy.mock.calls;
      return calls[calls.length - 1][3] as { label: string; data: number[]; color: string }[];
    }

    it('starts with all eight series selected', () => {
      expect(c().profileSeries()).toHaveLength(8);
    });

    it('drops a deselected series from the dataset passed to the chart builder', () => {
      const spy = vi.spyOn(c(), 'buildGroupedHorizontalBar');
      TestBed.flushEffects();
      expect(lastProfileCall(spy)).toHaveLength(8);
      c().onProfileSeriesChange(c().profileSeries().filter((k: string) => k !== 'contrast_score'));
      TestBed.flushEffects();
      const datasets = lastProfileCall(spy);
      expect(datasets).toHaveLength(7);
      expect(datasets.map(d => d.label)).not.toContain('stats.axes.contrast');
    });

    it('keeps each series colour when another one is hidden', () => {
      const spy = vi.spyOn(c(), 'buildGroupedHorizontalBar');
      TestBed.flushEffects();
      const before = lastProfileCall(spy).find(d => d.label === 'stats.axes.exposure')!.color;
      c().onProfileSeriesChange(['aggregate', 'exposure_score']);
      TestBed.flushEffects();
      expect(lastProfileCall(spy).find(d => d.label === 'stats.axes.exposure')!.color).toBe(before);
    });

    it('refuses to deselect the last series', () => {
      c().onProfileSeriesChange(['aesthetic']);
      c().onProfileSeriesChange([]);
      expect(c().profileSeries()).toEqual(['aesthetic']);
    });

    it('keeps a passive colour key: legend shown at the top, clicking it does nothing', () => {
      const ctx = { canvas: document.createElement('canvas') } as unknown as CanvasRenderingContext2D;
      const ref = { nativeElement: { getContext: () => ctx } };
      (c() as any).buildGroupedHorizontalBar('profile-test', ref, ['a'], [{ label: 'x', data: [1], color: '#ff0000' }]);
      const legend = (c() as any).charts.get('profile-test').options.plugins.legend;
      expect(legend.display).toBe(true);
      expect(legend.position).toBe('top');
      expect(legend.onClick()).toBeUndefined();
    });

    it('summarises more than three selected series as a count, passing the count placeholder', () => {
      const i18n = TestBed.inject(I18nService);
      vi.spyOn(i18n, 't').mockImplementation((key: string, params?: Record<string, unknown>) => key + (params ? JSON.stringify(params) : ''));
      expect(c().profileSeriesSummary()).toBe('stats.profile_series_count{"count":8}');
      c().onProfileSeriesChange(['aggregate', 'aesthetic']);
      expect(c().profileSeriesSummary()).toBeNull();
    });
  });

  describe('page shell', () => {
    async function render() {
      const component = createComponent();
      TestBed.resetTestingModule();
      const fixture = TestBed.configureTestingModule({
        providers: [
          { provide: ApiService, useValue: mockApi },
          { provide: AuthService, useValue: mockAuth },
          { provide: GalleryStore, useValue: { types: signal([]), loadTypeCounts: vi.fn(() => Promise.resolve()) } },
          { provide: I18nService, useValue: { t: (key: string) => key, locale: signal('en'), translations: () => ({}) } },
          { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        ],
      }).createComponent(StatsComponent);
      void component;
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      return fixture;
    }

    it('registers its toolbar with the header slot and clears it on destroy', async () => {
      const fixture = await render();
      const slot = TestBed.inject(HeaderSlotService);
      expect(slot.template()).not.toBeNull();
      fixture.destroy();
      expect(slot.template()).toBeNull();
    });

    it('insets the page 16px (px-4) at every width, not 24px at md', async () => {
      const fixture = await render();
      const host = (fixture.nativeElement as HTMLElement).className;
      expect(host).toContain('px-4');
      expect(host).not.toContain('md:p-6');
    });

    it('keeps the H1 for assistive tech only, and the in-page filters below lg only', async () => {
      const fixture = await render();
      const el = fixture.nativeElement as HTMLElement;
      expect(el.querySelector('h1#stats-heading')!.className).toContain('sr-only');
      expect(el.querySelector('details')!.className).toContain('lg:hidden');
      expect(el.querySelector('details')!.className).not.toContain('sm:hidden');
    });
  });

  describe('loadScoreDistribution()', () => {
    it('should fetch score bins and set the signal', async () => {
      const getMock = vi.fn((path: string) => {
        if (path === '/stats/score_distribution') return of(mockScoreBins);
        return safeDefault(path);
      });
      component = createComponent(getMock);
      await flushPromises();

      expect(c().scoreBins()).toEqual(mockScoreBins);
      expect(c().scoreLoading()).toBe(false);
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
