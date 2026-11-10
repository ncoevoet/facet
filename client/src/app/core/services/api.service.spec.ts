import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApiService } from './api.service';

describe('ApiService', () => {
  let service: ApiService;
  let httpTesting: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [ApiService, provideHttpClient(withXhr()), provideHttpClientTesting()],
    });
    service = TestBed.inject(ApiService);
    httpTesting = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpTesting.verify();
  });

  describe('get()', () => {
    it('preserves an explicit empty All photos type instead of selecting the server default', () => {
      service.get('/photos', { type: '', search: '' }).subscribe();
      const req = httpTesting.expectOne(r => r.url === '/api/photos');
      expect(req.request.params.has('type')).toBe(true);
      expect(req.request.params.get('type')).toBe('');
      expect(req.request.params.has('search')).toBe(false);
      req.flush({});
    });
    it('should make a GET request to /api + path', () => {
      const mockData = { items: [1, 2, 3] };

      service.get<{ items: number[] }>('/photos').subscribe((data) => {
        expect(data).toEqual(mockData);
      });

      const req = httpTesting.expectOne('/api/photos');
      expect(req.request.method).toBe('GET');
      req.flush(mockData);
    });

    it('should pass non-empty params as HttpParams', () => {
      service.get('/photos', { page: 1, sort: 'date', active: true }).subscribe();

      const req = httpTesting.expectOne((r) => r.url === '/api/photos');
      expect(req.request.params.get('page')).toBe('1');
      expect(req.request.params.get('sort')).toBe('date');
      expect(req.request.params.get('active')).toBe('true');
      req.flush({});
    });

    it('should filter out empty string, undefined, and null params', () => {
      service
        .get('/photos', {
          valid: 'keep',
          empty: '' as unknown as string,
          undef: undefined as unknown as string,
          nil: null as unknown as string,
        })
        .subscribe();

      const req = httpTesting.expectOne((r) => r.url === '/api/photos');
      expect(req.request.params.get('valid')).toBe('keep');
      expect(req.request.params.has('empty')).toBe(false);
      expect(req.request.params.has('undef')).toBe(false);
      expect(req.request.params.has('nil')).toBe(false);
      req.flush({});
    });

    it('should work without params', () => {
      service.get('/stats').subscribe();

      const req = httpTesting.expectOne('/api/stats');
      expect(req.request.params.keys().length).toBe(0);
      req.flush({});
    });
  });

  describe('post()', () => {
    it('should make a POST request with body', () => {
      const body = { name: 'test', value: 42 };
      const mockResponse = { id: 1 };

      service.post<{ id: number }>('/persons', body).subscribe((data) => {
        expect(data).toEqual(mockResponse);
      });

      const req = httpTesting.expectOne('/api/persons');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual(body);
      req.flush(mockResponse);
    });

    it('should make a POST request without body', () => {
      service.post('/action').subscribe();

      const req = httpTesting.expectOne('/api/action');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toBeNull();
      req.flush({});
    });
  });

  describe('delete()', () => {
    it('should make a DELETE request to /api + path', () => {
      service.delete('/persons/5').subscribe();

      const req = httpTesting.expectOne('/api/persons/5');
      expect(req.request.method).toBe('DELETE');
      req.flush({});
    });
  });

  describe('getRaw()', () => {
    it('should make a GET request with blob responseType', () => {
      const blob = new Blob(['binary data'], { type: 'image/jpeg' });

      service.getRaw('/thumbnail?path=test.jpg').subscribe((data) => {
        expect(data).toBeInstanceOf(Blob);
      });

      const req = httpTesting.expectOne('/thumbnail?path=test.jpg');
      expect(req.request.method).toBe('GET');
      expect(req.request.responseType).toBe('blob');
      req.flush(blob);
    });
  });

  describe('thumbnailUrl()', () => {
    it('should return URL with path param', () => {
      const url = service.thumbnailUrl('/photos/test.jpg');
      expect(url).toContain('/thumbnail?');
      expect(url).toContain('path=%2Fphotos%2Ftest.jpg');
    });

    it('should include size param when provided', () => {
      const url = service.thumbnailUrl('/photos/test.jpg', 320);
      expect(url).toContain('path=%2Fphotos%2Ftest.jpg');
      expect(url).toContain('size=320');
    });

    it('should not include size param when not provided', () => {
      const url = service.thumbnailUrl('/photos/test.jpg');
      expect(url).not.toContain('size=');
    });
  });

  describe('faceThumbnailUrl()', () => {
    it('should return the correct face thumbnail URL', () => {
      const url = new URL(service.faceThumbnailUrl(42), 'http://facet.test');
      expect(url.pathname).toBe('/face_thumbnail/42');
      expect(Object.fromEntries(url.searchParams)).toEqual({
        v: '2', 'ngsw-bypass': '1', session: expect.stringMatching(/^[a-f0-9]{32}$/),
      });
    });
  });

  describe('personThumbnailUrl()', () => {
    it('should return the correct person thumbnail URL', () => {
      const url = new URL(service.personThumbnailUrl(7), 'http://facet.test');
      expect(url.pathname).toBe('/person_thumbnail/7');
      expect(Object.fromEntries(url.searchParams)).toEqual({
        v: '2', 'ngsw-bypass': '1', session: expect.stringMatching(/^[a-f0-9]{32}$/),
      });
    });
  });

  describe('imageUrl()', () => {
    it('should return URL with encoded path', () => {
      const url = new URL(service.imageUrl('/photos/my image.jpg'), 'http://facet.test');
      expect(url.pathname).toBe('/image');
      expect(Object.fromEntries(url.searchParams)).toEqual({
        path: '/photos/my image.jpg', v: '3', 'ngsw-bypass': '1', session: expect.stringMatching(/^[a-f0-9]{32}$/),
      });
    });

    it('should encode special characters in path', () => {
      const url = new URL(service.imageUrl('/photos/file#1&2.jpg'), 'http://facet.test');
      expect(url.pathname).toBe('/image');
      expect(Object.fromEntries(url.searchParams)).toEqual({
        path: '/photos/file#1&2.jpg', v: '3', 'ngsw-bypass': '1', session: expect.stringMatching(/^[a-f0-9]{32}$/),
      });
    });
  });
});
