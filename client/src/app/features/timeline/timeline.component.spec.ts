import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { TimelineFiltersService } from './timeline-filters.service';
import { TimelineComponent } from './timeline.component';
import { PageContextService } from '../../core/agent/page-context.service';
import { GalleryStore } from '../gallery/gallery.store';

const timelinePersonalReset = { type: '', hide_rejected: 'false', favorites_only: 'false', is_monochrome: 'false', review_status: '', show_rejected: 'false', blinks_only: 'false', duplicates_only: 'false' };

describe('TimelineComponent', () => {

  let component: any;
  let mockRouter: { navigate: Mock };
  let mockFilters: {
    dateFrom: ReturnType<typeof signal<string>>;
    dateTo: ReturnType<typeof signal<string>>;
    sortDirection: ReturnType<typeof signal<'older' | 'newer'>>;
    showOverview: ReturnType<typeof signal<boolean>>;
  };
  let mockStore: { viewFilterParams: ReturnType<typeof signal>; showAllHidden: Mock };
  let paramMapSubject: { get: Mock };

  const noneHidden = {
    hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
  };

  beforeEach(() => {
    mockRouter = { navigate: vi.fn() };
    mockFilters = {
      dateFrom: signal(''),
      dateTo: signal(''),
      sortDirection: signal<'older' | 'newer'>('older'),
      showOverview: signal(false),
    };
    mockStore = { viewFilterParams: signal({ ...noneHidden }), showAllHidden: vi.fn() };
    paramMapSubject = { get: vi.fn().mockReturnValue(null) };

    TestBed.configureTestingModule({
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: TimelineFiltersService, useValue: mockFilters },
        { provide: ActivatedRoute, useValue: { paramMap: of(paramMapSubject) } },
        { provide: GalleryStore, useValue: mockStore },
      ],
    });
    component = TestBed.runInInjectionContext(() => new TimelineComponent());
  });

  describe('page context', () => {
    it('registers the timeline page and reads its filters live', () => {
      const context = TestBed.inject(PageContextService);
      expect(context.snapshot()).toEqual({ id: 'timeline', date_from: '', date_to: '', sort: 'older' });
      mockFilters.sortDirection.set('newer');
      expect(context.snapshot()).toMatchObject({ sort: 'newer' });
    });
  });

  it('retains calendar mode when timeline navigation recreates the component', () => {
    component.showOverview.set(true);
    const recreated: any = TestBed.runInInjectionContext(() => new TimelineComponent());
    expect(recreated.showOverview()).toBe(true);
    recreated.showOverview.set(false);
    expect(component.showOverview()).toBe(false);
  });

  describe('initial state', () => {
    it('should start at years level with no route params', () => {
      expect(component.level()).toBe('years');
    });

    it('should be at months level when year param is set', () => {
      paramMapSubject.get.mockImplementation((key: string) => key === 'year' ? '2024' : null);
      // Re-create with updated route
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      expect(component.level()).toBe('months');
      expect(component.year()).toBe('2024');
    });

    it('should be at days level when year and month params are set', () => {
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '6' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      expect(component.level()).toBe('days');
      expect(component.year()).toBe('2024');
      expect(component.month()).toBe('6');
    });
  });

  describe('selectedMonthFormatted', () => {
    it('returns empty string when no params', () => {
      expect(component.selectedMonthFormatted()).toBe('');
    });

    it('formats month with zero padding', () => {
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '6' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      expect(component.selectedMonthFormatted()).toBe('2024-06');
    });
  });

  describe('navigation methods', () => {
    it('goToYears navigates to /timeline', () => {
      component.goToYears();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/timeline']);
    });

    it('goToMonths navigates to /timeline/:year', () => {
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '6' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      component.goToMonths();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/timeline', '2024']);
    });

    it('onYearSelected navigates to /timeline/:year', () => {
      component.onYearSelected('2024');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/timeline', '2024']);
    });

    it('onMonthSelected navigates to /timeline/:year/:month', () => {
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      component.onMonthSelected('2024-06');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/timeline', '2024', '6']);
    });
  });

  describe('day selection', () => {
    it('onDaySelected navigates to gallery with date filter params', () => {
      component.onDaySelected('2024-06-15');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        queryParams: {
          ...Object.fromEntries(Object.keys(noneHidden).map(key => [key, 'false'])),
          ...timelinePersonalReset,
          date_from: '2024-06-15',
          date_to: '2024-06-15',
          sort: 'date_taken',
          sort_direction: 'ASC',
        },
      });
    });
  });

  describe('anyHiddenByFilters (reachability banner)', () => {
    it('is false when every hide toggle is off', () => {
      expect(component.anyHiddenByFilters()).toBe(false);
    });

    it('is true when at least one hide toggle is on', () => {
      mockStore.viewFilterParams.set({ ...noneHidden, hide_bursts: '1' });
      expect(component.anyHiddenByFilters()).toBe(true);
    });

    it('goes back to false once every toggle is off again', () => {
      mockStore.viewFilterParams.set({ ...noneHidden, hide_panoramas: '1' });
      expect(component.anyHiddenByFilters()).toBe(true);
      mockStore.viewFilterParams.set({ ...noneHidden });
      expect(component.anyHiddenByFilters()).toBe(false);
    });
  });
});


