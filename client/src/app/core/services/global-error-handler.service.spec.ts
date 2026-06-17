import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { HttpBackend, HttpEvent, HttpResponse } from '@angular/common/http';
import { NEVER, Observable, of, throwError } from 'rxjs';
import { GlobalErrorHandler } from './global-error-handler.service';

// The service builds its own HttpClient from `inject(HttpBackend)` to bypass
// interceptors, so HttpClient.post(...) ultimately delegates to
// HttpBackend.handle(req). Mocking `handle` therefore controls the transport
// exactly like error.interceptor.spec.ts. The 200 OK response below lets the
// post observable complete so `inFlight` decrements between independent tests.
const okResponse = (): Observable<HttpEvent<unknown>> =>
  of(new HttpResponse({ status: 200 }) as HttpEvent<unknown>);

describe('GlobalErrorHandler', () => {
  let backendMock: { handle: Mock };
  let consoleSpy: ReturnType<typeof vi.spyOn>;

  // MAX_INFLIGHT in the implementation. Kept here as a named constant so the
  // cap test reads clearly; mirrors the private readonly in the service.
  const MAX_INFLIGHT = 5;

  const createHandler = (): GlobalErrorHandler => {
    TestBed.configureTestingModule({
      providers: [{ provide: HttpBackend, useValue: backendMock }],
    });
    return TestBed.inject(GlobalErrorHandler);
  };

  beforeEach(() => {
    backendMock = { handle: vi.fn(() => okResponse()) };
    // Silence + observe console.error (the service always logs).
    consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
    TestBed.resetTestingModule();
  });

  it('always calls console.error for a handled error', () => {
    const handler = createHandler();
    const err = new Error('boom');
    handler.handleError(err);
    expect(consoleSpy).toHaveBeenCalledWith(err);
  });

  it('POSTs the report to /api/client-errors', () => {
    const handler = createHandler();
    handler.handleError(new Error('boom'));

    expect(backendMock.handle).toHaveBeenCalledTimes(1);
    const req = backendMock.handle.mock.calls[0][0];
    expect(req.method).toBe('POST');
    expect(req.url).toBe('/api/client-errors');
  });

  it('truncates the payload message to 2000 chars', () => {
    const handler = createHandler();
    const longMessage = 'x'.repeat(5000);
    handler.handleError(new Error(longMessage));

    const req = backendMock.handle.mock.calls[0][0];
    expect(req.body.message).toHaveLength(2000);
    expect(req.body.message).toBe('x'.repeat(2000));
  });

  it('truncates the stack to 8000 chars', () => {
    const handler = createHandler();
    const err = new Error('boom');
    err.stack = 's'.repeat(10000);
    handler.handleError(err);

    const req = backendMock.handle.mock.calls[0][0];
    expect(req.body.stack).toHaveLength(8000);
  });

  it('drops reports once MAX_INFLIGHT concurrent reports are in flight', () => {
    // Never-completing transport keeps every report in flight so the inFlight
    // counter climbs to the cap and stays there.
    backendMock.handle.mockReturnValue(NEVER);
    const handler = createHandler();

    for (let i = 0; i < MAX_INFLIGHT + 1; i++) {
      handler.handleError(new Error(`error ${i}`));
    }

    // The (MAX_INFLIGHT + 1)th report is dropped before reaching the transport,
    // while console.error still fired for every error.
    expect(backendMock.handle).toHaveBeenCalledTimes(MAX_INFLIGHT);
    expect(consoleSpy).toHaveBeenCalledTimes(MAX_INFLIGHT + 1);
  });

  it('frees an in-flight slot after a report completes', () => {
    const handler = createHandler();
    // First 5 complete synchronously (okResponse), so all slots free up; a
    // sixth report still reaches the transport.
    for (let i = 0; i < MAX_INFLIGHT + 1; i++) {
      handler.handleError(new Error(`error ${i}`));
    }
    expect(backendMock.handle).toHaveBeenCalledTimes(MAX_INFLIGHT + 1);
  });

  it('never throws when the transport errors, and still logs to console', () => {
    backendMock.handle.mockReturnValue(throwError(() => new Error('network down')));
    const handler = createHandler();
    const err = new Error('boom');

    expect(() => handler.handleError(err)).not.toThrow();
    expect(consoleSpy).toHaveBeenCalledWith(err);
    expect(backendMock.handle).toHaveBeenCalledTimes(1);
  });

  it('frees the slot again after a transport error so later reports send', () => {
    backendMock.handle.mockReturnValue(throwError(() => new Error('network down')));
    const handler = createHandler();
    // Each errors synchronously and decrements inFlight, so the cap is never
    // reached and every report reaches the transport.
    for (let i = 0; i < MAX_INFLIGHT + 3; i++) {
      handler.handleError(new Error(`error ${i}`));
    }
    expect(backendMock.handle).toHaveBeenCalledTimes(MAX_INFLIGHT + 3);
  });
});
