import { ErrorHandler, Injectable, inject } from '@angular/core';
import { HttpBackend, HttpClient } from '@angular/common/http';

/**
 * Self-hosted crash sink. Catches anything Angular hands to ErrorHandler
 * (unhandled effect / template / async errors) and POSTs a minimal report
 * to ``/api/client-errors``. The backend logs and forgets — no third-party
 * service. Errors that fail to send are still logged to the console so we
 * never silently swallow them.
 */
@Injectable({ providedIn: 'root' })
export class GlobalErrorHandler implements ErrorHandler {
  // Use HttpBackend directly to bypass interceptors. An auth/error interceptor
  // failure would otherwise route back through this handler (POST -> interceptor
  // -> handler) creating a tight loop. HttpBackend is the raw transport — no
  // interceptor chain — so a network failure here cannot retrigger us.
  private readonly http = new HttpClient(inject(HttpBackend));
  private inFlight = 0;
  private readonly MAX_INFLIGHT = 5;

  handleError(error: unknown): void {
    console.error(error);
    if (this.inFlight >= this.MAX_INFLIGHT) return;
    this.inFlight++;
    const payload = this.buildPayload(error);
    this.http.post('/api/client-errors', payload, {
      headers: { 'Content-Type': 'application/json' },
    }).subscribe({
      // .subscribe rather than firstValueFrom so we never throw out of
      // handleError. Network errors here are expected (e.g. backend down);
      // console.error already captured the original.
      next: () => { this.inFlight--; },
      error: () => { this.inFlight--; },
    });
  }

  private buildPayload(error: unknown): Record<string, unknown> {
    let message = String(error);
    let stack: string | undefined;
    let name: string | undefined;
    if (error instanceof Error) {
      message = error.message;
      stack = error.stack;
      name = error.name;
    } else if (typeof error === 'object' && error !== null) {
      const e = error as Record<string, unknown>;
      message = String(e['message'] ?? e['statusText'] ?? error);
      stack = typeof e['stack'] === 'string' ? e['stack'] : undefined;
      name = typeof e['name'] === 'string' ? e['name'] : undefined;
    }
    return {
      message: message.slice(0, 2000),
      name: name?.slice(0, 200),
      stack: stack?.slice(0, 8000),
      url: typeof window !== 'undefined' ? window.location.href : null,
      user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : null,
      ts: new Date().toISOString(),
    };
  }
}
