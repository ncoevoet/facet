import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { CompareFiltersService } from './compare-filters.service';
import { ComparisonAbTabComponent } from './comparison-ab-tab.component';

describe('ComparisonAbTabComponent', () => {
  let component: ComparisonAbTabComponent;
  let mockApi: { get: jest.Mock; post: jest.Mock };
  let mockSnackBar: { open: jest.Mock };
  let mockI18n: { t: jest.Mock };
  let mockAuth: { isEdition: jest.Mock };
  let compareFilters: { selectedCategory: ReturnType<typeof signal<string>> };

  beforeEach(() => {
    mockApi = {
      get: jest.fn(() => of({})),
      post: jest.fn(() => of({})),
    };
    mockSnackBar = { open: jest.fn() };
    mockI18n = { t: jest.fn((key: string) => key) };
    mockAuth = { isEdition: jest.fn(() => true) };
    compareFilters = { selectedCategory: signal('portrait') };

    TestBed.configureTestingModule({
      providers: [
        ComparisonAbTabComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: AuthService, useValue: mockAuth },
        { provide: CompareFiltersService, useValue: compareFilters },
      ],
    });
    component = TestBed.inject(ComparisonAbTabComponent);
  });

  describe('loadNextPair', () => {
    it('should set pair data on success', async () => {
      mockApi.get.mockReturnValue(of({ a: '/photo1.jpg', b: '/photo2.jpg', score_a: 7.5, score_b: 8.2 }));

      await component.loadNextPair();

      expect(mockApi.get).toHaveBeenCalledWith('/comparison/next_pair', { category: 'portrait', strategy: 'uncertainty' });
      expect(component.pairA()).toBe('/photo1.jpg');
      expect(component.pairB()).toBe('/photo2.jpg');
      expect(component.pairScoreA()).toBe(7.5);
      expect(component.pairScoreB()).toBe(8.2);
      expect(component.pairLoading()).toBe(false);
      expect(component.pairError()).toBeNull();
    });

    it('should clear pair and set error on API error response', async () => {
      mockApi.get.mockReturnValue(of({ error: 'Not enough photos' }));

      await component.loadNextPair();

      expect(component.pairA()).toBeNull();
      expect(component.pairB()).toBeNull();
      expect(component.pairError()).toBe('Not enough photos');
      expect(component.pairLoading()).toBe(false);
    });

    it('should set error on network failure', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));

      await component.loadNextPair();

      expect(component.pairError()).toBe('comparison.error_loading_pair');
      expect(component.pairLoading()).toBe(false);
    });

    it('should do nothing without category', async () => {
      compareFilters.selectedCategory.set('');

      await component.loadNextPair();

      expect(mockApi.get).not.toHaveBeenCalledWith('/comparison/next_pair', expect.anything());
      expect(component.pairLoading()).toBe(false);
    });

    it('should clear pair and set no_more_pairs when response has no a/b', async () => {
      mockApi.get.mockReturnValue(of({}));

      await component.loadNextPair();

      expect(component.pairA()).toBeNull();
      expect(component.pairB()).toBeNull();
      expect(component.pairError()).toBe('comparison.no_more_pairs');
    });
  });

  describe('submitComparison', () => {
    beforeEach(() => {
      component.pairA.set('/photo1.jpg');
      component.pairB.set('/photo2.jpg');
      mockApi.post.mockReturnValue(of({}));
      mockApi.get.mockReturnValue(of({ a: '/photo3.jpg', b: '/photo4.jpg', score_a: 6, score_b: 9 }));
    });

    it('should post correct payload', async () => {
      await component.submitComparison('a');

      expect(mockApi.post).toHaveBeenCalledWith('/comparison/submit', {
        photo_a: '/photo1.jpg',
        photo_b: '/photo2.jpg',
        winner: 'a',
        category: 'portrait',
      });
    });

    it('should increment comparisonCount', async () => {
      expect(component.comparisonCount()).toBe(0);

      await component.submitComparison('b');

      expect(component.comparisonCount()).toBe(1);
    });

    it('should load next pair after submit', async () => {
      await component.submitComparison('tie');

      expect(mockApi.get).toHaveBeenCalledWith('/comparison/next_pair', expect.objectContaining({ category: 'portrait' }));
      expect(component.pairA()).toBe('/photo3.jpg');
    });
  });

  describe('onKeydown', () => {
    beforeEach(() => {
      component.pairA.set('/photo1.jpg');
      component.pairB.set('/photo2.jpg');
      mockApi.post.mockReturnValue(of({}));
      mockApi.get.mockReturnValue(of({ a: '/next1.jpg', b: '/next2.jpg' }));
    });

    it('should call submitComparison("a") on ArrowLeft', () => {
      const spy = jest.spyOn(component, 'submitComparison');
      const event = new KeyboardEvent('keydown', { key: 'ArrowLeft' });
      component.onKeydown(event);
      expect(spy).toHaveBeenCalledWith('a');
    });

    it('should call submitComparison("b") on ArrowRight', () => {
      const spy = jest.spyOn(component, 'submitComparison');
      const event = new KeyboardEvent('keydown', { key: 'ArrowRight' });
      component.onKeydown(event);
      expect(spy).toHaveBeenCalledWith('b');
    });

    it('should call submitComparison("tie") on "t"', () => {
      const spy = jest.spyOn(component, 'submitComparison');
      const event = new KeyboardEvent('keydown', { key: 't' });
      component.onKeydown(event);
      expect(spy).toHaveBeenCalledWith('tie');
    });

    it('should call loadNextPair on "s"', () => {
      const spy = jest.spyOn(component, 'loadNextPair');
      const event = new KeyboardEvent('keydown', { key: 's' });
      component.onKeydown(event);
      expect(spy).toHaveBeenCalled();
    });

    it('should ignore when target is INPUT', () => {
      const spy = jest.spyOn(component, 'submitComparison');
      const input = document.createElement('input');
      const event = new KeyboardEvent('keydown', { key: 'ArrowLeft' });
      Object.defineProperty(event, 'target', { value: input });
      component.onKeydown(event);
      expect(spy).not.toHaveBeenCalled();
    });

    it('should ignore when pairA is null', () => {
      component.pairA.set(null);
      const spy = jest.spyOn(component, 'submitComparison');
      const event = new KeyboardEvent('keydown', { key: 'ArrowLeft' });
      component.onKeydown(event);
      expect(spy).not.toHaveBeenCalled();
    });
  });

  describe('currentWeightKeys', () => {
    it('should filter keys ending in _percent from learnedWeights', () => {
      component.learnedWeights.set({
        available: true,
        current_weights: {
          aesthetic_percent: 30,
          face_quality_percent: 20,
          bonus: 0.5,
          tech_sharpness: 10,
        },
        suggested_weights: {},
      });

      expect(component.currentWeightKeys()).toEqual(['aesthetic_percent', 'face_quality_percent']);
    });

    it('should return empty array when learnedWeights is null', () => {
      component.learnedWeights.set(null);
      expect(component.currentWeightKeys()).toEqual([]);
    });
  });

  describe('applyWeights', () => {
    it('should emit merged current + suggested weights', () => {
      const emitSpy = jest.spyOn(component.weightsApplied, 'emit');
      component.learnedWeights.set({
        available: true,
        current_weights: { aesthetic_percent: 30, face_quality_percent: 20 },
        suggested_weights: { aesthetic_percent: 35, comp_score_percent: 15 },
      });

      component.applyWeights();

      expect(emitSpy).toHaveBeenCalledWith({
        aesthetic_percent: 35,
        face_quality_percent: 20,
        comp_score_percent: 15,
      });
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('should not emit when learnedWeights has no suggested_weights', () => {
      const emitSpy = jest.spyOn(component.weightsApplied, 'emit');
      component.learnedWeights.set({ available: true });

      component.applyWeights();

      expect(emitSpy).not.toHaveBeenCalled();
    });
  });

  describe('onStrategyChange', () => {
    it('should update strategy signal', () => {
      component.onStrategyChange('random');
      expect(component.strategy()).toBe('random');
    });

    it('should load next pair when pairA exists', () => {
      component.pairA.set('/photo.jpg');
      mockApi.get.mockReturnValue(of({ a: '/a.jpg', b: '/b.jpg' }));
      const spy = jest.spyOn(component, 'loadNextPair');

      component.onStrategyChange('boundary');

      expect(spy).toHaveBeenCalled();
    });

    it('should not load next pair when pairA is null', () => {
      component.pairA.set(null);
      const spy = jest.spyOn(component, 'loadNextPair');

      component.onStrategyChange('active');

      expect(spy).not.toHaveBeenCalled();
    });
  });
});
