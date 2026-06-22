import type { Mock } from 'vitest';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { CompareFiltersService } from './compare-filters.service';
import { ComparisonSuggestionsTabComponent } from './comparison-suggestions-tab.component';

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('ComparisonSuggestionsTabComponent', () => {
  let component: ComparisonSuggestionsTabComponent;
  let mockApi: { get: Mock; post: Mock };
  const selectedCategory = signal<string | null>(null);

  beforeEach(async () => {
    selectedCategory.set('portrait');
    mockApi = {
      get: vi.fn((path: string) => {
        if (path === '/photos') {
          return of({ photos: [{ path: '/a.jpg', filename: 'a.jpg', aggregate: 9.2 }] });
        }
        if (path === '/comparison/category_weights') {
          return of({ weights: {}, modifiers: { bonus: 1 }, filters: { f: 2 } });
        }
        return of({ available: true });
      }),
      post: vi.fn(() => of({ success: true })),
    };

    TestBed.configureTestingModule({
      providers: [
        ComparisonSuggestionsTabComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (key: string) => key } },
        { provide: AuthService, useValue: { isEdition: () => true } },
        { provide: CompareFiltersService, useValue: { selectedCategory } },
      ],
    });
    component = TestBed.inject(ComparisonSuggestionsTabComponent);
    await flush();
  });

  it('applySuggested persists the merged weights, emits, and marks applied', async () => {
    component['learnedWeights'].set({
      available: true,
      suggest_changes: true,
      current_weights: { a_percent: 30, b_percent: 10 },
      suggested_weights: { a_percent: 40 },
    });
    component['categoryConfig'].set({ weights: {}, modifiers: { bonus: 1 }, filters: { f: 2 } });

    let emitted: Record<string, number> | undefined;
    component.weightsApplied.subscribe((w) => (emitted = w));
    await component['applySuggested']();

    expect(mockApi.post).toHaveBeenCalledWith('/config/update_weights', {
      category: 'portrait',
      weights: { a_percent: 40, b_percent: 10 },
      modifiers: { bonus: 1 },
      filters: { f: 2 },
    });
    expect(emitted).toEqual({ a_percent: 40, b_percent: 10 });
    expect(component['applied']()).toBe(true);
    expect(component['recomputed']()).toBe(false);
  });

  it('recompute calls the recompute endpoint and loads the after top photos', async () => {
    await component['recompute']();

    expect(mockApi.post).toHaveBeenCalledWith('/stats/categories/recompute', { category: 'portrait' });
    expect(component['recomputed']()).toBe(true);
    expect(component['topAfter']().length).toBeGreaterThan(0);
  });

  it('loads the current top photos as the before column', () => {
    expect(component['topBefore']().length).toBeGreaterThan(0);
  });

  it('only surfaces the percent weight keys', () => {
    component['learnedWeights'].set({ available: true, current_weights: { a_percent: 30, bonus: 1, b_percent: 10 } });
    expect(component['currentWeightKeys']()).toEqual(['a_percent', 'b_percent']);
  });
});
