import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { CompareFiltersService } from './compare-filters.service';
import { ComparisonWeightsTabComponent } from './comparison-weights-tab.component';

describe('ComparisonWeightsTabComponent', () => {
  let component: ComparisonWeightsTabComponent;
  let mockApi: { get: jest.Mock; post: jest.Mock };
  let mockSnackBar: { open: jest.Mock };
  let mockI18n: { t: jest.Mock };
  let compareFilters: { selectedCategory: ReturnType<typeof signal<string>> };

  beforeEach(() => {
    mockApi = {
      get: jest.fn(() => of({})),
      post: jest.fn(() => of({})),
    };
    mockSnackBar = { open: jest.fn() };
    mockI18n = { t: jest.fn((key: string) => key) };
    compareFilters = { selectedCategory: signal('') };

    TestBed.configureTestingModule({
      providers: [
        ComparisonWeightsTabComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: CompareFiltersService, useValue: compareFilters },
      ],
    });
    component = TestBed.inject(ComparisonWeightsTabComponent);
  });

  describe('setWeight', () => {
    it('should update an existing weight', () => {
      component.weights.set({ aesthetic_percent: 30, comp_score_percent: 20 });
      component.setWeight('aesthetic_percent', 45);
      expect(component.weights()['aesthetic_percent']).toBe(45);
    });

    it('should preserve other weights', () => {
      component.weights.set({ aesthetic_percent: 30, comp_score_percent: 20 });
      component.setWeight('aesthetic_percent', 45);
      expect(component.weights()['comp_score_percent']).toBe(20);
    });

    it('should add a new key', () => {
      component.weights.set({ aesthetic_percent: 30 });
      component.setWeight('face_quality_percent', 10);
      expect(component.weights()['face_quality_percent']).toBe(10);
      expect(component.weights()['aesthetic_percent']).toBe(30);
    });

    it('should allow setting a weight to zero', () => {
      component.weights.set({ aesthetic_percent: 30 });
      component.setWeight('aesthetic_percent', 0);
      expect(component.weights()['aesthetic_percent']).toBe(0);
    });
  });

  describe('weightTotal', () => {
    it('should sum all weight values', () => {
      component.weights.set({ aesthetic_percent: 30, comp_score_percent: 20, face_quality_percent: 50 });
      expect(component.weightTotal()).toBe(100);
    });

    it('should return 0 for empty weights', () => {
      component.weights.set({});
      expect(component.weightTotal()).toBe(0);
    });

    it('should handle partial weights', () => {
      component.weights.set({ aesthetic_percent: 25, comp_score_percent: 15 });
      expect(component.weightTotal()).toBe(40);
    });

    it('should treat falsy values as 0', () => {
      component.weights.set({ aesthetic_percent: 0, comp_score_percent: 30 });
      expect(component.weightTotal()).toBe(30);
    });
  });

  describe('normalizeWeights', () => {
    it('should normalize weights to sum to 100', () => {
      component.weights.set({ aesthetic_percent: 20, comp_score_percent: 30 });
      component.normalizeWeights();
      expect(component.weightTotal()).toBe(100);
    });

    it('should do nothing when total is zero', () => {
      component.weights.set({ aesthetic_percent: 0, comp_score_percent: 0 });
      component.normalizeWeights();
      expect(component.weights()['aesthetic_percent']).toBe(0);
      expect(component.weights()['comp_score_percent']).toBe(0);
    });

    it('should scale proportionally', () => {
      component.weights.set({ a_percent: 10, b_percent: 10 });
      component.normalizeWeights();
      // 10/20 * 100 = 50 each
      expect(component.weights()['a_percent']).toBe(50);
      expect(component.weights()['b_percent']).toBe(50);
    });

    it('should handle rounding so total is exactly 100', () => {
      component.weights.set({ a_percent: 33, b_percent: 33, c_percent: 33 });
      component.normalizeWeights();
      expect(component.weightTotal()).toBe(100);
    });

    it('should not change weights that already sum to 100', () => {
      component.weights.set({ a_percent: 60, b_percent: 40 });
      component.normalizeWeights();
      expect(component.weights()['a_percent']).toBe(60);
      expect(component.weights()['b_percent']).toBe(40);
    });
  });

  describe('hasChanges', () => {
    it('should be false initially (empty weights match)', () => {
      expect(component.hasChanges()).toBe(false);
    });

    it('should be false after loading weights (saved matches current)', () => {
      const w = { aesthetic_percent: 30, comp_score_percent: 20 };
      component.weights.set({ ...w });
      component.savedWeights.set({ ...w });
      component.modifiers.set({});
      component.savedModifiers.set({});
      component.filters.set({});
      component.savedFilters.set({});
      expect(component.hasChanges()).toBe(false);
    });

    it('should be true when a weight changes', () => {
      const w = { aesthetic_percent: 30 };
      component.savedWeights.set({ ...w });
      component.weights.set({ aesthetic_percent: 40 });
      expect(component.hasChanges()).toBe(true);
    });

    it('should be true when modifiers change', () => {
      component.weights.set({});
      component.savedWeights.set({});
      component.savedModifiers.set({});
      component.modifiers.set({ bonus: 1.5 });
      expect(component.hasChanges()).toBe(true);
    });

    it('should be true when filters change', () => {
      component.weights.set({});
      component.savedWeights.set({});
      component.modifiers.set({});
      component.savedModifiers.set({});
      component.savedFilters.set({});
      component.filters.set({ has_face: true });
      expect(component.hasChanges()).toBe(true);
    });
  });

  describe('modifierErrors', () => {
    it('should return empty when all modifiers are in range', () => {
      component.modifiers.set({ bonus: 2, noise_tolerance_multiplier: 1.0, _clipping_multiplier: 3.0 });
      expect(Object.keys(component.modifierErrors())).toHaveLength(0);
    });

    it('should return empty for empty modifiers', () => {
      component.modifiers.set({});
      expect(Object.keys(component.modifierErrors())).toHaveLength(0);
    });

    it('should flag bonus below -5', () => {
      component.modifiers.set({ bonus: -6 });
      expect(component.modifierErrors()['bonus']).toBe('comparison.validation.bonus_range');
    });

    it('should flag bonus above 5', () => {
      component.modifiers.set({ bonus: 6 });
      expect(component.modifierErrors()['bonus']).toBe('comparison.validation.bonus_range');
    });

    it('should accept bonus at boundary values', () => {
      component.modifiers.set({ bonus: -5 });
      expect(component.modifierErrors()['bonus']).toBeUndefined();
      component.modifiers.set({ bonus: 5 });
      expect(component.modifierErrors()['bonus']).toBeUndefined();
    });

    it('should flag noise_tolerance_multiplier below 0', () => {
      component.modifiers.set({ noise_tolerance_multiplier: -0.1 });
      expect(component.modifierErrors()['noise_tolerance_multiplier']).toBe('comparison.validation.noise_tolerance_range');
    });

    it('should flag noise_tolerance_multiplier above 2', () => {
      component.modifiers.set({ noise_tolerance_multiplier: 2.5 });
      expect(component.modifierErrors()['noise_tolerance_multiplier']).toBe('comparison.validation.noise_tolerance_range');
    });

    it('should accept noise_tolerance_multiplier at boundary values', () => {
      component.modifiers.set({ noise_tolerance_multiplier: 0 });
      expect(component.modifierErrors()['noise_tolerance_multiplier']).toBeUndefined();
      component.modifiers.set({ noise_tolerance_multiplier: 2 });
      expect(component.modifierErrors()['noise_tolerance_multiplier']).toBeUndefined();
    });

    it('should flag _clipping_multiplier below 0', () => {
      component.modifiers.set({ _clipping_multiplier: -1 });
      expect(component.modifierErrors()['_clipping_multiplier']).toBe('comparison.validation.clipping_multiplier_range');
    });

    it('should flag _clipping_multiplier above 5', () => {
      component.modifiers.set({ _clipping_multiplier: 6 });
      expect(component.modifierErrors()['_clipping_multiplier']).toBe('comparison.validation.clipping_multiplier_range');
    });

    it('should accept _clipping_multiplier at boundary values', () => {
      component.modifiers.set({ _clipping_multiplier: 0 });
      expect(component.modifierErrors()['_clipping_multiplier']).toBeUndefined();
      component.modifiers.set({ _clipping_multiplier: 5 });
      expect(component.modifierErrors()['_clipping_multiplier']).toBeUndefined();
    });

    it('should report multiple errors simultaneously', () => {
      component.modifiers.set({ bonus: -10, noise_tolerance_multiplier: 5, _clipping_multiplier: 10 });
      const errs = component.modifierErrors();
      expect(Object.keys(errs)).toHaveLength(3);
    });
  });

  describe('filterErrors', () => {
    it('should return empty for empty filters', () => {
      component.filters.set({});
      expect(Object.keys(component.filterErrors())).toHaveLength(0);
    });

    it('should return empty for valid filter values', () => {
      component.filters.set({ face_ratio_min: 0.1, face_ratio_max: 0.8, iso_min: 100, iso_max: 6400 });
      expect(Object.keys(component.filterErrors())).toHaveLength(0);
    });

    it('should flag face_ratio out of 0..1', () => {
      component.filters.set({ face_ratio_min: -0.1 });
      expect(component.filterErrors()['face_ratio_min']).toBe('comparison.validation.ratio_range');
      component.filters.set({ face_ratio_max: 1.5 });
      expect(component.filterErrors()['face_ratio_max']).toBe('comparison.validation.ratio_range');
    });

    it('should accept face_ratio at boundary values', () => {
      component.filters.set({ face_ratio_min: 0, face_ratio_max: 1 });
      expect(component.filterErrors()['face_ratio_min']).toBeUndefined();
      expect(component.filterErrors()['face_ratio_max']).toBeUndefined();
    });

    it('should flag min > max', () => {
      component.filters.set({ face_ratio_min: 0.8, face_ratio_max: 0.2 });
      const errs = component.filterErrors();
      expect(errs['face_ratio_min']).toBe('comparison.validation.min_gt_max');
      expect(errs['face_ratio_max']).toBe('comparison.validation.min_gt_max');
    });

    it('should flag negative values for non-negative fields', () => {
      component.filters.set({ iso_min: -100 });
      expect(component.filterErrors()['iso_min']).toBe('comparison.validation.non_negative');
    });

    it('should flag negative focal_length', () => {
      component.filters.set({ focal_length_min: -10 });
      expect(component.filterErrors()['focal_length_min']).toBe('comparison.validation.non_negative');
    });

    it('should flag negative f_stop', () => {
      component.filters.set({ f_stop_min: -1 });
      expect(component.filterErrors()['f_stop_min']).toBe('comparison.validation.non_negative');
    });

    it('should flag shutter_speed above 60', () => {
      component.filters.set({ shutter_speed_max: 61 });
      expect(component.filterErrors()['shutter_speed_max']).toBe('comparison.validation.shutter_range');
    });

    it('should accept shutter_speed at boundary values', () => {
      component.filters.set({ shutter_speed_min: 0, shutter_speed_max: 60 });
      expect(component.filterErrors()['shutter_speed_min']).toBeUndefined();
      expect(component.filterErrors()['shutter_speed_max']).toBeUndefined();
    });

    it('should flag iso min > max', () => {
      component.filters.set({ iso_min: 6400, iso_max: 100 });
      const errs = component.filterErrors();
      expect(errs['iso_min']).toBe('comparison.validation.min_gt_max');
      expect(errs['iso_max']).toBe('comparison.validation.min_gt_max');
    });

    it('should flag luminance out of 0..1', () => {
      component.filters.set({ luminance_min: -0.5 });
      expect(component.filterErrors()['luminance_min']).toBe('comparison.validation.ratio_range');
      component.filters.set({ luminance_max: 2.0 });
      expect(component.filterErrors()['luminance_max']).toBe('comparison.validation.ratio_range');
    });

    it('should not flag range error when only min or only max is set', () => {
      component.filters.set({ face_ratio_min: 0.5 });
      expect(component.filterErrors()['face_ratio_min']).toBeUndefined();
    });
  });

  describe('hasValidationErrors', () => {
    it('should be false when no errors', () => {
      component.modifiers.set({});
      component.filters.set({});
      expect(component.hasValidationErrors()).toBe(false);
    });

    it('should be true when modifier errors exist', () => {
      component.modifiers.set({ bonus: 100 });
      expect(component.hasValidationErrors()).toBe(true);
    });

    it('should be true when filter errors exist', () => {
      component.filters.set({ face_ratio_min: -1 });
      expect(component.hasValidationErrors()).toBe(true);
    });

    it('should be true when both modifier and filter errors exist', () => {
      component.modifiers.set({ bonus: 100 });
      component.filters.set({ face_ratio_min: -1 });
      expect(component.hasValidationErrors()).toBe(true);
    });
  });

  describe('setModifierNum', () => {
    it('should set a numeric value', () => {
      component.modifiers.set({});
      component.setModifierNum('bonus', 1.5);
      expect(component.modifiers()['bonus']).toBe(1.5);
    });

    it('should delete key on null', () => {
      component.modifiers.set({ bonus: 1.5 });
      component.setModifierNum('bonus', null);
      expect(component.modifiers()['bonus']).toBeUndefined();
    });

    it('should delete key on NaN', () => {
      component.modifiers.set({ bonus: 1.5 });
      component.setModifierNum('bonus', NaN);
      expect(component.modifiers()['bonus']).toBeUndefined();
    });

    it('should preserve other modifiers', () => {
      component.modifiers.set({ bonus: 1, noise_tolerance_multiplier: 0.5 });
      component.setModifierNum('bonus', 2);
      expect(component.modifiers()['noise_tolerance_multiplier']).toBe(0.5);
    });

    it('should allow setting to zero', () => {
      component.modifiers.set({});
      component.setModifierNum('bonus', 0);
      expect(component.modifiers()['bonus']).toBe(0);
    });
  });

  describe('setModifierBool', () => {
    it('should set key to true when value is true', () => {
      component.modifiers.set({});
      component.setModifierBool('_skip_clipping_penalty', true);
      expect(component.modifiers()['_skip_clipping_penalty']).toBe(true);
    });

    it('should delete key when value is false', () => {
      component.modifiers.set({ _skip_clipping_penalty: true });
      component.setModifierBool('_skip_clipping_penalty', false);
      expect(component.modifiers()['_skip_clipping_penalty']).toBeUndefined();
    });

    it('should preserve other modifiers', () => {
      component.modifiers.set({ bonus: 1.5, _skip_clipping_penalty: true });
      component.setModifierBool('_skip_clipping_penalty', false);
      expect(component.modifiers()['bonus']).toBe(1.5);
    });
  });

  describe('setFilterNum', () => {
    it('should set a numeric value', () => {
      component.filters.set({});
      component.setFilterNum('face_ratio_min', 0.2);
      expect(component.filters()['face_ratio_min']).toBe(0.2);
    });

    it('should delete key on null', () => {
      component.filters.set({ face_ratio_min: 0.2 });
      component.setFilterNum('face_ratio_min', null);
      expect(component.filters()['face_ratio_min']).toBeUndefined();
    });

    it('should delete key on NaN', () => {
      component.filters.set({ iso_min: 100 });
      component.setFilterNum('iso_min', NaN);
      expect(component.filters()['iso_min']).toBeUndefined();
    });

    it('should preserve other filters', () => {
      component.filters.set({ face_ratio_min: 0.1, iso_min: 100 });
      component.setFilterNum('face_ratio_min', 0.5);
      expect(component.filters()['iso_min']).toBe(100);
    });

    it('should allow setting to zero', () => {
      component.filters.set({});
      component.setFilterNum('iso_min', 0);
      expect(component.filters()['iso_min']).toBe(0);
    });
  });

  describe('setFilterTags', () => {
    it('should parse comma-separated tags', () => {
      component.filters.set({});
      component.setFilterTags('required_tags', 'landscape, mountain, beach');
      expect(component.filters()['required_tags']).toEqual(['landscape', 'mountain', 'beach']);
    });

    it('should trim whitespace from tags', () => {
      component.filters.set({});
      component.setFilterTags('required_tags', '  landscape ,  mountain  ');
      expect(component.filters()['required_tags']).toEqual(['landscape', 'mountain']);
    });

    it('should delete key on empty string', () => {
      component.filters.set({ required_tags: ['landscape'] });
      component.setFilterTags('required_tags', '');
      expect(component.filters()['required_tags']).toBeUndefined();
    });

    it('should delete key when only whitespace/commas', () => {
      component.filters.set({ required_tags: ['landscape'] });
      component.setFilterTags('required_tags', ' , , ');
      expect(component.filters()['required_tags']).toBeUndefined();
    });

    it('should handle a single tag', () => {
      component.filters.set({});
      component.setFilterTags('excluded_tags', 'portrait');
      expect(component.filters()['excluded_tags']).toEqual(['portrait']);
    });
  });

  describe('getFilterTags', () => {
    it('should join array as comma-separated', () => {
      component.filters.set({ required_tags: ['landscape', 'mountain'] });
      expect(component.getFilterTags('required_tags')).toBe('landscape, mountain');
    });

    it('should return empty string for missing key', () => {
      component.filters.set({});
      expect(component.getFilterTags('required_tags')).toBe('');
    });

    it('should return empty string for non-array value', () => {
      component.filters.set({ required_tags: 'not-an-array' });
      expect(component.getFilterTags('required_tags')).toBe('');
    });
  });

  describe('setFilterBool', () => {
    it('should set true for "true" string', () => {
      component.filters.set({});
      component.setFilterBool('has_face', 'true');
      expect(component.filters()['has_face']).toBe(true);
    });

    it('should set false for "false" string', () => {
      component.filters.set({});
      component.setFilterBool('has_face', 'false');
      expect(component.filters()['has_face']).toBe(false);
    });

    it('should delete key for empty string', () => {
      component.filters.set({ has_face: true });
      component.setFilterBool('has_face', '');
      expect(component.filters()['has_face']).toBeUndefined();
    });

    it('should preserve other filters', () => {
      component.filters.set({ has_face: true, iso_min: 100 });
      component.setFilterBool('has_face', '');
      expect(component.filters()['iso_min']).toBe(100);
    });
  });

  describe('getFilterBoolValue', () => {
    it('should return "true" for true', () => {
      component.filters.set({ has_face: true });
      expect(component.getFilterBoolValue('has_face')).toBe('true');
    });

    it('should return "false" for false', () => {
      component.filters.set({ has_face: false });
      expect(component.getFilterBoolValue('has_face')).toBe('false');
    });

    it('should return empty string for missing key', () => {
      component.filters.set({});
      expect(component.getFilterBoolValue('has_face')).toBe('');
    });
  });

  describe('loadWeights', () => {
    it('should do nothing without a selected category', async () => {
      compareFilters.selectedCategory.set('');
      await component.loadWeights();
      expect(mockApi.get).not.toHaveBeenCalledWith('/comparison/category_weights', expect.anything());
    });

    it('should set weights, modifiers, and filters from API response', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({
        weights: { aesthetic_percent: 35, face_quality_percent: 25 },
        modifiers: { bonus: 1.5 },
        filters: { has_face: true },
      }));

      await component.loadWeights();

      expect(component.weights()).toEqual({ aesthetic_percent: 35, face_quality_percent: 25 });
      expect(component.modifiers()).toEqual({ bonus: 1.5 });
      expect(component.filters()).toEqual({ has_face: true });
    });

    it('should set saved state to match current after load', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({
        weights: { aesthetic_percent: 35 },
        modifiers: { bonus: 1.5 },
        filters: { has_face: true },
      }));

      await component.loadWeights();

      expect(component.savedWeights()).toEqual({ aesthetic_percent: 35 });
      expect(component.savedModifiers()).toEqual({ bonus: 1.5 });
      expect(component.savedFilters()).toEqual({ has_face: true });
    });

    it('should have hasChanges false after load', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({
        weights: { aesthetic_percent: 35 },
        modifiers: { bonus: 1.5 },
        filters: { has_face: true },
      }));

      await component.loadWeights();

      expect(component.hasChanges()).toBe(false);
    });

    it('should handle missing modifiers and filters in response', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({
        weights: { aesthetic_percent: 35 },
      }));

      await component.loadWeights();

      expect(component.modifiers()).toEqual({});
      expect(component.filters()).toEqual({});
    });

    it('should set loading to true during request and false after', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({
        weights: { aesthetic_percent: 35 },
        modifiers: {},
        filters: {},
      }));

      await component.loadWeights();

      expect(component.loading()).toBe(false);
    });

    it('should show snackbar on error and set loading false', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));

      await component.loadWeights();

      expect(mockSnackBar.open).toHaveBeenCalled();
      expect(component.loading()).toBe(false);
    });

    it('should pass category param to API', async () => {
      compareFilters.selectedCategory.set('landscape');
      mockApi.get.mockReturnValue(of({ weights: {}, modifiers: {}, filters: {} }));

      await component.loadWeights();

      expect(mockApi.get).toHaveBeenCalledWith('/comparison/category_weights', { category: 'landscape' });
    });
  });

  describe('saveWeights', () => {
    it('should do nothing without a selected category', async () => {
      compareFilters.selectedCategory.set('');
      await component.saveWeights();
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should post correct payload', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 60, face_quality_percent: 40 });
      component.modifiers.set({ bonus: 1.0 });
      component.filters.set({ has_face: true });

      await component.saveWeights();

      expect(mockApi.post).toHaveBeenCalledWith('/config/update_weights', {
        category: 'portrait',
        weights: { aesthetic_percent: 60, face_quality_percent: 40 },
        modifiers: { bonus: 1.0 },
        filters: { has_face: true },
      });
    });

    it('should normalize weights before saving when total is not 100', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ a_percent: 25, b_percent: 25 });
      component.modifiers.set({});
      component.filters.set({});

      await component.saveWeights();

      // After normalization: 50/50
      expect(component.weightTotal()).toBe(100);
      expect(mockApi.post).toHaveBeenCalled();
    });

    it('should update saved state after successful save', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 60, face_quality_percent: 40 });
      component.modifiers.set({ bonus: 2.0 });
      component.filters.set({ has_face: true });

      await component.saveWeights();

      expect(component.savedWeights()).toEqual(component.weights());
      expect(component.savedModifiers()).toEqual(component.modifiers());
      expect(component.savedFilters()).toEqual(component.filters());
      expect(component.hasChanges()).toBe(false);
    });

    it('should set saving to false after completion', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 100 });

      await component.saveWeights();

      expect(component.saving()).toBe(false);
    });

    it('should show snackbar on error and set saving false', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 100 });
      mockApi.post.mockReturnValue(throwError(() => new Error('Save failed')));

      await component.saveWeights();

      expect(mockSnackBar.open).toHaveBeenCalled();
      expect(component.saving()).toBe(false);
    });

    it('should show success snackbar on save', async () => {
      compareFilters.selectedCategory.set('portrait');
      component.weights.set({ aesthetic_percent: 100 });

      await component.saveWeights();

      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.weights_saved', '', { duration: 3000 });
    });
  });

  describe('recalculateScores', () => {
    it('should do nothing without a selected category', async () => {
      compareFilters.selectedCategory.set('');
      await component.recalculateScores();
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should post to recompute endpoint', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.post.mockReturnValue(of({ success: true, message: 'Done' }));

      await component.recalculateScores();

      expect(mockApi.post).toHaveBeenCalledWith('/stats/categories/recompute', { category: 'portrait' });
    });

    it('should set recalculating to false after completion', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.post.mockReturnValue(of({ success: true }));

      await component.recalculateScores();

      expect(component.recalculating()).toBe(false);
    });

    it('should show snackbar on error', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.post.mockReturnValue(throwError(() => new Error('Fail')));

      await component.recalculateScores();

      expect(mockSnackBar.open).toHaveBeenCalled();
      expect(component.recalculating()).toBe(false);
    });
  });

  describe('loadPreview', () => {
    it('should do nothing without a selected category', async () => {
      compareFilters.selectedCategory.set('');
      await component.loadPreview();
      expect(mockApi.get).not.toHaveBeenCalledWith('/photos', expect.anything());
    });

    it('should fetch photos for the selected category', async () => {
      compareFilters.selectedCategory.set('portrait');
      const photos = [{ path: '/a.jpg', filename: 'a.jpg', aggregate: 8, aesthetic: 7, comp_score: 6, face_quality: 9 }];
      mockApi.get.mockReturnValue(of({ photos }));

      await component.loadPreview();

      expect(mockApi.get).toHaveBeenCalledWith('/photos', {
        category: 'portrait',
        sort: 'aggregate',
        sort_direction: 'DESC',
        per_page: 6,
        page: 1,
      });
      expect(component.previewPhotos()).toEqual(photos);
    });

    it('should set previewLoading to false after completion', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({ photos: [] }));

      await component.loadPreview();

      expect(component.previewLoading()).toBe(false);
    });

    it('should set empty array when response has no photos', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(of({}));

      await component.loadPreview();

      expect(component.previewPhotos()).toEqual([]);
    });

    it('should show snackbar on error and set previewLoading false', async () => {
      compareFilters.selectedCategory.set('portrait');
      mockApi.get.mockReturnValue(throwError(() => new Error('Fail')));

      await component.loadPreview();

      expect(mockSnackBar.open).toHaveBeenCalled();
      expect(component.previewLoading()).toBe(false);
    });
  });

  describe('weightKeys', () => {
    it('should return only keys ending in _percent', () => {
      component.weights.set({ aesthetic_percent: 30, comp_score_percent: 20, bonus: 5 });
      expect(component.weightKeys()).toEqual(['aesthetic_percent', 'comp_score_percent']);
    });

    it('should return empty array for empty weights', () => {
      component.weights.set({});
      expect(component.weightKeys()).toEqual([]);
    });
  });

  describe('getModifierNum', () => {
    it('should return numeric value when set', () => {
      component.modifiers.set({ bonus: 2.5 });
      expect(component.getModifierNum('bonus')).toBe(2.5);
    });

    it('should return null for missing key', () => {
      component.modifiers.set({});
      expect(component.getModifierNum('bonus')).toBeNull();
    });
  });

  describe('getFilterNum', () => {
    it('should return numeric value when set', () => {
      component.filters.set({ face_ratio_min: 0.3 });
      expect(component.getFilterNum('face_ratio_min')).toBe(0.3);
    });

    it('should return null for missing key', () => {
      component.filters.set({});
      expect(component.getFilterNum('face_ratio_min')).toBeNull();
    });
  });

  describe('setFilter', () => {
    it('should set arbitrary filter values', () => {
      component.filters.set({});
      component.setFilter('tag_match_mode', 'all');
      expect(component.filters()['tag_match_mode']).toBe('all');
    });

    it('should preserve other filters', () => {
      component.filters.set({ has_face: true });
      component.setFilter('tag_match_mode', 'any');
      expect(component.filters()['has_face']).toBe(true);
    });
  });
});
