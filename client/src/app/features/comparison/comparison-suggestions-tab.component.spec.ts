import type { Mock } from 'vitest';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { CompareFiltersService } from './compare-filters.service';
import { GalleryStore } from '../gallery/gallery.store';
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
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: AuthService, useValue: { isEdition: () => true } },
        { provide: CompareFiltersService, useValue: { selectedCategory } },
        { provide: GalleryStore, useValue: { types: signal([]) } },
      ],
    });
    component = TestBed.inject(ComparisonSuggestionsTabComponent);
    await flush();
  });

  it('persists canonical weights overlaid with suggestions, ignoring non-canonical keys', async () => {
    component['learnedWeights'].set({
      available: true,
      suggest_changes: true,
      // a stray non-canonical key that must NOT be saved
      current_weights: { a_percent: 30, b_percent: 10, stray_percent: 99 },
      suggested_weights: { a_percent: 40, stray_percent: 99 },
    });
    component['categoryConfig'].set({ weights: { a_percent: 30, b_percent: 10 }, modifiers: { bonus: 1 }, filters: { f: 2 } });

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

  it('offers Apply only when the server suggests changes', () => {
    component['learnedWeights'].set({ available: true, suggest_changes: false, suggested_weights: { a_percent: 40 } });
    expect(component.canApply()).toBe(false);

    component['learnedWeights'].set({ available: true, suggest_changes: true, suggested_weights: { a_percent: 40 } });
    expect(component.canApply()).toBe(true);
  });

  it('builds rows over the canonical percent weights, overlaying suggestions', () => {
    component['categoryConfig'].set({ weights: { a_percent: 30, bonus: 1, b_percent: 10 }, modifiers: {}, filters: {} });
    component['learnedWeights'].set({ available: true, suggested_weights: { a_percent: 40 } });

    const rows = component['weightRows']();
    expect(rows.map(r => r.key)).toEqual(['a_percent', 'b_percent']);
    expect(rows[0]).toEqual({ key: 'a_percent', current: 30, suggested: 40, changed: true });
    expect(rows[1]).toEqual({ key: 'b_percent', current: 10, suggested: 10, changed: false });
  });

  it('docks its Type select in a bar that uses the shared 56px row, not its own padding', () => {
    const fixture = TestBed.createComponent(ComparisonSuggestionsTabComponent);
    fixture.detectChanges();
    const bar = (fixture.nativeElement as HTMLElement).querySelector('.fixed.bottom-0') as HTMLElement;
    expect(bar.querySelector('mat-form-field')).not.toBeNull();
    for (const c of ['lg:hidden', 'min-h-14', 'items-center', 'gap-1', 'px-2', 'py-1']) expect(bar.classList, c).toContain(c);
    for (const c of ['gap-2', 'px-3', 'py-2']) expect(bar.classList, c).not.toContain(c);
  });
});
