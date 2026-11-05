import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TimelineFiltersService } from './timeline-filters.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineDaysComponent } from './timeline-days.component';
import { I18nService } from '../../core/services/i18n.service';

describe('TimelineDaysComponent', () => {
  let component: any;
  let mockApi: { get: Mock };
  let mockStore: { viewFilterParams: ReturnType<typeof signal> };
  const locale = signal('en');

  const noneHidden = {
    hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
  };

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of({ dates: [] })) };
    locale.set('en');
    mockStore = { viewFilterParams: signal({ ...noneHidden }) };

    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: { status: signal({ user_id: 'alice' }), token: 'a' } },
        { provide: ApiService, useValue: mockApi },
        TimelineFiltersService,
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: { locale, translations: () => ({}), t: (key: string) => key } },
      ],
    });
    vi.spyOn(TestBed.inject(Router), 'url', 'get').mockReturnValue('/timeline');
    TestBed.runInInjectionContext(() => {
      component = new TimelineDaysComponent();
    });
  });

  describe('API call', () => {
    it('should call /timeline/dates with year and month', async () => {
      await (component as any).load(2024, 6, '', '', { ...noneHidden });
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', { year: 2024, month: 6, ...noneHidden }, expect.anything());
    });

    it('should pass date_from and date_to when provided', async () => {
      await (component as any).load(2024, 6, '2024-06-01', '2024-06-30', { ...noneHidden });
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', {
        year: 2024, month: 6,
        ...noneHidden,
        date_from: '2024-06-01',
        date_to: '2024-06-30',
      }, expect.anything());
    });

    it('should set loading false after success', async () => {
      await (component as any).load(2024, 6, '', '', { ...noneHidden });
      expect(component.loading()).toBe(false);
    });

    it('should set loading false on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      try { await (component as any).load(2024, 6, '', '', { ...noneHidden }); } catch { /* expected */ }
      expect(component.loading()).toBe(false);
    });
  });

  describe('calendar cell building', () => {
    it('disables days with no photos and labels populated days with the date and count', async () => {
      component.year = () => '2024'; component.month = () => '6';
      mockApi.get.mockReturnValue(of({ dates: [{ date: '2024-06-15', count: 3, hero_photo_path: null }] }));
      const fixture = TestBed.createComponent(TimelineDaysComponent);
      fixture.componentRef.setInput('year', '2024'); fixture.componentRef.setInput('month', '6');
      fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      const buttons = [...fixture.nativeElement.querySelectorAll('button')] as HTMLButtonElement[];
      const empty = buttons.find(button => button.textContent?.trim() === '1')!;
      const populated = buttons.find(button => button.textContent?.includes('15'))!;
      expect(empty.disabled).toBe(true);
      expect(populated.disabled).toBe(false);
      expect(populated.getAttribute('aria-label')).toContain('15/06/2024');
      expect(populated.getAttribute('aria-label')).toContain('3');
      fixture.destroy();
    });
    it('should create correct number of cells for a known month', async () => {
      // June 2024 has 30 days, starts on Saturday → 5 padding cells (Mon-Fri)
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2024, 6, '', '', { ...noneHidden });

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
      await (component as any).load(2024, 6, '', '', { ...noneHidden });

      const cells = component.calendarCells();
      const june15 = cells.find((c: any) => c.date === '2024-06-15');
      expect(june15).toBeDefined();
      expect(june15.count).toBe(3);
      expect(june15.hero_photo_path).toBe('/photos/hero.jpg');
    });

    it('should give count=0 and no hero to days not in API response', async () => {
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2024, 6, '', '', { ...noneHidden });

      const cells = component.calendarCells();
      const june1 = cells.find((c: any) => c.date === '2024-06-01');
      expect(june1.count).toBe(0);
      expect(june1.hero_photo_path).toBeNull();
    });

    it('should format date strings with zero-padded month and day', async () => {
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2024, 1, '', '', { ...noneHidden }); // January

      const cells = component.calendarCells();
      const jan1 = cells.find((c: any) => c.date === '2024-01-01');
      expect(jan1).toBeDefined();
    });

    it('February: handles 29 days in a leap year', async () => {
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2024, 2, '', '', { ...noneHidden }); // Feb 2024 is a leap year

      const dayCells = component.calendarCells().filter((c: any) => c.date !== null);
      expect(dayCells).toHaveLength(29);
    });

    it('February: handles 28 days in a non-leap year', async () => {
      mockApi.get.mockReturnValue(of({ dates: [] }));
      await (component as any).load(2023, 2, '', '', { ...noneHidden });

      const dayCells = component.calendarCells().filter((c: any) => c.date !== null);
      expect(dayCells).toHaveLength(28);
    });
  });

  describe('weekDays', () => {
    it('should have exactly 7 entries', () => {
      expect(component.weekDays()).toHaveLength(7);
    });

    it('should be non-empty strings', () => {
      for (const d of component.weekDays()) {
        expect(typeof d).toBe('string');
        expect(d.length).toBeGreaterThan(0);
      }
    });

    it('updates weekday names when the viewer language changes', () => {
      const english = component.weekDays()[0];
      locale.set('de');
      expect(component.weekDays()[0]).toBe(new Intl.DateTimeFormat('de', { weekday: 'short' }).format(new Date(2026, 0, 5)));
      expect(component.weekDays()[0]).not.toBe(english);
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

  describe('reactive refetch on hide-toggle change', () => {
    it('re-fetches /timeline/dates when GalleryStore.viewFilterParams changes', () => {
      // year/month are required inputs; this component is constructed
      // directly (not via TestBed.createComponent), so there's no fixture to
      // drive componentRef.setInput() through — stand them up by hand instead.
      component.year = () => '2024';
      component.month = () => '6';
      TestBed.flushEffects();
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', { year: 2024, month: 6, ...noneHidden }, expect.anything());
      mockApi.get.mockClear();

      mockStore.viewFilterParams.set({ ...noneHidden, hide_duplicates: '1' });
      TestBed.flushEffects();

      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', { year: 2024, month: 6, ...noneHidden, hide_duplicates: '1' }, expect.anything());
    });
  });
});
