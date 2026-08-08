import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
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
type PromotedDropEvent = Parameters<ComparisonPriorityTabComponent['dropPromoted']>[0];

/**
 * Builds a realistic CdkDragDrop-shaped event (all fields the real directive emits),
 * without needing an actual mouse/pointer sequence — the drop handlers only read
 * `previousIndex`/`currentIndex`, but the surrounding fields are included so the event
 * shape matches what `(cdkDropListDropped)` really binds. The intersection return type
 * lets the same helper feed both drop lists (categories and promoted names).
 */
function makeDropEvent(previousIndex: number, currentIndex: number): DropEvent & PromotedDropEvent {
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
  } as unknown as DropEvent & PromotedDropEvent;
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

// Mirrors the shipped `scoring_contexts` presets, expressed against CATEGORIES_LARGE
// so the delta editor is exercised against the real 33-category order.
const CONTEXTS_LARGE = [
  { name: 'default', label_key: 'comparison.context.default', promote: [], excluded: [], suggest_from_moments: [], effective_order: [] },
  {
    name: 'action_stage', label_key: 'comparison.context.action_stage',
    promote: ['sports', 'concert', 'candid'], excluded: ['silhouette'],
    suggest_from_moments: ['sports'], effective_order: ['sports', 'concert', 'candid', 'default'],
  },
  {
    name: 'wildlife', label_key: 'comparison.context.wildlife',
    promote: ['wildlife'], excluded: [],
    suggest_from_moments: ['nature_wildlife'], effective_order: ['wildlife', 'default'],
  },
];

