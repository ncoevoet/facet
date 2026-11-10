import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { Observable, of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { StatsFiltersService } from './stats-filters.service';
import { allocateSeriesSlots, CORRELATION_PRESETS, correlationSeries, StatsCorrelationsTabComponent } from './stats-correlations-tab.component';
import { buildCorrelationCsvRecords } from './stats-correlations-csv';

describe('StatsCorrelationsTabComponent', () => {
  let component: StatsCorrelationsTabComponent;
  let owner: ReturnType<typeof signal<string>>;

  beforeEach(() => {
    owner = signal('owner-a');
    TestBed.configureTestingModule({
      providers: [
        StatsCorrelationsTabComponent,
        { provide: ApiService, useValue: { get: vi.fn(() => of({})) } },
        { provide: AuthService, useValue: { status: signal({ authenticated: true }), identity: owner, isAuthenticated: signal(true), token: 'token-a' } },
        { provide: I18nService, useValue: { t: vi.fn((k: string) => k), locale: signal('en'), currentLang: vi.fn(() => 'en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    component = TestBed.inject(StatsCorrelationsTabComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  const preset = (id: string) => CORRELATION_PRESETS.find(entry => entry.id === id)!;
  const lastParams = () => vi.mocked(TestBed.inject(ApiService).get).mock.lastCall?.[1];

  it('draws the default Scores by year chart without a click', async () => {
    const get = vi.mocked(TestBed.inject(ApiService).get);
    get.mockReturnValueOnce(of({ labels: ['2024'], metrics: { aggregate: [5.6], aesthetic: [4.5] }, x_axis: 'date_year', group_by: '' }));
    TestBed.tick();
    expect(get).toHaveBeenCalledTimes(1);
    expect(get.mock.calls[0][0]).toBe('/stats/correlations');
    expect(get.mock.calls[0][1]).toEqual({ x: 'date_year', y: 'aggregate,aesthetic', min_samples: '3' });
    await Promise.resolve();
    expect(component.currentData()?.labels).toEqual(['2024']);
  });

  it('fills the form from a preset and loads its chart', () => {
    TestBed.tick();
    component.applyPreset(preset('noise_vs_iso'));
    TestBed.tick();
    expect(lastParams()).toEqual({ x: 'iso', y: 'noise_sigma', group_by: 'camera_model', min_samples: '3' });
    expect(component.corrChartType()).toBe('line');
    expect(component.activePreset()).toBe('noise_vs_iso');
    component.applyPreset(preset('score_by_category'));
    TestBed.tick();
    expect(lastParams()).toEqual({ x: 'category', y: 'aggregate,aesthetic', min_samples: '3' });
    expect(component.corrChartType()).toBe('horizontalBar');
    expect(vi.mocked(TestBed.inject(ApiService).get)).toHaveBeenCalledTimes(3);
  });

  it('waits for Load after a form edit, and a preset resumes loading', async () => {
    const get = vi.mocked(TestBed.inject(ApiService).get);
    TestBed.tick();
    component.edit(component.corrXAxis, 'iso');
    TestBed.tick();
    expect(get).toHaveBeenCalledTimes(1);
    expect(component.activePreset()).toBeNull();
    component.edit(component.corrXAxis, 'date_year');
    TestBed.tick();
    expect(component.activePreset()).toBe('scores_by_year');
    component.applyPreset(preset('scores_by_year'));
    expect(get).toHaveBeenCalledTimes(2);
    expect(lastParams()).toEqual({ x: 'date_year', y: 'aggregate,aesthetic', min_samples: '3' });
  });

  it('queries nothing while the stats page shows another tab, and loads when the tab is shown', () => {
    TestBed.resetTestingModule();
    const get = vi.fn(() => of({}));
    TestBed.configureTestingModule({
      imports: [StatsCorrelationsTabComponent],
      providers: [
        { provide: ApiService, useValue: { get } },
        { provide: AuthService, useValue: { status: signal({ authenticated: true }), identity: signal('owner'), isAuthenticated: signal(true), token: 'token' } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), locale: signal('en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    const fixture = TestBed.createComponent(StatsCorrelationsTabComponent);
    fixture.componentRef.setInput('active', false);
    fixture.detectChanges();
    TestBed.inject(StatsFiltersService).dateFrom.set('2024-01-01');
    fixture.detectChanges();
    expect(get).not.toHaveBeenCalled();
    fixture.componentRef.setInput('active', true);
    fixture.detectChanges();
    expect(get).toHaveBeenCalledTimes(1);
    fixture.destroy();
  });

  it('loads from an icon button and centres each select icon on its label', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [StatsCorrelationsTabComponent],
      providers: [
        { provide: ApiService, useValue: { get: vi.fn(() => of({})) } },
        { provide: AuthService, useValue: { status: signal({ authenticated: true }), identity: signal('owner'), isAuthenticated: signal(true), token: 'token' } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), locale: signal('en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    const fixture = TestBed.createComponent(StatsCorrelationsTabComponent);
    fixture.componentRef.setInput('active', false);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const load = root.querySelector<HTMLButtonElement>('button[data-load-correlations]')!;
    expect(load.hasAttribute('mat-icon-button')).toBe(true);
    expect(load.getAttribute('aria-label')).toBe('stats.load_correlations');
    expect(load.textContent!.trim()).toBe('refresh');
    const icons = Array.from(root.querySelectorAll('mat-select-trigger mat-icon'));
    expect(icons).toHaveLength(2);
    for (const icon of icons) {
      expect(icon.parentElement!.classList).toContain('items-center');
      expect(icon.nextElementSibling!.classList).toContain('truncate');
    }
    fixture.destroy();
  });

  it('redraws a suggested chart when the stats filters change', () => {
    TestBed.tick();
    TestBed.inject(StatsFiltersService).dateFrom.set('2024-01-01');
    TestBed.tick();
    expect(vi.mocked(TestBed.inject(ApiService).get)).toHaveBeenCalledTimes(2);
    expect(lastParams()).toEqual({ x: 'date_year', y: 'aggregate,aesthetic', min_samples: '3', date_from: '2024-01-01' });
  });

  it('does not show or export data for settings changed while a request is pending', async () => {
    TestBed.tick();
    const pending = new Subject<any>();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(pending);
    const request = component.loadCorrelation();
    component.corrYMetrics.set(['aesthetic']);
    pending.next({ labels: ['2025'], metrics: { aggregate: [7] }, x_axis: 'date_year', group_by: '' });
    pending.complete();
    await request;
    expect(component.currentData()).toBeNull();
    expect(component.corrBucketCount()).toBe(0);
  });

  it('distinguishes a failed request from an empty result', async () => {
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(throwError(() => new Error('offline')));
    await component.loadCorrelation();
    expect(component.correlationFailed()).toBe(true);
    expect(component.currentData()).toBeNull();
  });

  it('clears loaded data immediately when the owner changes', async () => {
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['2025'], metrics: { aggregate: [7] } }));
    await component.loadCorrelation();
    expect(component.currentData()?.labels).toEqual(['2025']);
    owner.set('owner-b');
    expect(component.currentData()).toBeNull();
    expect(component.corrBucketCount()).toBe(0);
  });

  it('keeps a loaded chart when a status refresh changes neither identity nor token', async () => {
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['2025'], metrics: { aggregate: [7] }, x_axis: 'date_year', group_by: '' }));
    await component.loadCorrelation();
    (TestBed.inject(AuthService).status as ReturnType<typeof signal<object>>).set({ authenticated: true, edition_authenticated: true });
    TestBed.tick();
    expect(component.currentData()?.labels).toEqual(['2025']);
  });

  it('uses translation keys for chart-table headers while retaining raw CSV keys', async () => {
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['2025'], metrics: { aggregate: [7], aesthetic: [6] }, x_axis: 'date_year', group_by: '' }));
    await component.loadCorrelation();
    expect(component.accessibleColumnLabels()).toEqual([
      'stats.correlations.dimensions.date_year', 'stats.correlations.metrics.aggregate', 'stats.correlations.metrics.aesthetic',
    ]);
    expect(buildCorrelationCsvRecords(component.currentData(), ['aggregate', 'aesthetic'])[0]).toEqual({ date_year: '2025', aggregate: 7, aesthetic: 6 });
  });

  it('keeps a bucket column in the chart-data table when the X dimension is also a selected Y metric', async () => {
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['4.0-4.5', '4.5-5.0'], metrics: { aggregate: [4.2, 4.7], aesthetic: [5.1, 5.3] }, x_axis: 'aggregate', group_by: '' }));
    await component.loadCorrelation();
    expect(component.accessibleColumnLabels()).toEqual([
      'stats.correlations.dimensions.aggregate', 'stats.correlations.metrics.aggregate', 'stats.correlations.metrics.aesthetic',
    ]);
    expect(component.accessibleRows()).toEqual([['4.0-4.5', '4.2', '5.1'], ['4.5-5.0', '4.7', '5.3']]);
  });

  it('keeps one colour per group and a distinct dash and point style per metric', async () => {
    TestBed.tick();
    const metrics = ['aggregate', 'aesthetic', 'tech_sharpness', 'comp_score', 'face_quality'];
    component.corrYMetrics.set(metrics);
    component.corrGroupBy.set('camera_model');
    TestBed.tick();
    const cell = { aggregate: 1, aesthetic: 2, tech_sharpness: 3, comp_score: 4, face_quality: 5 };
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['2025'], groups: { Canon: { '2025': cell } }, x_axis: 'date_year', group_by: 'camera_model' }));
    await component.loadCorrelation();
    const rows = component.chartSeriesRows();
    expect(rows).toHaveLength(5);
    expect(new Set(rows.map(row => row.color)).size).toBe(1);
    expect(new Set(rows.map(row => `${row.dashPattern}|${row.point}`)).size).toBe(5);
  });

  it('keeps all 23 selectable metrics visually distinct on an ungrouped line chart', async () => {
    TestBed.tick();
    const metrics = component.corrMetricOptions.map(option => option.key);
    component.corrYMetrics.set(metrics);
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({
      labels: ['2025'], metrics: Object.fromEntries(metrics.map(metric => [metric, [1]])), x_axis: 'date_year', group_by: '',
    }));
    await component.loadCorrelation();
    const rows = component.chartSeriesRows();
    expect(rows).toHaveLength(23);
    expect(new Set(rows.map(row => `${row.color}|${row.dashPattern}|${row.point}`)).size).toBe(23);
  });

  it('labels grouped tables with the actual dimension and formats numbers in the selected locale', async () => {
    TestBed.tick();
    component.corrGroupBy.set('camera_model');
    TestBed.tick();
    const i18n = TestBed.inject(I18nService);
    (i18n.locale as ReturnType<typeof signal<string>>).set('de');
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['2025'], groups: { Canon: { '2025': { aggregate: 7.5 } } }, x_axis: 'date_year', group_by: 'camera_model' }));
    await component.loadCorrelation();
    expect(component.accessibleColumnLabels()).toEqual(['stats.correlations.dimensions.date_year', 'stats.correlations.dimensions.camera_model', 'stats.correlations.metrics.aggregate', 'stats.correlations.metrics.aesthetic']);
    expect(component.accessibleRows()[0]).toEqual(['2025', 'Canon', '7,5', '—']);
  });

  it('lets users hide a chart series without removing its table or CSV values', async () => {
    TestBed.tick();
    component.corrGroupBy.set('camera_model');
    TestBed.tick();
    const data = { labels: ['2025'], groups: { Canon: { '2025': { aggregate: 7.5, aesthetic: 6.5 } } }, x_axis: 'date_year', group_by: 'camera_model' };
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of(data));
    await component.loadCorrelation();
    expect(component.chartSeriesRows().map(row => row.visible)).toEqual([true, true]);
    expect(component.chartSeriesRows().map(row => row.dash)).toEqual([[], [7, 4]]);
    component.setSeriesVisible(component.chartSeriesRows()[1].key, false);
    expect(component.chartSeriesRows().map(row => row.visible)).toEqual([true, false]);
    expect(component.accessibleRows()[0]).toEqual(['2025', 'Canon', '7.5', '6.5']);
    expect(buildCorrelationCsvRecords(component.currentData(), ['aggregate', 'aesthetic'])[0]).toEqual({ date_year: '2025', group: 'Canon', aggregate: 7.5, aesthetic: 6.5 });
  });

  it('bounds bar series to eight distinct colors while allowing any series and retaining all data', async () => {
    TestBed.tick();
    component.corrGroupBy.set('camera_model');
    component.corrChartType.set('bar');
    TestBed.tick();
    const groups = Object.fromEntries(Array.from({ length: 6 }, (_, i) => [`Camera ${i}`, { '2025': { aggregate: i + 1, aesthetic: i + 2 } }]));
    const data = { labels: ['2025'], groups, x_axis: 'date_year', group_by: 'camera_model' };
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of(data));
    await component.loadCorrelation();
    let rows = component.chartSeriesRows();
    expect(rows).toHaveLength(12);
    expect(component.selectedSeriesCount()).toBe(8);
    expect(new Set(rows.filter(row => row.visible).map(row => row.color)).size).toBe(8);
    const originalColors = new Map(rows.filter(row => row.visible).map(row => [row.key, row.color]));
    expect(rows[8].atLimit).toBe(true);
    component.setSeriesVisible(rows[0].key, false);
    rows = component.chartSeriesRows();
    expect(rows[8].atLimit).toBe(false);
    component.setSeriesVisible(rows[8].key, true);
    rows = component.chartSeriesRows();
    expect(rows[8].visible).toBe(true);
    expect(component.selectedSeriesCount()).toBe(8);
    expect(new Set(rows.filter(row => row.visible).map(row => row.color)).size).toBe(8);
    for (const row of rows.slice(1, 8)) expect(row.color).toBe(originalColors.get(row.key));
    expect(rows[0].color).toBe('var(--mat-sys-outline)');
    expect(component.accessibleRows()).toHaveLength(6);
    expect(buildCorrelationCsvRecords(component.currentData(), ['aggregate', 'aesthetic'])).toHaveLength(6);
    for (const row of rows.filter(row => row.visible)) component.setSeriesVisible(row.key, false);
    expect(component.selectedSeriesCount()).toBe(0);
    component.resetSeriesSelection();
    expect(component.selectedSeriesCount()).toBe(8);
    expect(component.chartSeriesRows().slice(0, 8).every(row => row.visible)).toBe(true);
  });

  it('does not automatically select a hidden series when switching from line to bar', async () => {
    TestBed.tick();
    component.corrGroupBy.set('camera_model');
    TestBed.tick();
    const groups = Object.fromEntries(Array.from({ length: 6 }, (_, i) => [`Camera ${i}`, { '2025': { aggregate: i + 1, aesthetic: i + 2 } }]));
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['2025'], groups, x_axis: 'date_year', group_by: 'camera_model' }));
    await component.loadCorrelation();
    expect(component.selectedSeriesCount()).toBe(12);
    component.setChartType('bar');
    expect(component.selectedSeriesCount()).toBe(8);
    const rows = component.chartSeriesRows();
    component.setSeriesVisible(rows[0].key, false);
    expect(component.selectedSeriesCount()).toBe(7);
    expect(component.chartSeriesRows()[8].visible).toBe(false);
  });

  it('ignores a late response after the owner changes', async () => {
    TestBed.tick();
    const pending = new Subject<any>();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(pending);
    const request = component.loadCorrelation();
    owner.set('owner-b');
    pending.next({ labels: ['2025'], metrics: { aggregate: [7] } });
    pending.complete();
    await request;
    expect(component.currentData()).toBeNull();
  });

  it('ignores a response after the component is destroyed', async () => {
    TestBed.tick();
    const pending = new Subject<any>();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(pending);
    const request = component.loadCorrelation();
    TestBed.resetTestingModule();
    pending.next({ labels: ['2025'], metrics: { aggregate: [7] } });
    pending.complete();
    await request;
    expect(component.currentData()).toBeNull();
  });

  it('ignores a late response after the credential changes', async () => {
    TestBed.tick();
    const pending = new Subject<any>();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(pending);
    const request = component.loadCorrelation();
    Object.defineProperty(TestBed.inject(AuthService), 'token', { value: 'token-b', configurable: true });
    pending.next({ labels: ['2025'], metrics: { aggregate: [7] } });
    pending.complete();
    await request;
    expect(component.currentData()).toBeNull();
  });

  it('invalidates a loaded chart on a same-owner credential rotation', async () => {
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['2025'], metrics: { aggregate: [7] } }));
    await component.loadCorrelation();
    expect(component.currentData()?.labels).toEqual(['2025']);
    const auth = TestBed.inject(AuthService);
    Object.defineProperty(auth, 'token', { value: 'token-b', configurable: true });
    (auth.status as ReturnType<typeof signal<any>>).set({ authenticated: true });
    expect(component.currentData()).toBeNull();
    TestBed.tick();
    expect(component.corrData()).toBeNull();
  });
});

