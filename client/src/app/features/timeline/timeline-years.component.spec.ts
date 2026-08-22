import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TimelineFiltersService } from './timeline-filters.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineYearsComponent } from './timeline-years.component';

describe('TimelineYearsComponent', () => {

  let component: any;
  let mockApi: { get: Mock };
  let mockStore: { viewFilterParams: ReturnType<typeof signal> };

  const yearsResponse = {
    years: [
      { year: '2024', count: 120, hero_photo_path: '/photos/a.jpg' },
      { year: '2023', count: 85, hero_photo_path: null },
    ],
  };

  const noneHidden = {
    hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
  };

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of(yearsResponse)) };
    mockStore = { viewFilterParams: signal({ ...noneHidden }) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        TimelineFiltersService,
        { provide: GalleryStore, useValue: mockStore },
      ],
    });
    component = TestBed.runInInjectionContext(() => new TimelineYearsComponent());
  });

  describe('load', () => {
    it('should call /timeline/years with just the view filter params when dates are empty', async () => {
      await component.load('', '', { ...noneHidden });
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/years', { ...noneHidden });
    });

    it('should pass date_from and date_to when provided', async () => {
      await component.load('2024-01-01', '2024-12-31', { ...noneHidden });
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/years', {
        ...noneHidden,
        date_from: '2024-01-01',
        date_to: '2024-12-31',
      });
    });

    it('should populate years signal', async () => {
      await component.load('', '', { ...noneHidden });
      expect(component.years()).toHaveLength(2);
      expect(component.years()[0].year).toBe('2024');
      expect(component.years()[0].count).toBe(120);
      expect(component.years()[0].hero_photo_path).toBe('/photos/a.jpg');
    });

    it('should set loading false after success', async () => {
      await component.load('', '', { ...noneHidden });
      expect(component.loading()).toBe(false);
    });

    it('should set loading false even on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      try { await component.load('', '', { ...noneHidden }); } catch { /* expected */ }
      expect(component.loading()).toBe(false);
    });

    it('should accept entries with null hero_photo_path', async () => {
      await component.load('', '', { ...noneHidden });
      expect(component.years()[1].hero_photo_path).toBeNull();
    });
  });

  describe('reactive refetch on hide-toggle change', () => {
    it('re-fetches /timeline/years when GalleryStore.viewFilterParams changes', () => {
      TestBed.flushEffects();
      expect(mockApi.get).toHaveBeenCalledWith('/timeline/years', { ...noneHidden });
      mockApi.get.mockClear();

      mockStore.viewFilterParams.set({ ...noneHidden, hide_bursts: '1' });
      TestBed.flushEffects();

      expect(mockApi.get).toHaveBeenCalledWith('/timeline/years', { ...noneHidden, hide_bursts: '1' });
    });
  });
});
