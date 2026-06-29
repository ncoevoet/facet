import type { MockInstance } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { AuthService, AuthStatus } from './auth.service';

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
      getItemSpy.mockReturnValue('my-jwt-token');
      expect(service.token).toBe('my-jwt-token');
      expect(localStorage.getItem).toHaveBeenCalledWith('facet_token');
    });

    it('should return null when no token stored', () => {
      getItemSpy.mockReturnValue(null);
      expect(service.token).toBeNull();
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
      expect(result).toBe(true);
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

    it('should return false when login response has no access_token', async () => {
      const loginPromise = service.login('wrong');

      const loginReq = httpTesting.expectOne('/api/auth/login');
      loginReq.flush({});

      const result = await loginPromise;
      expect(result).toBe(false);
      expect(setItemSpy).not.toHaveBeenCalledWith('facet_token', expect.anything());
    });

    it('should return false when login request fails', async () => {
      const loginPromise = service.login('wrong');

      const loginReq = httpTesting.expectOne('/api/auth/login');
      loginReq.flush('Unauthorized', { status: 401, statusText: 'Unauthorized' });

      const result = await loginPromise;
      expect(result).toBe(false);
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
      expect(result).toBe(true);
      expect(setItemSpy).toHaveBeenCalledWith('facet_token', 'edition-token');
    });

    it('should return false when edition login fails', async () => {
      const loginPromise = service.editionLogin('wrong');

      const loginReq = httpTesting.expectOne('/api/auth/edition/login');
      loginReq.flush('Forbidden', { status: 403, statusText: 'Forbidden' });

      const result = await loginPromise;
      expect(result).toBe(false);
    });
  });

  describe('logout()', () => {
    it('should remove token from localStorage', () => {
      service.logout();
      expect(removeItemSpy).toHaveBeenCalledWith('facet_token');
    });

    it('should set status to null', () => {
      service.status.set(mockStatus);
      service.logout();
      expect(service.status()).toBeNull();
    });

    it('should navigate to /login', () => {
      service.logout();
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
