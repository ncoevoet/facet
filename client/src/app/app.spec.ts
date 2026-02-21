import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { signal } from '@angular/core';
import { NEVER } from 'rxjs';
import { App } from './app';
import { GalleryStore, GalleryFilters } from './features/gallery/gallery.store';
import { AuthService } from './core/services/auth.service';
import { I18nService } from './core/services/i18n.service';
import { CompareFiltersService } from './features/comparison/compare-filters.service';
import { StatsFiltersService } from './features/stats/stats-filters.service';
import { MatDialog } from '@angular/material/dialog';

const DEFAULT_FILTERS: GalleryFilters = {
  page: 1, per_page: 64, sort: 'aggregate', sort_direction: 'DESC', type: '',
  camera: '', lens: '', tag: '', person_id: '', search: '', composition_pattern: '',
  min_score: '', max_score: '', min_aesthetic: '', max_aesthetic: '',
  min_face_quality: '', max_face_quality: '', min_composition: '', max_composition: '',
  min_sharpness: '', max_sharpness: '', min_exposure: '', max_exposure: '',
  min_color: '', max_color: '', min_contrast: '', max_contrast: '',
  min_noise: '', max_noise: '', min_dynamic_range: '', max_dynamic_range: '',
  min_face_count: '', max_face_count: '', min_eye_sharpness: '', max_eye_sharpness: '',
  min_face_sharpness: '', max_face_sharpness: '', min_face_ratio: '', max_face_ratio: '',
  min_face_confidence: '', max_face_confidence: '',
  min_quality_score: '', max_quality_score: '', min_topiq: '', max_topiq: '',
  min_power_point: '', max_power_point: '', min_leading_lines: '', max_leading_lines: '',
  min_isolation: '', max_isolation: '', min_saturation: '', max_saturation: '',
  min_luminance: '', max_luminance: '', min_histogram_spread: '', max_histogram_spread: '',
  min_star_rating: '', max_star_rating: '', min_iso: '', max_iso: '',
  min_aperture: '', max_aperture: '', min_focal_length: '', max_focal_length: '',
  date_from: '', date_to: '',
  hide_details: true, hide_blinks: true, hide_bursts: true, hide_duplicates: true,
  hide_rejected: true, favorites_only: false, is_monochrome: false,
};

