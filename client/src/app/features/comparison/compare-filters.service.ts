import { Injectable, signal } from '@angular/core';

/** Index of each tab a UI tool may open, inside the comparison page's tab group. */
export const COMPARE_TAB_INDEX = { snapshots: 0, ab: 1, suggestions: 2, weights: 3 } as const;

export type CompareTabName = keyof typeof COMPARE_TAB_INDEX;

/** Strategy the A/B tab starts with: '' means the server's configured default (the request omits it). */
export const DEFAULT_COMPARE_STRATEGY = '';

@Injectable({ providedIn: 'root' })
export class CompareFiltersService {
  readonly selectedCategory = signal<string>('');
  /** Pair-selection strategy of the A/B tab; kept here so a UI tool can set it without touching the page. */
  readonly strategy = signal<string>(DEFAULT_COMPARE_STRATEGY);
  /** Tab shown by the comparison page; the page writes it on every tab change, a UI tool may set it.
   *  It opens on Weights, the page's main task, which needs no comparisons first. */
  readonly activeTab = signal<number>(COMPARE_TAB_INDEX.weights);
}
