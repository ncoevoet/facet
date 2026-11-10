import { HttpBackend, HttpClient, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { I18nService } from '../services/i18n.service';
import { I18N } from '../i18n/keys';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../utils/http-error-context';
import { extractErrorDetail, isLibraryBusyError } from '../utils/http-error.util';

import { HANDLE_PLACE_SEARCH_ERRORS_LOCALLY, isExpectedPlaceSearchError } from '../utils/place-search-error.util';

const CLIENT_ERRORS_URL = '/api/client-errors';

// A read refused as library_busy changed nothing the user did, so it gets no
// "try again" toast; only a save the user made is told why it did not land.
const READ_METHODS = new Set(['GET', 'HEAD']);

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
      if (req.method === 'GET' && req.url.split('?')[0] === '/api/places/search'
          && req.context.get(HANDLE_PLACE_SEARCH_ERRORS_LOCALLY) && isExpectedPlaceSearchError(error)) {
        // The caller still receives the refusal. Authentication and unexpected
        // faults retain the global paths below; no query is sent to the crash sink.
        return throwError(() => error);
      }
      if (error.status === 401 && !isAuthUrl(req.url)) {
        auth.logout();
      } else if (error.status === 429 && !isAuthUrl(req.url)) {
        // Excluded on the auth routes for the same reason 401 and 403 are: the
        // login form and the edition dialog render the outcome inline, right
        // where the operator is looking and next to the field they would
        // retype. A global toast saying the same thing is the second copy, and
        // it outlives the dialog that explains it.
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
        const detail = extractErrorDetail(error);
        void auth.revalidate().then(() => {
          const lostEdition = hadEdition && !auth.isEdition();
          const base = i18n.t(lostEdition ? I18N.errors.edition_expired : I18N.errors.access_denied);
          // The detail is the server's own (untranslated) prose, so it is
          // labelled as a server message rather than spliced straight after
          // a translated sentence -- otherwise a non-English user sees their
          // language switch to English mid-toast with nothing explaining why.
          snackBar.open(
            detail ? `${base} — ${i18n.t(I18N.errors.server_detail)} ${detail}` : base,
            '',
            { duration: detail ? 8000 : (lostEdition ? 6000 : 3000) },
          );
        });
      } else if (isLibraryBusyError(error)) {
        // Not a fault: another writer -- most often the one-time gallery index
        // build after an upgrade -- holds the library, so nothing is reported as
        // a crash. Opened on the next task, after the caller's own error handling
        // (an optimistic revert and its generic "action failed" toast) has run, so
        // that toast cannot replace the one that says why and what to do.
        if (!READ_METHODS.has(req.method)) {
          // Assumes the caller's error handling runs within the current task (its
          // own microtasks included), which a macrotask is guaranteed to follow.
          setTimeout(() => snackBar.open(i18n.t(I18N.errors.library_busy), '', { duration: 6000 }));
        }
      } else if (error.status >= 500) {
        if (!req.context.get(HANDLE_SERVER_ERROR_LOCALLY)) {
          snackBar.open(i18n.t(I18N.errors.server_error), '', { duration: 3000 });
        }
        if (!isCrashReportUrl(req.url)) {
          let msg = `${req.method} ${req.url} -> ${error.status}`;
          const detail = extractErrorDetail(error);
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
