import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { GalleryStore } from '../gallery/gallery.store';
import { FoldersComponent } from './folders.component';

describe('FoldersComponent', () => {

  let component: any;
  let mockApi: { get: Mock };
  let mockRouter: { navigate: Mock };
  let mockRoute: { queryParams: Observable<Record<string, string>> };
  let mockStore: { viewFilterParams: ReturnType<typeof signal> };

  const noneHidden = {
    hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
  };

  const foldersResponse = {
    folders: [
      { name: 'Holidays', path: '/photos/Holidays/', photo_count: 50, cover_photo_path: '/photos/Holidays/best.jpg' },
      { name: 'Work', path: '/photos/Work/', photo_count: 12, cover_photo_path: null },
    ],
    has_direct_photos: false,
  };

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of(foldersResponse)) };
    mockRouter = { navigate: vi.fn() };
    mockRoute = { queryParams: of({}) };
    mockStore = { viewFilterParams: signal({ ...noneHidden }) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: Router, useValue: mockRouter },
        { provide: ActivatedRoute, useValue: mockRoute },
        { provide: GalleryStore, useValue: mockStore },
      ],
    });
    component = TestBed.runInInjectionContext(() => new FoldersComponent());
  });

  describe('breadcrumbs', () => {
    it('should return empty array when at root', () => {
      component.currentPrefix.set('');
      expect(component.breadcrumbs()).toHaveLength(0);
    });

    it('should return one crumb for a single-level prefix', () => {
      component.currentPrefix.set('Holidays/');
      const crumbs = component.breadcrumbs();
      expect(crumbs).toHaveLength(1);
      expect(crumbs[0].name).toBe('Holidays');
      expect(crumbs[0].path).toBe('Holidays/');
    });

    it('should return nested crumbs for deep prefix', () => {
      component.currentPrefix.set('2024/Summer/Beach/');
      const crumbs = component.breadcrumbs();
      expect(crumbs).toHaveLength(3);
      expect(crumbs[0]).toEqual({ name: '2024', path: '2024/' });
      expect(crumbs[1]).toEqual({ name: 'Summer', path: '2024/Summer/' });
      expect(crumbs[2]).toEqual({ name: 'Beach', path: '2024/Summer/Beach/' });
    });
  });

  describe('loadFolders', () => {
    it('should call /folders with current prefix and the view filter params', async () => {
      component.currentPrefix.set('Holidays/');
      await (component as any).loadFolders();
      expect(mockApi.get).toHaveBeenCalledWith('/folders', { prefix: 'Holidays/', ...noneHidden });
    });

    it('should populate folders signal', async () => {
      await (component as any).loadFolders();
      expect(component.folders()).toHaveLength(2);
      expect(component.folders()[0].name).toBe('Holidays');
    });

    it('should set loading false after success', async () => {
      await (component as any).loadFolders();
      expect(component.loading()).toBe(false);
    });

    it('should auto-redirect to gallery when folder is a leaf (no subfolders)', async () => {
      mockApi.get.mockReturnValue(of({ folders: [], has_direct_photos: true }));
      component.currentPrefix.set('Holidays/');
      await (component as any).loadFolders();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        queryParams: {
          path_prefix: 'Holidays/',
          sort: 'date_taken',
          sort_direction: 'DESC',
        },
        replaceUrl: true,
      });
    });

    it('should not redirect when at root with no subfolders', async () => {
      mockApi.get.mockReturnValue(of({ folders: [], has_direct_photos: false }));
      component.currentPrefix.set('');
      await (component as any).loadFolders();
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });
  });

  describe('reactive refetch on hide-toggle change', () => {
    it('re-fetches /folders when GalleryStore.viewFilterParams changes', () => {
      TestBed.flushEffects();
      expect(mockApi.get).toHaveBeenCalledWith('/folders', { prefix: '', ...noneHidden });
      mockApi.get.mockClear();

      mockStore.viewFilterParams.set({ ...noneHidden, hide_blinks: '1' });
      TestBed.flushEffects();

      expect(mockApi.get).toHaveBeenCalledWith('/folders', { prefix: '', ...noneHidden, hide_blinks: '1' });
    });

    it('re-fetches when the route prefix changes', () => {
      TestBed.flushEffects();
      mockApi.get.mockClear();

      component.currentPrefix.set('Holidays/');
      TestBed.flushEffects();

      expect(mockApi.get).toHaveBeenCalledWith('/folders', { prefix: 'Holidays/', ...noneHidden });
    });
  });

  describe('navigateTo', () => {
    it('should navigate to /folders with prefix query param', () => {
      component.navigateTo('Holidays/');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/folders'], {
        queryParams: { prefix: 'Holidays/' },
      });
    });

    it('should navigate to /folders with no query params when prefix is empty', () => {
      component.navigateTo('');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/folders'], { queryParams: {} });
    });
  });

  describe('openFolder', () => {
    it('should navigate to /folders with the folder path as prefix', () => {
      const folder = { name: 'Work', path: '/photos/Work/', photo_count: 5, cover_photo_path: null };
      component.openFolder(folder);
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/folders'], {
        queryParams: { prefix: '/photos/Work/' },
      });
    });
  });

  describe('filterInGallery', () => {
    it('should navigate to the gallery filtered on the folder, without replacing history', () => {
      const folder = { name: 'Work', path: '/photos/Work/', photo_count: 5, cover_photo_path: null };
      component.filterInGallery(folder);
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        queryParams: {
          path_prefix: '/photos/Work/',
          sort: 'date_taken',
          sort_direction: 'DESC',
        },
      });
    });
  });
});
