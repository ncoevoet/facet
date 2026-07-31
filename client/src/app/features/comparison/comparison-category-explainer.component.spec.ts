import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { ComparisonCategoryExplainerComponent } from './comparison-category-explainer.component';

describe('ComparisonCategoryExplainerComponent', () => {

  let component: any;
  let mockApi: { post: Mock };

  beforeEach(() => {
    mockApi = { post: vi.fn(() => of({})) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
      ],
    });
    TestBed.runInInjectionContext(() => {
      component = new ComparisonCategoryExplainerComponent();
    });
  });

  describe('load', () => {
    it('does nothing without a path', async () => {
      await component.load('', 'sports');
      expect(mockApi.post).not.toHaveBeenCalled();
      expect(component.result()).toBeNull();
    });

    it('does nothing without a target category', async () => {
      await component.load('/a.jpg', '');
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('calls suggest_filters with path and target_category', async () => {
      mockApi.post.mockReturnValue(of({
        current_category: 'silhouette',
        target_category: 'sports',
        conflicts: [],
        suggestions: [],
        no_conflicts: false,
      }));

      await component.load('/a.jpg', 'sports');

      expect(mockApi.post).toHaveBeenCalledWith('/comparison/suggest_filters', { path: '/a.jpg', target_category: 'sports' });
    });

    it('stores the response in result', async () => {
      const response = {
        current_category: 'silhouette',
        target_category: 'sports',
        conflicts: [{ type: 'above_maximum', filter: 'shutter_speed_max', message: 'Shutter speed is above maximum' }],
        suggestions: [{ type: 'raise_maximum', filter: 'shutter_speed_max', message: 'Raise shutter_speed_max from 0.02 to 0.033' }],
        no_conflicts: false,
      };
      mockApi.post.mockReturnValue(of(response));

      await component.load('/a.jpg', 'sports');

      expect(component.result()).toEqual(response);
    });

    it('sets loading false after completion', async () => {
      mockApi.post.mockReturnValue(of({ current_category: 'a', target_category: 'b', conflicts: [], suggestions: [], no_conflicts: true }));

      await component.load('/a.jpg', 'sports');

      expect(component.loading()).toBe(false);
    });

    it('sets error and clears result on failure', async () => {
      component.result.set({ current_category: 'a', target_category: 'b', conflicts: [], suggestions: [], no_conflicts: true });
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));

      await component.load('/a.jpg', 'sports');

      expect(component.error()).toBe(true);
      expect(component.result()).toBeNull();
      expect(component.loading()).toBe(false);
    });
  });

  describe('retry', () => {
    it('re-runs load with the current input values', async () => {
      mockApi.post.mockReturnValue(of({ current_category: 'a', target_category: 'b', conflicts: [], suggestions: [], no_conflicts: true }));
      // Stub the (required) input signals directly rather than going through a
      // full fixture + setInput -- consistent with this file's lightweight,
      // fixture-free instantiation style.
      component.path = () => '/a.jpg';
      component.targetCategory = () => 'sports';

      component.retry();
      await new Promise(resolve => setTimeout(resolve, 0));

      expect(mockApi.post).toHaveBeenCalledWith('/comparison/suggest_filters', { path: '/a.jpg', target_category: 'sports' });
    });
  });
});
