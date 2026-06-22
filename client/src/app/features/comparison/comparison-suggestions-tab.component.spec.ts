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

describe('ComparisonSuggestionsTabComponent', () => {
  let component: ComparisonSuggestionsTabComponent;
  let mockApi: { get: Mock };
  const selectedCategory = signal<string | null>(null);

  beforeEach(() => {
    selectedCategory.set(null);
    mockApi = { get: vi.fn(() => of({ available: true })) };

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
  });

  it('applyWeights emits current weights merged with the suggested ones', () => {
    component['learnedWeights'].set({
      available: true,
      suggest_changes: true,
      current_weights: { a_percent: 30, b_percent: 10 },
      suggested_weights: { a_percent: 40 },
    });

    let emitted: Record<string, number> | undefined;
    component.weightsApplied.subscribe((w) => (emitted = w));
    component['applyWeights']();

    expect(emitted).toEqual({ a_percent: 40, b_percent: 10 });
  });

  it('does not emit when there are no suggested weights', () => {
    component['learnedWeights'].set({ available: true });

    let emitted: Record<string, number> | null = null;
    component.weightsApplied.subscribe((w) => (emitted = w));
    component['applyWeights']();

    expect(emitted).toBeNull();
  });

  it('only surfaces the percent weight keys', () => {
    component['learnedWeights'].set({
      available: true,
      current_weights: { a_percent: 30, bonus: 1, b_percent: 10 },
    });

    expect(component['currentWeightKeys']()).toEqual(['a_percent', 'b_percent']);
  });
});
