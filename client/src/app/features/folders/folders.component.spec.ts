import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { FoldersComponent } from './folders.component';

describe('FoldersComponent', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let component: any;
  let mockApi: { get: jest.Mock };
  let mockRouter: { navigate: jest.Mock };
  let mockRoute: { queryParams: Observable<Record<string, string>> };

  const foldersResponse = {
    folders: [
      { name: 'Holidays', path: '/photos/Holidays/', photo_count: 50, cover_photo_path: '/photos/Holidays/best.jpg' },
      { name: 'Work', path: '/photos/Work/', photo_count: 12, cover_photo_path: null },
    ],
    has_direct_photos: false,
  };

  beforeEach(() => {
    mockApi = { get: jest.fn(() => of(foldersResponse)) };
    mockRouter = { navigate: jest.fn() };
    mockRoute = { queryParams: of({}) };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: Router, useValue: mockRouter },
        { provide: ActivatedRoute, useValue: mockRoute },
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
    it('should call /folders with current prefix', async () => {
      component.currentPrefix.set('Holidays/');
      await (component as any).loadFolders();
      expect(mockApi.get).toHaveBeenCalledWith('/folders', { prefix: 'Holidays/' });
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
});
