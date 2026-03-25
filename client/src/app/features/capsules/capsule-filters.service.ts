import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class CapsuleFiltersService {
  readonly dateFrom = signal('');
  readonly dateTo = signal('');
  /** Incremented to trigger regeneration. */
  readonly regenerate = signal(0);
  /** True while a refresh request is in flight. */
  readonly refreshing = signal(false);
}
