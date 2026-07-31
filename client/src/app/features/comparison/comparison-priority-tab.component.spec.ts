import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { ComparisonPriorityTabComponent, CategoryFilterSummaryPipe } from './comparison-priority-tab.component';

async function flush(): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, 0));
}

type DropEvent = Parameters<ComparisonPriorityTabComponent['drop']>[0];

/**
 * Builds a realistic CdkDragDrop-shaped event (all fields the real directive emits),
 * without needing an actual mouse/pointer sequence — `drop()` only reads
 * `previousIndex`/`currentIndex`, but the surrounding fields are included so the event
 * shape matches what `(cdkDropListDropped)` really binds.
 */
function makeDropEvent(previousIndex: number, currentIndex: number): DropEvent {
  return {
    previousIndex,
    currentIndex,
    item: {},
    container: {},
    previousContainer: {},
    isPointerOverContainer: true,
    distance: { x: 0, y: 0 },
    dropPoint: { x: 0, y: 0 },
    event: new MouseEvent('mouseup'),
  } as unknown as DropEvent;
}

// Mirrors the real category priority order in scoring_config.json (sorted ascending by
// `priority`, `default` pinned last at 999) so the reorder is exercised against the
// actual 33-category shape, not a toy 2-item list.
const CATEGORIES_LARGE = [
  { name: 'art', priority: 8, filters: {} },
  { name: 'astro', priority: 10, filters: {} },
  { name: 'concert', priority: 15, filters: {} },
  { name: 'group_portrait', priority: 35, filters: {} },
  { name: 'silhouette', priority: 42, filters: {} },
  { name: 'fashion', priority: 43, filters: {} },
  { name: 'portrait', priority: 45, filters: {} },
  { name: 'portrait_bw', priority: 46, filters: {} },
  { name: 'candid', priority: 47, filters: {} },
  { name: 'macro', priority: 55, filters: {} },
  { name: 'aerial', priority: 60, filters: {} },
  { name: 'wildlife', priority: 65, filters: {} },
  { name: 'food', priority: 70, filters: {} },
  { name: 'sports', priority: 71, filters: {} },
  { name: 'vehicle', priority: 72, filters: {} },
  { name: 'travel', priority: 73, filters: {} },
  { name: 'product', priority: 74, filters: {} },
  { name: 'architecture', priority: 76, filters: {} },
  { name: 'urban', priority: 78, filters: {} },
  { name: 'blue_hour', priority: 79, filters: {} },
  { name: 'long_exposure', priority: 80, filters: {} },
  { name: 'golden_hour', priority: 81, filters: {} },
  { name: 'cinematic', priority: 82, filters: {} },
  { name: 'vintage', priority: 83, filters: {} },
  { name: 'abstract', priority: 84, filters: {} },
  { name: 'night', priority: 85, filters: {} },
  { name: 'minimalist', priority: 86, filters: {} },
  { name: 'dramatic', priority: 87, filters: {} },
  { name: 'monochrome', priority: 88, filters: {} },
  { name: 'weather', priority: 89, filters: {} },
  { name: 'street', priority: 95, filters: {} },
  { name: 'human_others', priority: 96, filters: {} },
  { name: 'landscape', priority: 100, filters: {} },
  { name: 'default', priority: 999, filters: {} },
];

// sports sits at index 13, silhouette at index 4, in the 33-entry non-default list.
const SPORTS_INDEX = 13;
const SILHOUETTE_INDEX = 4;
const LAST_NON_DEFAULT_INDEX = CATEGORIES_LARGE.length - 2; // 32: excludes 'default'

const EXPECTED_ORDER_AFTER_SPORTS_MOVE = [
  'art', 'astro', 'concert', 'group_portrait', 'sports', 'silhouette', 'fashion',
  'portrait', 'portrait_bw', 'candid', 'macro', 'aerial', 'wildlife', 'food',
  'vehicle', 'travel', 'product', 'architecture', 'urban', 'blue_hour',
  'long_exposure', 'golden_hour', 'cinematic', 'vintage', 'abstract', 'night',
  'minimalist', 'dramatic', 'monochrome', 'weather', 'street', 'human_others', 'landscape',
];

