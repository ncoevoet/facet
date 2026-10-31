import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { MatSelect } from '@angular/material/select';
import { MatDialog } from '@angular/material/dialog';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { OverlayContainer } from '@angular/cdk/overlay';
import { GalleryStore } from './gallery.store';
import {
  ADDITIONAL_FILTERS, ADVANCED_SECTION_ORDER, BROWSE_PANELS, GalleryFilterSidebarComponent, SECTION_ORDER, SidebarTabId, TAB_ICONS, TAB_IDS,
  SEGMENT_PATCHES, TAB_SECTIONS, UNIT_PANEL, loadActiveTab,
} from './gallery-filter-sidebar.component';
import { DEFAULT_FILTERS, GalleryFilters, activeFilterUnits, countActiveFilters } from './gallery-filters.util';
import { I18N } from '../../core/i18n/keys';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService } from '../../core/services/album.service';

describe('GalleryFilterSidebarComponent', () => {
  let component: GalleryFilterSidebarComponent;
  let mockStore: Record<string, unknown>;

  beforeEach(() => {
    localStorage.removeItem('facet_sidebar_tab');
    mockStore = {
      filters: signal({
        hide_details: true, hide_blinks: true, hide_bursts: true, hide_duplicates: true,
        hide_rejected: true, favorites_only: false, is_monochrome: false,
        hide_brackets: true, hide_panoramas: true, blinks_only: false, duplicates_only: false,
        show_rejected: false, review_status: '', manual_faces_need_review: false,
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
        semanticQuery: '', search_threshold: '', album_id: '',
        min_aesthetic_iaa: '', max_aesthetic_iaa: '',
        min_face_quality_iqa: '', max_face_quality_iqa: '',
        min_liqe: '', max_liqe: '',
        min_qrealign: '', max_qrealign: '',
        min_aesthetic_v25: '', max_aesthetic_v25: '',
        min_deqa: '', max_deqa: '',
        min_subject_sharpness: '', max_subject_sharpness: '',
        min_subject_prominence: '', max_subject_prominence: '',
        min_subject_placement: '', max_subject_placement: '',
        min_bg_separation: '', max_bg_separation: '',
        path_prefix: '',
      }),
      filterDrawerOpen: signal(true),
      reviewProgressVisible: signal(true), setReviewProgressVisible: vi.fn(),
      cameras: signal([]),
      lenses: signal([]),
      tags: signal([]),
      persons: signal([]),
      compositionPatterns: signal([]),
      metricRanges: signal({}),
      config: signal(null),
      activeFilterCount: signal(0),
      updateFilter: vi.fn(),
      updateFilterDebounced: vi.fn(),
      updateFilters: vi.fn(),
      resetFilters: vi.fn(),
      setFilterDrawerOpen: vi.fn(),
    };

    TestBed.configureTestingModule({
      providers: [
        GalleryFilterSidebarComponent,
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: { t: vi.fn((k: string) => k), currentLang: vi.fn(() => 'en'), translations: vi.fn(() => ({})) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })) } },
        { provide: MatDialog, useValue: { open: vi.fn() } },
      ],
    });
    component = TestBed.inject(GalleryFilterSidebarComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('unavailable metrics (commercial mode)', () => {
    const ids = () => component.advancedFilterGroups().flatMap(g => g.filters.map(f => f.id));

    it('lists the extended-quality filters in default mode', () => {
      expect(ids()).toEqual(expect.arrayContaining(['liqe_range', 'aesthetic_iaa_range', 'face_quality_iqa_range']));
    });

    it('drops filters for hidden metrics but keeps the rest', () => {
      (mockStore['config'] as ReturnType<typeof signal<unknown>>).set({
        unavailable_metrics: ['liqe_score', 'aesthetic_iaa', 'face_quality_iqa'],
      });
      const shown = ids();
      expect(shown).not.toContain('liqe_range');
      expect(shown).not.toContain('aesthetic_iaa_range');
      expect(shown).not.toContain('face_quality_iqa_range');
      expect(shown).toContain('qrealign_range');
      expect(shown).toContain('face_quality_range');
    });

    it('does not count an active hidden filter in the section badge', () => {
      (mockStore['config'] as ReturnType<typeof signal<unknown>>).set({ unavailable_metrics: ['liqe_score'] });
      const filters = mockStore['filters'] as ReturnType<typeof signal<Record<string, unknown>>>;
      filters.update(f => ({ ...f, min_liqe: '4' }));
      expect(component.sectionActiveCounts()['gallery.sidebar.extended_quality']).toBe(0);
    });
  });

  describe('clampDef', () => {
    const scoreDef = {
      id: 'score_range', minKey: 'min_score', maxKey: 'max_score',
      sliderMin: 0, sliderMax: 10, step: 0.5,
    };

    it('clamps slider bounds to the data-driven range when no value is out of range', () => {
      const store = (component as any).store;
      store.metricRanges.set({ min_score: { min: 5, max: 9, buckets: [] } });
      store.filters.set({ ...store.filters(), min_score: '', max_score: '' });
      const clamped = (component as any).clampDef(scoreDef);
      expect(clamped.sliderMin).toBe(5);
      expect(clamped.sliderMax).toBe(9);
    });

    it('widens bounds so an active value below the data min stays reachable', () => {
      const store = (component as any).store;
      store.metricRanges.set({ min_score: { min: 5, max: 9, buckets: [] } });
      // A persisted/URL min of 2 sits below the data minimum of 5.
      store.filters.set({ ...store.filters(), min_score: '2', max_score: '' });
      const clamped = (component as any).clampDef(scoreDef);
      expect(clamped.sliderMin).toBeLessThanOrEqual(2); // not pinned to 5 — reachable
      expect(clamped.sliderMax).toBe(9);                // data max unchanged
    });
  });

  describe('filename search', () => {
    const input = (value: string) => ({ target: { value } }) as unknown as Event;

    afterEach(() => vi.useRealTimers());

    it('filters 400 ms after the last keystroke, once', () => {
      vi.useFakeTimers();
      const store = (component as any).store;
      component.onSidebarSearchChange(input('IMG'));
      component.onSidebarSearchChange(input('IMG_1'));
      vi.advanceTimersByTime(399);
      expect(store.updateFilter).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(store.updateFilter).toHaveBeenCalledTimes(1);
      expect(store.updateFilter).toHaveBeenCalledWith('search', 'IMG_1');
    });

    it('Enter commits at once and drops the pending debounce', () => {
      vi.useFakeTimers();
      const store = (component as any).store;
      component.onSidebarSearchChange(input('IMG'));
      component.onSidebarSearchCommit(input('IMG_2'));
      vi.advanceTimersByTime(1000);
      expect(store.updateFilter.mock.calls).toEqual([['search', 'IMG_2']]);
    });

    it('a semantic keystroke does not cancel a pending filename update', () => {
      vi.useFakeTimers();
      const store = (component as any).store;
      component.onSidebarSearchChange(input('IMG'));
      component.onSemanticSearch(input('sunset'));
      vi.advanceTimersByTime(1000);
      expect(store.updateFilter).toHaveBeenCalledWith('search', 'IMG');
    });
  });

  describe('sectionActiveCounts', () => {
    it('returns 0 for all sections when no filters are active', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), hide_rejected: false });
      const counts = component.sectionActiveCounts();
      expect(counts['date']).toBe(0);
      expect(counts['content']).toBe(0);
      expect(counts['equipment']).toBe(0);
      expect(counts['refine']).toBe(0);
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

    it('counts an active path_prefix for the folder section', () => {
      const mockStore = (component as any).store;
      expect(component.sectionActiveCounts()['folder']).toBe(0);
      mockStore.filters.set({ ...mockStore.filters(), path_prefix: '/photos/Family/' });
      expect(component.sectionActiveCounts()['folder']).toBe(1);
    });

    it('counts favorites_only and is_monochrome for refine, but not the default-on hide_rejected', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), favorites_only: true, is_monochrome: true, hide_rejected: true });
      expect(component.sectionActiveCounts()['refine']).toBe(2);
    });

    it('counts manual_faces_need_review once in the refine section', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), hide_rejected: false });
      const before = component.sectionActiveCounts()['refine'];
      mockStore.filters.set({ ...mockStore.filters(), manual_faces_need_review: true });
      expect(component.sectionActiveCounts()['refine']).toBe(before + 1);
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
      helpKey: 'gallery.sidebar.metric_help.aesthetic_iaa_range',
      sectionKey: 'gallery.sidebar.extended_quality',
      minKey: 'min_aesthetic_iaa' as const, maxKey: 'max_aesthetic_iaa' as const,
      sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16',
    };

    const isoFilter = {
      id: 'iso_range', labelKey: 'gallery.iso_range',
      helpKey: 'gallery.sidebar.metric_help.iso_range',
      sectionKey: 'gallery.sidebar.exposure_range',
      minKey: 'min_iso' as const, maxKey: 'max_iso' as const,
      sliderMin: 50, sliderMax: 25600, step: 50, spanWidth: 'w-20',
    };

    it('clears min filter at slider minimum', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'min', 0);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('min_aesthetic_iaa', '');
    });

    it('redirects max to min when min is at default', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'max', 7.5);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('min_aesthetic_iaa', '7.5');
    });

    it('clears max filter at slider maximum when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_aesthetic_iaa: '5' });
      component.onDynamicRangeChange(iaaFilter, 'max', 10);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('max_aesthetic_iaa', '');
    });

    it('stores string value for non-boundary min', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'min', 6.5);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('min_aesthetic_iaa', '6.5');
    });

    it('stores string value for non-boundary max when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_aesthetic_iaa: '3' });
      component.onDynamicRangeChange(iaaFilter, 'max', 7.5);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('max_aesthetic_iaa', '7.5');
    });

    it('clears min at non-zero boundary (ISO 50)', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(isoFilter, 'min', 50);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('min_iso', '');
    });

    it('clears max at non-standard boundary (ISO 25600) when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_iso: '100' });
      component.onDynamicRangeChange(isoFilter, 'max', 25600);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('max_iso', '');
    });
  });

  describe('folder filter', () => {
    it('clearFolderFilter empties path_prefix', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), path_prefix: '/photos/Family/' });
      component.clearFolderFilter();
      expect(mockStore.updateFilter).toHaveBeenCalledWith('path_prefix', '');
    });

    it('currentFolderName shows the last segment of the active prefix', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), path_prefix: '/photos/Family/2026/' });
      expect(component.currentFolderName()).toBe('2026');
    });
  });

  describe('semantic search threshold slider', () => {
    // Note: this suite tests the component's methods/computeds directly, the
    // same style every other describe block in this file uses -- the harness
    // never renders the template via fixture.createComponent/detectChanges,
    // so panel-visibility (@if show_semantic_search, pre-existing/unchanged)
    // is not exercised here either.
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('searchThresholdValue mirrors the string filter as a number for the slider [value] binding', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '12' });
      expect((component as any).searchThresholdValue()).toBe(12);
    });

    it('searchThresholdValue falls back to 0 when unseeded and config has not loaded', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '' });
      mockStore.config.set(null);
      expect((component as any).searchThresholdValue()).toBe(0);
    });

    it('searchThresholdValue falls back to the config default (as a percent) when unseeded -- never a bare 0/blank readout while the server actually gates at its own default', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '' });
      mockStore.config.set({ search_threshold_default: 0.05 });
      expect((component as any).searchThresholdValue()).toBe(5);
    });

    it('onSearchThresholdChange debounces the filter update by 400ms', () => {
      const mockStore = (component as any).store;
      component.onSearchThresholdChange(20);
      expect(mockStore.updateFilter).not.toHaveBeenCalled();

      vi.advanceTimersByTime(400);

      expect(mockStore.updateFilter).toHaveBeenCalledWith('search_threshold', '20');
    });

    it('the readout follows the drag immediately, rather than freezing for the debounce', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '12' });

      component.onSearchThresholdChange(31);

      expect((component as any).searchThresholdValue()).toBe(31);
      expect(mockStore.updateFilter).not.toHaveBeenCalled();
    });

    it('drops the draft once the debounce fires, so the filter is the single source again', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '12' });
      component.onSearchThresholdChange(31);

      vi.advanceTimersByTime(400);
      // The mock store never applies updateFilter, so the filter is still '12':
      // a draft that outlived the timeout would keep reading 31.
      expect((component as any).searchThresholdValue()).toBe(12);
    });

    it('a second drag replaces the draft rather than queueing a stale readout', () => {
      component.onSearchThresholdChange(31);
      vi.advanceTimersByTime(200);
      component.onSearchThresholdChange(44);

      expect((component as any).searchThresholdValue()).toBe(44);

      vi.advanceTimersByTime(400);

      expect((component as any).store.updateFilter).toHaveBeenCalledTimes(1);
      expect((component as any).store.updateFilter).toHaveBeenCalledWith('search_threshold', '44');
    });

    it('uses its own debounce timer, independent of the semantic-query search timer', () => {
      const mockStore = (component as any).store;
      const inputEvent = { target: { value: 'sunset' } } as unknown as Event;

      component.onSemanticSearch(inputEvent);
      component.onSearchThresholdChange(30);
      vi.advanceTimersByTime(400);

      expect(mockStore.updateFilter).toHaveBeenCalledWith('semanticQuery', 'sunset');
      expect(mockStore.updateFilter).toHaveBeenCalledWith('search_threshold', '30');
    });
  });

  describe('tabs: panel mapping', () => {
    const allPanels = () => TAB_IDS.flatMap(id => [...TAB_SECTIONS[id]]);

    it('lists every panel in exactly one tab', () => {
      const panels = allPanels();
      expect(new Set(panels).size).toBe(panels.length);
    });

    it('covers every metric section, every browse panel and every hand-written panel', () => {
      const panels = allPanels();
      for (const key of SECTION_ORDER) expect(panels, key).toContain(key);
      for (const key of BROWSE_PANELS) expect(TAB_SECTIONS.browse).toContain(key);
      expect(panels).toEqual(expect.arrayContaining(['refine', 'color_quality', 'view']));
      expect(panels).toHaveLength(SECTION_ORDER.length + BROWSE_PANELS.length + 3);
    });

    it('splits the metric sections between Quality (image quality) and Subject (what is in the frame)', () => {
      expect(TAB_SECTIONS.quality).toEqual([
        'gallery.sidebar.quality', 'color_quality', 'gallery.sidebar.extended_quality',
        'gallery.sidebar.technical', 'gallery.sidebar.exposure_range',
      ]);
      expect(TAB_SECTIONS.subject).toEqual([
        'gallery.sidebar.face', 'gallery.sidebar.composition', 'gallery.sidebar.saliency', 'gallery.sidebar.moments',
      ]);
      expect(TAB_IDS).toEqual(['browse', 'review', 'quality', 'subject', 'display']);
      for (const key of ADVANCED_SECTION_ORDER) {
        expect([...TAB_SECTIONS.quality, ...TAB_SECTIONS.subject]).toContain(key);
      }
      expect(TAB_SECTIONS.browse).toContain('equipment');
      expect(TAB_SECTIONS.review).toEqual(['refine', 'gallery.sidebar.ratings']);
    });

    it('counts every filter control under a panel that a tab holds', () => {
      const panels = new Set(allPanels());
      for (const [unit, panel] of Object.entries(UNIT_PANEL)) expect(panels.has(panel), unit).toBe(true);
    });

    it('gives each tab one of the four icons', () => {
      expect(TAB_IDS.map(id => TAB_ICONS[id])).toEqual(['travel_explore', 'rule', 'high_quality', 'center_focus_strong', 'display_settings']);
    });
  });

  describe('tabs: active tab persistence', () => {
    it('defaults to browse', () => {
      expect(component.activeTab()).toBe('browse');
      expect(loadActiveTab()).toBe('browse');
    });

    it('round-trips the selected tab through localStorage by id', () => {
      component.selectTab('subject');
      expect(localStorage.getItem('facet_sidebar_tab')).toBe('subject');
      expect(loadActiveTab()).toBe('subject');
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          GalleryFilterSidebarComponent,
          { provide: GalleryStore, useValue: mockStore },
          { provide: I18nService, useValue: { t: vi.fn((k: string) => k), currentLang: vi.fn(() => 'en'), translations: vi.fn(() => ({})) } },
          { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
          { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })) } },
          { provide: MatDialog, useValue: { open: vi.fn() } },
        ],
      });
      expect(TestBed.inject(GalleryFilterSidebarComponent).activeTab()).toBe('subject');
    });

    it('falls back to browse for an id no tab has, including the retired metrics tab', () => {
      localStorage.setItem('facet_sidebar_tab', 'gone');
      expect(loadActiveTab()).toBe('browse');
      localStorage.setItem('facet_sidebar_tab', 'metrics');
      expect(loadActiveTab()).toBe('browse');
    });

    it('forgets a half-typed person search when the tab changes', () => {
      component.sidebarPersonQuery.set('ali');
      component.selectTab('review');
      expect(component.sidebarPersonQuery()).toBe('');
    });
  });

  describe('tabs: unified active counts', () => {
    const setFilters = (patch: Record<string, unknown>) => {
      const filters = (component as any).store.filters;
      filters.set({ ...filters(), ...patch });
    };

    it('counts a min/max range once in its panel, its tab and the header', () => {
      setFilters({ min_score: '5', max_score: '9' });
      expect(component.sectionActiveCounts()['gallery.sidebar.quality']).toBe(1);
      expect(component.tabActiveCounts().quality).toBe(1);
      expect(component.tabActiveCounts().subject).toBe(0);
      expect(component.totalActiveCount()).toBe(1);
    });

    it('counts the location once however many of its keys are set', () => {
      setFilters({ gps_lat: '1', gps_lng: '2', gps_radius_km: '5' });
      expect(component.sectionActiveCounts()['location']).toBe(1);
      expect(component.totalActiveCount()).toBe(1);
    });

    it('makes each tab count the sum of its panels', () => {
      setFilters({
        camera: 'Sony', lens: 'FE', date_from: '2024-01-01', person_id: '1,2', semanticQuery: 'dog', path_prefix: '/a',
        favorites_only: true, min_star_rating: '3', min_score: '6', color_temp: 'warm', min_liqe: '2',
        min_face_quality: '4', min_composition: '5', max_composition: '8',
      });
      const panels = component.sectionActiveCounts();
      const tabs = component.tabActiveCounts();
      for (const id of TAB_IDS) {
        expect(tabs[id], id).toBe(TAB_SECTIONS[id].reduce((sum, panel) => sum + panels[panel], 0));
      }
      expect(tabs.browse).toBe(6);
      expect(tabs.review).toBe(2);
      expect(tabs.quality).toBe(3);
      expect(tabs.subject).toBe(2);
      expect(tabs.display).toBe(0);
    });

    it('adds the fixed-area controls (filename search, similar-to) to the header only', () => {
      setFilters({ camera: 'Sony', search: 'IMG', similar_to: '/a.jpg' });
      expect(component.fixedAreaCount()).toBe(2);
      expect(component.tabActiveCounts().browse).toBe(1);
      expect(component.totalActiveCount()).toBe(3);
    });

    it('does not count the default-on hide toggles', () => {
      expect(component.totalActiveCount()).toBe(0);
    });

    it('agrees with the store-wide count the toolbar and the filter notice use', () => {
      setFilters({
        camera: 'Sony', min_score: '5', max_score: '9', gps_lat: '1', gps_lng: '2', gps_radius_km: '5',
        search: 'IMG', semanticQuery: 'dog', is_monochrome: true, min_topiq: '3', date_to: '2024-02-01',
      });
      const filters = (component as any).store.filters();
      expect(component.totalActiveCount()).toBe(countActiveFilters(filters));
      expect(component.totalActiveCount()).toBe(activeFilterUnits(filters).length);
    });

    it('puts every countable control in a panel, except the header-only filename search, similar-to and the slider-less TOPIQ range', () => {
      const every = Object.fromEntries(Object.entries(DEFAULT_FILTERS).map(([k, v]) => [k, typeof v === 'boolean' ? true : 'x']));
      const unmapped = activeFilterUnits(every as unknown as GalleryFilters).filter(unit => !UNIT_PANEL[unit]);
      expect(unmapped.sort()).toEqual(['search', 'similar_to', 'topiq']);
    });

    it('keeps a hidden metric\'s filter in the header count, so Reset can clear it, but out of every tab', () => {
      (mockStore['config'] as ReturnType<typeof signal<unknown>>).set({ unavailable_metrics: ['liqe_score'] });
      setFilters({ min_liqe: '5' });
      expect(component.totalActiveCount()).toBe(1);
      expect(TAB_IDS.reduce((sum, id) => sum + component.tabActiveCounts()[id], 0)).toBe(0);
    });
  });

  describe('tabs (rendered)', () => {
    let fixture: ComponentFixture<GalleryFilterSidebarComponent>;
    let store: Record<string, any>;
    const messages: Record<string, string> = {
      'gallery.sidebar.tabs.browse': 'Browse',
      'gallery.sidebar.tabs.review': 'Review',
      'gallery.sidebar.tabs.quality': 'Quality',
      'gallery.sidebar.tabs.subject': 'Subject',
      'gallery.sidebar.tabs.display': 'Display',
      'gallery.sidebar.tabs.active_count': '{label}, {count} active',
    };
    const translate = (key: string, vars?: Record<string, string | number>) =>
      Object.entries(vars ?? {}).reduce((text, [name, value]) => text.replace(`{${name}}`, String(value)), messages[key] ?? key);
    const links = () => Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('[mat-tab-link]')) as HTMLElement[];
    const settle = () => fixture.detectChanges();

    beforeEach(() => {
      TestBed.resetTestingModule();
      store = {
        ...mockStore,
        config: signal({ features: {} }),
        cardWidth: signal(220),
        colorTemps: signal([]),
        hueBuckets: signal([]),
        patterns: signal([]),
        types: signal([]),
        currentAlbum: signal(null),
        galleryMode: signal('grid'),
        gpsLocationName: signal(''),
        virtualScroll: signal(false),
        setCardWidth: vi.fn(),
        setGalleryMode: vi.fn(),
        setVirtualScroll: vi.fn(),
      };
      TestBed.configureTestingModule({
        providers: [
          provideNativeDateAdapter(),
          { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
          { provide: GalleryStore, useValue: store },
          { provide: I18nService, useValue: { t: vi.fn(translate), currentLang: vi.fn(() => 'en'), translations: vi.fn(() => ({})) } },
          { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
          { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })) } },
          { provide: MatDialog, useValue: { open: vi.fn() } },
        ],
      });
      fixture = TestBed.createComponent(GalleryFilterSidebarComponent);
      settle();
    });

    const setFilters = (patch: Record<string, unknown>) => {
      store['filters'].set({ ...store['filters'](), ...patch });
      settle();
    };

    describe('tab bar', () => {
      it('exposes a labelled tablist of five tabs with exactly the active one selected', () => {
        const nav = (fixture.nativeElement as HTMLElement).querySelector('nav[mat-tab-nav-bar]')!;
        expect(nav.getAttribute('aria-label')).toBe('gallery.sidebar.tabs.aria_label');
        expect(nav.getAttribute('role')).toBe('tablist');
        const tabs = Array.from(nav.querySelectorAll('[role="tab"]'));
        expect(tabs).toHaveLength(5);
        expect(tabs.map(t => t.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false', 'false', 'false']);
        expect((fixture.nativeElement as HTMLElement).querySelector('[role="tabpanel"]')).toBeTruthy();
      });

      it('moves the selection when a tab is clicked and stores it', () => {
        links()[1].click();
        settle();
        expect(fixture.componentInstance.activeTab()).toBe('review');
        expect(localStorage.getItem('facet_sidebar_tab')).toBe('review');
        expect(links().map(t => t.getAttribute('aria-selected'))).toEqual(['false', 'true', 'false', 'false', 'false']);
      });

      it('shows icons only, each with a tooltip carrying the tab name and an aria-label naming it', () => {
        const items = links();
        expect(items.map(l => l.querySelector('mat-icon')!.textContent!.trim()))
          .toEqual(['travel_explore', 'rule', 'high_quality', 'center_focus_strong', 'display_settings']);
        const tooltips = fixture.debugElement.queryAll(By.css('[mat-tab-link]')).map(d => d.injector.get(MatTooltip).message);
        expect(tooltips).toEqual(['Browse', 'Review', 'Quality', 'Subject', 'Display']);
        expect(items.map(l => l.getAttribute('aria-label'))).toEqual(['Browse', 'Review', 'Quality', 'Subject', 'Display']);
        for (const link of items) expect(link.textContent!.replace(link.querySelector('mat-icon')!.textContent!, '').trim()).toBe('');
      });

      it('names a tab with its active count and puts the count on the icon as a corner badge', () => {
        setFilters({ camera: 'Sony', lens: 'FE' });
        const browse = links()[0];
        expect(browse.getAttribute('aria-label')).toBe('Browse, 2 active');
        const badge = browse.querySelector('mat-icon')!.nextElementSibling!;
        expect(badge.textContent!.trim()).toBe('2');
        expect(badge.getAttribute('aria-hidden')).toBe('true');
        expect(links()[1].getAttribute('aria-label')).toBe('Review');
        expect(links()[1].querySelector('mat-icon')!.nextElementSibling).toBeNull();
      });

      it('hides the tab bar while a filter query is typed', () => {
        fixture.componentInstance.filterQuery.set('sharp');
        settle();
        expect((fixture.nativeElement as HTMLElement).querySelector('nav[mat-tab-nav-bar]')).toBeNull();
      });

      it('finds a filter on any tab, says when nothing matches, and returns to the stored tab when cleared', () => {
        const host = fixture.nativeElement as HTMLElement;
        const quality = ADDITIONAL_FILTERS.find(d => TAB_SECTIONS.quality.includes(d.sectionKey))!;
        const subject = ADDITIONAL_FILTERS.find(d => TAB_SECTIONS.subject.includes(d.sectionKey))!;
        fixture.componentInstance.selectTab('browse');
        settle();
        const stored = localStorage.getItem('facet_sidebar_tab');
        for (const def of [quality, subject]) {
          fixture.componentInstance.filterQuery.set(def.labelKey);
          settle();
          expect(host.querySelector(`[data-metric="${def.id}"]`), def.id).toBeTruthy();
          expect(host.textContent).not.toContain('gallery.sidebar.no_filters_match');
        }
        fixture.componentInstance.filterQuery.set('no-such-filter');
        settle();
        expect(host.querySelector('[data-metric]')).toBeNull();
        expect(host.textContent).toContain('gallery.sidebar.no_filters_match');
        fixture.componentInstance.filterQuery.set('');
        settle();
        expect(host.querySelector('nav[mat-tab-nav-bar]')).toBeTruthy();
        expect(fixture.componentInstance.activeTab()).toBe('browse');
        expect(localStorage.getItem('facet_sidebar_tab')).toBe(stored);
      });
    });

    describe('tab content', () => {
      const titles = () => Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('mat-panel-title'))
        .map(t => t.textContent!.trim());

      it('gives every metric row its own help, as a left tooltip and as the sliders\' description', () => {
        const help = I18N.gallery.sidebar.metric_help as Record<string, string>;
        for (const def of ADDITIONAL_FILTERS) expect(help[def.id], def.id).toBe(def.helpKey);
        let checked = 0;
        for (const tab of ['quality', 'subject'] as const) {
          fixture.componentInstance.selectTab(tab);
          settle();
          for (const def of ADDITIONAL_FILTERS) {
            const rowEl = fixture.debugElement.query(By.css(`[data-metric="${def.id}"]`));
            if (!rowEl) continue;
            const tip = rowEl.query(By.directive(MatTooltip)).injector.get(MatTooltip);
            expect(tip.message, def.id).toBe(def.helpKey);
            expect(tip.position, def.id).toBe('left');
            expect(tip.showDelay, def.id).toBe(600);
            const description = (rowEl.nativeElement as HTMLElement).querySelector(`#metric-help-${def.id}`)!.textContent!.trim();
            expect(description, def.id).toBe(def.helpKey);
            for (const input of (rowEl.nativeElement as HTMLElement).querySelectorAll('input')) {
              expect(input.getAttribute('aria-describedby'), def.id).toBe(`metric-help-${def.id}`);
            }
            checked++;
          }
          if (tab === 'quality') {
            const labelTips = fixture.debugElement.queryAll(By.directive(MatTooltip))
              .filter(d => d.nativeElement.tagName === 'MAT-LABEL').map(d => d.injector.get(MatTooltip).message);
            expect(labelTips).toContain('gallery.sidebar.metric_help.quality_tier');
            expect((fixture.nativeElement as HTMLElement).querySelector('#metric-help-quality_tier')).toBeTruthy();
          }
        }
        expect(checked).toBeGreaterThan(4);
      });

      it('renders only the active tab\'s panels', () => {
        expect(titles().join('|')).toContain('gallery.sidebar.persons');
        fixture.componentInstance.selectTab('quality');
        settle();
        expect(titles().join('|')).toContain('gallery.sidebar.color_quality');
        expect(titles().join('|')).toContain('gallery.sidebar.technical');
        expect(titles().join('|')).not.toContain('gallery.sidebar.face');
        expect(titles().join('|')).not.toContain('gallery.sidebar.persons');
        fixture.componentInstance.selectTab('subject');
        settle();
        expect(titles().join('|')).toContain('gallery.sidebar.face');
        expect(titles().join('|')).toContain('gallery.sidebar.moments');
        expect(titles().join('|')).not.toContain('gallery.sidebar.technical');
        fixture.componentInstance.selectTab('display');
        settle();
        expect(titles()).toHaveLength(0);
        expect((fixture.nativeElement as HTMLElement).querySelector('[data-section="view"]')).toBeTruthy();
      });

      it('keeps the filename search reachable with / from every tab', () => {
        for (const id of TAB_IDS) {
          fixture.componentInstance.selectTab(id);
          settle();
          (document.activeElement as HTMLElement | null)?.blur();
          fixture.componentInstance.focusSearch();
          const input = (fixture.nativeElement as HTMLElement).querySelector('input[placeholder="gallery.search_placeholder"]');
          expect(input, id).toBeTruthy();
          expect(document.activeElement, id).toBe(input);
        }
      });
    });

    describe('header', () => {
      const header = () => (fixture.nativeElement as HTMLElement).querySelector('[data-test="active-count"]')!.parentElement!;

      it('puts the count badge right after the title, as its sibling', () => {
        setFilters({ camera: 'Sony' });
        const badge = (fixture.nativeElement as HTMLElement).querySelector('[data-test="active-count"]')!;
        const title = badge.previousElementSibling!;
        expect(title.textContent!.trim()).toBe('gallery.filters');
        expect(title.parentElement).toBe(badge.parentElement);
        expect(badge.textContent!.trim()).toBe('1');
      });

      it('tells Reset and Close apart: a labelled text button against the only bare icon button, far right', () => {
        setFilters({ camera: 'Sony' });
        const reset = header().querySelector('[data-test="reset"]') as HTMLElement;
        const close = header().querySelector('[data-test="close"]') as HTMLElement;
        expect(reset.textContent).toContain('gallery.reset_filters');
        expect(reset.querySelector('mat-icon')!.textContent!.trim()).toBe('restart_alt');
        expect(reset.getAttribute('aria-label')).toBeNull();
        expect(close.getAttribute('aria-label')).toBe('dialog.close');
        expect(close.querySelector('mat-icon')!.textContent!.trim()).toBe('close');
        expect(close.textContent!.trim()).toBe('close');
        expect(close.classList.contains('md:hidden')).toBe(true);
        expect(header().lastElementChild).toBe(close);
        const tips = fixture.debugElement.queryAll(By.directive(MatTooltip)).map(d => d.injector.get(MatTooltip).message);
        expect(tips).toContain('gallery.sidebar.reset_tooltip');
        expect(tips).toContain('dialog.close');
        reset.click();
        expect(store['resetFilters']).toHaveBeenCalledOnce();
      });

      it('shows no Reset and no badge without active filters, but keeps Close', () => {
        expect((fixture.nativeElement as HTMLElement).querySelector('[data-test="reset"]')).toBeNull();
        expect((fixture.nativeElement as HTMLElement).querySelector('[data-test="active-count"]')).toBeNull();
        expect((fixture.nativeElement as HTMLElement).querySelector('[data-test="close"]')).toBeTruthy();
      });
    });
  });

  describe('semantic search threshold slider (rendered)', () => {
    // The only block in this file that renders the template: the slider is Material
    // markup, so [value]/(valueChange) wiring and the aria attributes cannot be
    // reached through the component's methods alone.
    let fixture: ComponentFixture<GalleryFilterSidebarComponent>;
    let thumb: HTMLInputElement;

    beforeEach(() => {
      TestBed.resetTestingModule();
      const renderedStore = {
        ...mockStore,
        config: signal({ features: { show_semantic_search: true }, search_threshold_default: 0.05 }),
        cardWidth: signal(220),
        colorTemps: signal([]),
        hueBuckets: signal([]),
        patterns: signal([]),
        types: signal([]),
        currentAlbum: signal(null),
        galleryMode: signal('grid'),
        gpsLocationName: signal(''),
        virtualScroll: signal(false),
        setCardWidth: vi.fn(),
        setGalleryMode: vi.fn(),
        setVirtualScroll: vi.fn(),
      };

      TestBed.configureTestingModule({
        providers: [
          provideNativeDateAdapter(),
          // Tooltip hides wait for an animationend jsdom never fires unless animations are off.
          { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
          { provide: GalleryStore, useValue: renderedStore },
          { provide: I18nService, useValue: { t: vi.fn((k: string) => k), currentLang: vi.fn(() => 'en'), translations: vi.fn(() => ({})) } },
          { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
          { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })) } },
          { provide: MatDialog, useValue: { open: vi.fn() } },
        ],
      });

      fixture = TestBed.createComponent(GalleryFilterSidebarComponent);
      fixture.detectChanges();
      thumb = fixture.nativeElement.querySelector('mat-slider input');
    });

    const showTab = (id: SidebarTabId) => {
      fixture.componentInstance.selectTab(id);
      fixture.detectChanges();
    };

    it('lists the advanced metric sections as top-level sections, with no wrapping panel', () => {
      const advanced = fixture.componentInstance.advancedFilterGroups();
      expect(advanced.length).toBeGreaterThan(0);
      for (const group of advanced) {
        showTab(TAB_SECTIONS.quality.includes(group.sectionKey) ? 'quality' : 'subject');
        const panels = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('mat-expansion-panel'));
        const panel = panels.find(el => el.querySelector('mat-panel-title')?.textContent?.includes(group.sectionKey));
        expect(panel, group.sectionKey).toBeDefined();
        expect(panel!.parentElement!.closest('mat-expansion-panel'), group.sectionKey).toBeNull();
      }
    });

    const row = (id: string) => (fixture.nativeElement as HTMLElement).querySelector(`[data-row="${id}"]`) as HTMLElement;
    const VALUES = 'gallery.sidebar.review.values.';
    const REVIEW_ROWS = ['decision', 'bursts', 'duplicates', 'blinks', 'brackets', 'panoramas', 'rejected'];
    const overlay = () => TestBed.inject(OverlayContainer).getContainerElement();
    const trigger = (id: string) => row(id) as HTMLButtonElement;
    const menuItems = () => Array.from(overlay().querySelectorAll('[role="menuitemradio"]')) as HTMLButtonElement[];
    const menuItem = (key: string) => menuItems().find(b => b.getAttribute('data-option') === key) as HTMLButtonElement;
    /** Opens the row's menu, as a user would, and returns its items. */
    const openMenu = (id: string) => {
      trigger(id).click();
      fixture.detectChanges();
      return menuItems();
    };
    /** Opens the row's menu and clicks the item for `key`. */
    const choose = (id: string, key: string) => {
      openMenu(id);
      menuItem(key).click();
      fixture.detectChanges();
    };
    const rowValue = (id: string) => trigger(id).querySelector('[data-value]')?.textContent?.trim();
    const toggleFilters = (patch: Record<string, unknown>) => {
      const filters = TestBed.inject(GalleryStore).filters;
      filters.update(current => ({ ...current, ...patch }));
      fixture.detectChanges();
    };

    it('renders the Review tab without any expansion panel', () => {
      showTab('review');
      expect((fixture.nativeElement as HTMLElement).querySelector('mat-expansion-panel')).toBeNull();
      expect((fixture.nativeElement as HTMLElement).querySelector('[data-section="review"]')).toBeTruthy();
    });

    it('lists the decision, then the sets with Rejected last, as menu rows', () => {
      showTab('review');
      const ids = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button[data-row][aria-haspopup="menu"]')).map(b => b.getAttribute('data-row'));
      expect(ids).toEqual(REVIEW_ROWS);
    });

    it('shows the viewer defaults as the current value of every row, with nothing counted', () => {
      showTab('review');
      expect(rowValue('decision')).toBe(`${VALUES}all`);
      expect(rowValue('rejected')).toBe(`${VALUES}hidden`);
      expect(rowValue('bursts')).toBe(`${VALUES}best_frame`);
      expect(rowValue('duplicates')).toBe(`${VALUES}hidden`);
      expect(rowValue('blinks')).toBe(`${VALUES}hidden`);
      expect(rowValue('brackets')).toBe(`${VALUES}base_exposure`);
      expect(rowValue('panoramas')).toBe(`${VALUES}middle_frame`);
      expect(fixture.componentInstance.totalActiveCount()).toBe(0);
    });

    it('marks only the current option of an opened menu as checked', () => {
      showTab('review');
      toggleFilters({ hide_duplicates: false, duplicates_only: true });
      const items = openMenu('duplicates');
      expect(items.map(i => i.getAttribute('data-option'))).toEqual(['hide', 'all', 'only']);
      expect(items.map(i => i.getAttribute('aria-checked'))).toEqual(['false', 'false', 'true']);
      expect(items.map(i => i.querySelector('mat-icon')!.classList.contains('invisible'))).toEqual([true, true, false]);
    });

    const PATCH_CASES = Object.entries(SEGMENT_PATCHES)
      .flatMap(([id, options]) => Object.entries(options).map(([key, patch]) => [id, key, patch] as const));

    it.each(PATCH_CASES)('writes the %s=%s keys, and the row reads that value back', (id, key, patch) => {
      showTab('review');
      choose(id, key);
      expect(mockStore['updateFilters']).toHaveBeenLastCalledWith(patch);
      toggleFilters(patch);
      expect(fixture.componentInstance.reviewRows().find(r => r.id === id)!.value).toBe(key);
    });

    it.each([
      ['duplicates', { hide_duplicates: false, duplicates_only: true }, { hide_duplicates: true, duplicates_only: false }],
      ['blinks', { hide_blinks: false, blinks_only: true }, { hide_blinks: true, blinks_only: false }],
    ] as const)('lets Hide and Only exclude each other on %s', (id, onlyState, hidePatch) => {
      showTab('review');
      toggleFilters(onlyState);
      expect(rowValue(id)).toBe(`${VALUES}only_these`);
      choose(id, 'hide');
      expect(mockStore['updateFilters']).toHaveBeenLastCalledWith(hidePatch);
    });

    it('reads a stale Hide plus Only as Only, as the server treats it', () => {
      showTab('review');
      toggleFilters({ hide_blinks: true, blinks_only: true });
      expect(rowValue('blinks')).toBe(`${VALUES}only_these`);
    });

    it('counts a row once when it is off its default, and not for a hide toggle', () => {
      showTab('review');
      toggleFilters({ blinks_only: true, hide_blinks: false, hide_bursts: false });
      expect(fixture.componentInstance.totalActiveCount()).toBe(1);
    });

    it.each([
      ['undecided', 'undecided'], ['kept', 'kept'], ['rejected', 'rejected'],
    ] as const)('sets the decision to %s, freezes the rejected row, and thaws it after All', (value, key) => {
      showTab('review');
      expect(trigger('rejected').getAttribute('aria-disabled')).toBeNull();
      choose('decision', key);
      expect(mockStore['updateFilter']).toHaveBeenLastCalledWith('review_status', value);
      toggleFilters({ review_status: value });
      expect(rowValue('decision')).toBe(`${VALUES}${key}`);
      expect(trigger('rejected').getAttribute('aria-disabled')).toBe('true');
      // Still focusable, so its tooltip can say why it is locked.
      expect(trigger('rejected').disabled).toBe(false);
      choose('decision', 'all');
      expect(mockStore['updateFilter']).toHaveBeenLastCalledWith('review_status', '');
      toggleFilters({ review_status: '' });
      expect(trigger('rejected').getAttribute('aria-disabled')).toBeNull();
    });

    it('names the current value in every row trigger, so a screen reader hears "label: value"', () => {
      vi.mocked(TestBed.inject(I18nService).t).mockImplementation((k: string, vars?: Record<string, string | number>) =>
        k.endsWith('review.value_aria') ? `${vars!['label']}: ${vars!['value']}` : k);
      showTab('review');
      toggleFilters({ hide_bursts: false });
      expect(trigger('bursts').getAttribute('aria-label')).toBe(`gallery.sidebar.review.bursts: ${VALUES}all_frames`);
      expect(trigger('rejected').getAttribute('aria-label')).toBe(`gallery.sidebar.review.rejected: ${VALUES}hidden`);
      for (const id of REVIEW_ROWS) expect(trigger(id).getAttribute('aria-haspopup'), id).toBe('menu');
    });

    it.each(REVIEW_ROWS)('gives every %s menu item a title, a description line and a left-hand tooltip with the same description', id => {
      showTab('review');
      const items = openMenu(id);
      expect(items.length).toBeGreaterThanOrEqual(2);
      const descriptions = items.map(item => {
        const lines = Array.from(item.querySelectorAll('span.flex-col > span')).map(l => l.textContent!.trim());
        expect(lines[0], 'title').toMatch(/^gallery\.sidebar\.review\.values\.\w+$/);
        expect(lines[1], 'description').toMatch(/^gallery\.sidebar\.review\.desc\.\w+$/);
        return lines[1];
      });
      const tips = fixture.debugElement.queryAll(By.css('[role="menuitemradio"]')).map(d => d.injector.get(MatTooltip));
      expect(tips.map(t => t.message)).toEqual(descriptions);
      for (const tip of tips) {
        expect(tip.position).toBe('left');
        expect(tip.showDelay).toBe(600);
      }
    });

    it('gives every row, the rating button and toggle a tooltip', () => {
      vi.mocked(TestBed.inject(AuthService).isEdition).mockReturnValue(true);
      showTab('review');
      const section = (fixture.nativeElement as HTMLElement).querySelector('[data-section="review"]') as HTMLElement;
      const rowTips = fixture.debugElement.queryAll(By.css('button[data-row][aria-haspopup="menu"]')).map(d => d.injector.get(MatTooltip));
      expect(rowTips).toHaveLength(7);
      for (const tip of rowTips) {
        expect(tip.message).toMatch(/^gallery\.sidebar\.refine_help\.\w+$/);
        expect(tip.position).toBe('left');
      }
      const ratingTip = fixture.debugElement.query(By.css('button[data-row="rating"]')).injector.get(MatTooltip);
      expect(ratingTip.message).toBe('gallery.sidebar.review.rating_off');
      expect(ratingTip.position).toBe('left');
      const toggles = fixture.debugElement.queryAll(By.css('button[data-toggle]'));
      expect(toggles.map(d => d.nativeElement.getAttribute('data-toggle'))).toEqual(['favorites_only', 'is_monochrome', 'manual_faces_need_review']);
      for (const toggle of toggles) {
        const tip = toggle.injector.get(MatTooltip);
        expect(tip.message).toMatch(/^gallery\.sidebar\.refine_help\.\w+$/);
        expect(tip.position).toBe('left');
      }
      const select = fixture.debugElement.queryAll(By.directive(MatSelect)).filter(d => section.contains(d.nativeElement));
      expect(select.map(d => d.injector.get(MatTooltip).message)).toEqual(['gallery.sidebar.refine_help.sequence_override']);
    });

    const ratingButton = () => fixture.nativeElement.querySelector('button[data-row="rating"]') as HTMLButtonElement;
    const ratingBadge = () => (fixture.nativeElement as HTMLElement).querySelector('[data-test="rating-badge"]')?.textContent?.trim();
    const ratingAria = (count: number, next: number) => `Rating ${count}>${next}`;

    it('shares one row between the rating button and the favorites and monochrome toggles', () => {
      showTab('review');
      const quick = row('quick');
      expect(quick.getAttribute('role')).toBe('group');
      expect(Array.from(quick.querySelectorAll('button')).map(b => b.getAttribute('data-row') ?? b.getAttribute('data-toggle')))
        .toEqual(['rating', 'favorites_only', 'is_monochrome']);
      for (const toggle of Array.from(quick.querySelectorAll('button[data-toggle]'))) expect(toggle.getAttribute('aria-label')).toMatch(/^gallery\.\w+$/);
    });

    it('shows an empty star and no badge while the rating is off', () => {
      showTab('review');
      expect(ratingButton().querySelector('mat-icon')!.textContent!.trim()).toBe('star_border');
      expect(ratingBadge()).toBeUndefined();
      expect(ratingButton().getAttribute('aria-label')).toBe('gallery.sidebar.review.rating_off');
    });

    it('raises the minimum by one per click, and clears it after 5', () => {
      showTab('review');
      const steps: [string, string][] = [['', '1'], ['1', '2'], ['2', '3'], ['3', '4'], ['4', '5'], ['5', '']];
      for (const [from, to] of steps) {
        toggleFilters({ min_star_rating: from });
        ratingButton().click();
        expect(mockStore['updateFilter'], `${from || 'off'} -> ${to || 'off'}`).toHaveBeenLastCalledWith('min_star_rating', to);
      }
    });

    it('stops at a max bound from a link instead of setting a minimum above it', () => {
      showTab('review');
      toggleFilters({ min_star_rating: '3', max_star_rating: '4' });
      ratingButton().click();
      expect(mockStore['updateFilter']).toHaveBeenLastCalledWith('min_star_rating', '4');
      toggleFilters({ min_star_rating: '4' });
      expect(ratingButton().getAttribute('aria-label')).toBe('gallery.sidebar.review.rating_last');
      ratingButton().click();
      expect(mockStore['updateFilter']).toHaveBeenLastCalledWith('min_star_rating', '');
    });

    it.each([['2.5', '3'], ['7', ''], ['0', '1']])('steps an odd minimum %s from a link to %s', (from, to) => {
      showTab('review');
      toggleFilters({ min_star_rating: from, max_star_rating: '' });
      ratingButton().click();
      expect(mockStore['updateFilter']).toHaveBeenLastCalledWith('min_star_rating', to);
    });

    it('shows a filled star with the minimum as a badge, and says what the next click does', () => {
      vi.mocked(TestBed.inject(I18nService).t).mockImplementation((k: string, vars?: Record<string, string | number>) =>
        k.endsWith('review.rating_step') ? ratingAria(Number(vars!['count']), Number(vars!['next'])) : k);
      showTab('review');
      toggleFilters({ min_star_rating: '3' });
      expect(ratingButton().querySelector('mat-icon')!.textContent!.trim()).toBe('star');
      expect(ratingBadge()).toBe('3');
      expect(ratingButton().getAttribute('aria-label')).toBe(ratingAria(3, 4));
      expect(fixture.debugElement.query(By.css('button[data-row="rating"]')).injector.get(MatTooltip).message).toBe(ratingAria(3, 4));
      expect(fixture.componentInstance.sectionActiveCounts()['gallery.sidebar.ratings']).toBe(1);
      toggleFilters({ min_star_rating: '5' });
      expect(ratingBadge()).toBe('5');
      expect(ratingButton().getAttribute('aria-label')).toBe('gallery.sidebar.review.rating_last');
    });

    it('keeps the max rating bound visible when a link set it', () => {
      showTab('review');
      toggleFilters({ min_star_rating: '2', max_star_rating: '4' });
      expect((fixture.nativeElement as HTMLElement).querySelector('[data-test="rating-max"]')!.textContent!.trim()).toBe('≤ 4');
      expect(ratingBadge()).toBe('2');
    });

    it('toggles favorites and monochrome as pressed buttons', () => {
      showTab('review');
      const fav = fixture.nativeElement.querySelector('[data-toggle="favorites_only"]') as HTMLButtonElement;
      expect(fav.getAttribute('aria-pressed')).toBe('false');
      fav.click();
      expect(mockStore['updateFilter']).toHaveBeenLastCalledWith('favorites_only', true);
      toggleFilters({ favorites_only: true });
      expect(fav.getAttribute('aria-pressed')).toBe('true');
      fav.click();
      expect(mockStore['updateFilter']).toHaveBeenLastCalledWith('favorites_only', false);
    });

    it('puts the filename Search first under the header and Find a filter just above the tab bar', () => {
      const html = fixture.nativeElement as HTMLElement;
      const search = html.querySelector('input[placeholder="gallery.search_placeholder"]')!;
      const find = html.querySelector('input[placeholder="gallery.sidebar.find_filter"]')!;
      const nav = html.querySelector('nav[mat-tab-nav-bar]')!;
      const header = html.querySelector('[data-test="close"]')!;
      const order = (a: Element, b: Element) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
      expect(order(header, search)).toBe(true);
      expect(order(search, find)).toBe(true);
      expect(order(find, nav)).toBe(true);
    });

    it('offers face naming in People with no people and semantic search disabled', () => {
      TestBed.inject(GalleryStore).config.update(config => config ? {
        ...config, features: { ...config.features, show_semantic_search: false },
      } : config);
      fixture.detectChanges();
      const controls = Array.from(fixture.nativeElement.querySelectorAll('mat-checkbox')) as HTMLElement[];
      const control = controls.find(el => el.textContent?.includes('gallery.faces_need_names'))!;
      expect(control).toBeTruthy();
      expect(control.closest('mat-expansion-panel')?.textContent).toContain('gallery.sidebar.persons');
      (control.querySelector('input') as HTMLInputElement).click();
      expect(mockStore['updateFilter']).toHaveBeenCalledWith('faces_need_names', true);
    });

    it.each([false, true])('renders the manual-face review toggle only for edition (edition=%s)', edition => {
      const auth = TestBed.inject(AuthService);
      vi.mocked(auth.isEdition).mockReturnValue(edition);
      showTab('review');
      const control = fixture.nativeElement.querySelector('[data-toggle="manual_faces_need_review"]') as HTMLButtonElement | null;
      expect(!!control).toBe(edition);
      if (control) {
        control.click();
        expect(mockStore['updateFilter']).toHaveBeenCalledWith('manual_faces_need_review', true);
      }
    });

    it.each([false, true])('describes face naming using actions available in edition=%s', edition => {
      const auth = TestBed.inject(AuthService);
      vi.mocked(auth.isEdition).mockReturnValue(edition);
      TestBed.inject(GalleryStore).filters.update(filters => ({ ...filters, faces_need_names: true }));
      fixture.detectChanges();
      const hint = fixture.nativeElement.querySelector('#face-naming-hint');
      expect(hint.textContent).toContain(edition ? 'gallery.faces_need_names_hint' : 'gallery.faces_need_names_readonly_hint');
      const input = fixture.nativeElement.querySelector('input[aria-describedby="face-naming-hint"]');
      expect(input).toBeTruthy();
    });

    it('closes its select overlay when the gallery parks', () => {
      showTab('quality');
      const select = fixture.debugElement.query(By.directive(MatSelect)).injector.get(MatSelect);
      select.open();
      fixture.detectChanges();
      expect(select.panelOpen).toBe(true);
      fixture.componentInstance.closeOverlays();
      expect(select.panelOpen).toBe(false);
    });


    it('offers no geolocation without the map feature and forwards the checkbox', () => {
      const labels = Array.from(fixture.nativeElement.querySelectorAll('mat-checkbox')) as HTMLElement[];
      const control = labels.find(el => el.textContent?.includes('gallery.no_geolocation'))!;
      expect(control).toBeTruthy();
      (control.querySelector('input') as HTMLInputElement).click();
      expect(mockStore['updateFilter']).toHaveBeenCalledWith('no_gps', '1');
    });

    it('renders the thumb seeded from the config default, announced with its unit', () => {
      expect(thumb).toBeTruthy();
      expect(thumb.value).toBe('5');
      expect(thumb.getAttribute('aria-valuetext')).toBe('5%');
      expect(thumb.getAttribute('aria-describedby')).toBe('semantic-search-threshold-hint');
      expect(fixture.nativeElement.querySelector('#semantic-search-threshold-hint')).toBeTruthy();
    });

    it('shows the grid / mosaic layout toggle below md too', () => {
      showTab('display');
      const label = [...(fixture.nativeElement as HTMLElement).querySelectorAll('span')]
        .find(e => e.textContent?.trim() === 'gallery.layout_mode');
      expect(label).toBeTruthy();
      const row = label!.parentElement!;
      expect(row.classList.contains('hidden')).toBe(false);
      expect(row.classList.contains('flex')).toBe(true);
    });

    it('hideTooltips takes a showing tooltip off the page', async () => {
      const tooltip = fixture.debugElement.queryAll(By.directive(MatTooltip))[0].injector.get(MatTooltip);
      tooltip.show(0);
      await new Promise(resolve => setTimeout(resolve, 30));
      const container = TestBed.inject(OverlayContainer).getContainerElement();
      expect(container.querySelector('.mat-mdc-tooltip')).not.toBeNull();
      fixture.componentInstance.hideTooltips();
      await new Promise(resolve => setTimeout(resolve, 30));
      expect(container.querySelector('.mat-mdc-tooltip')).toBeNull();
      expect(tooltip._isTooltipVisible()).toBe(false);
    });

    it('wires the thumb back to the component, readout and valuetext following the drag', () => {
      thumb.value = '31';
      thumb.dispatchEvent(new Event('input'));
      thumb.dispatchEvent(new Event('change'));
      fixture.detectChanges();

      expect(fixture.nativeElement.textContent).toContain('31%');
      expect(thumb.getAttribute('aria-valuetext')).toBe('31%');
    });
  });
});