function createApp(routerUrl = '/') {
  const filtersSignal = signal<GalleryFilters>({ ...DEFAULT_FILTERS });
  const personsSignal = signal<{ id: number; name: string | null }[]>([]);
  const compareCategorySig = signal('');
  const mockStore = {
    filters: filtersSignal,
    persons: personsSignal,
    updateFilter: jest.fn(),
    config: signal(null),
    types: signal<{ id: string; count: number }[]>([]),
    loadTypeCounts: jest.fn(() => Promise.resolve()),
  };

  TestBed.configureTestingModule({
    providers: [
      App,
      { provide: Router, useValue: { url: routerUrl, events: NEVER } },
      { provide: GalleryStore, useValue: mockStore },
      { provide: AuthService, useValue: { isAuthenticated: jest.fn(() => true), checkStatus: jest.fn(() => Promise.resolve()) } },
      { provide: I18nService, useValue: { load: jest.fn(() => Promise.resolve()), t: jest.fn((k: string) => k) } },
      { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      { provide: CompareFiltersService, useValue: { selectedCategory: compareCategorySig } },
      { provide: MatDialog, useValue: { open: jest.fn() } },
    ],
  });

  return { app: TestBed.inject(App), filtersSignal, personsSignal, mockStore, compareCategorySig };
}

describe('App', () => {
  describe('route detection', () => {
    it('isGalleryRoute returns true for /', () => {
      const { app } = createApp('/');
      expect(app.isGalleryRoute()).toBe(true);
    });

    it('isGalleryRoute returns false for /compare', () => {
      const { app } = createApp('/compare');
      expect(app.isGalleryRoute()).toBe(false);
    });

    it('isCompareRoute returns true for /compare', () => {
      const { app } = createApp('/compare');
      expect(app.isCompareRoute()).toBe(true);
    });

    it('isCompareRoute returns false for /', () => {
      const { app } = createApp('/');
      expect(app.isCompareRoute()).toBe(false);
    });

    it('isStatsRoute returns true for /stats', () => {
      const { app } = createApp('/stats');
      expect(app.isStatsRoute()).toBe(true);
    });

    it('isGalleryRoute ignores query string', () => {
      const { app } = createApp('/?sort=aggregate&type=portrait');
      expect(app.isGalleryRoute()).toBe(true);
    });

    it('isCompareRoute ignores query string', () => {
      const { app } = createApp('/compare?category=portrait');
      expect(app.isCompareRoute()).toBe(true);
    });
  });

  describe('activeFilterChips', () => {
    it('returns empty array when not on gallery route', () => {
      const { app, filtersSignal } = createApp('/compare');
      filtersSignal.set({ ...DEFAULT_FILTERS, tag: 'nature' });
      expect(app.activeFilterChips()).toEqual([]);
    });

    it('returns empty array when no active filters', () => {
      const { app } = createApp('/');
      expect(app.activeFilterChips()).toEqual([]);
    });

    it('produces chip for active tag filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, tag: 'nature' });
      const chip = app.activeFilterChips().find(c => c.id === 'tag');
      expect(chip).toBeDefined();
      expect(chip?.value).toBe('nature');
    });

    it('produces chip for active search filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, search: 'paris' });
      const chip = app.activeFilterChips().find(c => c.id === 'search');
      expect(chip?.value).toBe('paris');
    });

    it('produces chip for active camera filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, camera: 'Canon R5' });
      expect(app.activeFilterChips().some(c => c.id === 'camera' && c.value === 'Canon R5')).toBe(true);
    });

    it('produces one chip per person in comma-separated person_id', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1,2,3' });
      const personChips = app.activeFilterChips().filter(c => c.id.startsWith('person_'));
      expect(personChips).toHaveLength(3);
      expect(personChips.map(c => c.id)).toEqual(['person_1', 'person_2', 'person_3']);
    });

    it('uses person name when available', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([{ id: 1, name: 'Alice' }]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1' });
      const chip = app.activeFilterChips().find(c => c.id === 'person_1');
      expect(chip?.value).toBe('Alice');
    });

    it('falls back to #pid when person name is null', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([{ id: 2, name: null }]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '2' });
      const chip = app.activeFilterChips().find(c => c.id === 'person_2');
      expect(chip?.value).toBe('#2');
    });

    it('falls back to #pid when person is not in persons list', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '99' });
      const chip = app.activeFilterChips().find(c => c.id === 'person_99');
      expect(chip?.value).toBe('#99');
    });

    it('shows min–max format when both range bounds are set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '6', max_score: '9' });
      const chip = app.activeFilterChips().find(c => c.id === 'min_score');
      expect(chip?.value).toBe('6–9');
    });

    it('shows ≥min format when only min bound is set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '7', max_score: '' });
      const chip = app.activeFilterChips().find(c => c.id === 'min_score');
      expect(chip?.value).toBe('≥7');
    });

    it('shows ≤max format when only max bound is set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '', max_score: '8' });
      const chip = app.activeFilterChips().find(c => c.id === 'min_score');
      expect(chip?.value).toBe('≤8');
    });

    it('range chip clearKeys includes both min and max keys', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '5', max_score: '9' });
      const chip = app.activeFilterChips().find(c => c.id === 'min_score');
      expect(chip?.clearKeys).toEqual(['min_score', 'max_score']);
    });

    it('produces chip for favorites_only = true', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, favorites_only: true });
      expect(app.activeFilterChips().some(c => c.id === 'favorites_only')).toBe(true);
    });

    it('does not produce chip for favorites_only = false', () => {
      const { app } = createApp('/');
      expect(app.activeFilterChips().some(c => c.id === 'favorites_only')).toBe(false);
    });

    it('produces chip for is_monochrome = true', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, is_monochrome: true });
      expect(app.activeFilterChips().some(c => c.id === 'is_monochrome')).toBe(true);
    });

    it('topiq chip uses gallery.topiq_range (not aesthetic_range)', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_topiq: '5', max_topiq: '' });
      const topiqChip = app.activeFilterChips().find(c => c.id === 'min_topiq');
      expect(topiqChip?.labelKey).toBe('gallery.topiq_range');
    });

    it('aesthetic chip uses gallery.aesthetic_range', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_aesthetic: '5', max_aesthetic: '' });
      const aestheticChip = app.activeFilterChips().find(c => c.id === 'min_aesthetic');
      expect(aestheticChip?.labelKey).toBe('gallery.aesthetic_range');
    });

    it('topiq and aesthetic chips have distinct label keys', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_topiq: '5', min_aesthetic: '5', max_topiq: '', max_aesthetic: '' });
      const chips = app.activeFilterChips();
      const topiq = chips.find(c => c.id === 'min_topiq');
      const aesthetic = chips.find(c => c.id === 'min_aesthetic');
      expect(topiq?.labelKey).not.toBe(aesthetic?.labelKey);
    });
  });

  describe('clearFilterChip', () => {
    it('removes one person without affecting other person ids', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1,2,3' });
      app.clearFilterChip({ id: 'person_2', clearKeys: ['person_2'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('person_id', '1,3');
    });

    it('sets person_id to empty string when last person is removed', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '5' });
      app.clearFilterChip({ id: 'person_5', clearKeys: ['person_5'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('person_id', '');
    });

    it('calls updateFilter with false for favorites_only', () => {
      const { app, mockStore } = createApp('/');
      app.clearFilterChip({ id: 'favorites_only', clearKeys: ['favorites_only'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('favorites_only', false);
    });

    it('calls updateFilter with false for is_monochrome', () => {
      const { app, mockStore } = createApp('/');
      app.clearFilterChip({ id: 'is_monochrome', clearKeys: ['is_monochrome'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('is_monochrome', false);
    });

    it('calls updateFilter with empty string for string filters', () => {
      const { app, mockStore } = createApp('/');
      app.clearFilterChip({ id: 'tag', clearKeys: ['tag'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('tag', '');
    });

    it('calls updateFilter for both min and max keys of a range chip', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '5', max_score: '9' });
      const chip = app.activeFilterChips().find(c => c.id === 'min_score')!;
      app.clearFilterChip(chip);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('min_score', '');
      expect(mockStore.updateFilter).toHaveBeenCalledWith('max_score', '');
    });
  });

  describe('onCompareCategoryChange', () => {
    it('sets selectedCategory on compareFilters service', () => {
      const { app, compareCategorySig } = createApp('/');
      app.onCompareCategoryChange('portrait');
      expect(compareCategorySig()).toBe('portrait');
    });
  });
});