describe('Correlation selectors carry the gallery icons', () => {
  async function render() {
    TestBed.configureTestingModule({
      imports: [StatsCorrelationsTabComponent],
      providers: [
        { provide: ApiService, useValue: { get: vi.fn(() => of({})) } },
        { provide: AuthService, useValue: { status: signal({ authenticated: true }), identity: signal('owner'), isAuthenticated: signal(true), token: 'token' } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), locale: signal('en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    const fixture = TestBed.createComponent(StatsCorrelationsTabComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture;
  }

  it('shows the selected X axis, chart type and Y metrics as icons in the triggers', async () => {
    const fixture = await render();
    const triggers = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.mat-mdc-select-value'));
    const icons = triggers.map(t => t.querySelector('mat-icon')?.textContent?.trim() ?? null);
    // X axis (date_year), group by (none: no icon), Y metrics (multiple: no trigger icon), chart type (line)
    expect(icons).toEqual(['calendar_today', null, null, 'show_chart']);
    fixture.destroy();
  });

  it('gives every X-axis option an icon', async () => {
    const fixture = await render();
    ((fixture.nativeElement as HTMLElement).querySelector('.mat-mdc-select-trigger') as HTMLElement).click();
    fixture.detectChanges();
    await fixture.whenStable();
    const options = Array.from(document.querySelectorAll('mat-option'));
    expect(options.length).toBe(21);
    expect(options.every(o => !!o.querySelector('mat-icon')?.textContent?.trim())).toBe(true);
    expect(options.some(o => o.querySelector('mat-icon')?.textContent?.trim() === 'sort')).toBe(false);
    fixture.destroy();
  });
});

describe('Correlation error recovery', () => {
  it('shows an explicit status when every series is hidden without removing its data table', async () => {
    const api = { get: vi.fn(() => of({ labels: ['2025'], metrics: { aggregate: [7], aesthetic: [6] }, x_axis: 'date_year', group_by: '' })) };
    TestBed.configureTestingModule({
      imports: [StatsCorrelationsTabComponent],
      providers: [
        { provide: ApiService, useValue: api },
        { provide: AuthService, useValue: { status: signal({ authenticated: true }), identity: signal('owner'), isAuthenticated: signal(true), token: 'token' } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), locale: signal('en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    const fixture = TestBed.createComponent(StatsCorrelationsTabComponent);
    fixture.detectChanges();
    await fixture.componentInstance.loadCorrelation();
    fixture.detectChanges();
    const inputs = fixture.nativeElement.querySelectorAll('fieldset input[type="checkbox"]') as NodeListOf<HTMLInputElement>;
    expect(inputs).toHaveLength(2);
    expect(fixture.nativeElement.querySelectorAll('fieldset mat-checkbox')).toHaveLength(2);
    for (const input of inputs) { input.click(); fixture.detectChanges(); }
    expect(fixture.nativeElement.querySelector('[role="status"]')?.textContent).toContain('stats.no_series_selected');
    expect(fixture.nativeElement.querySelector('canvas')).toBeNull();
    expect(fixture.nativeElement.querySelector('details table')?.textContent).toContain('7');
    fixture.destroy();
  });

  it('keeps Retry focused through another failure and restores focus after success', async () => {
    const pending = new Subject<any>();
    const api = { get: vi.fn((): Observable<any> => throwError(() => new Error('offline'))) };
    TestBed.configureTestingModule({
      imports: [StatsCorrelationsTabComponent],
      providers: [
        { provide: ApiService, useValue: api },
        { provide: AuthService, useValue: { status: signal({ authenticated: true }), identity: signal('owner'), isAuthenticated: signal(true), token: 'token' } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), locale: signal('en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    const fixture = TestBed.createComponent(StatsCorrelationsTabComponent);
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
    await fixture.componentInstance.loadCorrelation();
    fixture.detectChanges();
    const retry = fixture.nativeElement.querySelector('[role="alert"] button') as HTMLButtonElement;
    expect(retry).toBeTruthy();
    retry.focus();
    api.get.mockReturnValueOnce(pending);
    retry.click();
    fixture.detectChanges();
    expect(document.activeElement).toBe(retry);
    expect(retry.getAttribute('aria-disabled')).toBe('true');
    pending.error(new Error('offline'));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(document.activeElement).toBe(retry);
    api.get.mockReturnValueOnce(of({ labels: [], metrics: {}, x_axis: 'date_year', group_by: '' }));
    retry.click();
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(document.activeElement?.textContent).toContain('stats.metric_correlations');
    fixture.destroy();
    fixture.nativeElement.remove();
  });
});

describe('buildCorrelationCsvRecords', () => {
  it('returns empty when no correlation data is loaded', () => {
    expect(buildCorrelationCsvRecords(null, ['aggregate'])).toEqual([]);
  });

  it('builds one row per label from the metrics branch', () => {
    const records = buildCorrelationCsvRecords(
      {
        labels: ['2023', '2024'],
        metrics: { aggregate: [7.1, 7.8], aesthetic: [6.0, 6.5] },
        x_axis: 'date_year',
        group_by: '',
      },
      ['aggregate', 'aesthetic'],
    );
    expect(records).toEqual([
      { date_year: '2023', aggregate: 7.1, aesthetic: 6.0 },
      { date_year: '2024', aggregate: 7.8, aesthetic: 6.5 },
    ]);
  });

  it('builds one row per group+label from the groups branch', () => {
    const records = buildCorrelationCsvRecords(
      {
        labels: ['2023', '2024'],
        groups: {
          canon: { '2023': { aggregate: 7.0 }, '2024': { aggregate: 7.5 } },
          nikon: { '2023': { aggregate: 6.8 }, '2024': { aggregate: 7.2 } },
        },
        x_axis: 'date_year',
        group_by: 'camera_model',
      },
      ['aggregate'],
    );
    expect(records).toEqual([
      { date_year: '2023', group: 'canon', aggregate: 7.0 },
      { date_year: '2024', group: 'canon', aggregate: 7.5 },
      { date_year: '2023', group: 'nikon', aggregate: 6.8 },
      { date_year: '2024', group: 'nikon', aggregate: 7.2 },
    ]);
  });
});

describe('correlationSeries', () => {
  it('preserves visible series colors and reuses only the freed slot', () => {
    const initial = allocateSeriesSlots(['a', 'b', 'c'], {});
    expect(initial).toEqual({ a: 0, b: 1, c: 2 });
    const changed = allocateSeriesSlots(['b', 'c', 'd'], initial);
    expect(changed).toEqual({ b: 1, c: 2, d: 0 });
  });

  it('shows every selected metric for every group and retains missing values', () => {
    const data = { labels: ['2024', '2025'], x_axis: 'date_year', group_by: 'camera_model', groups: {
      Canon: { '2024': { aggregate: 7, aesthetic: 6 }, '2025': { aggregate: 8 } },
      Nikon: { '2024': { aggregate: 5, aesthetic: 4 } },
    } };
    const series = correlationSeries(data, ['aggregate', 'aesthetic'], metric => `translated ${metric}`);
    expect(series.map(row => row.label)).toEqual(['Canon · translated aggregate', 'Canon · translated aesthetic', 'Nikon · translated aggregate', 'Nikon · translated aesthetic']);
    expect(series.map(row => row.values)).toEqual([[7, 8], [6, null], [5, null], [4, null]]);
    expect(series.map(row => [row.groupIndex, row.metricIndex])).toEqual([[0, 0], [0, 1], [1, 0], [1, 1]]);
  });
});