describe('CategoryFilterSummaryPipe', () => {
  const pipe = new CategoryFilterSummaryPipe();

  it('returns empty array for null/undefined filters', () => {
    expect(pipe.transform(null)).toEqual([]);
    expect(pipe.transform(undefined)).toEqual([]);
  });

  it('returns empty array for empty filters', () => {
    expect(pipe.transform({})).toEqual([]);
  });

  it('summarizes a true boolean filter', () => {
    expect(pipe.transform({ has_face: true })).toEqual([{ labelKey: 'comparison.filter.has_face', text: '✓' }]);
  });

  it('summarizes a false boolean filter', () => {
    expect(pipe.transform({ is_silhouette: false })).toEqual([{ labelKey: 'comparison.filter.is_silhouette', text: '✗' }]);
  });

  it('summarizes a numeric range with both min and max', () => {
    expect(pipe.transform({ face_ratio_min: 0.05, face_ratio_max: 0.8 })).toEqual([
      { labelKey: 'comparison.filter.face_ratio', text: '5%–80%' },
    ]);
  });

  it('summarizes a numeric range with only max', () => {
    expect(pipe.transform({ shutter_speed_max: 0.02 })).toEqual([
      { labelKey: 'comparison.filter.shutter_speed', text: '1/50' },
    ]);
  });

  it('summarizes required_tags, capped at 4 with ellipsis', () => {
    expect(pipe.transform({ required_tags: ['a', 'b', 'c', 'd', 'e'] })).toEqual([
      { labelKey: 'comparison.filter.required_tags', text: 'a, b, c, d…' },
    ]);
  });

  it('summarizes excluded_tags', () => {
    expect(pipe.transform({ excluded_tags: ['x'] })).toEqual([
      { labelKey: 'comparison.filter.excluded_tags', text: 'x' },
    ]);
  });

  it('combines multiple filter kinds', () => {
    const entries = pipe.transform({ has_face: true, face_ratio_min: 0.05, required_tags: ['sports'] });
    expect(entries).toHaveLength(3);
  });

  it('ignores unknown filter keys', () => {
    expect(pipe.transform({ tag_match_mode: 'any' })).toEqual([]);
  });
});

