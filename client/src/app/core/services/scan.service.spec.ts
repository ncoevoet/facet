import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ScanService, ScanStatus } from './scan.service';
import { AuthService, AuthStatus } from './auth.service';
import { MatDialog } from '@angular/material/dialog';
import { of } from 'rxjs';
import { makeJwt } from '../../../testing/jwt';

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

function authorizedStatus(): AuthStatus {
  return { authenticated: true, multi_user: false, edition_enabled: true, edition_authenticated: true,
    edition_password_required: false, login_password_required: false, user_id: 'alice', user_role: 'admin',
    display_name: 'Alice', features: { show_scan_button: true }, download_profiles: [] };
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

    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(makeJwt(3600));

    TestBed.configureTestingModule({
      providers: [
        ScanService,
        AuthService,
        provideHttpClient(withXhr()),
        provideHttpClientTesting(),
      ],
    });
    TestBed.inject(AuthService).status.set(authorizedStatus());
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

  describe('owned scan stopping', () => {
    const job = '1'.repeat(32);
    async function observe() {
      const connected = service.connect(); flushMint(); await connected;
      MockEventSource.instances.at(-1)!.simulateMessage({ ...mockStatus, job_id: job, kind: 'scan', cancel_requested: false });
      expect(service.canCancel()).toBe(true);
    }

    it('acknowledges only a stop request and keeps running until an observed exit', async () => {
      await observe();
      const stop = service.cancelScan(job);
      const request = httpTesting.expectOne('/api/scan/cancel');
      expect(request.request.method).toBe('POST');
      expect(request.request.body).toEqual({ job_id: job, confirm: true });
      request.flush({ job_id: job, stop_requested: true }); await stop;
      expect(service.status().running).toBe(true);
      expect(service.status().cancel_requested).toBe(true);
      expect(service.canCancel()).toBe(false);
    });

    it('does not apply a late receipt to a newer job or submit old observation under a new account', async () => {
      await observe();
      const stop = service.cancelScan(job);
      const request = httpTesting.expectOne('/api/scan/cancel');
      const newer = '2'.repeat(32);
      MockEventSource.instances.at(-1)!.simulateMessage({ ...mockStatus, job_id: newer, kind: 'scan', cancel_requested: false });
      request.flush({ job_id: job, stop_requested: true }); await stop;
      expect(service.status().job_id).toBe(newer);
      expect(service.status().cancel_requested).toBe(false);
      TestBed.inject(AuthService).status.set({ ...authorizedStatus(), user_id: 'other' });
      // Before Angular has run the auth cleanup effect, the old observation is already invalid.
      await expect(service.cancelScan(newer)).rejects.toThrow('context changed');
      httpTesting.expectNone('/api/scan/cancel');
    });

    it('refuses malformed job metadata rather than exposing a stop command', async () => {
      await observe();
      MockEventSource.instances.at(-1)!.simulateMessage({ ...mockStatus, job_id: 'not-a-job', kind: 'scan' });
      expect(service.observationError()).toBe(true);
      expect(service.canCancel()).toBe(false);
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

    it('should not connect without an authorized scan session', async () => {
      vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null);
      TestBed.inject(AuthService).status.set(null);
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

  it('does not reopen a stream after disconnect while mint is pending', async () => {
    const connect = service.connect();
    service.disconnect();
    flushMint(); await connect;
    expect(MockEventSource.instances).toHaveLength(0);
  });

  it('ignores an old closed stream callback after a new connection is live', async () => {
    const first = service.connect(); flushMint(); await first;
    const old = MockEventSource.instances[0];
    const second = service.connect(); flushMint(); await second;
    old.simulateMessage({ ...mockStatus, output: ['stale'] });
    old.simulateError();
    expect(MockEventSource.instances[1].closed).toBe(false);
    expect(service.status().output).not.toEqual(['stale']);
    httpTesting.expectNone('/api/scan/stream_token');
  });

  it('discards a pending mint and visible private output when the account changes', async () => {
    const first = service.connect(); flushMint(); await first;
    MockEventSource.instances[0].simulateMessage(mockStatus);
    const reconnect = service.connect();
    TestBed.inject(AuthService).status.set({ ...authorizedStatus(), user_id: 'bob' });
    flushMint(); await reconnect;
    expect(MockEventSource.instances).toHaveLength(1);
    expect(service.status().output).toEqual([]);
    expect(service.status().directories).toEqual([]);
    expect(service.statusKnown()).toBe(false);
  });

  it('rejects stale directory results and does not attach an accepted start to another account', async () => {
    const dirs = service.loadDirectories();
    const pendingDirs = httpTesting.expectOne('/api/scan/directories');
    TestBed.inject(AuthService).status.set({ ...authorizedStatus(), user_id: 'bob' });
    pendingDirs.flush({ directories: [{ path: '/alice/private', owner: 'alice' }] });
    await expect(dirs).rejects.toThrow('Scan session changed');
    const paths = ['/bob'];
    const start = service.startScan(paths);
    const post = httpTesting.expectOne('/api/scan/start');
    paths.push('/later');
    expect(post.request.body).toEqual({ directories: ['/bob'] });
    TestBed.inject(AuthService).status.set(authorizedStatus());
    post.flush({ success: true }); await start;
    httpTesting.expectNone('/api/scan/stream_token');
  });

  it('discards late polling after token rotation and blocks commands after rights loss', async () => {
    const connect = service.connect();
    httpTesting.expectOne('/api/scan/stream_token').flush('', { status: 503, statusText: 'Unavailable' });
    await connect;
    const poll = httpTesting.expectOne(r => r.url === '/api/scan/status');
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(makeJwt(7200));
    poll.flush(mockStatus); await Promise.resolve();
    expect(service.status().output).toEqual([]);
    expect(service.statusKnown()).toBe(false);
    TestBed.inject(AuthService).status.set({ ...authorizedStatus(), edition_authenticated: false });
    await expect(service.startScan(['/photos'])).rejects.toThrow('Scan session changed');
    httpTesting.expectNone('/api/scan/start');
  });

  it('keeps pending directory reads valid across same-session observation recovery', async () => {
    const dirs = service.loadDirectories();
    const pending = httpTesting.expectOne('/api/scan/directories');
    const connect = service.connect(); flushMint(); await connect;
    pending.flush({ directories: [{ path: '/photos', owner: 'alice' }] });
    await expect(dirs).resolves.toEqual([{ path: '/photos', owner: 'alice' }]);
  });

  it('retains last known same-session output while a recovered connection is still unknown', async () => {
    const first = service.connect(); flushMint(); await first;
    MockEventSource.instances[0].simulateMessage(mockStatus);
    const retry = service.connect();
    expect(service.statusKnown()).toBe(false);
    expect(service.status().output).toEqual(mockStatus.output);
    flushMint(); await retry;
  });

  it('recovers a failed status read using only observation requests', async () => {
    const connect = service.connect();
    httpTesting.expectOne('/api/scan/stream_token').flush('', { status: 503, statusText: 'Unavailable' });
    await connect;
    httpTesting.expectOne(r => r.url === '/api/scan/status').flush('', { status: 503, statusText: 'Unavailable' });
    await Promise.resolve();
    expect(service.observationError()).toBe(true);
    expect(service.statusKnown()).toBe(false);
    const retry = service.connect(); flushMint(); await retry;
    MockEventSource.instances[0].simulateMessage(mockStatus);
    expect(service.observationError()).toBe(false);
    expect(service.statusKnown()).toBe(true);
    expect(service.status()).toEqual(mockStatus);
    httpTesting.expectNone('/api/scan/start');
  });

  it('treats malformed SSE data as a recoverable read error', async () => {
    const connect = service.connect(); flushMint(); await connect;
    MockEventSource.instances[0].onmessage?.({ data: 'null' } as MessageEvent);
    expect(service.observationError()).toBe(true);
    expect(service.statusKnown()).toBe(false);
    expect(MockEventSource.instances[0].closed).toBe(true);
    httpTesting.expectNone('/api/scan/start');
  });

  it('falls back to a status read if EventSource construction is unavailable', async () => {
    globalThis.EventSource = class { constructor() { throw new Error('blocked transport'); } } as unknown as typeof EventSource;
    const connect = service.connect(); flushMint(); await connect;
    httpTesting.expectOne(r => r.url === '/api/scan/status').flush(mockStatus);
    await Promise.resolve();
    expect(service.status()).toEqual(mockStatus);
    expect(service.statusKnown()).toBe(true);
    httpTesting.expectNone('/api/scan/start');
  });

  it('does not report malformed polling data as a finished scan', async () => {
    const connect = service.connect();
    httpTesting.expectOne('/api/scan/stream_token').flush('', { status: 503, statusText: 'Unavailable' });
    await connect;
    httpTesting.expectOne(r => r.url === '/api/scan/status').flush({ running: false, output: null });
    await Promise.resolve();
    expect(service.observationError()).toBe(true);
    expect(service.statusKnown()).toBe(false);
    expect(service.status().exit_code).toBeNull();
  });

  it('keeps at most one polling request in flight', async () => {
    vi.useFakeTimers();
    try {
      const connect = service.connect();
      httpTesting.expectOne('/api/scan/stream_token').flush('', { status: 503, statusText: 'Unavailable' });
      await connect;
      const first = httpTesting.expectOne(r => r.url === '/api/scan/status');
      vi.advanceTimersByTime(6000);
      httpTesting.expectNone(r => r.url === '/api/scan/status');
      first.flush(mockStatus); await Promise.resolve();
      vi.advanceTimersByTime(2000);
      httpTesting.expectOne(r => r.url === '/api/scan/status').flush({ ...mockStatus, running: false, exit_code: 0 });
      await Promise.resolve();
      expect(service.status().exit_code).toBe(0);
    } finally { vi.useRealTimers(); }
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

  it('reads bounded history and refuses a late result from another session', async () => {
    const history = service.loadHistory(42);
    const request = httpTesting.expectOne(r => r.url === '/api/scan/runs');
    expect(request.request.method).toBe('GET');
    expect(request.request.params.get('limit')).toBe('20');
    expect(request.request.params.get('before')).toBe('42');
    TestBed.inject(AuthService).status.set({ ...authorizedStatus(), user_id: 'other' });
    request.flush({ runs: [], next_before: null });
    await expect(history).rejects.toThrow('Scan session changed');
    httpTesting.expectNone('/api/scan/start');
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

  describe('canLaunch', () => {
    function setAuth(overrides: {
      isMultiUser?: boolean;
      isSuperadmin?: boolean;
      editionPasswordRequired?: boolean;
      isEdition?: boolean;
      loginPasswordRequired?: boolean;
      hasFeature?: boolean;
    }): boolean {
      TestBed.resetTestingModule();
      const auth = {
        identity: () => 'test', status: () => null, token: null,
        loginPasswordRequired: () => overrides.loginPasswordRequired ?? false,
        isMultiUser: () => overrides.isMultiUser ?? false,
        isSuperadmin: () => overrides.isSuperadmin ?? false,
        editionPasswordRequired: () => overrides.editionPasswordRequired ?? false,
        isEdition: () => overrides.isEdition ?? false,
        hasFeature: () => overrides.hasFeature ?? true,
      };
      TestBed.configureTestingModule({
        providers: [
          ScanService,
          { provide: AuthService, useValue: auth },
          provideHttpClient(withXhr()),
          provideHttpClientTesting(),
        ],
      });
      return TestBed.inject(ScanService).canLaunch();
    }

    it('is true for a multi-user superadmin with the flag on', () => {
      expect(setAuth({ isMultiUser: true, isSuperadmin: true, hasFeature: true })).toBe(true);
    });

    it('is false for a multi-user admin who is not superadmin', () => {
      expect(setAuth({ isMultiUser: true, isSuperadmin: false, hasFeature: true })).toBe(false);
    });

    it('is true for a single-user locked install with an edition session', () => {
      expect(setAuth({ isMultiUser: false, editionPasswordRequired: true, isEdition: true, hasFeature: true })).toBe(true);
    });

    // On an open install the server reports edition only for a trusted-local session
    // (viewer.trusted_local_editing), so that session may scan without the flag.
    it('is true for an open-install edition session without the flag', () => {
      expect(setAuth({ isMultiUser: false, editionPasswordRequired: false, isEdition: true, hasFeature: false })).toBe(true);
    });

    it('is false for an open-install non-edition session without the flag', () => {
      expect(setAuth({ isMultiUser: false, editionPasswordRequired: false, isEdition: false, hasFeature: false })).toBe(false);
    });

    it('is false for an edition session behind a login password without the flag', () => {
      expect(setAuth({ isMultiUser: false, editionPasswordRequired: false, loginPasswordRequired: true, isEdition: true, hasFeature: false })).toBe(false);
    });

    it('is false regardless of role when the feature flag is off', () => {
      expect(setAuth({ isMultiUser: true, isSuperadmin: true, hasFeature: false })).toBe(false);
    });

    it('is false for a locked single-user install without an edition session, even with the flag on', () => {
      expect(setAuth({ isMultiUser: false, editionPasswordRequired: true, isEdition: false, hasFeature: true })).toBe(false);
    });

    it('is false for an edition session behind a login password with no edition password, even with the flag on', () => {
      expect(setAuth({ isMultiUser: false, editionPasswordRequired: false, loginPasswordRequired: true, isEdition: true, hasFeature: true })).toBe(false);
    });
  });

  describe('openLauncher()', () => {
    function withDialog(result: unknown): { open: ReturnType<typeof vi.fn> } {
      TestBed.resetTestingModule();
      const dialog = { open: vi.fn(() => ({ afterClosed: () => of(result) })) };
      TestBed.configureTestingModule({
        providers: [
          ScanService,
          AuthService,
          { provide: MatDialog, useValue: dialog },
          provideHttpClient(withXhr()),
          provideHttpClientTesting(),
        ],
      });
      TestBed.inject(AuthService).status.set(authorizedStatus());
      return dialog;
    }

    it('returns true when the launcher closes with a truthy result', async () => {
      const dialog = withDialog(true);
      expect(await TestBed.inject(ScanService).openLauncher()).toBe(true);
      expect(dialog.open).toHaveBeenCalledWith(expect.anything(), { width: '36rem' });
    });

    it('returns false when the launcher is dismissed', async () => {
      withDialog(undefined);
      expect(await TestBed.inject(ScanService).openLauncher()).toBe(false);
    });
  });
});
