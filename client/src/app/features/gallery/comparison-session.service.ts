import { Injectable, effect, inject } from '@angular/core';
import { AuthService } from '../../core/services/auth.service';
import { Photo } from '../../shared/models/photo.model';

export interface ComparisonSessionData { photos: Photo[]; returnUrl: string }

/** Captured membership stays in this tab, never in URLs or browser storage. */
@Injectable({ providedIn: 'root' })
export class ComparisonSessionService {
  private readonly auth = inject(AuthService);
  private session: { data: ComparisonSessionData; owner: string; status: unknown; token: string | null } | null = null;

  constructor() {
    effect(() => {
      const status = this.auth.status();
      const owner = this.auth.identity();
      if (this.session && (this.session.owner !== owner || this.session.status !== status || this.session.token !== this.auth.token)) this.clear();
    });
  }

  start(photos: Photo[], returnUrl: string): boolean {
    if (photos.length < 2 || photos.length > 4 || new Set(photos.map(photo => photo.path)).size !== photos.length) return false;
    if (!/^\/(?:album\/\d+)?(?:\?|$)/.test(returnUrl)) return false;
    this.session = { data: { photos: structuredClone(photos), returnUrl }, owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
    return true;
  }

  snapshot(): ComparisonSessionData {
    const session = this.session;
    return session && session.owner === this.auth.identity() && session.status === this.auth.status() && session.token === this.auth.token
      ? structuredClone(session.data) : { photos: [], returnUrl: '/' };
  }

  clear(): void { this.session = null; }
}
