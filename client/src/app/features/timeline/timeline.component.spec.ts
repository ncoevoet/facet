import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { TimelineFiltersService } from './timeline-filters.service';
import { TimelineComponent } from './timeline.component';

describe('TimelineComponent', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let component: any;
  let mockRouter: { navigate: jest.Mock };
  let mockFilters: {
    dateFrom: ReturnType<typeof signal<string>>;
    dateTo: ReturnType<typeof signal<string>>;
    sortDirection: ReturnType<typeof signal<'older' | 'newer'>>;
  };
  let paramMapSubject: { get: jest.Mock };

  beforeEach(() => {
    mockRouter = { navigate: jest.fn() };
    mockFilters = {
      dateFrom: signal(''),
      dateTo: signal(''),
      sortDirection: signal<'older' | 'newer'>('older'),
    };
    paramMapSubject = { get: jest.fn().mockReturnValue(null) };

    TestBed.configureTestingModule({
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: TimelineFiltersService, useValue: mockFilters },
        { provide: ActivatedRoute, useValue: { paramMap: of(paramMapSubject) } },
      ],
    });
    component = TestBed.runInInjectionContext(() => new TimelineComponent());
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
          date_from: '2024-06-15',
          date_to: '2024-06-15',
          sort: 'date_taken',
          sort_direction: 'DESC',
        },
      });
    });
  });
});
