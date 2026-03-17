import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class TimelineFiltersService {
  readonly dateFrom = signal('');
  readonly dateTo = signal('');
  readonly sortDirection = signal<'older' | 'newer'>('older');
  readonly selectedYear = signal('');
  readonly selectedMonth = signal('');
}
