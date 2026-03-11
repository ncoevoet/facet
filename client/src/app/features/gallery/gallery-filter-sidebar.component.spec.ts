import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { GalleryStore } from './gallery.store';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService } from '../../core/services/album.service';

describe('GalleryFilterSidebarComponent', () => {
  let component: GalleryFilterSidebarComponent;

  beforeEach(() => {
    const mockStore = {
      filters: signal({
        hide_details: true, hide_blinks: true, hide_bursts: true, hide_duplicates: true,
        hide_rejected: true, favorites_only: false, is_monochrome: false,
        camera: '', lens: '', tag: '', composition_pattern: '', person_id: '',
        min_score: '', max_score: '', min_aesthetic: '', max_aesthetic: '',
        min_face_quality: '', max_face_quality: '', min_composition: '', max_composition: '',
        min_sharpness: '', max_sharpness: '', min_exposure: '', max_exposure: '',
        min_color: '', max_color: '', min_contrast: '', max_contrast: '',
        min_noise: '', max_noise: '', min_dynamic_range: '', max_dynamic_range: '',
        min_face_count: '', max_face_count: '', min_eye_sharpness: '', max_eye_sharpness: '',
        min_face_sharpness: '', max_face_sharpness: '', min_face_ratio: '', max_face_ratio: '',
        min_face_confidence: '', max_face_confidence: '', min_quality_score: '', max_quality_score: '',
        min_topiq: '', max_topiq: '', min_power_point: '', max_power_point: '',
        min_leading_lines: '', max_leading_lines: '', min_isolation: '', max_isolation: '',
        min_saturation: '', max_saturation: '', min_luminance: '', max_luminance: '',
        min_histogram_spread: '', max_histogram_spread: '', min_star_rating: '', max_star_rating: '',
        min_iso: '', max_iso: '', min_aperture: '', max_aperture: '',
        min_focal_length: '', max_focal_length: '', date_from: '', date_to: '',
        search: '', type: '', sort: 'aggregate', sort_direction: 'DESC', page: 1, per_page: 64,
        similar_to: '', similarity_mode: 'visual', min_similarity: '70',
        semanticQuery: '', album_id: '',
        min_aesthetic_iaa: '', max_aesthetic_iaa: '',
        min_face_quality_iqa: '', max_face_quality_iqa: '',
        min_liqe: '', max_liqe: '',
        min_subject_sharpness: '', max_subject_sharpness: '',
        min_subject_prominence: '', max_subject_prominence: '',
        min_subject_placement: '', max_subject_placement: '',
        min_bg_separation: '', max_bg_separation: '',
      }),
      filterDrawerOpen: signal(true),
      cameras: signal([]),
      lenses: signal([]),
      tags: signal([]),
      persons: signal([]),
      compositionPatterns: signal([]),
      config: signal(null),
      activeFilterCount: signal(0),
      updateFilter: jest.fn(),
      updateFilters: jest.fn(),
      resetFilters: jest.fn(),
      setFilterDrawerOpen: jest.fn(),
    };

    TestBed.configureTestingModule({
      providers: [
        GalleryFilterSidebarComponent,
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: { t: jest.fn((k: string) => k), currentLang: jest.fn(() => 'en') } },
        { provide: AuthService, useValue: { isEdition: jest.fn(() => false) } },
        { provide: AlbumService, useValue: { list: jest.fn(() => of({ albums: [] })) } },
        { provide: MatDialog, useValue: { open: jest.fn() } },
      ],
    });
    component = TestBed.inject(GalleryFilterSidebarComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('sectionActiveCounts', () => {
    it('returns 0 for all sections when no filters are active', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), hide_rejected: false });
      const counts = component.sectionActiveCounts();
      expect(counts['date']).toBe(0);
      expect(counts['content']).toBe(0);
      expect(counts['equipment']).toBe(0);
      expect(counts['display']).toBe(0);
      expect(counts['gallery.sidebar.quality']).toBe(0);
      expect(counts['gallery.sidebar.face']).toBe(0);
    });

    it('counts date_from and date_to independently', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), date_from: '2024-01-01' });
      expect(component.sectionActiveCounts()['date']).toBe(1);
      mockStore.filters.set({ ...mockStore.filters(), date_to: '2024-12-31' });
      expect(component.sectionActiveCounts()['date']).toBe(2);
    });

    it('counts tag and composition_pattern for content section', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), tag: 'landscape' });
      expect(component.sectionActiveCounts()['content']).toBe(1);
      mockStore.filters.set({ ...mockStore.filters(), composition_pattern: 'rule_of_thirds' });
      expect(component.sectionActiveCounts()['content']).toBe(2);
    });

    it('counts camera and lens for equipment section', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), camera: 'Sony A7', lens: 'FE 85mm' });
      expect(component.sectionActiveCounts()['equipment']).toBe(2);
    });

    it('counts favorites_only, is_monochrome, hide_rejected for display section', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), favorites_only: true, is_monochrome: true, hide_rejected: true });
      expect(component.sectionActiveCounts()['display']).toBe(3);
    });

    it('counts active metric filters by min/max key', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_score: '7', min_aesthetic: '6' });
      expect(component.sectionActiveCounts()['gallery.sidebar.quality']).toBe(2);
    });

    it('counts a metric filter once even when both min and max are set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_score: '5', max_score: '9' });
      expect(component.sectionActiveCounts()['gallery.sidebar.quality']).toBe(1);
    });
  });

  describe('onDynamicRangeChange', () => {
    const iaaFilter = {
      id: 'aesthetic_iaa_range', labelKey: 'gallery.aesthetic_iaa_range',
      sectionKey: 'gallery.sidebar.extended_quality',
      minKey: 'min_aesthetic_iaa' as const, maxKey: 'max_aesthetic_iaa' as const,
      sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16',
    };

    const isoFilter = {
      id: 'iso_range', labelKey: 'gallery.iso_range',
      sectionKey: 'gallery.sidebar.exposure_range',
      minKey: 'min_iso' as const, maxKey: 'max_iso' as const,
      sliderMin: 50, sliderMax: 25600, step: 50, spanWidth: 'w-20',
    };

    it('clears min filter at slider minimum', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'min', 0);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('min_aesthetic_iaa', '');
    });

    it('redirects max to min when min is at default', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'max', 7.5);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('min_aesthetic_iaa', '7.5');
    });

    it('clears max filter at slider maximum when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_aesthetic_iaa: '5' });
      component.onDynamicRangeChange(iaaFilter, 'max', 10);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('max_aesthetic_iaa', '');
    });

    it('stores string value for non-boundary min', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'min', 6.5);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('min_aesthetic_iaa', '6.5');
    });

    it('stores string value for non-boundary max when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_aesthetic_iaa: '3' });
      component.onDynamicRangeChange(iaaFilter, 'max', 7.5);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('max_aesthetic_iaa', '7.5');
    });

    it('clears min at non-zero boundary (ISO 50)', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(isoFilter, 'min', 50);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('min_iso', '');
    });

    it('clears max at non-standard boundary (ISO 25600) when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_iso: '100' });
      component.onDynamicRangeChange(isoFilter, 'max', 25600);
      expect(mockStore.updateFilter).toHaveBeenCalledWith('max_iso', '');
    });
  });
});
