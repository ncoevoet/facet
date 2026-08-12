import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { CdkTrapFocus } from '@angular/cdk/a11y';
import { Subject, of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { BurstCullingComponent } from './burst-culling.component';

describe('BurstCullingComponent', () => {
  let component: BurstCullingComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockSnackBar: { open: Mock };
  let mockI18n: { t: Mock; translations: Mock };

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
    // Returns a ref stub, not undefined: UndoService reads onAction() /
    // afterDismissed() off whatever open() hands back.
    mockSnackBar = {
      open: vi.fn(() => ({
        onAction: () => new Subject<void>(),
        afterDismissed: () => new Subject<void>(),
      })),
    };
    // `translations` is the bundle signal the (impure) translate pipe reads when
    // a test actually renders the template.
    mockI18n = { t: vi.fn((key: string) => key), translations: vi.fn(() => ({})) };

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

    it('commits the selected paths and hides the group after the cooldown', async () => {
      const group = component['groups']()[0];
      component['confirmGroup'](group);

      await vi.advanceTimersByTimeAsync(7000);

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
    const originalExitFullscreen = document.exitFullscreen;

    beforeEach(async () => {
      await (component as any).loadGroups();
    });

    afterEach(() => {
      setFullscreenElement(null);
      document.exitFullscreen = originalExitFullscreen;
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

    it('autoCullBody sends trim_brackets false by default', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await component['openAutoCull']();
      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({ trim_brackets: false }));
    });

    it('onTrimBracketsChange sets the signal and re-runs the dry run with trim_brackets true', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await component['onTrimBracketsChange'](true);
      expect(component['trimBrackets']()).toBe(true);
      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({ trim_brackets: true, dry_run: true }));
      expect(component['autoCullPreview']()).toEqual(preview);
    });

    // A re-run that answers with the same counts is indistinguishable from a
    // toggle that does nothing, which is exactly how the checkbox read.
    it('says so when trimming brackets changes none of the counts', async () => {
      component['autoCullPreview'].set({ ...preview });
      mockApi.post = vi.fn(() => of({ ...preview }));

      await component['onTrimBracketsChange'](true);

      expect(component['trimBracketsUnchanged']()).toBe(true);
    });

    it('stays quiet when trimming brackets does change the counts', async () => {
      component['autoCullPreview'].set({ ...preview });
      mockApi.post = vi.fn(() => of({ ...preview, rejected: preview.rejected + 3 }));

      await component['onTrimBracketsChange'](true);

      expect(component['trimBracketsUnchanged']()).toBe(false);
    });

    // A failed re-run leaves the previous preview in place, which must not be
    // read as "the trimmed run returned the same answer".
    it('stays quiet when the re-run fails', async () => {
      component['autoCullPreview'].set({ ...preview });
      mockApi.post = vi.fn(() => throwError(() => new Error('boom')));

      await component['onTrimBracketsChange'](true);

      expect(component['trimBracketsUnchanged']()).toBe(false);
    });

    it('clears the dialog notices on cancel', () => {
      component['autoCullPreview'].set(preview);
      component['trimBracketsUnchanged'].set(true);
      component['autoCullSuggestionNotice'].set('culling.profiles.wedding');

      component['cancelAutoCull']();

      expect(component['trimBracketsUnchanged']()).toBe(false);
      expect(component['autoCullSuggestionNotice']()).toBeNull();
    });
  });

  describe('cull profiles (genre presets)', () => {
    const profilesResponse = {
      profiles: [
        { id: 'balanced', label_key: 'culling.profiles.balanced', strictness: 50, eyes_closed_max: 4.0, poor_expression_min: 4.0, keep_min_per_group: 1, similarity_threshold: 85 },
        { id: 'wedding', label_key: 'culling.profiles.wedding', strictness: 35, eyes_closed_max: 5.0, poor_expression_min: 5.0, keep_min_per_group: 2, similarity_threshold: 90 },
      ],
      default: 'balanced',
    };

    it('loads profiles from the API', async () => {
      mockApi.get.mockReturnValue(of(profilesResponse));
      await (component as any).loadCullProfiles();

      expect(mockApi.get).toHaveBeenCalledWith('/culling/profiles');
      expect(component['cullProfiles']()).toEqual(profilesResponse.profiles);
    });

    it('applyProfile sets strictness and the similarity threshold, and persists the choice', () => {
      mockApi.get.mockReturnValue(of(mockCullingGroupsResponse));
      component['applyProfile'](profilesResponse.profiles[1]);

      expect(component['selectedProfile']()).toBe('wedding');
      expect(component['strictness']()).toBe(35);
      expect(component['similarityThreshold']()).toBe(90);
      expect(localStorage.getItem('facet_culling_profile')).toBe('wedding');
    });

    it('a manual strictness change after selecting a profile reverts the selection to custom', () => {
      mockApi.get.mockReturnValue(of(mockCullingGroupsResponse));
      component['applyProfile'](profilesResponse.profiles[1]);

      component['onStrictnessChange'](60);

      expect(component['selectedProfile']()).toBe('');
      expect(localStorage.getItem('facet_culling_profile')).toBeNull();
      expect(component['selectedProfileLabel']()).toBe('culling.profiles.custom');
    });

    it('a manual similarity threshold change after selecting a profile also reverts to custom', () => {
      mockApi.get.mockReturnValue(of(mockCullingGroupsResponse));
      component['applyProfile'](profilesResponse.profiles[1]);

      component['onThresholdChange'](75);

      expect(component['selectedProfile']()).toBe('');
    });

    it('restores a persisted profile id from localStorage on a fresh construction', async () => {
      localStorage.setItem('facet_culling_profile', 'wedding');
      mockApi.get.mockReturnValue(of(profilesResponse));
      TestBed.resetTestingModule();
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
      component = TestBed.runInInjectionContext(() => new BurstCullingComponent());

      expect(component['selectedProfile']()).toBe('wedding');

      await (component as any).loadCullProfiles();

      expect(component['strictness']()).toBe(35);
      expect(component['similarityThreshold']()).toBe(90);
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

  describe('edited-look cull preview', () => {
    const styles = [{ name: 'velvia', label_key: 'culling.cull_style.styles.velvia' }];

    function build(config: Record<string, unknown> | null, isEdition = true): BurstCullingComponent {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          BurstCullingComponent,
          { provide: ApiService, useValue: mockApi },
          { provide: MatSnackBar, useValue: mockSnackBar },
          { provide: I18nService, useValue: mockI18n },
          { provide: GalleryStore, useValue: { config: () => config } },
          { provide: AuthService, useValue: { isEdition: () => isEdition } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
        ],
      });
      return TestBed.runInInjectionContext(() => new BurstCullingComponent());
    }

    it('hides the style selector when no styles are configured', () => {
      component = build({ cull_styles: [] });
      expect(component['cullStyleCapable']()).toBe(false);
    });

    it('hides the style selector when the user lacks edition rights', () => {
      component = build({ cull_styles: styles }, false);
      expect(component['cullStyleCapable']()).toBe(false);
    });

    it('shows the style selector with configured styles and edition rights', () => {
      component = build({ cull_styles: styles });
      expect(component['cullStyleCapable']()).toBe(true);
      expect(component['cullStyles']()).toEqual(styles);
    });

    it('selecting a style updates the active style that drives the preview src swap', () => {
      component = build({ cull_styles: styles });
      expect(component['activeStyle']()).toBe('');
      component['selectCullStyle']('velvia');
      expect(component['activeStyle']()).toBe('velvia');
    });

    it('selecting Original clears the active style back to the flat frame', () => {
      component = build({ cull_styles: styles });
      component['selectCullStyle']('velvia');
      component['selectCullStyle']('');
      expect(component['activeStyle']()).toBe('');
    });
  });

  describe('developed preview staleness guard (F8)', () => {
    const grp = {
      group_id: 1, type: 'burst' as const, reason: '', best_path: '/photo1.jpg', count: 2,
      photos: [
        { path: '/photo1.jpg', filename: 'photo1.jpg', aggregate: 8, aesthetic: 7, tech_sharpness: 6, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8 },
        { path: '/photo2.jpg', filename: 'photo2.jpg', aggregate: 7, aesthetic: 6, tech_sharpness: 5, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7 },
      ],
    };

    const focus = (idx: number, style: string) => {
      component['groups'].set([grp]);
      component['lightboxGroupId'].set(component['groupKey'](grp));
      component['lightboxIndex'].set(idx);
      component['activeStyle'].set(style);
    };

    it('detaches the previous in-flight image handlers before spawning a new one', () => {
      focus(0, 'velvia');
      (component as any).preloadDevelopedPreview('/photo1.jpg', 'velvia');
      const first = component['previewImg']!;
      expect(first).toBeTruthy();

      (component as any).preloadDevelopedPreview('/photo1.jpg', 'velvia');

      expect(first.onload).toBeNull();
      expect(first.onerror).toBeNull();
      expect(component['previewImg']).not.toBe(first);
    });

    it('onerror reverts the style and toasts for the frame still shown', () => {
      focus(0, 'velvia');
      (component as any).preloadDevelopedPreview('/photo1.jpg', 'velvia');
      mockSnackBar.open.mockClear();

      component['previewImg']!.onerror!(new Event('error'));

      expect(component['activeStyle']()).toBe('');
      expect(component['previewLoading']()).toBe(false);
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('a stale onerror (user navigated away) neither reverts the style nor toasts', () => {
      focus(0, 'velvia');
      (component as any).preloadDevelopedPreview('/photo1.jpg', 'velvia');
      component['lightboxIndex'].set(1);
      mockSnackBar.open.mockClear();

      component['previewImg']!.onerror!(new Event('error'));

      expect(component['activeStyle']()).toBe('velvia');
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    it('a stale onload (style changed under it) does not clear the spinner', () => {
      focus(0, 'velvia');
      (component as any).preloadDevelopedPreview('/photo1.jpg', 'velvia');
      component['activeStyle'].set('portra');
      component['previewLoading'].set(true);

      component['previewImg']!.onload!(new Event('load'));

      expect(component['previewLoading']()).toBe(true);
    });
  });

  describe('subject close-up strip (non-face groups)', () => {
    const wildlifeGroup = {
      group_id: 3, type: 'similar' as const, reason: '', best_path: '/w1.jpg', count: 2,
      photos: [
        { path: '/w1.jpg', filename: 'w1.jpg', aggregate: 8, aesthetic: 7, tech_sharpness: 6, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8 },
        { path: '/w2.jpg', filename: 'w2.jpg', aggregate: 7, aesthetic: 6, tech_sharpness: 5, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7 },
      ],
    };
    const subjectFor = (path: string, score: number) => ({
      path, has_subject: true, crop: 'data:image/jpeg;base64,x',
      subject_sharpness: null, subject_prominence: null,
      crop_sharpness: score * 10, crop_sharpness_score: score,
    });

    const routePost = (faces: unknown, subjects: unknown) => {
      mockApi.post.mockImplementation((url: string) => {
        if (url === '/culling-group/faces') return of(faces);
        if (url === '/culling-group/subjects') return of(subjects);
        return of({});
      });
    };

    const focusGroup = () => {
      component['groups'].set([wildlifeGroup]);
      component['lightboxGroupId'].set(component['groupKey'](wildlifeGroup));
    };

    it('loadSubjectsForGroup populates the subject map from the response', async () => {
      routePost({ faces_by_path: {} }, {
        subjects_by_path: { '/w1.jpg': subjectFor('/w1.jpg', 10), '/w2.jpg': subjectFor('/w2.jpg', 4) },
      });

      await (component as any).loadSubjectsForGroup(wildlifeGroup);

      const map = component['subjectMap']();
      expect(map.get('/w1.jpg')?.has_subject).toBe(true);
      expect(map.get('/w2.jpg')?.crop_sharpness_score).toBe(4);
    });

    it('shows the strip for a group with subjects and no faces', async () => {
      routePost({ faces_by_path: {} }, {
        subjects_by_path: { '/w1.jpg': subjectFor('/w1.jpg', 10), '/w2.jpg': subjectFor('/w2.jpg', 4) },
      });
      focusGroup();

      await (component as any).loadCloseupsForGroup(wildlifeGroup);

      expect(component['subjectStripVisible']()).toBe(true);
      expect(mockApi.post).toHaveBeenCalledWith('/culling-group/subjects', { paths: ['/w1.jpg', '/w2.jpg'] });
    });

    it('does not load or show subjects when the group has faces', async () => {
      routePost({ faces_by_path: { '/w1.jpg': [{ id: 1, face_index: 0 }] } }, { subjects_by_path: {} });
      focusGroup();

      await (component as any).loadCloseupsForGroup(wildlifeGroup);

      expect(component['subjectStripVisible']()).toBe(false);
      expect(mockApi.post).not.toHaveBeenCalledWith('/culling-group/subjects', expect.anything());
    });

    it('records has_subject=false for unreturned paths so the strip stays hidden', async () => {
      routePost({ faces_by_path: {} }, { subjects_by_path: {} });
      focusGroup();

      await (component as any).loadCloseupsForGroup(wildlifeGroup);

      expect(component['subjectStripVisible']()).toBe(false);
      expect(component['subjectMap']().get('/w1.jpg')?.has_subject).toBe(false);
    });

    it('focusPhotoInLightbox jumps the darkroom to the clicked subject', () => {
      focusGroup();
      component['lightboxIndex'].set(0);

      component['focusPhotoInLightbox'](1);

      expect(component['lightboxIndex']()).toBe(1);
    });
  });

  describe('panorama corrections', () => {
    const panoramaGroup = {
      group_id: 7,
      type: 'panorama' as const,
      reason: '3 frames',
      sequence_kind: 'panorama',
      best_path: '/p1.jpg',
      count: 3,
      photos: [0, 1, 2].map(i => ({
        path: `/p${i}.jpg`, filename: `p${i}.jpg`, aggregate: 5, aesthetic: 5,
        tech_sharpness: 5, is_blink: 0, is_burst_lead: 0, date_taken: '2025-04-15',
        burst_score: 5, sequence_kind: 'panorama',
      })),
    };

    const seed = () => component['groups'].set([structuredClone(panoramaGroup)] as never);

    it('suppressing a set posts the correction for every frame', async () => {
      seed();

      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(component['groups']()[0]);

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/override_sequence', {
        paths: ['/p0.jpg', '/p1.jpg', '/p2.jpg'],
        kind: null,
      });
    });

    it('marks the frames pending so the group reads as corrected', async () => {
      seed();

      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(component['groups']()[0]);

      expect(component['groups']()[0].photos.map(p => p.sequence_override))
        .toEqual(['suppressed', 'suppressed', 'suppressed']);
      expect(component['pendingCorrections']()).toBe(1);
    });

    it('a relabel records the forced kind', async () => {
      seed();

      await (component as never as { correctSequence: (g: unknown, k: string) => Promise<void> })
        .correctSequence(component['groups']()[0], 'hdr_panorama');

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/override_sequence', {
        paths: ['/p0.jpg', '/p1.jpg', '/p2.jpg'],
        kind: 'hdr_panorama',
      });
      expect(component['groups']()[0].photos[0].sequence_override).toBe('hdr_panorama');
    });

    it('leaves the group in the feed — the detector has not run yet', async () => {
      seed();

      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(component['groups']()[0]);

      expect(component['groups']()).toHaveLength(1);
      expect(component['hiddenGroups']()).not.toContain('7_panorama');
    });

    it('a failed correction marks nothing pending', async () => {
      seed();
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('nope')));

      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(component['groups']()[0]);

      expect(component['groups']()[0].photos[0].sequence_override).toBeUndefined();
      expect(component['pendingCorrections']()).toBe(0);
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('dropping a correction clears it server-side and locally', async () => {
      seed();
      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(component['groups']()[0]);

      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(component['groups']()[0]);

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/clear_sequence_override', {
        paths: ['/p0.jpg', '/p1.jpg', '/p2.jpg'],
      });
      expect(component['pendingCorrections']()).toBe(0);
    });

    it('an uncorrected feed offers no re-run', () => {
      seed();

      expect(component['pendingCorrections']()).toBe(0);
    });
  });

  describe('shoot-type suggestion (auto-cull preset preselect)', () => {
    const profiles = [
      { id: 'balanced', label_key: 'culling.profiles.balanced', strictness: 50, eyes_closed_max: 4, poor_expression_min: 4, keep_min_per_group: 1, similarity_threshold: 85 },
      { id: 'wedding', label_key: 'culling.profiles.wedding', strictness: 35, eyes_closed_max: 5, poor_expression_min: 5, keep_min_per_group: 2, similarity_threshold: 90 },
      { id: 'wildlife', label_key: 'culling.profiles.wildlife', strictness: 70, eyes_closed_max: 0, poor_expression_min: 0, keep_min_per_group: 1, similarity_threshold: 82 },
    ];
    const preview = {
      groups_processed: 2, kept: 3, rejected: 4, highlights_added: 0,
      dry_run: true, preview: [], preview_truncated: false,
    };
    const suggestion = (profile: string | null) =>
      ({ profile, confidence: 0.8, evidence: { photos: 40, wedding: 32 } });

    /** Answer the suggestion endpoint, leaving every other GET on the feed. */
    const routeGet = (answer: unknown) => {
      mockApi.get = vi.fn((url: string) =>
        url === '/culling/suggest_profile' ? of(answer) : of(mockCullingGroupsResponse));
    };
    const suggestCalls = () =>
      mockApi.get.mock.calls.filter(call => call[0] === '/culling/suggest_profile');

    beforeEach(() => {
      component['cullProfiles'].set(profiles);
      mockApi.post = vi.fn(() => of(preview));
    });

    it('preselects the suggested preset when the user has chosen none', async () => {
      routeGet(suggestion('wedding'));

      await (component as any).applySuggestedProfile();

      expect(mockApi.get).toHaveBeenCalledWith('/culling/suggest_profile', {});
      expect(component['selectedProfile']()).toBe('wedding');
      expect(component['strictness']()).toBe(35);
      expect(component['suggestedProfileActive']()).toBe(true);
    });

    // A suggestion is not a decision: it must not become the preset the next
    // session restores, which only an explicit click may do.
    it('does not persist the preset it suggested', async () => {
      routeGet(suggestion('wedding'));

      await (component as any).applySuggestedProfile();

      expect(localStorage.getItem('facet_culling_profile')).toBeNull();
    });

    it('never overrides a preset the user picked, and does not even ask', async () => {
      component['applyProfile'](profiles[1]);
      routeGet(suggestion('wildlife'));

      await (component as any).applySuggestedProfile();

      expect(suggestCalls()).toHaveLength(0);
      expect(component['selectedProfile']()).toBe('wedding');
      expect(component['suggestedProfileActive']()).toBe(false);
    });

    it('a hand-moved knob also settles the preset for the session', async () => {
      component['onStrictnessChange'](80);
      routeGet(suggestion('wedding'));

      await (component as any).applySuggestedProfile();

      expect(suggestCalls()).toHaveLength(0);
      expect(component['strictness']()).toBe(80);
    });

    it('applies nothing when the scope argues for no preset', async () => {
      routeGet(suggestion(null));

      await (component as any).applySuggestedProfile();

      expect(component['selectedProfile']()).toBe('');
      expect(component['suggestedProfileActive']()).toBe(false);
    });

    it('applies nothing when the suggested preset is not configured', async () => {
      routeGet(suggestion('sports'));

      await (component as any).applySuggestedProfile();

      expect(component['selectedProfile']()).toBe('');
    });

    it('asks once per scope and reuses the answer', async () => {
      routeGet(suggestion('wedding'));

      await (component as any).applySuggestedProfile();
      await (component as any).applySuggestedProfile();

      expect(suggestCalls()).toHaveLength(1);
    });

    it('opens the dialog without waiting for the suggestion', async () => {
      // The suggestion never answers; the preview must land regardless.
      mockApi.get = vi.fn((url: string) =>
        url === '/culling/suggest_profile' ? new Subject() : of(mockCullingGroupsResponse));

      await component['openAutoCull']();

      expect(suggestCalls()).toHaveLength(1);
      expect(component['autoCullPreview']()).toEqual(preview);
      expect(component['selectedProfile']()).toBe('');
    });

    it('a suggestion landing on the open dialog re-runs the preview under its knobs', async () => {
      routeGet(suggestion('wedding'));
      component['autoCullPreview'].set(preview);

      await (component as any).applySuggestedProfile();

      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({
        dry_run: true, profile: 'wedding', strictness: 35,
      }));
    });

    // Renumbering "Reject N photos" under an open dialog without saying why is a
    // silent change to a destructive confirmation.
    it('names the preset when a landing suggestion renumbers an open dialog', async () => {
      routeGet(suggestion('wedding'));
      component['autoCullPreview'].set(preview);

      await (component as any).applySuggestedProfile();

      expect(component['autoCullSuggestionNotice']()).toBe('culling.profiles.wedding');
    });

    it('raises no notice when the dialog was not open', async () => {
      routeGet(suggestion('wedding'));

      await (component as any).applySuggestedProfile();

      expect(component['autoCullSuggestionNotice']()).toBeNull();
    });

    it('clears a stale notice when the dialog is opened again', async () => {
      routeGet(suggestion(null));
      component['autoCullSuggestionNotice'].set('culling.profiles.wildlife');

      await component['openAutoCull']();

      expect(component['autoCullSuggestionNotice']()).toBeNull();
    });
  });

  describe('darkroom overlays (focus peaking + composition grid)', () => {
    const grp = {
      group_id: 5, type: 'burst' as const, reason: '', best_path: '/f1.jpg', count: 2,
      photos: [
        { path: '/f1.jpg', filename: 'f1.jpg', aggregate: 8, aesthetic: 7, tech_sharpness: 6, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8 },
        { path: '/f2.jpg', filename: 'f2.jpg', aggregate: 7, aesthetic: 6, tech_sharpness: 5, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7 },
      ],
    };
    let renderPeaking: Mock;
    const flush = () => new Promise(resolve => setTimeout(resolve, 0));

    const openDarkroom = (index = 0) => {
      component['groups'].set([grp]);
      component['lightboxGroupId'].set(component['groupKey'](grp));
      component['lightboxIndex'].set(index);
    };
    /** Run the overlay effects and let their async raster work settle. */
    const settle = async () => {
      TestBed.tick();
      await flush();
    };

    beforeEach(() => {
      // jsdom has no 2D canvas, so the raster pipeline is replaced at its seam.
      renderPeaking = vi.fn((src: string) => Promise.resolve(`overlay:${src}`));
      vi.spyOn(component as any, 'renderPeaking').mockImplementation(renderPeaking as never);
      vi.spyOn(component as any, 'measureFrame').mockResolvedValue({ w: 6000, h: 4000 });
    });

    it('builds an overlay for the displayed frame once peaking is on', async () => {
      openDarkroom();
      component['peakingActive'].set(true);

      await settle();

      expect(component['peakingOverlays']().get('/f1.jpg')).toContain('size=1920');
      expect(component['peakingOverlays']().size).toBe(1);
    });

    it('builds nothing while peaking is off', async () => {
      openDarkroom();

      await settle();

      expect(renderPeaking).not.toHaveBeenCalled();
      expect(component['peakingOverlays']().size).toBe(0);
    });

    it('drops the overlays when peaking is switched back off', async () => {
      openDarkroom();
      component['peakingActive'].set(true);
      await settle();

      component['peakingActive'].set(false);
      await settle();

      expect(component['peakingOverlays']().size).toBe(0);
    });

    it('rebuilds for the new frame when the photo changes', async () => {
      openDarkroom();
      component['peakingActive'].set(true);
      await settle();

      component['lightboxIndex'].set(1);
      await settle();

      expect(component['peakingOverlays']().has('/f2.jpg')).toBe(true);
      expect(component['peakingOverlays']().has('/f1.jpg')).toBe(false);
    });

    it('covers every pane in compare mode', async () => {
      openDarkroom();
      component['peakingActive'].set(true);
      component['setCompareMode']('2up');

      await settle();

      expect([...component['peakingOverlays']().keys()]).toEqual(['/f1.jpg', '/f2.jpg']);
    });

    it('drops the overlays when the darkroom closes', async () => {
      openDarkroom();
      component['peakingActive'].set(true);
      await settle();

      component['closeLightbox']();
      await settle();

      expect(component['peakingOverlays']().size).toBe(0);
    });

    // The overlay rides the image's transform, so a pan must cost nothing; only
    // the swap to the full-resolution source is worth re-convolving.
    it('rebuilds on the full-resolution swap but not while panning', async () => {
      openDarkroom();
      component['peakingActive'].set(true);
      await settle();
      const afterFit = renderPeaking.mock.calls.length;

      component['zoom'].set({ scale: 2, tx: 0, ty: 0 });
      await settle();
      const afterZoom = renderPeaking.mock.calls.length;

      component['zoom'].set({ scale: 2, tx: 60, ty: 20 });
      await settle();

      expect(afterZoom).toBe(afterFit + 1);
      expect(renderPeaking.mock.calls.length).toBe(afterZoom);
      expect(renderPeaking.mock.calls.at(-1)?.[0]).toContain('/image?');
    });

    // A data URL per frame ever shown would grow with the session, and a cull
    // session walks thousands of frames.
    it('bounds how many edge maps it keeps while walking a long group', async () => {
      const long = {
        ...grp,
        photos: Array.from({ length: 12 }, (_, i) => ({ ...grp.photos[0], path: `/long${i}.jpg` })),
      };
      component['groups'].set([long]);
      component['lightboxGroupId'].set(component['groupKey'](long));
      component['peakingActive'].set(true);
      for (let i = 0; i < long.photos.length; i++) {
        component['lightboxIndex'].set(i);
        await settle();
      }

      expect(renderPeaking).toHaveBeenCalledTimes(12);
      expect(component['peakingCache'].size).toBe(8);
    });

    it('cycles the grid off → thirds → golden → off', () => {
      expect(component['gridMode']()).toBe('');
      component['cycleGrid']();
      expect(component['gridMode']()).toBe('thirds');
      component['cycleGrid']();
      expect(component['gridMode']()).toBe('golden');
      component['cycleGrid']();
      expect(component['gridMode']()).toBe('');
    });

    it('measures the frame the grid will cover, so it lands on the image box', async () => {
      openDarkroom();
      component['cycleGrid']();

      await settle();

      expect(component['frameSizes']().get('/f1.jpg')).toEqual({ w: 6000, h: 4000 });
    });

    // The signal-level tests above cannot see whether the overlays are actually
    // attached to each pane, which is the whole feature; this one renders them.
    it('renders both overlays over the frame and removes them when toggled off', async () => {
      // jsdom ships no scrollIntoView, which the rendered group list calls.
      const scrollIntoView = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = vi.fn();
      const fixture = TestBed.createComponent(BurstCullingComponent);
      const rendered = fixture.componentInstance;
      // Let this instance's own initial load land before seeding the darkroom,
      // or it would replace the seeded group and close it again.
      await flush();
      vi.spyOn(rendered as any, 'renderPeaking').mockResolvedValue('data:image/png;base64,x');
      vi.spyOn(rendered as any, 'measureFrame').mockResolvedValue({ w: 6000, h: 4000 });
      rendered['groups'].set([grp]);
      rendered['lightboxGroupId'].set(rendered['groupKey'](grp));
      rendered['lightboxIndex'].set(0);
      rendered['peakingActive'].set(true);
      rendered['gridMode'].set('thirds');

      fixture.detectChanges();
      await flush();
      fixture.detectChanges();

      const host: HTMLElement = fixture.nativeElement;
      expect(host.querySelector('img[src^="data:image/png"]')).toBeTruthy();
      // Two positions, each drawn on both axes.
      expect(host.querySelectorAll('svg line')).toHaveLength(4);

      rendered['peakingActive'].set(false);
      rendered['gridMode'].set('');
      fixture.detectChanges();
      await flush();
      fixture.detectChanges();

      expect(host.querySelector('img[src^="data:image/png"]')).toBeNull();
      expect(host.querySelectorAll('svg line')).toHaveLength(0);
      fixture.destroy();
      Element.prototype.scrollIntoView = scrollIntoView;
    });

    it('P and G toggle the overlays only while the darkroom is open', () => {
      const event = { preventDefault: vi.fn(), target: document.body } as unknown as Event;

      component['onPeakingKey'](event);
      component['onGridKey'](event);
      expect(component['peakingActive']()).toBe(false);
      expect(component['gridMode']()).toBe('');

      openDarkroom();
      component['onPeakingKey'](event);
      component['onGridKey'](event);

      expect(component['peakingActive']()).toBe(true);
      expect(component['gridMode']()).toBe('thirds');
    });
  });
});

