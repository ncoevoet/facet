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
  let mockApi: { get: jest.Mock; post: jest.Mock };
  let mockSnackBar: { open: jest.Mock };
  let mockI18n: { t: jest.Mock };
  let mockAuth: { isEdition: jest.Mock };
  let compareFilters: { selectedCategory: ReturnType<typeof signal<string>> };

  beforeEach(() => {
    mockApi = {
      get: jest.fn(() => of({ snapshots: [] })),
      post: jest.fn(() => of({})),
    };
    mockSnackBar = { open: jest.fn() };
    mockI18n = { t: jest.fn((key: string) => key) };
    mockAuth = { isEdition: jest.fn(() => true) };
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
      mockApi.get.mockReturnValue(of({ snapshots }));

      await component.loadSnapshots();

      expect(mockApi.get).toHaveBeenCalledWith('/config/weight_snapshots', { category: 'portrait' });
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

      expect(mockApi.get).toHaveBeenCalledWith('/config/weight_snapshots', { category: 'portrait' });
    });

    it('should do nothing with empty name', async () => {
      component.snapshotName.set('   ');

      await component.saveSnapshot();

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('restoreSnapshot', () => {
    it('should post correct payload and emit restored', async () => {
      const emitSpy = jest.spyOn(component.restored, 'emit');
      mockApi.post.mockReturnValue(of({}));

      await component.restoreSnapshot(42);

      expect(mockApi.post).toHaveBeenCalledWith('/config/restore_weights', { snapshot_id: 42 });
      expect(emitSpy).toHaveBeenCalled();
      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.snapshot_restored', '', { duration: 3000 });
    });

    it('should show error snackbar on failure', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('fail')));

      await component.restoreSnapshot(1);

      expect(mockSnackBar.open).toHaveBeenCalledWith('comparison.error_restoring_snapshot', '', { duration: 4000 });
    });
  });
});
