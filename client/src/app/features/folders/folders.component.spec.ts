import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { I18nService } from '../../core/services/i18n.service';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { GalleryStore } from '../gallery/gallery.store';
import { FoldersComponent, KEEP_CHAIN_STATE } from './folders.component';

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

    it('skips a lone folder with no photos beside it, to the first level that branches', async () => {
      mockApi.get.mockReturnValue(of({ folders: [{ name: 'Users', path: '/Users/', photo_count: 3, cover_photo_path: null }], has_direct_photos: false }));
      await (component as any).loadFolders();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/folders'], { queryParams: { prefix: '/Users/' }, replaceUrl: true });
      expect(component.folders()).toHaveLength(0);
    });

    it('clicking a chain crumb stays there instead of skipping straight back down', async () => {
      history.replaceState({ [KEEP_CHAIN_STATE]: true }, '');
      try {
        mockApi.get.mockReturnValue(of({ folders: [{ name: 'Users', path: '/Users/', photo_count: 3, cover_photo_path: null }], has_direct_photos: false }));
        await (component as any).loadFolders();
        expect(mockRouter.navigate).not.toHaveBeenCalled();
        expect(component.folders()).toHaveLength(1);
      } finally {
        history.replaceState(null, '');
      }
    });

    it('keeps a lone folder when photos also sit at this level', async () => {
      mockApi.get.mockReturnValue(of({ folders: [{ name: 'Users', path: '/Users/', photo_count: 3, cover_photo_path: null }], has_direct_photos: true }));
      await (component as any).loadFolders();
      expect(mockRouter.navigate).not.toHaveBeenCalled();
      expect(component.folders()).toHaveLength(1);
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
        state: { [KEEP_CHAIN_STATE]: true },
      });
    });

    it('should navigate to /folders with no query params when prefix is empty', () => {
      component.navigateTo('');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/folders'], { queryParams: {}, state: { [KEEP_CHAIN_STATE]: true } });
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

  describe('page shell', () => {
    async function render() {
      TestBed.resetTestingModule();
      mockApi = { get: vi.fn(() => of(foldersResponse)) };
      mockRouter = { navigate: vi.fn(() => new Promise<boolean>(() => undefined)) };
      TestBed.configureTestingModule({
        providers: [
          { provide: ApiService, useValue: mockApi },
          { provide: Router, useValue: mockRouter },
          { provide: ActivatedRoute, useValue: mockRoute },
          { provide: GalleryStore, useValue: mockStore },
          { provide: I18nService, useValue: { t: (key: string, params?: object) => key + (params ? JSON.stringify(params) : ''), translations: () => ({}) } },
        ],
      });
      const fixture = TestBed.createComponent(FoldersComponent);
      fixture.detectChanges();
      await fixture.whenStable();
      return fixture;
    }

    it('registers its toolbar template with the header slot on init and clears it on destroy', async () => {
      const fixture = await render();
      const slot = TestBed.inject(HeaderSlotService);
      expect(slot.template()).not.toBeNull();
      fixture.destroy();
      expect(slot.template()).toBeNull();
    });

    it('renders the in-page breadcrumb row at root, below lg only and sticky', async () => {
      const fixture = await render();
      const row = (fixture.nativeElement as HTMLElement).querySelector('[data-folders-toolbar]') as HTMLElement;
      expect(row).not.toBeNull();
      expect(row.className).toContain('lg:hidden');
      expect(row.className).toContain('sticky');
      expect(row.className).toContain('top-0');
      expect(row.className).toContain('z-20');
      expect(row.textContent).toContain('folders.root');
    });

    it('renders the spinner after the breadcrumb row in DOM order', async () => {
      const fixture = await render();
      const el = fixture.nativeElement as HTMLElement;
      const row = el.querySelector('[data-folders-toolbar]') as HTMLElement;
      const spinner = el.querySelector('mat-spinner') as HTMLElement;
      expect(spinner).not.toBeNull();
      expect(row.compareDocumentPosition(spinner) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('keeps loading true across a redirect branch while the navigation is pending', async () => {
      const fixture = await render();
      const cmp = fixture.componentInstance as any;
      mockApi.get.mockReturnValue(of({ folders: [], has_direct_photos: true }));
      cmp.currentPrefix.set('Holidays/');
      await cmp.loadFolders();
      expect(mockRouter.navigate).toHaveBeenCalled();
      expect(cmp.loading()).toBe(true);
    });

    it('keeps loading true while skipping a lone folder, so the spinner does not blink between hops', async () => {
      const fixture = await render();
      const cmp = fixture.componentInstance as any;
      mockApi.get.mockReturnValue(of({ folders: [{ name: 'Users', path: '/Users/', photo_count: 3, cover_photo_path: null }], has_direct_photos: false }));
      await cmp.loadFolders();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/folders'], { queryParams: { prefix: '/Users/' }, replaceUrl: true });
      expect(cmp.loading()).toBe(true);
    });

    it('clears loading when the redirect navigation resolves false or rejects', async () => {
      const fixture = await render();
      const cmp = fixture.componentInstance as any;
      mockApi.get.mockReturnValue(of({ folders: [], has_direct_photos: true }));
      cmp.currentPrefix.set('Holidays/');
      mockRouter.navigate.mockReturnValueOnce(Promise.resolve(false));
      await cmp.loadFolders();
      await Promise.resolve();
      expect(cmp.loading()).toBe(false);
      mockRouter.navigate.mockReturnValueOnce(Promise.reject(new Error('nav')));
      await cmp.loadFolders();
      await Promise.resolve();
      await Promise.resolve();
      expect(cmp.loading()).toBe(false);
    });
  });
});
