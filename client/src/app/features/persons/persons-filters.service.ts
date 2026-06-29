import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class PersonsFiltersService {
  readonly sort = signal('count');
  readonly sortDirection = signal<'asc' | 'desc'>('desc');
  readonly search = signal('');
  readonly showHidden = signal(false);
  readonly createRequested = signal(0);
}
