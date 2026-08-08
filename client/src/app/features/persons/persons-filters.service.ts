import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class PersonsFiltersService {
  readonly sort = signal('count');
  readonly sortDirection = signal<'asc' | 'desc'>('desc');
  readonly search = signal('');
  readonly showHidden = signal(false);
  readonly createRequested = signal(0);
  /** Lives here rather than in ManagePersonsComponent so the app shell can swap its
   *  mobile bottom bar for the selection action bar (issue #73). */
  readonly selectedIds = signal<Set<number>>(new Set());
}