describe('ComparisonPriorityTabComponent', () => {
  let component: ComparisonPriorityTabComponent;
  let mockApi: { get: Mock; post: Mock; put: Mock };
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
      put: vi.fn(() => of({})),
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

  // The named-context delta editor: promote order + exclusions, saved through
  // PUT /api/config/scoring_contexts/{name}. Only the delta is editable — the
  // non-promoted categories always keep the global priority order.
  describe('scoring context delta editing', () => {
    beforeEach(async () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/config/scoring_contexts') return of({ contexts: CONTEXTS_LARGE });
        return of({ categories: CATEGORIES_LARGE });
      });
      await component.loadCategories();
      await component.loadContexts();
      component.selectContext('action_stage');
    });

    it('seeds the draft from the selected context', () => {
      expect(component.draftPromote()).toEqual(['sports', 'concert', 'candid']);
      expect(component.draftExcluded()).toEqual(['silhouette']);
    });

    it('reports no pending changes right after selecting a context', () => {
      expect(component.hasContextChanges()).toBe(false);
      expect(component.contextSaveDisabled()).toBe(true);
    });

    it('re-seeds the draft when switching contexts', () => {
      component.selectContext('wildlife');
      expect(component.draftPromote()).toEqual(['wildlife']);
      expect(component.draftExcluded()).toEqual([]);
    });

    it('reorders the promoted head by drag', () => {
      component.dropPromoted(makeDropEvent(2, 0));

      expect(component.draftPromote()).toEqual(['candid', 'sports', 'concert']);
      expect(component.hasContextChanges()).toBe(true);
    });

    it('adds a category to the promoted head', () => {
      component.promoteCategory('wildlife');
      expect(component.draftPromote()).toEqual(['sports', 'concert', 'candid', 'wildlife']);
    });

    it('never promotes the same category twice', () => {
      component.promoteCategory('sports');
      expect(component.draftPromote()).toEqual(['sports', 'concert', 'candid']);
    });

    it('removes a category from the promoted head', () => {
      component.unpromoteCategory('concert');
      expect(component.draftPromote()).toEqual(['sports', 'candid']);
    });

    it('offers only the not-yet-promoted, non-default categories for promotion', () => {
      const promotable = component.promotableCategories();
      expect(promotable).not.toContain('sports');
      expect(promotable).not.toContain('default');
      expect(promotable).toContain('wildlife');
      expect(promotable).toHaveLength(LAST_NON_DEFAULT_INDEX + 1 - 3);
    });

    it('toggles a category into the exclusion set', () => {
      component.toggleExcluded('macro');
      expect(component.draftExcluded()).toEqual(['silhouette', 'macro']);
      expect(component.hasContextChanges()).toBe(true);
    });

    it('toggles a category back out of the exclusion set', () => {
      component.toggleExcluded('silhouette');
      expect(component.draftExcluded()).toEqual([]);
    });

    it('flags each exclusion chip with its current membership', () => {
      const chips = component.exclusionChips();
      expect(chips.find(c => c.name === 'silhouette')?.excluded).toBe(true);
      expect(chips.find(c => c.name === 'macro')?.excluded).toBe(false);
      expect(chips.map(c => c.name)).not.toContain('default');
    });

    it('resetContextDraft discards pending edits', () => {
      component.toggleExcluded('macro');
      component.dropPromoted(makeDropEvent(0, 2));

      component.resetContextDraft();

      expect(component.draftPromote()).toEqual(['sports', 'concert', 'candid']);
      expect(component.draftExcluded()).toEqual(['silhouette']);
      expect(component.hasContextChanges()).toBe(false);
    });

    it('previews the effective order as promoted head → global order minus excluded → default', () => {
      const order = component.contextEffectiveOrder();

      expect(order.slice(0, 3)).toEqual(['sports', 'concert', 'candid']);
      expect(order).not.toContain('silhouette');
      expect(order[order.length - 1]).toBe('default');
      // 33 non-default categories, 1 excluded, plus the pinned default.
      expect(order).toHaveLength(LAST_NON_DEFAULT_INDEX + 1 - 1 + 1);
    });

    it('the effective-order preview follows an unsaved edit', () => {
      component.dropPromoted(makeDropEvent(2, 0));
      component.toggleExcluded('macro');

      const order = component.contextEffectiveOrder();
      expect(order.slice(0, 3)).toEqual(['candid', 'sports', 'concert']);
      expect(order).not.toContain('macro');
    });

    it('a category both promoted and excluded is dropped from the preview (excluded wins)', () => {
      component.toggleExcluded('sports');

      expect(component.draftPromote()).toContain('sports');
      expect(component.contextEffectiveOrder()).not.toContain('sports');
    });

    it('does not PUT without changes', async () => {
      mockApi.put.mockClear();
      await component.saveContext();
      expect(mockApi.put).not.toHaveBeenCalled();
    });

    it('PUTs the edited delta to the selected context', async () => {
      component.dropPromoted(makeDropEvent(2, 0));
      component.toggleExcluded('macro');

      await component.saveContext();

      expect(mockApi.put).toHaveBeenCalledWith('/config/scoring_contexts/action_stage', {
        promote: ['candid', 'sports', 'concert'],
        excluded: ['silhouette', 'macro'],
      });
    });

    it('marks scores stale and clears the recompute message on success', async () => {
      component.toggleExcluded('macro');
      component.recomputeMessageKey.set('some.key');

      await component.saveContext();

      expect(component.stale()).toBe(true);
      expect(component.recomputeMessageKey()).toBeNull();
      expect(component.savingContext()).toBe(false);
    });

    it('shows a snackbar and does not mark stale on error', async () => {
      component.toggleExcluded('macro');
      mockApi.put.mockReturnValue(throwError(() => new Error('fail')));

      await component.saveContext();

      expect(mockSnackBar.open).toHaveBeenCalled();
      expect(component.stale()).toBe(false);
      expect(component.savingContext()).toBe(false);
    });

    it('save stays disabled without edition even with pending changes', () => {
      component.toggleExcluded('macro');
      mockAuth.isEdition.set(false);
      expect(component.contextSaveDisabled()).toBe(true);
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
    // 'default' is pinned last by design (D3), so on the real library it would
    // otherwise lead the table with a huge, non-diagnostic captured_by_higher
    // count -- it must never appear in sortedOverlapCategories.
    const OVERLAP = {
      overlaps: [
        { pair: ['sports', 'silhouette'] as [string, string], count: 2227 },
        { pair: ['landscape', 'travel'] as [string, string], count: 300 },
        { pair: ['sports', 'default'] as [string, string], count: 40 },
      ],
      per_category: [
        { name: 'default', priority: 999, assigned: 7614, matched: 126661, captured_by_higher: 119047 },
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

    it('D3: never includes the pinned default category, however high its captured_by_higher is', async () => {
      mockApi.get.mockReturnValue(of(OVERLAP));
      await component.loadOverlapLazily();

      expect(component.sortedOverlapCategories().map(c => c.name)).not.toContain('default');
    });

    it('D4: exposes the top colliding pairs sorted by count descending', async () => {
      mockApi.get.mockReturnValue(of(OVERLAP));
      await component.loadOverlapLazily();

      expect(component.topOverlapPairs().map(p => p.pair)).toEqual([
        ['sports', 'silhouette'], ['landscape', 'travel'], ['sports', 'default'],
      ]);
    });

    it('D4: caps the rendered pairs at MAX_OVERLAP_PAIRS', async () => {
      const manyPairs = Array.from({ length: 12 }, (_, i) => ({ pair: ['a', `b${i}`] as [string, string], count: i }));
      mockApi.get.mockReturnValue(of({ ...OVERLAP, overlaps: manyPairs }));
      await component.loadOverlapLazily();

      expect(component.topOverlapPairs()).toHaveLength(8);
      expect(component.topOverlapPairs()[0].count).toBe(11);
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

    // Defect 1: a subprocess that exits non-zero must NOT be reported as a successful
    // recompute — the stale banner has to stay up (the scores really are stale) and an
    // error must surface, mirroring AlbumScoringContextDialogComponent.pollRecomputeStatus.
    it('keeps the stale banner and surfaces an error when the job exits non-zero', async () => {
      component.stale.set(true);
      mockApi.post.mockReturnValue(of({ success: true }));
      mockApi.get.mockReturnValue(of({ running: false, kind: 'recompute', progress: null, exit_code: 1 }));

      await component.startRecompute();
      await flush();

      expect(component.stale()).toBe(true);
      expect(component.recomputing()).toBe(false);
      expect(component.recomputeMessageKey()).toBe(I18N.comparison.context.recompute_failed);
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    // D8: `_scan_state` (api/routers/scan.py) is a per-PROCESS module global on a
    // multi-worker deployment. A poll served by a worker that never saw the POST
    // answers {running:false, kind:null, exit_code:null} -- indistinguishable from
    // a real failure unless the client treats it as indeterminate instead.
    it('D8: reports an indeterminate outcome when exit_code is null (worker never saw the POST)', async () => {
      component.stale.set(true);
      mockApi.post.mockReturnValue(of({ success: true }));
      mockApi.get.mockReturnValue(of({ running: false, kind: null, progress: null, exit_code: null }));

      await component.startRecompute();
      await flush();

      expect(component.stale()).toBe(true);
      expect(component.recomputing()).toBe(false);
      expect(component.recomputeMessageKey()).toBe(I18N.comparison.context.recompute_unknown);
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    // D8: a finished job of a DIFFERENT kind (e.g. a concurrent superadmin scan)
    // must never be attributed to this recompute, even when its exit_code is 0.
    it('D8: reports an indeterminate outcome when the finished job is a different kind', async () => {
      component.stale.set(true);
      mockApi.post.mockReturnValue(of({ success: true }));
      mockApi.get.mockReturnValue(of({ running: false, kind: 'scan', progress: null, exit_code: 0 }));

      await component.startRecompute();
      await flush();

      expect(component.stale()).toBe(true);
      expect(component.recomputeMessageKey()).toBe(I18N.comparison.context.recompute_unknown);
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    // D7: the poll's own catch used to silently clear `recomputing` with no
    // message, dropping the banner back to "Recompute now" while the job is
    // very likely still running server-side -- the next click then 409s.
    it('D7: surfaces a message when the status poll itself fails', async () => {
      component.stale.set(true);
      mockApi.post.mockReturnValue(of({ success: true }));
      mockApi.get.mockReturnValue(throwError(() => new Error('network')));

      await component.startRecompute();
      await flush();

      expect(component.recomputing()).toBe(false);
      expect(component.recomputeMessageKey()).toBe(I18N.comparison.context.recompute_unknown);
    });

    // Defect 5: a second click before the first POST resolves must not overwrite the
    // stored interval handle (which would leak the first one forever).
    it('ignores a second call while a recompute is already starting/running (re-entrancy guard)', async () => {
      mockApi.post.mockReturnValue(of({ success: true }));
      mockApi.get.mockReturnValue(of({ running: false, kind: 'recompute', progress: null, exit_code: 0 }));

      const first = component.startRecompute();
      const second = component.startRecompute();
      await Promise.all([first, second]);
      await flush();

      expect(mockApi.post).toHaveBeenCalledTimes(1);
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

// D2/D6 are template-only defects (an unrendered field, a nesting bug) that a
// class-only instantiation cannot prove -- these render the real template.
describe('ComparisonPriorityTabComponent — rendering (D2/D6)', () => {
  let fixture: ComponentFixture<ComparisonPriorityTabComponent>;
  let component: ComparisonPriorityTabComponent;
  let renderApi: { get: Mock; post: Mock };

  const CONTEXTS = {
    contexts: [
      { name: 'default', label_key: 'comparison.context.default', promote: [], excluded: [], suggest_from_moments: [], effective_order: [] },
      { name: 'action_stage', label_key: 'comparison.context.action_stage', promote: ['sports'], excluded: [], suggest_from_moments: [], effective_order: ['sports', 'default'] },
    ],
  };

  async function render(): Promise<void> {
    TestBed.resetTestingModule();
    renderApi = {
      get: vi.fn((url: string) => {
        if (url === '/config/scoring_contexts') return of(CONTEXTS);
        if (url === '/config/category_priorities') return of({ categories: [] });
        if (url === '/stats/categories/overlap') return of({ overlaps: [], per_category: [], uncategorized: 0, total: 0 });
        return of({});
      }),
      post: vi.fn(() => of({ success: true })),
    };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: renderApi },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        {
          provide: I18nService,
          useValue: {
            t: (k: string, vars?: Record<string, string | number>) => (vars ? `${k}(${JSON.stringify(vars)})` : k),
            translations: () => ({}),
          },
        },
        { provide: AuthService, useValue: { isEdition: signal(true) } },
      ],
    });
    fixture = TestBed.createComponent(ComparisonPriorityTabComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  it('D6: the stale/recompute affordance renders for a named (non-default) context', async () => {
    await render();
    component.selectContext('action_stage');
    component.stale.set(true);
    fixture.detectChanges();

    expect(component.isDefaultContext()).toBe(false);
    const buttons = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    const recomputeButton = buttons.find(b => b.textContent?.includes(I18N.comparison.context.recompute_now));
    expect(recomputeButton).toBeTruthy();
    expect(fixture.nativeElement.textContent).toContain(I18N.comparison.context.stale_notice);
  });

  it('D6: the affordance stays absent for a named context while scores are not stale', async () => {
    await render();
    component.selectContext('action_stage');
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).not.toContain(I18N.comparison.context.recompute_now);
  });

  it('D2: the ETA renders next to the current/total progress once the backend reports one', async () => {
    await render();
    component.stale.set(true);
    component.recomputing.set(true);
    component.recomputeStatus.set({
      running: true, kind: 'recompute',
      progress: { phase: 'recompute', current: 500, total: 126172, eta_seconds: 480 },
      exit_code: null,
    });
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('8 min');
  });

  // The named-context branch used to render a single "can't be edited from the UI"
  // hint. It now renders the real delta editor, so the promote drag list and the
  // exclusion chips have to be in the DOM for a named context.
  it('renders the editable delta (promote drag list + exclusion chips) for a named context', async () => {
    await render();
    component.selectContext('action_stage');
    fixture.detectChanges();

    const dragHandles = fixture.nativeElement.querySelectorAll('[cdkdraghandle], [cdkDragHandle]');
    expect(dragHandles.length).toBe(component.draftPromote().length);
    expect(fixture.nativeElement.textContent).toContain(I18N.comparison.context.delta_description);
    expect(fixture.nativeElement.textContent).toContain(I18N.comparison.context.excluded_title);
  });

  it('D2: renders nothing extra when the backend has not reported an ETA yet', async () => {
    await render();
    component.stale.set(true);
    component.recomputing.set(true);
    component.recomputeStatus.set({
      running: true, kind: 'recompute',
      progress: { phase: 'recompute', current: 10, total: 126172 },
      exit_code: null,
    });
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).not.toContain('min');
  });
});
