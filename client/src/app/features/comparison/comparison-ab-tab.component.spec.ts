import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { COMPARE_TAB_INDEX, CompareFiltersService } from './compare-filters.service';
import { ComparisonAbTabComponent } from './comparison-ab-tab.component';

describe('ComparisonAbTabComponent', () => {
   
  let component: any;
  let mockApi: { get: Mock; post: Mock };
  let mockSnackBar: { open: Mock };
  let mockI18n: { t: Mock };
  let mockAuth: { isEdition: Mock };
  let journal: { record: Mock };
  let compareFilters: { selectedCategory: ReturnType<typeof signal<string>>; strategy: ReturnType<typeof signal<string>>; activeTab: ReturnType<typeof signal<number>> };

  beforeEach(() => {
    mockApi = {
      get: vi.fn(() => of({})),
      post: vi.fn(() => of({})),
    };
    mockSnackBar = { open: vi.fn() };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockAuth = { isEdition: vi.fn(() => true) };
    journal = { record: vi.fn() };
    compareFilters = { selectedCategory: signal('portrait'), strategy: signal('uncertainty'), activeTab: signal(0) };

    TestBed.configureTestingModule({
      providers: [
        ComparisonAbTabComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: AuthService, useValue: mockAuth },
        { provide: UserActivityJournal, useValue: journal },
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

    it.each(['a', 'b', 'tie'])('journals the %s answer with both paths and the category', async winner => {
      await component.submitComparison(winner);

      expect(journal.record).toHaveBeenCalledTimes(1);
      expect(journal.record).toHaveBeenCalledWith('compare', ['/photo1.jpg', '/photo2.jpg'], { category: 'portrait', winner });
    });

    it('journals nothing when the submit fails', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));

      await component.submitComparison('a');

      expect(journal.record).not.toHaveBeenCalled();
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
      compareFilters.activeTab.set(COMPARE_TAB_INDEX.ab);
      component.pairA.set('/photo1.jpg');
      component.pairB.set('/photo2.jpg');
      mockApi.post.mockReturnValue(of({}));
      mockApi.get.mockReturnValue(of({ a: '/next1.jpg', b: '/next2.jpg' }));
    });

    it('should call submitComparison("a") on ArrowLeft', () => {
      const spy = vi.spyOn(component, 'submitComparison');
      const event = new KeyboardEvent('keydown', { key: 'ArrowLeft' });
      component.onKeydown(event);
      expect(spy).toHaveBeenCalledWith('a');
    });

    it('should call submitComparison("b") on ArrowRight', () => {
      const spy = vi.spyOn(component, 'submitComparison');
      const event = new KeyboardEvent('keydown', { key: 'ArrowRight' });
      component.onKeydown(event);
      expect(spy).toHaveBeenCalledWith('b');
    });

    it('should call submitComparison("tie") on "t"', () => {
      const spy = vi.spyOn(component, 'submitComparison');
      const event = new KeyboardEvent('keydown', { key: 't' });
      component.onKeydown(event);
      expect(spy).toHaveBeenCalledWith('tie');
    });

    it('should call skipPair on "s"', () => {
      const spy = vi.spyOn(component, 'skipPair');
      const event = new KeyboardEvent('keydown', { key: 's' });
      component.onKeydown(event);
      expect(spy).toHaveBeenCalled();
    });

    it('should ignore when target is INPUT', () => {
      const spy = vi.spyOn(component, 'submitComparison');
      const input = document.createElement('input');
      const event = new KeyboardEvent('keydown', { key: 'ArrowLeft' });
      Object.defineProperty(event, 'target', { value: input });
      component.onKeydown(event);
      expect(spy).not.toHaveBeenCalled();
    });

    it('should ignore when pairA is null', () => {
      component.pairA.set(null);
      const spy = vi.spyOn(component, 'submitComparison');
      const event = new KeyboardEvent('keydown', { key: 'ArrowLeft' });
      component.onKeydown(event);
      expect(spy).not.toHaveBeenCalled();
    });

    it('should ignore every key while another compare tab is active', () => {
      // mat-tab-group keeps this tab's DOM alive, so window keydowns keep
      // arriving: without the tab gate a hidden pair would record results.
      compareFilters.activeTab.set(COMPARE_TAB_INDEX.snapshots);
      const submit = vi.spyOn(component, 'submitComparison');
      const skip = vi.spyOn(component, 'skipPair');
      for (const key of ['ArrowLeft', 'ArrowRight', 't', 's']) {
        component.onKeydown(new KeyboardEvent('keydown', { key }));
      }
      expect(submit).not.toHaveBeenCalled();
      expect(skip).not.toHaveBeenCalled();
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
      const emitSpy = vi.spyOn(component.weightsApplied, 'emit');
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
      const emitSpy = vi.spyOn(component.weightsApplied, 'emit');
      component.learnedWeights.set({ available: true });

      component.applyWeights();

      expect(emitSpy).not.toHaveBeenCalled();
    });
  });

  describe('skipPair', () => {
    beforeEach(() => {
      component.pairA.set('/photo1.jpg');
      component.pairB.set('/photo2.jpg');
      mockApi.post.mockReturnValue(of({}));
      mockApi.get.mockReturnValue(of({ a: '/photo3.jpg', b: '/photo4.jpg', score_a: 6, score_b: 9 }));
    });

    it('should post winner=skip and load next pair', async () => {
      await component.skipPair();

      expect(mockApi.post).toHaveBeenCalledWith('/comparison/submit', {
        photo_a: '/photo1.jpg',
        photo_b: '/photo2.jpg',
        winner: 'skip',
        category: 'portrait',
      });
      expect(component.pairA()).toBe('/photo3.jpg');
    });

    it('journals a skip, so unseen pairs cannot be inferred', async () => {
      await component.skipPair();

      expect(journal.record).toHaveBeenCalledWith('compare', ['/photo1.jpg', '/photo2.jpg'], { category: 'portrait', winner: 'skip' });
    });

    it('should not increment comparisonCount', async () => {
      expect(component.comparisonCount()).toBe(0);

      await component.skipPair();

      expect(component.comparisonCount()).toBe(0);
    });

    it('should set error on failure', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));

      await component.skipPair();

      expect(component.pairError()).toBe('comparison.error_submitting');
    });

    it('should do nothing without category', async () => {
      compareFilters.selectedCategory.set('');

      await component.skipPair();

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('suggestDisabled', () => {
    it('should be true when stats are null', () => {
      component.comparisonStats.set(null);
      expect(component.suggestDisabled()).toBe(true);
    });

    it('should be true when total_comparisons is below threshold', () => {
      component.comparisonStats.set({ total_comparisons: 10, min_comparisons_for_optimization: 30, winner_breakdown: {} });
      expect(component.suggestDisabled()).toBe(true);
    });

    it('should be false when total_comparisons meets threshold', () => {
      component.comparisonStats.set({ total_comparisons: 30, min_comparisons_for_optimization: 30, winner_breakdown: {} });
      expect(component.suggestDisabled()).toBe(false);
    });

    it('should be true when loading', () => {
      component.comparisonStats.set({ total_comparisons: 100, min_comparisons_for_optimization: 30, winner_breakdown: {} });
      component.learnedWeightsLoading.set(true);
      expect(component.suggestDisabled()).toBe(true);
    });
  });

  describe('suggestTooltip', () => {
    it('should return empty string when stats are null', () => {
      component.comparisonStats.set(null);
      expect(component.suggestTooltip()).toBe('');
    });

    it('should return disabled tooltip when below threshold', () => {
      component.comparisonStats.set({ total_comparisons: 5, min_comparisons_for_optimization: 30, winner_breakdown: {} });
      component.suggestTooltip();
      expect(mockI18n.t).toHaveBeenCalledWith('compare.tooltips.suggest_weights_disabled', { count: 5, min: 30 });
    });

    it('should return normal tooltip when threshold met', () => {
      component.comparisonStats.set({ total_comparisons: 50, min_comparisons_for_optimization: 30, winner_breakdown: {} });
      expect(component.suggestTooltip()).toBe('compare.tooltips.suggest_weights');
    });
  });

  describe('onStrategyChange', () => {
    it('should offer learning as a selectable strategy', () => {
      expect((component as unknown as { strategies: readonly string[] }).strategies).toContain('learning');
      component.onStrategyChange('learning');
      expect(component.strategy()).toBe('learning');
    });

    it('should update strategy signal', () => {
      component.onStrategyChange('random');
      expect(component.strategy()).toBe('random');
    });

    it('should load next pair when pairA exists', () => {
      component.pairA.set('/photo.jpg');
      mockApi.get.mockReturnValue(of({ a: '/a.jpg', b: '/b.jpg' }));
      const spy = vi.spyOn(component, 'loadNextPair');

      component.onStrategyChange('boundary');

      expect(spy).toHaveBeenCalled();
    });

    it('should not load next pair when pairA is null', () => {
      component.pairA.set(null);
      const spy = vi.spyOn(component, 'loadNextPair');

      component.onStrategyChange('active');

      expect(spy).not.toHaveBeenCalled();
    });
  });
});

