import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { StatsFiltersService } from './stats-filters.service';
import { StatsTimelineTabComponent, HeatmapColorPipe, HeatmapSizePipe } from './stats-timeline-tab.component';

describe('StatsTimelineTabComponent', () => {
  let component: StatsTimelineTabComponent;
  let api: { get: Mock };
  const populated = {
    monthly: [{ month: '2024-06', count: 12, avg_score: 7 }],
    heatmap: [{ day: 2, hour: 8, count: 12 }],
  };
  const filters = () => TestBed.inject(StatsFiltersService);

  beforeEach(() => {
    api = { get: vi.fn(() => of({ monthly: [], heatmap: [] })) };
    TestBed.configureTestingModule({
      providers: [
        StatsTimelineTabComponent,
        { provide: ApiService, useValue: api },
        { provide: I18nService, useValue: { t: vi.fn((k: string) => k), currentLang: vi.fn(() => 'en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    component = TestBed.inject(StatsTimelineTabComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('loaded timeline ownership', () => {
    beforeEach(async () => {
      TestBed.tick();
      await Promise.resolve();
      api.get.mockReturnValueOnce(of(populated));
      await component.loadTimeline();
    });

    it('clears every derived chart after a populated query becomes empty', async () => {
      expect(component.dayOfWeekData()[2].count).toBe(12);
      expect(component.hourOfDayData()[8].count).toBe(12);
      expect(component.heatmapMax()).toBe(12);
      expect(component.yearlyData()).toEqual([{ year: '2024', count: 12 }]);
      await component.loadTimeline();
      expect(component.timeline()).toEqual([]);
      expect(component.yearlyData()).toEqual([]);
      expect(component.dayOfWeekData()).toEqual([]);
      expect(component.hourOfDayData()).toEqual([]);
      expect(component.heatmapRows()).toEqual([]);
      expect(component.heatmapMax()).toBe(1);
    });

    it.each(['success', 'failure'])('ignores a queued obsolete %s while the new filter is loading', async outcome => {
      const old = new Subject<typeof populated>();
      const latest = new Subject<typeof populated>();
      api.get.mockReturnValueOnce(old).mockReturnValueOnce(latest);
      filters().filterCategory.set('portrait');
      TestBed.tick();
      if (outcome === 'success') old.next(populated);
      else old.error(new Error('obsolete failure'));
      filters().dateFrom.set('2025-01-01');
      TestBed.tick();
      await Promise.resolve();
      expect(component.timelineLoading()).toBe(true);
      expect(component.timeline()).toEqual([]);
      expect(component.heatmapRows()).toEqual([]);
      latest.next({ monthly: [{ month: '2025-01', count: 2, avg_score: 4 }], heatmap: [] });
      latest.complete();
      await Promise.resolve();
      expect(component.timeline()).toEqual([{ period: '2025-01', count: 2, avg_score: 4 }]);
      expect(component.timelineLoading()).toBe(false);
      expect((component as any).timelineError()).toBe(false);
    });

    it('clears stale data on failure and recovers on retry', async () => {
      api.get.mockReturnValueOnce(throwError(() => new Error('failed')));
      await component.loadTimeline();
      expect((component as any).timelineError()).toBe(true);
      expect(component.timelineLoading()).toBe(false);
      expect(component.timeline()).toEqual([]);
      expect(component.heatmapRows()).toEqual([]);
      api.get.mockReturnValueOnce(of(populated));
      await component.loadTimeline();
      expect((component as any).timelineError()).toBe(false);
      expect(component.heatmapGrid()[2][8]).toBe(12);
    });

    it('unsubscribes on destroy and does not publish queued results', async () => {
      const pending = new Subject<typeof populated>();
      api.get.mockReturnValueOnce(pending);
      const done = component.loadTimeline();
      expect(pending.observed).toBe(true);
      TestBed.resetTestingModule();
      expect(pending.observed).toBe(false);
      await done;
      expect(component.timeline()).toEqual([]);
    });
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
