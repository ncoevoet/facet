import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class StatsFiltersService {
  readonly filterCategory = signal('');
  readonly dateFrom = signal('');
  readonly dateTo = signal('');
}
