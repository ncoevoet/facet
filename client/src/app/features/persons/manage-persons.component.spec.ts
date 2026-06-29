import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PersonsFiltersService } from './persons-filters.service';
import { ManagePersonsComponent } from './manage-persons.component';

describe('ManagePersonsComponent', () => {
  let component: ManagePersonsComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockAuth: { isEdition: Mock };
  let mockI18n: { t: Mock };
  let mockDialog: { open: Mock };
  let mockSnackBar: { open: Mock };

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
    mockAuth = { isEdition: vi.fn(() => true) };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockDialog = {
      open: vi.fn(() => ({ afterClosed: () => of(true) })),
    };
    mockSnackBar = { open: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        ManagePersonsComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
      ],
    });
    component = TestBed.inject(ManagePersonsComponent);
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
});
