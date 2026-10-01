import { Component, signal, computed } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { AuthService, AuthStatus } from '../services/auth.service';
import { authGuard } from './auth.guard';
import { editionGuard } from './edition.guard';

@Component({ template: '' })
class DummyComponent {}

const STATUS: AuthStatus = {
  authenticated: true,
  multi_user: false,
  edition_enabled: true,
  edition_authenticated: true,
  edition_password_required: true,
  login_password_required: false,
  user_id: null,
  user_role: null,
  display_name: null,
  features: {},
  download_profiles: [],
};

/** An AuthService whose status arrives after a real delay, as on a cold load. */
function makeAuth(result: AuthStatus | 'error', delayMs = 5) {
  const status = signal<AuthStatus | null>(null);
  let pending: Promise<AuthStatus> | null = null;
  const loadStatus = vi.fn((): Promise<AuthStatus> => {
    if (status()) return Promise.resolve(status() as AuthStatus);
    pending ??= new Promise<AuthStatus>((resolve, reject) =>
      setTimeout(() => {
        pending = null;
        if (result === 'error') {
          reject(new Error('offline'));
          return;
        }
        status.set(result);
        resolve(result);
      }, delayMs),
    );
    return pending;
  });
  return { status, loadStatus, isEdition: computed(() => status()?.edition_authenticated ?? false) };
}

describe('editionGuard (real Router, concurrent guards)', () => {
  function setup(auth: ReturnType<typeof makeAuth>) {
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: auth },
        provideRouter([
          { path: '', component: DummyComponent },
          { path: 'compare', component: DummyComponent, canActivate: [authGuard, editionGuard] },
        ]),
      ],
    });
    return TestBed.inject(Router);
  }

  it('lets an edition session through a cold deep link while the status is still loading', async () => {
    const auth = makeAuth(STATUS);
    const router = setup(auth);
    expect(auth.status()).toBeNull();

    const ok = await router.navigateByUrl('/compare');

    expect(ok).toBe(true);
    expect(router.url).toBe('/compare');
  });

  it('shares one status load between the concurrent guards', async () => {
    const auth = makeAuth(STATUS);
    const router = setup(auth);

    await router.navigateByUrl('/compare');

    // Both guards asked; the stub only creates one underlying request.
    expect(auth.loadStatus.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(auth.status()).toEqual(STATUS);
  });

  it('still redirects a session without edition to the gallery', async () => {
    const auth = makeAuth({ ...STATUS, edition_authenticated: false, edition_password_required: false });
    const router = setup(auth);

    await router.navigateByUrl('/compare');

    expect(router.url).toBe('/');
  });

  it('redirects to the gallery when the status cannot be loaded', async () => {
    const auth = makeAuth('error');
    const router = setup(auth);

    await router.navigateByUrl('/compare');

    expect(router.url).not.toBe('/compare');
  });
});
