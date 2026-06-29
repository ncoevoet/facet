import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { MergeSuggestionsComponent } from './merge-suggestions.component';

describe('MergeSuggestionsComponent', () => {
  let component: MergeSuggestionsComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockI18n: { t: Mock };
  let mockDialog: { open: Mock };
  let mockSnackBar: { open: Mock };

  const makeSuggestion = (
    id1: number,
    name1: string | null,
    count1: number,
    id2: number,
    name2: string | null,
    count2: number,
    similarity = 0.85,
  ) => ({
    person1: { id: id1, name: name1, face_count: count1 },
    person2: { id: id2, name: name2, face_count: count2 },
    similarity,
  });

  beforeEach(() => {
    mockApi = {
      get: vi.fn(() => of({ suggestions: [] })),
      post: vi.fn(() => of({})),
    };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockDialog = {
      open: vi.fn(() => ({ afterClosed: () => of(null) })),
    };
    mockSnackBar = { open: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        MergeSuggestionsComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: mockSnackBar },
      ],
    });
    component = TestBed.inject(MergeSuggestionsComponent);
  });

  describe('initial state', () => {
    it('should have empty suggestions', () => {
      expect(component.suggestions()).toEqual([]);
    });

    it('should have loading as false', () => {
      expect(component.loading()).toBe(false);
    });

    it('should have merging as false', () => {
      expect(component.merging()).toBe(false);
    });
  });

  describe('hasSuggestions computed', () => {
    it('should return false when no suggestions', () => {
      expect(component.hasSuggestions()).toBe(false);
    });

    it('should return true when suggestions exist', () => {
      component.suggestions.set([makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5)]);
      expect(component.hasSuggestions()).toBe(true);
    });
  });

  describe('rejectSuggestion', () => {
    it('should remove the suggestion from the list', () => {
      const s1 = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      const s2 = makeSuggestion(3, 'Carol', 8, 4, 'Dave', 3);
      component.suggestions.set([s1, s2]);

      component.rejectSuggestion(s1);

      expect(component.suggestions()).toEqual([s2]);
    });

    it('should leave other suggestions intact', () => {
      const s1 = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      const s2 = makeSuggestion(3, 'Carol', 8, 4, 'Dave', 3);
      const s3 = makeSuggestion(5, 'Eve', 12, 6, 'Frank', 7);
      component.suggestions.set([s1, s2, s3]);

      component.rejectSuggestion(s2);

      expect(component.suggestions()).toEqual([s1, s3]);
    });
  });

  describe('mergeInto', () => {
    it('should merge person2 into person1 when person1 is clicked', async () => {
      const suggestion = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      component.suggestions.set([suggestion]);

      await component.mergeInto(suggestion, suggestion.person1);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge', {
        source_id: 2,
        target_id: 1,
      });
    });

    it('should merge person1 into person2 when person2 is clicked', async () => {
      const suggestion = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      component.suggestions.set([suggestion]);

      await component.mergeInto(suggestion, suggestion.person2);

      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge', {
        source_id: 1,
        target_id: 2,
      });
    });

    it('should remove suggestion from list after successful merge', async () => {
      const s1 = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      const s2 = makeSuggestion(3, 'Carol', 8, 4, 'Dave', 3);
      component.suggestions.set([s1, s2]);

      await component.mergeInto(s1, s1.person1);

      expect(component.suggestions()).toEqual([s2]);
    });

    it('should show success snackbar after merge', async () => {
      const suggestion = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      component.suggestions.set([suggestion]);

      await component.mergeInto(suggestion, suggestion.person1);

      expect(mockSnackBar.open).toHaveBeenCalledWith('persons.merged', '', { duration: 2000 });
    });

    it('should show error snackbar on API failure', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('Network error')));
      const suggestion = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      component.suggestions.set([suggestion]);

      await component.mergeInto(suggestion, suggestion.person1);

      expect(mockSnackBar.open).toHaveBeenCalledWith('persons.merge_error', '', { duration: 3000 });
    });

    it('should set merging to false after completion', async () => {
      const suggestion = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      component.suggestions.set([suggestion]);

      await component.mergeInto(suggestion, suggestion.person1);

      expect(component.merging()).toBe(false);
    });

    it('should set merging to false after error', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));
      const suggestion = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      component.suggestions.set([suggestion]);

      await component.mergeInto(suggestion, suggestion.person1);

      expect(component.merging()).toBe(false);
    });
  });

  describe('confirmAcceptAll', () => {
    it('should run the batch merge when confirmed', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of(true) });
      component.suggestions.set([makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5)]);

      await component.confirmAcceptAll();

      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge_batch', {
        merges: [{ source_id: 2, target_id: 1 }],
      });
    });

    it('should not merge when the confirmation is dismissed', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of(null) });
      component.suggestions.set([makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5)]);

      await component.confirmAcceptAll();

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('acceptAll', () => {
    it('should post batch merge with correct source/target for all suggestions', async () => {
      const s1 = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);   // source=2, target=1
      const s2 = makeSuggestion(3, 'Carol', 3, 4, 'Dave', 8);   // source=3, target=4
      component.suggestions.set([s1, s2]);

      await component.acceptAll();

      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge_batch', {
        merges: [
          { source_id: 2, target_id: 1 },
          { source_id: 3, target_id: 4 },
        ],
      });
    });

    it('should clear all suggestions after success', async () => {
      component.suggestions.set([
        makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5),
        makeSuggestion(3, 'Carol', 8, 4, 'Dave', 3),
      ]);

      await component.acceptAll();

      expect(component.suggestions()).toEqual([]);
    });

    it('should show batch success snackbar', async () => {
      component.suggestions.set([
        makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5),
        makeSuggestion(3, 'Carol', 8, 4, 'Dave', 3),
      ]);

      await component.acceptAll();

      expect(mockSnackBar.open).toHaveBeenCalledWith('persons.batch_merged', '', { duration: 2000 });
      expect(mockI18n.t).toHaveBeenCalledWith('persons.batch_merged', { count: 2 });
    });

    it('should set merging to false after completion', async () => {
      component.suggestions.set([makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5)]);

      await component.acceptAll();

      expect(component.merging()).toBe(false);
    });

    it('should show error snackbar on failure', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));
      component.suggestions.set([makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5)]);

      await component.acceptAll();

      expect(mockSnackBar.open).toHaveBeenCalledWith('persons.merge_error', '', { duration: 3000 });
      expect(component.merging()).toBe(false);
    });
  });

  describe('ngOnInit', () => {
    it('should load suggestions from API', async () => {
      const suggestions = [makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5)];
      mockApi.get.mockReturnValue(of({ suggestions }));

      await component.ngOnInit();

      expect(mockApi.get).toHaveBeenCalledWith('/merge_suggestions', { threshold: 0.6 });
      expect(component.suggestions()).toEqual(suggestions);
    });

    it('should set loading to false after loading', async () => {
      await component.ngOnInit();
      expect(component.loading()).toBe(false);
    });

    it('should show error snackbar on load failure', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));

      await component.ngOnInit();

      expect(mockSnackBar.open).toHaveBeenCalledWith('persons.error_loading', '', { duration: 3000 });
      expect(component.loading()).toBe(false);
    });
  });
});
