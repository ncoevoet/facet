import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { HttpErrorResponse } from '@angular/common/http';
import { CdkTrapFocus } from '@angular/cdk/a11y';
import { Subject, of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { provideNativeDateAdapter } from '@angular/material/core';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { CullingStore } from './culling.store';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { PageContextService } from '../../core/agent/page-context.service';
import { AssistantCullPlanService } from '../../core/agent/assistant-cull-plan.service';
import { BurstCullingComponent } from './burst-culling.component';
import { AssistantChangesService, AssistantChangeBatch } from '../../core/agent/assistant-changes.service';
import { SyncedZoomComponent, LoadedSources, SHARP_PRELOAD_DEBOUNCE_MS } from './synced-zoom.component';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { SwipeDecisionDirective, SWIPE_SETTLE_MS } from '../../shared/directives/swipe-decision.directive';

let changes$ = new Subject<AssistantChangeBatch>();

describe('BurstCullingComponent', () => {
  let component: BurstCullingComponent;
  let store: CullingStore;
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
    changes$ = new Subject<AssistantChangeBatch>();
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
        provideNativeDateAdapter(),
        BurstCullingComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: GalleryStore, useValue: { config: () => null } },
        { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
        { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    component = TestBed.inject(BurstCullingComponent);
    store = TestBed.inject(CullingStore);
  });

  afterEach(() => {
    component.ngOnDestroy();
  });

  describe('overlays', () => {
    it('reports the auto-cull confirm as a dialog while it is shown, and nothing once it is closed', () => {
      const context = TestBed.inject(PageContextService);
      TestBed.tick();
      expect(context.overlays()).toEqual([]);
      store.autoCullPreview.set({
        groups_processed: 1, kept: 1, rejected: 1, highlights_added: 0,
        dry_run: true, preview: [], next_cursor: null, plan_digest: 'digest',
      });
      TestBed.tick();
      expect(context.overlays()).toEqual(['dialog']);
      store.autoCullPreview.set(null);
      TestBed.tick();
      expect(context.overlays()).toEqual([]);
    });
  });

  describe('assistant changes', () => {
    it('folds a batch of paths into the store in place', () => {
      const apply = vi.spyOn(store, 'applyExternalChanges').mockResolvedValue();
      changes$.next({ paths: ['/photo1.jpg'], count: 1 });
      expect(apply).toHaveBeenCalledWith(['/photo1.jpg'], expect.objectContaining({ lightboxOpen: false }));
    });

    it('keeps an inline Reload banner for a null batch across later batches, and Reload clears it', async () => {
      const fixture = TestBed.createComponent(BurstCullingComponent);
      fixture.detectChanges();
      await fixture.whenStable();
      const cull = fixture.debugElement.injector.get(CullingStore);
      await cull.loadGroups();
      cull.setPhotoKept(cull.groups()[0], '/photo2.jpg', true);
      const banner = () => fixture.nativeElement.querySelector('[data-testid="assistant-reload-banner"]') as HTMLElement | null;
      expect(banner()).toBeNull();
      changes$.next({ paths: null, count: 12 });
      await new Promise(resolve => setTimeout(resolve));
      fixture.detectChanges();
      expect(banner()).not.toBeNull();
      expect(banner()?.getAttribute('role')).toBe('status');
      expect(banner()?.textContent).toContain('culling.assistant_changed');
      mockApi.post.mockReturnValue(of({ photos: [], total: 0, missing: [] }));
      changes$.next({ paths: ['/photo1.jpg'], count: 1 });
      await new Promise(resolve => setTimeout(resolve));
      fixture.detectChanges();
      expect(banner()).not.toBeNull();
      const reload = vi.spyOn(cull, 'resetForReload');
      (banner()?.querySelector('button') as HTMLButtonElement).click();
      expect(reload).toHaveBeenCalledTimes(1);
      await fixture.whenStable();
      fixture.detectChanges();
      expect(banner()).toBeNull();
    });

    it('clamps the lightbox index when its photo disappears, and closes it when the group empties', async () => {
      await store.loadGroups();
      const group = store.groups()[0];
      component['lightboxGroupId'].set(store.groupKey(group));
      component['lightboxIndex'].set(2);
      TestBed.tick();
      mockApi.post.mockReturnValue(of({ photos: [], total: 0, missing: ['/photo3.jpg'] }));
      await store.applyExternalChanges(['/photo3.jpg']);
      TestBed.tick();
      expect(component['lightboxIndex']()).toBe(1);
      mockApi.post.mockReturnValue(of({ photos: [], total: 0, missing: ['/photo1.jpg', '/photo2.jpg'] }));
      await store.applyExternalChanges(['/photo1.jpg', '/photo2.jpg']);
      TestBed.tick();
      expect(component['lightboxGroupId']()).toBeNull();
    });
  });

  describe('focusedPath mirror (ui_get_context)', () => {
    const grp = {
      group_id: 1, type: 'burst', size: 2, best_path: '/photo1.jpg', best_score: 8, photos: [
        { path: '/photo1.jpg', filename: 'photo1.jpg', aggregate: 8, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8 },
        { path: '/photo2.jpg', filename: 'photo2.jpg', aggregate: 7, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7 },
      ],
    } as unknown as ReturnType<typeof store.groups>[number];

    it('follows the lightbox photo and is null with no lightbox', () => {
      // jsdom has no scrollIntoView; opening the lightbox scrolls its filmstrip.
      Element.prototype.scrollIntoView = vi.fn();
      const fixture = TestBed.createComponent(BurstCullingComponent);
      const own = fixture.debugElement.injector.get(CullingStore);
      const comp = fixture.componentInstance;
      expect(own).not.toBe(TestBed.inject(CullingStore));
      // What the agent sees: the root-scoped value.
      const seen = () => TestBed.inject(UserActivityJournal).darkroomFocus();
      own.groups.set([grp]);
      fixture.detectChanges();
      TestBed.tick();
      expect(seen()).toBeNull();
      comp['lightboxGroupId'].set(own.groupKey(grp));
      comp['lightboxIndex'].set(1);
      fixture.detectChanges();
      TestBed.tick();
      expect(seen()).toBe('/photo2.jpg');
      comp['lightboxGroupId'].set(null);
      fixture.detectChanges();
      TestBed.tick();
      expect(seen()).toBeNull();
    });
  });

  describe('loadGroups', () => {
    it('should load culling groups from API', async () => {
      await store.loadGroups();

      expect(mockApi.get).toHaveBeenCalledWith('/culling-groups', expect.objectContaining({ page: 1, per_page: 20, exclude_rejected: true }));
      expect(store.groups()).toHaveLength(2);
      expect(store.totalGroups()).toBe(2);
      expect(store.loading()).toBe(false);
    });

    it('should update exclude_rejected value and reload on change', async () => {
      mockApi.get.mockClear();
      (component as any).onExcludeRejectedChange(false);

      expect(store.excludeRejected()).toBe(false);
      expect(mockApi.get).toHaveBeenCalledWith('/culling-groups', expect.objectContaining({ page: 1, per_page: 20, exclude_rejected: false }));
    });

    it('should auto-select best photo in each group', async () => {
      await store.loadGroups();

      const selections = store.selectionsMap();
      expect(selections.get('1_burst')?.has('/photo1.jpg')).toBe(true);
      expect(selections.get('2_similar')?.has('/photo4.jpg')).toBe(true);
    });

    it('should not create selection entry for groups without best_path', async () => {
      mockApi.get.mockReturnValue(of({
        groups: [{ group_id: 10, type: 'burst', reason: '', photos: [], best_path: '', count: 0 }],
        total_groups: 1, page: 1, per_page: 20, total_pages: 1,
      }));

      await store.loadGroups();

      const selections = store.selectionsMap();
      expect(selections.has('10_burst')).toBe(false);
    });

    it('should set loading false on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadGroups();

      expect(store.loading()).toBe(false);
    });

    it('should retain existing groups on error (no reset)', async () => {
      // First load succeeds
      await store.loadGroups();
      expect(store.groups()).toHaveLength(2);

      // Second load fails — groups remain from the first load
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));
      await store.loadGroups();

      expect(store.groups()).toHaveLength(2);
    });
  });

  describe('showGroupForAgent (ui_show_culling_group)', () => {
    const show = (type: string, groupId: number): Promise<unknown> =>
      (component as any).showGroupForAgent({ type, group_id: groupId });

    it('stops paging when a page fails instead of re-requesting it', async () => {
      await store.loadGroups();
      store.totalPages.set(3);
      mockApi.get.mockClear();
      mockApi.get.mockReturnValue(throwError(() => new Error('down')));
      await expect(show('burst', 99)).rejects.toMatchObject({ code: 'not_found' });
      expect(mockApi.get).toHaveBeenCalledTimes(1);
    });

    it('waits for a load already in flight rather than racing it', async () => {
      await store.loadGroups();
      store.totalPages.set(2);
      const pending = new Subject<unknown>();
      mockApi.get.mockClear();
      mockApi.get.mockReturnValue(pending);
      const scrolled = store.loadMore() as Promise<void>;
      const asked = show('burst', 3);
      pending.next({ groups: [{ group_id: 3, type: 'burst', reason: '', photos: [], best_path: '', count: 0 }], total_groups: 3, page: 2, per_page: 20, total_pages: 2 });
      pending.complete();
      await scrolled;
      await expect(asked).resolves.toMatchObject({ group_id: 3 });
      expect(mockApi.get).toHaveBeenCalledTimes(1);
    });
  });

  // The one write behind the arrow keys, a swipe and the compare panes' own
  // buttons. It takes a path because "the current photo" is a question only the
  // keyboard can answer, and a compare grid has four of them on screen.
  describe('setPhotoKept (the shared darkroom decision)', () => {
    beforeEach(async () => {
      await store.loadGroups();
    });

    it('keeps and rejects the path it is given, whatever frame is focused', () => {
      const group = store.groups()[0];
      component['lightboxIndex'].set(0);

      store.setPhotoKept(group, '/photo3.jpg', true);
      expect([...store.selectionsMap().get('1_burst')!]).toContain('/photo3.jpg');

      store.setPhotoKept(group, '/photo3.jpg', false);
      expect([...store.selectionsMap().get('1_burst')!]).not.toContain('/photo3.jpg');
      expect(component['lightboxIndex']()).toBe(0);
    });

    it('is what the arrow keys write through', () => {
      const group = store.groups()[0];
      component['lightboxGroupId'].set(store.groupKey(group));
      component['lightboxIndex'].set(1);
      const event = { preventDefault: vi.fn(), target: document.body } as unknown as Event;

      component['onArrowUp'](event);

      expect([...store.selectionsMap().get('1_burst')!]).toContain('/photo2.jpg');
    });

    it('never mutates the map in place', () => {
      const group = store.groups()[0];
      const before = store.selectionsMap();

      store.setPhotoKept(group, '/photo2.jpg', true);

      expect(store.selectionsMap()).not.toBe(before);
    });
  });

  describe('confirmGroup (cooldown then commit + hide)', () => {
    beforeEach(async () => {
      vi.useFakeTimers();
      await store.loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('greys the group and starts the countdown without posting yet', () => {
      const group = store.groups()[0];
      store.confirmGroup(group);

      expect(store.confirmedGroups().has('1_burst')).toBe(true);
      expect(store.passingGroups().get('1_burst')).toBe(7);
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('commits the selected paths and hides the group after the cooldown', async () => {
      const group = store.groups()[0];
      store.confirmGroup(group);

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
      store.selectionsMap.set(new Map());
      const group = store.groups()[0];

      store.confirmGroup(group);

      expect(store.confirmedGroups().has('1_burst')).toBe(false);
      expect(store.passingGroups().has('1_burst')).toBe(false);
    });

    it('cancelPass within the cooldown reverts the confirm without posting', () => {
      const group = store.groups()[0];
      store.confirmGroup(group);
      store.cancelPass(group);

      vi.advanceTimersByTime(7000);

      expect(store.confirmedGroups().has('1_burst')).toBe(false);
      expect(store.passingGroups().has('1_burst')).toBe(false);
      expect(mockApi.post).not.toHaveBeenCalled();
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeDefined();
    });
  });

  describe('onSpace (darkroom confirm + auto-advance)', () => {
    beforeEach(async () => {
      await store.loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    it('confirms the open group and opens the next group fullscreen', async () => {
      const [first, second] = store.groups();
      component['openLightbox'](first, 0);

      component['onSpace'](new KeyboardEvent('keydown'));
      await Promise.resolve();
      await Promise.resolve();

      expect(store.confirmedGroups().has('1_burst')).toBe(true);
      expect(component['lightboxGroupId']()).toBe(store.groupKey(second));
    });

    it('closes the lightbox after confirming the last group', async () => {
      const second = store.groups()[1];
      component['openLightbox'](second, 0);

      component['onSpace'](new KeyboardEvent('keydown'));
      await Promise.resolve();
      await Promise.resolve();

      expect(store.confirmedGroups().has('2_similar')).toBe(true);
      expect(component['lightboxGroupId']()).toBeNull();
    });

    it('list mode: Shift+Space confirms the selected group and advances the selection', () => {
      // Lightbox closed, first group selected.
      component['selectedGroupIndex'].set(0);
      component['onShiftSpace'](new KeyboardEvent('keydown'));

      expect(store.confirmedGroups().has('1_burst')).toBe(true);
      expect(component['lightboxGroupId']()).toBeNull();
      expect(component['selectedGroupIndex']()).toBe(1);
    });

    it('list mode: Space toggles the photo under the cursor and confirms nothing', () => {
      component['selectedGroupIndex'].set(0);
      component['onArrowRight'](new KeyboardEvent('keydown'));
      const group = store.groups()[0];
      const wasKept = store.selectionsMap().get('1_burst')?.has('/photo2.jpg') ?? false;

      component['onSpace'](new KeyboardEvent('keydown'));
      expect(store.selectionsMap().get('1_burst')?.has('/photo2.jpg') ?? false).toBe(!wasKept);
      component['onSpace'](new KeyboardEvent('keydown'));
      expect(store.selectionsMap().get('1_burst')?.has('/photo2.jpg') ?? false).toBe(wasKept);

      expect(store.confirmedGroups().size).toBe(0);
      expect(group.photos[component['selectedPhotoIndex']()].path).toBe('/photo2.jpg');
    });

    it('list mode: Space leaves a confirmed group untouched', () => {
      component['selectedGroupIndex'].set(0);
      expect(store.confirmGroup(store.groups()[0])).toBe(true);
      const before = new Set(store.selectionsMap().get('1_burst') ?? []);

      component['onSpace'](new KeyboardEvent('keydown'));

      expect(new Set(store.selectionsMap().get('1_burst') ?? [])).toEqual(before);
    });

    it('list mode: ← / → move the photo cursor, stop at the group edges, and reset on a group change', () => {
      component['selectedGroupIndex'].set(0);
      component['onArrowLeft'](new KeyboardEvent('keydown'));
      expect(component['selectedPhotoIndex']()).toBe(0);
      for (let i = 0; i < 5; i++) component['onArrowRight'](new KeyboardEvent('keydown'));
      expect(component['selectedPhotoIndex']()).toBe(2);

      component['onArrowDown'](new KeyboardEvent('keydown'));
      expect(component['selectedGroupIndex']()).toBe(1);
      expect(component['selectedPhotoIndex']()).toBe(0);
    });

    it('list mode: ← / → are left to a text field', () => {
      component['selectedGroupIndex'].set(0);
      const input = document.createElement('input');
      document.body.append(input);
      try {
        const event = new KeyboardEvent('keydown', { key: 'ArrowRight', cancelable: true });
        Object.defineProperty(event, 'target', { value: input });
        component['onArrowRight'](event);
        expect(event.defaultPrevented).toBe(false);
        expect(component['selectedPhotoIndex']()).toBe(0);
      } finally {
        input.remove();
      }
    });

    it('list mode: Enter or Space on a focused control activates the control, not the page shortcut', () => {
      component['selectedGroupIndex'].set(0);
      const button = document.createElement('button');
      const item = document.createElement('div');
      item.setAttribute('role', 'menuitem');
      document.body.append(button, item);
      try {
        for (const target of [button, item]) {
          for (const key of ['Enter', ' ']) {
            const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
            Object.defineProperty(event, 'target', { value: target });
            if (key === 'Enter') component['onEnter'](event);
            else component['onSpace'](event);
            expect(event.defaultPrevented).toBe(false);
            if (key === ' ') {
              component['onShiftSpace'](event);
              expect(event.defaultPrevented).toBe(false);
            }
          }
        }
        expect(component['lightboxGroupId']()).toBeNull();
        expect(store.confirmedGroups().size).toBe(0);
      } finally {
        button.remove();
        item.remove();
      }
    });

    it('list mode: Enter with no focused control opens the selected group', () => {
      component['selectedGroupIndex'].set(0);
      const event = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });
      Object.defineProperty(event, 'target', { value: document.body });
      component['onEnter'](event);
      expect(component['lightboxGroupId']()).toBe('1_burst');
    });
  });

  describe('fullscreen (darkroom)', () => {
    const setFullscreenElement = (value: Element | null) => {
      Object.defineProperty(document, 'fullscreenElement', { value, writable: true, configurable: true });
    };
    const originalExitFullscreen = document.exitFullscreen;

    beforeEach(async () => {
      await store.loadGroups();
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

      component['openLightbox'](store.groups()[0], 0);
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
      component['openLightbox'](store.groups()[0], 0);
      setFullscreenElement(document.body);

      component['closeLightbox']();

      expect(document.exitFullscreen).toHaveBeenCalled();
      expect(component['lightboxGroupId']()).toBeNull();
    });
  });

  describe('darkroom keyboard-shortcut legend toggle', () => {
    it('defaults to hidden', () => {
      expect(component['legendVisible']()).toBe(false);
    });

    it('toggleLegend() flips visibility and persists the choice', () => {
      component['toggleLegend']();
      expect(component['legendVisible']()).toBe(true);
      expect(localStorage.getItem('facet_culling_legend')).toBe('true');

      component['toggleLegend']();
      expect(component['legendVisible']()).toBe(false);
      expect(localStorage.getItem('facet_culling_legend')).toBe('false');
    });

    it('restores a persisted visible legend from localStorage on a fresh construction', () => {
      localStorage.setItem('facet_culling_legend', 'true');
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          provideNativeDateAdapter(),
          BurstCullingComponent,
          { provide: ApiService, useValue: mockApi },
          { provide: MatSnackBar, useValue: mockSnackBar },
          { provide: I18nService, useValue: mockI18n },
          { provide: GalleryStore, useValue: { config: () => null } },
          { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
          { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
        ],
      });
      component = TestBed.runInInjectionContext(() => new BurstCullingComponent());
      store = component['cull'];

      expect(component['legendVisible']()).toBe(true);
    });
  });

  describe('darkroom hover loupe toggle', () => {
    it('defaults to on when nothing is in localStorage', () => {
      expect(component['darkroomLoupeActive']()).toBe(true);
    });

    it('toggleDarkroomLoupe() flips the setting and persists the choice', () => {
      component['toggleDarkroomLoupe']();
      expect(component['darkroomLoupeActive']()).toBe(false);
      expect(localStorage.getItem('facet_culling_darkroom_loupe')).toBe('false');

      component['toggleDarkroomLoupe']();
      expect(component['darkroomLoupeActive']()).toBe(true);
      expect(localStorage.getItem('facet_culling_darkroom_loupe')).toBe('true');
    });

    it('restores a persisted "off" value from localStorage on a fresh construction', () => {
      localStorage.setItem('facet_culling_darkroom_loupe', 'false');
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          provideNativeDateAdapter(),
          BurstCullingComponent,
          { provide: ApiService, useValue: mockApi },
          { provide: MatSnackBar, useValue: mockSnackBar },
          { provide: I18nService, useValue: mockI18n },
          { provide: GalleryStore, useValue: { config: () => null } },
          { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
          { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
        ],
      });
      component = TestBed.runInInjectionContext(() => new BurstCullingComponent());
      store = component['cull'];

      expect(component['darkroomLoupeActive']()).toBe(false);
    });

    it('is inactive while the darkroom frame is zoomed beyond fit, even when the toggle is on', () => {
      expect(component['darkroomLoupeActive']()).toBe(true);
      expect(component['darkroomLoupeEffective']()).toBe(true);

      component['zoom'].set({ scale: 2, tx: 0, ty: 0 });
      expect(component['darkroomLoupeEffective']()).toBe(false);

      component['zoom'].set({ scale: 1, tx: 0, ty: 0 });
      expect(component['darkroomLoupeEffective']()).toBe(true);
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
      await store.loadGroups();
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
      expect(store.sortMode()).toBe('easiest');
      expect(store.buildParams(1)).toEqual(expect.objectContaining({ sort: 'easiest' }));
    });

    it('onSortChange updates the mode and reloads from page 1', () => {
      const spy = vi.spyOn(store, 'loadGroups');
      component['onSortChange']('recent');
      expect(store.sortMode()).toBe('recent');
      expect(store.buildParams(1)).toEqual(expect.objectContaining({ sort: 'recent' }));
      expect(spy).toHaveBeenCalled();
    });

    it('persists the sort choice to localStorage', () => {
      component['onSortChange']('best');
      expect(localStorage.getItem('facet_culling_sort')).toBe('best');
    });
  });

  describe('group_by granularity', () => {
    it('defaults to "all" and passes group_by in request params', () => {
      expect(store.groupBy()).toBe('all');
      expect(store.buildParams(1)).toEqual(expect.objectContaining({ group_by: 'all' }));
    });

    it('onGroupByChange updates the granularity, persists it, and reloads from page 1', () => {
      const spy = vi.spyOn(store, 'loadGroups');
      component['onGroupByChange']('scene');
      expect(store.groupBy()).toBe('scene');
      expect(store.buildParams(1)).toEqual(expect.objectContaining({ group_by: 'scene' }));
      expect(localStorage.getItem('facet_culling_group_by')).toBe('scene');
      expect(spy).toHaveBeenCalled();
    });

    it('ignores a no-op change to the same granularity', () => {
      const spy = vi.spyOn(store, 'loadGroups');
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
      dry_run: true, preview: [], next_cursor: null, plan_digest: 'digest',
    };

    it('openAutoCull dry-runs the current scope and stores the preview', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.openAutoCull();
      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({
        dry_run: true,
        group_by: 'all',
        strictness: store.strictness(),
      }));
      expect(store.autoCullPreview()).toEqual(preview);
    });

    /** The apply body, which only exists once a preview has been agreed to. */
    const appliedBody = () => mockApi.post.mock.calls.at(-1)?.[1] as Record<string, unknown>;

    /** Answer a deferred apply, and wait for the handler behind it to finish. */
    const settleApply = async (response: Subject<typeof preview>, applied: Promise<void>) => {
      response.next({ ...preview, dry_run: false });
      response.complete();
      await applied;
    };

    it('confirmAutoCull applies with dry_run false, closes the dialog and reloads', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.openAutoCull();
      const reload = vi.spyOn(store, 'loadGroups');

      await component['confirmAutoCull']();

      expect(appliedBody()).toMatchObject({ dry_run: false });
      expect(store.autoCullPreview()).toBeNull();
      expect(reload).toHaveBeenCalled();
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('confirmAutoCull puts the keyboard selection back on the first group once the apply lands', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.openAutoCull();
      component['selectedGroupIndex'].set(1);

      await component['confirmAutoCull']();

      expect(component['selectedGroupIndex']()).toBe(0);
    });

    // Apply is reachable from the dialog alone, and the dialog is the preview.
    it('applies nothing when no preview was agreed to', async () => {
      mockApi.post = vi.fn(() => of(preview));

      await component['confirmAutoCull']();

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('sends an empty highlights_album on apply when the checkbox is off', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.openAutoCull();
      store.autoCullHighlights.set(false);

      await component['confirmAutoCull']();

      expect(appliedBody()).toMatchObject({ highlights_album: '' });
    });

    it('sends the generated highlights album name on apply when the checkbox is on', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.openAutoCull();
      store.autoCullHighlights.set(true);

      await component['confirmAutoCull']();

      expect(String(appliedBody()['highlights_album'])).not.toBe('');
    });

    it('openAutoCull surfaces an error snackbar on failure', async () => {
      mockApi.post = vi.fn(() => throwError(() => new Error('boom')));
      await store.openAutoCull();
      expect(store.autoCullPreview()).toBeNull();
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('autoCullBody sends trim_brackets false by default', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.openAutoCull();
      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({ trim_brackets: false }));
    });

    it('onTrimBracketsChange sets the signal and re-runs the dry run with trim_brackets true', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.onTrimBracketsChange(true);
      expect(store.trimBrackets()).toBe(true);
      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({ trim_brackets: true, dry_run: true }));
      expect(store.autoCullPreview()).toEqual(preview);
    });

    // A re-run that answers with the same counts is indistinguishable from a
    // toggle that does nothing, which is exactly how the checkbox read.
    it('says so when trimming brackets changes none of the counts', async () => {
      store.autoCullPreview.set({ ...preview });
      mockApi.post = vi.fn(() => of({ ...preview }));

      await store.onTrimBracketsChange(true);

      expect(store.trimBracketsUnchanged()).toBe(true);
    });

    it('stays quiet when trimming brackets does change the counts', async () => {
      store.autoCullPreview.set({ ...preview });
      mockApi.post = vi.fn(() => of({ ...preview, rejected: preview.rejected + 3 }));

      await store.onTrimBracketsChange(true);

      expect(store.trimBracketsUnchanged()).toBe(false);
    });

    // A failed re-run leaves the previous preview in place, which must not be
    // read as "the trimmed run returned the same answer".
    it('stays quiet when the re-run fails', async () => {
      store.autoCullPreview.set({ ...preview });
      mockApi.post = vi.fn(() => throwError(() => new Error('boom')));

      await store.onTrimBracketsChange(true);

      expect(store.trimBracketsUnchanged()).toBe(false);
    });

    it('clears the dialog notices on cancel', () => {
      store.autoCullPreview.set(preview);
      store.trimBracketsUnchanged.set(true);
      store.autoCullSuggestionNotice.set('culling.profiles.wedding');

      store.cancelAutoCull();

      expect(store.trimBracketsUnchanged()).toBe(false);
      expect(store.autoCullSuggestionNotice()).toBeNull();
    });

    // The checkbox is a mirror of the snapshot Apply sends, not of the click: a
    // re-run that failed left the snapshot on trim_brackets:false while the box
    // stayed ticked, promising a trim the apply would never perform.
    it('reverts the trim-brackets checkbox when the re-run fails', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.openAutoCull();
      mockApi.post = vi.fn(() => throwError(() => new Error('boom')));
      mockSnackBar.open.mockClear();

      await store.onTrimBracketsChange(true);

      expect(store.trimBrackets()).toBe(false);
      expect(store.autoCullRequest()).toMatchObject({ trim_brackets: false });
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('keeps the trim-brackets checkbox ticked when the re-run lands', async () => {
      mockApi.post = vi.fn(() => of(preview));
      await store.openAutoCull();

      await store.onTrimBracketsChange(true);

      expect(store.trimBrackets()).toBe(true);
      expect(store.autoCullRequest()).toMatchObject({ trim_brackets: true });
    });

    describe('the destructive apply is uninterruptible', () => {
      /** Opens the dialog on a landed dry run, then leaves an apply in flight. */
      const applyInFlight = async () => {
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        const response = new Subject<typeof preview>();
        mockApi.post = vi.fn(() => response);
        return { response, applied: component['confirmAutoCull']() };
      };

      // Dismissing mid-flight closed the dialog, which re-armed Apply over a
      // snapshot already being applied and left the apply's own close to bump
      // the dry-run generation over whatever the reopened dialog was awaiting.
      it('ignores cancel and Escape while the apply is in flight', async () => {
        const { response, applied } = await applyInFlight();

        store.cancelAutoCull();
        component['onEscape'](new KeyboardEvent('keydown', { key: 'Escape' }));

        expect(store.autoCullPreview()).toEqual(preview);
        expect(store.autoCullRequest()).not.toBeNull();
        expect(mockApi.post).toHaveBeenCalledTimes(1);

        await settleApply(response, applied);

        expect(store.autoCullPreview()).toBeNull();
        expect(mockApi.post).toHaveBeenCalledTimes(1);
      });

      it('sends one apply per snapshot however often Apply is clicked', async () => {
        const { response, applied } = await applyInFlight();

        const second = component['confirmAutoCull']();

        expect(mockApi.post).toHaveBeenCalledTimes(1);

        await settleApply(response, applied);
        await second;

        expect(mockApi.post).toHaveBeenCalledTimes(1);
      });

      it('re-arms the dialog after a failed apply', async () => {
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        mockApi.post = vi.fn(() => throwError(() => new Error('boom')));

        await component['confirmAutoCull']();

        expect(store.autoCullPreview()).toEqual(preview);
        expect(mockSnackBar.open).toHaveBeenCalled();

        mockApi.post = vi.fn(() => of({ ...preview, dry_run: false }));
        await component['confirmAutoCull']();

        expect(mockApi.post).toHaveBeenCalledTimes(1);
        expect(store.autoCullPreview()).toBeNull();
      });

      // The close behind a completed apply bumps the dry-run generation, so the
      // next dialog must still be able to open.
      it('dry-runs again after a completed apply', async () => {
        const { response, applied } = await applyInFlight();
        await settleApply(response, applied);

        mockApi.post = vi.fn(() => of({ ...preview, rejected: 9 }));
        await store.openAutoCull();

        expect(store.autoCullPreview()).toMatchObject({ rejected: 9 });
        expect(store.autoCullLoading()).toBe(false);
      });
    });

    /**
     * Apply sends the snapshot verbatim, so nothing may repaint it while that
     * request is open — the dialog would then describe a run the destructive one
     * was never computed from.
     *
     * The profile suggestion's re-run is the writer that reaches it: it is
     * fire-and-forget, started behind every dry run, and lands whenever the
     * backend answers — including in the middle of the apply, where it used to
     * fire a dry run straight through and publish over the snapshot.
     */
    describe('no dry run may move the snapshot under the apply', () => {
      const flush = () => new Promise(resolve => setTimeout(resolve, 0));
      const profiles = [
        { id: 'wedding', label_key: 'culling.profiles.wedding', strictness: 35, eyes_closed_max: 5, poor_expression_min: 5, keep_min_per_group: 2, similarity_threshold: 90 },
      ];

      it('refuses to dry-run at all while the apply is in flight', async () => {
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        const snapshot = store.autoCullRequest();
        const response = new Subject<typeof preview>();
        mockApi.post = vi.fn(() => response);
        const applied = component['confirmAutoCull']();

        // Left unawaited on purpose: a call that fires is a call that hangs on
        // the apply's own answer, and the count below is the finding either way.
        const outcome = store.openAutoCull();

        expect(mockApi.post).toHaveBeenCalledTimes(1);
        expect(store.autoCullRequest()).toBe(snapshot);

        await settleApply(response, applied);

        expect(await outcome).toBe('superseded');
      });

      /** The reproduction, through the writer that actually reaches it. */
      it('drops the suggestion re-run that lands mid-apply', async () => {
        store.cullProfiles.set(profiles);
        const suggestReply = new Subject<unknown>();
        mockApi.get = vi.fn((url: string) =>
          url === '/culling/suggest_profile' ? suggestReply : of(mockCullingGroupsResponse));
        const bodies: Record<string, unknown>[] = [];
        const posts: Subject<unknown>[] = [];
        mockApi.post = vi.fn((_url: string, body: Record<string, unknown>) => {
          bodies.push(body);
          const answer = new Subject<unknown>();
          posts.push(answer);
          return answer;
        });

        void store.openAutoCull();
        await flush();
        posts[0].next(preview);
        await flush();
        const snapshot = store.autoCullRequest();

        void component['confirmAutoCull']();
        await flush();
        suggestReply.next({ profile: 'wedding', confidence: 0.8, evidence: {} });
        await flush();

        expect(bodies.filter(body => body['dry_run'] === true)).toHaveLength(1);
        expect(store.autoCullRequest()).toBe(snapshot);
        expect(store.autoCullPreview()).toEqual(preview);
        // The notice would have claimed counts the refused re-run never computed.
        expect(store.autoCullSuggestionNotice()).toBeNull();

        posts[1].next({ ...preview, dry_run: false });
        await flush();
      });

      // The same drop, one layer up. Refusing at the dry run's door came too
      // late: applying the preset had already moved strictness and lit the
      // suggested-preset chip, so the user watched the knobs jump while the
      // destructive request was open — knobs that describe neither the counts on
      // screen nor the request being applied.
      it('leaves the knobs alone when the suggestion resolves mid-apply', async () => {
        store.cullProfiles.set(profiles);
        const suggestReply = new Subject<unknown>();
        mockApi.get = vi.fn((url: string) =>
          url === '/culling/suggest_profile' ? suggestReply : of(mockCullingGroupsResponse));
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        const knobs = () => ({ strictness: store.strictness(), profile: store.selectedProfile() });
        const before = knobs();
        const response = new Subject<typeof preview>();
        mockApi.post = vi.fn(() => response);
        const applied = component['confirmAutoCull']();

        suggestReply.next({ profile: 'wedding', confidence: 0.8, evidence: {} });
        await flush();

        expect(knobs()).toEqual(before);
        expect(component['suggestedProfileActive']()).toBe(false);
        expect(store.autoCullSuggestionNotice()).toBeNull();
        // The apply, and nothing behind it.
        expect(mockApi.post).toHaveBeenCalledTimes(1);

        await settleApply(response, applied);
      });

      // The same writer, one beat earlier: its dry run was already in flight when
      // Apply was hit, so refusing at the door cannot catch it.
      it('drops the answer of a dry run that was already in flight when Apply was hit', async () => {
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        const snapshot = store.autoCullRequest();
        const late = new Subject<typeof preview>();
        mockApi.post = vi.fn(() => late);
        void store.openAutoCull();
        await flush();
        const response = new Subject<typeof preview>();
        mockApi.post = vi.fn(() => response);
        const applied = component['confirmAutoCull']();

        late.next({ ...preview, rejected: 99 });
        await flush();

        expect(store.autoCullPreview()).toEqual(preview);
        expect(store.autoCullRequest()).toBe(snapshot);

        await settleApply(response, applied);

        expect(store.autoCullPreview()).toBeNull();
      });

      // Nothing else may edit the state the snapshot is mirrored in either.
      it('refuses the trim-brackets toggle while the apply is in flight', async () => {
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        const response = new Subject<typeof preview>();
        mockApi.post = vi.fn(() => response);
        const applied = component['confirmAutoCull']();

        const toggling = store.onTrimBracketsChange(true);

        expect(store.trimBrackets()).toBe(false);
        expect(mockApi.post).toHaveBeenCalledTimes(1);

        await settleApply(response, applied);
        await toggling;

        expect(store.trimBrackets()).toBe(false);
      });
    });

    /**
     * The invariant the trim-brackets checkbox exists under: whenever the dialog
     * is at rest — Apply armed, Cancel armed — the box says exactly what the
     * snapshot Apply sends carries. The box is a promise about a destructive
     * request, so a ticked box over a `trim_brackets: false` body is a false one.
     *
     * Asserted across the three ways the toggle's own re-run can end, since two
     * of them used to be indistinguishable from inside the toggle.
     */
    describe('the trim-brackets checkbox never contradicts the snapshot', () => {
      const flush = () => new Promise(resolve => setTimeout(resolve, 0));
      /** Armed, and what the two sides say — one assertion, one legible diff. */
      const armedState = () => ({
        armed: !store.autoCullBusy(),
        box: store.trimBrackets(),
        snapshotTrim: store.autoCullRequest()?.trim_brackets,
      });

      it('holds when the toggle\'s own re-run lands', async () => {
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();

        await store.onTrimBracketsChange(true);

        expect(armedState()).toEqual({ armed: true, box: true, snapshotTrim: true });
      });

      it('holds when the toggle\'s own re-run fails', async () => {
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        mockApi.post = vi.fn(() => throwError(() => new Error('boom')));

        await store.onTrimBracketsChange(true);

        expect(armedState()).toEqual({ armed: true, box: false, snapshotTrim: false });
      });

      // The reproduction. A superseded re-run reads from inside the toggle
      // exactly like its own failure, so the box was reconciled against the stale
      // snapshot the newer run had not replaced yet — and that run then published
      // `trim_brackets: true` under a box the toggle had just unticked.
      it('holds when a newer run supersedes the toggle\'s own', async () => {
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        const bodies: Record<string, unknown>[] = [];
        const posts: Subject<typeof preview>[] = [];
        mockApi.post = vi.fn((_url: string, body: Record<string, unknown>) => {
          bodies.push(body);
          const answer = new Subject<typeof preview>();
          posts.push(answer);
          return answer;
        });

        const toggling = store.onTrimBracketsChange(true);
        await flush();
        void store.openAutoCull();
        await flush();
        posts[0].next(preview);
        await toggling;

        // The dialog belongs to the newer run: nothing is confirmable until it
        // answers, which is what makes leaving the box to it safe.
        expect(store.autoCullBusy()).toBe(true);

        posts[1].next({ ...preview, kept: 9 });
        await flush();

        expect(bodies[1]).toMatchObject({ trim_brackets: true });
        expect(armedState()).toEqual({ armed: true, box: true, snapshotTrim: true });
      });

      // The same ordering, one beat further on. Leaving the box to the newer run
      // only holds while that run publishes: the run that supersedes a toggle is
      // the suggestion's re-run — the checkbox is disabled for its own run's
      // duration — and it can fail in turn. A failed run never moved the
      // snapshot, so the box was left standing on the superseding run's value
      // over a snapshot that still carries the older one.
      it('holds when the run that superseded the toggle\'s own fails', async () => {
        store.cullProfiles.set([
          { id: 'wedding', label_key: 'culling.profiles.wedding', strictness: 35, eyes_closed_max: 5, poor_expression_min: 5, keep_min_per_group: 2, similarity_threshold: 90 },
        ]);
        const suggestReply = new Subject<unknown>();
        mockApi.get = vi.fn((url: string) =>
          url === '/culling/suggest_profile' ? suggestReply : of(mockCullingGroupsResponse));
        mockApi.post = vi.fn(() => of(preview));
        await store.openAutoCull();
        const posts: Subject<typeof preview>[] = [];
        mockApi.post = vi.fn(() => {
          const answer = new Subject<typeof preview>();
          posts.push(answer);
          return answer;
        });

        const toggling = store.onTrimBracketsChange(true);
        await flush();
        // The suggestion's re-run takes the dialog over from the toggle's run...
        suggestReply.next({ profile: 'wedding', confidence: 0.8, evidence: {} });
        await flush();
        posts[0].next(preview);
        await toggling;
        // ...and then fails, leaving the snapshot where the toggle found it.
        posts[1].error(new Error('boom'));
        await flush();

        expect(armedState()).toEqual({ armed: true, box: false, snapshotTrim: false });
      });
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
      await store.loadCullProfiles();

      expect(mockApi.get).toHaveBeenCalledWith('/culling/profiles');
      expect(store.cullProfiles()).toEqual(profilesResponse.profiles);
    });

    it('applyProfile sets strictness and the similarity threshold, and persists the choice', () => {
      mockApi.get.mockReturnValue(of(mockCullingGroupsResponse));
      store.applyProfile(profilesResponse.profiles[1]);

      expect(store.selectedProfile()).toBe('wedding');
      expect(store.strictness()).toBe(35);
      expect(store.similarityThreshold()).toBe(90);
      expect(localStorage.getItem('facet_culling_profile')).toBe('wedding');
    });

    it('a manual strictness change after selecting a profile reverts the selection to custom', () => {
      mockApi.get.mockReturnValue(of(mockCullingGroupsResponse));
      store.applyProfile(profilesResponse.profiles[1]);

      component['onStrictnessChange'](60);

      expect(store.selectedProfile()).toBe('');
      expect(localStorage.getItem('facet_culling_profile')).toBeNull();
      expect(component['selectedProfileLabel']()).toBe('culling.profiles.custom');
    });

    it('a manual similarity threshold change after selecting a profile also reverts to custom', () => {
      mockApi.get.mockReturnValue(of(mockCullingGroupsResponse));
      store.applyProfile(profilesResponse.profiles[1]);

      component['onThresholdChange'](75);

      expect(store.selectedProfile()).toBe('');
    });

    it('restores a persisted profile id from localStorage on a fresh construction', async () => {
      localStorage.setItem('facet_culling_profile', 'wedding');
      mockApi.get.mockReturnValue(of(profilesResponse));
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          provideNativeDateAdapter(),
          BurstCullingComponent,
          { provide: ApiService, useValue: mockApi },
          { provide: MatSnackBar, useValue: mockSnackBar },
          { provide: I18nService, useValue: mockI18n },
          { provide: GalleryStore, useValue: { config: () => null } },
          { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
          { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
        ],
      });
      component = TestBed.runInInjectionContext(() => new BurstCullingComponent());
      store = component['cull'];

      expect(store.selectedProfile()).toBe('wedding');

      await store.loadCullProfiles();

      expect(store.strictness()).toBe(35);
      expect(store.similarityThreshold()).toBe(90);
    });
  });

  describe('skipGroup (pass with countdown)', () => {
    beforeEach(async () => {
      vi.useFakeTimers();
      await store.loadGroups();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('should add group to passingGroups with the configured countdown', () => {
      const group = store.groups()[0];
      store.skipGroup(group);

      expect(store.passingGroups().has('1_burst')).toBe(true);
      expect(store.passingGroups().get('1_burst')).toBe(7);
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should not add group to confirmedGroups immediately', () => {
      const group = store.groups()[0];
      store.skipGroup(group);

      expect(store.confirmedGroups().has('1_burst')).toBe(false);
    });

    it('should decrement countdown every second', () => {
      const group = store.groups()[0];
      store.skipGroup(group);

      vi.advanceTimersByTime(1000);
      expect(store.passingGroups().get('1_burst')).toBe(6);

      vi.advanceTimersByTime(1000);
      expect(store.passingGroups().get('1_burst')).toBe(5);
    });

    it('should hide group after the countdown elapses', () => {
      const group = store.groups()[0];
      store.skipGroup(group);

      vi.advanceTimersByTime(7000);

      // Group should be hidden (removed from visible groups)
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeUndefined();
      // But still in groups
      expect(store.groups().find(g => g.group_id === 1)).toBeDefined();
    });

    it('should remove group from passingGroups after timeout', () => {
      const group = store.groups()[0];
      store.skipGroup(group);

      vi.advanceTimersByTime(7000);

      expect(store.passingGroups().has('1_burst')).toBe(false);
    });
  });

  describe('cancelPass', () => {
    beforeEach(async () => {
      vi.useFakeTimers();
      await store.loadGroups();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('should remove group from passingGroups', () => {
      const group = store.groups()[0];
      store.skipGroup(group);
      expect(store.passingGroups().has('1_burst')).toBe(true);

      store.cancelPass(group);
      expect(store.passingGroups().has('1_burst')).toBe(false);
    });

    it('should keep group visible after cancel', () => {
      const group = store.groups()[0];
      store.skipGroup(group);

      vi.advanceTimersByTime(2000);
      store.cancelPass(group);

      // Group should still be visible
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeDefined();
    });

    it('should prevent auto-hide after cancel', () => {
      const group = store.groups()[0];
      store.skipGroup(group);

      vi.advanceTimersByTime(2000);
      store.cancelPass(group);

      // Advance past original timeout
      vi.advanceTimersByTime(5000);

      // Group should still be visible
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeDefined();
    });
  });

  describe('confirmAllRemaining', () => {
    beforeEach(async () => {
      await store.loadGroups();
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

    it('only confirms the groups the category filter leaves visible', async () => {
      store.groups.update(gs => gs.map((g, i) => ({ ...g, category: i === 0 ? 'portrait' : 'landscape' })));
      component['categoryFilter'].set('portrait');
      mockApi.post.mockClear();

      await component['confirmAllRemaining']();

      expect(mockApi.post).toHaveBeenCalledTimes(1);
      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({ group_id: 1 }));
      expect(store.confirmedGroups().has('2_similar')).toBe(false);
    });

    it('should mark all groups as confirmed', async () => {
      await component['confirmAllRemaining']();

      expect(store.confirmedGroups().has('1_burst')).toBe(true);
      expect(store.confirmedGroups().has('2_similar')).toBe(true);
    });

    it('should skip already confirmed groups', async () => {
      // Directly confirm group 1 (simulating a previously confirmed group)
      store.confirmedGroups.update(s => {
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

      expect(store.confirming()).toBe(false);
    });
  });

  describe('edited-look cull preview', () => {
    const styles = [{ name: 'velvia', label_key: 'culling.cull_style.styles.velvia' }];

    function build(config: Record<string, unknown> | null, isEdition = true): BurstCullingComponent {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          provideNativeDateAdapter(),
          BurstCullingComponent,
          { provide: ApiService, useValue: mockApi },
          { provide: MatSnackBar, useValue: mockSnackBar },
          { provide: I18nService, useValue: mockI18n },
          { provide: GalleryStore, useValue: { config: () => config } },
          { provide: AuthService, useValue: { isEdition: () => isEdition } },
          { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
        ],
      });
      return TestBed.runInInjectionContext(() => new BurstCullingComponent());
    }

    it('hides the style selector when no styles are configured', () => {
      component = build({ cull_styles: [] });
      store = component['cull'];
      expect(component['cullStyleCapable']()).toBe(false);
    });

    it('hides the style selector when the user lacks edition rights', () => {
      component = build({ cull_styles: styles }, false);
      store = component['cull'];
      expect(component['cullStyleCapable']()).toBe(false);
    });

    it('shows the style selector with configured styles and edition rights', () => {
      component = build({ cull_styles: styles });
      store = component['cull'];
      expect(component['cullStyleCapable']()).toBe(true);
      expect(component['cullStyles']()).toEqual(styles);
    });

    it('selecting a style updates the active style that drives the preview src swap', () => {
      component = build({ cull_styles: styles });
      store = component['cull'];
      expect(component['activeStyle']()).toBe('');
      component['selectCullStyle']('velvia');
      expect(component['activeStyle']()).toBe('velvia');
    });

    it('selecting Original clears the active style back to the flat frame', () => {
      component = build({ cull_styles: styles });
      store = component['cull'];
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
      store.groups.set([grp]);
      component['lightboxGroupId'].set(store.groupKey(grp));
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
      store.groups.set([wildlifeGroup]);
      component['lightboxGroupId'].set(store.groupKey(wildlifeGroup));
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

  describe('face close-up size slider (persisted browser preference)', () => {
    const freshComponent = (): BurstCullingComponent => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          provideNativeDateAdapter(),
          BurstCullingComponent,
          { provide: ApiService, useValue: mockApi },
          { provide: MatSnackBar, useValue: mockSnackBar },
          { provide: I18nService, useValue: mockI18n },
          { provide: GalleryStore, useValue: { config: () => null } },
          { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
          { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
        ],
      });
      return TestBed.runInInjectionContext(() => new BurstCullingComponent());
    };

    it('defaults to 112 when nothing is stored', () => {
      expect(component['faceSize']()).toBe(112);
    });

    it('restores a valid stored value', () => {
      localStorage.setItem('facet_culling_face_size', '192');

      expect(freshComponent()['faceSize']()).toBe(192);
    });

    it.each(['abc', '9999', '70'])('falls back to the default for an invalid stored value (%s)', (stored) => {
      localStorage.setItem('facet_culling_face_size', stored);

      expect(freshComponent()['faceSize']()).toBe(112);
    });

    it('onFaceSizeChange updates the signal and writes localStorage', () => {
      component['onFaceSizeChange'](160);

      expect(component['faceSize']()).toBe(160);
      expect(localStorage.getItem('facet_culling_face_size')).toBe('160');
    });
  });

  describe('face-strip slider focus release (pointer drag/click must not eat arrow-key nav)', () => {
    beforeEach(async () => {
      await store.loadGroups();
    });

    it('releaseSliderFocus() (bound to a slider thumb\'s dragEnd) refocuses the darkroom dialog', () => {
      const mockEl = { focus: vi.fn() };
      Object.defineProperty(component, 'lightboxDialog', { value: () => ({ nativeElement: mockEl }), writable: true, configurable: true });

      component['releaseSliderFocus']();

      expect(mockEl.focus).toHaveBeenCalledTimes(1);
    });

    it('after a pointer interaction releases focus, ArrowRight advances lightboxIndex again', () => {
      const mockEl = { focus: vi.fn() };
      Object.defineProperty(component, 'lightboxDialog', { value: () => ({ nativeElement: mockEl }), writable: true, configurable: true });
      component['openLightbox'](store.groups()[0], 0);
      expect(component['lightboxIndex']()).toBe(0);

      // Simulate the slider's dragEnd firing after a mouse drag/click.
      component['releaseSliderFocus']();
      component['onArrowRight'](new KeyboardEvent('keydown', { key: 'ArrowRight' }));

      expect(mockEl.focus).toHaveBeenCalled();
      expect(component['lightboxIndex']()).toBe(1);
    });

    it('a keyboard-only interaction (no pointer event, no dragEnd) never touches focus', () => {
      const mockEl = { focus: vi.fn() };
      Object.defineProperty(component, 'lightboxDialog', { value: () => ({ nativeElement: mockEl }), writable: true, configurable: true });
      component['openLightbox'](store.groups()[0], 0);

      // Tab onto the slider, then adjust it with the keyboard: valueChange fires,
      // but releaseSliderFocus() is only wired to dragEnd, so it must stay uncalled.
      component['onFaceSizeChange'](component['faceSize']() + component['faceSizeStepPx']);

      expect(mockEl.focus).not.toHaveBeenCalled();
    });
  });

  describe('key subject (darkroom zoom target + key-person badge)', () => {
    const grp = {
      group_id: 9, type: 'burst' as const, reason: '', best_path: '/k1.jpg', count: 2,
      photos: [
        { path: '/k1.jpg', filename: 'k1.jpg', aggregate: 8, aesthetic: 7, tech_sharpness: 6, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8 },
        { path: '/k2.jpg', filename: 'k2.jpg', aggregate: 7, aesthetic: 6, tech_sharpness: 5, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7 },
      ],
    };
    // The frame is 4000x3000 and the key face sits at three-quarters across,
    // one quarter down — deliberately off-centre, so a centred zoom cannot pass.
    const keyPerson = (overrides: Record<string, unknown> = {}) => ({
      path: '/k1.jpg', kind: 'person', coordinate_space: 'normalized_frame_xyxy',
      image_width: 4000, image_height: 3000, bbox: [0.7, 0.2, 0.8, 0.3], center: [0.75, 0.25],
      area_ratio: 0.01, centrality: 0.5, score: 0.9,
      face_id: 11, face_index: 0, person_id: 3, person_name: 'Alice',
      subject_sharpness: null, subject_prominence: null,
      subject_placement: null, bg_separation: null, ...overrides,
    });
    const unresolved = (path: string) => keyPerson({
      path, kind: 'none', bbox: null, center: null, face_id: null,
      person_id: null, person_name: null, score: null,
    });
    const facesByPath = {
      '/k1.jpg': [{ id: 11, face_index: 0, confidence: 0.9 }, { id: 12, face_index: 1, confidence: 0.8 }],
    };
    const PANE = { width: 800, height: 600 };
    const flush = () => new Promise(resolve => setTimeout(resolve, 0));

    const routePost = (keySubjects: Record<string, unknown>) => {
      mockApi.post.mockImplementation((url: string) => {
        if (url === '/culling-group/faces') return of({ faces_by_path: facesByPath });
        if (url === '/photos/key_subjects') return of({ key_subjects_by_path: keySubjects });
        return of({});
      });
    };

    /** Open the darkroom in a real view — the bindings under test are template ones. */
    const renderDarkroom = async (keySubjects: Record<string, unknown>) => {
      // jsdom ships no scrollIntoView, which the rendered group list calls.
      const scrollIntoView = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = vi.fn();
      routePost(keySubjects);
      const fixture = TestBed.createComponent(BurstCullingComponent);
      const rendered = fixture.componentInstance as any;
      // Let this instance's own initial load land before seeding the darkroom,
      // or it would replace the seeded group and close it again.
      await flush();
      rendered['cull'].groups.set([grp]);
      rendered['openLightbox'](grp, 0);
      await flush();
      fixture.detectChanges();
      const teardown = () => {
        fixture.destroy();
        Element.prototype.scrollIntoView = scrollIntoView;
      };
      return { fixture, rendered, teardown };
    };

    /** The browser-less env reports a zero-size pane and an unloaded image. */
    const measurePane = (fixture: ComponentFixture<BurstCullingComponent>) => {
      const el: HTMLElement = fixture.debugElement.query(By.directive(SyncedZoomComponent)).nativeElement;
      el.getBoundingClientRect = () => ({ ...PANE, x: 0, y: 0, top: 0, left: 0,
        right: PANE.width, bottom: PANE.height, toJSON: () => ({}) }) as DOMRect;
      const img = el.querySelector('img')!;
      Object.defineProperty(img, 'naturalWidth', { value: 4000, configurable: true });
      Object.defineProperty(img, 'naturalHeight', { value: 3000, configurable: true });
    };

    const keyPills = (fixture: ComponentFixture<BurstCullingComponent>) =>
      [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')]
        .filter(el => el.className.includes('bg-amber-500/90'));

    const zKey = () => ({ preventDefault: vi.fn(), target: document.body }) as unknown as Event;

    it('resolves one key subject per frame in a single batch call', async () => {
      routePost({ '/k1.jpg': keyPerson(), '/k2.jpg': unresolved('/k2.jpg') });

      await (component as any).loadCloseupsForGroup(grp);

      expect(mockApi.post).toHaveBeenCalledWith('/photos/key_subjects', { paths: ['/k1.jpg', '/k2.jpg'] });
      expect(mockApi.post.mock.calls.filter(c => c[0] === '/photos/key_subjects')).toHaveLength(1);
      expect(component['keySubjectMap']().size).toBe(2);
      expect(component['keySubjectMap']().get('/k1.jpg')?.face_id).toBe(11);
    });

    // Unlike the subject crops, which are a strip only non-face groups get, the
    // key subject is the zoom target and a face group wants it just as much.
    it('resolves them for a face group, which never loads subject crops', async () => {
      routePost({ '/k1.jpg': keyPerson(), '/k2.jpg': unresolved('/k2.jpg') });

      await (component as any).loadCloseupsForGroup(grp);

      expect(mockApi.post).not.toHaveBeenCalledWith('/culling-group/subjects', expect.anything());
      expect(component['keySubjectMap']().get('/k1.jpg')?.kind).toBe('person');
    });

    it('records an unresolved entry on failure, so a broken call is not retried', async () => {
      mockApi.post.mockImplementation((url: string) =>
        url === '/photos/key_subjects' ? throwError(() => new Error('boom')) : of({ faces_by_path: {} }));

      await (component as any).loadKeySubjectsForGroup(grp);
      expect(component['keySubjectMap']().get('/k1.jpg')?.kind).toBe('none');

      mockApi.post.mockClear();
      await (component as any).loadKeySubjectsForGroup(grp);

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    // The whole point of the feature: Z lands the loupe on the key face, not on
    // the middle of the frame. Delegating to the pane is what makes that work —
    // the pixel math needs the pane rect, which only the pane has.
    it('Z centres the single-view frame on its key subject', async () => {
      const { fixture, rendered, teardown } = await renderDarkroom({ '/k1.jpg': keyPerson() });
      measurePane(fixture);

      rendered['onZoomToggle'](zKey());

      expect(rendered['zoom']()).toEqual({ scale: 2, tx: -400, ty: 300 });
      // The pane reads the shared zoom as an input, so the toggle only sees the
      // new scale once change detection has pushed it back down.
      fixture.detectChanges();
      rendered['onZoomToggle'](zKey());
      expect(rendered['zoom']()).toEqual({ scale: 1, tx: 0, ty: 0 });
      teardown();
    });

    it('Z stays centred for an unresolved frame', async () => {
      const { fixture, rendered, teardown } = await renderDarkroom({ '/k1.jpg': unresolved('/k1.jpg') });
      measurePane(fixture);

      rendered['onZoomToggle'](zKey());

      expect(rendered['zoom']()).toEqual({ scale: 2, tx: 0, ty: 0 });
      teardown();
    });

    it('Z keeps the compare grid centred, having no single frame to aim at', async () => {
      const { fixture, rendered, teardown } = await renderDarkroom({ '/k1.jpg': keyPerson() });
      rendered['setCompareMode']('2up');
      fixture.detectChanges();
      measurePane(fixture);

      rendered['onZoomToggle'](zKey());

      expect(rendered['zoom']()).toEqual({ scale: 2, tx: 0, ty: 0 });
      teardown();
    });

    it('badges the key face with its person name, and only that face', async () => {
      const { fixture, teardown } = await renderDarkroom({ '/k1.jpg': keyPerson() });

      const pills = keyPills(fixture);

      expect(pills).toHaveLength(1);
      // The badge is a focusable button now (keyboard/AT users could never
      // trigger a matTooltip on a bare div), and its sr-only text folds the
      // tooltip's explanation in rather than leaving it reachable only on
      // hover. The screen-reader text and the name must not run together (&ngsp;).
      expect(pills[0].tagName).toBe('BUTTON');
      expect(pills[0].textContent?.trim())
        .toBe('culling.key_person: culling.key_person_tooltip Alice');
      teardown();
    });

    it('badges nothing for an unresolved frame or a nameless cluster', async () => {
      const nameless = await renderDarkroom({ '/k1.jpg': keyPerson({ person_id: 4, person_name: null }) });
      expect(keyPills(nameless.fixture)).toHaveLength(0);
      nameless.teardown();

      const none = await renderDarkroom({ '/k1.jpg': unresolved('/k1.jpg') });
      expect(keyPills(none.fixture)).toHaveLength(0);
      none.teardown();
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

    const seed = () => store.groups.set([structuredClone(panoramaGroup)] as never);

    it('suppressing a set posts the correction for every frame', async () => {
      seed();

      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(store.groups()[0]);

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/override_sequence', {
        paths: ['/p0.jpg', '/p1.jpg', '/p2.jpg'],
        kind: null,
      });
    });

    it('marks the frames pending so the group reads as corrected', async () => {
      seed();

      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(store.groups()[0]);

      expect(store.groups()[0].photos.map(p => p.sequence_override))
        .toEqual(['suppressed', 'suppressed', 'suppressed']);
      expect(store.pendingCorrectionKeys().size).toBe(1);
    });

    it('a relabel records the forced kind', async () => {
      seed();

      await (component as never as { correctSequence: (g: unknown, k: string) => Promise<void> })
        .correctSequence(store.groups()[0], 'hdr_panorama');

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/override_sequence', {
        paths: ['/p0.jpg', '/p1.jpg', '/p2.jpg'],
        kind: 'hdr_panorama',
      });
      expect(store.groups()[0].photos[0].sequence_override).toBe('hdr_panorama');
    });

    it('leaves the group in the feed — the detector has not run yet', async () => {
      seed();

      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(store.groups()[0]);

      expect(store.groups()).toHaveLength(1);
      expect(store.hiddenGroups()).not.toContain('7_panorama');
    });

    it('a failed correction marks nothing pending', async () => {
      seed();
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('nope')));

      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(store.groups()[0]);

      expect(store.groups()[0].photos[0].sequence_override).toBeUndefined();
      expect(store.pendingCorrectionKeys().size).toBe(0);
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('dropping a correction clears it server-side and locally', async () => {
      seed();
      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(store.groups()[0]);

      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(store.groups()[0]);

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/clear_sequence_override', {
        paths: ['/p0.jpg', '/p1.jpg', '/p2.jpg'],
      });
      expect(store.pendingCorrectionKeys().size).toBe(0);
    });

    it('an uncorrected feed offers no re-run', () => {
      seed();

      expect(store.pendingCorrectionKeys().size).toBe(0);
    });

    it('dropping an already-applied correction still asks for a re-run', async () => {
      seed();
      // Simulate a completed detection run: the override is no longer pending.
      store.groups()[0].photos.forEach(p => {
        (p as { sequence_override?: string; sequence_override_pending?: number })
          .sequence_override = 'suppressed';
        (p as { sequence_override_pending?: number }).sequence_override_pending = 0;
      });

      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(store.groups()[0]);

      expect(store.pendingCorrectionKeys().size).toBe(0);
      expect(store.rerunNeeded()).toBe(1);
    });

    it('dropping a still-pending correction needs no re-run', async () => {
      seed();
      await (component as never as { correctSequence: (g: unknown) => Promise<void> })
        .correctSequence(store.groups()[0]);
      expect(store.pendingCorrectionKeys().size).toBe(1);

      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(store.groups()[0]);

      expect(store.rerunNeeded()).toBe(0);
    });

    it('a successful re-run clears the applied-drop counter', async () => {
      seed();
      store.groups()[0].photos.forEach(p => {
        (p as { sequence_override?: string; sequence_override_pending?: number })
          .sequence_override = 'suppressed';
        (p as { sequence_override_pending?: number }).sequence_override_pending = 0;
      });
      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(store.groups()[0]);
      expect(store.rerunNeeded()).toBe(1);

      mockApi.post.mockReturnValueOnce(of({}));
      mockApi.get.mockReturnValueOnce(of({ running: false, kind: null, exit_code: 0 }));
      await (component as never as { rerunDetection: () => Promise<void> }).rerunDetection();
      await (component as never as { ['pollDetection']: () => Promise<void> })['pollDetection']();

      expect(store.rerunNeeded()).toBe(0);
      (component as never as { stopDetectionPolling: () => void }).stopDetectionPolling();
    });

    it('re-correcting a group after dropping its applied override counts it once', async () => {
      seed();
      store.groups()[0].photos.forEach(p => {
        (p as { sequence_override?: string; sequence_override_pending?: number })
          .sequence_override = 'suppressed';
        (p as { sequence_override_pending?: number }).sequence_override_pending = 0;
      });

      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(store.groups()[0]);
      expect(store.rerunNeeded()).toBe(1);

      await (component as never as { correctSequence: (g: unknown, k?: string) => Promise<void> })
        .correctSequence(store.groups()[0], 'hdr_panorama');

      expect(store.rerunNeeded()).toBe(1);
    });

    it('dropping an applied override, re-marking, then dropping again still needs one re-run', async () => {
      seed();
      store.groups()[0].photos.forEach(p => {
        (p as { sequence_override?: string; sequence_override_pending?: number })
          .sequence_override = 'suppressed';
        (p as { sequence_override_pending?: number }).sequence_override_pending = 0;
      });

      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(store.groups()[0]);
      expect(store.rerunNeeded()).toBe(1);

      await (component as never as { correctSequence: (g: unknown, k?: string) => Promise<void> })
        .correctSequence(store.groups()[0], 'hdr_panorama');
      expect(store.rerunNeeded()).toBe(1);

      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(store.groups()[0]);

      expect(store.rerunNeeded()).toBe(1);
    });

    it('dropping an applied override, re-marking, then undoing the re-mark still needs one re-run', async () => {
      seed();
      store.groups()[0].photos.forEach(p => {
        (p as { sequence_override?: string; sequence_override_pending?: number })
          .sequence_override = 'suppressed';
        (p as { sequence_override_pending?: number }).sequence_override_pending = 0;
      });

      await (component as never as { clearCorrection: (g: unknown) => Promise<void> })
        .clearCorrection(store.groups()[0]);
      expect(store.rerunNeeded()).toBe(1);

      const undoAction = new Subject<void>();
      mockSnackBar.open.mockReturnValueOnce({
        onAction: () => undoAction, afterDismissed: () => new Subject<void>(),
      });
      await (component as never as { correctSequence: (g: unknown, k?: string) => Promise<void> })
        .correctSequence(store.groups()[0], 'hdr_panorama');
      expect(store.rerunNeeded()).toBe(1);

      undoAction.next();
      await new Promise(resolve => setTimeout(resolve, 0));

      expect(store.rerunNeeded()).toBe(1);
    });

    it('a bracket correction failing with a 400 shows the ladder-specific message', async () => {
      seed();
      mockApi.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 400 })));

      await (component as never as { correctSequence: (g: unknown, k?: string) => Promise<void> })
        .correctSequence(store.groups()[0], 'bracket');

      expect(mockSnackBar.open).toHaveBeenCalledWith(
        'culling.bracket.not_a_ladder', '', expect.anything());
    });

    it('a panorama correction failing with the same 400 keeps the generic message', async () => {
      seed();
      mockApi.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 400 })));

      await (component as never as { correctSequence: (g: unknown, k?: string) => Promise<void> })
        .correctSequence(store.groups()[0], 'panorama');

      expect(mockSnackBar.open).toHaveBeenCalledWith(
        'culling.panorama.correction_failed', '', expect.anything());
    });
  });

  describe('bracket correction — darkroom list surfaces', () => {
    const burstGroup = {
      group_id: 11,
      type: 'burst' as const,
      reason: '2 frames',
      best_path: '/b0.jpg',
      count: 2,
      photos: [0, 1].map(i => ({
        path: `/b${i}.jpg`, filename: `b${i}.jpg`, aggregate: 5, aesthetic: 5,
        tech_sharpness: 5, is_blink: 0, is_burst_lead: i === 0 ? 1 : 0, date_taken: '2025-04-15',
        burst_score: 5,
      })),
    };
    const bracketGroup = {
      group_id: 12,
      type: 'bracket' as const,
      reason: '2 frames',
      sequence_kind: 'bracket',
      best_path: '/k0.jpg',
      count: 2,
      photos: [0, 1].map(i => ({
        path: `/k${i}.jpg`, filename: `k${i}.jpg`, aggregate: 5, aesthetic: 5,
        tech_sharpness: 5, is_blink: 0, is_burst_lead: 0, date_taken: '2025-04-15',
        burst_score: 5, sequence_kind: 'bracket',
        sequence_override: 'bracket', sequence_override_pending: 0,
      })),
    };

    const renderList = async (groups: unknown[]) => {
      const scrollIntoView = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = vi.fn();
      const fixture = TestBed.createComponent(BurstCullingComponent);
      const rendered = fixture.componentInstance as any;
      await new Promise(resolve => setTimeout(resolve, 0));
      rendered['cull'].groups.set(groups);
      rendered['cull'].loading.set(false);
      fixture.detectChanges();
      return {
        fixture,
        teardown: () => { fixture.destroy(); Element.prototype.scrollIntoView = scrollIntoView; },
      };
    };

    const byAriaLabel = (fixture: ComponentFixture<BurstCullingComponent>, label: string) =>
      [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')]
        .find(el => el.getAttribute('aria-label') === label);

    it('offers "Mark as bracket" for a plain burst group, with the panorama-trigger accessible name', async () => {
      const { fixture, teardown } = await renderList([structuredClone(burstGroup)]);

      // The bracket-only trigger's tooltip stays a whole sentence, but its
      // aria-label mirrors the panorama and bracket-clear triggers' short name.
      expect(byAriaLabel(fixture, 'culling.panorama.correct')).toBeTruthy();
      teardown();
    });

    it('offers no bracket-only trigger for an already-panorama group', async () => {
      const panoramaGroup = {
        ...structuredClone(burstGroup), group_id: 13, sequence_kind: 'panorama',
        photos: structuredClone(burstGroup).photos.map(p => ({ ...p, sequence_kind: 'panorama' })),
      };
      const { fixture, teardown } = await renderList([panoramaGroup]);

      // Only the panorama-kind trigger renders here (same aria-label), so this
      // group must show exactly one such button, not two.
      const matches = [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')]
        .filter(el => el.getAttribute('aria-label') === 'culling.panorama.correct');
      expect(matches).toHaveLength(1);
      teardown();
    });

    // group.sequence_kind is only set when EVERY frame shares one sequence, so
    // a group mixing a bracket frame with unclaimed frames has no sequence_kind
    // of its own -- `!group.sequence_kind` alone would wrongly offer "mark as
    // bracket" here and let the user fold the already-classified frame into a
    // second, competing set.
    it('offers no bracket-only trigger for a mixed group with a partial bracket frame', async () => {
      const mixedGroup = {
        ...structuredClone(burstGroup), group_id: 14, sequence_kind: null,
        photos: [
          { ...structuredClone(burstGroup).photos[0], sequence_kind: 'bracket' },
          structuredClone(burstGroup).photos[1],
        ],
      };
      const { fixture, teardown } = await renderList([mixedGroup]);

      expect(byAriaLabel(fixture, 'culling.panorama.correct')).toBeFalsy();
      teardown();
    });

    it('offers "Clear correction" for a bracket-forced group carrying an override', async () => {
      const { fixture, teardown } = await renderList([structuredClone(bracketGroup)]);

      expect(byAriaLabel(fixture, 'culling.panorama.correct')).toBeTruthy();
      teardown();
    });

    it('renders the pending/corrected chip for a plain burst group with a pending bracket override', async () => {
      const pendingBurst = structuredClone(burstGroup);
      pendingBurst.photos[0] = {
        ...pendingBurst.photos[0], sequence_override: 'bracket', sequence_override_pending: 1,
      } as never;
      const { fixture, teardown } = await renderList([pendingBurst]);

      expect((fixture.nativeElement as HTMLElement).textContent).toContain('culling.panorama.pending');
      teardown();
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
      dry_run: true, preview: [], next_cursor: null, plan_digest: 'digest',
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
      store.cullProfiles.set(profiles);
      mockApi.post = vi.fn(() => of(preview));
    });

    it('preselects the suggested preset when the user has chosen none', async () => {
      routeGet(suggestion('wedding'));

      await store.applySuggestedProfile();

      expect(mockApi.get).toHaveBeenCalledWith('/culling/suggest_profile', {});
      expect(store.selectedProfile()).toBe('wedding');
      expect(store.strictness()).toBe(35);
      expect(component['suggestedProfileActive']()).toBe(true);
    });

    // A suggestion is not a decision: it must not become the preset the next
    // session restores, which only an explicit click may do.
    it('does not persist the preset it suggested', async () => {
      routeGet(suggestion('wedding'));

      await store.applySuggestedProfile();

      expect(localStorage.getItem('facet_culling_profile')).toBeNull();
    });

    it('never overrides a preset the user picked, and does not even ask', async () => {
      store.applyProfile(profiles[1]);
      routeGet(suggestion('wildlife'));

      await store.applySuggestedProfile();

      expect(suggestCalls()).toHaveLength(0);
      expect(store.selectedProfile()).toBe('wedding');
      expect(component['suggestedProfileActive']()).toBe(false);
    });

    it('a hand-moved knob also settles the preset for the session', async () => {
      component['onStrictnessChange'](80);
      routeGet(suggestion('wedding'));

      await store.applySuggestedProfile();

      expect(suggestCalls()).toHaveLength(0);
      expect(store.strictness()).toBe(80);
    });

    it('applies nothing when the scope argues for no preset', async () => {
      routeGet(suggestion(null));

      await store.applySuggestedProfile();

      expect(store.selectedProfile()).toBe('');
      expect(component['suggestedProfileActive']()).toBe(false);
    });

    it('applies nothing when the suggested preset is not configured', async () => {
      routeGet(suggestion('sports'));

      await store.applySuggestedProfile();

      expect(store.selectedProfile()).toBe('');
    });

    it('asks once per scope and reuses the answer', async () => {
      routeGet(suggestion('wedding'));

      await store.applySuggestedProfile();
      await store.applySuggestedProfile();

      expect(suggestCalls()).toHaveLength(1);
    });

    it('opens the dialog without waiting for the suggestion', async () => {
      // The suggestion never answers; the preview must land regardless.
      mockApi.get = vi.fn((url: string) =>
        url === '/culling/suggest_profile' ? new Subject() : of(mockCullingGroupsResponse));

      await store.openAutoCull();

      expect(suggestCalls()).toHaveLength(1);
      expect(store.autoCullPreview()).toEqual(preview);
      expect(store.selectedProfile()).toBe('');
    });

    it('a suggestion landing on the open dialog re-runs the preview under its knobs', async () => {
      routeGet(suggestion('wedding'));
      store.autoCullPreview.set(preview);

      await store.applySuggestedProfile();

      expect(mockApi.post).toHaveBeenCalledWith('/culling/auto', expect.objectContaining({
        dry_run: true, profile: 'wedding', strictness: 35,
      }));
    });

    // Renumbering "Reject N photos" under an open dialog without saying why is a
    // silent change to a destructive confirmation.
    it('names the preset when a landing suggestion renumbers an open dialog', async () => {
      routeGet(suggestion('wedding'));
      store.autoCullPreview.set(preview);

      await store.applySuggestedProfile();

      expect(store.autoCullSuggestionNotice()).toBe('culling.profiles.wedding');
    });

    // The third way that re-run can end. A failed one leaves the counts on
    // screen exactly as they were, so naming the preset would claim a
    // recomputation that never happened — the error snackbar is the only thing
    // that has anything to say.
    it('raises no notice when the re-run behind a landing suggestion fails', async () => {
      routeGet(suggestion('wedding'));
      store.autoCullPreview.set(preview);
      mockApi.post = vi.fn(() => throwError(() => new Error('boom')));

      await store.applySuggestedProfile();

      expect(store.autoCullSuggestionNotice()).toBeNull();
      expect(store.autoCullPreview()).toEqual(preview);
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('raises no notice when the dialog was not open', async () => {
      routeGet(suggestion('wedding'));

      await store.applySuggestedProfile();

      expect(store.autoCullSuggestionNotice()).toBeNull();
    });

    it('clears a stale notice when the dialog is opened again', async () => {
      routeGet(suggestion(null));
      store.autoCullSuggestionNotice.set('culling.profiles.wildlife');

      await store.openAutoCull();

      expect(store.autoCullSuggestionNotice()).toBeNull();
    });

    /**
     * The race the confirm dialog cannot afford to lose.
     *
     * The suggestion is fetched alongside the dry run, so it can apply a preset —
     * moving strictness and the profile — at any point between the dry run's
     * request and its answer. Whatever the ordering, the parameters Apply sends
     * must be the ones the counts on screen were computed from; the dialog is a
     * confirmation, and confirming counts under other knobs is not one.
     */
    describe('a suggestion racing the dry run it was fetched with', () => {
      let suggestReply: Subject<unknown>;
      let posts: Subject<unknown>[];
      let bodies: Record<string, unknown>[];
      const flush = () => new Promise(resolve => setTimeout(resolve, 0));

      beforeEach(() => {
        suggestReply = new Subject<unknown>();
        posts = [];
        bodies = [];
        mockApi.get = vi.fn((url: string) =>
          url === '/culling/suggest_profile' ? suggestReply : of(mockCullingGroupsResponse));
        mockApi.post = vi.fn((_url: string, body: Record<string, unknown>) => {
          bodies.push(body);
          const answer = new Subject<unknown>();
          posts.push(answer);
          return answer;
        });
      });

      /** The dry run behind the counts on screen, as the dialog displays them. */
      const displayedBody = () => bodies[bodies.length - 2];

      // Ordering one: the suggestion lands while the dry run is still in flight.
      // The dialog is not open yet, so the old re-run condition never fired and
      // the preview opened on pre-suggestion counts under post-suggestion knobs.
      it('opens on the suggested knobs when the suggestion lands before the preview', async () => {
        void store.openAutoCull();
        await flush();
        expect(bodies).toHaveLength(1);
        expect(bodies[0]).toMatchObject({ strictness: 100 });

        suggestReply.next(suggestion('wedding'));
        await flush();
        // The superseded run answers late and must not become the preview.
        posts[0].next({ ...preview, kept: 99, rejected: 99 });
        posts[1].next(preview);
        await flush();

        expect(bodies).toHaveLength(2);
        expect(bodies[1]).toMatchObject({ strictness: 35, profile: 'wedding' });
        expect(store.autoCullPreview()).toEqual(preview);
        expect(store.autoCullSuggestionNotice()).toBe('culling.profiles.wedding');
      });

      it('applies exactly the body the displayed counts came from, after the re-run', async () => {
        void store.openAutoCull();
        await flush();
        suggestReply.next(suggestion('wedding'));
        await flush();
        posts[0].next({ ...preview, kept: 99, rejected: 99 });
        posts[1].next(preview);
        await flush();

        void component['confirmAutoCull']();
        posts[2].next({ ...preview, dry_run: false });
        await flush();

        expect(bodies[2]).toEqual({ ...displayedBody(), dry_run: false, highlights_album: '' });
        expect(bodies[2]).toMatchObject({ strictness: 35, profile: 'wedding' });
      });

      // Ordering two: Apply is clicked while the suggestion's re-run is still in
      // flight, so the counts on screen are still the first run's. Those are the
      // ones the user agreed to, so those are the knobs that run.
      it('applies the displayed run when Apply is clicked before the re-run lands', async () => {
        void store.openAutoCull();
        await flush();
        posts[0].next(preview);
        await flush();
        expect(store.autoCullPreview()).toEqual(preview);

        suggestReply.next(suggestion('wedding'));
        await flush();
        expect(bodies).toHaveLength(2);

        void component['confirmAutoCull']();
        posts[2].next({ ...preview, dry_run: false });
        await flush();

        expect(bodies[2]).toEqual({ ...bodies[0], dry_run: false, highlights_album: '' });
        expect(bodies[2]).toMatchObject({ strictness: 100 });
        expect(bodies[2]['profile']).toBeUndefined();
      });

      it('keeps the Highlights checkbox the dialog\'s own decision', async () => {
        void store.openAutoCull();
        await flush();
        posts[0].next(preview);
        await flush();
        store.autoCullHighlights.set(true);

        void component['confirmAutoCull']();
        posts[1].next({ ...preview, dry_run: false });
        await flush();

        expect(bodies[1]['highlights_album']).toBe(bodies[0]['highlights_album']);
        expect(String(bodies[1]['highlights_album'])).not.toBe('');
      });
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
    let renderPooledPeaking: Mock;
    const flush = () => new Promise(resolve => setTimeout(resolve, 0));

    const openDarkroom = (index = 0) => {
      store.groups.set([grp]);
      component['lightboxGroupId'].set(store.groupKey(grp));
      component['lightboxIndex'].set(index);
    };
    /** The single pane reports its render as loaded, which peaking waits for. */
    const markSharp = () => {
      const photo = component['lightboxGroup']()?.photos[component['lightboxIndex']()];
      if (photo) component['sharpPath'].set(photo.path);
    };
    /** Run the overlay effects and let their async raster work settle. */
    const settle = async () => {
      markSharp();
      TestBed.tick();
      await flush();
    };

    beforeEach(() => {
      // jsdom has no 2D canvas, so the raster pipeline is replaced at its seam.
      renderPeaking = vi.fn((src: string) => Promise.resolve(`overlay:${src}`));
      renderPooledPeaking = vi.fn((srcs: string[]) =>
        Promise.resolve(new Map(srcs.map(src => [src, `pooled:${src}`]))));
      vi.spyOn(component as any, 'renderPeaking').mockImplementation(renderPeaking as never);
      vi.spyOn(component as any, 'renderPooledPeaking').mockImplementation(renderPooledPeaking as never);
      vi.spyOn(component as any, 'measureFrame').mockResolvedValue({ w: 6000, h: 4000 });
    });

    it('builds an overlay for the displayed frame once peaking is on', async () => {
      openDarkroom();
      component['peakingActive'].set(true);

      await settle();

      expect(component['peakingOverlays']().get('/f1.jpg')).toContain('size=1920');
      expect(component['peakingOverlays']().size).toBe(1);
    });

    it('measures fit view at the tuned field and the full-resolution swap at full size', async () => {
      openDarkroom();
      component['peakingActive'].set(true);
      await settle();
      expect(renderPeaking.mock.calls.at(-1)?.[1]).toBe(640);

      component['zoom'].set({ scale: 2, tx: 0, ty: 0 });
      await settle();
      expect(renderPeaking.mock.calls.at(-1)?.[1]).toBeUndefined();

      component['setCompareMode']('2up');
      component['zoom'].set({ scale: 1, tx: 0, ty: 0 });
      await settle();
      expect(renderPooledPeaking.mock.calls.at(-1)?.[1]).toBe(640);
    });

    it('keeps the edge maps of frames already seen while a step waits for the sharp render', async () => {
      openDarkroom(0);
      component['peakingActive'].set(true);
      await settle();
      expect(renderPeaking).toHaveBeenCalledTimes(1);

      // Step on, passing through the awaiting-sharp state (no markSharp yet).
      component['lightboxIndex'].set(1);
      TestBed.tick();
      await flush();
      expect(component['peakingOverlays']().size).toBe(0);
      await settle();
      expect(renderPeaking).toHaveBeenCalledTimes(2);

      // Step back: awaiting again, then sharp. The first frame is not re-convolved.
      component['lightboxIndex'].set(0);
      TestBed.tick();
      await flush();
      expect(component['peakingOverlays']().size).toBe(0);
      await settle();

      expect(renderPeaking).toHaveBeenCalledTimes(2);
      expect(component['peakingOverlays']().get('/f1.jpg')).toBeDefined();
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

    // Side by side, the frames are read against each other, so one threshold has
    // to have painted them both -- which per-frame passes cannot do.
    it('paints the panes of a compare grid in one pooled pass', async () => {
      openDarkroom();
      component['peakingActive'].set(true);
      component['setCompareMode']('2up');

      await settle();

      expect(renderPeaking).not.toHaveBeenCalled();
      expect(renderPooledPeaking).toHaveBeenCalledTimes(1);
      expect(renderPooledPeaking.mock.calls[0][0]).toHaveLength(2);
      expect(component['peakingOverlays']().get('/f1.jpg')).toContain('pooled:');
    });

    // Stepping the focus inside a pair shows the very same two frames, so the
    // pooled pass must be reused rather than re-convolved on every arrow key.
    it('reuses a pooled pass while the same frames stay on screen', async () => {
      openDarkroom();
      component['peakingActive'].set(true);
      component['setCompareMode']('2up');
      await settle();

      component['lightboxIndex'].set(1);
      await settle();

      expect(renderPooledPeaking).toHaveBeenCalledTimes(1);
      expect(component['peakingOverlays']().size).toBe(2);
    });

    // A pooled overlay is only the answer for the set it was pooled over: the
    // same frame paired with a different one is a different threshold.
    it('does not hand a pooled overlay back for a different pairing', async () => {
      const trio = {
        ...grp,
        photos: [...grp.photos, { ...grp.photos[0], path: '/f3.jpg', filename: 'f3.jpg' }],
      };
      store.groups.set([trio]);
      component['lightboxGroupId'].set(store.groupKey(trio));
      component['peakingActive'].set(true);
      component['setCompareMode']('2up');
      await settle();

      component['lightboxIndex'].set(1);
      await settle();
      component['lightboxIndex'].set(0);
      await settle();

      expect(renderPooledPeaking).toHaveBeenCalledTimes(3);
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
      store.groups.set([long]);
      component['lightboxGroupId'].set(store.groupKey(long));
      component['peakingActive'].set(true);
      for (let i = 0; i < long.photos.length; i++) {
        component['lightboxIndex'].set(i);
        await settle();
      }

      expect(renderPeaking).toHaveBeenCalledTimes(12);
      expect(component['peakingCache'].size).toBe(8);
    });

    // A pass is one await away from publishing; the toggle that switched peaking
    // off has to invalidate it, or the overlays come back on their own.
    it('publishes nothing from a pass still running when peaking is switched off', async () => {
      let land!: (url: string) => void;
      renderPeaking.mockImplementation(() => new Promise<string>(resolve => { land = resolve; }));
      openDarkroom();
      component['peakingActive'].set(true);
      await settle();
      expect(renderPeaking).toHaveBeenCalledTimes(1);
      expect(component['peakingOverlays']().size).toBe(0);

      component['peakingActive'].set(false);
      await settle();
      land('data:image/png;base64,late');
      await settle();

      expect(component['peakingOverlays']().size).toBe(0);
    });

    // Same guard, the other way the frames leave the screen.
    it('publishes nothing from a pass still running when the darkroom closes', async () => {
      let land!: (url: string) => void;
      renderPeaking.mockImplementation(() => new Promise<string>(resolve => { land = resolve; }));
      openDarkroom();
      component['peakingActive'].set(true);
      await settle();

      component['closeLightbox']();
      await settle();
      land('data:image/png;base64,late');
      await settle();

      expect(component['peakingOverlays']().size).toBe(0);
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
      await new Promise(resolve => setTimeout(resolve, SHARP_PRELOAD_DEBOUNCE_MS + 50));

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
      const renderedStore: CullingStore = rendered['cull'];
      renderedStore.groups.set([grp]);
      rendered['lightboxGroupId'].set(renderedStore.groupKey(grp));
      rendered['lightboxIndex'].set(0);
      rendered['peakingActive'].set(true);
      rendered['gridMode'].set('thirds');
      rendered['sharpPath'].set('/f1.jpg');

      fixture.detectChanges();
      await flush();
      await new Promise(resolve => setTimeout(resolve, SHARP_PRELOAD_DEBOUNCE_MS + 50));
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

  describe('assistant plan mode', () => {
    const planPhoto = (path: string, i: number) => ({
      path, filename: path.slice(1), aggregate: 8, aesthetic: 7, tech_sharpness: 6,
      is_blink: 0, is_burst_lead: i === 0 ? 1 : 0, date_taken: '2024-01-01', burst_score: 9 - i,
    });
    const planGroup = (id: number, type: string, paths: string[], keep: string[], number: number) => ({
      group_id: id, type, reason: '', best_path: paths[0], count: paths.length,
      photos: paths.map(planPhoto),
      plan: { number, keep_paths: keep, group_reason: { key: 'similar_percent', params: { percent: 91 } } },
    });
    const planOf = (groups: unknown[], extra: Record<string, unknown> = {}) => ({
      groups, total_groups: groups.length, plan_digest: 'dg', truncated: false, oversize_groups: 0, ...extra,
    });
    const pin = { digest: 'dg', request: { group_by: 'all' as const } };
    let plan: AssistantCullPlanService;
    let response: ReturnType<typeof planOf>;

    const mount = async () => {
      Element.prototype.scrollIntoView = vi.fn();
      const fixture = TestBed.createComponent(BurstCullingComponent);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      return fixture;
    };
    const el = (fixture: ComponentFixture<BurstCullingComponent>, id: string) =>
      fixture.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

    beforeEach(() => {
      plan = TestBed.inject(AssistantCullPlanService);
      response = planOf([
        planGroup(5, 'burst', ['/a.jpg', '/b.jpg'], ['/b.jpg'], 1),
        planGroup(5, 'similar', ['/c.jpg', '/d.jpg'], ['/c.jpg'], 2),
      ]);
      mockApi.post.mockImplementation((path: string) => of(path === '/culling/plan' ? response : {}));
    });

    it('renders the banner with x/y confirmed, the chip per group, and no differs dot until a keep flips', async () => {
      plan.setPin(pin);
      const fixture = await mount();
      expect(el(fixture, 'cull-plan-banner')?.textContent).toContain('culling.plan.banner');
      expect(fixture.nativeElement.querySelectorAll('[data-testid="cull-plan-chip"]').length).toBe(2);
      expect(el(fixture, 'cull-plan-chip')?.textContent).toContain('#1');
      expect(el(fixture, 'cull-plan-chip')?.textContent).toContain('culling.group_reason.similar_percent');
      expect(fixture.nativeElement.querySelectorAll('[data-testid="plan-differs-dot"]').length).toBe(0);
      const cull = fixture.debugElement.injector.get(CullingStore);
      cull.toggleSelection('/a.jpg', cull.groups()[0]);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('[data-testid="plan-differs-dot"]').length).toBe(1);
    });

    describe('assistant suggestion badges', () => {
      const key = (e: HTMLElement, type: string) => e.querySelector(`[data-testid="${type}"]`) as HTMLElement | null;
      const badges = (fixture: ComponentFixture<BurstCullingComponent>) =>
        Array.from(fixture.nativeElement.querySelectorAll('[data-testid="plan-suggestion-badge"]')) as HTMLButtonElement[];
      const mountWithSuggestions = async () => {
        plan.setPin(pin);
        const fixture = await mount();
        plan.suggest([{ path: '/b.jpg', action: 'reject', reason: 'soft focus' }], [{ path: '/a.jpg', note: 'tight call' }], false);
        fixture.detectChanges();
        return fixture;
      };
      const press = (target: HTMLElement, pressed: string) => {
        const event = new KeyboardEvent('keydown', { key: pressed, bubbles: true, cancelable: true });
        target.dispatchEvent(event);
        return event;
      };

      it('shows a badge on the differing photo and the group note in the chip row, as plain text', async () => {
        plan.setPin(pin);
        const fixture = await mount();
        plan.suggest([{ path: '/b.jpg', action: 'reject', reason: '<img src=x onerror=alert(1)>' }], [{ path: '/a.jpg', note: '<b>x</b>' }], false);
        fixture.detectChanges();
        expect(badges(fixture)).toHaveLength(1);
        expect(badges(fixture)[0].getAttribute('aria-label')).toContain('culling.plan.accept_reject');
        const note = key(fixture.nativeElement, 'cull-plan-note')!;
        expect(note.textContent).toContain('<b>x</b>');
        expect(note.querySelector('b')).toBeNull();
        expect(fixture.nativeElement.querySelector('img[src="x"]')).toBeNull();
      });

      it('a click on the badge accepts through the store and does not also toggle the tile', async () => {
        const fixture = await mountWithSuggestions();
        const cull = fixture.debugElement.injector.get(CullingStore);
        const accept = vi.spyOn(cull, 'acceptSuggestion');
        const toggle = vi.spyOn(cull, 'toggleSelection');
        badges(fixture)[0].click();
        fixture.detectChanges();
        expect(accept).toHaveBeenCalledWith(cull.groups()[0], '/b.jpg', 'reject');
        expect(toggle).not.toHaveBeenCalled();
        expect([...cull.selectionsMap().get('5_burst') ?? []]).toEqual([]);
        expect(badges(fixture)).toHaveLength(0);
        expect(plan.snapshot()?.changed).toHaveLength(1);
      });

      it('a double-click on the badge does not make the photo the only keeper', async () => {
        const fixture = await mountWithSuggestions();
        const cull = fixture.debugElement.injector.get(CullingStore);
        const exclusive = vi.spyOn(cull, 'selectExclusive');
        badges(fixture)[0].dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        expect(exclusive).not.toHaveBeenCalled();
      });

      it('a real double-click on a badge (click, badge unmounts, click and dblclick land on the tile) leaves the other keepers alone', async () => {
        plan.setPin(pin);
        const fixture = await mount();
        const cull = fixture.debugElement.injector.get(CullingStore);
        plan.suggest([{ path: '/d.jpg', action: 'keep', reason: 'sharper' }], [], false);
        fixture.detectChanges();
        const badge = badges(fixture)[0];
        const tile = badge.parentElement as HTMLElement;
        badge.click();
        fixture.detectChanges();
        expect(badges(fixture)).toHaveLength(0);
        tile.click();
        tile.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        fixture.detectChanges();
        expect([...cull.selectionsMap().get('5_similar') ?? []].sort()).toEqual(['/c.jpg', '/d.jpg']);
      });

      it('moves focus to the photo tile after an accept, instead of letting it fall to the body', async () => {
        const fixture = await mountWithSuggestions();
        const badge = badges(fixture)[0];
        const tile = badge.parentElement as HTMLElement;
        badge.focus();
        badge.click();
        fixture.detectChanges();
        expect(document.activeElement).toBe(tile);
      });

      it('names the badge starting with its visible text', async () => {
        const fixture = await mountWithSuggestions();
        const badge = badges(fixture)[0];
        expect(badge.getAttribute('aria-label')!.startsWith(badge.querySelector('span')!.textContent!.trim())).toBe(true);
      });

      it('Enter on the badge neither toggles the tile nor opens the lightbox', async () => {
        const fixture = await mountWithSuggestions();
        const cull = fixture.debugElement.injector.get(CullingStore);
        const toggle = vi.spyOn(cull, 'toggleSelection');
        press(badges(fixture)[0], 'Enter');
        expect(toggle).not.toHaveBeenCalled();
        expect(fixture.componentInstance['lightboxGroup']()).toBeNull();
      });

      it('Space on the badge neither toggles the tile nor confirms the group', async () => {
        const fixture = await mountWithSuggestions();
        const cull = fixture.debugElement.injector.get(CullingStore);
        const toggle = vi.spyOn(cull, 'toggleSelection');
        press(badges(fixture)[0], ' ');
        expect(toggle).not.toHaveBeenCalled();
        expect(cull.confirmedGroups().size).toBe(0);
        expect(cull.passingGroups().size).toBe(0);
      });

      it('renders no badge in a group that is counting down to a confirm', async () => {
        const fixture = await mountWithSuggestions();
        const cull = fixture.debugElement.injector.get(CullingStore);
        expect(cull.confirmGroup(cull.groups()[0])).toBe(true);
        fixture.detectChanges();
        expect(badges(fixture)).toHaveLength(0);
      });
    });

    it('shows the oversize note only when groups were left out', async () => {
      response = planOf(response.groups, { oversize_groups: 2 });
      plan.setPin(pin);
      const fixture = await mount();
      expect(el(fixture, 'cull-plan-oversize')).not.toBeNull();
    });

    it('shows no banner in manual mode', async () => {
      const fixture = await mount();
      expect(el(fixture, 'cull-plan-banner')).toBeNull();
      expect(el(fixture, 'cull-plan-chip')).toBeNull();
    });

    it('switches to plan mode when a pin is set on an already-mounted page', async () => {
      const fixture = await mount();
      const cull = fixture.debugElement.injector.get(CullingStore);
      expect(cull.planActive()).toBe(false);
      plan.setPin(pin);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(cull.planActive()).toBe(true);
      expect(el(fixture, 'cull-plan-banner')).not.toBeNull();
    });

    it('Exit restores the manual feed and drops the pin', async () => {
      plan.setPin(pin);
      const fixture = await mount();
      mockApi.get.mockClear();
      (el(fixture, 'cull-plan-exit') as HTMLButtonElement).click();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(mockApi.get).toHaveBeenCalledWith('/culling-groups', expect.anything());
      expect(plan.pin()).toBeNull();
      expect(el(fixture, 'cull-plan-banner')).toBeNull();
    });

    it('keeps the strictness button enabled in plan mode while the threshold stays frozen', async () => {
      plan.setPin(pin);
      const fixture = await mount();
      const button = (label: string) => fixture.nativeElement.querySelector(`button[aria-label="${label}"]`) as HTMLButtonElement;
      expect(fixture.debugElement.injector.get(CullingStore).planActive()).toBe(true);
      expect(button('culling.strictness').disabled).toBe(false);
      expect(button('culling.threshold').disabled).toBe(true);
    });

    it('a slider move in plan mode schedules a re-plan instead of re-deriving the keepers', async () => {
      plan.setPin(pin);
      const fixture = await mount();
      const cull = fixture.debugElement.injector.get(CullingStore);
      const schedule = vi.spyOn(cull, 'scheduleReplan');
      const reselect = vi.spyOn(cull, 'reselectFromStrictness');
      fixture.componentInstance['onStrictnessChange'](40);
      expect(schedule).toHaveBeenCalledTimes(1);
      expect(reselect).not.toHaveBeenCalled();
      expect(cull.strictness()).toBe(40);
      expect(localStorage.getItem('facet_culling_strictness')).toBe('40');
    });

    it('a slider move in manual mode re-derives the keepers, schedules nothing and drops the stored preset', async () => {
      const fixture = await mount();
      const cull = fixture.debugElement.injector.get(CullingStore);
      cull.selectedProfile.set('wedding');
      localStorage.setItem('facet_culling_profile', 'wedding');
      const schedule = vi.spyOn(cull, 'scheduleReplan');
      const reselect = vi.spyOn(cull, 'reselectFromStrictness');
      fixture.componentInstance['onStrictnessChange'](40);
      expect(reselect).toHaveBeenCalledTimes(1);
      expect(schedule).not.toHaveBeenCalled();
      expect(cull.selectedProfile()).toBe('');
      expect(localStorage.getItem('facet_culling_profile')).toBeNull();
    });

    it('a slider move in plan mode keeps the stored preset the plan carries', async () => {
      plan.setPin(pin);
      const fixture = await mount();
      const cull = fixture.debugElement.injector.get(CullingStore);
      expect(cull.planActive()).toBe(true);
      cull.selectedProfile.set('wedding');
      localStorage.setItem('facet_culling_profile', 'wedding');
      fixture.componentInstance['onStrictnessChange'](40);
      expect(cull.selectedProfile()).toBe('wedding');
      expect(localStorage.getItem('facet_culling_profile')).toBe('wedding');
    });

    it('disables confirm, skip and confirm-all while a re-plan is in flight', async () => {
      plan.setPin(pin);
      const fixture = await mount();
      const cull = fixture.debugElement.injector.get(CullingStore);
      const pending = new Subject<unknown>();
      mockApi.post.mockImplementation((path: string) => (path === '/culling/plan' ? pending : of({})));
      const buttons = () => {
        const all = [...fixture.nativeElement.querySelectorAll('button')] as HTMLButtonElement[];
        return {
          confirm: all.filter(b => b.getAttribute('aria-label') === 'culling.confirm'),
          skip: all.filter(b => b.getAttribute('aria-label') === 'culling.skip'),
          confirmAll: all.filter(b => b.textContent?.includes('culling.confirm_all')),
        };
      };
      const disabled = () => Object.values(buttons()).flat().map(b => b.disabled);
      expect(buttons().confirm.length).toBeGreaterThan(0);
      expect(buttons().skip.length).toBeGreaterThan(0);
      expect(buttons().confirmAll.length).toBeGreaterThan(0);
      expect(disabled().every(d => !d)).toBe(true);
      void cull.replan();
      await fixture.whenStable();
      expect(cull.replanning()).toBe(true);
      fixture.detectChanges();
      expect(disabled().every(d => d)).toBe(true);
      pending.next(planOf(response.groups, { plan_digest: 'dg2' }));
      pending.complete();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(cull.replanning()).toBe(false);
      expect(disabled().every(d => !d)).toBe(true);
    });

    it('the pin swap a re-plan makes does not re-enter the plan', async () => {
      plan.setPin(pin);
      const fixture = await mount();
      const cull = fixture.debugElement.injector.get(CullingStore);
      const enter = vi.spyOn(cull, 'enterPlan');
      const planPosts = () => mockApi.post.mock.calls.filter(c => c[0] === '/culling/plan');
      const before = planPosts().length;
      response = planOf(response.groups, { plan_digest: 'dg2' });
      cull.setStrictness(40);
      await cull.replan();
      fixture.detectChanges();
      await fixture.whenStable();
      TestBed.tick();
      expect(plan.pin()?.digest).toBe('dg2');
      expect(cull.planDigest()).toBe('dg2');
      expect(enter).not.toHaveBeenCalled();
      expect(planPosts()).toHaveLength(before + 1);
      expect(planPosts().at(-1)?.[1]).toEqual({ group_by: 'all', strictness: 40, date_from: null, date_to: null });
    });

    it('showGroupForAgent still pages plan groups in', async () => {
      response = planOf(Array.from({ length: 25 }, (_, i) => planGroup(i + 1, 'burst', [`/p${i}a.jpg`, `/p${i}b.jpg`], [`/p${i}a.jpg`], i + 1)));
      plan.setPin(pin);
      const fixture = await mount();
      const cull = fixture.debugElement.injector.get(CullingStore);
      expect(cull.groups()).toHaveLength(20);
      await fixture.componentInstance['showGroupForAgent']({ type: 'burst', group_id: 25 });
      expect(cull.groups()).toHaveLength(25);
      expect(fixture.componentInstance['lightboxGroupId']()).toBe('25_burst');
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
  let store: CullingStore;
  // jsdom ships no scrollIntoView, which the group list calls whenever the
  // selection lands back on a tile — as it does when the darkroom closes.
  const scrollIntoView = Element.prototype.scrollIntoView;

  const emptyFeed = {
    groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1,
  };
  const preview = {
    groups_processed: 3, kept: 4, rejected: 5, highlights_added: 0,
    dry_run: true, preview: [], next_cursor: null, plan_digest: 'digest',
  };

  beforeEach(() => {
    localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        provideNativeDateAdapter(),
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
        { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
        { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    fixture = TestBed.createComponent(BurstCullingComponent);
    component = fixture.componentInstance;
    store = component['cull'];
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
    Element.prototype.scrollIntoView = scrollIntoView;
  });

  const autoCullDialog = () =>
    fixture.debugElement.query(By.css('[aria-labelledby="autoCullTitle"]'));

  const openAutoCullDialog = () => {
    store.autoCullPreview.set(preview);
    fixture.detectChanges();
  };

  /** A dialog footer button, found by the key its label renders as. */
  const dialogButton = (labelKey: string): HTMLButtonElement => fixture.debugElement
    .queryAll(By.css('[aria-labelledby="autoCullTitle"] button'))
    .map(el => el.nativeElement as HTMLButtonElement)
    .find(el => el.textContent?.includes(labelKey))!;

  /** The dialog's only knob before a preview offers highlights: trim brackets. */
  const trimBracketsBox = (): HTMLInputElement => fixture.debugElement
    .query(By.css('[aria-labelledby="autoCullTitle"] input[type="checkbox"]')).nativeElement;

  /** The toolbar control that opens the dialog, disabled from the same signal. */
  const openAutoCullButton = (): HTMLButtonElement => fixture.debugElement
    .query(By.css('button[aria-label="culling.auto_cull.button"]')).nativeElement;

  const photo = (path: string) => ({
    path, filename: path.slice(1), aggregate: 8, aesthetic: 7, tech_sharpness: 6,
    is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8,
  });

  const openDarkroom = () => {
    store.groups.set([{
      group_id: 1, type: 'burst', reason: '', best_path: '/p1.jpg', count: 2,
      photos: [photo('/p1.jpg'), photo('/p2.jpg')],
    }]);
    component['lightboxGroupId'].set(store.groupKey(store.groups()[0]));
    fixture.detectChanges();
  };

  /** A per-pane keep button: a real control, deep inside a keydown shield. */
  const paneKeepButton = (): HTMLElement => fixture.debugElement
    .query(By.css('button[aria-label$="culling.lightbox.keep"]')).nativeElement;

  it('renders a reject marker on a rejected photo card only', () => {
    store.groups.set([{
      group_id: 1, type: 'burst', reason: '', best_path: '/p1.jpg', count: 2,
      photos: [{ ...photo('/p1.jpg'), is_rejected: 1 }, photo('/p2.jpg')],
    }]);
    fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.css('[data-testid="reject-marker"]'))).toHaveLength(1);
  });

  it('shows only Rejected for a legacy photo with conflicting review flags', () => {
    store.groups.set([{
      group_id: 1, type: 'burst', reason: '', best_path: '/p1.jpg', count: 2,
      photos: [{ ...photo('/p1.jpg'), is_kept: 1, is_rejected: 1 }, photo('/p2.jpg')],
    }]);
    fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.css('[data-testid="kept-marker"]'))).toHaveLength(0);
    expect(fixture.debugElement.queryAll(By.css('[data-testid="reject-marker"]'))).toHaveLength(1);
  });

  it('shows a persisted Keep marker independently of the pending culling selection', () => {
    store.groups.set([{
      group_id: 1, type: 'burst', reason: '', best_path: '/p1.jpg', count: 2,
      photos: [{ ...photo('/p1.jpg'), is_kept: 1 }, photo('/p2.jpg')],
    }]);
    fixture.detectChanges();
    const markers = fixture.debugElement.queryAll(By.css('[data-testid="kept-marker"]'));
    expect(markers).toHaveLength(1);
    expect(markers[0].nativeElement.textContent).toContain('review.kept');
  });

  it('closes the auto-cull dialog on Escape despite its keydown shield', () => {
    openAutoCullDialog();
    expect(autoCullDialog()).toBeTruthy();

    autoCullDialog().nativeElement.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
    );
    fixture.detectChanges();

    expect(store.autoCullPreview()).toBeNull();
  });

  // Rendered rather than called: the backdrop click and the Escape binding are
  // the template's, and both used to tear the dialog down over a destructive
  // apply that was still in flight — re-arming Apply for a second one.
  it('survives Escape and a backdrop click while the apply is in flight', async () => {
    const api = TestBed.inject(ApiService) as unknown as { post: Mock };
    await store.openAutoCull();
    fixture.detectChanges();
    const response = new Subject<typeof preview>();
    api.post = vi.fn(() => response);
    const applied = component['confirmAutoCull']();
    fixture.detectChanges();

    const backdrop = autoCullDialog().nativeElement.parentElement as HTMLElement;
    autoCullDialog().nativeElement.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
    );
    backdrop.click();
    fixture.detectChanges();

    expect(autoCullDialog()).toBeTruthy();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(dialogButton('dialog.cancel').disabled).toBe(true);

    response.next({ ...preview, dry_run: false });
    response.complete();
    await applied;
    fixture.detectChanges();

    expect(autoCullDialog()).toBeFalsy();
  });

  /**
   * Every control the dialog disables reads `autoCullBusy`, never
   * `autoCullLoading` alone. A dry run started before the apply — the profile
   * suggestion's is fire-and-forget, so it can be — clears the loading flag when
   * it answers, and each control driven by that flag re-armed itself over a
   * destructive request that was still open: the knobs invited a re-run of the
   * body being applied, and Apply invited a second apply.
   *
   * Rendered rather than read off the signals: the bindings are the whole of the
   * fix, and every behavioural test stayed green with them reverted.
   */
  it('keeps every dialog control disabled while an apply outlives the dry run behind it', async () => {
    const api = TestBed.inject(ApiService) as unknown as { post: Mock };
    const flush = () => new Promise(resolve => setTimeout(resolve, 0));
    await store.openAutoCull();
    fixture.detectChanges();
    expect(trimBracketsBox().disabled).toBe(false);
    expect(dialogButton('culling.auto_cull.apply').disabled).toBe(false);

    const dryRun = new Subject<typeof preview>();
    api.post = vi.fn(() => dryRun);
    void store.openAutoCull();
    await flush();
    const response = new Subject<typeof preview>();
    api.post = vi.fn(() => response);
    const applied = component['confirmAutoCull']();
    dryRun.next({ ...preview, rejected: 99 });
    dryRun.complete();
    await flush();
    fixture.detectChanges();

    // The window the two signals disagree in: the dry run behind the apply has
    // cleared `loading`, and the apply is still open.
    expect(store.autoCullLoading()).toBe(false);
    expect(store.autoCullApplying()).toBe(true);
    expect(trimBracketsBox().disabled).toBe(true);
    expect(dialogButton('culling.auto_cull.apply').disabled).toBe(true);
    expect(dialogButton('dialog.cancel').disabled).toBe(true);
    expect(openAutoCullButton().disabled).toBe(true);
    expect(fixture.debugElement
      .query(By.css('[aria-labelledby="autoCullTitle"] mat-spinner'))).toBeTruthy();

    response.next({ ...preview, dry_run: false });
    response.complete();
    await applied;
    fixture.detectChanges();

    expect(autoCullDialog()).toBeFalsy();
    expect(openAutoCullButton().disabled).toBe(false);
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
    openDarkroom();

    const darkroom = fixture.debugElement.query(By.css('[role="dialog"][aria-modal="true"]'));
    expect(fixture.debugElement.queryAll(By.directive(CdkTrapFocus))
      .some(el => el.nativeElement === darkroom.nativeElement)).toBe(true);
  });

  // The darkroom's shields are the auto-cull dialog's problem one layer down:
  // every inner region stops keys from reaching the page, so from any control
  // the user is actually focused on, Escape never reached the container binding
  // and the darkroom could not be closed with the keyboard at all.
  it('closes the darkroom on Escape from a control inside it', () => {
    openDarkroom();
    component['setCompareMode']('2up');
    fixture.detectChanges();
    const keepButton = paneKeepButton();
    keepButton.focus();

    keepButton.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();

    expect(component['lightboxGroup']()).toBeNull();
  });

  it('closes the darkroom on Escape from the header controls', () => {
    openDarkroom();
    const legendButton: HTMLElement = fixture.debugElement
      .query(By.css('[aria-label="culling.legend.label"]')).nativeElement;
    legendButton.focus();

    legendButton.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();

    expect(component['lightboxGroup']()).toBeNull();
  });

  // Escape is acted on at the shield rather than let through it: the page's cull
  // shortcuts must still not see a single key pressed inside the darkroom.
  it('keeps shielding the page from keys pressed inside the darkroom', () => {
    openDarkroom();
    component['setCompareMode']('2up');
    fixture.detectChanges();
    const keepButton = paneKeepButton();
    const seenAtDocument = vi.fn();
    document.addEventListener('keydown', seenAtDocument);

    keepButton.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    keepButton.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    document.removeEventListener('keydown', seenAtDocument);

    expect(seenAtDocument).not.toHaveBeenCalled();
  });

  it('legend toggle starts hidden, shows the legend on click and flips aria-pressed', () => {
    store.groups.set([{
      group_id: 1, type: 'burst', reason: '', best_path: '/p1.jpg', count: 1,
      photos: [{
        path: '/p1.jpg', filename: 'p1.jpg', aggregate: 8, aesthetic: 7,
        tech_sharpness: 6, is_blink: 0, is_burst_lead: 1,
        date_taken: '2024-01-01', burst_score: 8,
      }],
    }]);
    component['lightboxGroupId'].set(store.groupKey(store.groups()[0]));
    fixture.detectChanges();

    const darkroom = fixture.debugElement.query(By.css('[role="dialog"][aria-modal="true"]'));
    const legendButton = darkroom.query(By.css('[aria-label="culling.legend.label"]'));
    expect(darkroom.query(By.css('kbd'))).toBeNull();
    expect(legendButton.nativeElement.getAttribute('aria-pressed')).toBe('false');

    legendButton.nativeElement.click();
    fixture.detectChanges();

    expect(darkroom.query(By.css('kbd'))).toBeTruthy();
    expect(legendButton.nativeElement.getAttribute('aria-pressed')).toBe('true');
  });

  // Rendered, not called directly: openDarkroom + a populated faceMap put the
  // real face-strip sliders on screen, so this exercises the template's own
  // (dragEnd) bindings rather than the handler in isolation. A dropped binding
  // on any one thumb (the eyes slider lost it once) passes every unit test in
  // the 'face-strip slider focus release' describe block above, because those
  // never render the template — only this test can catch that.
  it('face-strip slider focus release: every face-strip slider thumb refocuses the dialog on dragEnd', () => {
    openDarkroom();
    component['faceMap'].set(new Map([
      ['/p1.jpg', [{ id: 1, face_index: 0, eyes_open_score: 5, smile_score: 5 }]],
    ]));
    fixture.detectChanges();

    const dialog = fixture.debugElement.query(By.css('[role="dialog"][aria-modal="true"]')).nativeElement;
    const focusSpy = vi.spyOn(dialog, 'focus');
    const thumbs = fixture.debugElement.queryAll(By.css('[matSliderThumb]'));
    expect(thumbs.length).toBe(3);

    for (const thumb of thumbs) {
      focusSpy.mockClear();
      thumb.triggerEventHandler('dragEnd', {});
      expect(focusSpy).toHaveBeenCalledTimes(1);
    }
  });

  it('face strip: outlines the current frame and follows the arrow keys', () => {
    openDarkroom();
    component['faceMap'].set(new Map([
      ['/p1.jpg', [{ id: 1, face_index: 0, eyes_open_score: 5, smile_score: 5 }]],
      ['/p2.jpg', [{ id: 2, face_index: 0, eyes_open_score: 5, smile_score: 5 }]],
    ]));
    fixture.detectChanges();
    const outlined = () => fixture.debugElement.queryAll(By.css('[data-face-frame]'))
      .filter(el => el.nativeElement.classList.contains('outline-amber-400'))
      .map(el => el.nativeElement.getAttribute('data-face-frame'));
    expect(outlined()).toEqual(['0']);

    component.onArrowRight(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
    fixture.detectChanges();
    expect(outlined()).toEqual(['1']);
  });
});

// Rendered, and with real pointer events: the gesture is a property of the
// element the directive sits on, and the three gates that decide whether it is
// live at all (coarse pointer, single view, fit scale) are template conditions.
// Nothing below is evidence about a real finger — see the note in VIEWER.md.
describe('BurstCullingComponent swipe-to-decide (rendered, touch)', () => {
  let fixture: ComponentFixture<BurstCullingComponent>;
  let component: any;
  let store: CullingStore;
  let undoAction: Subject<void>;
  let mockSnackBar: { open: Mock };

  const photo = (path: string) => ({
    path, filename: path.slice(1), aggregate: 8, aesthetic: 7, tech_sharpness: 6,
    is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8,
  });
  const group = {
    group_id: 1, type: 'burst' as const, reason: '', best_path: '/s1.jpg', count: 3,
    photos: [photo('/s1.jpg'), photo('/s2.jpg'), photo('/s3.jpg')],
  };
  const emptyFeed = { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 };

  /** jsdom lays nothing out, so the gesture is given a width to measure against. */
  const PANE_WIDTH = 400;
  /** Past 35% of PANE_WIDTH (140px) — commits. */
  const OVER = 200;
  /** Short of it, but well past the 10px axis slop — springs back. */
  const UNDER = 60;

  beforeEach(() => {
    localStorage.clear();
    // The shared test setup answers every media query with `matches: false`,
    // which would leave the swipe disabled in every test here.
    vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
      matches: query === '(pointer: coarse)',
      media: query,
      onchange: null,
      addListener: vi.fn(), removeListener: vi.fn(),
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as MediaQueryList);
    undoAction = new Subject<void>();
    mockSnackBar = {
      open: vi.fn(() => ({
        onAction: () => undoAction,
        afterDismissed: () => new Subject<void>(),
      })),
    };
    TestBed.configureTestingModule({
      providers: [
        provideNativeDateAdapter(),
        provideRouter([]),
        { provide: ApiService, useValue: {
          get: vi.fn(() => of(emptyFeed)),
          post: vi.fn(() => of({})),
          thumbnailUrl: vi.fn(() => '/thumb'),
          imageUrl: vi.fn(() => '/image'),
        } },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: GalleryStore, useValue: { config: () => null } },
        { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
        { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    fixture = TestBed.createComponent(BurstCullingComponent);
    component = fixture.componentInstance;
    store = component['cull'];
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
    vi.restoreAllMocks();
  });

  const openDarkroom = () => {
    store.groups.set([group]);
    component['lightboxGroupId'].set(store.groupKey(group));
    component['lightboxIndex'].set(0);
    fixture.detectChanges();
  };

  const surface = () => fixture.debugElement.query(By.directive(SwipeDecisionDirective));

  /**
   * Drag by (dx, dy) in three steps and lift the finger.
   *
   * Dispatched on the image itself, which is what a finger actually lands on,
   * so the events reach the directive the only way they ever do in a browser:
   * by bubbling up through `app-synced-zoom` — which gets its own look at every
   * one of them first.
   */
  const drag = (dx: number, dy = 0) => {
    const el: HTMLElement = surface().nativeElement;
    el.getBoundingClientRect = () => ({
      width: PANE_WIDTH, height: 600, x: 0, y: 0, top: 0, left: 0,
      right: PANE_WIDTH, bottom: 600, toJSON: () => ({}),
    }) as DOMRect;
    const target = el.querySelector('img') ?? el;
    const send = (type: string, x: number, y: number) => target.dispatchEvent(
      new PointerEvent(type, { pointerId: 1, isPrimary: true, clientX: x, clientY: y, bubbles: true }),
    );
    send('pointerdown', 0, 0);
    send('pointermove', dx / 2, dy / 2);
    send('pointermove', dx, dy);
    send('pointerup', dx, dy);
  };

  /** The decision lands when the card has flown out, not when the finger lifts. */
  const settle = () => new Promise(resolve => setTimeout(resolve, SWIPE_SETTLE_MS + 20));
  const keptPaths = () => [...(store.selectionsMap().get('1_burst') ?? [])];

  it('keeps the frame on a right swipe past the threshold, then steps to the next', async () => {
    openDarkroom();

    drag(OVER);
    await settle();

    expect(keptPaths()).toEqual(['/s1.jpg']);
    expect(component['lightboxIndex']()).toBe(1);
  });

  // The same state ArrowDown writes: rejecting is dropping the frame out of the
  // group's kept set, not adding it to a second one.
  it('rejects the frame on a left swipe past the threshold, then steps to the next', async () => {
    openDarkroom();
    store.selectionsMap.set(new Map([['1_burst', new Set(['/s1.jpg', '/s2.jpg', '/s3.jpg'])]]));

    drag(-OVER);
    await settle();

    expect(keptPaths()).toEqual(['/s2.jpg', '/s3.jpg']);
    expect(component['lightboxIndex']()).toBe(1);
  });

  it('springs back under the threshold, deciding nothing and staying on the frame', async () => {
    openDarkroom();

    drag(UNDER);
    await settle();

    expect(store.selectionsMap().get('1_burst')).toBeUndefined();
    expect(component['lightboxIndex']()).toBe(0);
  });

  // The axis lock, not the distance, is what makes this pass: dx alone would be
  // well past the commit threshold.
  it('lets a dominantly vertical drag through untouched', async () => {
    openDarkroom();

    drag(OVER, 400);
    await settle();

    expect(store.selectionsMap().get('1_burst')).toBeUndefined();
    expect(component['lightboxIndex']()).toBe(0);
  });

  // The gesture never calls preventDefault; this declaration is the whole of its
  // deal with the browser — horizontal is ours, vertical stays the page's.
  it('declares the axis contract with touch-action, and drops it when it stands down', () => {
    openDarkroom();
    expect((surface().nativeElement as HTMLElement).style.touchAction).toBe('pan-y');

    component['zoom'].set({ scale: 2, tx: 0, ty: 0 });
    fixture.detectChanges();

    expect((surface().nativeElement as HTMLElement).style.touchAction).toBe('');
  });

  it('is not mounted at all in the compare grid, which has no single frame to decide', () => {
    openDarkroom();
    expect(surface()).toBeTruthy();

    component['setCompareMode']('2up');
    fixture.detectChanges();

    expect(surface()).toBeNull();
  });

  // The non-interference guarantee, and the reason it is a gate rather than a
  // priority: past the fit scale the very same drag is the pane's pan, so the
  // one drag below has to move the crop and decide nothing.
  it('stands down while the frame is zoomed, leaving the drag to the pane pan', async () => {
    openDarkroom();
    component['zoom'].set({ scale: 2, tx: 0, ty: 0 });
    fixture.detectChanges();
    expect(component['swipeEnabled']()).toBe(false);

    drag(OVER);
    await settle();

    // How far it panned depends on when change detection pushes the shared zoom
    // back down into the pane; that it panned at all is the point.
    expect(component['zoom']().tx).toBeGreaterThan(0);
    expect(store.selectionsMap().get('1_burst')).toBeUndefined();
    expect(component['lightboxIndex']()).toBe(0);
  });

  it('offers an Undo that restores both the decision and the frame it was made on', async () => {
    openDarkroom();

    drag(OVER);
    await settle();
    expect(mockSnackBar.open).toHaveBeenCalledWith(
      'culling.swipe.kept', 'undo.action', expect.anything());

    undoAction.next();
    await settle();

    expect(keptPaths()).toEqual([]);
    expect(component['lightboxIndex']()).toBe(0);
  });

  it('shows the swipe hint until it is dismissed, and remembers that', () => {
    openDarkroom();
    const dismissButton = () => [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')]
      .find(b => b.textContent?.includes('culling.swipe.hint_dismiss'));
    expect(dismissButton()).toBeTruthy();

    dismissButton()!.click();
    fixture.detectChanges();

    expect(dismissButton()).toBeUndefined();
    expect(localStorage.getItem('facet_culling_swipe_hint')).toBe('true');
  });
});

/**
 * The compare grid's per-frame chrome.
 *
 * Everything here is about one pane's own photo: a decision taken on it must not
 * land on whichever frame the keyboard happens to be focused on, and the marks
 * that say what was decided must sit on the photo rather than on the cell that
 * letterboxes it.
 */
describe('BurstCullingComponent compare panes (rendered)', () => {
  let fixture: ComponentFixture<BurstCullingComponent>;
  let component: any;
  let store: CullingStore;

  const photo = (path: string) => ({
    path, filename: path.slice(1), aggregate: 8, aesthetic: 7, tech_sharpness: 6,
    is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8,
  });
  const group = {
    group_id: 1, type: 'burst' as const, reason: '', best_path: '/c1.jpg', count: 2,
    photos: [photo('/c1.jpg'), photo('/c2.jpg')],
  };
  const emptyFeed = { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 };

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideNativeDateAdapter(),
        provideRouter([]),
        { provide: ApiService, useValue: {
          get: vi.fn(() => of(emptyFeed)),
          post: vi.fn(() => of({})),
          thumbnailUrl: vi.fn(() => '/thumb'),
          imageUrl: vi.fn(() => '/image'),
        } },
        { provide: MatSnackBar, useValue: { open: vi.fn(() => ({
          onAction: () => new Subject<void>(), afterDismissed: () => new Subject<void>(),
        })) } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: GalleryStore, useValue: { config: () => null } },
        { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
        { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    fixture = TestBed.createComponent(BurstCullingComponent);
    component = fixture.componentInstance;
    store = component['cull'];
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
    vi.restoreAllMocks();
  });

  const openCompare = () => {
    store.groups.set([group]);
    component['lightboxGroupId'].set(store.groupKey(group));
    component['lightboxIndex'].set(0);
    component['setCompareMode']('2up');
    fixture.detectChanges();
  };

  const buttonFor = (label: string): HTMLButtonElement | undefined =>
    [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')]
      .find(b => b.getAttribute('aria-label') === label);
  const keptPaths = () => [...(store.selectionsMap().get('1_burst') ?? [])];

  it('offers a keep and a reject button naming the frame of each pane', () => {
    openCompare();

    expect(buttonFor('c1.jpg, culling.lightbox.keep')).toBeTruthy();
    expect(buttonFor('c1.jpg, culling.lightbox.reject')).toBeTruthy();
    expect(buttonFor('c2.jpg, culling.lightbox.keep')).toBeTruthy();
    expect(buttonFor('c2.jpg, culling.lightbox.reject')).toBeTruthy();
  });

  // The ↑ / ↓ keys can only ever reach the focused frame, which is what left the
  // other panes undecidable without stepping onto them first.
  it('decides the frame of the pane clicked, not the focused one', () => {
    openCompare();

    buttonFor('c2.jpg, culling.lightbox.keep')!.click();
    fixture.detectChanges();

    expect(keptPaths()).toEqual(['/c2.jpg']);
    expect(component['lightboxIndex']()).toBe(0);
  });

  it('writes the same state the arrow keys do, so rejecting drops the frame', () => {
    openCompare();
    store.selectionsMap.set(new Map([['1_burst', new Set(['/c1.jpg', '/c2.jpg'])]]));
    fixture.detectChanges();

    buttonFor('c2.jpg, culling.lightbox.reject')!.click();
    fixture.detectChanges();

    expect(keptPaths()).toEqual(['/c1.jpg']);
  });

  it('marks the decided pane with the solid badge the tiles use', () => {
    openCompare();
    store.selectionsMap.set(new Map([['1_burst', new Set(['/c1.jpg'])]]));
    fixture.detectChanges();

    const host: HTMLElement = fixture.nativeElement;
    expect(host.querySelectorAll('[aria-label="culling.lightbox.kept"].bg-green-600')).toHaveLength(1);
    expect(host.querySelectorAll('[aria-label="culling.lightbox.rejected"].bg-red-600')).toHaveLength(1);
  });

  // The chrome traces the rendered photo, so it must be inset by whatever the
  // pane letterboxed away -- not pinned to the cell corner.
  it('insets the per-frame chrome by the letterbox of its pane', () => {
    openCompare();
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    const pane = panes[0].componentInstance as SyncedZoomComponent;
    const host: HTMLElement = panes[0].nativeElement;
    host.getBoundingClientRect = () => ({
      width: 800, height: 600, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 600,
      toJSON: () => ({}),
    }) as DOMRect;
    const img = host.querySelector('img')!;
    Object.defineProperty(img, 'naturalWidth', { value: 4000, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 1000, configurable: true });
    img.dispatchEvent(new Event('load'));
    fixture.detectChanges();

    expect(pane.fitInsetY()).toBe(200);
    const chrome = buttonFor('c1.jpg, culling.lightbox.keep')!.closest('div[style]') as HTMLElement;
    expect(chrome.style.top).toBe('200px');
    expect(chrome.style.left).toBe('0px');
  });

  it('names the frame the footer status is about while a grid is shown', () => {
    openCompare();
    const footer: HTMLElement = fixture.nativeElement;
    expect(footer.textContent).toContain('c1.jpg');

    component['setCompareMode']('single');
    fixture.detectChanges();

    expect(footer.querySelectorAll('app-synced-zoom')).toHaveLength(1);
    expect(footer.textContent).not.toContain('c1.jpg');
  });
});

describe('BurstCullingComponent progressive darkroom frames (rendered)', () => {
  class FakeImage {
    static instances: FakeImage[] = [];
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    src = '';
    constructor() { FakeImage.instances.push(this); }
  }
  let fixture: ComponentFixture<BurstCullingComponent>;
  let component: any;
  const urls = new ThumbnailUrlPipe();
  const thumb = (path: string) => urls.transform(path, 640);
  const render = (path: string) => urls.transform(path, 1920);
  const photo = (path: string) => ({
    path, filename: path.slice(1), aggregate: 8, aesthetic: 7, tech_sharpness: 6,
    is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 8,
  });
  const group = {
    group_id: 1, type: 'burst', reason: '', best_path: '/p0.jpg', count: 3,
    photos: [photo('/p0.jpg'), photo('/p1.jpg'), photo('/p2.jpg')],
  };
  const emptyFeed = { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 };
  const srcs = () => FakeImage.instances.map(i => i.src).filter(Boolean);

  beforeEach(() => {
    FakeImage.instances = [];
    vi.stubGlobal('Image', FakeImage);
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideNativeDateAdapter(),
        provideRouter([]),
        { provide: ApiService, useValue: {
          get: vi.fn(() => of(emptyFeed)), post: vi.fn(() => of({})),
          thumbnailUrl: vi.fn(() => '/thumb'), imageUrl: vi.fn(() => '/image'),
        } },
        { provide: MatSnackBar, useValue: { open: vi.fn(() => ({
          onAction: () => new Subject<void>(), afterDismissed: () => new Subject<void>(),
        })) } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: GalleryStore, useValue: { config: () => null } },
        { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
        { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    fixture = TestBed.createComponent(BurstCullingComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
    vi.unstubAllGlobals();
    Object.defineProperty(navigator, 'connection', { value: undefined, configurable: true });
    vi.restoreAllMocks();
  });

  const open = (index: number) => {
    component['cull'].groups.set([group]);
    component['lightboxGroupId'].set(component['cull'].groupKey(group));
    component['lightboxIndex'].set(index);
    fixture.detectChanges();
    FakeImage.instances = FakeImage.instances.filter(i => i.src);
    fixture.detectChanges();
  };
  const pane = (): SyncedZoomComponent =>
    fixture.debugElement.query(By.directive(SyncedZoomComponent)).componentInstance;

  it('shows the stored thumbnail as the placeholder of the render, keyed by the frame', () => {
    open(1);

    expect(pane().src()).toBe(render('/p1.jpg'));
    expect(pane().placeholderSrc()).toBe(thumb('/p1.jpg'));
    expect(pane().frameKey()).toBe('/p1.jpg');
  });

  it('fetches the neighbours thumbnails at once and their renders only after the frame is sharp', () => {
    open(1);
    expect(srcs()).toEqual(expect.arrayContaining([thumb('/p0.jpg'), thumb('/p2.jpg')]));
    expect(srcs()).not.toContain(render('/p0.jpg'));

    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();

    expect(srcs()).toEqual(expect.arrayContaining([render('/p0.jpg'), render('/p2.jpg')]));
  });

  it('keeps the displayed frame and the decision target in step while walking, and a late sharp event preloads nothing', () => {
    open(0);
    const shown = () => fixture.nativeElement.querySelector('app-synced-zoom img').getAttribute('src');
    for (const [idx, path] of [[0, '/p0.jpg'], [1, '/p1.jpg'], [2, '/p2.jpg']] as const) {
      component['lightboxIndex'].set(idx);
      fixture.detectChanges();
      expect(component['lightboxGroup']().photos[component['lightboxIndex']()].path).toBe(path);
      expect(shown()).toContain(encodeURIComponent(path));
      expect(shown()).toBe(thumb(path));
      // The decision target, through the real keyboard path: reject, then keep,
      // must land on the frame on screen and on no other.
      const kept = () => [...(component['cull'].selectionsMap().get(component['cull'].groupKey(group)) ?? [])];
      component['onArrowDown'](new KeyboardEvent('keydown', { key: 'ArrowDown' }));
      expect(kept()).not.toContain(path);
      component['onArrowUp'](new KeyboardEvent('keydown', { key: 'ArrowUp' }));
      expect(kept()).toContain(path);
      for (const other of ['/p0.jpg', '/p1.jpg', '/p2.jpg'].filter(p => p !== path && p > path)) {
        expect(kept()).not.toContain(other);
      }
    }
    FakeImage.instances = [];
    // The render of frame 1 reports in after the user is already on frame 2.
    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();
    expect(srcs().filter(u => u.includes('size=1920'))).toEqual([]);
  });

  it('prefetches one neighbour at either end of the group', () => {
    open(0);
    component['onSharpLoaded'](render('/p0.jpg'));
    fixture.detectChanges();
    expect(srcs().filter(u => u.includes('size=1920'))).toEqual([render('/p1.jpg')]);

    FakeImage.instances = [];
    component['lightboxIndex'].set(2);
    fixture.detectChanges();
    component['onSharpLoaded'](render('/p2.jpg'));
    fixture.detectChanges();
    expect(srcs().filter(u => u.includes('size=1920'))).toEqual([render('/p1.jpg')]);
  });

  it('keeps the in-flight render of the frame stepped onto and aborts the one left behind', () => {
    open(1);
    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();
    const farSide = FakeImage.instances.find(i => i.src === render('/p0.jpg'))!;
    const stepTarget = FakeImage.instances.find(i => i.src === render('/p2.jpg'))!;

    component['lightboxIndex'].set(2);
    fixture.detectChanges();

    // The render being fetched for the frame stepped onto carries on, with its handler.
    expect(stepTarget.src).toBe(render('/p2.jpg'));
    expect(stepTarget.onload).not.toBeNull();
    expect(FakeImage.instances.filter(i => i.src === render('/p2.jpg'))).toHaveLength(1);
    // The far side is not wanted any more.
    expect(farSide.src).toBe('');
    expect(farSide.onload).toBeNull();
    expect(farSide.onerror).toBeNull();
  });

  it('does not create a second image for a render still in flight when stepping back', () => {
    open(1);
    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();
    const p2Render = FakeImage.instances.find(i => i.src === render('/p2.jpg'))!;
    component['lightboxIndex'].set(2);
    fixture.detectChanges();
    component['lightboxIndex'].set(1);
    fixture.detectChanges();
    const live = (url: string) => FakeImage.instances.filter(i => i.src === url);
    for (const url of new Set(FakeImage.instances.map(i => i.src).filter(u => u !== ''))) {
      expect(live(url), url).toHaveLength(1);
    }
    expect(live(render('/p2.jpg'))[0]).toBe(p2Render);
  });

  it('keeps the stored thumbnail in flight for the frame stepped onto', () => {
    open(1);
    const stepTarget = FakeImage.instances.find(i => i.src === thumb('/p2.jpg'))!;

    component['lightboxIndex'].set(2);
    fixture.detectChanges();

    expect(stepTarget.src).toBe(thumb('/p2.jpg'));
    expect(FakeImage.instances.filter(i => i.src === thumb('/p2.jpg'))).toHaveLength(1);
  });

  it('does not restart the neighbour fetches when a new group object has the same neighbours', () => {
    open(1);
    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();
    const before = [...FakeImage.instances];
    // A re-run of either prefetch effect goes through prefetch().
    const prefetch = vi.spyOn(component as any, 'prefetch');

    component['cull'].groups.set([{ ...group, photos: [...group.photos] }]);
    fixture.detectChanges();

    expect(prefetch).not.toHaveBeenCalled();
    expect(FakeImage.instances).toEqual(before);
    expect(before.every(i => i.src !== '')).toBe(true);
  });

  it('records a neighbour render it has fetched so the pane can skip its debounce', () => {
    open(1);
    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();
    const neighbour = FakeImage.instances.find(i => i.src === render('/p2.jpg'))!;
    neighbour.onload!();
    expect((component['loadedRenders'] as LoadedSources).has(render('/p2.jpg'))).toBe(true);
  });

  it('prefetches no neighbours and shows no placeholder while a darktable style is active', () => {
    component['activeStyle'].set('portra');
    open(1);
    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();

    expect(pane().placeholderSrc()).toBeNull();
    expect(srcs().filter(u => u.includes('path=%2Fp0.jpg') || u.includes('path=%2Fp2.jpg'))).toEqual([]);
  });

  it('prefetches no neighbours when the browser asks to save data', () => {
    Object.defineProperty(navigator, 'connection', { value: { saveData: true }, configurable: true });
    open(1);
    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();

    expect(srcs().filter(u => u.includes('path=%2Fp0.jpg') || u.includes('path=%2Fp2.jpg'))).toEqual([]);
  });

  it('gives every compare pane its own thumbnail as placeholder and prefetches no neighbours', () => {
    open(0);
    component['setCompareMode']('2up');
    fixture.detectChanges();
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(d => d.componentInstance as SyncedZoomComponent);

    expect(panes.map(p => p.placeholderSrc())).toEqual([thumb('/p0.jpg'), thumb('/p1.jpg')]);
    expect(panes.map(p => p.frameKey())).toEqual(['/p0.jpg', '/p1.jpg']);
    expect(srcs().filter(u => u.includes('path=%2Fp2.jpg'))).toEqual([]);
  });

  it('waits for the sharp render before building the peaking overlay in single view', async () => {
    const renderPeaking = vi.spyOn(component as any, 'renderPeaking').mockResolvedValue('overlay');
    open(1);
    component['peakingActive'].set(true);
    fixture.detectChanges();
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(renderPeaking).not.toHaveBeenCalled();

    component['onSharpLoaded'](render('/p1.jpg'));
    fixture.detectChanges();
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(renderPeaking).toHaveBeenCalledTimes(1);
  });
});

// Rendered: the date-range button, its tooltip and the empty states are template properties, and the URL
// mirror is an effect. Every other suite stubs ActivatedRoute with no `/culling` route, so navigation is
// observed on a spy of `router.navigate`, not on the URL.
describe('BurstCullingComponent date range', () => {
  let fixture: ComponentFixture<BurstCullingComponent>;
  let component: any;
  let cull: CullingStore;
  let router: Router;
  let navigate: Mock;
  let urlGetter: { mockReturnValue: (v: string) => void };
  const scrollIntoView = Element.prototype.scrollIntoView;
  const emptyFeed = { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 };

  const mount = (query: Record<string, string> = {}, url = '/culling'): void => {
    TestBed.configureTestingModule({
      providers: [
        provideNativeDateAdapter(),
        provideRouter([]),
        { provide: ApiService, useValue: { get: vi.fn(() => of(emptyFeed)), post: vi.fn(() => of({})), thumbnailUrl: vi.fn(() => '/thumb'), imageUrl: vi.fn(() => '/image') } },
        { provide: MatSnackBar, useValue: { open: vi.fn(() => ({ onAction: () => new Subject<void>(), afterDismissed: () => new Subject<void>() })) } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: GalleryStore, useValue: { config: () => null } },
        { provide: AuthService, useValue: { isEdition: () => true, identity: () => '0|' } },
        { provide: AssistantChangesService, useValue: { batch$: new Subject<AssistantChangeBatch>().asObservable() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: (k: string) => query[k] ?? null } } } },
      ],
    });
    router = TestBed.inject(Router);
    navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true) as unknown as Mock;
    urlGetter = vi.spyOn(router, 'url', 'get') as unknown as { mockReturnValue: (v: string) => void };
    urlGetter.mockReturnValue(url);
    fixture = TestBed.createComponent(BurstCullingComponent);
    component = fixture.componentInstance;
    cull = component['cull'];
    fixture.detectChanges();
  };

  const dateButton = (): HTMLButtonElement | null =>
    fixture.nativeElement.querySelector('button[data-testid="cull-date-range"]');
  const settle = async (): Promise<void> => {
    fixture.detectChanges();
    await fixture.whenStable();
    TestBed.tick();
    fixture.detectChanges();
  };
  const scopeCalls = () => navigate.mock.calls.filter(c => c[1]?.queryParamsHandling === 'merge' && 'from' in (c[1]?.queryParams ?? {}));

  beforeEach(() => {
    localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    fixture.destroy();
    Element.prototype.scrollIntoView = scrollIntoView;
  });

  it('shows the date button with no album at all', () => {
    mount();
    expect(cull.albums()).toEqual([]);
    expect(dateButton()).not.toBeNull();
    expect(dateButton()!.getAttribute('aria-label')).toBe('culling.date_range.label');
    expect(dateButton()!.className).not.toContain('text-[var(--mat-sys-primary)]');
  });

  it('lights the button and names the window dd/MM/yyyy when the URL carries one', () => {
    mount({ from: '2026-07-01', to: '2026-07-31' });
    expect(dateButton()!.getAttribute('aria-label')).toBe('01/07/2026 - 31/07/2026');
    expect(dateButton()!.className).toContain('text-[var(--mat-sys-primary)]');
  });

  it('reads the EXIF form of a plan\'s window too', () => {
    mount({ from: '2026:07:01 00:00:00', to: '2026:07:31 23:59:59' });
    expect(dateButton()!.getAttribute('aria-label')).toBe('01/07/2026 - 31/07/2026');
  });

  it('a preset reloads the feed over the window and mirrors the whole scope into the URL, keeping group_by', async () => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 9, 23, 12) });
    mount();
    component['onDatePreset']('last_7_days');
    await settle();
    expect(cull.scopeFrom()).toBe('2026-10-17');
    expect(cull.scopeTo()).toBe('2026-10-23');
    expect(scopeCalls()).toHaveLength(1);
    expect(scopeCalls()[0]).toEqual([[], {
      queryParams: { album: null, from: '2026-10-17', to: '2026-10-23', scene: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    }]);
  });

  it('a window picked over a scene drops the scene param', async () => {
    mount({ album: '9', from: '2026-07-01', to: '2026-07-01', scene: '01/07/2026 10:00' });
    component['onDateRange']('2026-08-01', '2026-08-31');
    await settle();
    expect(scopeCalls().at(-1)![1].queryParams).toEqual({ album: '9', from: '2026-08-01', to: '2026-08-31', scene: null });
  });

  it('exitScope resets the feed (plan keys, timers) instead of only reloading groups', () => {
    mount({ album: '9' });
    const reset = vi.spyOn(cull, 'resetForReload').mockImplementation(() => undefined);
    const load = vi.spyOn(cull, 'loadGroups').mockResolvedValue(undefined);
    component['exitScope']();
    expect(reset).toHaveBeenCalledTimes(1);
    expect(load).not.toHaveBeenCalled();
    expect(cull.scopeAlbum()).toBeNull();
  });

  it('All dates nulls only the dates and leaves the album', async () => {
    mount({ album: '9', from: '2026-07-01', to: '2026-07-31' });
    component['onDateRange'](null, null);
    await settle();
    expect(scopeCalls().at(-1)![1].queryParams).toEqual({ album: '9', from: null, to: null, scene: null });
    expect(cull.scopeAlbum()).toBe('9');
  });

  it('does not navigate when router.url already matches the scope', async () => {
    mount({ album: '9', from: '2026-07-01', to: '2026-07-31' }, '/culling?album=9&from=2026-07-01&to=2026-07-31&group_by=burst');
    await settle();
    expect(scopeCalls()).toHaveLength(0);
    cull.scopeTo.set('2026-08-31');
    await settle();
    expect(scopeCalls()).toHaveLength(1);
  });

  it('a window alone leaves the album button unlit and the empty state names the dates', async () => {
    mount({ from: '2026-07-01', to: '2026-07-31' });
    cull.albums.set([{ id: 9, name: 'Trip' } as never]);
    await settle();
    const albumButton = fixture.nativeElement.querySelector('button[aria-label="culling.scope_whole_library"]') as HTMLButtonElement;
    expect(albumButton).not.toBeNull();
    expect(albumButton.className).not.toContain('text-[var(--mat-sys-primary)]');
    expect(fixture.nativeElement.textContent).toContain('culling.date_range.empty');
    expect(fixture.nativeElement.textContent).not.toContain('culling.scene_complete');
  });

  it('keeps the scene wording for an empty scene scope and the plain one for no scope', async () => {
    mount({ album: '9', from: '2026-07-01', to: '2026-07-01', scene: '01/07/2026 10:00' });
    await settle();
    expect(fixture.nativeElement.textContent).toContain('culling.scene_complete');
    TestBed.resetTestingModule();
    mount();
    await settle();
    expect(fixture.nativeElement.textContent).toContain('culling.no_bursts');
  });

  it('keeps the date range when Whole album is picked, in the store and in the URL, and keeps group_by', async () => {
    mount();
    component['onDateRange']('2026-07-01', '2026-07-31');
    await settle();
    navigate.mockClear();
    component['expandedAlbumId'].set(9);
    component['scopeAlbumWhole']();
    await settle();
    expect(cull.scopeAlbum()).toBe('9');
    expect(cull.scopeFrom()).toBe('2026-07-01');
    expect(cull.scopeTo()).toBe('2026-07-31');
    const call = navigate.mock.calls.find(c => c[1]?.queryParams?.album === '9')!;
    expect(call[1].queryParams).toEqual({ album: '9', from: '2026-07-01', to: '2026-07-31', scene: null });
    expect(call[1].queryParamsHandling).toBe('merge');
  });

  it('keeps the date range when Whole library is picked and drops it for a scene\'s own window', async () => {
    mount({ album: '9' });
    component['onDateRange']('2026-07-01', '2026-07-31');
    component['scopeWholeLibrary']();
    await settle();
    expect(cull.scopeAlbum()).toBeNull();
    expect(cull.scopeFrom()).toBe('2026-07-01');
    component['expandedAlbumId'].set(9);
    component['scopeAlbumScene']({ start: '2026:08:01 10:00:00', end: '2026:08:01 10:30:00' } as never);
    await settle();
    expect(cull.scopeFrom()).toBe('2026:08:01 10:00:00');
    component['scopeAlbumWhole']();
    await settle();
    expect(cull.scopeFrom()).toBeNull();
    expect(cull.scopeAlbum()).toBe('9');
  });

  it('applies a custom range only when both ends are set, as plain local dates', async () => {
    mount();
    component['onCustomRangeEnd'](new Date(2026, 6, 1), null);
    await settle();
    expect(cull.dateRangeActive()).toBe(false);
    component['onCustomRangeEnd'](null, new Date(2026, 6, 31));
    expect(cull.dateRangeActive()).toBe(false);
    component['onCustomRangeEnd'](new Date(2026, 6, 1, 23, 30), new Date(2026, 6, 31, 0, 15));
    expect(cull.scopeFrom()).toBe('2026-07-01');
    expect(cull.scopeTo()).toBe('2026-07-31');
  });

  it('keeps the done wording for a dated feed whose groups are all confirmed or hidden', async () => {
    mount({ from: '2026-07-01', to: '2026-07-31' });
    await settle();
    const group = { group_id: 1, type: 'burst', reason: '', photos: [], best_path: '', count: 0 } as never;
    cull.groups.set([group]);
    cull.hiddenGroups.set(new Set(['1_burst']));
    await settle();
    expect(fixture.nativeElement.textContent).toContain('culling.scene_complete');
    expect(fixture.nativeElement.textContent).not.toContain('culling.date_range.empty');
  });

  it('keeps the done wording for a dated plan whose groups were all confirmed', async () => {
    mount({ from: '2026-07-01', to: '2026-07-31' });
    await settle();
    const group = { group_id: 1, type: 'burst', reason: '', photos: [], best_path: '', count: 0 } as never;
    cull.planActive.set(true);
    cull.groups.set([group]);
    cull.hiddenGroups.set(new Set(['1_burst']));
    await settle();
    expect(fixture.nativeElement.textContent).toContain('culling.scene_complete');
    expect(fixture.nativeElement.textContent).not.toContain('culling.date_range.plan_empty');
  });

  it('says the plan has no group in the window while staying in plan mode', async () => {
    mount({ from: '2026-07-01', to: '2026-07-31' });
    cull.planActive.set(true);
    await settle();
    expect(fixture.nativeElement.textContent).toContain('culling.date_range.plan_empty');
  });
});
