import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { CompareFiltersService } from './compare-filters.service';
import { ComparisonSnapshotsTabComponent } from './comparison-snapshots-tab.component';

describe('ComparisonSnapshotsTabComponent', () => {
  let component: ComparisonSnapshotsTabComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockSnackBar: { open: Mock };
  let mockI18n: { t: Mock };
  let mockAuth: { isEdition: Mock };
  let compareFilters: { selectedCategory: ReturnType<typeof signal<string>> };

  beforeEach(() => {
    mockApi = {
      get: vi.fn(() => of({ snapshots: [] })),
      post: vi.fn(() => of({})),
    };
    mockSnackBar = { open: vi.fn() };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockAuth = { isEdition: vi.fn(() => true) };
    compareFilters = { selectedCategory: signal('portrait') };

    TestBed.configureTestingModule({
      providers: [
        ComparisonSnapshotsTabComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: AuthService, useValue: mockAuth },
        { provide: CompareFiltersService, useValue: compareFilters },
      ],
    });
    component = TestBed.inject(ComparisonSnapshotsTabComponent);
  });

  describe('loadSnapshots', () => {
    it('should load and set snapshots', async () => {
      const snapshots = [
        { id: 1, description: 'Baseline', category: 'portrait', weights: { aesthetic_percent: 30 }, timestamp: '2026-02-20' },
        { id: 2, description: 'Tuned', category: 'portrait', weights: { aesthetic_percent: 35 }, timestamp: '2026-02-21' },
      ];
      mockApi.get.mockReturnValue(of({ snapshots, has_more: false }));

      await component.loadSnapshots();

      expect(mockApi.get).toHaveBeenCalledWith('/config/weight_snapshots', { offset: 0, limit: 20, category: 'portrait' });
      expect(component.snapshots()).toEqual(snapshots);
    });

    it('should set empty array when response has no snapshots', async () => {
      mockApi.get.mockReturnValue(of({}));

      await component.loadSnapshots();

      expect(component.snapshots()).toEqual([]);
    });

    it('should show snackbar on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));

      await component.loadSnapshots();

      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.error_loading_snapshots', '', { duration: 4000 });
    });
  });

  describe('saveSnapshot', () => {
    it('should post correct payload and clear name', async () => {
      component.snapshotName.set('My Snapshot');
      mockApi.post.mockReturnValue(of({}));
      mockApi.get.mockReturnValue(of({ snapshots: [] }));

      await component.saveSnapshot();

      expect(mockApi.post).toHaveBeenCalledWith('/config/save_snapshot', {
        category: 'portrait',
        description: 'My Snapshot',
      });
      expect(component.snapshotName()).toBe('');
      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.snapshot_saved', '', { duration: 3000 });
    });

    it('should reload snapshots after save', async () => {
      component.snapshotName.set('Test');
      mockApi.post.mockReturnValue(of({}));
      mockApi.get.mockReturnValue(of({ snapshots: [{ id: 1, description: 'Test', category: 'portrait', weights: {}, timestamp: '' }] }));

      await component.saveSnapshot();

      expect(mockApi.get).toHaveBeenCalledWith('/config/weight_snapshots', { offset: 0, limit: 20, category: 'portrait' });
    });

    it('should do nothing with empty name', async () => {
      component.snapshotName.set('   ');

      await component.saveSnapshot();

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('restoreSnapshot', () => {
    it('should post correct payload, emit restored, and flag scores stale', async () => {
      const emitSpy = vi.spyOn(component.restored, 'emit');
      mockApi.post.mockReturnValue(of({ category: 'portrait' }));

      await component.restoreSnapshot(42);

      expect(mockApi.post).toHaveBeenCalledWith('/config/restore_weights', { snapshot_id: 42 });
      expect(emitSpy).toHaveBeenCalled();
      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.snapshot_restored', '', { duration: 3000 });
      expect(component.scoresStale()).toBe('portrait');
    });

    it('should show error snackbar on failure', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));

      await component.restoreSnapshot(1);

      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.error_restoring_snapshot', '', { duration: 4000 });
    });
  });

  describe('recalculate', () => {
    it('should recompute the stale category and clear the flag', async () => {
      component.scoresStale.set('portrait');
      mockApi.post.mockReturnValue(of({ success: true }));

      await component.recalculate();

      expect(mockApi.post).toHaveBeenCalledWith('/stats/categories/recompute', { category: 'portrait' });
      expect(component.scoresStale()).toBeNull();
      expect(component.recomputing()).toBe(false);
    });

    it('should do nothing when no category is stale', async () => {
      component.scoresStale.set(null);

      await component.recalculate();

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should keep the stale flag on error', async () => {
      component.scoresStale.set('portrait');
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));

      await component.recalculate();

      expect(component.scoresStale()).toBe('portrait');
      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.error_recalculating', '', { duration: 4000 });
    });
  });

  describe('infinite scroll', () => {
    it('should append the next page and track has_more', async () => {
      const page1 = [{ id: 1, description: 'a', category: 'portrait', weights: {}, timestamp: '' }];
      const page2 = [{ id: 2, description: 'b', category: 'portrait', weights: {}, timestamp: '' }];
      mockApi.get.mockReturnValueOnce(of({ snapshots: page1, has_more: true }));
      await component.loadSnapshots();
      expect(component.snapshots().length).toBe(1);
      expect(component.hasMoreSnapshots()).toBe(true);

      mockApi.get.mockReturnValueOnce(of({ snapshots: page2, has_more: false }));
      await component.loadMoreSnapshots();
      expect(component.snapshots().map(s => s.id)).toEqual([1, 2]);
      expect(component.hasMoreSnapshots()).toBe(false);
      expect(mockApi.get).toHaveBeenLastCalledWith('/config/weight_snapshots', { offset: 1, limit: 20, category: 'portrait' });
    });

    it('should not load more once has_more is false', async () => {
      mockApi.get.mockReturnValueOnce(of({ snapshots: [], has_more: false }));
      await component.loadSnapshots();
      mockApi.get.mockClear();

      await component.loadMoreSnapshots();

      expect(mockApi.get).not.toHaveBeenCalled();
    });
  });
});
