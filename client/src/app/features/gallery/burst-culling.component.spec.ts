import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ActivatedRoute } from '@angular/router';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { BurstCullingComponent } from './burst-culling.component';

describe('BurstCullingComponent', () => {
  let component: BurstCullingComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockSnackBar: { open: Mock };
  let mockI18n: { t: Mock };

  const mockCullingGroupsResponse = {
    groups: [
      {
        group_id: 1,
        type: 'burst',
        reason: '0.8s apart',
        photos: [
          { path: '/photo1.jpg', filename: 'photo1.jpg', aggregate: 8.5, aesthetic: 7.0, tech_sharpness: 6.0, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 9.0 },
          { path: '/photo2.jpg', filename: 'photo2.jpg', aggregate: 7.0, aesthetic: 6.5, tech_sharpness: 5.5, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7.0 },
          { path: '/photo3.jpg', filename: 'photo3.jpg', aggregate: 5.0, aesthetic: 5.0, tech_sharpness: 4.0, is_blink: 1, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 4.0 },
        ],
        best_path: '/photo1.jpg',
        count: 3,
      },
      {
        group_id: 2,
        type: 'similar',
        reason: '85% similar',
        photos: [
          { path: '/photo4.jpg', filename: 'photo4.jpg', aggregate: 9.0, aesthetic: 8.5, tech_sharpness: 7.0, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-02', burst_score: 9.5 },
          { path: '/photo5.jpg', filename: 'photo5.jpg', aggregate: 6.0, aesthetic: 5.0, tech_sharpness: 5.0, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-02', burst_score: 5.5 },
        ],
        best_path: '/photo4.jpg',
        count: 2,
      },
    ],
    total_groups: 2,
    page: 1,
    per_page: 20,
    total_pages: 1,
  };

  beforeEach(() => {
    localStorage.clear();
    mockApi = {
      get: vi.fn(() => of(mockCullingGroupsResponse)),
      post: vi.fn(() => of({})),
    };
    mockSnackBar = { open: vi.fn() };
    mockI18n = { t: vi.fn((key: string) => key) };

    TestBed.configureTestingModule({
      providers: [
        BurstCullingComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: GalleryStore, useValue: { config: () => null } },
        { provide: AuthService, useValue: { isEdition: () => true } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    component = TestBed.inject(BurstCullingComponent);
  });

  afterEach(() => {
    component.ngOnDestroy();
  });

  describe('initial state', () => {
    it('should have loading as a signal function', () => {
      expect(typeof component['loading']).toBe('function');
    });

    it('should start with confirming false', () => {
      expect(component['confirming']()).toBe(false);
    });
  });

  describe('loadGroups', () => {
    it('should load culling groups from API', async () => {
      await (component as any).loadGroups();

      expect(mockApi.get).toHaveBeenCalledWith('/culling-groups', expect.objectContaining({ page: 1, per_page: 20, exclude_rejected: true }));
      expect(component['groups']()).toHaveLength(2);
      expect(component['totalGroups']()).toBe(2);
      expect(component['loading']()).toBe(false);
    });

    it('should update exclude_rejected value and reload on change', async () => {
      mockApi.get.mockClear();
      (component as any).onExcludeRejectedChange(false);

      expect(component['excludeRejected']()).toBe(false);
      expect(mockApi.get).toHaveBeenCalledWith('/culling-groups', expect.objectContaining({ page: 1, per_page: 20, exclude_rejected: false }));
    });

    it('should auto-select best photo in each group', async () => {
      await (component as any).loadGroups();

      const selections = component['selectionsMap']();
      expect(selections.get(1)?.has('/photo1.jpg')).toBe(true);
      expect(selections.get(2)?.has('/photo4.jpg')).toBe(true);
    });

    it('should not create selection entry for groups without best_path', async () => {
      mockApi.get.mockReturnValue(of({
        groups: [{ group_id: 10, type: 'burst', reason: '', photos: [], best_path: '', count: 0 }],
        total_groups: 1, page: 1, per_page: 20, total_pages: 1,
      }));

      await (component as any).loadGroups();

      const selections = component['selectionsMap']();
      expect(selections.has(10)).toBe(false);
    });

    it('should set loading false on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));

      await (component as any).loadGroups();

      expect(component['loading']()).toBe(false);
    });

    it('should retain existing groups on error (no reset)', async () => {
      // First load succeeds
      await (component as any).loadGroups();
      expect(component['groups']()).toHaveLength(2);

      // Second load fails — groups remain from the first load
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));
      await (component as any).loadGroups();

      expect(component['groups']()).toHaveLength(2);
    });
  });

  describe('loadMore', () => {
    it('should append groups from the next page', async () => {
      await (component as any).loadGroups();
      component['totalPages'].set(2);

      const page2Response = {
        groups: [{ group_id: 3, type: 'burst', reason: '1s apart', photos: [], best_path: '', count: 0 }],
        total_groups: 3, page: 2, per_page: 20, total_pages: 2,
      };
      mockApi.get.mockReturnValue(of(page2Response));

      await (component as any).loadMore();

      expect(component['groups']()).toHaveLength(3);
      expect(component['currentPage']()).toBe(2);
    });

    it('should not load if no more pages', async () => {
      await (component as any).loadGroups();
      mockApi.get.mockClear();

      await (component as any).loadMore();

      expect(mockApi.get).not.toHaveBeenCalled();
    });
  });

  describe('toggleSelection', () => {
    beforeEach(async () => {
      await (component as any).loadGroups();
    });

    it('should add a photo to the selection when not already selected', () => {
      const group = component['groups']()[0];
      component['toggleSelection']('/photo2.jpg', group);

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo2.jpg')).toBe(true);
    });

    it('should remove a photo from the selection when already selected', () => {
      const group = component['groups']()[0];
      // photo1.jpg is auto-selected as best_path
      component['toggleSelection']('/photo1.jpg', group);

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo1.jpg')).toBe(false);
    });

    it('should allow multiple photos to be selected', () => {
      const group = component['groups']()[0];
      component['toggleSelection']('/photo2.jpg', group);
      component['toggleSelection']('/photo3.jpg', group);

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo1.jpg')).toBe(true); // auto-selected
      expect(kept?.has('/photo2.jpg')).toBe(true);
      expect(kept?.has('/photo3.jpg')).toBe(true);
    });

    it('should not mutate original map', () => {
      const originalMap = component['selectionsMap']();
      const group = component['groups']()[0];
      component['toggleSelection']('/photo2.jpg', group);
      const newMap = component['selectionsMap']();

      expect(newMap).not.toBe(originalMap);
    });
  });

  describe('confirmGroup (cooldown then commit + hide)', () => {
    beforeEach(async () => {
      vi.useFakeTimers();
      await (component as any).loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('greys the group and starts the countdown without posting yet', () => {
      const group = component['groups']()[0];
      component['confirmGroup'](group);

      expect(component['confirmedGroups']().has('1_burst')).toBe(true);
      expect(component['passingGroups']().get('1_burst')).toBe(7);
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('commits the selected paths and hides the group after the cooldown', () => {
      const group = component['groups']()[0];
      component['confirmGroup'](group);

      vi.advanceTimersByTime(7000);

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', {
        group_id: 1,
        type: 'burst',
        paths: ['/photo1.jpg', '/photo2.jpg', '/photo3.jpg'],
        keep_paths: ['/photo1.jpg'],
      });
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeUndefined();
    });

    it('does nothing when no photos are selected', () => {
      component['selectionsMap'].set(new Map());
      const group = component['groups']()[0];

      component['confirmGroup'](group);

      expect(component['confirmedGroups']().has('1_burst')).toBe(false);
      expect(component['passingGroups']().has('1_burst')).toBe(false);
    });

    it('cancelPass within the cooldown reverts the confirm without posting', () => {
      const group = component['groups']()[0];
      component['confirmGroup'](group);
      component['cancelPass'](group);

      vi.advanceTimersByTime(7000);

      expect(component['confirmedGroups']().has('1_burst')).toBe(false);
      expect(component['passingGroups']().has('1_burst')).toBe(false);
      expect(mockApi.post).not.toHaveBeenCalled();
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeDefined();
    });
  });

  describe('onSpace (darkroom confirm + auto-advance)', () => {
    beforeEach(async () => {
      await (component as any).loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    it('confirms the open group and opens the next group fullscreen', async () => {
      const [first, second] = component['groups']();
      component['openLightbox'](first, 0);

      component['onSpace'](new KeyboardEvent('keydown'));
      await Promise.resolve();
      await Promise.resolve();

      expect(component['confirmedGroups']().has('1_burst')).toBe(true);
      expect(component['lightboxGroupId']()).toBe(component['groupKey'](second));
    });

    it('closes the lightbox after confirming the last group', async () => {
      const second = component['groups']()[1];
      component['openLightbox'](second, 0);

      component['onSpace'](new KeyboardEvent('keydown'));
      await Promise.resolve();
      await Promise.resolve();

      expect(component['confirmedGroups']().has('2_similar')).toBe(true);
      expect(component['lightboxGroupId']()).toBeNull();
    });

    it('list mode: Space confirms the selected group and advances the selection', () => {
      // Lightbox closed, first group selected.
      component['selectedGroupIndex'].set(0);
      component['onSpace'](new KeyboardEvent('keydown'));

      expect(component['confirmedGroups']().has('1_burst')).toBe(true);
      expect(component['lightboxGroupId']()).toBeNull();
      expect(component['selectedGroupIndex']()).toBe(1);
    });
  });

  describe('fullscreen (darkroom)', () => {
    const setFullscreenElement = (value: Element | null) => {
      Object.defineProperty(document, 'fullscreenElement', { value, writable: true, configurable: true });
    };

    beforeEach(async () => {
      await (component as any).loadGroups();
    });

    afterEach(() => {
      setFullscreenElement(null);
    });

    it('toggleFullscreen() requests fullscreen on the darkroom dialog when not fullscreen', () => {
      const mockEl = { requestFullscreen: vi.fn().mockResolvedValue(undefined), focus: vi.fn() };
      Object.defineProperty(component, 'lightboxDialog', { value: () => ({ nativeElement: mockEl }), writable: true, configurable: true });
      setFullscreenElement(null);
      component['toggleFullscreen']();
      expect(mockEl.requestFullscreen).toHaveBeenCalled();
    });

    it('toggleFullscreen() calls exitFullscreen when in fullscreen', () => {
      document.exitFullscreen = vi.fn().mockResolvedValue(undefined);
      setFullscreenElement(document.body);
      component['toggleFullscreen']();
      expect(document.exitFullscreen).toHaveBeenCalled();
    });

    it('f key toggles fullscreen only while the darkroom is open', () => {
      const spy = vi.spyOn(component as any, 'toggleFullscreen').mockImplementation(() => {});
      component['onFullscreenToggle'](new KeyboardEvent('keydown', { key: 'f' }));
      expect(spy).not.toHaveBeenCalled();

      component['openLightbox'](component['groups']()[0], 0);
      component['onFullscreenToggle'](new KeyboardEvent('keydown', { key: 'f' }));
      expect(spy).toHaveBeenCalledTimes(1);
    });

    it('fullscreenchange syncs the isFullscreen signal from document.fullscreenElement', () => {
      setFullscreenElement(document.body);
      component['onFullscreenChange']();
      expect(component['isFullscreen']()).toBe(true);

      setFullscreenElement(null);
      component['onFullscreenChange']();
      expect(component['isFullscreen']()).toBe(false);
    });

    it('closeLightbox() exits fullscreen when the darkroom closes while fullscreen', () => {
      document.exitFullscreen = vi.fn().mockResolvedValue(undefined);
      component['openLightbox'](component['groups']()[0], 0);
      setFullscreenElement(document.body);

      component['closeLightbox']();

      expect(document.exitFullscreen).toHaveBeenCalled();
      expect(component['lightboxGroupId']()).toBeNull();
    });
  });

  describe('category filter', () => {
    beforeEach(async () => {
      mockApi.get.mockReturnValue(of({
        ...mockCullingGroupsResponse,
        groups: [
          { ...mockCullingGroupsResponse.groups[0], category: 'portrait' },
          { ...mockCullingGroupsResponse.groups[1], category: 'landscape' },
        ],
      }));
      await (component as any).loadGroups();
    });

    it('lists distinct categories from loaded groups', () => {
      expect(component['availableCategories']()).toEqual(['landscape', 'portrait']);
    });

    it('shows only matching groups when a category is selected', () => {
      component['onCategoryFilterChange']('portrait');
      const visible = component['visibleGroups']();
      expect(visible).toHaveLength(1);
      expect(visible[0].group_id).toBe(1);
    });

    it('shows all groups when the filter is cleared', () => {
      component['onCategoryFilterChange']('portrait');
      component['onCategoryFilterChange']('');
      expect(component['visibleGroups']()).toHaveLength(2);
    });
  });

  describe('sort', () => {
    it('defaults to easiest and passes the sort mode in request params', () => {
      expect(component['sortMode']()).toBe('easiest');
      expect(component['buildParams'](1)).toEqual(expect.objectContaining({ sort: 'easiest' }));
    });

    it('onSortChange updates the mode and reloads from page 1', () => {
      const spy = vi.spyOn(component as any, 'loadGroups');
      component['onSortChange']('recent');
      expect(component['sortMode']()).toBe('recent');
      expect(component['buildParams'](1)).toEqual(expect.objectContaining({ sort: 'recent' }));
      expect(spy).toHaveBeenCalled();
    });

    it('persists the sort choice to localStorage', () => {
      component['onSortChange']('best');
      expect(localStorage.getItem('facet_culling_sort')).toBe('best');
    });
  });

  describe('group_by granularity', () => {
    it('defaults to "all" and passes group_by in request params', () => {
      expect(component['groupBy']()).toBe('all');
      expect(component['buildParams'](1)).toEqual(expect.objectContaining({ group_by: 'all' }));
    });

    it('onGroupByChange updates the granularity, persists it, and reloads from page 1', () => {
      const spy = vi.spyOn(component as any, 'loadGroups');
      component['onGroupByChange']('scene');
      expect(component['groupBy']()).toBe('scene');
      expect(component['buildParams'](1)).toEqual(expect.objectContaining({ group_by: 'scene' }));
      expect(localStorage.getItem('facet_culling_group_by')).toBe('scene');
      expect(spy).toHaveBeenCalled();
    });

    it('ignores a no-op change to the same granularity', () => {
      const spy = vi.spyOn(component as any, 'loadGroups');
      component['onGroupByChange']('all');
      expect(spy).not.toHaveBeenCalled();
    });

    it('persists the category filter to localStorage', () => {
      component['onCategoryFilterChange']('portrait');
      expect(localStorage.getItem('facet_culling_category')).toBe('portrait');
    });
  });

  describe('auto-cull (one-button cull with keeper budget)', () => {
    const preview = {
      groups_processed: 3, kept: 4, rejected: 5, highlights_added: 2,
      dry_run: true, preview: [], preview_truncated: false,
    };

    it('openAutoCull dry-runs the current scope and stores the preview', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await component['openAutoCull']();
      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({
        dry_run: true,
        group_by: 'all',
        strictness: component['strictness'](),
      }));
      expect(component['autoCullPreview']()).toEqual(preview);
    });

    it('confirmAutoCull applies with dry_run false, closes the dialog and reloads', async () => {
      component['autoCullPreview'].set(preview);
      mockApi.post = vi.fn(() => of({ ...preview, dry_run: false }));
      const reload = vi.spyOn(component as any, 'loadGroups');
      await component['confirmAutoCull']();
      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({ dry_run: false }));
      expect(component['autoCullPreview']()).toBeNull();
      expect(reload).toHaveBeenCalled();
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('sends an empty highlights_album on apply when the checkbox is off', async () => {
      component['autoCullHighlights'].set(false);
      mockApi.post = vi.fn(() => of(preview));
      await component['confirmAutoCull']();
      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({ highlights_album: '' }));
    });

    it('sends the generated highlights album name on apply when the checkbox is on', async () => {
      component['autoCullHighlights'].set(true);
      mockApi.post = vi.fn(() => of(preview));
      await component['confirmAutoCull']();
      const body = mockApi.post.mock.calls[0][1] as Record<string, unknown>;
      expect(String(body['highlights_album'])).not.toBe('');
    });

    it('openAutoCull surfaces an error snackbar on failure', async () => {
      mockApi.post = vi.fn(() => throwError(() => new Error('boom')));
      await component['openAutoCull']();
      expect(component['autoCullPreview']()).toBeNull();
      expect(mockSnackBar.open).toHaveBeenCalled();
    });
  });

  describe('skipGroup (pass with countdown)', () => {
    beforeEach(async () => {
      vi.useFakeTimers();
      await (component as any).loadGroups();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('should add group to passingGroups with the configured countdown', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      expect(component['passingGroups']().has('1_burst')).toBe(true);
      expect(component['passingGroups']().get('1_burst')).toBe(7);
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should not add group to confirmedGroups immediately', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      expect(component['confirmedGroups']().has('1_burst')).toBe(false);
    });

    it('should decrement countdown every second', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      vi.advanceTimersByTime(1000);
      expect(component['passingGroups']().get('1_burst')).toBe(6);

      vi.advanceTimersByTime(1000);
      expect(component['passingGroups']().get('1_burst')).toBe(5);
    });

    it('should hide group after the countdown elapses', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      vi.advanceTimersByTime(7000);

      // Group should be hidden (removed from visible groups)
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeUndefined();
      // But still in groups
      expect(component['groups']().find(g => g.group_id === 1)).toBeDefined();
    });

    it('should remove group from passingGroups after timeout', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      vi.advanceTimersByTime(7000);

      expect(component['passingGroups']().has('1_burst')).toBe(false);
    });
  });

  describe('cancelPass', () => {
    beforeEach(async () => {
      vi.useFakeTimers();
      await (component as any).loadGroups();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('should remove group from passingGroups', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);
      expect(component['passingGroups']().has('1_burst')).toBe(true);

      component['cancelPass'](group);
      expect(component['passingGroups']().has('1_burst')).toBe(false);
    });

    it('should keep group visible after cancel', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      vi.advanceTimersByTime(2000);
      component['cancelPass'](group);

      // Group should still be visible
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeDefined();
    });

    it('should prevent auto-hide after cancel', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      vi.advanceTimersByTime(2000);
      component['cancelPass'](group);

      // Advance past original timeout
      vi.advanceTimersByTime(5000);

      // Group should still be visible
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeDefined();
    });
  });

  describe('confirmAllRemaining', () => {
    beforeEach(async () => {
      await (component as any).loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    it('should post best_path for each remaining group', async () => {
      await component['confirmAllRemaining']();

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({
        group_id: 1,
        type: 'burst',
        keep_paths: ['/photo1.jpg'],
      }));
      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({
        group_id: 2,
        type: 'similar',
        keep_paths: ['/photo4.jpg'],
      }));
    });

    it('should mark all groups as confirmed', async () => {
      await component['confirmAllRemaining']();

      expect(component['confirmedGroups']().has('1_burst')).toBe(true);
      expect(component['confirmedGroups']().has('2_similar')).toBe(true);
    });

    it('should skip already confirmed groups', async () => {
      // Directly confirm group 1 (simulating a previously confirmed group)
      component['confirmedGroups'].update(s => {
        const next = new Set(s);
        next.add('1_burst');
        return next;
      });
      mockApi.post.mockClear();

      await component['confirmAllRemaining']();

      // Only group 2 should be posted (group 1 was already confirmed)
      expect(mockApi.post).toHaveBeenCalledTimes(1);
      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({
        group_id: 2,
      }));
    });

    it('should set confirming false after completion', async () => {
      await component['confirmAllRemaining']();

      expect(component['confirming']()).toBe(false);
    });
  });

  describe('hasMore', () => {
    beforeEach(async () => {
      await (component as any).loadGroups();
    });

    it('should return false on single page', () => {
      expect(component['hasMore']()).toBe(false);
    });

    it('should return true when more pages exist', () => {
      component['totalPages'].set(2);
      expect(component['hasMore']()).toBe(true);
    });
  });
});

// The IsKept/IsDecided/IsConfirmed/IsPassing/PassCountdown pipe tests moved to
// burst-culling.pipes.spec.ts alongside their extracted source.
