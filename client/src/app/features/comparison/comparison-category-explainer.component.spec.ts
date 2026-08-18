import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { ComparisonCategoryExplainerComponent } from './comparison-category-explainer.component';
import type { components } from '../../core/api/schema';

type SuggestFiltersResponse = components['schemas']['SuggestFiltersResponse'];

const RESPONSE = (overrides: Partial<SuggestFiltersResponse> = {}): SuggestFiltersResponse => ({
  current_category: 'silhouette',
  target_category: 'sports',
  conflicts: [],
  suggestions: [],
  no_conflicts: true,
  ...overrides,
});

describe('ComparisonCategoryExplainerComponent', () => {
  let fixture: ComponentFixture<ComparisonCategoryExplainerComponent>;
  let component: ComparisonCategoryExplainerComponent;
  let mockApi: { post: Mock };
  const mockI18n = {
    t: vi.fn((key: string) => key),
    currentLang: vi.fn(() => 'en'),
    locale: vi.fn(() => 'en'),
    translations: vi.fn(() => ({})),
  };

  beforeEach(() => {
    mockApi = { post: vi.fn(() => of(RESPONSE())) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
      ],
    });
    fixture = TestBed.createComponent(ComparisonCategoryExplainerComponent);
    component = fixture.componentInstance;
  });

  /** Sets both required inputs and runs the constructor effect that loads on their change. */
  function setInputs(path: string, targetCategory: string): void {
    fixture.componentRef.setInput('path', path);
    fixture.componentRef.setInput('targetCategory', targetCategory);
    fixture.detectChanges();
  }

  describe('loading via the path/targetCategory effect', () => {
    it('does nothing without a path', async () => {
      setInputs('', 'sports');
      await fixture.whenStable();

      expect(mockApi.post).not.toHaveBeenCalled();
      expect(component.result()).toBeNull();
    });

    it('does nothing without a target category', async () => {
      setInputs('/a.jpg', '');
      await fixture.whenStable();

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('calls suggest_filters with path and target_category', async () => {
      mockApi.post.mockReturnValue(of(RESPONSE({ current_category: 'silhouette', target_category: 'sports', no_conflicts: false })));

      setInputs('/a.jpg', 'sports');
      await fixture.whenStable();

      expect(mockApi.post).toHaveBeenCalledWith('/comparison/suggest_filters', { path: '/a.jpg', target_category: 'sports' });
    });

    it('stores the response in result', async () => {
      const response = RESPONSE({
        current_category: 'silhouette',
        target_category: 'sports',
        conflicts: [{ type: 'above_maximum', filter: 'shutter_speed_max', message: 'Shutter speed is above maximum' }],
        suggestions: [{ type: 'raise_maximum', filter: 'shutter_speed_max', message: 'Raise shutter_speed_max from 0.02 to 0.033' }],
        no_conflicts: false,
      });
      mockApi.post.mockReturnValue(of(response));

      setInputs('/a.jpg', 'sports');
      await fixture.whenStable();

      expect(component.result()).toEqual(response);
    });

    it('sets loading false after completion', async () => {
      setInputs('/a.jpg', 'sports');
      await fixture.whenStable();

      expect(component.loading()).toBe(false);
    });

    it('sets error and clears result on failure', async () => {
      mockApi.post.mockReturnValueOnce(of(RESPONSE()));
      setInputs('/a.jpg', 'sports');
      await fixture.whenStable();
      expect(component.result()).not.toBeNull();

      mockApi.post.mockReturnValueOnce(throwError(() => new Error('fail')));
      fixture.componentRef.setInput('path', '/b.jpg');
      fixture.detectChanges();
      await fixture.whenStable();

      expect(component.error()).toBe(true);
      expect(component.result()).toBeNull();
      expect(component.loading()).toBe(false);
    });
  });

  // Defect 2: holding ArrowRight in photo detail re-sets the `path` input on the
  // same mounted instance, so a slow response for the PREVIOUS photo/category can
  // land after a newer request already resolved. The stale response must never
  // overwrite the fresh result.
  describe('stale-response race across a real input change', () => {
    it('discards a stale response that resolves after a newer request has already applied', async () => {
      const staleResponse = new Subject<SuggestFiltersResponse>();
      mockApi.post.mockReturnValueOnce(staleResponse.asObservable());
      mockApi.post.mockReturnValueOnce(of(RESPONSE({ current_category: 'b_current' })));

      fixture.componentRef.setInput('path', '/a.jpg');
      fixture.componentRef.setInput('targetCategory', 'sports');
      fixture.detectChanges();

      // The user moved on to photo B (e.g. holding ArrowRight) while A is still in flight.
      fixture.componentRef.setInput('path', '/b.jpg');
      fixture.detectChanges();
      await fixture.whenStable();

      expect(component.result()?.current_category).toBe('b_current');
      expect(component.loading()).toBe(false);

      staleResponse.next(RESPONSE({ current_category: 'a_current' }));
      staleResponse.complete();
      await fixture.whenStable();

      expect(component.result()?.current_category).toBe('b_current');
      expect(component.loading()).toBe(false);
    });

    it('keeps loading true while a newer request is still in flight after the previous one settled', async () => {
      const slowB = new Subject<SuggestFiltersResponse>();
      mockApi.post.mockReturnValueOnce(of(RESPONSE({ current_category: 'a_current' })));
      mockApi.post.mockReturnValueOnce(slowB.asObservable());

      // Both inputs move before either request settles: A resolves only after
      // B is already the current input, so A is discarded as stale on arrival.
      fixture.componentRef.setInput('path', '/a.jpg');
      fixture.componentRef.setInput('targetCategory', 'sports');
      fixture.detectChanges();

      fixture.componentRef.setInput('path', '/b.jpg');
      fixture.detectChanges();
      await fixture.whenStable();

      expect(component.loading()).toBe(true);
      expect(component.result()).toBeNull();

      slowB.next(RESPONSE({ current_category: 'b_current' }));
      slowB.complete();
      await fixture.whenStable();

      expect(component.loading()).toBe(false);
      expect(component.result()?.current_category).toBe('b_current');
    });

    it('never lets a stale FAILURE clobber the fresh result already shown', async () => {
      const failA = new Subject<unknown>();
      mockApi.post.mockReturnValueOnce(failA.asObservable());
      mockApi.post.mockReturnValueOnce(of(RESPONSE({ current_category: 'b_current' })));

      fixture.componentRef.setInput('path', '/a.jpg');
      fixture.componentRef.setInput('targetCategory', 'sports');
      fixture.detectChanges();

      fixture.componentRef.setInput('path', '/b.jpg');
      fixture.detectChanges();
      await fixture.whenStable();

      failA.error(new Error('boom'));
      await fixture.whenStable();

      expect(component.error()).toBe(false);
      expect(component.result()?.current_category).toBe('b_current');
      expect(component.loading()).toBe(false);
    });

    // Latent robustness hole (not reachable today: photo-detail.component.ts only
    // instantiates this component inside an `@if` guard with non-empty path/target),
    // pinned so a future caller can't reintroduce it silently: the early return for
    // a falsy input skips the `finally` that resets `loading`, because that `finally`
    // belongs to the now-superseded in-flight request.
    it('leaves loading stuck true if an input goes falsy while a request is still in flight', async () => {
      const slowA = new Subject<unknown>();
      mockApi.post.mockReturnValueOnce(slowA.asObservable());

      fixture.componentRef.setInput('path', '/a.jpg');
      fixture.componentRef.setInput('targetCategory', 'sports');
      fixture.detectChanges();

      expect(component.loading()).toBe(true);

      fixture.componentRef.setInput('targetCategory', '');
      fixture.detectChanges();

      slowA.next(RESPONSE({ current_category: 'a_current' }));
      slowA.complete();
      await fixture.whenStable();

      expect(component.loading()).toBe(true);
    });
  });

  describe('retry', () => {
    it('re-runs load with the current input values', async () => {
      setInputs('/a.jpg', 'sports');
      await fixture.whenStable();
      mockApi.post.mockClear();
      mockApi.post.mockReturnValue(of(RESPONSE()));

      component.retry();
      await fixture.whenStable();

      expect(mockApi.post).toHaveBeenCalledWith('/comparison/suggest_filters', { path: '/a.jpg', target_category: 'sports' });
    });
  });

  // SuggestFiltersResponse (api/models/comparison.py:109) documents "Either the
  // early-exit shape (message only) or the full analysis" -- every field but
  // `message` is Optional. The suite above only ever drives the full shape.
  describe('the documented early-exit response shape', () => {
    it('renders the already-in-category message without throwing for the real early-exit response', async () => {
      // What api_comparison_suggest_filters actually returns when current_category
      // === target_category (api/routers/comparison.py:956-963): categories and
      // empty arrays are present, but no_conflicts/target_filters/photo_values are
      // never set, so response_model_exclude_unset drops them off the wire.
      const earlyExit: SuggestFiltersResponse = {
        current_category: 'sports',
        target_category: 'sports',
        conflicts: [],
        suggestions: [],
        message: 'Photo is already in the target category',
      };
      mockApi.post.mockReturnValue(of(earlyExit));

      setInputs('/a.jpg', 'sports');
      await fixture.whenStable();
      fixture.detectChanges();

      expect(component.result()).toEqual(earlyExit);
      expect(component.error()).toBe(false);
      expect(fixture.nativeElement.textContent).toContain('comparison.context.explainer_already_in_category');
    });

    it('renders neither a category nor the already-in-category branch when only message is sent', async () => {
      // Every field but `message` is Optional server-side, so this shape is
      // legal. Asserting only "did not throw" is not enough: with the pair
      // declared required the template rendered the literal
      // `category_names.undefined` as visible text, and `undefined ===
      // undefined` took the green "already in the target category" branch for a
      // response that says nothing of the sort.
      const earlyExit: SuggestFiltersResponse = { message: 'nothing to suggest' };
      mockApi.post.mockReturnValue(of(earlyExit));

      setInputs('/a.jpg', 'sports');
      await fixture.whenStable();
      fixture.detectChanges();

      expect(component.result()).toEqual(earlyExit);
      expect(component.error()).toBe(false);
      const rendered = fixture.nativeElement.textContent;
      expect(rendered).not.toContain('category_names.undefined');
      expect(rendered).not.toContain('comparison.context.explainer_already_in_category');
    });

    it('does not throw when conflicts and suggestions are absent and the categories differ', async () => {
      // Distinct from the previous case: current_category !== target_category
      // and no_conflicts is falsy drives the @else branch, the only template
      // path that reads r.conflicts / r.suggestions. The Optional server model
      // (api/models/comparison.py:109, SuggestFiltersResponse) permits exactly
      // this shape, and the template must render it rather than dereferencing
      // an absent array.
      const earlyExit: SuggestFiltersResponse = {
        current_category: 'silhouette',
        target_category: 'sports',
        message: 'nothing to suggest',
      };
      mockApi.post.mockReturnValue(of(earlyExit));

      setInputs('/a.jpg', 'sports');

      await fixture.whenStable();
      fixture.detectChanges();

      expect(component.result()).toEqual(earlyExit);
      expect(component.error()).toBe(false);
    });
  });
});
