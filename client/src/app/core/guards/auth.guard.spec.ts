import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Router, ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';
import { signal } from '@angular/core';
import { authGuard } from './auth.guard';
import { AuthService, AuthStatus } from '../services/auth.service';

describe('authGuard', () => {
  let authMock: {
    status: ReturnType<typeof signal<AuthStatus | null>>;
    loadStatus: Mock;
  };
  let routerMock: { navigate: Mock };

  const dummyRoute = {} as ActivatedRouteSnapshot;
  const dummyState = {} as RouterStateSnapshot;

  beforeEach(() => {
    authMock = {
      status: signal<AuthStatus | null>(null),
      loadStatus: vi.fn(),
    };
    routerMock = { navigate: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: authMock },
        { provide: Router, useValue: routerMock },
      ],
    });
  });

  const runGuard = () =>
    TestBed.runInInjectionContext(() => authGuard(dummyRoute, dummyState));

  it('returns true when already authenticated', async () => {
    authMock.status.set({
      authenticated: true,
      multi_user: false,
      edition_enabled: false,
      edition_authenticated: false,
      edition_password_required: false,
      login_password_required: false,
      user_id: null,
      user_role: null,
      display_name: null,
      features: {},
      download_profiles: [],
    });

    const result = await runGuard();

    expect(result).toBe(true);
    expect(authMock.loadStatus).not.toHaveBeenCalled();
    expect(routerMock.navigate).not.toHaveBeenCalled();
  });

  it('calls loadStatus when status is null, returns true if authenticated', async () => {
    authMock.status.set(null);
    authMock.loadStatus.mockImplementation(async () => {
      authMock.status.set({
        authenticated: true,
        multi_user: false,
        edition_enabled: false,
        edition_authenticated: false,
        edition_password_required: false,
        login_password_required: false,
        user_id: null,
        user_role: null,
        display_name: null,
        features: {},
        download_profiles: [],
      });
    });

    const result = await runGuard();

    expect(authMock.loadStatus).toHaveBeenCalled();
    expect(result).toBe(true);
    expect(routerMock.navigate).not.toHaveBeenCalled();
  });

  it('redirects to /login when loadStatus throws', async () => {
    authMock.status.set(null);
    authMock.loadStatus.mockRejectedValue(new Error('Network error'));

    const result = await runGuard();

    expect(authMock.loadStatus).toHaveBeenCalled();
    expect(result).toBe(false);
    expect(routerMock.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('redirects to /login when status exists but not authenticated', async () => {
    authMock.status.set({
      authenticated: false,
      multi_user: false,
      edition_enabled: false,
      edition_authenticated: false,
      edition_password_required: false,
      login_password_required: false,
      user_id: null,
      user_role: null,
      display_name: null,
      features: {},
      download_profiles: [],
    });

    const result = await runGuard();

    expect(result).toBe(false);
    expect(routerMock.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('redirects to /login when status is null after loadStatus', async () => {
    authMock.status.set(null);
    authMock.loadStatus.mockImplementation(async () => {
      // loadStatus resolves but does not set status
    });

    const result = await runGuard();

    expect(authMock.loadStatus).toHaveBeenCalled();
    expect(result).toBe(false);
    expect(routerMock.navigate).toHaveBeenCalledWith(['/login']);
  });
});
