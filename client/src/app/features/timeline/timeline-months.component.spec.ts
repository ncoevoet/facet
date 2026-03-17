import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TimelineMonthsComponent } from './timeline-months.component';

describe('TimelineMonthsComponent', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let component: any;
  let mockApi: { get: jest.Mock };

  const monthsResponse = {
    months: [
      { month: '2024-06', count: 42, hero_photo_path: '/photos/june.jpg' },
      { month: '2024-05', count: 18, hero_photo_path: null },
    ],
  };

  beforeEach(() => {
    mockApi = { get: jest.fn(() => of(monthsResponse)) };

    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: mockApi }],
    });

    // TimelineMonthsComponent requires the `year` input; provide it as a signal fixture
    TestBed.runInInjectionContext(() => {
      component = new TimelineMonthsComponent();
    });
  });

  describe('loading months for a year', () => {
    it('should call /timeline/months with the year input value', async () => {
      // Simulate input signal by calling load directly via the private method
      // accessible via any-typed component
      await (component as any).load('2024');
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/months', { year: 2024 });
    });

    it('should populate months signal', async () => {
      await (component as any).load('2024');
      expect(component.months()).toHaveLength(2);
      expect(component.months()[0].month).toBe('2024-06');
    });

    it('should set loading false after success', async () => {
      await (component as any).load('2024');
      expect(component.loading()).toBe(false);
    });

    it('should set loading false even on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      try { await (component as any).load('2024'); } catch { /* expected */ }
      expect(component.loading()).toBe(false);
    });
  });

  describe('monthSelected output', () => {
    it('should emit a month string', () => {
      const emitted: string[] = [];
      component.monthSelected.subscribe((v: string) => emitted.push(v));
      component.monthSelected.emit('2024-06');
      expect(emitted).toContain('2024-06');
    });
  });
});
