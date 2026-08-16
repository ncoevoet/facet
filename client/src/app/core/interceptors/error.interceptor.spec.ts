import type { Mock, MockedFunction } from 'vitest';
import { TestBed } from '@angular/core/testing';
import {
  HttpBackend,
  HttpRequest,
  HttpHandlerFn,
  HttpErrorResponse,
} from '@angular/common/http';
import { EMPTY, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { errorInterceptor } from './error.interceptor';
import { AuthService } from '../services/auth.service';
import { I18nService } from '../services/i18n.service';

describe('errorInterceptor', () => {
  let authMock: { token: string | null; logout: Mock; isEdition: Mock; revalidate: Mock };
  let snackBarMock: { open: Mock };
  let i18nMock: { t: Mock; locale: Mock };
  let backendMock: { handle: Mock };
  let next: MockedFunction<HttpHandlerFn>;

  beforeEach(() => {
    authMock = {
      token: null,
      logout: vi.fn(),
      isEdition: vi.fn(() => false),
      revalidate: vi.fn(() => Promise.resolve(null)),
    };
    snackBarMock = { open: vi.fn() };
    i18nMock = { t: vi.fn((key: string) => key), locale: vi.fn(() => 'en') };
    // The interceptor uses HttpBackend directly to post 5xx crash reports
    // without recursing through itself. Mock returns an empty observable so
    // the post is a no-op.
    backendMock = { handle: vi.fn(() => EMPTY) };
    next = vi.fn();

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: authMock },
        { provide: MatSnackBar, useValue: snackBarMock },
        { provide: I18nService, useValue: i18nMock },
        { provide: HttpBackend, useValue: backendMock },
      ],
    });
  });

  const runInterceptor = (req: HttpRequest<unknown>) =>
    TestBed.runInInjectionContext(() => errorInterceptor(req, next));

  it('calls auth.logout() on 401 for non-auth URLs', () =>
    new Promise<void>((resolve) => {
      const req = new HttpRequest('GET', '/api/photos');
      const error = new HttpErrorResponse({ status: 401, url: '/api/photos' });
      next.mockReturnValue(throwError(() => error));

      runInterceptor(req).subscribe({
        error: () => {
          expect(authMock.logout).toHaveBeenCalled();
          resolve();
        },
      });
    }));

  it('does NOT call auth.logout() on 401 for /api/auth/ URLs', () =>
    new Promise<void>((resolve) => {
      const req = new HttpRequest('GET', '/api/auth/status');
      const error = new HttpErrorResponse({ status: 401, url: '/api/auth/status' });
      next.mockReturnValue(throwError(() => error));

      runInterceptor(req).subscribe({
        error: () => {
          expect(authMock.logout).not.toHaveBeenCalled();
          resolve();
        },
      });
    }));

  it('does NOT call auth.logout() on other error codes (404, 500)', () =>
    new Promise<void>((resolve) => {
      const req = new HttpRequest('GET', '/api/photos');
      const error404 = new HttpErrorResponse({ status: 404, url: '/api/photos' });
      next.mockReturnValue(throwError(() => error404));

      runInterceptor(req).subscribe({
        error: () => {
          expect(authMock.logout).not.toHaveBeenCalled();

          const error500 = new HttpErrorResponse({ status: 500, url: '/api/photos' });
          next.mockReturnValue(throwError(() => error500));

          runInterceptor(req).subscribe({
            error: () => {
              expect(authMock.logout).not.toHaveBeenCalled();
              resolve();
            },
          });
        },
      });
    }));

  it('re-throws the error', () =>
    new Promise<void>((resolve, reject) => {
      const req = new HttpRequest('GET', '/api/photos');
      const error = new HttpErrorResponse({ status: 401, url: '/api/photos' });
      next.mockReturnValue(throwError(() => error));

      runInterceptor(req).subscribe({
        next: () => {
          reject(new Error('expected an error'));
        },
        error: (err: HttpErrorResponse) => {
          expect(err.status).toBe(401);
          resolve();
        },
      });
    }));

  it('shows snackbar on 429 rate limit', () =>
    new Promise<void>((resolve) => {
      const req = new HttpRequest('GET', '/api/photos');
      const error = new HttpErrorResponse({ status: 429, url: '/api/photos' });
      next.mockReturnValue(throwError(() => error));

      runInterceptor(req).subscribe({
        error: () => {
          expect(snackBarMock.open).toHaveBeenCalledWith('errors.rate_limited', '', { duration: 5000 });
          resolve();
        },
      });
    }));

  const raise403 = (url = '/api/photos', error: unknown = null) =>
    new Promise<void>((resolve) => {
      const req = new HttpRequest('GET', url);
      next.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 403, url, error })));
      runInterceptor(req).subscribe({ error: () => resolve() });
    });

  it('shows snackbar on 403 for non-auth URLs', async () => {
    await raise403();

    await vi.waitFor(() =>
      expect(snackBarMock.open).toHaveBeenCalledWith('errors.access_denied', '', { duration: 3000 }),
    );
  });

  it('reconciles the cached status on 403 for non-auth URLs', async () => {
    await raise403();

    expect(authMock.revalidate).toHaveBeenCalled();
  });

  it('does NOT reconcile on 403 for /api/auth/ URLs', async () => {
    await raise403('/api/auth/edition/login');

    expect(authMock.revalidate).not.toHaveBeenCalled();
    expect(snackBarMock.open).not.toHaveBeenCalled();
  });

  it('reports a lost edition session when reconciling shows edition is gone', async () => {
    authMock.isEdition.mockReturnValueOnce(true).mockReturnValue(false);

    await raise403();

    await vi.waitFor(() =>
      expect(snackBarMock.open).toHaveBeenCalledWith('errors.edition_expired', '', { duration: 6000 }),
    );
  });

  it('appends the server-supplied detail to the 403 toast', async () => {
    await raise403('/api/photos', { detail: 'target_dir is not an allowed export location' });

    await vi.waitFor(() =>
      expect(snackBarMock.open).toHaveBeenCalledWith(
        'errors.access_denied: target_dir is not an allowed export location',
        '',
        { duration: 8000 },
      ),
    );
  });

  it('falls back to the generic 403 toast when no detail is present', async () => {
    await raise403('/api/photos', {});

    await vi.waitFor(() =>
      expect(snackBarMock.open).toHaveBeenCalledWith('errors.access_denied', '', { duration: 3000 }),
    );
  });

  it('does not crash on a non-string detail (FastAPI validation error list)', async () => {
    await raise403('/api/photos', { detail: [{ loc: ['body', 'target_dir'], msg: 'field required' }] });

    await vi.waitFor(() =>
      expect(snackBarMock.open).toHaveBeenCalledWith('errors.access_denied', '', { duration: 3000 }),
    );
  });

  it('shows snackbar on 500 server error', () =>
    new Promise<void>((resolve) => {
      const req = new HttpRequest('GET', '/api/photos');
      const error = new HttpErrorResponse({ status: 500, url: '/api/photos' });
      next.mockReturnValue(throwError(() => error));

      runInterceptor(req).subscribe({
        error: () => {
          expect(snackBarMock.open).toHaveBeenCalledWith('errors.server_error', '', { duration: 3000 });
          resolve();
        },
      });
    }));
});
