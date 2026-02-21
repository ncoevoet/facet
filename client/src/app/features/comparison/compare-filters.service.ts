import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class CompareFiltersService {
  readonly selectedCategory = signal<string>('');
  readonly categories = signal<string[]>([]);
}
