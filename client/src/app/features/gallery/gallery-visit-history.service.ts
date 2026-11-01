import { effect, inject, Injectable, signal } from '@angular/core';
import { AuthService } from '../../core/services/auth.service';
import { DEFAULT_FILTERS } from './gallery-filters.util';

export interface GalleryVisit {
  readonly url: string;
  readonly albumId: string | null;
  readonly criteria: readonly (readonly [string, string])[];
}

const LIMIT = 10;
const PRESENTATION_KEYS = new Set(['page', 'per_page', 'hide_details', 'tooltip_mode', 'panel_activation']);
const SORT_KEYS = new Set(['sort', 'sort_direction']);
const QUERY_KEYS = new Set(Object.keys(DEFAULT_FILTERS));

/** Session-only query inputs, never cached photo rows, selection or file-write state. */
@Injectable({ providedIn: 'root' })
export class GalleryVisitHistoryService {
  private readonly auth = inject(AuthService);
  private owner = this.context();
  private readonly stored = signal<readonly GalleryVisit[]>([]);
  readonly visits = this.stored.asReadonly();

  constructor() {
    effect(() => {
      const context = this.context();
      if (context !== this.owner) {
        this.owner = context;
        this.stored.set([]);
      }
    });
  }

  private context(): string | null {
    return this.auth.status() ? JSON.stringify([this.auth.identity(), this.auth.token]) : null;
  }

  private syncOwner(): boolean {
    const context = this.context();
    if (context !== this.owner) {
      this.owner = context;
      this.stored.set([]);
    }
    return context !== null;
  }

  remember(raw: string): void {
    if (!this.syncOwner() || !raw.startsWith('/') || raw.startsWith('//') || raw.length > 4096) return;
    const parsed = new URL(raw, 'https://facet.invalid');
    if (parsed.origin !== 'https://facet.invalid') return;
    const album = parsed.pathname.match(/^\/album\/(\d+)$/);
    if ((parsed.pathname !== '/' && !album) || parsed.hash) return;
    for (const key of parsed.searchParams.keys()) if (!QUERY_KEYS.has(key)) return;
    for (const key of PRESENTATION_KEYS) parsed.searchParams.delete(key);
    parsed.searchParams.sort();
    const criteria = [...parsed.searchParams.entries()].filter(([key]) => !SORT_KEYS.has(key));
    if (!album && !criteria.length) return;
    const query = parsed.searchParams.toString();
    const url = parsed.pathname + (query ? '?' + query : '');
    const queryAlbum = parsed.searchParams.get('album_id');
    const albumId = queryAlbum === '0' ? null : queryAlbum || album?.[1] || null;
    const visit: GalleryVisit = { url, albumId, criteria };
    this.stored.update(items => [visit, ...items.filter(item => item.url !== url)].slice(0, LIMIT));
  }

  /** Old menu callbacks cannot restore a previous account's query. */
  restoreUrl(visit: GalleryVisit): string | null {
    return this.syncOwner() && this.stored().includes(visit) ? visit.url : null;
  }

  clear(): void {
    this.syncOwner();
    this.stored.set([]);
  }
}
