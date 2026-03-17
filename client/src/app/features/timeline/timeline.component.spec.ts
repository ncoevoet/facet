import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { Router } from '@angular/router';
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
    selectedYear: ReturnType<typeof signal<string>>;
    selectedMonth: ReturnType<typeof signal<string>>;
  };

  beforeEach(() => {
    mockRouter = { navigate: jest.fn() };
    mockFilters = {
      dateFrom: signal(''),
      dateTo: signal(''),
      sortDirection: signal<'older' | 'newer'>('older'),
      selectedYear: signal(''),
      selectedMonth: signal(''),
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: TimelineFiltersService, useValue: mockFilters },
      ],
    });
    component = TestBed.runInInjectionContext(() => new TimelineComponent());
  });

  describe('initial state', () => {
    it('should start at years level', () => {
      expect(component.level()).toBe('years');
    });

    it('ngOnInit should reset selectedYear and selectedMonth', () => {
      mockFilters.selectedYear.set('2024');
      mockFilters.selectedMonth.set('2024-06');
      component.ngOnInit();
      expect(mockFilters.selectedYear()).toBe('');
      expect(mockFilters.selectedMonth()).toBe('');
    });
  });

  describe('selectedMonthNumber', () => {
    it('returns empty string when no month selected', () => {
      mockFilters.selectedMonth.set('');
      expect(component.selectedMonthNumber()).toBe('');
    });

    it('extracts month number from YYYY-MM string', () => {
      mockFilters.selectedMonth.set('2024-06');
      expect(component.selectedMonthNumber()).toBe('6');
    });

    it('strips leading zero from month number', () => {
      mockFilters.selectedMonth.set('2024-03');
      expect(component.selectedMonthNumber()).toBe('3');
    });

    it('returns empty string for malformed month', () => {
      mockFilters.selectedMonth.set('2024');
      expect(component.selectedMonthNumber()).toBe('');
    });
  });

  describe('year selection', () => {
    it('onYearSelected sets selectedYear and advances to months level', () => {
      component.onYearSelected('2024');
      expect(mockFilters.selectedYear()).toBe('2024');
      expect(component.level()).toBe('months');
    });
  });

  describe('month selection', () => {
    it('onMonthSelected sets selectedMonth and advances to days level', () => {
      component.onMonthSelected('2024-06');
      expect(mockFilters.selectedMonth()).toBe('2024-06');
      expect(component.level()).toBe('days');
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

  describe('breadcrumb navigation', () => {
    it('goToYears resets to years level and clears filters', () => {
      mockFilters.selectedYear.set('2024');
      mockFilters.selectedMonth.set('2024-06');
      component.level.set('days');

      component.goToYears();

      expect(component.level()).toBe('years');
      expect(mockFilters.selectedYear()).toBe('');
      expect(mockFilters.selectedMonth()).toBe('');
    });

    it('goToMonths returns to months level and clears selectedMonth', () => {
      mockFilters.selectedYear.set('2024');
      mockFilters.selectedMonth.set('2024-06');
      component.level.set('days');

      component.goToMonths();

      expect(component.level()).toBe('months');
      expect(mockFilters.selectedMonth()).toBe('');
    });
  });
});
