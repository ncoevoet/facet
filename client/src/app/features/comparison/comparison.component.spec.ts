import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { CompareFiltersService } from './compare-filters.service';
import { ComparisonComponent, WeightIconPipe } from './comparison.component';

describe('ComparisonComponent', () => {
  let component: ComparisonComponent;
  let mockApi: { get: jest.Mock; post: jest.Mock; delete: jest.Mock };
  let mockSnackBar: { open: jest.Mock };
  let mockI18n: { t: jest.Mock };
  let mockAuth: { isEdition: jest.Mock };
  let mockStore: { types: ReturnType<typeof signal<{ id: string; count: number }[]>>; loadTypeCounts: jest.Mock };
  let compareFilters: { selectedCategory: ReturnType<typeof signal<string>> };

  beforeEach(() => {
    mockApi = {
      get: jest.fn(() => of({})),
      post: jest.fn(() => of({})),
      delete: jest.fn(() => of({})),
    };
    mockSnackBar = { open: jest.fn() };
    mockI18n = { t: jest.fn((key: string) => key) };
    mockAuth = { isEdition: jest.fn(() => true) };
    mockStore = {
      types: signal([]),
      loadTypeCounts: jest.fn(() => Promise.resolve()),
    };
    compareFilters = { selectedCategory: signal('') };

    TestBed.configureTestingModule({
      providers: [
        ComparisonComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: AuthService, useValue: mockAuth },
        { provide: GalleryStore, useValue: mockStore },
        { provide: CompareFiltersService, useValue: compareFilters },
      ],
    });
    component = TestBed.inject(ComparisonComponent);
  });

  describe('WeightIconPipe', () => {
    let pipe: WeightIconPipe;

    beforeEach(() => {
      pipe = new WeightIconPipe();
    });

    it('should return correct icon for known keys', () => {
      expect(pipe.transform('aesthetic_percent')).toBe('auto_awesome');
      expect(pipe.transform('composition_percent')).toBe('grid_on');
      expect(pipe.transform('face_quality_percent')).toBe('face');
      expect(pipe.transform('tech_sharpness_percent')).toBe('center_focus_strong');
      expect(pipe.transform('color_percent')).toBe('palette');
      expect(pipe.transform('exposure_percent')).toBe('exposure');
      expect(pipe.transform('noise_percent')).toBe('grain');
    });

    it('should return fallback icon for unknown keys', () => {
      expect(pipe.transform('unknown_key')).toBe('tune');
    });
  });

  describe('setWeight', () => {
    it('should update a weight value', () => {
      component.weights.set({ aesthetic_percent: 30, composition_percent: 20 });
      component.setWeight('aesthetic_percent', 45);
      expect(component.weights()['aesthetic_percent']).toBe(45);
    });

    it('should preserve other weights', () => {
      component.weights.set({ aesthetic_percent: 30, composition_percent: 20 });
      component.setWeight('aesthetic_percent', 45);
      expect(component.weights()['composition_percent']).toBe(20);
    });

    it('should add new weight keys', () => {
      component.weights.set({});
      component.setWeight('noise_percent', 10);
      expect(component.weights()['noise_percent']).toBe(10);
    });
  });

  describe('weightTotal computed', () => {
    it('should sum all weight values', () => {
      component.weights.set({
        aesthetic_percent: 35,
        composition_percent: 25,
        face_quality_percent: 20,
        tech_sharpness_percent: 10,
        color_percent: 5,
        exposure_percent: 3,
        noise_percent: 2,
      });
      expect(component.weightTotal()).toBe(100);
    });

    it('should return 0 for empty weights', () => {
      component.weights.set({});
      expect(component.weightTotal()).toBe(0);
    });

    it('should handle partial weights', () => {
      component.weights.set({ aesthetic_percent: 30, composition_percent: 20 });
      expect(component.weightTotal()).toBe(50);
    });
  });

  describe('loadCategories', () => {
    it('should call store.loadTypeCounts when types are empty', async () => {
      mockStore.types.set([]);
      await component.loadCategories();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });

    it('should not call loadTypeCounts when types are already populated', async () => {
      mockStore.types.set([{ id: 'portrait', count: 10 }]);
      mockStore.loadTypeCounts.mockClear();
      await component.loadCategories();
      expect(mockStore.loadTypeCounts).not.toHaveBeenCalled();
    });

    it('should set selectedCategory to first type when none selected', async () => {
      mockStore.types.set([{ id: 'portrait', count: 10 }, { id: 'landscape', count: 5 }]);
      compareFilters.selectedCategory.set('');
      await component.loadCategories();
      expect(compareFilters.selectedCategory()).toBe('portrait');
    });

    it('should not overwrite an already-selected category', async () => {
      mockStore.types.set([{ id: 'portrait', count: 10 }, { id: 'landscape', count: 5 }]);
      compareFilters.selectedCategory.set('landscape');
      await component.loadCategories();
      expect(compareFilters.selectedCategory()).toBe('landscape');
    });

    it('should not set category when types are empty', async () => {
      mockStore.types.set([]);
      compareFilters.selectedCategory.set('');
      await component.loadCategories();
      expect(compareFilters.selectedCategory()).toBe('');
    });

    it('should show error on loadTypeCounts failure', async () => {
      mockStore.loadTypeCounts.mockRejectedValue(new Error('fail'));
      await component.loadCategories();
      expect(mockSnackBar.open).toHaveBeenCalledWith(
        'comparison.error_loading_categories',
        '',
        { duration: 4000 },
      );
    });
  });

  describe('loadWeights', () => {
    it('should do nothing if no category is selected', async () => {
      compareFilters.selectedCategory.set('');
      mockApi.get.mockClear();
      await component.loadWeights();
      expect(mockApi.get).not.toHaveBeenCalled();
    });

    it('should load and set weights, modifiers, and filters', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({
        weights: { aesthetic_percent: 40, composition_percent: 30 },
        modifiers: { bonus: 0.5 },
        filters: { has_face: true },
      }));
      await component.loadWeights();
      expect(component.weights()).toEqual({ aesthetic_percent: 40, composition_percent: 30 });
      expect(component.modifiers()).toEqual({ bonus: 0.5 });
      expect(component.filters()).toEqual({ has_face: true });
    });

    it('should handle missing modifiers and filters gracefully', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({ weights: { aesthetic_percent: 100 } }));
      await component.loadWeights();
      expect(component.modifiers()).toEqual({});
      expect(component.filters()).toEqual({});
    });

    it('hasChanges should be false immediately after loadWeights', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({
        weights: { aesthetic_percent: 60, composition_percent: 40 },
        modifiers: { bonus: 1.0 },
        filters: { has_face: true },
      }));
      await component.loadWeights();
      expect(component.hasChanges()).toBe(false);
    });

    it('should set loading to false after completion', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({ weights: {}, modifiers: {}, filters: {} }));
      await component.loadWeights();
      expect(component.loading()).toBe(false);
    });

    it('should set loading to false on error', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      await component.loadWeights();
      expect(component.loading()).toBe(false);
    });
  });

  describe('saveWeights', () => {
    it('should post weights, modifiers, and filters for selected category', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 100 });
      component.modifiers.set({ bonus: 0.5 });
      component.filters.set({ has_face: true });

      await component.saveWeights();

      expect(mockApi.post).toHaveBeenCalledWith('/config/update_weights', {
        category: 'portrait',
        weights: { aesthetic_percent: 100 },
        modifiers: { bonus: 0.5 },
        filters: { has_face: true },
      });
    });

    it('should show success snackbar', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 100 });
      await component.saveWeights();
      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.weights_saved', '', { duration: 3000 });
    });

    it('should do nothing if no category selected', async () => {
      compareFilters.selectedCategory.set('');
      await component.saveWeights();
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should update savedModifiers and savedFilters so hasChanges returns false', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 100 });
      component.modifiers.set({ bonus: 1.0 });
      component.filters.set({ has_face: true });
      await component.saveWeights();
      expect(component.hasChanges()).toBe(false);
    });

    it('should set saving to false after completion', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 100 });
      await component.saveWeights();
      expect(component.saving()).toBe(false);
    });
  });

  describe('hasChanges', () => {
    it('should return false in initial state (weights, modifiers, filters all empty)', () => {
      // Initial state: weights={}, savedWeights={}, modifiers={}, filters={} — all match
      expect(component.hasChanges()).toBe(false);
    });

    it('should return true when a weight key is added', () => {
      // savedWeights is still {}, so adding a key creates a difference
      component.weights.set({ aesthetic_percent: 50 });
      expect(component.hasChanges()).toBe(true);
    });

    it('should return true when modifiers change after load', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({ weights: { aesthetic_percent: 50 }, modifiers: {}, filters: {} }));
      await component.loadWeights();
      // After load, hasChanges should be false
      expect(component.hasChanges()).toBe(false);
      // Now modify a modifier
      component.modifiers.set({ bonus: 1.0 });
      expect(component.hasChanges()).toBe(true);
    });

    it('should return true when filters change after load', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({ weights: {}, modifiers: {}, filters: {} }));
      await component.loadWeights();
      expect(component.hasChanges()).toBe(false);
      component.filters.set({ has_face: true });
      expect(component.hasChanges()).toBe(true);
    });
  });

  describe('modifierErrors', () => {
    it('returns empty object for valid modifier values', () => {
      component.modifiers.set({ bonus: 1.0, noise_tolerance_multiplier: 0.5, _clipping_multiplier: 1.5 });
      expect(component.modifierErrors()).toEqual({});
    });

    it('returns error for bonus below -5', () => {
      component.modifiers.set({ bonus: -6 });
      expect(component.modifierErrors()['bonus']).toBeDefined();
    });

    it('returns error for bonus above 5', () => {
      component.modifiers.set({ bonus: 5.1 });
      expect(component.modifierErrors()['bonus']).toBeDefined();
    });

    it('does not error for bonus at boundary values -5 and 5', () => {
      component.modifiers.set({ bonus: -5 });
      expect(component.modifierErrors()['bonus']).toBeUndefined();
      component.modifiers.set({ bonus: 5 });
      expect(component.modifierErrors()['bonus']).toBeUndefined();
    });

    it('returns error for noise_tolerance_multiplier above 2', () => {
      component.modifiers.set({ noise_tolerance_multiplier: 2.5 });
      expect(component.modifierErrors()['noise_tolerance_multiplier']).toBeDefined();
    });

    it('returns error for noise_tolerance_multiplier below 0', () => {
      component.modifiers.set({ noise_tolerance_multiplier: -0.1 });
      expect(component.modifierErrors()['noise_tolerance_multiplier']).toBeDefined();
    });

    it('returns error for _clipping_multiplier above 5', () => {
      component.modifiers.set({ _clipping_multiplier: 5.1 });
      expect(component.modifierErrors()['_clipping_multiplier']).toBeDefined();
    });

    it('returns error for _clipping_multiplier below 0', () => {
      component.modifiers.set({ _clipping_multiplier: -1 });
      expect(component.modifierErrors()['_clipping_multiplier']).toBeDefined();
    });

    it('returns no error for missing optional modifier keys', () => {
      component.modifiers.set({});
      expect(component.modifierErrors()).toEqual({});
    });
  });

  describe('filterErrors', () => {
    it('returns empty object for valid filter values', () => {
      component.filters.set({ face_ratio_min: 0.1, face_ratio_max: 0.9 });
      expect(component.filterErrors()).toEqual({});
    });

    it('returns error for face_ratio_min above 1', () => {
      component.filters.set({ face_ratio_min: 1.5 });
      expect(component.filterErrors()['face_ratio_min']).toBeDefined();
    });

    it('returns error for face_ratio_max above 1', () => {
      component.filters.set({ face_ratio_max: 1.1 });
      expect(component.filterErrors()['face_ratio_max']).toBeDefined();
    });

    it('returns error when min > max for face_ratio', () => {
      component.filters.set({ face_ratio_min: 0.8, face_ratio_max: 0.2 });
      const errs = component.filterErrors();
      expect(errs['face_ratio_min']).toBeDefined();
      expect(errs['face_ratio_max']).toBeDefined();
    });

    it('returns error when iso_min > iso_max', () => {
      component.filters.set({ iso_min: 3200, iso_max: 800 });
      const errs = component.filterErrors();
      expect(errs['iso_min']).toBeDefined();
      expect(errs['iso_max']).toBeDefined();
    });

    it('returns error for negative face_count_min', () => {
      component.filters.set({ face_count_min: -1 });
      expect(component.filterErrors()['face_count_min']).toBeDefined();
    });

    it('returns error when shutter_speed_min > 60', () => {
      component.filters.set({ shutter_speed_min: 61 });
      expect(component.filterErrors()['shutter_speed_min']).toBeDefined();
    });

    it('does not error for empty filters object', () => {
      component.filters.set({});
      expect(component.filterErrors()).toEqual({});
    });
  });

  describe('hasValidationErrors', () => {
    it('returns false when no errors', () => {
      component.modifiers.set({});
      component.filters.set({});
      expect(component.hasValidationErrors()).toBe(false);
    });

    it('returns true when modifier has error', () => {
      component.modifiers.set({ bonus: 99 });
      expect(component.hasValidationErrors()).toBe(true);
    });

    it('returns true when filter has error', () => {
      component.filters.set({ face_ratio_min: 2.0 });
      expect(component.hasValidationErrors()).toBe(true);
    });

    it('returns false for valid modifier boundary values', () => {
      component.modifiers.set({ bonus: 5, noise_tolerance_multiplier: 2, _clipping_multiplier: 5 });
      expect(component.hasValidationErrors()).toBe(false);
    });
  });

  describe('setModifierNum', () => {
    it('sets a numeric modifier value', () => {
      component.setModifierNum('bonus', 1.5);
      expect(component.modifiers()['bonus']).toBe(1.5);
    });

    it('deletes key when value is null', () => {
      component.modifiers.set({ bonus: 1.0 });
      component.setModifierNum('bonus', null);
      expect('bonus' in component.modifiers()).toBe(false);
    });

    it('deletes key when value is NaN', () => {
      component.modifiers.set({ bonus: 1.0 });
      component.setModifierNum('bonus', NaN);
      expect('bonus' in component.modifiers()).toBe(false);
    });

    it('preserves other modifier keys', () => {
      component.modifiers.set({ bonus: 1.0, noise_tolerance_multiplier: 0.5 });
      component.setModifierNum('bonus', 2.0);
      expect(component.modifiers()['noise_tolerance_multiplier']).toBe(0.5);
    });
  });

  describe('setFilterNum', () => {
    it('sets a numeric filter value', () => {
      component.setFilterNum('face_ratio_min', 0.1);
      expect(component.filters()['face_ratio_min']).toBe(0.1);
    });

    it('deletes key when value is null', () => {
      component.filters.set({ face_ratio_min: 0.1 });
      component.setFilterNum('face_ratio_min', null);
      expect('face_ratio_min' in component.filters()).toBe(false);
    });

    it('deletes key when value is NaN', () => {
      component.filters.set({ face_ratio_min: 0.1 });
      component.setFilterNum('face_ratio_min', NaN);
      expect('face_ratio_min' in component.filters()).toBe(false);
    });
  });

  describe('loadPreview', () => {
    it('should fetch preview photos for selected category', async () => {
      compareFilters.selectedCategory.set('portrait');
      const photos = [
        { path: '/a.jpg', filename: 'a.jpg', aggregate: 8, aesthetic: 7, comp_score: 6, face_quality: 9 },
      ];
      mockApi.get.mockReturnValue(of({ photos }));

      await component.loadPreview();

      expect(mockApi.get).toHaveBeenCalledWith('/photos', expect.objectContaining({
        category: 'portrait',
        sort: 'aggregate',
      }));
      expect(component.previewPhotos()).toEqual(photos);
    });

    it('should not fetch when no category is selected', async () => {
      compareFilters.selectedCategory.set('');
      mockApi.get.mockClear();
      await component.loadPreview();
      expect(mockApi.get).not.toHaveBeenCalled();
    });

    it('should set previewLoading to false after completion', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({ photos: [] }));
      await component.loadPreview();
      expect(component.previewLoading()).toBe(false);
    });
  });

  describe('snapshot CRUD', () => {
    it('should load snapshots', async () => {
      const snaps = [
        { id: 1, name: 'Baseline', category: 'portrait', weights: {}, created_at: '2024-01-01' },
      ];
      mockApi.get.mockReturnValue(of({ snapshots: snaps }));

      await component.loadSnapshots();

      expect(mockApi.get).toHaveBeenCalledWith('/config/weight_snapshots', expect.any(Object));
      expect(component.snapshots()).toEqual(snaps);
    });

    it('should save snapshot and reload list', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 35 });
      component.snapshotName.set('My Snapshot');
      mockApi.post.mockReturnValue(of({}));
      mockApi.get.mockReturnValue(of({ snapshots: [] }));

      await component.saveSnapshot();

      expect(mockApi.post).toHaveBeenCalledWith('/config/save_snapshot', {
        category: 'portrait',
        description: 'My Snapshot',
      });
      expect(component.snapshotName()).toBe('');
    });

    it('should not save snapshot with empty name', async () => {
      component.snapshotName.set('   ');
      await component.saveSnapshot();
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should restore snapshot and reload weights', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.post.mockReturnValue(of({}));
      mockApi.get.mockReturnValue(of({ weights: { aesthetic_percent: 40 }, modifiers: {}, filters: {} }));

      await component.restoreSnapshot(5);

      expect(mockApi.post).toHaveBeenCalledWith('/config/restore_weights', { snapshot_id: 5 });
    });

    it('should show info snackbar for delete (not supported)', async () => {
      await component.deleteSnapshot(5);
      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.delete_not_supported', '', { duration: 3000 });
    });
  });

  describe('constructor', () => {
    it('should call loadCategories on construction, triggering store.loadTypeCounts when types are empty', () => {
      // types is empty by default in beforeEach, so loadTypeCounts should be called
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });
  });
});
