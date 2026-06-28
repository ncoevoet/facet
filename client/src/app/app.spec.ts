import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { signal } from '@angular/core';
import { NEVER } from 'rxjs';
import { App } from './app';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS } from './features/gallery/gallery.store';
import { AuthService } from './core/services/auth.service';
import { ApiService } from './core/services/api.service';
import { I18nService } from './core/services/i18n.service';
import { ThemeService } from './core/services/theme.service';
import { CompareFiltersService } from './features/comparison/compare-filters.service';
import { StatsFiltersService } from './features/stats/stats-filters.service';
import { MatDialog } from '@angular/material/dialog';

function createApp(routerUrl = '/') {
  const filtersSignal = signal<GalleryFilters>({ ...DEFAULT_FILTERS });
  const personsSignal = signal<{ id: number; name: string | null }[]>([]);
  const compareCategorySig = signal('');
  const mockStore = {
    filters: filtersSignal,
    persons: personsSignal,
    updateFilter: vi.fn(),
    resetFilters: vi.fn(() => Promise.resolve()),
    config: signal(null),
    types: signal<{ id: string; count: number }[]>([]),
    loadTypeCounts: vi.fn(() => Promise.resolve()),
  };

  const mockRouter = { url: routerUrl, events: NEVER, navigate: vi.fn() };

  TestBed.configureTestingModule({
    providers: [
      App,
      { provide: Router, useValue: mockRouter },
      { provide: GalleryStore, useValue: mockStore },
      { provide: AuthService, useValue: { isAuthenticated: vi.fn(() => true), checkStatus: vi.fn(() => Promise.resolve()) } },
      { provide: I18nService, useValue: { load: vi.fn(() => Promise.resolve()), loadLanguages: vi.fn(() => Promise.resolve()), languages: signal([]), t: vi.fn((k: string) => k), translations: signal({}) } },
      { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      { provide: CompareFiltersService, useValue: { selectedCategory: compareCategorySig } },
      { provide: MatDialog, useValue: { open: vi.fn() } },
      { provide: ApiService, useValue: { get: vi.fn(() => NEVER), post: vi.fn(() => NEVER) } },
      { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], setTheme: vi.fn(), toggleDarkMode: vi.fn(), accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
    ],
  });

  return { app: TestBed.inject(App), filtersSignal, personsSignal, mockStore, mockRouter, compareCategorySig };
}

describe('App', () => {
  describe('route detection', () => {
    it('isGalleryRoute returns true for /', () => {
      const { app } = createApp('/');
      expect((app as any).isGalleryRoute()).toBe(true);
    });

    it('isGalleryRoute returns false for /compare', () => {
      const { app } = createApp('/compare');
      expect((app as any).isGalleryRoute()).toBe(false);
    });

    it('isCompareRoute returns true for /compare', () => {
      const { app } = createApp('/compare');
      expect((app as any).isCompareRoute()).toBe(true);
    });

    it('isCompareRoute returns false for /', () => {
      const { app } = createApp('/');
      expect((app as any).isCompareRoute()).toBe(false);
    });

    it('isStatsRoute returns true for /stats', () => {
      const { app } = createApp('/stats');
      expect((app as any).isStatsRoute()).toBe(true);
    });

    it('isGalleryRoute ignores query string', () => {
      const { app } = createApp('/?sort=aggregate&type=portrait');
      expect((app as any).isGalleryRoute()).toBe(true);
    });

    it('isCompareRoute ignores query string', () => {
      const { app } = createApp('/compare?category=portrait');
      expect((app as any).isCompareRoute()).toBe(true);
    });
  });

  describe('activeFilterChips', () => {
    it('returns empty array when not on gallery route', () => {
      const { app, filtersSignal } = createApp('/compare');
      filtersSignal.set({ ...DEFAULT_FILTERS, tag: 'nature' });
      expect((app as any).activeFilterChips()).toEqual([]);
    });

    it('returns empty array when no active filters', () => {
      const { app } = createApp('/');
      expect((app as any).activeFilterChips()).toEqual([]);
    });

    it('produces chip for active tag filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, tag: 'nature' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'tag');
      expect(chip).toBeDefined();
      expect(chip?.value).toBe('nature');
    });

    it('produces chip for active search filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, search: 'paris' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'search');
      expect(chip?.value).toBe('paris');
    });

    it('produces chip for active camera filter', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, camera: 'Canon R5' });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'camera' && c.value === 'Canon R5')).toBe(true);
    });

    it('produces one chip per person in comma-separated person_id', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1,2,3' });
      const personChips = (app as any).activeFilterChips().filter((c: any) => c.id.startsWith('person_'));
      expect(personChips).toHaveLength(3);
      expect(personChips.map((c: any) => c.id)).toEqual(['person_1', 'person_2', 'person_3']);
    });

    it('uses person name when available', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([{ id: 1, name: 'Alice' }]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_1');
      expect(chip?.value).toBe('Alice');
    });

    it('falls back to #pid when person name is null', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([{ id: 2, name: null }]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '2' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_2');
      expect(chip?.value).toBe('#2');
    });

    it('falls back to #pid when person is not in persons list', () => {
      const { app, filtersSignal, personsSignal } = createApp('/');
      personsSignal.set([]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '99' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_99');
      expect(chip?.value).toBe('#99');
    });

    it('shows min–max format when both range bounds are set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '6', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('6–9');
    });

    it('shows ≥min format when only min bound is set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '7', max_score: '' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('≥7');
    });

    it('shows ≤max format when only max bound is set', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '', max_score: '8' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('≤8');
    });

    it('range chip clearKeys includes both min and max keys', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '5', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.clearKeys).toEqual(['min_score', 'max_score']);
    });

    it('produces chip for favorites_only = true', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, favorites_only: true });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'favorites_only')).toBe(true);
    });

    it('does not produce chip for favorites_only = false', () => {
      const { app } = createApp('/');
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'favorites_only')).toBe(false);
    });

    it('produces chip for is_monochrome = true', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, is_monochrome: true });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'is_monochrome')).toBe(true);
    });

    it('topiq chip uses gallery.topiq_range (not aesthetic_range)', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_topiq: '5', max_topiq: '' });
      const topiqChip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_topiq');
      expect(topiqChip?.labelKey).toBe('gallery.topiq_range');
    });

    it('aesthetic chip uses gallery.aesthetic_range', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_aesthetic: '5', max_aesthetic: '' });
      const aestheticChip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_aesthetic');
      expect(aestheticChip?.labelKey).toBe('gallery.aesthetic_range');
    });

    it('topiq and aesthetic chips have distinct label keys', () => {
      const { app, filtersSignal } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_topiq: '5', min_aesthetic: '5', max_topiq: '', max_aesthetic: '' });
      const chips = (app as any).activeFilterChips();
      const topiq = chips.find((c: any) => c.id === 'min_topiq');
      const aesthetic = chips.find((c: any) => c.id === 'min_aesthetic');
      expect(topiq?.labelKey).not.toBe(aesthetic?.labelKey);
    });
  });

  describe('clearFilterChip', () => {
    it('removes one person without affecting other person ids', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1,2,3' });
      (app as any).clearFilterChip({ id: 'person_2', clearKeys: ['person_2'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('person_id', '1,3');
    });

    it('sets person_id to empty string when last person is removed', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '5' });
      (app as any).clearFilterChip({ id: 'person_5', clearKeys: ['person_5'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('person_id', '');
    });

    it('calls updateFilter with false for favorites_only', () => {
      const { app, mockStore } = createApp('/');
      (app as any).clearFilterChip({ id: 'favorites_only', clearKeys: ['favorites_only'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('favorites_only', false);
    });

    it('calls updateFilter with false for is_monochrome', () => {
      const { app, mockStore } = createApp('/');
      (app as any).clearFilterChip({ id: 'is_monochrome', clearKeys: ['is_monochrome'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('is_monochrome', false);
    });

    it('calls updateFilter with empty string for string filters', () => {
      const { app, mockStore } = createApp('/');
      (app as any).clearFilterChip({ id: 'tag', clearKeys: ['tag'] });
      expect(mockStore.updateFilter).toHaveBeenCalledWith('tag', '');
    });

    it('calls updateFilter for both min and max keys of a range chip', () => {
      const { app, filtersSignal, mockStore } = createApp('/');
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '5', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score')!;
      (app as any).clearFilterChip(chip);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('min_score', '');
      expect(mockStore.updateFilter).toHaveBeenCalledWith('max_score', '');
    });
  });

  describe('onCompareCategoryChange', () => {
    it('sets selectedCategory on compareFilters service', () => {
      const { app, compareCategorySig } = createApp('/');
      (app as any).onCompareCategoryChange('portrait');
      expect(compareCategorySig()).toBe('portrait');
    });
  });

  describe('resetAllFilters', () => {
    it('navigates to / and calls store.resetFilters', () => {
      const { app, mockStore, mockRouter } = createApp('/');
      (app as any).resetAllFilters();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/']);
      expect(mockStore.resetFilters).toHaveBeenCalled();
    });

    it('navigates to / even when on a different route', () => {
      const { app, mockStore, mockRouter } = createApp('/stats');
      (app as any).resetAllFilters();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/']);
      expect(mockStore.resetFilters).toHaveBeenCalled();
    });
  });
});
