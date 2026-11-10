import type { MockInstance } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { PersonAssignmentHistoryService } from './person-assignment-history.service';
import { AuthService, AuthStatus } from './auth.service';
import { makeJwt } from '../../../testing/jwt';
import { authInterceptor } from '../interceptors/auth.interceptor';
import { PRIVATE_IMAGE_SESSION_STORAGE_KEY, privateImageCacheKey, privateImageSessionKey } from '../../shared/utils/private-image-session';

describe('AuthService', () => {
  let service: AuthService;
  let httpTesting: HttpTestingController;
  const mockRouter = { navigate: vi.fn() };

  const mockStatus: AuthStatus = {
    authenticated: true,
    multi_user: true,
    edition_enabled: true,
    edition_authenticated: false,
    edition_password_required: false,
    login_password_required: false,
    user_id: 'testuser',
    user_role: 'admin',
    display_name: 'Test User',
    features: { face_recognition: true, edition: false },
    download_profiles: [],
  };

  let getItemSpy: MockInstance;
  let setItemSpy: MockInstance;
  let removeItemSpy: MockInstance;

  // Let promise continuations settle while intentionally held HTTP requests stay pending.
  const nextTurn = () => new Promise<void>(resolve => setTimeout(resolve, 0));

  /** Model the shared token value as well as spying on writes. */
  function trackTokenStorage(initial: string | null) {
    const stored = new Map<string, string>();
    if (initial) stored.set('facet_token', initial);
    getItemSpy.mockImplementation((key: string) => stored.get(key) ?? null);
    setItemSpy.mockImplementation((key: string, value: string) => {
      stored.set(key, value);
    });
    removeItemSpy.mockImplementation((key: string) => {
      stored.delete(key);
    });
  }

  beforeEach(() => {
    getItemSpy = vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null);
    setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
    removeItemSpy = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {});

    TestBed.configureTestingModule({
      providers: [
        AuthService,
        provideHttpClient(withInterceptors([authInterceptor]), withXhr()),
        provideHttpClientTesting(),
        { provide: Router, useValue: mockRouter },
      ],
    });
    service = TestBed.inject(AuthService);
    httpTesting = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpTesting.verify();
    vi.restoreAllMocks();
    mockRouter.navigate.mockClear();
  });

  describe('initial state', () => {
    it('should have null status initially', () => {
      expect(service.status()).toBeNull();
    });

    it('should have isAuthenticated as false initially', () => {
      expect(service.isAuthenticated()).toBe(false);
    });

    it('should have isEdition as false initially', () => {
      expect(service.isEdition()).toBe(false);
    });

    it('should have isSuperadmin as false initially', () => {
      expect(service.isSuperadmin()).toBe(false);
    });

    it('should have isMultiUser as false initially', () => {
      expect(service.isMultiUser()).toBe(false);
    });

    it('should have empty features initially', () => {
      expect(service.features()).toEqual({});
    });
  });

  describe('computed signals', () => {
    it('should derive isAuthenticated from status', () => {
      service.status.set(mockStatus);
      expect(service.isAuthenticated()).toBe(true);
    });

    it('should derive isEdition from status', () => {
      service.status.set({ ...mockStatus, edition_authenticated: true });
      expect(service.isEdition()).toBe(true);
    });

    it('should derive isSuperadmin when user_role is superadmin', () => {
      service.status.set({ ...mockStatus, user_role: 'superadmin' });
      expect(service.isSuperadmin()).toBe(true);
    });

    it('should derive isSuperadmin as false for non-superadmin roles', () => {
      service.status.set({ ...mockStatus, user_role: 'admin' });
      expect(service.isSuperadmin()).toBe(false);
    });

    it('should derive isMultiUser from status', () => {
      service.status.set(mockStatus);
      expect(service.isMultiUser()).toBe(true);
    });

    describe('isReadOnlyInstall (drives the read-only hint)', () => {
      const single = { ...mockStatus, multi_user: false, edition_authenticated: false, edition_password_required: false };

      it('is false before the status is known', () => {
        expect(service.isReadOnlyInstall()).toBe(false);
      });

      it('is true on an open single-user install', () => {
        service.status.set(single);
        expect(service.isReadOnlyInstall()).toBe(true);
      });

      it('is false on a locked install that has not been unlocked yet (the unlock entry covers it)', () => {
        service.status.set({ ...single, edition_password_required: true });
        expect(service.isReadOnlyInstall()).toBe(false);
      });

      it('is false on a locked install once unlocked', () => {
        service.status.set({ ...single, edition_password_required: true, edition_authenticated: true });
        expect(service.isReadOnlyInstall()).toBe(false);
      });

      it('is false for a multi-user regular user', () => {
        service.status.set({ ...single, multi_user: true, user_role: 'user' });
        expect(service.isReadOnlyInstall()).toBe(false);
      });
    });

    it('should derive features from status', () => {
      service.status.set(mockStatus);
      expect(service.features()).toEqual({ face_recognition: true, edition: false });
    });
  });

  describe('token', () => {
    it('should read token from localStorage', () => {
      const live = makeJwt(3600);
      getItemSpy.mockReturnValue(live);
      expect(service.token).toBe(live);
      expect(localStorage.getItem).toHaveBeenCalledWith('facet_token');
    });

    it('should return null when no token stored', () => {
      getItemSpy.mockReturnValue(null);
      expect(service.token).toBeNull();
    });

    it('should return null for a token whose exp has passed beyond the clock-skew grace', () => {
      getItemSpy.mockReturnValue(makeJwt(-3600));
      expect(service.token).toBeNull();
    });

    // A browser clock a few minutes fast used to make the client withhold a token the
    // server still accepts: the request then 401s, the error interceptor logs out, and
    // the freshly issued login token is judged dead by the same clock — a lockout with
    // no server verdict anywhere in it.
    it('should still present a token that only looks expired because the local clock runs fast', () => {
      const skewed = makeJwt(-60);
      getItemSpy.mockReturnValue(skewed);
      expect(service.token).toBe(skewed);
    });

    it('should return null for a token with no exp claim', () => {
      getItemSpy.mockReturnValue(`header.${btoa(JSON.stringify({ sub: '_legacy' }))}.sig`);
      expect(service.token).toBeNull();
    });

    it('should return null for an unreadable token', () => {
      getItemSpy.mockReturnValue('not-a-jwt');
      expect(service.token).toBeNull();
    });
  });

  describe('revalidate()', () => {
    it('should coalesce concurrent callers into a single request', async () => {
      const both = Promise.all([service.revalidate(), service.revalidate()]);

      httpTesting.expectOne('/api/auth/status').flush(mockStatus);

      expect(await both).toEqual([mockStatus, mockStatus]);
      expect(service.status()).toEqual(mockStatus);
    });

    it('should issue a fresh request once the previous one settled', async () => {
      const first = service.revalidate();
      httpTesting.expectOne('/api/auth/status').flush(mockStatus);
      await first;

      const second = service.revalidate();
      httpTesting.expectOne('/api/auth/status').flush(mockStatus);
      await second;
    });

    it('should resolve null instead of rejecting when the request fails', async () => {
      const promise = service.revalidate();

      httpTesting.expectOne('/api/auth/status').flush('boom', { status: 500, statusText: 'Server Error' });

      await expect(promise).resolves.toBeNull();
    });
  });

  describe('cross-tab token rotation', () => {
    it('discards an old account response and clears its identity while the new account loads', async () => {
      const aliceToken = makeJwt(3600, { sub: 'alice' });
      trackTokenStorage(aliceToken);
      const alice = { ...mockStatus, user_id: 'alice', edition_authenticated: true };
      const bob = { ...mockStatus, user_id: 'bob' };
      service.status.set(alice);
      const history = TestBed.inject(PersonAssignmentHistoryService);
      history.record(11, '1|alice');
      expect(history.recentIds()).toEqual([11]);
      const stale = service.revalidate();
      const aliceRequest = httpTesting.expectOne('/api/auth/status');
      expect(aliceRequest.request.headers.get('Authorization')).toBe(`Bearer ${aliceToken}`);

      const bobToken = makeJwt(3600, { sub: 'bob' });
      localStorage.setItem('facet_token', bobToken);
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token', newValue: bobToken }));
      expect(service.status()).toBeNull();
      expect(history.recentIds()).toEqual([]);
      const bobRequest = httpTesting.expectOne('/api/auth/status');
      expect(bobRequest.request.headers.get('Authorization')).toBe(`Bearer ${bobToken}`);
      bobRequest.flush(bob);
      await nextTurn();
      aliceRequest.flush(alice);
      await stale;
      expect(service.status()).toEqual(bob);
      expect(service.token).toBe(bobToken);
      expect(history.recentIds()).toEqual([]);
    });

    it('does not let an old reconciliation release the newer generation pending request', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      const stale = service.revalidate();
      const aliceRequest = httpTesting.expectOne('/api/auth/status');
      const bobToken = makeJwt(3600, { sub: 'bob' });
      localStorage.setItem('facet_token', bobToken);
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token', newValue: bobToken }));
      const bobRequest = httpTesting.expectOne('/api/auth/status');
      const current = service.revalidate();

      aliceRequest.flush('offline', { status: 503, statusText: 'Unavailable' });
      await stale;
      const joined = service.revalidate();
      expect(joined).toBe(current);
      httpTesting.expectNone('/api/auth/status');
      const bob = { ...mockStatus, user_id: 'bob' };
      bobRequest.flush(bob);
      expect(await joined).toEqual(bob);
    });

    it('keeps only the final account after two cross-tab token rotations finish out of order', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      service.status.set({ ...mockStatus, user_id: 'alice', edition_authenticated: true });
      const alice = service.revalidate();
      const aliceRequest = httpTesting.expectOne('/api/auth/status');
      const bobToken = makeJwt(3600, { sub: 'bob' });
      localStorage.setItem('facet_token', bobToken);
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token', newValue: bobToken }));
      const bobRequest = httpTesting.expectOne('/api/auth/status');

      const finalToken = makeJwt(3600, { sub: 'carol' });
      localStorage.setItem('facet_token', finalToken);
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token', newValue: finalToken }));
      const current = service.revalidate();
      const finalRequest = httpTesting.expectOne('/api/auth/status');
      expect(finalRequest.request.headers.get('Authorization')).toBe(`Bearer ${finalToken}`);
      const finalStatus = { ...mockStatus, user_id: 'carol' };
      finalRequest.flush(finalStatus);
      await current;
      bobRequest.flush({ ...mockStatus, user_id: 'bob', edition_authenticated: true });
      aliceRequest.flush({ ...mockStatus, user_id: 'alice', edition_authenticated: true });
      await alice;
      expect(service.status()).toEqual(finalStatus);
      expect(service.identity()).toBe('1|carol');
      expect(service.isEdition()).toBe(false);
    });

    it('invalidates the account when another tab clears localStorage', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      service.status.set(mockStatus);
      localStorage.removeItem('facet_token');
      window.dispatchEvent(new StorageEvent('storage', { key: null }));
      expect(service.status()).toBeNull();
      httpTesting.expectOne('/api/auth/status').flush({ ...mockStatus, authenticated: false });
      await nextTurn();
      expect(service.isAuthenticated()).toBe(false);
    });

    it('should refetch status when another tab rewrites the token', async () => {
      service.status.set({ ...mockStatus, edition_authenticated: true });

      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token' }));

      httpTesting.expectOne('/api/auth/status').flush(mockStatus);
      await nextTurn();
      expect(service.isEdition()).toBe(false);
    });

    it('should ignore changes to unrelated storage keys', () => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_language' }));

      httpTesting.expectNone('/api/auth/status');
    });
  });

  describe('private image key', () => {
    const singleUser: AuthStatus = {
      ...mockStatus, multi_user: false, edition_authenticated: false, edition_password_required: true,
      user_id: null, user_role: null,
    };

    async function confirm(status: AuthStatus): Promise<void> {
      const pending = service.revalidate();
      httpTesting.expectOne('/api/auth/status').flush(status);
      await pending;
    }

    it('rotates when another tab signs in a different account', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      await confirm({ ...mockStatus, user_id: 'alice' });
      const aliceKey = privateImageSessionKey();
      const bobToken = makeJwt(3600, { sub: 'bob' });
      localStorage.setItem('facet_token', bobToken);
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token', newValue: bobToken }));
      httpTesting.expectOne('/api/auth/status').flush({ ...mockStatus, user_id: 'bob' });
      await nextTurn();
      expect(service.identity()).toBe('1|bob');
      expect(privateImageSessionKey()).not.toBe(aliceKey);
    });

    it('rotates on an account login, even when the same account signs in again', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      await confirm({ ...mockStatus, user_id: 'alice' });
      const before = privateImageSessionKey();
      const login = service.login('secret', 'alice');
      httpTesting.expectOne('/api/auth/login').flush({ access_token: makeJwt(3600, { sub: 'alice' }) });
      await nextTurn();
      httpTesting.expectOne('/api/auth/status').flush({ ...mockStatus, user_id: 'alice' });
      expect(await login).toBe('ok');
      expect(privateImageSessionKey()).not.toBe(before);
    });

    it('rotates on logout, and again once the cookie is cleared', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      await confirm({ ...mockStatus, user_id: 'alice' });
      const before = privateImageCacheKey();
      const done = service.logout();
      const hidden = privateImageCacheKey();
      httpTesting.expectOne('/api/auth/logout').flush({});
      await done;
      expect(hidden).not.toBe(before);
      expect(privateImageCacheKey()).not.toBe(hidden);
    });

    it('rotates when a failed cookie reconciliation clears the session', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'bob' }));
      service.status.set({ ...mockStatus, user_id: 'bob' });
      const before = privateImageCacheKey();
      const login = service.login('alice-password', 'alice');
      httpTesting.expectOne('/api/auth/login').error(new ProgressEvent('error'));
      await nextTurn();
      httpTesting.expectOne('/api/auth/cookie').flush('revoked', { status: 401, statusText: 'Unauthorized' });
      await nextTurn();
      const cleared = privateImageCacheKey();
      httpTesting.expectOne('/api/auth/logout').flush({});
      expect(await login).toBe('unavailable');
      expect(cleared).not.toBe(before);
      expect(privateImageCacheKey()).not.toBe(cleared);
    });

    it('does not take back a key this document dropped', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      await confirm({ ...mockStatus, user_id: 'alice' });
      const aliceKey = privateImageCacheKey();
      const done = service.logout();
      httpTesting.expectOne('/api/auth/logout').flush({});
      await done;
      // A tab that read storage before the logout writes Alice's key back.
      localStorage.setItem(PRIVATE_IMAGE_SESSION_STORAGE_KEY, JSON.stringify({ owner: null, key: aliceKey }));
      window.dispatchEvent(new StorageEvent('storage', { key: PRIVATE_IMAGE_SESSION_STORAGE_KEY }));
      expect(privateImageCacheKey()).not.toBe(aliceKey);
      expect(JSON.parse(localStorage.getItem(PRIVATE_IMAGE_SESSION_STORAGE_KEY)!).key).toBe(privateImageCacheKey());
      await confirm({ ...mockStatus, user_id: 'bob' });
      expect(privateImageCacheKey()).not.toBe(aliceKey);
    });

    it('starts a new key when another tab clears storage', () => {
      trackTokenStorage(null);
      const before = privateImageCacheKey();
      localStorage.removeItem(PRIVATE_IMAGE_SESSION_STORAGE_KEY);
      window.dispatchEvent(new StorageEvent('storage', { key: null }));
      httpTesting.expectOne('/api/auth/status').flush(mockStatus);
      expect(privateImageCacheKey()).not.toBe(before);
    });

    it('keeps the key while the same account is confirmed again', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      await confirm({ ...mockStatus, user_id: 'alice' });
      const key = privateImageSessionKey();
      await confirm({ ...mockStatus, user_id: 'alice', display_name: 'Alice' });
      expect(privateImageSessionKey()).toBe(key);
    });

    it('keeps the key across an edition unlock and lock, which change no image visibility', async () => {
      trackTokenStorage(makeJwt(3600, {}));
      await confirm(singleUser);
      const identity = service.identity();
      const key = privateImageSessionKey();
      const cacheKey = privateImageCacheKey();
      const unlock = service.editionLogin('edition-pass');
      httpTesting.expectOne('/api/auth/edition/login').flush({ access_token: makeJwt(3600, { edition: true }) });
      await nextTurn();
      // As the server reports it: the edition token's subject, where no token reported none.
      httpTesting.expectOne('/api/auth/status').flush({ ...singleUser, edition_authenticated: true, user_id: '_legacy' });
      expect(await unlock).toBe('ok');
      expect(service.identity()).toBe(identity);
      expect(privateImageSessionKey()).toBe(key);
      const lock = service.dropEdition();
      httpTesting.expectOne('/api/auth/edition/logout').flush({ access_token: makeJwt(3600, { edition: false }) });
      expect(await lock).toBe(true);
      expect(privateImageSessionKey()).toBe(key);
      expect(privateImageCacheKey()).toBe(cacheKey);
    });

    it('adopts the key another tab wrote', () => {
      trackTokenStorage(null);
      const key = 'ab'.repeat(16);
      const session = privateImageSessionKey();
      localStorage.setItem(PRIVATE_IMAGE_SESSION_STORAGE_KEY, JSON.stringify({ owner: null, key }));
      window.dispatchEvent(new StorageEvent('storage', { key: PRIVATE_IMAGE_SESSION_STORAGE_KEY }));
      expect(privateImageCacheKey()).toBe(key);
      expect(privateImageSessionKey()).not.toBe(session);
      httpTesting.expectNone('/api/auth/status');
    });
  });

  describe('checkStatus()', () => {
    it('does not overwrite a newer status response even for the same token', async () => {
      const first = service.checkStatus();
      const oldRequest = httpTesting.expectOne('/api/auth/status');
      const second = service.checkStatus();
      const current = { ...mockStatus, edition_authenticated: false };
      httpTesting.expectOne('/api/auth/status').flush(current);
      await second;
      oldRequest.flush({ ...mockStatus, edition_authenticated: true });
      await first.catch(() => undefined);
      expect(service.status()).toEqual(current);
    });

    it('should fetch auth status and update the signal', async () => {
      const promise = service.checkStatus();

      const req = httpTesting.expectOne('/api/auth/status');
      expect(req.request.method).toBe('GET');
      req.flush(mockStatus);

      const result = await promise;
      expect(result).toEqual(mockStatus);
      expect(service.status()).toEqual(mockStatus);
    });
  });

  describe('loadStatus()', () => {
    it('lets a cold guard load finish while the app status request is still pending', async () => {
      const guard = service.loadStatus();
      const guardRequest = httpTesting.expectOne('/api/auth/status');
      const app = service.checkStatus();
      const appRequest = httpTesting.expectOne('/api/auth/status');
      guardRequest.flush(mockStatus);
      const guardResult = await guard.catch(() => null);
      appRequest.flush(mockStatus);
      await app;
      expect(guardResult).toEqual(mockStatus);
      expect(service.status()).toEqual(mockStatus);
    });

    it('does not reuse or release an older account load after logout', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      const previous = service.loadStatus().catch(() => null);
      const previousRequest = httpTesting.expectOne('/api/auth/status');
      const logout = service.logout();
      httpTesting.expectOne('/api/auth/logout').flush({ ok: true });
      await logout;
      const current = service.loadStatus();
      const currentRequest = httpTesting.expectOne('/api/auth/status');

      previousRequest.flush('offline', { status: 503, statusText: 'Unavailable' });
      await previous;
      const joined = service.loadStatus();
      expect(joined).toBe(current);
      httpTesting.expectNone('/api/auth/status');
      const loggedOut = { ...mockStatus, authenticated: false, user_id: null };
      currentRequest.flush(loggedOut);
      expect(await joined).toEqual(loggedOut);
      expect(service.status()).toEqual(loggedOut);
    });

    it('shares one request between concurrent callers', async () => {
      const first = service.loadStatus();
      const second = service.loadStatus();

      httpTesting.expectOne('/api/auth/status').flush(mockStatus);

      expect(await first).toEqual(mockStatus);
      expect(await second).toEqual(mockStatus);
    });

    it('answers from the cache without a request once the status is known', async () => {
      service.status.set(mockStatus);

      expect(await service.loadStatus()).toEqual(mockStatus);
      httpTesting.expectNone('/api/auth/status');
    });

    it('rejects on a failed load and retries on the next call', async () => {
      const failed = service.loadStatus();
      httpTesting.expectOne('/api/auth/status').flush('x', { status: 500, statusText: 'err' });
      await expect(failed).rejects.toBeDefined();

      const retry = service.loadStatus();
      httpTesting.expectOne('/api/auth/status').flush(mockStatus);
      expect(await retry).toEqual(mockStatus);
    });
  });

  describe('login()', () => {
    it('does not restore a previous account from a status response that follows login', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice' }));
      service.status.set({ ...mockStatus, user_id: 'alice' });
      const old = service.revalidate();
      const oldRequest = httpTesting.expectOne('/api/auth/status');
      const login = service.login('secret', 'bob');
      const bobToken = makeJwt(3600, { sub: 'bob' });
      httpTesting.expectOne('/api/auth/login').flush({ access_token: bobToken });
      await nextTurn();
      expect(service.status()).toBeNull();
      const bob = { ...mockStatus, user_id: 'bob' };
      httpTesting.expectOne('/api/auth/status').flush(bob);
      expect(await login).toBe('ok');
      oldRequest.flush({ ...mockStatus, user_id: 'alice' });
      await old;
      expect(service.status()).toEqual(bob);
    });

    it('clears a pending login cookie before allowing a logged-out guard to check status', async () => {
      trackTokenStorage(null);
      const login = service.login('secret', 'alice');
      const loginRequest = httpTesting.expectOne('/api/auth/login');
      const logout = service.logout();
      const guard = service.loadStatus();
      httpTesting.expectNone('/api/auth/logout');
      httpTesting.expectNone('/api/auth/status');
      loginRequest.flush({ access_token: makeJwt(3600, { sub: 'alice' }) });
      await nextTurn();
      httpTesting.expectOne('/api/auth/status').flush({ ...mockStatus, user_id: 'alice' });
      await login;
      await nextTurn();
      expect(service.status()).toBeNull();
      httpTesting.expectOne('/api/auth/logout').flush({ ok: true });
      await logout;
      await nextTurn();
      httpTesting.expectOne('/api/auth/status').flush({ ...mockStatus, authenticated: false, user_id: null });
      await guard;
      expect(service.token).toBeNull();
      expect(service.isAuthenticated()).toBe(false);
    });

    it('should POST credentials and store token on success', async () => {
      const loginPromise = service.login('secret123', 'admin');

      // Handle login request
      const loginReq = httpTesting.expectOne('/api/auth/login');
      expect(loginReq.request.method).toBe('POST');
      expect(loginReq.request.body).toEqual({ password: 'secret123', username: 'admin' });
      loginReq.flush({ access_token: 'jwt-token-123', token_type: 'bearer' });

      // Allow microtask to process so checkStatus() fires
      await nextTurn();

      // Handle checkStatus request triggered after login
      const statusReq = httpTesting.expectOne('/api/auth/status');
      statusReq.flush(mockStatus);

      const result = await loginPromise;
      expect(result).toBe('ok');
      expect(setItemSpy).toHaveBeenCalledWith('facet_token', 'jwt-token-123');
    });

    it('should POST password only when username is not provided', async () => {
      const loginPromise = service.login('secret123');

      const loginReq = httpTesting.expectOne('/api/auth/login');
      expect(loginReq.request.body).toEqual({ password: 'secret123' });
      loginReq.flush({ access_token: 'token', token_type: 'bearer' });

      await nextTurn();

      const statusReq = httpTesting.expectOne('/api/auth/status');
      statusReq.flush(mockStatus);

      await loginPromise;
    });

    it("reports 'unavailable' and clears an unconfirmed cookie when login has no access_token", async () => {
      const loginPromise = service.login('wrong');

      const loginReq = httpTesting.expectOne('/api/auth/login');
      loginReq.flush({});
      await nextTurn();
      httpTesting.expectOne('/api/auth/logout').flush({ ok: true });

      const result = await loginPromise;
      expect(result).toBe('unavailable');
      expect(setItemSpy).not.toHaveBeenCalledWith('facet_token', expect.anything());
    });

    it("should report 'invalid' on a 401", async () => {
      const loginPromise = service.login('wrong');

      const loginReq = httpTesting.expectOne('/api/auth/login');
      loginReq.flush('Unauthorized', { status: 401, statusText: 'Unauthorized' });

      const result = await loginPromise;
      expect(result).toBe('invalid');
    });

    it("should report 'unavailable' on a 503, not a wrong password", async () => {
      // The server answers 503 when it could not read its own config and is
      // refusing to authenticate anyone. Collapsing that into 'invalid' told
      // the operator their password was wrong -- the one thing it was not.
      const loginPromise = service.login('correct-password');

      const loginReq = httpTesting.expectOne('/api/auth/login');
      loginReq.flush('Configuration could not be read; refusing to authenticate.', {
        status: 503,
        statusText: 'Service Unavailable',
      });

      const result = await loginPromise;
      expect(result).toBe('unavailable');
      expect(setItemSpy).not.toHaveBeenCalledWith('facet_token', expect.anything());
    });

    it("should report 'rate_limited' on a 429, not a wrong password", async () => {
      // The rate limiter rejects the request before any password check runs,
      // so it is never bad credentials -- and retyping one only extends the
      // lockout window.
      const loginPromise = service.login('correct-password');

      const loginReq = httpTesting.expectOne('/api/auth/login');
      loginReq.flush('Too many login attempts. Try again later.', {
        status: 429,
        statusText: 'Too Many Requests',
      });

      const result = await loginPromise;
      expect(result).toBe('rate_limited');
      expect(setItemSpy).not.toHaveBeenCalledWith('facet_token', expect.anything());
    });
  });

  describe('cookie mutation ordering', () => {
    it.each([true, false])('applies the first login before the queued login (second succeeds: %s)', async succeeds => {
      trackTokenStorage(makeJwt(3600, { sub: 'old' }));
      service.status.set({ ...mockStatus, user_id: 'old' });
      const alice = service.login('alice-password', 'alice');
      const aliceRequest = httpTesting.expectOne('/api/auth/login');
      const bob = service.login('bob-password', 'bob');
      httpTesting.expectNone('/api/auth/login');
      expect(service.status()).toBeNull();

      const aliceToken = makeJwt(3600, { sub: 'alice' });
      aliceRequest.flush({ access_token: aliceToken });
      await nextTurn();
      const aliceStatus = { ...mockStatus, user_id: 'alice' };
      httpTesting.expectOne('/api/auth/status').flush(aliceStatus);
      expect(await alice).toBe('ok');
      await nextTurn();
      const bobRequest = httpTesting.expectOne('/api/auth/login');
      expect(bobRequest.request.body).toEqual({ password: 'bob-password', username: 'bob' });
      expect(service.token).toBe(aliceToken);
      expect(service.status()).toBeNull();
      if (succeeds) {
        const bobToken = makeJwt(3600, { sub: 'bob' });
        bobRequest.flush({ access_token: bobToken });
        await nextTurn();
        const bobStatus = { ...mockStatus, user_id: 'bob' };
        httpTesting.expectOne('/api/auth/status').flush(bobStatus);
        expect(await bob).toBe('ok');
        expect(service.token).toBe(bobToken);
        expect(service.status()).toEqual(bobStatus);
      } else {
        bobRequest.flush('incorrect password', { status: 401, statusText: 'Unauthorized' });
        expect(await bob).toBe('invalid');
        expect(service.token).toBe(aliceToken);
        expect(service.status()).toEqual(aliceStatus);
      }
    });

    it('orders edition unlock, lock and logout without cancelling queued user actions', async () => {
      trackTokenStorage(makeJwt(3600));
      service.status.set({ ...mockStatus, multi_user: false });
      const unlock = service.editionLogin('edition-password');
      const unlockRequest = httpTesting.expectOne('/api/auth/edition/login');
      const lock = service.dropEdition();
      const logout = service.logout();
      httpTesting.expectNone('/api/auth/edition/logout');
      httpTesting.expectNone('/api/auth/logout');
      const editionToken = makeJwt(3600, { edition: true });
      unlockRequest.flush({ access_token: editionToken });
      await nextTurn();
      httpTesting.expectOne('/api/auth/status').flush({ ...mockStatus, multi_user: false, edition_authenticated: true });
      expect(await unlock).toBe('ok');
      await nextTurn();
      const lockRequest = httpTesting.expectOne('/api/auth/edition/logout');
      expect(lockRequest.request.headers.get('Authorization')).toBe(`Bearer ${editionToken}`);
      const readToken = makeJwt(3600, { edition: false });
      lockRequest.flush({ access_token: readToken });
      expect(await lock).toBe(true);
      await nextTurn();
      const logoutRequest = httpTesting.expectOne('/api/auth/logout');
      expect(logoutRequest.request.headers.get('Authorization')).toBe(`Bearer ${readToken}`);
      logoutRequest.flush({ ok: true });
      await logout;
      expect(service.token).toBeNull();
      expect(service.status()).toBeNull();
    });

    it('aborts a stuck login request before starting queued logout', async () => {
      vi.useFakeTimers();
      try {
        trackTokenStorage(makeJwt(3600));
        service.status.set(mockStatus);
        const login = service.login('password', 'alice');
        const request = httpTesting.expectOne('/api/auth/login');
        const logout = service.logout();
        httpTesting.expectNone('/api/auth/logout');
        await vi.advanceTimersByTimeAsync(15_000);
        expect(request.cancelled).toBe(true);
        // The uncertain login may already have set a cookie; cleanup remains
        // inside its lock before the explicitly queued logout starts.
        httpTesting.expectOne('/api/auth/logout').flush({ ok: true });
        expect(await login).toBe('unavailable');
        await vi.advanceTimersByTimeAsync(0);
        httpTesting.expectOne('/api/auth/logout').flush({ ok: true });
        await logout;
        expect(service.token).toBeNull();
        expect(service.status()).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    it('waits for the origin lock and retains queued intent across storage events', async () => {
      const descriptor = Object.getOwnPropertyDescriptor(navigator, 'locks');
      let grant!: () => void;
      const request = vi.fn((_name: string, _options: object, callback: () => Promise<unknown>) =>
        new Promise<unknown>(resolve => { grant = () => resolve(callback()); }));
      Object.defineProperty(navigator, 'locks', { configurable: true, value: { request } });
      try {
        trackTokenStorage(makeJwt(3600, { sub: 'old' }));
        service.status.set({ ...mockStatus, user_id: 'old' });
        const bob = service.login('bob-password', 'bob');
        expect(request).toHaveBeenCalledWith('facet-auth-cookie', expect.objectContaining({ signal: expect.any(AbortSignal) }), expect.any(Function));
        httpTesting.expectNone('/api/auth/login');
        const aliceToken = makeJwt(3600, { sub: 'alice' });
        localStorage.setItem('facet_token', aliceToken);
        window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token', newValue: aliceToken }));
        const reconciliation = service.revalidate();
        expect(service.status()).toBeNull();
        httpTesting.expectNone('/api/auth/status');

        grant();
        const bobToken = makeJwt(3600, { sub: 'bob' });
        httpTesting.expectOne('/api/auth/login').flush({ access_token: bobToken });
        await nextTurn();
        const bobStatus = { ...mockStatus, user_id: 'bob' };
        httpTesting.expectOne('/api/auth/status').flush(bobStatus);
        expect(await bob).toBe('ok');
        await nextTurn();
        httpTesting.expectOne('/api/auth/status').flush(bobStatus);
        await reconciliation;
        expect(service.token).toBe(bobToken);
        expect(service.status()).toEqual(bobStatus);
      } finally {
        if (descriptor) Object.defineProperty(navigator, 'locks', descriptor);
        else Reflect.deleteProperty(navigator, 'locks');
      }
    });

    it('bounds origin lock waiting without dispatching a cookie request after cancellation', async () => {
      const descriptor = Object.getOwnPropertyDescriptor(navigator, 'locks');
      vi.useFakeTimers();
      const request = vi.fn((_name: string, options: { signal: AbortSignal }) =>
        new Promise<never>((_resolve, reject) => {
          options.signal.addEventListener('abort', () => reject(new DOMException('Lock wait expired', 'AbortError')));
        }));
      Object.defineProperty(navigator, 'locks', { configurable: true, value: { request } });
      try {
        trackTokenStorage(makeJwt(3600));
        service.status.set(mockStatus);
        const login = service.login('password', 'alice');
        await vi.advanceTimersByTimeAsync(60_000);
        expect(await login).toBe('unavailable');
        expect(request.mock.calls[0][1].signal.aborted).toBe(true);
        httpTesting.expectNone('/api/auth/login');
        expect(service.status()).toEqual(mockStatus);
      } finally {
        vi.useRealTimers();
        if (descriptor) Object.defineProperty(navigator, 'locks', descriptor);
        else Reflect.deleteProperty(navigator, 'locks');
      }
    });
  });

  describe('uncertain cookie recovery', () => {
    it.each([0, 200])('restores the known account only after cookie synchronization for HTTP %s', async status => {
      const bobToken = makeJwt(3600, { sub: 'bob' });
      trackTokenStorage(bobToken);
      const bob = { ...mockStatus, user_id: 'bob' };
      service.status.set(bob);
      const login = service.login('alice-password', 'alice');
      httpTesting.expectOne('/api/auth/login').error(new ProgressEvent('error'), { status, statusText: 'Truncated response' });
      await nextTurn();
      const synchronization = httpTesting.expectOne('/api/auth/cookie');
      expect(synchronization.request.headers.get('Authorization')).toBe(`Bearer ${bobToken}`);
      expect(service.status()).toBeNull();
      expect(localStorage.getItem('facet_auth_cookie_uncertain')).toBe('1');
      synchronization.flush(null, { status: 204, statusText: 'No Content' });
      expect(await login).toBe('unavailable');
      expect(service.token).toBe(bobToken);
      expect(service.status()).toEqual(bob);
      expect(localStorage.getItem('facet_auth_cookie_uncertain')).toBeNull();
    });

    it('blocks cookie-only status after failed cleanup and reload, then permits explicit login retry', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'bob' }));
      service.status.set({ ...mockStatus, user_id: 'bob' });
      const login = service.login('alice-password', 'alice');
      httpTesting.expectOne('/api/auth/login').error(new ProgressEvent('error'));
      await nextTurn();
      httpTesting.expectOne('/api/auth/cookie').flush('revoked', { status: 401, statusText: 'Unauthorized' });
      await nextTurn();
      httpTesting.expectOne('/api/auth/logout').flush('offline', { status: 503, statusText: 'Unavailable' });
      expect(await login).toBe('unavailable');
      expect(service.status()).toBeNull();
      expect(service.token).toBeNull();
      expect(localStorage.getItem('facet_auth_cookie_uncertain')).toBe('1');

      // A new instance models reload: no memory of the failed request survives.
      const reloaded = TestBed.runInInjectionContext(() => new AuthService());
      expect(reloaded.isMultiUser()).toBe(true);
      const guarded = reloaded.loadStatus();
      httpTesting.expectOne('/api/auth/logout').flush('offline', { status: 503, statusText: 'Unavailable' });
      await expect(guarded).rejects.toThrow('could not be reconciled');
      httpTesting.expectNone('/api/auth/status');
      expect(reloaded.isAuthenticated()).toBe(false);

      const retry = reloaded.login('bob-password', 'bob');
      const bobToken = makeJwt(3600, { sub: 'bob' });
      httpTesting.expectOne('/api/auth/login').flush({ access_token: bobToken });
      await nextTurn();
      const bob = { ...mockStatus, user_id: 'bob' };
      httpTesting.expectOne('/api/auth/status').flush(bob);
      expect(await retry).toBe('ok');
      expect(reloaded.status()).toEqual(bob);
      expect(localStorage.getItem('facet_auth_cookie_uncertain')).toBeNull();
    });

    it('reconciles the latest credential when storage changes during cookie synchronization', async () => {
      const bobToken = makeJwt(3600, { sub: 'bob' });
      trackTokenStorage(bobToken);
      service.status.set({ ...mockStatus, user_id: 'bob' });
      const login = service.login('alice-password', 'alice');
      httpTesting.expectOne('/api/auth/login').error(new ProgressEvent('error'));
      await nextTurn();
      const oldSynchronization = httpTesting.expectOne('/api/auth/cookie');
      const carolToken = makeJwt(3600, { sub: 'carol' });
      localStorage.setItem('facet_token', carolToken);
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token', newValue: carolToken }));
      const reconciliation = service.revalidate();
      oldSynchronization.flush(null, { status: 204, statusText: 'No Content' });
      await nextTurn();
      const currentSynchronization = httpTesting.expectOne('/api/auth/cookie');
      expect(currentSynchronization.request.headers.get('Authorization')).toBe(`Bearer ${carolToken}`);
      currentSynchronization.flush(null, { status: 204, statusText: 'No Content' });
      expect(await login).toBe('unavailable');
      expect(service.status()).toBeNull();
      await nextTurn();
      const carol = { ...mockStatus, user_id: 'carol' };
      httpTesting.expectOne('/api/auth/status').flush(carol);
      await reconciliation;
      expect(service.status()).toEqual(carol);
      expect(service.token).toBe(carolToken);
    });

    it('does not restore edition privileges when malformed lock recovery falls back to logout', async () => {
      trackTokenStorage(makeJwt(3600, { edition: true }));
      service.status.set({ ...mockStatus, multi_user: false, edition_authenticated: true });
      const lock = service.dropEdition();
      httpTesting.expectOne('/api/auth/edition/logout').flush({});
      await nextTurn();
      httpTesting.expectOne('/api/auth/cookie').flush('revoked', { status: 401, statusText: 'Unauthorized' });
      await nextTurn();
      httpTesting.expectOne('/api/auth/logout').flush({ ok: true });
      expect(await lock).toBe(false);
      expect(service.token).toBeNull();
      expect(service.status()).toBeNull();
      expect(service.isEdition()).toBe(false);
    });
  });

  describe('editionLogin()', () => {
    it('should POST edition password and store token on success', async () => {
      const loginPromise = service.editionLogin('edition-pass');

      const loginReq = httpTesting.expectOne('/api/auth/edition/login');
      expect(loginReq.request.method).toBe('POST');
      expect(loginReq.request.body).toEqual({ password: 'edition-pass' });
      loginReq.flush({ access_token: 'edition-token', token_type: 'bearer' });

      await nextTurn();

      const statusReq = httpTesting.expectOne('/api/auth/status');
      statusReq.flush(mockStatus);

      const result = await loginPromise;
      expect(result).toBe('ok');
      expect(setItemSpy).toHaveBeenCalledWith('facet_token', 'edition-token');
    });

    it("should report 'invalid' when edition login fails", async () => {
      const loginPromise = service.editionLogin('wrong');

      const loginReq = httpTesting.expectOne('/api/auth/edition/login');
      loginReq.flush('Forbidden', { status: 403, statusText: 'Forbidden' });

      const result = await loginPromise;
      expect(result).toBe('invalid');
    });

    it("should report 'unavailable' when the server is unreachable (status 0)", async () => {
      // A dropped connection, a stopped server or a CORS failure never reached
      // the password check either, so calling it invalid credentials repeats
      // the same conflation one layer down.
      const loginPromise = service.editionLogin('edition-pass');

      const loginReq = httpTesting.expectOne('/api/auth/edition/login');
      loginReq.error(new ProgressEvent('error'), { status: 0, statusText: 'Unknown Error' });
      await nextTurn();
      httpTesting.expectOne('/api/auth/logout').flush({ ok: true });

      const result = await loginPromise;
      expect(result).toBe('unavailable');
    });

    it("should report 'unavailable' when the server cannot read its config", async () => {
      const loginPromise = service.editionLogin('edition-pass');

      const loginReq = httpTesting.expectOne('/api/auth/edition/login');
      loginReq.flush('Server error', { status: 500, statusText: 'Internal Server Error' });

      const result = await loginPromise;
      expect(result).toBe('unavailable');
    });

    it("should report 'rate_limited' on a 429, not a wrong password", async () => {
      const loginPromise = service.editionLogin('edition-pass');

      const loginReq = httpTesting.expectOne('/api/auth/edition/login');
      loginReq.flush('Too many login attempts. Try again later.', {
        status: 429,
        statusText: 'Too Many Requests',
      });

      const result = await loginPromise;
      expect(result).toBe('rate_limited');
    });
  });

  describe('logout()', () => {
    // logout() fires a fire-and-forget POST to clear the HttpOnly auth cookie.
    const flushLogout = () =>
      httpTesting.expectOne('/api/auth/logout').flush({ ok: true });

    it('does not restore the logged-out account from an in-flight status request', async () => {
      trackTokenStorage(makeJwt(3600));
      service.status.set(mockStatus);
      const pending = service.revalidate();
      const statusRequest = httpTesting.expectOne('/api/auth/status');
      service.logout();
      flushLogout();
      statusRequest.flush(mockStatus);
      await pending;
      expect(service.status()).toBeNull();
      expect(service.token).toBeNull();
    });

    it('should clear the server auth cookie', () => {
      service.logout();
      const req = httpTesting.expectOne('/api/auth/logout');
      expect(req.request.method).toBe('POST');
      req.flush({ ok: true });
    });

    it('should remove token from localStorage', () => {
      service.logout();
      flushLogout();
      expect(removeItemSpy).toHaveBeenCalledWith('facet_token');
    });

    it('clears private person assignment recents on shared-browser logout', () => {
      service.logout();
      flushLogout();
      expect(removeItemSpy).toHaveBeenCalledWith('facet_person_assignments_v1');
    });

    it('refuses a late assignment receipt after logout with an unchanged single-user identity', () => {
      const history = TestBed.inject(PersonAssignmentHistoryService);
      service.status.set({ ...mockStatus, authenticated: false, multi_user: false,
        user_id: null, edition_authenticated: true });
      const owner = service.identity();
      expect(owner).toBe('0|');
      expect(service.isEdition()).toBe(true);
      service.logout();
      flushLogout();
      expect(service.identity()).toBe(owner);
      setItemSpy.mockClear();
      // A successful assignment response may arrive after the submitted save survives logout.
      history.record(42, owner);
      expect(setItemSpy).not.toHaveBeenCalled();
    });

    it('should set status to null', () => {
      service.status.set(mockStatus);
      service.logout();
      flushLogout();
      expect(service.status()).toBeNull();
    });

    it('should navigate to /login', () => {
      service.logout();
      flushLogout();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/login']);
    });
  });

  describe('dropEdition()', () => {
    const editionStatus = {
      ...mockStatus, multi_user: false, edition_authenticated: true,
      edition_password_required: true, user_id: null, user_role: null,
    };

    it('replaces the token and drops edition only after the server confirms the swap', async () => {
      trackTokenStorage(makeJwt(3600, { edition: true }));
      service.status.set(editionStatus);
      const stale = service.revalidate();
      const oldRequest = httpTesting.expectOne('/api/auth/status');
      const dropping = service.dropEdition();
      expect(service.status()).toBeNull();
      const readToken = makeJwt(3600, { edition: false });
      httpTesting.expectOne('/api/auth/edition/logout').flush({ access_token: readToken });
      expect(await dropping).toBe(true);
      expect(service.token).toBe(readToken);
      expect(service.isEdition()).toBe(false);
      const readStatus = service.revalidate();
      const nextRequest = httpTesting.expectOne('/api/auth/status');
      expect(nextRequest.request.headers.get('Authorization')).toBe(`Bearer ${readToken}`);
      nextRequest.flush({ ...editionStatus, edition_authenticated: false });
      await readStatus;
      oldRequest.flush(editionStatus);
      await stale;
      expect(service.isEdition()).toBe(false);
    });

    it.each([0, 401, 403, 500])('keeps the actual edition state and reports failure for HTTP %s', async status => {
      const token = makeJwt(3600, { edition: true });
      trackTokenStorage(token);
      service.status.set(editionStatus);
      const dropping = service.dropEdition();
      const req = httpTesting.expectOne('/api/auth/edition/logout');
      expect(req.request.headers.get('Authorization')).toBe(`Bearer ${token}`);
      if (status === 0) {
        req.error(new ProgressEvent('error'));
        await nextTurn();
        httpTesting.expectOne('/api/auth/cookie').flush(null, { status: 204, statusText: 'No Content' });
      } else req.flush('failed', { status, statusText: 'failed' });
      const result = await dropping;
      expect(service.token).toBe(token);
      expect(service.status()).toEqual(editionStatus);
      expect(result).toBe(false);
    });

    it('does not claim a lock when a success response contains no replacement token', async () => {
      const token = makeJwt(3600, { edition: true });
      trackTokenStorage(token);
      service.status.set(editionStatus);
      const dropping = service.dropEdition();
      httpTesting.expectOne('/api/auth/edition/logout').flush({});
      await nextTurn();
      httpTesting.expectOne('/api/auth/cookie').flush(null, { status: 204, statusText: 'No Content' });
      const result = await dropping;
      expect(service.token).toBe(token);
      expect(service.isEdition()).toBe(true);
      expect(result).toBe(false);
    });

    it('applies a cookie response even when a storage event arrives during the mutation', async () => {
      trackTokenStorage(makeJwt(3600, { sub: 'alice', edition: true }));
      service.status.set(editionStatus);
      const dropping = service.dropEdition();
      const oldRequest = httpTesting.expectOne('/api/auth/edition/logout');
      const bobToken = makeJwt(3600, { sub: 'bob' });
      localStorage.setItem('facet_token', bobToken);
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token', newValue: bobToken }));
      httpTesting.expectNone('/api/auth/status');
      const readToken = makeJwt(3600, { sub: 'alice' });
      oldRequest.flush({ access_token: readToken });
      expect(await dropping).toBe(true);
      await nextTurn();
      const request = httpTesting.expectOne('/api/auth/status');
      expect(request.request.headers.get('Authorization')).toBe(`Bearer ${readToken}`);
      const locked = { ...editionStatus, edition_authenticated: false };
      request.flush(locked);
      await nextTurn();
      expect(service.token).toBe(readToken);
      expect(service.status()).toEqual(locked);
    });
  });

  describe('hasFeature()', () => {
    it('should return true for an enabled feature', () => {
      service.status.set(mockStatus);
      expect(service.hasFeature('face_recognition')).toBe(true);
    });

    it('should return false for a disabled feature', () => {
      service.status.set(mockStatus);
      expect(service.hasFeature('edition')).toBe(false);
    });

    it('should return false for an unknown feature', () => {
      service.status.set(mockStatus);
      expect(service.hasFeature('nonexistent')).toBe(false);
    });

    it('should return false when status is null', () => {
      expect(service.hasFeature('face_recognition')).toBe(false);
    });
  });
});
