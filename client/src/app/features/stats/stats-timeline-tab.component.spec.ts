import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { Observable, of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { StatsFiltersService } from './stats-filters.service';
import { StatsTimelineTabComponent, HeatmapColorPipe, HeatmapSizePipe, formatStatsMonth } from './stats-timeline-tab.component';

describe('StatsTimelineTabComponent', () => {
  let component: StatsTimelineTabComponent;
  let owner: ReturnType<typeof signal<string>>;

  beforeEach(() => {
    owner = signal('owner-a');
    TestBed.configureTestingModule({
      providers: [
        StatsTimelineTabComponent,
        { provide: ApiService, useValue: { get: vi.fn(() => of({})) } },
        { provide: AuthService, useValue: { status: signal({ authenticated: true }), identity: owner, isAuthenticated: signal(true), token: 'token-a' } },
        { provide: I18nService, useValue: { t: vi.fn((k: string) => k), locale: signal('en'), currentLang: vi.fn(() => 'en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    component = TestBed.inject(StatsTimelineTabComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('clears previous values and shows a failure when the next request fails', async () => {
    TestBed.tick();
    component.timeline.set([{ period: '2025-01', count: 8, avg_score: 5 }]);
    component.heatmapGrid.set([[4]]);
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(throwError(() => new Error('offline')));
    await component.loadTimeline();
    expect(component.timelineFailed()).toBe(true);
    expect(component.timeline()).toEqual([]);
    expect(component.heatmapGrid()).toEqual([]);
  });

  it('ignores a response for an earlier filter', async () => {
    TestBed.tick();
    const pending = new Subject<any>();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(pending);
    const request = component.loadTimeline();
    TestBed.inject(StatsFiltersService).filterCategory.set('portrait');
    pending.next({ monthly: [{ month: '2025-01', count: 8 }] });
    pending.complete();
    await request;
    expect(component.timeline()).toEqual([]);
  });

  it('ignores a late response from the previous owner and loads the new owner', async () => {
    TestBed.tick();
    const pending = new Subject<any>();
    const api = vi.mocked(TestBed.inject(ApiService).get);
    api.mockReturnValueOnce(pending);
    const request = component.loadTimeline();
    owner.set('owner-b');
    pending.next({ monthly: [{ month: '2025-01', count: 8 }] });
    pending.complete();
    await request;
    expect(component.timeline()).toEqual([]);
    api.mockReturnValueOnce(of({ monthly: [{ month: '2026-01', count: 3 }] }));
    TestBed.tick();
    await Promise.resolve();
    expect(component.timeline().map(row => row.count)).toEqual([3]);
  });

  it('ignores a response after destruction', async () => {
    TestBed.tick();
    const pending = new Subject<any>();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(pending);
    const request = component.loadTimeline();
    TestBed.resetTestingModule();
    pending.next({ monthly: [{ month: '2025-01', count: 8 }] });
    pending.complete();
    await request;
    expect(component.timeline()).toEqual([]);
  });

  it('does not load while signed out and clears previous data', async () => {
    TestBed.tick();
    component.timeline.set([{ period: '2025-01', count: 8, avg_score: 5 }]);
    (TestBed.inject(AuthService).isAuthenticated as ReturnType<typeof signal<boolean>>).set(false);
    const api = vi.mocked(TestBed.inject(ApiService).get);
    api.mockClear();
    await component.loadTimeline();
    expect(api).not.toHaveBeenCalled();
    expect(component.timeline()).toEqual([]);
  });

  it('ignores a late response after the credential changes', async () => {
    TestBed.tick();
    const pending = new Subject<any>();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(pending);
    const request = component.loadTimeline();
    Object.defineProperty(TestBed.inject(AuthService), 'token', { value: 'token-b', configurable: true });
    pending.next({ monthly: [{ month: '2025-01', count: 8 }] });
    pending.complete();
    await request;
    expect(component.timeline()).toEqual([]);
  });

  it('clears and reloads the timeline on a same-owner credential rotation', async () => {
    TestBed.tick();
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ monthly: [{ month: '2025-01', count: 8 }] }));
    await component.loadTimeline();
    expect(component.timeline().map(row => row.count)).toEqual([8]);
    const auth = TestBed.inject(AuthService);
    Object.defineProperty(auth, 'token', { value: 'token-b', configurable: true });
    vi.mocked(TestBed.inject(ApiService).get).mockReturnValueOnce(of({ monthly: [{ month: '2026-01', count: 3 }] }));
    (auth.status as ReturnType<typeof signal<any>>).set({ authenticated: true });
    TestBed.tick();
    await Promise.resolve();
    expect(component.timeline().map(row => row.count)).toEqual([3]);
  });
});

describe('Timeline retry focus', () => {
  it('keeps Retry focused on failure and moves focus to the heading only after success', async () => {
    const pending = new Subject<any>();
    const api = { get: vi.fn((): Observable<any> => throwError(() => new Error('offline'))) };
    TestBed.configureTestingModule({
      imports: [StatsTimelineTabComponent],
      providers: [
        { provide: ApiService, useValue: api },
        { provide: AuthService, useValue: { status: signal({ authenticated: true }), identity: signal('owner'), isAuthenticated: signal(true), token: 'token' } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), locale: signal('en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    const fixture = TestBed.createComponent(StatsTimelineTabComponent);
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
    await fixture.componentInstance.loadTimeline();
    await fixture.whenStable();
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
    expect(retry.getAttribute('aria-disabled')).not.toBe('true');
    const next = new Subject<any>();
    api.get.mockReturnValueOnce(next);
    retry.click();
    fixture.detectChanges();
    const elsewhere = document.createElement('button');
    document.body.appendChild(elsewhere);
    elsewhere.focus();
    next.next({ monthly: [] });
    next.complete();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(document.activeElement).toBe(elsewhere);
    elsewhere.remove();
    await fixture.componentInstance.loadTimeline();
    fixture.detectChanges();
    const retryAgain = fixture.nativeElement.querySelector('[role="alert"] button') as HTMLButtonElement;
    retryAgain.focus();
    api.get.mockReturnValueOnce(of({ monthly: [] }));
    retryAgain.click();
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(document.activeElement?.textContent).toContain('stats.photos_over_time');
    fixture.destroy();
    fixture.nativeElement.remove();
  });
});

describe('formatStatsMonth', () => {
  it('formats valid months with the viewer locale and leaves unknown periods alone', () => {
    expect(formatStatsMonth('2026-10', 'de')).toBe(new Intl.DateTimeFormat('de', { month: 'short', year: 'numeric' }).format(new Date(2026, 9, 15)));
    expect(formatStatsMonth('2026-13', 'de')).toBe('2026-13');
    expect(formatStatsMonth('unknown', 'de')).toBe('unknown');
  });
});

describe('HeatmapColorPipe', () => {
  let pipe: HeatmapColorPipe;
  beforeEach(() => { pipe = new HeatmapColorPipe(); });

  it('should return transparent for count=0', () => {
    expect(pipe.transform(0, 100)).toBe('transparent');
  });

  it('should return color-mix string for non-zero count', () => {
    // formula: 40 + 60*(count/max) → 50/100 → 70%
    const result = pipe.transform(50, 100);
    expect(result).toBe('color-mix(in srgb, var(--facet-accent) 70%, transparent)');
  });

  it('should return 100% color-mix for count=max', () => {
    const result = pipe.transform(100, 100);
    expect(result).toBe('color-mix(in srgb, var(--facet-accent) 100%, transparent)');
  });
});

describe('HeatmapSizePipe', () => {
  let pipe: HeatmapSizePipe;
  beforeEach(() => { pipe = new HeatmapSizePipe(); });

  it('should return 0 for count=0', () => {
    expect(pipe.transform(0, 100)).toBe(0);
  });

  it('should return at least 4 for non-zero count', () => {
    expect(pipe.transform(1, 1000)).toBeGreaterThanOrEqual(4);
  });

  it('should return 28 for count=max', () => {
    expect(pipe.transform(100, 100)).toBe(28);
  });

  it('should scale with sqrt of ratio', () => {
    const small = pipe.transform(10, 100);
    const large = pipe.transform(90, 100);
    expect(large).toBeGreaterThan(small);
  });
});
