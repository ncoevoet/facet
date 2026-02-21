import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class CompareFiltersService {
  readonly selectedCategory = signal<string>('');
}
