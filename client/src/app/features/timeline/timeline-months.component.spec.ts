import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TimelineFiltersService } from './timeline-filters.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineMonthsComponent } from './timeline-months.component';

describe('TimelineMonthsComponent', () => {

  let component: any;
  let mockApi: { get: Mock };
  let mockStore: { viewFilterParams: ReturnType<typeof signal> };

  const monthsResponse = {
    months: [
      { month: '2024-06', count: 42, hero_photo_path: '/photos/june.jpg' },
      { month: '2024-05', count: 18, hero_photo_path: null },
    ],
  };

  const noneHidden = {
    hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
  };

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of(monthsResponse)) };
    mockStore = { viewFilterParams: signal({ ...noneHidden }) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        TimelineFiltersService,
        { provide: GalleryStore, useValue: mockStore },
      ],
    });

    TestBed.runInInjectionContext(() => {
      component = new TimelineMonthsComponent();
    });
  });

  describe('loading months for a year', () => {
    it('should call /timeline/months with the year input value', async () => {
      await (component as any).load('2024', '', '', { ...noneHidden });
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/months', { year: 2024, ...noneHidden });
    });

    it('should pass date_from and date_to when provided', async () => {
      await (component as any).load('2024', '2024-01-01', '2024-12-31', { ...noneHidden });
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/months', {
        year: 2024,
        ...noneHidden,
        date_from: '2024-01-01',
        date_to: '2024-12-31',
      });
    });

    it('should populate months signal', async () => {
      await (component as any).load('2024', '', '', { ...noneHidden });
      expect(component.months()).toHaveLength(2);
      expect(component.months()[0].month).toBe('2024-06');
    });

    it('should set loading false after success', async () => {
      await (component as any).load('2024', '', '', { ...noneHidden });
      expect(component.loading()).toBe(false);
    });

    it('should set loading false even on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      try { await (component as any).load('2024', '', '', { ...noneHidden }); } catch { /* expected */ }
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

  describe('reactive refetch on hide-toggle change', () => {
    it('re-fetches /timeline/months when GalleryStore.viewFilterParams changes', () => {
      // `year` is a required input; this component is constructed directly
      // (not via TestBed.createComponent), so there's no fixture to drive
      // componentRef.setInput() through — stand it up by hand instead.
      component.year = () => '2024';
      TestBed.flushEffects();
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/months', { year: 2024, ...noneHidden });
      mockApi.get.mockClear();

      mockStore.viewFilterParams.set({ ...noneHidden, hide_panoramas: '1' });
      TestBed.flushEffects();

      expect(mockApi.get).toHaveBeenCalledWith('/timeline/months', { year: 2024, ...noneHidden, hide_panoramas: '1' });
    });
  });
});
