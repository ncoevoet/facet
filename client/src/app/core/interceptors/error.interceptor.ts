import { HttpBackend, HttpClient, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { I18nService } from '../services/i18n.service';
import { I18N } from '../i18n/keys';

const CLIENT_ERRORS_URL = '/api/client-errors';

const isAuthUrl = (url: string) => url.startsWith('/api/auth/') || url.includes('/api/auth/');

// Match the exact crash-report endpoint, not any URL that happens to contain
// the substring. A future endpoint like `/api/client-errors/clear` would
// otherwise be excluded from crash reporting.
const isCrashReportUrl = (url: string) => {
  const path = url.split('?')[0];
  return path === CLIENT_ERRORS_URL || path.endsWith(CLIENT_ERRORS_URL);
};

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const snackBar = inject(MatSnackBar);
  const i18n = inject(I18nService);
  // Raw HttpClient (interceptor-free) for posting crash reports. Going through
  // the normal HttpClient would route /api/client-errors back through THIS
  // interceptor and create a recursion if the report POST itself 5xx'd.
  const backend = inject(HttpBackend);
  const crashReporter = new HttpClient(backend);

  return next(req).pipe(
    catchError(error => {
      if (error.status === 401 && !isAuthUrl(req.url)) {
        auth.logout();
      } else if (error.status === 429) {
        snackBar.open(i18n.t(I18N.errors.rate_limited), '', { duration: 5000 });
      } else if (error.status === 403 && !isAuthUrl(req.url)) {
        // The server refused rights the cached status still advertises. Either
        // the edition password was rotated — which strips the edition claim
        // from every token minted under the old one — or this session simply
        // never had the right the UI offered. A logout elsewhere is NOT a
        // cause: it drops that client's own token and revokes nothing here.
        // Reconcile before reporting, so the toast can say which of the two it
        // was and the Edition indicator stops lying either way.
        const hadEdition = auth.isEdition();
        void auth.revalidate().then(() => {
          const lostEdition = hadEdition && !auth.isEdition();
          snackBar.open(
            i18n.t(lostEdition ? I18N.errors.edition_expired : I18N.errors.access_denied),
            '',
            { duration: lostEdition ? 6000 : 3000 },
          );
        });
      } else if (error.status >= 500) {
        snackBar.open(i18n.t(I18N.errors.server_error), '', { duration: 3000 });
        if (!isCrashReportUrl(req.url)) {
          let msg = `${req.method} ${req.url} -> ${error.status}`;
          const body = error.error as Record<string, unknown> | null;
          const detail = body && typeof body === 'object'
            ? (typeof body['detail'] === 'string' ? body['detail'] :
               typeof body['message'] === 'string' ? body['message'] : undefined)
            : undefined;
          if (detail) msg += `: ${detail}`;
          crashReporter.post(CLIENT_ERRORS_URL, {
            message: msg.slice(0, 2000),
            url: typeof window !== 'undefined' ? window.location.href : null,
            user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : null,
            component: 'http',
            extra: { request_url: req.url, request_method: req.method, status: error.status },
          }).subscribe({ next: () => {}, error: () => {} });
        }
      }
      return throwError(() => error);
    }),
  );
};
