import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { StatsFiltersService } from './stats-filters.service';
import { StatsCorrelationsTabComponent } from './stats-correlations-tab.component';
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
        { provide: I18nService, useValue: { t: vi.fn((k: string) => k), currentLang: vi.fn(() => 'en') } },
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
