import { Injectable, effect, inject } from '@angular/core';
import { AuthService } from '../../core/services/auth.service';
import { Photo } from '../../shared/models/photo.model';
import { MAX_COMPARE_QUEUE } from './comparison-slots.util';
import { isGalleryCollectionUrl } from '../../shared/utils/url-path';

export interface ComparisonSessionData { photos: Photo[]; returnUrl: string; revision: number }

/** Captured membership stays in this tab, never in URLs or browser storage. */
@Injectable({ providedIn: 'root' })
export class ComparisonSessionService {
  private readonly auth = inject(AuthService);
  /** Keyed on `AuthService.session()`: a same-session revalidation replaces the status object and may null it briefly. */
  private session: { data: ComparisonSessionData; owner: string | null; token: string | null } | null = null;
  private revision = 0;

  constructor() {
    effect(() => {
      const owner = this.auth.session();
      if (this.session && (this.session.owner !== owner || this.session.token !== this.auth.token)) this.clear();
    });
  }

  start(photos: Photo[], returnUrl: string): boolean {
    if (photos.length < 2 || photos.length > MAX_COMPARE_QUEUE || new Set(photos.map(photo => photo.path)).size !== photos.length) return false;
    if (!isGalleryCollectionUrl(returnUrl)) return false;
    this.session = { data: { photos: structuredClone(photos), returnUrl, revision: ++this.revision }, owner: this.auth.session(), token: this.auth.token };
    return true;
  }

  snapshot(): ComparisonSessionData {
    const session = this.session;
    return session && session.owner === this.auth.session() && session.token === this.auth.token
      ? structuredClone(session.data) : { photos: [], returnUrl: '/', revision: 0 };
  }

  clear(revision?: number): void {
    if (revision === undefined || this.session?.data.revision === revision) this.session = null;
  }
}
