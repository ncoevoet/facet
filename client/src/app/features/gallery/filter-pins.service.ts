import { computed, inject, Injectable, signal } from '@angular/core';
import { AuthService } from '../../core/services/auth.service';

export const FILTER_PIN_LIMIT = 6;
const STORAGE_PREFIX = 'facet_filter_pins:';

/** Only control IDs are saved: never query values, paths or selected photos.
 * Signed-in identities keep independent preferences on this browser. Anonymous
 * preferences live in memory only; changing identity never adopts another set. */
@Injectable({ providedIn: 'root' })
export class FilterPinsService {
  private readonly auth = inject(AuthService);
  private readonly choice = signal<{ owner: string; ids: readonly string[] } | null>(null);
  private readonly rawIds = computed(() => {
    const owner = this.auth.identity();
    const choice = this.choice();
    if (choice?.owner === owner) return choice.ids;
    if (!owner.startsWith('1|')) return [];
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + encodeURIComponent(owner));
      if (!raw || raw.length > 8192) return [];
      const ids: unknown = JSON.parse(raw);
      return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === 'string') : [];
    } catch { return []; }
  });

  ids(allowed: readonly string[]): readonly string[] {
    const valid = new Set(allowed);
    return [...new Set(this.rawIds().filter(id => valid.has(id)))].slice(0, FILTER_PIN_LIMIT);
  }

  toggle(id: string, allowed: readonly string[]): boolean {
    if (!allowed.includes(id)) return false;
    const owner = this.auth.identity();
    const current = this.ids(allowed);
    if (!current.includes(id) && current.length >= FILTER_PIN_LIMIT) return false;
    const ids = current.includes(id) ? current.filter(value => value !== id) : [...current, id];
    this.choice.set({ owner, ids });
    if (owner.startsWith('1|')) {
      try { localStorage.setItem(STORAGE_PREFIX + encodeURIComponent(owner), JSON.stringify(ids)); }
      catch { /* Storage denied: retain this tab's presentation choice. */ }
    }
    return true;
  }
}
