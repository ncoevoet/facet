import { Injectable, signal } from '@angular/core';

/** Set to '1' while the Calendar view is chosen; absent means the photo feed, the default. */
export const TIMELINE_CALENDAR_VIEW_KEY = 'facet_timeline_calendar_view';

function readCalendarView(): boolean {
  try { return localStorage.getItem(TIMELINE_CALENDAR_VIEW_KEY) === '1'; } catch { return false; }
}

@Injectable({ providedIn: 'root' })
export class TimelineFiltersService {
  readonly dateFrom = signal('');
  readonly dateTo = signal('');
  readonly sortDirection = signal<'older' | 'newer'>('older');
  readonly showOverview = signal(readCalendarView());
}
