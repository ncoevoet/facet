import type { MockedFunction } from 'vitest';
import {
  HttpRequest,
  HttpHandlerFn,
  HttpErrorResponse,
  HttpResponse,
  HttpEvent,
} from '@angular/common/http';
import { defer, of, throwError, Observable } from 'rxjs';
import { retryInterceptor } from './retry.interceptor';

describe('retryInterceptor', () => {
  let next: MockedFunction<HttpHandlerFn>;

  beforeEach(() => {
    next = vi.fn();
  });

  // retry() re-subscribes to the next(req) observable rather than re-invoking
  // next, so attempts are counted by subscriptions to a deferred source.
  const failingSource = (status: number, url = '/api/photos') => {
    const counter = { attempts: 0 };
    const obs: Observable<HttpEvent<unknown>> = defer(() => {
      counter.attempts++;
      return throwError(() => new HttpErrorResponse({ status, url }));
    });
    return { obs, counter };
  };

  const errored = (req: HttpRequest<unknown>) =>
    new Promise<void>((resolve, reject) =>
      retryInterceptor(req, next).subscribe({
        next: () => reject(new Error('expected error')),
        error: () => resolve(),
      }),
    );

  it('passes non-GET requests through without retrying', async () => {
    const { obs, counter } = failingSource(500);
    next.mockReturnValue(obs);
    await errored(new HttpRequest('POST', '/api/photos', {}));
    expect(counter.attempts).toBe(1); // no retry on POST
  });

  it('does not retry a successful GET', () => {
    next.mockReturnValue(of(new HttpResponse({ status: 200 }) as HttpEvent<unknown>));
    let value: HttpEvent<unknown> | undefined;
    retryInterceptor(new HttpRequest('GET', '/api/photos'), next).subscribe((v) => (value = v));
    expect(next).toHaveBeenCalledTimes(1);
    expect(value).toBeInstanceOf(HttpResponse);
  });

  // Real timers: backoff (300ms + 1200ms) is fixed and small; rxjs timer under
  // zone.js does not advance reliably with vitest fake timers.
  it('retries a GET on 500 up to MAX_RETRIES (3 attempts) then errors', async () => {
    const { obs, counter } = failingSource(500);
    next.mockReturnValue(obs);
    await errored(new HttpRequest('GET', '/api/photos'));
    expect(counter.attempts).toBe(3); // initial + 2 retries
  }, 10000);

  it('retries a GET on network failure (status 0)', async () => {
    const { obs, counter } = failingSource(0);
    next.mockReturnValue(obs);
    await errored(new HttpRequest('GET', '/api/photos'));
    expect(counter.attempts).toBe(3);
  }, 10000);

  it('applies exponential backoff before exhausting retries (~300ms + 1200ms)', async () => {
    const { obs, counter } = failingSource(503);
    next.mockReturnValue(obs);
    const start = Date.now();
    await errored(new HttpRequest('GET', '/api/photos'));
    expect(counter.attempts).toBe(3);
    expect(Date.now() - start).toBeGreaterThanOrEqual(1400); // 300 + 1200 backoff
  }, 10000);

  it('does NOT retry a GET on 429 (rate limited)', async () => {
    const { obs, counter } = failingSource(429);
    next.mockReturnValue(obs);
    await errored(new HttpRequest('GET', '/api/photos'));
    expect(counter.attempts).toBe(1);
  });

  it('does NOT retry a GET on 4xx (e.g. 404)', async () => {
    const { obs, counter } = failingSource(404);
    next.mockReturnValue(obs);
    await errored(new HttpRequest('GET', '/api/photos'));
    expect(counter.attempts).toBe(1);
  });

  it('does NOT retry the /scan/stream endpoint even on 500', async () => {
    const { obs, counter } = failingSource(500, '/api/scan/stream');
    next.mockReturnValue(obs);
    await errored(new HttpRequest('GET', '/api/scan/stream'));
    expect(counter.attempts).toBe(1);
  });
});
