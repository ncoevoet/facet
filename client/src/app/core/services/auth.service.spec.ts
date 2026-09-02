import type { MockInstance } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { AuthService, AuthStatus } from './auth.service';
import { makeJwt } from '../../../testing/jwt';

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

  beforeEach(() => {
    getItemSpy = vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null);
    setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
    removeItemSpy = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {});

    TestBed.configureTestingModule({
      providers: [
        AuthService,
        provideHttpClient(),
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
    it('should refetch status when another tab rewrites the token', async () => {
      service.status.set({ ...mockStatus, edition_authenticated: true });

      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_token' }));

      httpTesting.expectOne('/api/auth/status').flush(mockStatus);
      await Promise.resolve();
      expect(service.isEdition()).toBe(false);
    });

    it('should ignore changes to unrelated storage keys', () => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'facet_language' }));

      httpTesting.expectNone('/api/auth/status');
    });
  });

  describe('checkStatus()', () => {
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

  describe('login()', () => {
    it('should POST credentials and store token on success', async () => {
      const loginPromise = service.login('secret123', 'admin');

      // Handle login request
      const loginReq = httpTesting.expectOne('/api/auth/login');
      expect(loginReq.request.method).toBe('POST');
      expect(loginReq.request.body).toEqual({ password: 'secret123', username: 'admin' });
      loginReq.flush({ access_token: 'jwt-token-123', token_type: 'bearer' });

      // Allow microtask to process so checkStatus() fires
      await Promise.resolve();

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

      await Promise.resolve();

      const statusReq = httpTesting.expectOne('/api/auth/status');
      statusReq.flush(mockStatus);

      await loginPromise;
    });

    it("should report 'invalid' when login response has no access_token", async () => {
      const loginPromise = service.login('wrong');

      const loginReq = httpTesting.expectOne('/api/auth/login');
      loginReq.flush({});

      const result = await loginPromise;
      expect(result).toBe('invalid');
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
  });

  describe('editionLogin()', () => {
    it('should POST edition password and store token on success', async () => {
      const loginPromise = service.editionLogin('edition-pass');

      const loginReq = httpTesting.expectOne('/api/auth/edition/login');
      expect(loginReq.request.method).toBe('POST');
      expect(loginReq.request.body).toEqual({ password: 'edition-pass' });
      loginReq.flush({ access_token: 'edition-token', token_type: 'bearer' });

      await Promise.resolve();

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

    it("should report 'unavailable' when the server cannot read its config", async () => {
      const loginPromise = service.editionLogin('edition-pass');

      const loginReq = httpTesting.expectOne('/api/auth/edition/login');
      loginReq.flush('Server error', { status: 500, statusText: 'Internal Server Error' });

      const result = await loginPromise;
      expect(result).toBe('unavailable');
    });
  });

  describe('logout()', () => {
    // logout() fires a fire-and-forget POST to clear the HttpOnly auth cookie.
    const flushLogout = () =>
      httpTesting.expectOne('/api/auth/logout').flush({ ok: true });

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
