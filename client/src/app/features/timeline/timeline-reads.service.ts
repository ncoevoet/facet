import { Injectable, inject } from '@angular/core';
import { Observable, finalize, share } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { timelineReadContext } from './timeline-read-context';

type ReadParams = Record<string, string | number | boolean>;

/**
 * Shares one in-flight timeline read between the views asking for it at once: the
 * density strip and the year, month or day overview read the same buckets. Nothing is
 * kept once the read settles, so a later read always reaches the server.
 */
@Injectable({ providedIn: 'root' })
export class TimelineReads {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly inFlight = new Map<string, Observable<unknown>>();

  get<T>(path: string, params: ReadParams): Observable<T> {
    // The query ApiService would send, in a stable order, under the session that sends it.
    const query = Object.entries(params)
      .filter(([name, value]) => (value !== '' || name === 'type') && value !== undefined && value !== null)
      .map(([name, value]) => `${name}=${String(value)}`)
      .sort();
    const key = JSON.stringify([this.auth.token, path, query]);
    const pending = this.inFlight.get(key);
    if (pending) return pending as Observable<T>;
    const read: Observable<T> = this.api.get<T>(path, params, timelineReadContext()).pipe(
      finalize(() => { if (this.inFlight.get(key) === read) this.inFlight.delete(key); }),
      share(),
    );
    this.inFlight.set(key, read);
    return read;
  }
}