describe('Timeline missing-date and range transitions', () => {
  it.each([
    ['2024-02-20', '2024-02-10'],
    ['2024-03-01', '2024-03-31'],
  ])('keeps an empty date intersection on the timeline until corrected (%s, %s)', (from, to) => {
    const navigate = vi.fn();
    const dateFrom = signal(from); const dateTo = signal(to);
    TestBed.configureTestingModule({ providers: [
      { provide: Router, useValue: { navigate } },
      { provide: ActivatedRoute, useValue: { paramMap: of({ get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '2' : null }) } },
      { provide: TimelineFiltersService, useValue: { dateFrom, dateTo, sortDirection: signal('older'), showOverview: signal(false) } },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({ hide_bursts: '1' }) } },
    ] });
    const component: any = TestBed.runInInjectionContext(() => new TimelineComponent());
    component.viewRange();
    expect(navigate).not.toHaveBeenCalled();
    expect(component.emptyRange()).toBe(true);
    dateFrom.set('2024-02-29'); dateTo.set('2024-02-29');
    expect(component.emptyRange()).toBe(false);
    component.viewRange();
    expect(navigate).toHaveBeenCalledWith(['/'], { queryParams: {
      ...timelinePersonalReset, hide_bursts: 'true', date_from: '2024-02-29', date_to: '2024-02-29',
      sort: 'date_taken', sort_direction: 'DESC',
    } });
  });

  it('opens the selected route month intersected with the typed range instead of widening to the whole library', () => {
    const navigate = vi.fn();
    TestBed.configureTestingModule({ providers: [
      { provide: Router, useValue: { navigate } },
      { provide: ActivatedRoute, useValue: { paramMap: of({ get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '2' : null }) } },
      { provide: TimelineFiltersService, useValue: { dateFrom: signal('2024-02-12'), dateTo: signal(''), sortDirection: signal('older'), showOverview: signal(false) } },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({ hide_bursts: '1' }) } },
    ] });
    const component: any = TestBed.runInInjectionContext(() => new TimelineComponent());
    component.viewRange();
    expect(navigate).toHaveBeenCalledWith(['/'], { queryParams: { ...timelinePersonalReset, hide_bursts: 'true', date_from: '2024-02-12', date_to: '2024-02-29', sort: 'date_taken', sort_direction: 'DESC' } });
  });
  it('carries only visibility into the chosen date scope, and resets the timeline window', () => {
    const navigate = vi.fn();
    const dateFrom = signal('2026-01-01'); const dateTo = signal('2026-02-01');
    TestBed.configureTestingModule({ providers: [
      { provide: Router, useValue: { navigate } },
      { provide: ActivatedRoute, useValue: { paramMap: of({ get: () => null }) } },
      { provide: TimelineFiltersService, useValue: { dateFrom, dateTo, sortDirection: signal('older'), showOverview: signal(false) } },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({ hide_bursts: '1' }) } },
    ] });
    const component: any = TestBed.runInInjectionContext(() => new TimelineComponent());
    component.viewRange();
    expect(navigate).toHaveBeenLastCalledWith(['/'], { queryParams: { ...timelinePersonalReset, hide_bursts: 'true', date_from: '2026-01-01', date_to: '2026-02-01', sort: 'date_taken', sort_direction: 'DESC' } });
    component.viewUnknownDates();
    expect(navigate).toHaveBeenLastCalledWith(['/'], { queryParams: { ...timelinePersonalReset, hide_bursts: 'true', no_capture_date: '1', sort: 'filename', sort_direction: 'ASC' } });
    component.resetDates();
    expect(dateFrom()).toBe(''); expect(dateTo()).toBe('');
    expect(navigate).toHaveBeenLastCalledWith(['/timeline']);
  });
});
