import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { Observable, of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { StatsFiltersService } from './stats-filters.service';
import { correlationSeries, StatsCorrelationsTabComponent } from './stats-correlations-tab.component';
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

  it('uses translation keys for chart-table headers while retaining raw CSV keys', async () => {
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ labels: ['2025'], metrics: { aggregate: [7], aesthetic: [6] }, x_axis: 'date_year', group_by: '' }));
    await component.loadCorrelation();
    expect(component.accessibleColumnLabels()).toEqual([
      'stats.correlations.dimensions.date_year', 'stats.correlations.metrics.aggregate', 'stats.correlations.metrics.aesthetic',
    ]);
    expect(buildCorrelationCsvRecords(component.currentData(), ['aggregate', 'aesthetic'])[0]).toEqual({ date_year: '2025', aggregate: 7, aesthetic: 6 });
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

describe('Correlation error recovery', () => {
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
