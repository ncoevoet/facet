import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { HttpErrorResponse, provideHttpClient, withXhr } from '@angular/common/http';
import { of, throwError, Subject } from 'rxjs';
import { signal } from '@angular/core';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApiService } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { I18nService } from '../../../core/services/i18n.service';
import { SharedViewComponent } from './shared-view.component';

const asset1 = '1.' + 'a'.repeat(64);
const asset2 = '2.' + 'b'.repeat(64);
const asset3 = '3.' + 'c'.repeat(64);

function observeDownloads() {
  const create = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
  const revoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:fixture') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  const save = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  return { save, restore: () => {
    save.mockRestore();
    if (create) Object.defineProperty(URL, 'createObjectURL', create);
    else Reflect.deleteProperty(URL, 'createObjectURL');
    if (revoke) Object.defineProperty(URL, 'revokeObjectURL', revoke);
    else Reflect.deleteProperty(URL, 'revokeObjectURL');
  } };
}

function buildMockRoute(
  id: string | null,
  token: string | null,
) {
  return {
    snapshot: {
      paramMap: { get: vi.fn((key: string) => key === 'albumId' ? id : null) },
      queryParamMap: { get: vi.fn((key: string) => key === 'token' ? token : null) },
    },
  };
}

describe('SharedViewComponent', () => {
   
  let component: any;
  let mockApi: { get: Mock; getRaw: Mock };
  let mockI18n: { t: Mock };

  const sharedAlbumResponse = {
    album: { id: 1, name: 'Shared Album', description: 'A shared album' },
    photos: [
      { asset_id: asset1, filename: 'p1.jpg', aggregate: 8.5 },
      { asset_id: asset2, filename: 'p2.jpg', aggregate: 7.0 },
    ],
    total: 10,
    page: 1,
    per_page: 20,
    total_pages: 1,
    has_more: false,
  };

  function createComponent(
    id: string | null = '1',
    token: string | null = 'valid_token',
  ) {
    const mockRoute = buildMockRoute(id, token);
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        SharedViewComponent,
        provideHttpClient(withXhr()),
        provideHttpClientTesting(),
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: { downloadProfiles: signal([]) } },
        { provide: I18nService, useValue: mockI18n },
        { provide: ActivatedRoute, useValue: mockRoute },
      ],
    });
    component = TestBed.inject(SharedViewComponent);
  }

  beforeEach(() => {
    mockApi = {
      get: vi.fn(() => of(sharedAlbumResponse)),
      getRaw: vi.fn(() => of(new Blob(['fixture']))),
    };
    mockI18n = {
      t: vi.fn((key: string) => key),
    };
  });

  it('rehydrates and saves proofing picks using only asset identities', async () => {
    createComponent('1', 'fixture-token'); await component.ngOnInit();
    component.proofingToken.set('fixture-session');
    const http = TestBed.inject(HttpTestingController);
    const loading = component.loadPicks();
    const read = http.expectOne('/api/shared/album/1/picks');
    expect(read.request.headers.get('Authorization')).toBe('Bearer fixture-session');
    read.flush({ picks: [{ asset_id: asset1, picked: true, comment: 'print' }] });
    await loading;
    expect(component.pickedPaths().has(asset1)).toBe(true);
    expect(component.pickComments().get(asset1)).toBe('print');
    const saving = component.togglePick(component.photos()[0], new Event('click'));
    const write = http.expectOne('/api/shared/album/1/picks');
    expect(write.request.body).toEqual({ asset_id: asset1, picked: false });
    write.flush({ ok: true, asset_id: asset1, picked: false });
    await saving;
    expect(component.pickedPaths().has(asset1)).toBe(false);
    http.verify();
  });

  it('downloads the captured selection using only the album-scoped original endpoint', async () => {
    createComponent('1', 'fixture-token'); await component.ngOnInit();
    component.selectedPaths.set(new Set([asset1, asset2]));
    const { save, restore } = observeDownloads();
    try {
      await component.downloadSelected();
      expect(mockApi.getRaw).toHaveBeenCalledTimes(2);
      for (const [url] of mockApi.getRaw.mock.calls) {
        const parsed = new URL(url, 'http://facet.test');
        expect(parsed.pathname).toBe('/api/shared/album/1/media/download');
        expect(parsed.searchParams.get('token')).toBe('fixture-token');
        expect(parsed.searchParams.has('profile')).toBe(false);
      }
      expect(save).toHaveBeenCalledTimes(2);
      await component.downloadSelected('raw');
      expect(mockApi.getRaw).toHaveBeenCalledTimes(2);
    } finally { restore(); }
  });

  it('does not save a late blob or fetch the next file after the shared link changes', async () => {
    createComponent('1', 'fixture-token'); await component.ngOnInit();
    component.selectedPaths.set(new Set([asset1, asset2]));
    const pending = new Subject<Blob>(); mockApi.getRaw.mockReturnValueOnce(pending);
    const { save, restore } = observeDownloads();
    try {
      const operation = component.downloadSelected();
      const route = TestBed.inject(ActivatedRoute);
      vi.mocked(route.snapshot.queryParamMap.get).mockReturnValue('new-token');
      pending.next(new Blob(['old'])); pending.complete(); await operation;
      expect(mockApi.getRaw).toHaveBeenCalledTimes(1);
      expect(save).not.toHaveBeenCalled();
    } finally { restore(); }
  });

  it('does not append page two over old rows while a new filter page one is pending', async () => {
    createComponent('1', 'fixture-token'); await component.ngOnInit();
    component.hasMore.set(true);
    const pending = new Subject<typeof sharedAlbumResponse>();
    mockApi.get.mockClear(); mockApi.get.mockReturnValue(pending);
    component.filters.update((filters: object) => ({ ...filters, camera: 'new-camera' }));
    const reload = component.refreshFiltered();
    component.onScrollReached();
    expect(mockApi.get).toHaveBeenCalledTimes(1);
    pending.next({ ...sharedAlbumResponse, photos: [{ asset_id: asset3, filename: 'new.jpg', aggregate: 8 }] });
    pending.complete(); await reload;
    expect(component.photos().map((photo: { path: string }) => photo.path)).toEqual([asset3]);
    expect(component.loading()).toBe(false);
  });

  describe('album mode', () => {
    describe('ngOnInit', () => {
      it('should load shared album data', async () => {
        createComponent('1', 'abc123');

        await component.ngOnInit();

        expect(mockApi.get).toHaveBeenCalledWith('/shared/album/1', expect.objectContaining({ token: 'abc123', page: 1 }));
        expect(component.entityName()).toBe('Shared Album');
        expect(component.description()).toBe('A shared album');
        expect(component.photos()).toHaveLength(2);
        expect(component.total()).toBe(10);
        expect(component.loading()).toBe(false);
      });

      it('should set error when albumId is missing', async () => {
        createComponent(null, 'abc123');

        await component.ngOnInit();

        expect(component.error()).toBe('albums.invalid_share_link');
        expect(component.loading()).toBe(false);
        expect(mockApi.get).not.toHaveBeenCalled();
      });

      it('should set error when token is missing', async () => {
        createComponent('1', null);

        await component.ngOnInit();

        expect(component.error()).toBe('albums.invalid_share_link');
        expect(component.loading()).toBe(false);
        expect(mockApi.get).not.toHaveBeenCalled();
      });

      it('should set error when albumId is 0', async () => {
        createComponent('0', 'token');

        await component.ngOnInit();

        expect(component.error()).toBe('albums.invalid_share_link');
        expect(mockApi.get).not.toHaveBeenCalled();
      });

      it('should set revoked error on 403 response', async () => {
        mockApi.get.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 403 })));
        createComponent('1', 'expired_token');

        await component.ngOnInit();

        expect(component.error()).toBe('albums.share_link_revoked');
        expect(component.loading()).toBe(false);
      });

      it('should set generic error on other HTTP errors', async () => {
        mockApi.get.mockReturnValue(throwError(() => ({ status: 500 })));
        createComponent('1', 'token');

        await component.ngOnInit();

        expect(component.error()).toBe('albums.load_error');
        expect(component.loading()).toBe(false);
      });
    });

    describe('onScrollReached (load more)', () => {
      beforeEach(async () => {
        // Initial load must set hasMore=true so onScrollReached triggers
        mockApi.get.mockReturnValue(of({ ...sharedAlbumResponse, has_more: true }));
        createComponent('1', 'token');
        await component.ngOnInit();
        mockApi.get.mockClear();
      });

      it('should load next page and append photos', async () => {
        mockApi.get.mockReturnValue(of({
          album: { id: 1, name: 'Shared Album', description: 'A shared album' },
          photos: [{ asset_id: asset3, filename: 'p3.jpg', aggregate: 6.5 }],
          total: 10,
          page: 2,
          per_page: 20,
          total_pages: 2,
          has_more: false,
        }));

        component.onScrollReached();
        await flushPromises();

        expect(mockApi.get).toHaveBeenCalledWith('/shared/album/1', expect.objectContaining({ token: 'token', page: 2 }));
        expect(component.photos()).toHaveLength(3);
      });

      it('should set loadingMore true then false', async () => {
        mockApi.get.mockReturnValue(of({
          ...sharedAlbumResponse,
          page: 2,
          has_more: false,
        }));

        component.onScrollReached();
        expect(component.loadingMore()).toBe(true);

        await flushPromises();
        expect(component.loadingMore()).toBe(false);
      });
    });
  });

  describe('hide-toggle defaults (issue #112)', () => {
    function mockApiForConfig(defaults: { hide_blinks?: boolean; hide_bursts?: boolean; hide_duplicates?: boolean }) {
      mockApi.get.mockImplementation((path: string) => {
        if (path === '/config') return of({ defaults });
        return of(sharedAlbumResponse);
      });
    }

    it('initialises the hide toggles from config().defaults, not hardcoded false', async () => {
      mockApiForConfig({ hide_blinks: false, hide_bursts: true, hide_duplicates: true });
      createComponent('1', 'token');

      await component.ngOnInit();

      expect(component.filters().hide_blinks).toBe(false);
      expect(component.filters().hide_bursts).toBe(true);
      expect(component.filters().hide_duplicates).toBe(true);
    });

    it('keeps the hide toggles false when /config fails (non-critical failure)', async () => {
      mockApi.get.mockImplementation((path: string) => {
        if (path === '/config') return throwError(() => new Error('boom'));
        return of(sharedAlbumResponse);
      });
      createComponent('1', 'token');

      await component.ngOnInit();

      expect(component.filters().hide_blinks).toBe(false);
      expect(component.filters().hide_bursts).toBe(false);
      expect(component.filters().hide_duplicates).toBe(false);
    });

    it('resetFilters() resets to the config defaults, not hardcoded false', async () => {
      mockApiForConfig({ hide_blinks: false, hide_bursts: true, hide_duplicates: true });
      createComponent('1', 'token');
      await component.ngOnInit();

      component.updateFilter('hide_bursts', false);
      component.resetFilters();

      expect(component.filters().hide_bursts).toBe(true);
    });

    it('activeFilterCount only counts a toggle once it differs from its default', async () => {
      mockApiForConfig({ hide_blinks: false, hide_bursts: true, hide_duplicates: true });
      createComponent('1', 'token');
      await component.ngOnInit();

      expect(component.activeFilterCount()).toBe(0);

      component.updateFilter('hide_bursts', false);
      expect(component.activeFilterCount()).toBe(1);
    });

    it('displayFilterCount only counts a toggle once it differs from its default', async () => {
      mockApiForConfig({ hide_blinks: false, hide_bursts: true, hide_duplicates: true });
      createComponent('1', 'token');
      await component.ngOnInit();

      expect(component.displayFilterCount()).toBe(0);

      component.updateFilter('hide_blinks', true);
      expect(component.displayFilterCount()).toBe(1);
    });

    it('unchecking a toggle away from a true default sends an explicit "0", never omits it', async () => {
      mockApiForConfig({ hide_blinks: false, hide_bursts: true, hide_duplicates: true });
      createComponent('1', 'token');
      await component.ngOnInit();
      mockApi.get.mockClear();

      component.updateFilter('hide_bursts', false);
      await flushPromises();

      expect(mockApi.get).toHaveBeenCalledWith('/shared/album/1', expect.objectContaining({ hide_bursts: '0' }));
    });
  });

});

function flushPromises(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 0));
}