// The IsKept/IsDecided/IsConfirmed/IsPassing/PassCountdown pipe tests moved to
// burst-culling.pipes.spec.ts alongside their extracted source.

// Rendered, unlike the suites above: both behaviours here are properties of the
// template (an Escape binding that has to survive the dialog's own keydown
// shield, and a CDK focus trap), so only the real DOM can show them.
describe('BurstCullingComponent modals (rendered)', () => {
  let fixture: ComponentFixture<BurstCullingComponent>;
  let component: any;

  const emptyFeed = {
    groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1,
  };
  const preview = {
    groups_processed: 3, kept: 4, rejected: 5, highlights_added: 0,
    dry_run: true, preview: [], preview_truncated: false,
  };

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: ApiService, useValue: {
          get: vi.fn(() => of(emptyFeed)),
          post: vi.fn(() => of(preview)),
          thumbnailUrl: vi.fn(() => '/thumb'),
          imageUrl: vi.fn(() => '/image'),
        } },
        { provide: MatSnackBar, useValue: { open: vi.fn(() => ({
          onAction: () => new Subject<void>(), afterDismissed: () => new Subject<void>(),
        })) } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: GalleryStore, useValue: { config: () => null } },
        { provide: AuthService, useValue: { isEdition: () => true } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    fixture = TestBed.createComponent(BurstCullingComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => fixture.destroy());

  const autoCullDialog = () =>
    fixture.debugElement.query(By.css('[aria-labelledby="autoCullTitle"]'));

  const openAutoCullDialog = () => {
    component['autoCullPreview'].set(preview);
    fixture.detectChanges();
  };

  it('closes the auto-cull dialog on Escape despite its keydown shield', () => {
    openAutoCullDialog();
    expect(autoCullDialog()).toBeTruthy();

    autoCullDialog().nativeElement.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
    );
    fixture.detectChanges();

    expect(component['autoCullPreview']()).toBeNull();
  });

  // The shield is load-bearing: the page's cull shortcuts must not fire while a
  // modal is up, so Escape had to be handled on the dialog rather than above it.
  it('keeps shielding the page from keys pressed inside the dialog', () => {
    openAutoCullDialog();
    const event = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true });
    const seenAtDocument = vi.fn();
    document.addEventListener('keydown', seenAtDocument);

    autoCullDialog().nativeElement.dispatchEvent(event);
    document.removeEventListener('keydown', seenAtDocument);

    expect(seenAtDocument).not.toHaveBeenCalled();
  });

  it('traps focus inside the auto-cull dialog', () => {
    openAutoCullDialog();

    expect(fixture.debugElement.queryAll(By.directive(CdkTrapFocus))
      .some(el => el.nativeElement === autoCullDialog().nativeElement)).toBe(true);
  });

  it('traps focus inside the darkroom', () => {
    component['groups'].set([{
      group_id: 1, type: 'burst', reason: '', best_path: '/p1.jpg', count: 1,
      photos: [{
        path: '/p1.jpg', filename: 'p1.jpg', aggregate: 8, aesthetic: 7,
        tech_sharpness: 6, is_blink: 0, is_burst_lead: 1,
        date_taken: '2024-01-01', burst_score: 8,
      }],
    }]);
    component['lightboxGroupId'].set(component['groupKey'](component['groups']()[0]));
    fixture.detectChanges();

    const darkroom = fixture.debugElement.query(By.css('[role="dialog"][aria-modal="true"]'));
    expect(fixture.debugElement.queryAll(By.directive(CdkTrapFocus))
      .some(el => el.nativeElement === darkroom.nativeElement)).toBe(true);
  });
});
