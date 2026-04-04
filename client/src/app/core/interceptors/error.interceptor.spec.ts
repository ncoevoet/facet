import { TestBed } from '@angular/core/testing';
import {
  HttpRequest,
  HttpHandlerFn,
  HttpErrorResponse,
} from '@angular/common/http';
import { throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { errorInterceptor } from './error.interceptor';
import { AuthService } from '../services/auth.service';
import { I18nService } from '../services/i18n.service';

describe('errorInterceptor', () => {
  let authMock: { token: string | null; logout: jest.Mock };
  let snackBarMock: { open: jest.Mock };
  let i18nMock: { t: jest.Mock; locale: jest.Mock };
  let next: jest.MockedFunction<HttpHandlerFn>;

  beforeEach(() => {
    authMock = { token: null, logout: jest.fn() };
    snackBarMock = { open: jest.fn() };
    i18nMock = { t: jest.fn((key: string) => key), locale: jest.fn(() => 'en') };
    next = jest.fn();

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: authMock },
        { provide: MatSnackBar, useValue: snackBarMock },
        { provide: I18nService, useValue: i18nMock },
      ],
    });
  });

  const runInterceptor = (req: HttpRequest<unknown>) =>
    TestBed.runInInjectionContext(() => errorInterceptor(req, next));

  it('calls auth.logout() on 401 for non-auth URLs', (done) => {
    const req = new HttpRequest('GET', '/api/photos');
    const error = new HttpErrorResponse({ status: 401, url: '/api/photos' });
    next.mockReturnValue(throwError(() => error));

    runInterceptor(req).subscribe({
      error: () => {
        expect(authMock.logout).toHaveBeenCalled();
        done();
      },
    });
  });

  it('does NOT call auth.logout() on 401 for /api/auth/ URLs', (done) => {
    const req = new HttpRequest('GET', '/api/auth/status');
    const error = new HttpErrorResponse({ status: 401, url: '/api/auth/status' });
    next.mockReturnValue(throwError(() => error));

    runInterceptor(req).subscribe({
      error: () => {
        expect(authMock.logout).not.toHaveBeenCalled();
        done();
      },
    });
  });

  it('does NOT call auth.logout() on other error codes (404, 500)', (done) => {
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
            done();
          },
        });
      },
    });
  });

  it('re-throws the error', (done) => {
    const req = new HttpRequest('GET', '/api/photos');
    const error = new HttpErrorResponse({ status: 401, url: '/api/photos' });
    next.mockReturnValue(throwError(() => error));

    runInterceptor(req).subscribe({
      next: () => {
        done.fail('expected an error');
      },
      error: (err: HttpErrorResponse) => {
        expect(err.status).toBe(401);
        done();
      },
    });
  });

  it('shows snackbar on 429 rate limit', (done) => {
    const req = new HttpRequest('GET', '/api/photos');
    const error = new HttpErrorResponse({ status: 429, url: '/api/photos' });
    next.mockReturnValue(throwError(() => error));

    runInterceptor(req).subscribe({
      error: () => {
        expect(snackBarMock.open).toHaveBeenCalledWith('errors.rate_limited', '', { duration: 5000 });
        done();
      },
    });
  });

  it('shows snackbar on 403 for non-auth URLs', (done) => {
    const req = new HttpRequest('GET', '/api/photos');
    const error = new HttpErrorResponse({ status: 403, url: '/api/photos' });
    next.mockReturnValue(throwError(() => error));

    runInterceptor(req).subscribe({
      error: () => {
        expect(snackBarMock.open).toHaveBeenCalledWith('errors.access_denied', '', { duration: 3000 });
        done();
      },
    });
  });

  it('shows snackbar on 500 server error', (done) => {
    const req = new HttpRequest('GET', '/api/photos');
    const error = new HttpErrorResponse({ status: 500, url: '/api/photos' });
    next.mockReturnValue(throwError(() => error));

    runInterceptor(req).subscribe({
      error: () => {
        expect(snackBarMock.open).toHaveBeenCalledWith('errors.server_error', '', { duration: 3000 });
        done();
      },
    });
  });
});
