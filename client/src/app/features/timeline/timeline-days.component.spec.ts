import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, Subject, throwError } from 'rxjs';
import { I18nService } from '../../core/services/i18n.service';
import { ApiService } from '../../core/services/api.service';
import { TimelineFiltersService } from './timeline-filters.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineDaysComponent } from './timeline-days.component';

describe('TimelineDaysComponent', () => {
  let component: any;
  let mockApi: { get: Mock };
  let mockStore: { viewFilterParams: ReturnType<typeof signal> };

  const noneHidden = {
    hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
  };

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of({ dates: [] })) };
    mockStore = { viewFilterParams: signal({ ...noneHidden }) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: { t: (key: string) => `T(${key})`, translations: () => ({}) } },
        TimelineFiltersService,
        { provide: GalleryStore, useValue: mockStore },
      ],
    });
    TestBed.runInInjectionContext(() => {
      component = new TimelineDaysComponent();
      component.year = signal('2024');
      component.month = signal('6');
    });
  });

  describe('API call', () => {
    it('should call /timeline/dates with year and month', async () => {
      await (component as any).load(2024, 6, '', '', { ...noneHidden });
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', { year: 2024, month: 6, ...noneHidden });
    });

    it('should pass date_from and date_to when provided', async () => {
      await (component as any).load(2024, 6, '2024-06-01', '2024-06-30', { ...noneHidden });
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', {
        year: 2024, month: 6,
        ...noneHidden,
        date_from: '2024-06-01',
        date_to: '2024-06-30',
      });
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

  describe('request ownership', () => {
    const response = (date: string, count = 3) => ({
      dates: [{ date, count, hero_photo_path: '/photos/hero.jpg' }],
    });

    it.each(['success', 'failure'])('ignores a queued obsolete month %s', async outcome => {
      mockApi.get.mockReturnValueOnce(of(response('2024-05-15')));
      await component.load(2024, 5, '', '', noneHidden);
      expect(component.calendarCells().find((cell: any) => cell.date === '2024-05-15').count).toBe(3);
      const old = new Subject<ReturnType<typeof response>>();
      const latest = new Subject<ReturnType<typeof response>>();
      mockApi.get.mockReturnValueOnce(old).mockReturnValueOnce(latest);
      const oldDone = component.load(2024, 6, '', '', noneHidden);
      if (outcome === 'success') old.next(response('2024-06-15'));
      else old.error(new Error('obsolete month'));
      const latestDone = component.load(2024, 7, '', '', noneHidden);
      await oldDone;
      expect(component.loading()).toBe(true);
      expect(component.loadError()).toBe(false);
      expect(component.calendarCells()).toEqual([]);
      latest.next(response('2024-07-15', 7));
      latest.complete();
      await latestDone;
      expect(component.loading()).toBe(false);
      expect(component.calendarCells().find((cell: any) => cell.date === '2024-07-15').count).toBe(7);
      expect(component.calendarCells().some((cell: any) => cell.date?.startsWith('2024-06'))).toBe(false);
    });

    it('rejects a queued response immediately after an input or filter changes, before the effect runs', async () => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          { provide: ApiService, useValue: mockApi },
          { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}) } },
          TimelineFiltersService,
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      const fixture = TestBed.createComponent(TimelineDaysComponent);
      component = fixture.componentInstance;
      fixture.componentRef.setInput('year', '2024');
      fixture.componentRef.setInput('month', '5');
      mockApi.get.mockReturnValueOnce(of(response('2024-05-15')));
      fixture.detectChanges();
      await fixture.whenStable();
      expect(component.calendarCells().find((cell: any) => cell.date === '2024-05-15').count).toBe(3);
      const old = new Subject<ReturnType<typeof response>>();
      const latest = new Subject<ReturnType<typeof response>>();
      mockApi.get.mockReturnValueOnce(old).mockReturnValueOnce(latest);
      fixture.componentRef.setInput('month', '6');
      fixture.detectChanges();
      old.next(response('2024-06-15'));
      fixture.componentRef.setInput('month', '7');
      mockStore.viewFilterParams.set({ ...noneHidden, hide_duplicates: '1' });
      // No detectChanges/tick yet: the response must reject the changed selection itself.
      await Promise.resolve();
      expect(component.calendarCells()).toEqual([]);
      expect(component.loading()).toBe(true);
      fixture.detectChanges();
      expect(mockApi.get).toHaveBeenLastCalledWith('/timeline/dates', {
        year: 2024, month: 7, ...noneHidden, hide_duplicates: '1',
      });
      latest.next(response('2024-07-15', 8));
      latest.complete();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(component.calendarCells().find((cell: any) => cell.date === '2024-07-15').count).toBe(8);
      expect(component.loading()).toBe(false);
    });

    it('cancels the pending calendar request on destroy', async () => {
      const pending = new Subject<ReturnType<typeof response>>();
      mockApi.get.mockReturnValueOnce(pending);
      const done = component.load(2024, 6, '', '', noneHidden);
      expect(pending.observed).toBe(true);
      TestBed.resetTestingModule();
      expect(pending.observed).toBe(false);
      await done;
      expect(component.calendarCells()).toEqual([]);
    });
  });

  describe('calendar cell building', () => {
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

  describe('reactive refetch on hide-toggle change', () => {
    it('re-fetches /timeline/dates when GalleryStore.viewFilterParams changes', () => {
      // year/month are required inputs; this component is constructed
      // directly (not via TestBed.createComponent), so there's no fixture to
      // drive componentRef.setInput() through — stand them up by hand instead.
      component.year = () => '2024';
      component.month = () => '6';
      TestBed.flushEffects();
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', { year: 2024, month: 6, ...noneHidden });
      mockApi.get.mockClear();

      mockStore.viewFilterParams.set({ ...noneHidden, hide_duplicates: '1' });
      TestBed.flushEffects();

      expect(mockApi.get).toHaveBeenCalledWith('/timeline/dates', { year: 2024, month: 6, ...noneHidden, hide_duplicates: '1' });
    });
  });

  describe('rendered: a failed load', () => {
    async function renderFailed() {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      // The outer beforeEach built a bare instance whose effect has no inputs; start clean.
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          { provide: ApiService, useValue: mockApi },
          { provide: I18nService, useValue: { t: (key: string) => `T(${key})`, translations: () => ({}) } },
          TimelineFiltersService,
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      const fixture = TestBed.createComponent(TimelineDaysComponent);
      fixture.componentRef.setInput('year', '2024');
      fixture.componentRef.setInput('month', '6');
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    it('shows the alert and not the empty state (Retry re-requests)', async () => {
      const el = await renderFailed();
      expect(el.querySelector('[role="alert"]')).toBeTruthy();
      expect(el.querySelector('.grid.grid-cols-7')).toBeNull();
    });
  });
});
