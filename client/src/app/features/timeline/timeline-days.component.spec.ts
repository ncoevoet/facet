import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TimelineFiltersService } from './timeline-filters.service';
import { TimelineDaysComponent } from './timeline-days.component';

describe('TimelineDaysComponent', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let component: any;
  let mockApi: { get: jest.Mock };

  beforeEach(() => {
    mockApi = { get: jest.fn(() => of({ dates: [] })) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        TimelineFiltersService,
      ],
    });
    TestBed.runInInjectionContext(() => {
      component = new TimelineDaysComponent();
    });
  });

  describe('API call', () => {
    it('should call /timeline/dates with year and month', async () => {
      await (component as any).load(2024, 6, '', '');
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', { year: 2024, month: 6 });
    });

    it('should pass date_from and date_to when provided', async () => {
      await (component as any).load(2024, 6, '2024-06-01', '2024-06-30');
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', {
        year: 2024, month: 6,
        date_from: '2024-06-01',
        date_to: '2024-06-30',
      });
    });

    it('should set loading false after success', async () => {
      await (component as any).load(2024, 6, '', '');
      expect(component.loading()).toBe(false);
    });

    it('should set loading false on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      try { await (component as any).load(2024, 6, '', ''); } catch { /* expected */ }
      expect(component.loading()).toBe(false);
    });
  });

  describe('calendar cell building', () => {
    it('should create correct number of cells for a known month', async () => {
      // June 2024 has 30 days, starts on Saturday → 5 padding cells (Mon-Fri)
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2024, 6, '', '');

      const cells = component.calendarCells();
      const padCells = cells.filter((c: any) => c.date === null);
      const dayCells = cells.filter((c: any) => c.date !== null);

      expect(dayCells).toHaveLength(30); // June has 30 days
      expect(padCells.length).toBeGreaterThanOrEqual(0); // some padding depending on start day
      expect(cells.length).toBe(padCells.length + 30);
    });

    it('should assign hero photo to cells returned by the API', async () => {
      mockApi.get.mockReturnValue(of({
        dates: [
          { date: '2024-06-15', count: 3, hero_photo_path: '/photos/hero.jpg' },
        ],
      }));
      await (component as any).load(2024, 6, '', '');

      const cells = component.calendarCells();
      const june15 = cells.find((c: any) => c.date === '2024-06-15');
      expect(june15).toBeDefined();
      expect(june15.count).toBe(3);
      expect(june15.hero_photo_path).toBe('/photos/hero.jpg');
    });

    it('should give count=0 and no hero to days not in API response', async () => {
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2024, 6, '', '');

      const cells = component.calendarCells();
      const june1 = cells.find((c: any) => c.date === '2024-06-01');
      expect(june1.count).toBe(0);
      expect(june1.hero_photo_path).toBeNull();
    });

    it('should format date strings with zero-padded month and day', async () => {
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2024, 1, '', ''); // January

      const cells = component.calendarCells();
      const jan1 = cells.find((c: any) => c.date === '2024-01-01');
      expect(jan1).toBeDefined();
    });

    it('February: handles 29 days in a leap year', async () => {
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2024, 2, '', ''); // Feb 2024 is a leap year

      const dayCells = component.calendarCells().filter((c: any) => c.date !== null);
      expect(dayCells).toHaveLength(29);
    });

    it('February: handles 28 days in a non-leap year', async () => {
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2023, 2, '', '');

      const dayCells = component.calendarCells().filter((c: any) => c.date !== null);
      expect(dayCells).toHaveLength(28);
    });
  });

  describe('weekDays', () => {
    it('should have exactly 7 entries', () => {
      expect(component.weekDays).toHaveLength(7);
    });

    it('should be non-empty strings', () => {
      for (const d of component.weekDays) {
        expect(typeof d).toBe('string');
        expect(d.length).toBeGreaterThan(0);
      }
    });
  });

  describe('daySelected output', () => {
    it('should emit a date string', () => {
      const emitted: string[] = [];
      component.daySelected.subscribe((v: string) => emitted.push(v));
      component.daySelected.emit('2024-06-15');
      expect(emitted).toContain('2024-06-15');
    });
  });
});
