import { signal } from '@angular/core';
import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, DefaultUrlSerializer, NavigationEnd, Router } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { By } from '@angular/platform-browser';
import { PersonCardComponent } from '../../shared/components/person-card/person-card.component';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { ApiService } from '../../core/services/api.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { ScanService } from '../../core/services/scan.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { PersonsFiltersService } from './persons-filters.service';
import { ManagePersonsComponent } from './manage-persons.component';
import { FaceReviewQueueComponent } from './face-review-queue.component';
import { FaceUpdateControlComponent } from './face-update-control.component';
import { PageContextService } from '../../core/agent/page-context.service';
import { SameNameMergeDialogComponent } from './same-name-merge.service';

describe('ManagePersonsComponent', () => {
  let component: ManagePersonsComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockAuth: { isEdition: Mock; identity: () => string; status: () => null };
  let mockI18n: { t: Mock; translations: () => object };
  let mockDialog: { open: Mock };
  let mockSnackBar: { open: Mock };
  let journal: { record: Mock };
  let routerEvents: Subject<unknown>;
  /** The Undo action of the last snackbar opened. */
  let snackAction: Subject<void>;

  const mockPersonsResponse = {
    persons: [
      { id: 1, name: 'Alice', face_count: 10, face_thumbnail: true },
      { id: 2, name: 'Bob', face_count: 5, face_thumbnail: true },
      { id: 3, name: null, face_count: 3, face_thumbnail: false },
    ],
    total: 3,
  };

  beforeEach(() => {
    mockApi = {
      get: vi.fn(() => of(mockPersonsResponse)),
      post: vi.fn(() => of({})),
    };
    mockAuth = { status: () => null, isEdition: vi.fn(() => true), identity: () => 'test' };
    mockI18n = { t: vi.fn((key: string) => key), translations: () => ({}) };
    mockDialog = {
      open: vi.fn(() => ({ afterClosed: () => of(true) })),
    };
    snackAction = new Subject<void>();
    mockSnackBar = { open: vi.fn(() => ({ onAction: () => snackAction, afterDismissed: () => new Subject<void>() })) };
    journal = { record: vi.fn() };
    routerEvents = new Subject<unknown>();

    TestBed.configureTestingModule({
      providers: [
        ManagePersonsComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: mockAuth },
        { provide: ScanService, useValue: { canLaunch: signal(false) } },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: UserActivityJournal, useValue: journal },
        { provide: Router, useValue: { url: '/persons', navigate: vi.fn(() => Promise.resolve(true)), currentNavigation: () => null, events: routerEvents, parseUrl: (url: string) => new DefaultUrlSerializer().parse(url) } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    component = TestBed.inject(ManagePersonsComponent);
  });

  describe('a navigation made by the assistant', () => {
    const filters = () => TestBed.inject(PersonsFiltersService);
    const navigated = (url: string) => routerEvents.next(new NavigationEnd(1, url, url));

    it('sets the search to the query and resets the other filters', () => {
      filters().showHidden.set(true);
      filters().sort.set('name');
      filters().sortDirection.set('asc');
      navigated('/persons?search=anna');
      expect(filters().search()).toBe('anna');
      expect(filters().showHidden()).toBe(false);
      expect(filters().sort()).toBe('count');
      expect(filters().sortDirection()).toBe('desc');
    });

    it('removes the search from the URL once applied, replacing the history entry', () => {
      const router = TestBed.inject(Router) as unknown as { navigate: Mock };
      navigated('/persons?search=anna');
      expect(router.navigate).toHaveBeenCalledWith(['/persons'], {
        queryParams: { search: null }, queryParamsHandling: 'merge', replaceUrl: true,
      });
      router.navigate.mockClear();
      filters().search.set('typed by the user');
      navigated('/persons');
      expect(filters().search()).toBe('typed by the user');
      expect(router.navigate).not.toHaveBeenCalled();
    });

    it('clears a previous search when the query is empty', () => {
      filters().search.set('old');
      navigated('/persons?search=');
      expect(filters().search()).toBe('');
    });

    it('leaves the filters alone without a search or on another page', () => {
      filters().search.set('kept');
      navigated('/persons');
      navigated('/albums?search=x');
      expect(filters().search()).toBe('kept');
    });
  });

  describe('page context', () => {
    it('registers the persons page and reads its filters live, without the selection', () => {
      const context = TestBed.inject(PageContextService);
      expect(context.snapshot()).toEqual({ id: 'persons', tab: 'named', search: '', sort: 'count', sort_direction: 'desc', show_hidden: false });
      TestBed.inject(PersonsFiltersService).search.set('ann');
      TestBed.inject(PersonsFiltersService).selectedIds.set(new Set([1]));
      expect(context.snapshot()).toEqual({ id: 'persons', tab: 'named', search: 'ann', sort: 'count', sort_direction: 'desc', show_hidden: false });
    });
  });

  describe('toggleSelect', () => {
    it('should add a person id when checked', () => {
      component.toggleSelect(1, true);
      expect(component.selectedIds().has(1)).toBe(true);
    });

    it('should remove a person id when unchecked', () => {
      component.toggleSelect(1, true);
      component.toggleSelect(1, false);
      expect(component.selectedIds().has(1)).toBe(false);
    });

    it('should handle multiple selections', () => {
      component.toggleSelect(1, true);
      component.toggleSelect(2, true);
      expect(component.selectedIds().size).toBe(2);
      expect(component.selectedIds().has(1)).toBe(true);
      expect(component.selectedIds().has(2)).toBe(true);
    });
  });

  describe('clearSelection', () => {
    it('should clear all selected ids', () => {
      component.toggleSelect(1, true);
      component.toggleSelect(2, true);
      component.clearSelection();
      expect(component.selectedIds().size).toBe(0);
    });
  });

  describe('startEdit / cancelEdit', () => {
    it('should set editingId when starting edit', () => {
      component.startEdit(42);
      expect(component.editingId()).toBe(42);
    });

    it('should clear editingId when cancelling edit', () => {
      component.startEdit(42);
      component.cancelEdit();
      expect(component.editingId()).toBeNull();
    });
  });

  describe('loadPersons', () => {
    it('keeps the latest search rows and total when an older response arrives last', async () => {
      const older = new Subject<typeof mockPersonsResponse>();
      const newer = new Subject<typeof mockPersonsResponse>();
      mockApi.get.mockReturnValueOnce(older).mockReturnValueOnce(newer);
      const filters = TestBed.inject(PersonsFiltersService);
      filters.search.set('A');
      const first = component.loadPersons(true);
      filters.search.set('AB');
      const second = component.loadPersons(true);
      const fresh = { persons: [{ id: 42, name: 'AB', face_count: 1, face_thumbnail: true }], total: 1 };
      newer.next(fresh); await second;
      older.next(mockPersonsResponse); await first;
      expect(component.persons()).toEqual(fresh.persons);
      expect(component.total()).toBe(1);
      expect(filters.search()).toBe('AB');
    });

    it.each(['success', 'failure'])('does not let stale %s settle the newer loading state', async outcome => {
      const older = new Subject<typeof mockPersonsResponse>();
      const newer = new Subject<typeof mockPersonsResponse>();
      mockApi.get.mockReturnValueOnce(older).mockReturnValueOnce(newer);
      const first = component.loadPersons(true);
      const second = component.loadPersons(true);
      if (outcome === 'success') older.next(mockPersonsResponse);
      else older.error(new Error('obsolete read'));
      await first;
      expect(component.loading()).toBe(true);
      expect(component.persons()).toEqual([]);
      expect(mockSnackBar.open).not.toHaveBeenCalled();
      newer.next(mockPersonsResponse); await second;
      expect(component.loading()).toBe(false);
      expect(component.persons()).toEqual(mockPersonsResponse.persons);
    });

    it.each(['owner', 'token', 'destroy'])('refuses a late read after %s changes', async loss => {
      const pending = new Subject<typeof mockPersonsResponse>();
      mockApi.get.mockReturnValueOnce(pending);
      Object.assign(mockAuth, { token: 'original' });
      const reading = component.loadPersons(true);
      if (loss === 'owner') mockAuth.identity = () => 'other';
      else if (loss === 'token') Object.assign(mockAuth, { token: 'rotated' });
      else TestBed.resetTestingModule();
      pending.next(mockPersonsResponse); await reading;
      expect(component.persons()).toEqual([]);
      expect(component.total()).toBe(0);
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    it.each(['success', 'failure'])('settles an invalidated latest %s without publishing stale state', async outcome => {
      const pending = new Subject<typeof mockPersonsResponse>();
      mockApi.get.mockReturnValueOnce(pending);
      Object.assign(mockAuth, { token: 'original' });
      const reading = component.loadPersons(true);
      Object.assign(mockAuth, { token: 'rotated' });
      if (outcome === 'success') pending.next(mockPersonsResponse);
      else pending.error(new Error('obsolete credential'));
      await reading;
      expect(component.loading()).toBe(false);
      expect(component.persons()).toEqual([]);
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    it.each(['owner', 'token'])('reloads through the real effect when %s changes with edition unchanged', async change => {
      const status = signal<object | null>({ revision: 1 });
      const owner = signal('test');
      Object.assign(mockAuth, { status, identity: owner, token: 'original' });
      TestBed.tick();
      await component.ngOnInit();
      const pending = new Subject<typeof mockPersonsResponse>();
      mockApi.get.mockImplementation((url: string) => url === '/persons' ? pending : of({ persons: [] }));
      mockApi.get.mockClear();
      if (change === 'owner') owner.set('other');
      else Object.assign(mockAuth, { token: 'rotated' });
      status.set({ revision: 2 }); TestBed.tick();
      expect(mockApi.get).toHaveBeenCalledOnce();
      expect(component.persons()).toEqual([]);
      expect(component.total()).toBe(0);
      expect(component.loading()).toBe(true);
      pending.next(mockPersonsResponse); await Promise.resolve();
      expect(component.persons()).toEqual(mockPersonsResponse.persons);
      expect(component.loading()).toBe(false);
      status.set({ revision: 3 }); TestBed.tick();
      expect(mockApi.get).toHaveBeenCalledOnce();
    });

    it('discards a pending old page after a new search and preserves subsequent paging', async () => {
      await component.loadPersons(true);
      const oldPage = new Subject<typeof mockPersonsResponse>();
      mockApi.get.mockReturnValueOnce(oldPage);
      const paging = component.loadPersons(false);
      const fresh = { persons: [{ id: 42, name: 'AB', face_count: 1, face_thumbnail: true }], total: 2 };
      mockApi.get.mockReturnValueOnce(of(fresh));
      TestBed.inject(PersonsFiltersService).search.set('AB');
      await component.loadPersons(true);
      oldPage.next(mockPersonsResponse); await paging;
      expect(component.persons()).toEqual(fresh.persons);
      const next = { ...fresh.persons[0], id: 43 };
      mockApi.get.mockReturnValueOnce(of({ persons: [next], total: 2 }));
      await component.loadPersons(false);
      expect(component.persons()).toEqual([...fresh.persons, next]);
      expect(component.total()).toBe(2);
    });

    it('should reset page and clear persons list when reset is true', async () => {
      component.persons.set([
        { id: 99, name: 'Old', face_count: 1, face_thumbnail: false },
      ]);

      await component.loadPersons(true);

      expect(mockApi.get).toHaveBeenCalledWith('/persons', {
        search: '',
        page: 1,
        per_page: 48,
        sort: 'count_desc',
        include_hidden: false,
        named_only: true,
      });
      expect(component.persons()).toEqual(mockPersonsResponse.persons);
      expect(component.total()).toBe(3);
    });

    it('should append to existing persons when reset is false', async () => {
      const existingPerson = { id: 99, name: 'Existing', face_count: 1, face_thumbnail: false };
      component.persons.set([existingPerson]);

      await component.loadPersons(false);

      expect(component.persons()).toEqual([existingPerson, ...mockPersonsResponse.persons]);
    });

    it('should set loading to false after completion', async () => {
      await component.loadPersons(true);
      expect(component.loading()).toBe(false);
    });

    it('should pass search query to API', async () => {
      const personsFilters = TestBed.inject(PersonsFiltersService);
      personsFilters.search.set('alice');
      await component.loadPersons(true);

      expect(mockApi.get).toHaveBeenCalledWith('/persons', {
        search: 'alice',
        page: 1,
        per_page: 48,
        sort: 'count_desc',
        include_hidden: false,
        named_only: true,
      });
    });

    it('should request hidden persons when showHidden is on', async () => {
      const personsFilters = TestBed.inject(PersonsFiltersService);
      personsFilters.showHidden.set(true);

      await component.loadPersons(true);

      expect(mockApi.get).toHaveBeenCalledWith('/persons', {
        search: '',
        page: 1,
        per_page: 48,
        sort: 'count_desc',
        include_hidden: true,
        named_only: false,
      });
    });
  });

  describe('hasMore computed', () => {
    it('should return false when persons length equals total', () => {
      component.persons.set(mockPersonsResponse.persons);
      component.total.set(3);
      expect(component.hasMore()).toBe(false);
    });

    it('should return true when persons length is less than total', () => {
      component.persons.set([mockPersonsResponse.persons[0]]);
      component.total.set(3);
      expect(component.hasMore()).toBe(true);
    });

    it('should return false when both are 0', () => {
      expect(component.hasMore()).toBe(false);
    });
  });

  describe('which persons the grid lists', () => {
    const gridParams = () =>
      mockApi.get.mock.calls.filter((c: unknown[]) => c[0] === '/persons').at(-1)?.[1] as Record<string, unknown>;

    it('lists named persons only while Needs naming is shown (edition)', async () => {
      await component.loadPersons(true);
      expect(gridParams()['named_only']).toBe(true);
    });

    it('lists everyone when read-only, since Needs naming is not shown', async () => {
      mockAuth.isEdition.mockReturnValue(false);
      await component.loadPersons(true);
      expect(gridParams()['named_only']).toBe(false);
    });

    it('lists everyone when showing hidden persons, so hidden unnamed ones can be unhidden', async () => {
      TestBed.inject(PersonsFiltersService).showHidden.set(true);
      await component.loadPersons(true);
      expect(gridParams()['named_only']).toBe(false);
    });

    it('reloads the grid after naming a person with no namesake', async () => {
      mockApi.post.mockReturnValue(of({ success: true, name: 'Zed', same_name_persons: [] }));
      component.needsNaming.set([{ id: 3, name: null, face_count: 5, face_thumbnail: true }]);
      const spy = vi.spyOn(component, 'loadPersons').mockResolvedValue();

      await component.onNeedsNamingSave({ id: 3, name: 'Zed' });

      expect(spy).toHaveBeenCalledWith(true);
    });
  });

  describe('name suggestions', () => {
    it('offers every distinct name once, as the person with the most photos, sorted', async () => {
      mockApi.get.mockReturnValue(of({
        persons: [[2, ' peter salem ', 4], [1, 'Peter Salem', 100], [3, null, 9], [4, 'Anna', 3], [5, '  ', 1]],
      }));

      await component.loadNameOptions();

      expect(mockApi.get).toHaveBeenCalledWith('/filter_options/persons');
      expect(component.nameOptions()).toEqual([
        { id: 4, name: 'Anna', count: 3 },
        { id: 1, name: 'Peter Salem', count: 100 },
      ]);
    });

    it('keeps the previous suggestions when the request fails', async () => {
      component.nameOptions.set([{ id: 4, name: 'Anna', count: 3 }]);
      mockApi.get.mockReturnValue(throwError(() => new Error('down')));

      await component.loadNameOptions();

      expect(component.nameOptions()).toEqual([{ id: 4, name: 'Anna', count: 3 }]);
    });

    it('refreshes the suggestions after a rename with no namesake', async () => {
      mockApi.post.mockReturnValue(of({ success: true, name: 'Zed', same_name_persons: [] }));
      const spy = vi.spyOn(component, 'loadNameOptions').mockResolvedValue();

      await component.saveName({ id: 1, name: null, face_count: 3, face_thumbnail: true }, 'Zed');

      expect(spy).toHaveBeenCalled();
    });
  });

  describe('renaming to a name another person already has', () => {
    const peter = { id: 1, name: null, face_count: 10, face_thumbnail: true };
    const sameName = [
      { id: 5, name: 'Peter Salem', face_count: 77 },
      { id: 6, name: 'PETER SALEM', face_count: 4 },
    ];

    beforeEach(() => {
      component.persons.set([peter]);
      mockApi.post.mockImplementation((url: string) =>
        of(url.endsWith('/rename') ? { success: true, name: 'peter salem', same_name_persons: sameName } : {}),
      );
    });

    it('shows the named cluster and every namesake, and folds the picked ones into the largest', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of([1, 5, 6]) });

      await component.saveName(peter, 'peter salem');

      expect(mockDialog.open).toHaveBeenCalledWith(SameNameMergeDialogComponent, expect.objectContaining({
        data: { name: 'peter salem', current: { id: 1, name: 'peter salem', face_count: 10 }, persons: sameName },
      }));
      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge_batch', {
        merges: [
          { source_id: 1, target_id: 5 },
          { source_id: 6, target_id: 5 },
        ],
      });
      expect(mockApi.get).toHaveBeenCalled();
    });

    it('merges only the persons left picked, into the largest of those', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of([1, 6]) });

      await component.saveName(peter, 'peter salem');

      // 5 stays apart; of the cluster (10 faces) and 6 (4 faces), the cluster is larger.
      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge_batch', {
        merges: [{ source_id: 6, target_id: 1 }],
      });
    });

    it('keeps the clusters apart when the merge is declined, and still refreshes the page', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of(null) });
      component.needsNaming.set([{ id: 1, name: null, face_count: 10, face_thumbnail: true }]);
      const grid = vi.spyOn(component, 'loadPersons').mockResolvedValue();
      const names = vi.spyOn(component, 'loadNameOptions').mockResolvedValue();

      await component.onNeedsNamingSave({ id: 1, name: 'peter salem' });

      expect(mockApi.post).not.toHaveBeenCalledWith('/persons/merge_batch', expect.anything());
      expect(grid).toHaveBeenCalledWith(true);
      expect(names).toHaveBeenCalled();
      expect(component.needsNaming()).toEqual([]);
    });

    it('offers the same merge when naming from the needs-naming section', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of([1, 5, 6]) });
      component.needsNaming.set([{ id: 1, name: null, face_count: 100, face_thumbnail: true }]);

      await component.onNeedsNamingSave({ id: 1, name: 'peter salem' });

      // The renamed cluster is now the largest, so it keeps the others.
      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge_batch', {
        merges: [
          { source_id: 5, target_id: 1 },
          { source_id: 6, target_id: 1 },
        ],
      });
    });

    it('asks nothing when no other person has the name', async () => {
      mockApi.post.mockReturnValue(of({ success: true, name: 'Zed', same_name_persons: [] }));

      await component.saveName(peter, 'Zed');

      expect(mockDialog.open).not.toHaveBeenCalled();
    });
  });

  describe('ignoring people', () => {
    const waiter = { id: 7, name: null, face_count: 6, face_thumbnail: true };

    it('loads the Ignored section from the hidden persons, with their total', async () => {
      mockApi.get.mockReturnValue(of({ persons: [{ ...waiter, is_hidden: true }], total: 1 }));

      await component.loadIgnored();

      expect(mockApi.get).toHaveBeenCalledWith('/persons', { hidden_only: true, offset: 0, per_page: 200, sort: 'count_desc' });
      expect(component.ignored().map((p) => p.id)).toEqual([7]);
      expect(component.ignoredTotal()).toBe(1);
    });

    it('pages the Ignored section instead of stopping at 200', async () => {
      mockApi.get.mockReturnValue(of({ persons: [{ ...waiter, is_hidden: true }], total: 201 }));
      await component.loadIgnored();
      mockApi.get.mockReturnValue(of({ persons: [{ ...waiter, id: 8, is_hidden: true }], total: 201 }));

      await component.loadMoreIgnored();

      expect(mockApi.get).toHaveBeenLastCalledWith('/persons', { hidden_only: true, offset: 1, per_page: 200, sort: 'count_desc' });
      expect(component.ignored().map((p) => p.id)).toEqual([7, 8]);
      expect(component.ignoredTotal()).toBe(201);
    });

    it('ends the Ignored section when a page brings no new person, so scrolling stops asking', async () => {
      mockApi.get.mockReturnValue(of({ persons: [{ ...waiter, is_hidden: true }], total: 2 }));
      await component.loadIgnored();
      mockApi.get.mockReturnValue(of({ persons: [], total: 2 }));
      await component.loadMoreIgnored();
      expect(component.ignoredTotal()).toBe(1);
      mockApi.get.mockClear();
      await component.loadMoreIgnored();
      expect(mockApi.get).not.toHaveBeenCalled();
    });

    it('restoring from a full first page asks for the row after the loaded ones, so nobody is skipped', async () => {
      let server = Array.from({ length: 250 }, (_, i) => ({ id: i + 1, name: null, face_count: 1000 - i, face_thumbnail: true, is_hidden: true }));
      mockApi.get.mockImplementation((_url: string, params?: { hidden_only?: boolean; page?: number; offset?: number; per_page?: number }) => {
        if (!params?.hidden_only) return of({ persons: [], total: 0 });
        const perPage = params.per_page ?? 48;
        const start = params.offset ?? ((params.page ?? 1) - 1) * perPage;
        return of({ persons: server.slice(start, start + perPage), total: server.length });
      });
      vi.spyOn(component, 'loadNeedsNaming').mockResolvedValue();
      await component.loadIgnored();

      await component.setHidden(5, false);
      server = server.filter((p) => p.id !== 5);
      await component.loadMoreIgnored();

      expect(component.ignored().map((p) => p.id)).toEqual(server.map((p) => p.id));
      expect(component.ignoredTotal()).toBe(249);
    });

    it('places a newly ignored person among equal face counts by id, as the server orders them', async () => {
      const hidden = (id: number) => ({ id, name: null, face_count: 5, face_thumbnail: true, is_hidden: true });
      component.ignored.set([hidden(1), hidden(9)]);
      component.ignoredTotal.set(10);
      component.needsNaming.set([{ ...waiter, id: 5, face_count: 5 }]);
      vi.spyOn(component, 'loadNeedsNaming').mockResolvedValue();

      await component.setHidden(5, true);

      expect(component.ignored().map((p) => p.id)).toEqual([1, 5, 9]);
      expect(component.ignoredTotal()).toBe(11);
    });

    it('does not load the Ignored section for a read-only user', async () => {
      mockAuth.isEdition.mockReturnValue(false);

      await component.loadIgnored();

      expect(mockApi.get).not.toHaveBeenCalledWith('/persons', expect.objectContaining({ hidden_only: true }));
    });

    it('ignoring from Needs naming takes the group out of it', async () => {
      component.needsNaming.set([waiter, { id: 8, name: null, face_count: 3, face_thumbnail: true }]);

      await component.setHidden(7, true);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/7/hide');
      expect(component.needsNaming().map((p) => p.id)).toEqual([8]);
    });

    it('ignoring and restoring keep the Ignored pages already loaded', async () => {
      const page = Array.from({ length: 3 }, (_, i) => ({ id: 100 + i, name: null, face_count: 30 - i * 10, face_thumbnail: true, is_hidden: true }));
      component.ignored.set(page);
      component.ignoredTotal.set(3);
      component.needsNaming.set([{ ...waiter, face_count: 15 }]);
      const reload = vi.spyOn(component, 'loadIgnored');
      vi.spyOn(component, 'loadNeedsNaming').mockResolvedValue();

      await component.setHidden(7, true);

      expect(reload).not.toHaveBeenCalled();
      expect(component.ignored().map((p) => p.id)).toEqual([100, 101, 7, 102]);
      expect(component.ignoredTotal()).toBe(4);

      await component.setHidden(101, false);

      expect(component.ignored().map((p) => p.id)).toEqual([100, 7, 102]);
      expect(component.ignoredTotal()).toBe(3);
    });

    it('restoring takes the person out of Ignored and reloads Needs naming', async () => {
      component.ignored.set([{ ...waiter, is_hidden: true }]);
      const spy = vi.spyOn(component, 'loadNeedsNaming').mockResolvedValue();

      await component.setHidden(7, false);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/7/unhide');
      expect(component.ignored()).toEqual([]);
      expect(spy).toHaveBeenCalled();
    });

    it('Delete finds a person that is only in the Ignored section', () => {
      component.persons.set([]);
      component.ignored.set([{ ...waiter, is_hidden: true }]);
      const spy = vi.spyOn(component, 'deletePerson').mockResolvedValue();

      component.onDelete(7);

      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
    });

    it('deleting an ignored person removes it and leaves the grid total alone', async () => {
      const ignoredWaiter = { ...waiter, is_hidden: true };
      component.ignored.set([ignoredWaiter]);
      component.total.set(10);

      await component.deletePerson(ignoredWaiter);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/7/delete');
      expect(component.ignored()).toEqual([]);
      expect(component.total()).toBe(10);
    });
  });

  describe('find more faces', () => {
    it('opens for a person that is only in the needs-naming section', async () => {
      component.persons.set([]);
      component.needsNaming.set([{ id: 9, name: null, face_count: 40, face_thumbnail: true }]);
      mockDialog.open.mockReturnValue({ afterClosed: () => of({ added: 0 }) });

      component.onFindMore(9);
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalled());

      expect(mockDialog.open.mock.calls[0][1].data).toEqual({ personId: 9, personName: null });
    });

    it('reloads both lists after faces were added', async () => {
      component.persons.set([{ id: 1, name: 'Alice', face_count: 10, face_thumbnail: true }]);
      mockDialog.open.mockReturnValue({ afterClosed: () => of({ added: 3 }) });
      mockApi.get.mockClear();

      await component.findMoreFaces(component.persons()[0]);

      const urls = mockApi.get.mock.calls.map((c: unknown[]) => c[0]);
      expect(urls).toContain('/persons');
      expect(urls).toContain('/persons/needs_naming');
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('does nothing for an unknown id', () => {
      component.persons.set([]);
      component.needsNaming.set([]);
      component.onFindMore(404);
      expect(mockDialog.open).not.toHaveBeenCalled();
    });
  });

  describe('saveName', () => {
    it('should skip save if name is empty after trimming', async () => {
      const person = { id: 1, name: 'Alice', face_count: 10, face_thumbnail: true };
      component.startEdit(1);

      await component.saveName(person, '   ');

      expect(mockApi.post).not.toHaveBeenCalled();
      expect(component.editingId()).toBeNull();
    });

    it('should skip save if name is same as current', async () => {
      const person = { id: 1, name: 'Alice', face_count: 10, face_thumbnail: true };
      component.startEdit(1);

      await component.saveName(person, 'Alice');

      expect(mockApi.post).not.toHaveBeenCalled();
      expect(component.editingId()).toBeNull();
    });

    it('should post rename and update person in list', async () => {
      component.persons.set([
        { id: 1, name: 'Alice', face_count: 10, face_thumbnail: true },
        { id: 2, name: 'Bob', face_count: 5, face_thumbnail: true },
      ]);
      const person = component.persons()[0];
      component.startEdit(1);

      await component.saveName(person, 'Alicia');

      expect(mockApi.post).toHaveBeenCalledWith('/persons/1/rename', { name: 'Alicia' });
      expect(component.persons()[0].name).toBe('Alicia');
      expect(component.editingId()).toBeNull();
    });
  });

  describe('batchDelete', () => {
    it('should do nothing if no selection', async () => {
      await component.batchDelete();
      expect(mockDialog.open).not.toHaveBeenCalled();
    });

    it('should open confirm dialog and post delete on confirmation', async () => {
      component.persons.set(mockPersonsResponse.persons);
      component.toggleSelect(1, true);
      component.toggleSelect(2, true);

      await component.batchDelete();

      expect(mockDialog.open).toHaveBeenCalled();
      expect(mockApi.post).toHaveBeenCalledWith('/persons/delete_batch', {
        person_ids: [1, 2],
      });
    });

    it('should not delete if dialog is dismissed', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of(false) });
      component.toggleSelect(1, true);

      await component.batchDelete();

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('openMergeDialog', () => {
    it('should do nothing if fewer than 2 selected', async () => {
      component.toggleSelect(1, true);
      await component.openMergeDialog();
      expect(mockDialog.open).not.toHaveBeenCalled();
    });

    it('should open merge target dialog when 2+ selected', async () => {
      component.persons.set(mockPersonsResponse.persons);
      component.toggleSelect(1, true);
      component.toggleSelect(2, true);

      // Dialog returns a target id
      mockDialog.open.mockReturnValue({ afterClosed: () => of(1) });

      await component.openMergeDialog();

      expect(mockDialog.open).toHaveBeenCalled();
    });
  });

  describe('showHidden toggle (filters service)', () => {
    it('should flip the shared signal the way the toolbar button does', () => {
      const personsFilters = TestBed.inject(PersonsFiltersService);
      expect(personsFilters.showHidden()).toBe(false);

      personsFilters.showHidden.set(!personsFilters.showHidden());
      expect(personsFilters.showHidden()).toBe(true);

      personsFilters.showHidden.set(!personsFilters.showHidden());
      expect(personsFilters.showHidden()).toBe(false);
    });
  });

  describe('setHidden', () => {
    it('should post hide and drop the person when hidden persons are not shown', async () => {
      component.persons.set(mockPersonsResponse.persons);
      component.total.set(3);

      await component.setHidden(1, true);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/1/hide');
      expect(component.persons().some((p) => p.id === 1)).toBe(false);
      expect(component.total()).toBe(2);
    });

    it('should post hide and mark the person hidden when showHidden is on', async () => {
      const personsFilters = TestBed.inject(PersonsFiltersService);
      personsFilters.showHidden.set(true);
      component.persons.set(mockPersonsResponse.persons);

      await component.setHidden(1, true);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/1/hide');
      expect(component.persons().find((p) => p.id === 1)?.is_hidden).toBe(true);
      expect(component.persons().some((p) => p.id === 1)).toBe(true);
    });

    it('should post unhide and clear the hidden flag', async () => {
      component.persons.set([
        { id: 1, name: 'Alice', face_count: 10, face_thumbnail: true, is_hidden: true },
      ]);

      await component.setHidden(1, false);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/1/unhide');
      expect(component.persons().find((p) => p.id === 1)?.is_hidden).toBe(false);
    });
  });

  describe('Ignore undo', () => {
    beforeEach(() => {
      component.persons.set(mockPersonsResponse.persons);
      component.total.set(3);
    });

    it('Ignore on /persons shows the notification with Undo for 10 s', async () => {
      await component.setHidden(1, true);
      expect(mockSnackBar.open).toHaveBeenCalledWith('persons.hidden_done', 'undo.action', { duration: 10_000 });
    });

    it('Undo calls unhide and reloads the lists rather than restoring a stale snapshot', async () => {
      await component.setHidden(2, true);
      expect(component.persons().map((p) => p.id)).toEqual([1, 3]);
      // Another change lands between the ignore and the undo: the server's lists now differ.
      const fresh = { ...mockPersonsResponse, persons: [mockPersonsResponse.persons[0], mockPersonsResponse.persons[1]], total: 2 };
      mockApi.get.mockImplementation(() => of(fresh));
      mockApi.get.mockClear();
      snackAction.next();
      await new Promise((r) => setTimeout(r));
      expect(mockApi.post).toHaveBeenCalledWith('/persons/2/unhide');
      expect(mockApi.get).toHaveBeenCalled();
      expect(component.persons().map((p) => p.id)).toEqual([1, 2]);
      expect(mockSnackBar.open).toHaveBeenLastCalledWith('undo.restored', '', { duration: 2000 });
    });

    it('a failed restore reports the translated error and keeps the person ignored', async () => {
      await component.setHidden(2, true);
      mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
      snackAction.next();
      await new Promise((r) => setTimeout(r));
      expect(component.persons().some((p) => p.id === 2)).toBe(false);
      expect(mockSnackBar.open).toHaveBeenLastCalledWith('undo.restore_failed', '', { duration: 3000 });
    });

    it('without Undo the ignore stays: no restore call after the 10 s', async () => {
      vi.useFakeTimers();
      try {
        await component.setHidden(2, true);
        await vi.advanceTimersByTimeAsync(11_000);
        expect(mockApi.post).not.toHaveBeenCalledWith('/persons/2/unhide');
        expect(component.persons().some((p) => p.id === 2)).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('splitPerson', () => {
    it('should do nothing when the dialog is cancelled', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of(null) });
      const person = { id: 1, name: 'Alice', face_count: 10, face_thumbnail: true };

      await component.splitPerson(person);

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should post the selected face ids and prepend the new person', async () => {
      component.persons.set([
        { id: 1, name: 'Alice', face_count: 10, face_thumbnail: true },
      ]);
      component.total.set(1);
      mockDialog.open.mockReturnValue({
        afterClosed: () => of({ faceIds: [11, 12], name: 'Alice B' }),
      });
      mockApi.post.mockReturnValue(
        of({ success: true, new_person_id: 99, new_count: 2, source_count: 8 }),
      );

      await component.splitPerson(component.persons()[0]);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/1/split', {
        face_ids: [11, 12],
        name: 'Alice B',
      });
      expect(component.persons()[0].id).toBe(99);
      expect(component.persons()[0].face_count).toBe(2);
      expect(component.persons().find((p) => p.id === 1)?.face_count).toBe(8);
      expect(component.total()).toBe(2);
    });

    it('should drop the source person when it is emptied', async () => {
      component.persons.set([
        { id: 1, name: 'Alice', face_count: 2, face_thumbnail: true },
      ]);
      component.total.set(1);
      mockDialog.open.mockReturnValue({
        afterClosed: () => of({ faceIds: [11, 12], name: null }),
      });
      mockApi.post.mockReturnValue(
        of({ success: true, new_person_id: 99, new_count: 2, source_count: 0 }),
      );

      await component.splitPerson(component.persons()[0]);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/1/split', { face_ids: [11, 12] });
      expect(component.persons().some((p) => p.id === 1)).toBe(false);
      expect(component.persons()[0].id).toBe(99);
      expect(component.total()).toBe(1);
    });
  });

  describe('user activity journal', () => {
    const alice = { id: 1, name: 'Alice', face_count: 10, face_thumbnail: true };

    beforeEach(() => {
      component.persons.set(mockPersonsResponse.persons);
    });

    it('journals a needs-naming rename with the id and the trimmed name, and nothing on failure', async () => {
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('boom')));
      await component.onNeedsNamingSave({ id: 3, name: 'Carol' });
      expect(journal.record).not.toHaveBeenCalled();
      await component.onNeedsNamingSave({ id: 3, name: ' Carol ' });
      expect(journal.record).toHaveBeenCalledTimes(1);
      expect(journal.record).toHaveBeenCalledWith('person', [], { action: 'rename', person_id: 3, name: 'Carol' });
    });

    it('journals a person created from the dialog, and nothing when cancelled or failed', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of(null) });
      await component.openNewPersonDialog();
      mockDialog.open.mockReturnValue({ afterClosed: () => of('Zoe') });
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('boom')));
      await component.openNewPersonDialog();
      expect(journal.record).not.toHaveBeenCalled();
      mockApi.post.mockReturnValueOnce(of({ id: 12, name: 'Zoe', face_count: 0 }));
      await component.openNewPersonDialog();
      expect(journal.record).toHaveBeenCalledTimes(1);
      expect(journal.record).toHaveBeenCalledWith('person', [], { action: 'create', person_id: 12, name: 'Zoe' });
    });

    it('journals a rename with the id and the typed name, and nothing on failure', async () => {
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('boom')));
      await component.saveName(alice, 'Alicia');
      expect(journal.record).not.toHaveBeenCalled();
      await component.saveName(alice, 'Alicia');
      expect(journal.record).toHaveBeenCalledTimes(1);
      expect(journal.record).toHaveBeenCalledWith('person', [], { action: 'rename', person_id: 1, name: 'Alicia' });
    });

    it('journals a delete, a hide and an unhide with the id', async () => {
      await component.deletePerson(alice);
      await component.setHidden(2, true);
      await component.setHidden(2, false);
      expect(journal.record.mock.calls.map(c => c[2])).toEqual([
        { action: 'delete', person_id: 1 },
        { action: 'hide', person_id: 2 },
        { action: 'unhide', person_id: 2 },
      ]);
    });

    it('journals a split with the number of faces moved', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of({ faceIds: [11, 12], name: null }) });
      mockApi.post.mockReturnValue(of({ success: true, new_person_id: 99, new_count: 2, source_count: 8 }));
      await component.splitPerson(alice);
      expect(journal.record).toHaveBeenCalledWith('person', [], { action: 'split', person_id: 1, count: 2 });
    });

    it('journals a batch delete as one entry with a count', async () => {
      component.toggleSelect(1, true);
      component.toggleSelect(2, true);
      await component.batchDelete();
      expect(journal.record).toHaveBeenCalledTimes(1);
      expect(journal.record).toHaveBeenCalledWith('person', [], { action: 'delete', count: 2 });
    });

    it('journals a single merge with its pair and a multi merge with a count only', async () => {
      component.toggleSelect(1, true);
      component.toggleSelect(2, true);
      await (component as any).mergeIntoTarget(1);
      expect(journal.record).toHaveBeenLastCalledWith('person', [], { action: 'merge', count: 1, pairs: [[2, 1]] });
      component.toggleSelect(2, true);
      component.toggleSelect(3, true);
      await (component as any).mergeIntoTarget(1);
      expect(journal.record).toHaveBeenLastCalledWith('person', [], { action: 'merge', count: 2 });
    });

    it('journals only the merges that landed, flagged partial, when a later one fails', async () => {
      component.toggleSelect(1, true);
      component.toggleSelect(2, true);
      component.toggleSelect(3, true);
      mockApi.post.mockReturnValueOnce(of({})).mockReturnValueOnce(throwError(() => new Error('boom')));
      await (component as any).mergeIntoTarget(1);
      expect(journal.record).toHaveBeenCalledTimes(1);
      expect(journal.record).toHaveBeenCalledWith('person', [], { action: 'merge', count: 1, partial: true });
    });

    it('journals nothing when the first merge fails', async () => {
      component.toggleSelect(1, true);
      component.toggleSelect(2, true);
      mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
      await (component as any).mergeIntoTarget(1);
      expect(journal.record).not.toHaveBeenCalled();
    });
  });

  describe('tabs', () => {
    const NAMED = { persons: [{ id: 1, name: 'Alice', face_count: 10, face_thumbnail: true }], total: 1 };
    const WAITING = { id: 7, name: null, face_count: 4, face_thumbnail: true };
    let named: { persons: unknown[]; total: number };
    let waiting: unknown[];

    function withTab(tab: string | null): void {
      const route = TestBed.inject(ActivatedRoute) as unknown as { snapshot: { queryParamMap: { get: (k: string) => string | null } } };
      route.snapshot.queryParamMap.get = (k: string) => (k === 'tab' ? tab : null);
    }

    async function render() {
      const fixture = TestBed.createComponent(ManagePersonsComponent);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      return fixture;
    }

    const labels = (el: HTMLElement) =>
      ([...el.querySelectorAll('[role="tab"]')] as HTMLElement[]).map((t) => ({
        text: t.textContent!.replace(/\s+/g, ' ').trim(),
        selected: t.getAttribute('aria-selected') === 'true',
      }));

    beforeEach(() => {
      named = { ...NAMED };
      waiting = [WAITING];
      mockApi.get.mockImplementation((url: string, params?: { hidden_only?: boolean }) => {
        if (url === '/persons/needs_naming') return of({ persons: waiting, total: waiting.length });
        if (url === '/filter_options/persons') return of({ persons: [] });
        if (params?.hidden_only) return of({ persons: [], total: 0 });
        return of(named);
      });
    });

    it('loads the next Ignored page on scroll, and stops on a failure until Retry', async () => {
      const original = mockApi.get.getMockImplementation()!;
      const hidden = (id: number) => ({ id, name: null, face_count: 2, face_thumbnail: true, is_hidden: true });
      mockApi.get.mockImplementation((url: string, params?: { hidden_only?: boolean; offset?: number }) =>
        params?.hidden_only ? of({ persons: [hidden(101 + (params.offset ?? 0))], total: 3 }) : original(url, params));
      withTab(null);
      const fixture = await render();
      fixture.componentInstance.ignoredExpanded.set(true); fixture.detectChanges();
      const root = fixture.nativeElement as HTMLElement;
      const sentinel = () => root.querySelector('[data-ignored-more] [data-ignored-sentinel]');
      const reach = () => fixture.debugElement.query(By.css('[data-ignored-sentinel]')).injector.get(InfiniteScrollDirective).scrollReached.emit();
      expect(sentinel()).not.toBeNull();
      expect(root.textContent).not.toContain('persons.load_more');
      mockApi.get.mockImplementationOnce(() => throwError(() => ({ status: 500 })));
      reach(); await fixture.whenStable(); fixture.detectChanges();
      expect(sentinel()).toBeNull();
      expect(root.querySelector('[data-ignored-more] [role="alert"]')?.textContent).toContain('persons.ignored_more_error');
      root.querySelector<HTMLButtonElement>('[data-ignored-retry]')!.click();
      await fixture.whenStable(); fixture.detectChanges();
      expect(mockApi.get).toHaveBeenLastCalledWith('/persons', { hidden_only: true, offset: 1, per_page: 200, sort: 'count_desc' });
      expect(fixture.componentInstance.ignored().map((p) => p.id)).toEqual([101, 102]);
      expect(root.querySelector('[data-ignored-more] [role="alert"]')).toBeNull();
      expect(sentinel()).not.toBeNull();
      reach(); await fixture.whenStable(); fixture.detectChanges();
      expect(fixture.componentInstance.ignored().map((p) => p.id)).toEqual([101, 102, 103]);
      expect(root.querySelector('[data-ignored-more]')).toBeNull();
    });

    it('opens on Named first, even with persons waiting for a name', async () => {
      withTab(null);
      const fixture = await render();
      expect(fixture.componentInstance.tab()).toBe('named');
      expect(labels(fixture.nativeElement)).toEqual([
        { text: 'manage_persons.named (1)', selected: true },
        { text: 'manage_persons.needs_naming (1)', selected: false },
        { text: 'persons.review_queue.matches', selected: false },
        { text: 'persons.review_queue.unassigned', selected: false },
      ]);
    });

    it('reloads captured match choices only after the explicit face-update review action', async () => {
      withTab('matches');
      (TestBed.inject(Router) as unknown as { url: string }).url = '/persons?tab=matches';
      Object.assign(mockAuth, { status: signal({ user_id: 'test' }), token: 'fixture' });
      const original = mockApi.get.getMockImplementation()!;
      mockApi.get.mockImplementation((url: string, params: unknown) => url === '/faces/review' ? of({
        faces: [{ face_id: 9, photo_path: '/nine.jpg', identity_token: 'a'.repeat(64), embedding_state: 'ready', suggestions: [{ person_id: 1, name: 'Alice', similarity: 0.9 }] }],
        total_unassigned: 1, next_after_id: null, model: 'arcface_buffalo_l', compared_people: 1, suggestions_requested: true,
      }) : original(url, params));
      const fixture = await render();
      const root = fixture.nativeElement as HTMLElement;
      document.body.appendChild(root);
      root.querySelector<HTMLButtonElement>('app-face-review-queue [data-review-tile]')!.focus();
      root.querySelector<HTMLButtonElement>('app-face-review-queue [data-review-tile]')!.click(); fixture.detectChanges();
      const queue = fixture.debugElement.query(By.directive(FaceReviewQueueComponent)).componentInstance;
      expect(queue.selected().has(9)).toBe(true);
      const before = mockApi.get.mock.calls.filter(([url]) => url === '/faces/review').length;
      fixture.debugElement.query(By.directive(FaceUpdateControlComponent)).componentInstance.reviewRequested.emit();
      await fixture.whenStable(); fixture.detectChanges();
      await fixture.whenStable(); fixture.detectChanges();
      expect(mockApi.get.mock.calls.filter(([url]) => url === '/faces/review')).toHaveLength(before + 1);
      expect(queue.selected().size).toBe(0);
      expect(root.querySelector<HTMLButtonElement>('app-face-review-queue [data-review-tile]')!.getAttribute('aria-pressed')).toBe('false');
      expect(document.activeElement).toBe(root.querySelector('app-face-review-queue'));
      root.remove();
    });

    it('keeps a persons selection from Named but hides its bar on the review tabs, which have their own', async () => {
      withTab(null);
      Object.assign(mockAuth, { isEdition: signal(true), status: signal({ user_id: 'test' }), token: 'fixture' });
      const original = mockApi.get.getMockImplementation()!;
      mockApi.get.mockImplementation((url: string, params: unknown) => url === '/faces/review' ? of({ faces: [], total_unassigned: 0, next_after_id: null, model: 'arcface_buffalo_l', compared_people: 0, suggestions_requested: true }) : original(url, params));
      const fixture = await render(); const root = fixture.nativeElement as HTMLElement;
      const bar = () => [...root.querySelectorAll('button')].some(button => button.textContent?.includes('persons.merge_action'));
      TestBed.inject(PersonsFiltersService).selectedIds.set(new Set([1])); fixture.detectChanges();
      expect(bar()).toBe(true);
      routerEvents.next(new NavigationEnd(5, '/persons?tab=matches', '/persons?tab=matches')); fixture.detectChanges();
      expect(fixture.componentInstance.tab()).toBe('matches');
      expect(bar()).toBe(false);
      expect(fixture.componentInstance.selectedIds().has(1)).toBe(true);
      routerEvents.next(new NavigationEnd(6, '/persons?tab=named', '/persons?tab=named')); fixture.detectChanges();
      expect(bar()).toBe(true);
      fixture.destroy();
    });

    it('moves focus to the matches queue after the face-update review action changes tabs', async () => {
      withTab(null);
      Object.assign(mockAuth, { isEdition: signal(true), status: signal({ user_id: 'test' }), token: 'fixture' });
      const fixture = await render(); const root = fixture.nativeElement as HTMLElement;
      document.body.appendChild(root);
      fixture.debugElement.query(By.directive(FaceUpdateControlComponent)).componentInstance.reviewRequested.emit();
      await fixture.whenStable(); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      expect(fixture.componentInstance.tab()).toBe('matches');
      expect(document.activeElement).toBe(root.querySelector('app-face-review-queue'));
      root.remove();
    });

    it('does not move focus when the matches navigation is refused', async () => {
      withTab(null);
      Object.assign(mockAuth, { isEdition: signal(true), status: signal({ user_id: 'test' }), token: 'fixture' });
      const router = TestBed.inject(Router) as unknown as { navigate: Mock };
      router.navigate.mockResolvedValueOnce(false);
      const fixture = await render(); const root = fixture.nativeElement as HTMLElement;
      document.body.appendChild(root);
      const trigger = root.querySelector<HTMLElement>('[role="tab"]')!; trigger.focus();
      fixture.debugElement.query(By.directive(FaceUpdateControlComponent)).componentInstance.reviewRequested.emit();
      await fixture.whenStable(); fixture.detectChanges();
      expect(fixture.componentInstance.tab()).toBe('named'); expect(document.activeElement).toBe(trigger);
      root.remove();
    });

    it('exposes global review destinations without duplicating the Named toolbar', async () => {
      withTab('matches');
      const router = TestBed.inject(Router) as unknown as { url: string; navigate: Mock };
      router.url = '/persons?tab=matches';
      const edition = signal(true);
      Object.assign(mockAuth, { isEdition: edition, status: signal({ user_id: 'test' }), token: 'fixture' });
      const original = mockApi.get.getMockImplementation()!;
      mockApi.get.mockImplementation((url: string, params: unknown) => url === '/faces/review' ? of({ faces: [], total_unassigned: 0, next_after_id: null, model: 'arcface_buffalo_l', compared_people: 0, suggestions_requested: true }) : original(url, params));
      const fixture = await render();
      expect(fixture.componentInstance.tab()).toBe('matches');
      expect(labels(fixture.nativeElement)[2].selected).toBe(true);
      expect(fixture.nativeElement.querySelectorAll('app-face-review-queue')).toHaveLength(1);
      expect(TestBed.inject(HeaderSlotService).template()).toBeNull();
      expect(mockApi.get).toHaveBeenCalledWith('/faces/review', expect.objectContaining({ suggest: true }));
      routerEvents.next(new NavigationEnd(5, '/persons?tab=unassigned', '/persons?tab=unassigned'));
      expect(fixture.componentInstance.tab()).toBe('unassigned');
      edition.set(false); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('app-face-review-queue')).toBeNull();
      expect(TestBed.inject(HeaderSlotService).template()).not.toBeNull();
      fixture.destroy();
    });

    it('restores the previous tab when a requested tab navigation is refused', async () => {
      const router = TestBed.inject(Router) as unknown as { navigate: Mock };
      router.navigate.mockResolvedValueOnce(false);
      component.selectTab('matches');
      await Promise.resolve();
      expect(component.tab()).toBe('named');
    });

    it('restores the previous tab after navigation rejects', async () => {
      const router = TestBed.inject(Router) as unknown as { navigate: Mock };
      router.navigate.mockRejectedValueOnce(new Error('navigation failed'));
      expect(await component.selectTab('matches')).toBe(false);
      expect(component.tab()).toBe('named');
    });

    it.each(['refused', 'rejected'] as const)('ignores an old %s completion after tab ABA navigation', async ending => {
      const router = TestBed.inject(Router) as unknown as { navigate: Mock };
      let settle!: (value: boolean) => void, reject!: (error: Error) => void;
      router.navigate.mockReturnValueOnce(new Promise<boolean>((resolve, fail) => { settle = resolve; reject = fail; }));
      const first = component.selectTab('matches');
      await component.selectTab('unassigned'); await component.selectTab('matches');
      if (ending === 'refused') settle(false); else reject(new Error('obsolete navigation'));
      expect(await first).toBe(false); expect(component.tab()).toBe('matches');
    });

    it.each(['edition', 'navigation'] as const)('does not launch updated-face review while %s blocks it', state => {
      const router = TestBed.inject(Router) as unknown as { navigate: Mock; currentNavigation: () => unknown };
      if (state === 'edition') mockAuth.isEdition.mockReturnValue(false);
      else router.currentNavigation = () => ({ id: 1 });
      (component as any).reviewUpdatedFaces();
      expect(router.navigate).not.toHaveBeenCalled(); expect(component.tab()).toBe('named');
    });

    it('requests the matches tab from another tab without reloading a nonexistent queue', async () => {
      const router = TestBed.inject(Router) as unknown as { navigate: Mock };
      router.navigate.mockResolvedValueOnce(false);
      (component as any).reviewUpdatedFaces(); await Promise.resolve();
      expect(router.navigate).toHaveBeenCalledExactlyOnceWith([], { queryParams: { tab: 'matches' }, queryParamsHandling: 'merge', replaceUrl: true });
      expect(component.tab()).toBe('named');
    });

    it.each(['owner', 'token', 'edition', 'focus', 'destroyed'] as const)('does not steal focus after updated-face review when %s changes during navigation', async ending => {
      withTab(null);
      Object.assign(mockAuth, { isEdition: signal(true), status: signal({ user_id: 'test' }), token: 'fixture' });
      const original = mockApi.get.getMockImplementation()!;
      mockApi.get.mockImplementation((url: string, params: unknown) => url === '/faces/review'
        ? of({ faces: [], total_unassigned: 0, next_after_id: null, model: 'arcface_buffalo_l', compared_people: 0, suggestions_requested: true }) : original(url, params));
      const fixture = await render(); const root = fixture.nativeElement as HTMLElement;
      document.body.appendChild(root);
      let finish!: (value: boolean) => void;
      const router = TestBed.inject(Router) as unknown as { navigate: Mock };
      router.navigate.mockReturnValueOnce(new Promise<boolean>(resolve => { finish = resolve; }));
      fixture.debugElement.query(By.directive(FaceUpdateControlComponent)).componentInstance.reviewRequested.emit();
      fixture.detectChanges();
      const queue = fixture.debugElement.query(By.directive(FaceReviewQueueComponent)).componentInstance;
      const focus = vi.spyOn(queue, 'focus');
      const newer = document.createElement('button'); document.body.appendChild(newer);
      if (ending === 'owner') mockAuth.identity = () => 'bob';
      if (ending === 'token') Object.assign(mockAuth, { token: 'rotated' });
      if (ending === 'edition') (mockAuth.isEdition as unknown as ReturnType<typeof signal<boolean>>).set(false);
      if (ending === 'focus') newer.focus();
      if (ending === 'destroyed') fixture.destroy();
      finish(true);
      if (ending !== 'destroyed') { await fixture.whenStable(); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges(); }
      else await Promise.resolve();
      expect(focus).not.toHaveBeenCalled();
      if (ending === 'focus') expect(document.activeElement).toBe(newer);
      if (ending !== 'destroyed') fixture.destroy();
      root.remove(); newer.remove();
    });

    it('?tab=naming opens Needs naming, and switching writes ?tab back', async () => {
      withTab('naming');
      const fixture = await render();
      expect(fixture.componentInstance.tab()).toBe('naming');
      expect(labels(fixture.nativeElement)[1].selected).toBe(true);
      expect(fixture.nativeElement.querySelector('app-person-card')).not.toBeNull();
      const router = TestBed.inject(Router) as unknown as { navigate: Mock };
      (fixture.nativeElement.querySelectorAll('[role="tab"]')[0] as HTMLElement).click();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      await fixture.whenStable();
      expect(fixture.componentInstance.tab()).toBe('named');
      expect(router.navigate).toHaveBeenCalledWith([], { queryParams: { tab: 'named' }, queryParamsHandling: 'merge', replaceUrl: true });
      (fixture.nativeElement.querySelectorAll('[role="tab"]')[1] as HTMLElement).click();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      await fixture.whenStable();
      expect(router.navigate).toHaveBeenLastCalledWith([], { queryParams: { tab: 'naming' }, queryParamsHandling: 'merge', replaceUrl: true });
    });

    it('read-only shows the Named grid alone, with no tab bar, whatever ?tab says', async () => {
      mockAuth.isEdition.mockReturnValue(false);
      withTab('naming');
      const fixture = await render();
      expect(fixture.nativeElement.querySelector('mat-tab-group')).toBeNull();
      expect(fixture.nativeElement.querySelectorAll('[role="tab"]').length).toBe(0);
      expect(fixture.nativeElement.querySelectorAll('app-person-card').length).toBe(1);
      expect(mockApi.get).not.toHaveBeenCalledWith('/persons/needs_naming');
    });

    it('naming the last person moves the counts and leaves an empty state', async () => {
      withTab('naming');
      mockApi.post.mockReturnValue(of({ success: true, name: 'Zoe', face_count: 4, same_name_persons: [] }));
      const fixture = await render();
      named = { persons: [...NAMED.persons, { id: 7, name: 'Zoe', face_count: 4, face_thumbnail: true }], total: 2 };
      await fixture.componentInstance.onNeedsNamingSave({ id: 7, name: 'Zoe' });
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(labels(fixture.nativeElement).map((l) => l.text)).toEqual([
        'manage_persons.named (2)',
        'manage_persons.needs_naming (0)',
        'persons.review_queue.matches',
        'persons.review_queue.unassigned',
      ]);
      expect(fixture.nativeElement.querySelector('[data-needs-naming-empty]')).not.toBeNull();
    });

    it('the Needs naming sort reorders its cards', async () => {
      waiting = [
        { id: 7, name: null, face_count: 4, face_thumbnail: true },
        { id: 9, name: null, face_count: 2, face_thumbnail: true },
        { id: 8, name: null, face_count: 12, face_thumbnail: true },
      ];
      withTab('naming');
      const fixture = await render();
      const order = () => fixture.debugElement.queryAll(By.directive(PersonCardComponent))
        .map((d) => (d.componentInstance as PersonCardComponent).person().id);
      // The toolbar is projected into the shell's header slot; render it here.
      const toolbar = TestBed.inject(HeaderSlotService).template()!.createEmbeddedView(null);
      toolbar.detectChanges();
      const inToolbar = (sel: string) => toolbar.rootNodes
        .map((n: Node) => (n instanceof Element ? (n.matches(sel) ? n : n.querySelector(sel)) : null))
        .find(Boolean) as HTMLElement | undefined;
      expect(inToolbar('[data-naming-sort]')).toBeDefined();
      expect(order()).toEqual([8, 7, 9]);
      fixture.componentInstance.namingSort.set('recent');
      fixture.detectChanges();
      expect(order()).toEqual([9, 8, 7]);
      inToolbar('[data-naming-sort-direction]')!.click();
      fixture.detectChanges();
      expect(order()).toEqual([7, 8, 9]);
      toolbar.destroy();
    });

    describe('Update faces placement', () => {
      const control = (el: HTMLElement) => el.querySelector('app-face-update-control') as HTMLElement;

      beforeEach(() => {
        (TestBed.inject(ScanService) as unknown as { canLaunch: ReturnType<typeof signal<boolean>> }).canLaunch.set(true);
      });

      it('is the last item of the page-actions bar template, after the labelled create button that carries ml-auto', async () => {
        withTab('named');
        const fixture = await render();
        const toolbar = TestBed.inject(HeaderSlotService).template()!.createEmbeddedView(null);
        toolbar.detectChanges();
        const elements = toolbar.rootNodes.filter((n: Node): n is HTMLElement => n instanceof HTMLElement);
        const last = elements[elements.length - 1];
        expect(last.tagName.toLowerCase()).toBe('app-face-update-control');
        expect(last.className).not.toContain('ml-auto');
        const create = elements.find(e => e.tagName === 'BUTTON' && e.textContent!.includes('manage_persons.new_person'))!;
        expect(create.className).toContain('ml-auto');
        expect(create.className).toContain('mat-mdc-unelevated-button');
        expect(create.querySelector('mat-icon')!.textContent!.trim()).toBe('person_add');
        expect(create.getAttribute('aria-label')).toBeNull();
        expect(elements.indexOf(create)).toBeLessThan(elements.indexOf(last));
        toolbar.destroy();
        fixture.destroy();
      });

      it('adds no left margin of its own to the bar items, so the first control sits at 16px', async () => {
        withTab('named');
        const fixture = await render();
        const toolbar = TestBed.inject(HeaderSlotService).template()!.createEmbeddedView(null);
        toolbar.detectChanges();
        const fields = toolbar.rootNodes.filter((n: Node): n is HTMLElement => n instanceof HTMLElement && n.matches('mat-form-field'));
        expect(fields.length).toBeGreaterThan(0);
        expect(fields.every(f => !f.classList.contains('ml-2'))).toBe(true);
        toolbar.destroy();
        fixture.destroy();
      });

      it('is a right-aligned row above the tabs at every in-page width, hidden at lg+ while the bar shows it', async () => {
        withTab('named');
        const fixture = await render();
        const inPage = control(fixture.nativeElement);
        const classes = inPage.className.split(/\s+/);
        expect(classes).toEqual(expect.arrayContaining(['ml-auto', 'block', 'w-fit', 'lg:hidden']));
        expect(classes.some(c => c.endsWith('absolute'))).toBe(false);
        expect(inPage.nextElementSibling!.tagName.toLowerCase()).toBe('mat-tab-group');
        fixture.destroy();
      });

      it('collapses its in-page host (no mb-2 gap above the tabs) when launching is not allowed', async () => {
        (TestBed.inject(ScanService) as unknown as { canLaunch: ReturnType<typeof signal<boolean>> }).canLaunch.set(false);
        withTab('named');
        const fixture = await render();
        const inPage = control(fixture.nativeElement);
        expect(Array.from(inPage.childNodes).filter(n => n.nodeType !== Node.COMMENT_NODE)).toHaveLength(0);
        expect(inPage.classList).toContain('empty:hidden');
        fixture.destroy();
      });

      it('keeps its in-page host unchanged when launching is allowed', async () => {
        withTab('named');
        const fixture = await render();
        const inPage = control(fixture.nativeElement);
        expect(inPage.querySelector('[data-update-faces]')).not.toBeNull();
        expect(Array.from(inPage.classList)).toEqual(expect.arrayContaining(['ml-auto', 'mb-2', 'block', 'w-fit']));
        fixture.destroy();
      });

      it('stays reachable in the page on the review tabs, where the bar is cleared', async () => {
        withTab('matches');
        Object.assign(mockAuth, { isEdition: signal(true), status: signal({ user_id: 'test' }), token: 'fixture' });
        const fixture = await render();
        expect(TestBed.inject(HeaderSlotService).template()).toBeNull();
        const inPage = control(fixture.nativeElement);
        expect(inPage).not.toBeNull();
        expect(inPage.className).not.toContain('lg:hidden');
        fixture.destroy();
      });
    });

    describe('restore-only cards', () => {
      const IGNORED = { id: 55, name: 'Staff', face_count: 2, face_thumbnail: true, is_hidden: true };

      beforeEach(() => {
        mockApi.get.mockImplementation((url: string, params?: { hidden_only?: boolean }) => {
          if (url === '/persons/needs_naming') return of({ persons: waiting, total: waiting.length });
          if (url === '/filter_options/persons') return of({ persons: [] });
          if (params?.hidden_only) return of({ persons: [IGNORED], total: 1 });
          return of(named);
        });
      });

      const cards = (fixture: ComponentFixture<ManagePersonsComponent>) =>
        fixture.debugElement.queryAll(By.directive(PersonCardComponent))
          .map((d) => ({
            id: (d.componentInstance as PersonCardComponent).person().id,
            restoreOnly: (d.componentInstance as PersonCardComponent).restoreOnly(),
            labels: [...(d.nativeElement as HTMLElement).querySelectorAll('button[aria-label]')]
              .map((b) => b.getAttribute('aria-label')),
          }));

      // The card's actions live in a lazily rendered ⋮ menu: open it and read the item labels.
      const menuItems = (fixture: ComponentFixture<ManagePersonsComponent>, id: number): string[] => {
        const card = fixture.debugElement.queryAll(By.directive(PersonCardComponent))
          .find((d) => (d.componentInstance as PersonCardComponent).person().id === id)!;
        (card.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('button[aria-label="nav.more"]')!.click();
        fixture.detectChanges();
        return [...document.querySelectorAll('.mat-mdc-menu-panel button[mat-menu-item] .mat-mdc-menu-item-text > span')].map((e) => e.textContent!.trim());
      };

      it('Ignored cards are restore-only: Restore and Delete are all the menu offers', async () => {
        withTab(null);
        const fixture = await render();
        fixture.componentInstance.ignoredExpanded.set(true);
        fixture.detectChanges();
        const ignored = cards(fixture).find((c) => c.id === 55)!;
        expect(ignored.restoreOnly).toBe(true);
        expect(menuItems(fixture, 55)).toEqual(['persons.unhide', 'persons.delete']);
      });

      it('Named cards are not restore-only', async () => {
        withTab(null);
        const fixture = await render();
        fixture.componentInstance.ignoredExpanded.set(true);
        fixture.detectChanges();
        const alice = cards(fixture).find((c) => c.id === 1)!;
        expect(alice.restoreOnly).toBe(false);
        expect(alice.labels).toEqual(['persons.view_photos', 'nav.more']);
        expect(menuItems(fixture, 1)).toEqual(expect.arrayContaining(['persons.rename', 'persons.split', 'persons.find_more']));
      });

      it('Needs naming cards are not restore-only', async () => {
        withTab('naming');
        const fixture = await render();
        const waitingCard = cards(fixture).find((c) => c.id === 7)!;
        expect(waitingCard.restoreOnly).toBe(false);
        expect(waitingCard.labels).toContain('persons.find_more');
      });
    });

    it('ignoring a person waiting for a name leaves the Named count alone', async () => {
      withTab('naming');
      const fixture = await render();
      await fixture.componentInstance.setHidden(7, true);
      fixture.detectChanges();
      expect(labels(fixture.nativeElement).map((l) => l.text)).toEqual([
        'manage_persons.named (1)',
        'manage_persons.needs_naming (0)',
        'persons.review_queue.matches',
        'persons.review_queue.unassigned',
      ]);
    });
  });
});
