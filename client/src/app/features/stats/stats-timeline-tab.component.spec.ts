import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { StatsFiltersService } from './stats-filters.service';
import { StatsTimelineTabComponent, HeatmapColorPipe, HeatmapSizePipe } from './stats-timeline-tab.component';

describe('StatsTimelineTabComponent', () => {
  let component: StatsTimelineTabComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        StatsTimelineTabComponent,
        { provide: ApiService, useValue: { get: jest.fn(() => of({})) } },
        { provide: I18nService, useValue: { t: jest.fn((k: string) => k), currentLang: jest.fn(() => 'en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    component = TestBed.inject(StatsTimelineTabComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
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