describe('ComparisonPriorityTabComponent', () => {
  let component: ComparisonPriorityTabComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockSnackBar: { open: Mock };
  let mockI18n: { t: Mock };
  let mockAuth: { isEdition: ReturnType<typeof signal<boolean>> };

  const CATEGORIES = [
    { name: 'sports', priority: 71, filters: { shutter_speed_max: 0.02 } },
    { name: 'silhouette', priority: 42, filters: { is_silhouette: true } },
    { name: 'default', priority: 999, filters: {} },
  ];

  const CONTEXTS = [
    { name: 'default', label_key: 'comparison.context.default', promote: [], excluded: [], suggest_from_moments: [], effective_order: ['sports', 'silhouette', 'default'] },
    { name: 'action_stage', label_key: 'comparison.context.action_stage', promote: ['sports'], excluded: ['silhouette'], suggest_from_moments: ['sports'], effective_order: ['sports', 'default'] },
  ];

  beforeEach(() => {
    mockApi = {
      get: vi.fn(() => of({})),
      post: vi.fn(() => of({})),
    };
    mockSnackBar = { open: vi.fn() };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockAuth = { isEdition: signal(true) };

    TestBed.configureTestingModule({
      providers: [
        ComparisonPriorityTabComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: AuthService, useValue: mockAuth },
      ],
    });
    component = TestBed.inject(ComparisonPriorityTabComponent);
  });

  describe('loadCategories', () => {
    it('excludes the default category from the draggable list', async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));
      await component.loadCategories();

      expect(component.orderedCategories().map(c => c.name)).toEqual(['sports', 'silhouette']);
    });

    it('records the loaded order as the saved order', async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));
      await component.loadCategories();

      expect(component.savedOrder()).toEqual(['sports', 'silhouette']);
    });

    it('keeps the default category available for the pinned row', async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));
      await component.loadCategories();

      expect(component.defaultCategory()?.name).toBe('default');
    });

    it('shows a snackbar on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      await component.loadCategories();

      expect(mockSnackBar.open).toHaveBeenCalled();
      expect(component.categoriesLoading()).toBe(false);
    });
  });

  describe('loadContexts', () => {
    it('sets the contexts list', async () => {
      mockApi.get.mockReturnValue(of({ contexts: CONTEXTS }));
      await component.loadContexts();

      expect(component.contexts()).toEqual(CONTEXTS);
    });

    it('shows a snackbar on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      await component.loadContexts();

      expect(mockSnackBar.open).toHaveBeenCalled();
    });
  });

  describe('selectContext / isDefaultContext / selectedContextEntry', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ contexts: CONTEXTS }));
      await component.loadContexts();
    });

    it('defaults to the default context', () => {
      expect(component.isDefaultContext()).toBe(true);
    });

    it('switches to a named context', () => {
      component.selectContext('action_stage');
      expect(component.isDefaultContext()).toBe(false);
      expect(component.selectedContextEntry()?.name).toBe('action_stage');
    });

    it('returns null for an unknown context', () => {
      component.selectContext('nope');
      expect(component.selectedContextEntry()).toBeNull();
    });
  });

  describe('drop', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));
      await component.loadCategories();
    });

    it('reorders the draggable list', () => {
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      expect(component.orderedCategories().map(c => c.name)).toEqual(['silhouette', 'sports']);
    });
  });

  describe('hasOrderChanges / resetOrder', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));
      await component.loadCategories();
    });

    it('is false right after load', () => {
      expect(component.hasOrderChanges()).toBe(false);
    });

    it('is true after reordering', () => {
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      expect(component.hasOrderChanges()).toBe(true);
    });

    it('resetOrder restores the saved order', () => {
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      component.resetOrder();
      expect(component.orderedCategories().map(c => c.name)).toEqual(['sports', 'silhouette']);
      expect(component.hasOrderChanges()).toBe(false);
    });
  });

  describe('saveOrder', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));
      await component.loadCategories();
    });

    it('does nothing without changes', async () => {
      mockApi.post.mockClear();
      await component.saveOrder();
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('posts the reordered name list', async () => {
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));

      await component.saveOrder();

      expect(mockApi.post).toHaveBeenCalledWith('/config/category_priorities', { order: ['silhouette', 'sports'] });
    });

    it('marks scores stale and clears the recompute message on success', async () => {
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));
      component.recomputeMessageKey.set('some.key');

      await component.saveOrder();

      expect(component.stale()).toBe(true);
      expect(component.recomputeMessageKey()).toBeNull();
    });

    it('invalidates the cached overlap panel on success', async () => {
      component.overlapLoaded.set(true);
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));

      await component.saveOrder();

      expect(component.overlapLoaded()).toBe(false);
    });

    it('shows a snackbar and does not mark stale on error', async () => {
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));

      await component.saveOrder();

      expect(mockSnackBar.open).toHaveBeenCalled();
      expect(component.stale()).toBe(false);
      expect(component.saving()).toBe(false);
    });
  });

  describe('loadOverlapLazily / refreshOverlap / activateOverlap', () => {
    const OVERLAP = {
      overlaps: [],
      per_category: [
        { name: 'silhouette', priority: 42, assigned: 5, matched: 20, captured_by_higher: 0 },
        { name: 'sports', priority: 71, assigned: 15, matched: 15, captured_by_higher: 15 },
      ],
      uncategorized: 0,
      total: 20,
    };

    it('loads once and sorts by captured_by_higher descending', async () => {
      mockApi.get.mockReturnValue(of(OVERLAP));
      await component.loadOverlapLazily();

      expect(component.overlapLoaded()).toBe(true);
      expect(component.sortedOverlapCategories().map(c => c.name)).toEqual(['sports', 'silhouette']);
    });

    it('does not re-fetch once loaded', async () => {
      mockApi.get.mockReturnValue(of(OVERLAP));
      await component.loadOverlapLazily();
      mockApi.get.mockClear();

      await component.loadOverlapLazily();

      expect(mockApi.get).not.toHaveBeenCalled();
    });

    it('activateOverlap triggers a load', async () => {
      mockApi.get.mockReturnValue(of(OVERLAP));
      component.activateOverlap();
      await flush();

      expect(component.overlapLoaded()).toBe(true);
    });

    it('refreshOverlap forces a re-fetch', async () => {
      mockApi.get.mockReturnValue(of(OVERLAP));
      await component.loadOverlapLazily();
      mockApi.get.mockClear();
      mockApi.get.mockReturnValue(of(OVERLAP));

      component.refreshOverlap();
      await flush();

      expect(mockApi.get).toHaveBeenCalledWith('/stats/categories/overlap');
      expect(component.overlapLoaded()).toBe(true);
    });

    it('shows a snackbar on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      await component.loadOverlapLazily();

      expect(mockSnackBar.open).toHaveBeenCalled();
      expect(component.overlapLoaded()).toBe(false);
    });
  });

  describe('startRecompute', () => {
    it('starts recomputing and completes immediately when the job finishes fast', async () => {
      mockApi.post.mockReturnValue(of({ success: true }));
      mockApi.get.mockReturnValue(of({ running: false, kind: 'recompute', progress: null, exit_code: 0 }));

      await component.startRecompute();
      await flush();

      expect(mockApi.post).toHaveBeenCalledWith('/scan/recompute', { confirm: true });
      expect(component.recomputing()).toBe(false);
      expect(component.stale()).toBe(false);
    });

    it('sets a conflict message on 409', async () => {
      mockApi.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 409 })));

      await component.startRecompute();

      expect(component.recomputeMessageKey()).toBe(I18N.comparison.context.recompute_conflict);
      expect(component.recomputing()).toBe(false);
    });

    it('sets a generic error message on other failures', async () => {
      mockApi.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));

      await component.startRecompute();

      expect(component.recomputeMessageKey()).toBe(I18N.comparison.context.error_recompute);
    });
  });

  describe('recomputeProgressPercent', () => {
    it('is null without a status', () => {
      expect(component.recomputeProgressPercent()).toBeNull();
    });

    it('is null when total is missing or zero', () => {
      component.recomputeStatus.set({ running: true, kind: 'recompute', progress: { phase: 'recompute', current: 5 }, exit_code: null });
      expect(component.recomputeProgressPercent()).toBeNull();
    });

    it('computes a rounded percentage', () => {
      component.recomputeStatus.set({ running: true, kind: 'recompute', progress: { phase: 'recompute', current: 25, total: 100 }, exit_code: null });
      expect(component.recomputeProgressPercent()).toBe(25);
    });

    it('caps at 100', () => {
      component.recomputeStatus.set({ running: true, kind: 'recompute', progress: { phase: 'recompute', current: 150, total: 100 }, exit_code: null });
      expect(component.recomputeProgressPercent()).toBe(100);
    });
  });

  describe('saveDisabled / recomputeDisabled', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES }));
      await component.loadCategories();
    });

    it('save is disabled without changes', () => {
      expect(component.saveDisabled()).toBe(true);
    });

    it('save is enabled with changes and edition', () => {
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      expect(component.saveDisabled()).toBe(false);
    });

    it('save stays disabled without edition even with changes', () => {
      component.drop({ previousIndex: 0, currentIndex: 1 } as never);
      mockAuth.isEdition.set(false);
      expect(component.saveDisabled()).toBe(true);
    });

    it('recompute is disabled without edition', () => {
      mockAuth.isEdition.set(false);
      expect(component.recomputeDisabled()).toBe(true);
    });

    it('recompute is enabled with edition when idle', () => {
      expect(component.recomputeDisabled()).toBe(false);
    });

    it('recompute is disabled while a job is running', () => {
      component.recomputing.set(true);
      expect(component.recomputeDisabled()).toBe(true);
    });
  });

  // Drives the CDK drop handler directly with a synthesized CdkDragDrop event, bypassing
  // the real pointer/mouse drag sequence entirely (jsdom + CDP synthetic mouse events
  // cannot reliably trigger Angular CDK's drag-drop pointer machinery). This exercises
  // exactly the same code path `(cdkDropListDropped)="drop($event)"` invokes in the
  // template — the only thing NOT covered is the physical mouse gesture itself.
  describe('drop — realistic reorder against the full scoring_config.json priority order', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES_LARGE }));
      await component.loadCategories();
    });

    it('loads the full 33-entry non-default order', () => {
      expect(component.orderedCategories()).toHaveLength(LAST_NON_DEFAULT_INDEX + 1);
      expect(component.orderedCategories()[SPORTS_INDEX].name).toBe('sports');
      expect(component.orderedCategories()[SILHOUETTE_INDEX].name).toBe('silhouette');
    });

    it('moving sports from index 13 to index 4 places it immediately before silhouette and shifts the rest', () => {
      component.drop(makeDropEvent(SPORTS_INDEX, SILHOUETTE_INDEX));

      const names = component.orderedCategories().map(c => c.name);
      expect(names).toEqual(EXPECTED_ORDER_AFTER_SPORTS_MOVE);
      expect(names[SILHOUETTE_INDEX]).toBe('sports');
      expect(names[SILHOUETTE_INDEX + 1]).toBe('silhouette');
      expect(names).toHaveLength(LAST_NON_DEFAULT_INDEX + 1);
    });

    it('moving an item downward (silhouette to just after sports) shifts the intervening items the other way', () => {
      component.drop(makeDropEvent(SILHOUETTE_INDEX, SPORTS_INDEX));

      const names = component.orderedCategories().map(c => c.name);
      expect(names[SPORTS_INDEX - 1]).toBe('sports');
      expect(names[SPORTS_INDEX]).toBe('silhouette');
      expect(names).toHaveLength(LAST_NON_DEFAULT_INDEX + 1);
    });
  });

  describe('drop — pinned "default" category can never be displaced', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES_LARGE }));
      await component.loadCategories();
    });

    it('dropping exactly onto the default row (currentIndex === length) clamps to the last real slot', () => {
      component.drop(makeDropEvent(0, component.orderedCategories().length));

      const names = component.orderedCategories().map(c => c.name);
      expect(names).toHaveLength(LAST_NON_DEFAULT_INDEX + 1);
      expect(names[LAST_NON_DEFAULT_INDEX]).toBe('art');
      expect(names).not.toContain('default');
    });

    it('dropping far past the default row clamps the same way, never appending or losing entries', () => {
      component.drop(makeDropEvent(0, 1000));

      const names = component.orderedCategories().map(c => c.name);
      expect(names).toHaveLength(LAST_NON_DEFAULT_INDEX + 1);
      expect(names[LAST_NON_DEFAULT_INDEX]).toBe('art');
      expect(names).not.toContain('default');
    });

    it('never mutates the default category entry itself', () => {
      const before = component.defaultCategory();

      component.drop(makeDropEvent(0, component.orderedCategories().length));
      component.drop(makeDropEvent(SPORTS_INDEX, 5000));

      expect(component.defaultCategory()).toEqual(before);
    });

    it('a drop attempted with currentIndex beyond the list still reports a real order change (Save should enable)', () => {
      component.drop(makeDropEvent(0, component.orderedCategories().length));
      expect(component.hasOrderChanges()).toBe(true);
    });
  });

  describe('Save button enablement lifecycle (disabled -> enabled -> disabled after reset)', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES_LARGE }));
      await component.loadCategories();
    });

    it('flips disabled -> enabled on reorder, then back to disabled after resetOrder()', () => {
      expect(component.saveDisabled()).toBe(true);

      component.drop(makeDropEvent(SPORTS_INDEX, SILHOUETTE_INDEX));
      expect(component.saveDisabled()).toBe(false);

      component.resetOrder();
      expect(component.saveDisabled()).toBe(true);
      expect(component.orderedCategories().map(c => c.name)).toEqual(
        CATEGORIES_LARGE.filter(c => c.name !== 'default').map(c => c.name),
      );
    });
  });

  describe('saveOrder — payload for a realistic reorder', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES_LARGE }));
      await component.loadCategories();
    });

    it('POSTs the full ordered name list, excluding the pinned default, in the new order', async () => {
      component.drop(makeDropEvent(SPORTS_INDEX, SILHOUETTE_INDEX));
      mockApi.get.mockReturnValue(of({ categories: CATEGORIES_LARGE }));

      await component.saveOrder();

      expect(mockApi.post).toHaveBeenCalledWith('/config/category_priorities', {
        order: EXPECTED_ORDER_AFTER_SPORTS_MOVE,
      });
      const [, body] = mockApi.post.mock.calls[0] as [string, { order: string[] }];
      expect(body.order).not.toContain('default');
      expect(body.order).toHaveLength(LAST_NON_DEFAULT_INDEX + 1);
    });
  });
});
