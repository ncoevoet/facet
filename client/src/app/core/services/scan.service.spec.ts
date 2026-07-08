import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ScanService, ScanStatus } from './scan.service';
import { AuthService } from './auth.service';

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  simulateMessage(data: ScanStatus): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  simulateError(): void {
    this.onerror?.();
  }
}

describe('ScanService', () => {
  let service: ScanService;
  let httpTesting: HttpTestingController;
  let originalEventSource: typeof EventSource;

  const mockStatus: ScanStatus = {
    running: true,
    directories: ['/photos'],
    output: ['Processing...'],
    elapsed_seconds: 5,
    exit_code: null,
  };

  const flushMint = (token = 'minted-token') => {
    const req = httpTesting.expectOne('/api/scan/stream_token');
    expect(req.request.method).toBe('GET');
    req.flush({ token });
  };

  beforeEach(() => {
    MockEventSource.instances = [];
    originalEventSource = globalThis.EventSource;
    globalThis.EventSource = MockEventSource as unknown as typeof EventSource;

    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('test-token');

    TestBed.configureTestingModule({
      providers: [
        ScanService,
        AuthService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    service = TestBed.inject(ScanService);
    httpTesting = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    service.ngOnDestroy();
    httpTesting.verify();
    globalThis.EventSource = originalEventSource;
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('should have idle status', () => {
      expect(service.status().running).toBe(false);
      expect(service.status().output).toEqual([]);
    });

    it('should not be connected', () => {
      expect(service.connected()).toBe(false);
    });
  });

  describe('connect()', () => {
    it('should mint a stream token then create an EventSource with it', async () => {
      const connectPromise = service.connect();
      flushMint('minted-token');
      await connectPromise;

      expect(MockEventSource.instances).toHaveLength(1);
      expect(MockEventSource.instances[0].url).toContain('/api/scan/stream?');
      expect(MockEventSource.instances[0].url).toContain('token=minted-token');
      expect(MockEventSource.instances[0].url).toContain('lines=50');
      expect(service.connected()).toBe(true);
    });

    it('should not connect when no local token is available', async () => {
      vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null);
      await service.connect();

      httpTesting.expectNone('/api/scan/stream_token');
      expect(MockEventSource.instances).toHaveLength(0);
      expect(service.connected()).toBe(false);
    });

    it('should fall back to polling when minting the stream token fails', async () => {
      const connectPromise = service.connect();
      httpTesting
        .expectOne('/api/scan/stream_token')
        .flush('mint failed', { status: 403, statusText: 'Forbidden' });
      await connectPromise;

      expect(MockEventSource.instances).toHaveLength(0);
      expect(service.connected()).toBe(false);

      const req = httpTesting.expectOne((r) => r.url === '/api/scan/status');
      req.flush(mockStatus);
      await Promise.resolve();

      expect(service.status()).toEqual(mockStatus);
    });

    it('should update status when receiving a message', async () => {
      const connectPromise = service.connect();
      flushMint();
      await connectPromise;

      MockEventSource.instances[0].simulateMessage(mockStatus);

      expect(service.status()).toEqual(mockStatus);
    });

    it('should disconnect when scan finishes', async () => {
      const connectPromise = service.connect();
      flushMint();
      await connectPromise;
      const source = MockEventSource.instances[0];

      source.simulateMessage({ ...mockStatus, running: false, exit_code: 0 });

      expect(source.closed).toBe(true);
      expect(service.connected()).toBe(false);
    });

    it('should close previous connection and mint a fresh token when connecting again', async () => {
      const firstConnect = service.connect();
      flushMint('token-1');
      await firstConnect;
      const first = MockEventSource.instances[0];

      const secondConnect = service.connect();
      flushMint('token-2');
      await secondConnect;

      expect(first.closed).toBe(true);
      expect(MockEventSource.instances).toHaveLength(2);
      expect(MockEventSource.instances[1].url).toContain('token=token-2');
    });
  });

  describe('connect() SSE error handling', () => {
    it('should re-mint the token and reopen the stream on the first error', async () => {
      const connectPromise = service.connect();
      flushMint('token-1');
      await connectPromise;
      const first = MockEventSource.instances[0];

      first.simulateError();

      expect(first.closed).toBe(true);
      expect(service.connected()).toBe(false);

      flushMint('token-2');

      await vi.waitFor(() => {
        expect(MockEventSource.instances).toHaveLength(2);
      });
      expect(MockEventSource.instances[1].url).toContain('token=token-2');
      expect(service.connected()).toBe(true);
    });

    it('should fall back to polling after a second consecutive error', async () => {
      const connectPromise = service.connect();
      flushMint('token-1');
      await connectPromise;
      MockEventSource.instances[0].simulateError();

      flushMint('token-2');

      await vi.waitFor(() => {
        expect(MockEventSource.instances).toHaveLength(2);
      });
      MockEventSource.instances[1].simulateError();

      const req = await vi.waitFor(() =>
        httpTesting.expectOne((r) => r.url === '/api/scan/status'),
      );
      req.flush(mockStatus);
      await Promise.resolve();

      expect(service.status()).toEqual(mockStatus);
      httpTesting.expectNone('/api/scan/stream_token');
    });

    it('should re-mint again on a later error after the reopened stream recovered', async () => {
      const connectPromise = service.connect();
      flushMint('token-1');
      await connectPromise;

      MockEventSource.instances[0].simulateError();

      flushMint('token-2');
      await vi.waitFor(() => {
        expect(MockEventSource.instances).toHaveLength(2);
      });

      MockEventSource.instances[1].simulateMessage(mockStatus);
      expect(service.status()).toEqual(mockStatus);

      MockEventSource.instances[1].simulateError();

      flushMint('token-3');
      await vi.waitFor(() => {
        expect(MockEventSource.instances).toHaveLength(3);
      });
      expect(MockEventSource.instances[2].url).toContain('token=token-3');
      expect(service.connected()).toBe(true);

      httpTesting.expectNone((r) => r.url === '/api/scan/status');
    });
  });

  describe('disconnect()', () => {
    it('should close the EventSource', async () => {
      const connectPromise = service.connect();
      flushMint();
      await connectPromise;
      const source = MockEventSource.instances[0];

      service.disconnect();

      expect(source.closed).toBe(true);
      expect(service.connected()).toBe(false);
    });
  });

  describe('startScan()', () => {
    it('should POST to /scan/start and then connect SSE', async () => {
      const promise = service.startScan(['/photos']);

      const req = httpTesting.expectOne('/api/scan/start');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ directories: ['/photos'] });
      req.flush({ success: true });

      await Promise.resolve();
      flushMint();
      await promise;

      expect(MockEventSource.instances).toHaveLength(1);
      expect(service.connected()).toBe(true);
    });
  });

  describe('loadDirectories()', () => {
    it('should fetch configured directories', async () => {
      const promise = service.loadDirectories();

      const req = httpTesting.expectOne('/api/scan/directories');
      expect(req.request.method).toBe('GET');
      req.flush({ directories: [{ path: '/photos', owner: 'shared' }] });

      const dirs = await promise;
      expect(dirs).toEqual([{ path: '/photos', owner: 'shared' }]);
    });
  });
});
