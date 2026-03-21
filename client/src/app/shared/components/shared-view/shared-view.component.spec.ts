import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { of, throwError } from 'rxjs';
import { signal } from '@angular/core';
import { ApiService } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { I18nService } from '../../../core/services/i18n.service';
import { SharedViewComponent } from './shared-view.component';

function buildMockRoute(
  id: string | null,
  token: string | null,
) {
  return {
    snapshot: {
      paramMap: { get: jest.fn((key: string) => key === 'albumId' ? id : null) },
      queryParamMap: { get: jest.fn((key: string) => key === 'token' ? token : null) },
    },
  };
}

describe('SharedViewComponent', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let component: any;
  let mockApi: { get: jest.Mock };
  let mockI18n: { t: jest.Mock };

  const sharedAlbumResponse = {
    album: { id: 1, name: 'Shared Album', description: 'A shared album' },
    photos: [
      { path: '/p1.jpg', filename: 'p1.jpg', aggregate: 8.5 },
      { path: '/p2.jpg', filename: 'p2.jpg', aggregate: 7.0 },
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
      get: jest.fn(() => of(sharedAlbumResponse)),
    };
    mockI18n = {
      t: jest.fn((key: string) => key),
    };
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
          photos: [{ path: '/p3.jpg', filename: 'p3.jpg', aggregate: 6.5 }],
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

});

function flushPromises(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 0));
}
