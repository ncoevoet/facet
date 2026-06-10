import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { retry, throwError, timer } from 'rxjs';

const MAX_RETRIES = 2;
const BASE_DELAY_MS = 300;

function isRetryable(error: unknown, req: HttpRequest<unknown>): boolean {
  if (!(error instanceof HttpErrorResponse)) return false;
  if (req.url.includes('/scan/stream')) return false;
  // Network failures (status 0) and server errors; 429 is excluded on purpose -
  // the server is rate-limiting, retrying makes it worse
  return error.status === 0 || error.status >= 500;
}

/**
 * Retries idempotent GET requests on transient failures with exponential
 * backoff (300ms, 1200ms). Registered after errorInterceptor so retries are
 * exhausted before any error snackbar appears.
 */
export const retryInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.method !== 'GET') return next(req);
  return next(req).pipe(
    retry({
      count: MAX_RETRIES,
      delay: (error, retryCount) =>
        isRetryable(error, req)
          ? timer(BASE_DELAY_MS * Math.pow(4, retryCount - 1))
          : throwError(() => error),
    }),
  );
};