describe('ComparisonAbTabComponent pair-selection strategy on the wire', () => {
  let http: HttpTestingController;
  let component: any;
  let filters: CompareFiltersService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ComparisonAbTabComponent,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => true) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    filters = TestBed.inject(CompareFiltersService);
    filters.selectedCategory.set('portrait');
    component = TestBed.inject(ComparisonAbTabComponent);
  });

  afterEach(() => {
    http.match(() => true);
  });

  it('sends no strategy while it is unset, so the server uses its configured default', () => {
    void component.loadNextPair();
    const req = http.expectOne((r) => r.url === '/api/comparison/next_pair');
    expect(req.request.params.keys()).not.toContain('strategy');
    expect(req.request.params.get('category')).toBe('portrait');
  });

  it('sends the strategy the user picked', () => {
    component.onStrategyChange('boundary');
    void component.loadNextPair();
    const req = http.expectOne((r) => r.url === '/api/comparison/next_pair');
    expect(req.request.params.get('strategy')).toBe('boundary');
  });

  it('shows the server-configured strategy from the stats while none is picked', () => {
    expect(component.shownStrategy()).toBe('');
    component.comparisonStats.set({ pair_selection_strategy: 'learning' });
    expect(component.shownStrategy()).toBe('learning');
    component.onStrategyChange('boundary');
    expect(component.shownStrategy()).toBe('boundary');
  });
});
