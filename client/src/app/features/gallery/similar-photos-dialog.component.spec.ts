import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { SimilarPhotosDialogComponent } from './similar-photos-dialog.component';
import { ApiService } from '../../core/services/api.service';

describe('SimilarPhotosDialogComponent', () => {
  const mockDialogRef = { close: jest.fn() };
  let mockApi: { get: jest.Mock };

  const selectedPaths = signal(new Set<string>());
  const togglePath = jest.fn((path: string) => {
    const next = new Set(selectedPaths());
    if (next.has(path)) next.delete(path); else next.add(path);
    selectedPaths.set(next);
  });

  const dialogData = {
    photoPath: '/photos/test.jpg',
    selectedPaths,
    togglePath,
  };

  const mockObserve = jest.fn();
  const mockDisconnect = jest.fn();

  beforeAll(() => {
    (window as any).IntersectionObserver = jest.fn().mockImplementation(() => ({
      observe: mockObserve,
      disconnect: mockDisconnect,
    }));
  });

  const makePhoto = (i: number) => ({
    path: `/p${i}.jpg`,
    filename: `p${i}.jpg`,
    similarity: 0.8,
    aggregate: 7,
    aesthetic: 6,
    date_taken: null,
  });

  const makeResponse = (similar: object[], has_more = false) => ({
    similar,
    total: similar.length,
    has_more,
  });

  const createComponent = () => {
    TestBed.configureTestingModule({
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: dialogData },
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: ApiService, useValue: mockApi },
      ],
    });
    return TestBed.runInInjectionContext(() => new SimilarPhotosDialogComponent());
  };

  beforeEach(() => {
    jest.clearAllMocks();
    selectedPaths.set(new Set());
    mockApi = { get: jest.fn() };
  });

  describe('initial load', () => {
    it('starts in loading state before ngOnInit completes', () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      const component = createComponent();
      expect(component.loading()).toBe(true);
      expect(component.loadingMore()).toBe(false);
      expect(component.results()).toEqual([]);
    });

    it('clears loading and populates results after successful load', async () => {
      const photos = [makePhoto(0), makePhoto(1)];
      mockApi.get.mockReturnValue(of(makeResponse(photos)));
      const component = createComponent();
      await component.ngOnInit();
      expect(component.loading()).toBe(false);
      expect(component.loadingMore()).toBe(false);
      expect(component.results()).toHaveLength(2);
      expect(component.results()[0].path).toBe('/p0.jpg');
    });

    it('calls API with offset=0 and limit=20 on first load', async () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      const component = createComponent();
      await component.ngOnInit();
      expect(mockApi.get).toHaveBeenCalledWith(
        `/similar_photos/${encodeURIComponent('/photos/test.jpg')}`,
        { limit: 20, offset: 0 },
      );
    });

    it('shows empty results when no similar photos found', async () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      const component = createComponent();
      await component.ngOnInit();
      expect(component.loading()).toBe(false);
      expect(component.results()).toHaveLength(0);
    });

    it('handles null similar array in response', async () => {
      mockApi.get.mockReturnValue(of({ similar: null, total: 0, has_more: false }));
      const component = createComponent();
      await component.ngOnInit();
      expect(component.results()).toHaveLength(0);
    });
  });

  describe('error handling', () => {
    it('clears loading state on API error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));
      const component = createComponent();
      await component.ngOnInit();
      expect(component.loading()).toBe(false);
      expect(component.loadingMore()).toBe(false);
      expect(component.results()).toHaveLength(0);
    });

    it('stops all subsequent loadMore calls after error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));
      const component = createComponent();
      await component.ngOnInit();
      await component.loadMore();
      await component.loadMore();
      expect(mockApi.get).toHaveBeenCalledTimes(1);
    });
  });

  describe('pagination', () => {
    it('appends second page results without duplicating first page', async () => {
      const page1 = Array.from({ length: 20 }, (_, i) => makePhoto(i));
      const page2 = [makePhoto(20)];
      mockApi.get
        .mockReturnValueOnce(of({ similar: page1, total: 21, has_more: true }))
        .mockReturnValueOnce(of(makeResponse(page2)));
      const component = createComponent();
      await component.ngOnInit();
      await component.loadMore();
      expect(component.results()).toHaveLength(21);
      expect(component.results()[20].path).toBe('/p20.jpg');
    });

    it('calls API with correct offset on second page', async () => {
      const page1 = Array.from({ length: 20 }, (_, i) => makePhoto(i));
      mockApi.get
        .mockReturnValueOnce(of({ similar: page1, total: 21, has_more: true }))
        .mockReturnValueOnce(of(makeResponse([])));
      const component = createComponent();
      await component.ngOnInit();
      await component.loadMore();
      expect(mockApi.get).toHaveBeenNthCalledWith(2,
        `/similar_photos/${encodeURIComponent('/photos/test.jpg')}`,
        { limit: 20, offset: 20 },
      );
    });

    it('stops loading when has_more is false', async () => {
      const photos = [makePhoto(0)];
      mockApi.get.mockReturnValue(of({ similar: photos, total: 1, has_more: false }));
      const component = createComponent();
      await component.ngOnInit();
      await component.loadMore();
      await component.loadMore();
      expect(mockApi.get).toHaveBeenCalledTimes(1);
    });

    it('stops loading when empty batch returned despite has_more=true', async () => {
      mockApi.get
        .mockReturnValueOnce(of({ similar: [makePhoto(0)], total: 1, has_more: true }))
        .mockReturnValueOnce(of({ similar: [], total: 0, has_more: true }));
      const component = createComponent();
      await component.ngOnInit();
      await component.loadMore();
      await component.loadMore();
      expect(mockApi.get).toHaveBeenCalledTimes(2);
    });

    it('does not start a second request while one is in flight', async () => {
      // has_more=true means allLoaded stays false after first page
      const page1 = Array.from({ length: 20 }, (_, i) => makePhoto(i));
      let resolveSecond!: (v: unknown) => void;
      const pending = new Promise((r) => { resolveSecond = r; });
      mockApi.get
        .mockReturnValueOnce(of({ similar: page1, total: 40, has_more: true }))
        .mockReturnValueOnce(pending as any);
      const component = createComponent();
      await component.ngOnInit();
      // Start second load but don't await — leave it in flight
      const inflight = component.loadMore();
      // Third call while second is in flight should be a no-op
      await component.loadMore();
      expect(mockApi.get).toHaveBeenCalledTimes(2);
      resolveSecond({ similar: [], total: 0, has_more: false });
      await inflight;
    });
  });

  describe('selection', () => {
    it('reflects parent selectedPaths signal state', async () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      const component = createComponent();
      await component.ngOnInit();
      expect(component.data.selectedPaths().size).toBe(0);
      selectedPaths.set(new Set(['/a.jpg']));
      expect(component.data.selectedPaths().has('/a.jpg')).toBe(true);
    });

    it('togglePath adds path when not selected', async () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      const component = createComponent();
      await component.ngOnInit();
      component.data.togglePath('/a.jpg');
      expect(selectedPaths().has('/a.jpg')).toBe(true);
    });

    it('togglePath removes path when already selected', async () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      selectedPaths.set(new Set(['/a.jpg']));
      const component = createComponent();
      await component.ngOnInit();
      component.data.togglePath('/a.jpg');
      expect(selectedPaths().has('/a.jpg')).toBe(false);
    });

    it('togglePath does not affect other selected paths', async () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      selectedPaths.set(new Set(['/a.jpg', '/b.jpg']));
      const component = createComponent();
      await component.ngOnInit();
      component.data.togglePath('/a.jpg');
      expect(selectedPaths().has('/b.jpg')).toBe(true);
    });
  });

  describe('cleanup', () => {
    it('disconnects observer on destroy when observer was created', async () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      const component = createComponent();
      await component.ngOnInit();
      // Force observer via private field (sentinel not rendered in unit test)
      (component as any).observer = { disconnect: mockDisconnect };
      component.ngOnDestroy();
      expect(mockDisconnect).toHaveBeenCalledTimes(1);
    });

    it('does not throw on destroy when no observer was created', async () => {
      mockApi.get.mockReturnValue(of(makeResponse([])));
      const component = createComponent();
      await component.ngOnInit();
      expect(() => component.ngOnDestroy()).not.toThrow();
    });
  });
});
