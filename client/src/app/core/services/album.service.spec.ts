import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { AlbumService, Album, AlbumPhotosResponse } from './album.service';

const MOCK_ALBUM: Album = {
  id: 1,
  name: 'Vacation',
  description: 'Summer 2025',
  cover_photo_path: '/photos/cover.jpg',
  first_photo_path: '/photos/first.jpg',
  is_smart: false,
  is_shared: false,
  smart_filter_json: null,
  photo_count: 42,
  created_at: '2025-06-01T00:00:00Z',
  updated_at: '2025-06-15T00:00:00Z',
};

describe('AlbumService', () => {
  let service: AlbumService;
  let httpTesting: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [AlbumService, provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AlbumService);
    httpTesting = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpTesting.verify();
  });

  describe('list()', () => {
    it('should GET /api/albums', () => {
      const mockResponse = { albums: [MOCK_ALBUM], total: 1, has_more: false };

      service.list().subscribe((data) => {
        expect(data).toEqual(mockResponse);
      });

      const req = httpTesting.expectOne('/api/albums');
      expect(req.request.method).toBe('GET');
      req.flush(mockResponse);
    });

    it('should pass query params', () => {
      service.list({ page: 1, per_page: 20 }).subscribe();

      const req = httpTesting.expectOne((r) => r.url === '/api/albums');
      expect(req.request.params.get('page')).toBe('1');
      expect(req.request.params.get('per_page')).toBe('20');
      req.flush({ albums: [], total: 0, has_more: false });
    });
  });

  describe('create()', () => {
    it('should POST /api/albums with name and defaults', () => {
      service.create('My Album').subscribe((data) => {
        expect(data).toEqual(MOCK_ALBUM);
      });

      const req = httpTesting.expectOne('/api/albums');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({
        name: 'My Album',
        description: '',
        is_smart: false,
        smart_filter_json: null,
      });
      req.flush(MOCK_ALBUM);
    });

    it('should POST with description and smart filter', () => {
      const filter = '{"tag":"landscape"}';
      service.create('Smart', 'A smart album', true, filter).subscribe();

      const req = httpTesting.expectOne('/api/albums');
      expect(req.request.body).toEqual({
        name: 'Smart',
        description: 'A smart album',
        is_smart: true,
        smart_filter_json: filter,
      });
      req.flush(MOCK_ALBUM);
    });
  });

  describe('get()', () => {
    it('should GET /api/albums/:id', () => {
      service.get(1).subscribe((data) => {
        expect(data).toEqual(MOCK_ALBUM);
      });

      const req = httpTesting.expectOne('/api/albums/1');
      expect(req.request.method).toBe('GET');
      req.flush(MOCK_ALBUM);
    });
  });

  describe('update()', () => {
    it('should PUT /api/albums/:id with updates', () => {
      const updates = { name: 'Renamed', description: 'Updated' };

      service.update(1, updates).subscribe((data) => {
        expect(data).toEqual(MOCK_ALBUM);
      });

      const req = httpTesting.expectOne('/api/albums/1');
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual(updates);
      req.flush(MOCK_ALBUM);
    });
  });

  describe('delete()', () => {
    it('should DELETE /api/albums/:id', () => {
      service.delete(1).subscribe((data) => {
        expect(data).toEqual({ ok: true });
      });

      const req = httpTesting.expectOne('/api/albums/1');
      expect(req.request.method).toBe('DELETE');
      req.flush({ ok: true });
    });
  });

  describe('addPhotos()', () => {
    it('should POST photo paths to /api/albums/:id/photos', () => {
      const paths = ['/photos/a.jpg', '/photos/b.jpg'];

      service.addPhotos(1, paths).subscribe((data) => {
        expect(data).toEqual({ ok: true, photo_count: 44 });
      });

      const req = httpTesting.expectOne('/api/albums/1/photos');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ photo_paths: paths });
      req.flush({ ok: true, photo_count: 44 });
    });
  });

  describe('removePhotos()', () => {
    it('should DELETE with body to /api/albums/:id/photos', () => {
      const paths = ['/photos/a.jpg'];

      service.removePhotos(1, paths).subscribe((data) => {
        expect(data).toEqual({ ok: true, photo_count: 41 });
      });

      const req = httpTesting.expectOne('/api/albums/1/photos');
      expect(req.request.method).toBe('DELETE');
      expect(req.request.body).toEqual({ photo_paths: paths });
      req.flush({ ok: true, photo_count: 41 });
    });
  });

  describe('getPhotos()', () => {
    it('should GET /api/albums/:id/photos', () => {
      const mockResponse: AlbumPhotosResponse = {
        photos: [],
        total: 0,
        page: 1,
        per_page: 64,
        has_more: false,
      };

      service.getPhotos(1).subscribe((data) => {
        expect(data).toEqual(mockResponse);
      });

      const req = httpTesting.expectOne('/api/albums/1/photos');
      expect(req.request.method).toBe('GET');
      req.flush(mockResponse);
    });

    it('should pass query params for pagination and sorting', () => {
      service.getPhotos(1, { page: 2, per_page: 32, sort: 'date' }).subscribe();

      const req = httpTesting.expectOne((r) => r.url === '/api/albums/1/photos');
      expect(req.request.params.get('page')).toBe('2');
      expect(req.request.params.get('per_page')).toBe('32');
      expect(req.request.params.get('sort')).toBe('date');
      req.flush({ photos: [], total: 0, page: 2, per_page: 32, has_more: false });
    });
  });

  describe('share()', () => {
    it('should POST to /api/albums/:id/share', () => {
      const mockResponse = { share_url: 'http://example.com/shared/1?token=abc', share_token: 'abc' };

      service.share(1).subscribe((data) => {
        expect(data).toEqual(mockResponse);
      });

      const req = httpTesting.expectOne('/api/albums/1/share');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({});
      req.flush(mockResponse);
    });
  });

  describe('revokeShare()', () => {
    it('should DELETE /api/albums/:id/share', () => {
      service.revokeShare(1).subscribe((data) => {
        expect(data).toEqual({ ok: true });
      });

      const req = httpTesting.expectOne('/api/albums/1/share');
      expect(req.request.method).toBe('DELETE');
      req.flush({ ok: true });
    });
  });

  describe('getShared()', () => {
    it('should GET /api/shared/album/:id with token param', () => {
      const mockResponse = { album: MOCK_ALBUM, photos: [], total: 0 };

      service.getShared(1, 'my-token').subscribe((data) => {
        expect(data).toEqual(mockResponse);
      });

      const req = httpTesting.expectOne((r) => r.url === '/api/shared/album/1');
      expect(req.request.method).toBe('GET');
      expect(req.request.params.get('token')).toBe('my-token');
      req.flush(mockResponse);
    });
  });
});
