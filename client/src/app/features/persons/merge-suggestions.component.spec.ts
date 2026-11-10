import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { from, of, throwError } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { GalleryStore } from '../gallery/gallery.store';
import { MergeSuggestionsComponent } from './merge-suggestions.component';

describe('MergeSuggestionsComponent', () => {
  let component: MergeSuggestionsComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockI18n: { t: Mock };
  let mockDialog: { open: Mock };
  let mockSnackBar: { open: Mock };
  let journal: { record: Mock };
  const storeConfig = signal<{ face_merge_threshold?: number } | null>(null);

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
    storeConfig.set(null);
    mockApi = {
      get: vi.fn(() => of({ suggestions: [], threshold: 0.6 })),
      post: vi.fn(() => of({})),
    };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockDialog = {
      open: vi.fn(() => ({ afterClosed: () => of(null) })),
    };
    mockSnackBar = { open: vi.fn() };
    journal = { record: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        MergeSuggestionsComponent,
        { provide: AuthService, useValue: { isEdition: signal(true) } },
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: UserActivityJournal, useValue: journal },
        { provide: GalleryStore, useValue: { config: storeConfig } },
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

  describe('user activity journal', () => {
    it('journals a single merge with its pair, and nothing when it fails', async () => {
      const suggestion = makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5);
      component.suggestions.set([suggestion]);
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('fail')));
      await component.mergeInto(suggestion, suggestion.person1);
      expect(journal.record).not.toHaveBeenCalled();
      await component.mergeInto(suggestion, suggestion.person1);
      expect(journal.record).toHaveBeenCalledTimes(1);
      expect(journal.record).toHaveBeenCalledWith('person', [], { action: 'merge', count: 1, pairs: [[2, 1]] });
    });

    it('journals a batch merge as one entry, never partial: the endpoint is atomic and folds overlapping pairs', async () => {
      const list = [makeSuggestion(1, 'Alice', 10, 2, 'Bob', 5), makeSuggestion(3, 'Carol', 3, 4, 'Dave', 8)];
      component.suggestions.set(list);
      mockApi.post.mockReturnValueOnce(of({ merged_count: 2 }));
      await component.acceptAll();
      expect(journal.record).toHaveBeenLastCalledWith('person', [], { action: 'merge', count: 2 });
      component.suggestions.set(list);
      mockApi.post.mockReturnValueOnce(of({ merged_count: 1 }));
      await component.acceptAll();
      expect(journal.record).toHaveBeenLastCalledWith('person', [], { action: 'merge', count: 1 });
      journal.record.mockClear();
      component.suggestions.set(list);
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('fail')));
      await component.acceptAll();
      expect(journal.record).not.toHaveBeenCalled();
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
      mockApi.get.mockReturnValue(of({ suggestions, threshold: 0.6 }));

      await component.ngOnInit();

      expect(mockApi.get).toHaveBeenCalledWith('/merge_suggestions', {});
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

  describe('per-model default threshold', () => {
    afterEach(() => vi.useRealTimers());

    it('sends no threshold on the first load and seeds the slider from the server default', async () => {
      mockApi.get.mockReturnValue(of({ suggestions: [], threshold: 0.45 }));

      expect(component.threshold()).toBeNull();
      await component.ngOnInit();

      expect(mockApi.get).toHaveBeenCalledWith('/merge_suggestions', {});
      expect(component.threshold()).toBe(0.45);
    });

    it('shows the config default before the first response arrives', async () => {
      storeConfig.set({ face_merge_threshold: 0.65 });
      let resolve!: (v: unknown) => void;
      const deferred = new Promise((r) => (resolve = r));
      mockApi.get.mockReturnValue(from(deferred));

      const loading = component.ngOnInit();
      expect(component.sliderValue()).toBe(0.65);
      expect(mockApi.get).toHaveBeenCalledWith('/merge_suggestions', {});

      resolve({ suggestions: [], threshold: 0.65 });
      await loading;
      expect(component.sliderValue()).toBe(0.65);
    });

    it('stays hidden until the response when the config carries no default', () => {
      expect(component.sliderValue()).toBeNull();
    });

    it('sends the threshold only after the user moves the slider', async () => {
      vi.useFakeTimers();
      mockApi.get.mockReturnValue(of({ suggestions: [], threshold: 0.45 }));
      await component.ngOnInit();

      component.onThresholdChange(0.7);
      await vi.advanceTimersByTimeAsync(300);

      expect(mockApi.get).toHaveBeenLastCalledWith('/merge_suggestions', { threshold: 0.7 });
      expect(component.threshold()).toBe(0.7);
    });
  });
});

describe('MergeSuggestionsComponent layout', () => {
  function render() {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: { isEdition: signal(true) } },
        { provide: ApiService, useValue: { get: vi.fn(() => of({ suggestions: [], threshold: 0.6 })), post: vi.fn(() => of({})) } },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key), translations: () => ({}) } },
        { provide: MatDialog, useValue: { open: vi.fn() } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: UserActivityJournal, useValue: { record: vi.fn() } },
        { provide: GalleryStore, useValue: { config: signal(null) } },
      ],
    });
    const fixture = TestBed.createComponent(MergeSuggestionsComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('insets its content 16px (px-4) like the other pages, not centred in a padded column', () => {
    const content = render().querySelector('div.w-full') as HTMLElement;
    expect(content.className).toContain('px-4');
    expect(content.className).toContain('pt-4');
    expect(content.className).toContain('pb-20');
    expect(content.className).not.toContain('md:p-6');
    expect(content.className).not.toContain('mx-auto');
    expect(content.className).not.toContain('max-w-');
  });

  it('docks its toolbar on the shared 56px row below lg, without a padding or gap of its own', () => {
    const bar = render().querySelector('.max-lg\\:fixed') as HTMLElement;
    for (const cls of ['max-lg:min-h-14', 'max-lg:items-center', 'max-lg:gap-1', 'max-lg:px-2', 'max-lg:py-1']) expect(bar.classList.contains(cls)).toBe(true);
    for (const cls of ['max-lg:px-4', 'max-lg:py-2', 'gap-3']) expect(bar.classList.contains(cls)).toBe(false);
  });
});
