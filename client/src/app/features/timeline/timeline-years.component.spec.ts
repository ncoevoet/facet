import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TimelineFiltersService } from './timeline-filters.service';
import { TimelineYearsComponent } from './timeline-years.component';

describe('TimelineYearsComponent', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let component: any;
  let mockApi: { get: jest.Mock };

  const yearsResponse = {
    years: [
      { year: '2024', count: 120, hero_photo_path: '/photos/a.jpg' },
      { year: '2023', count: 85, hero_photo_path: null },
    ],
  };

  beforeEach(() => {
    mockApi = { get: jest.fn(() => of(yearsResponse)) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        TimelineFiltersService,
      ],
    });
    component = TestBed.runInInjectionContext(() => new TimelineYearsComponent());
  });

  describe('load', () => {
    it('should call /timeline/years with empty params', async () => {
      await component.load('', '');
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/years', {});
    });

    it('should pass date_from and date_to when provided', async () => {
      await component.load('2024-01-01', '2024-12-31');
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/years', {
        date_from: '2024-01-01',
        date_to: '2024-12-31',
      });
    });

    it('should populate years signal', async () => {
      await component.load('', '');
      expect(component.years()).toHaveLength(2);
      expect(component.years()[0].year).toBe('2024');
      expect(component.years()[0].count).toBe(120);
      expect(component.years()[0].hero_photo_path).toBe('/photos/a.jpg');
    });

    it('should set loading false after success', async () => {
      await component.load('', '');
      expect(component.loading()).toBe(false);
    });

    it('should set loading false even on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      try { await component.load('', ''); } catch { /* expected */ }
      expect(component.loading()).toBe(false);
    });

    it('should accept entries with null hero_photo_path', async () => {
      await component.load('', '');
      expect(component.years()[1].hero_photo_path).toBeNull();
    });
  });
});
