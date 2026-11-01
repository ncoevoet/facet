import { Injectable, effect, inject } from '@angular/core';
import { AuthService, type AuthStatus } from '../../core/services/auth.service';
import type { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from '../gallery/gallery.store';

export interface TimelineGroup {
  date: string;
  count: number;
  photos: Photo[];
}

export interface TimelinePage {
  groups: TimelineGroup[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface TimelineSnapshot extends TimelinePage {
  scope: string;
  owner: AuthStatus;
  token: string | null;
  scrollTop: number;
  rows: Photo[];
}

/** One bounded, memory-only return position. Never shared across credentials. */
@Injectable({ providedIn: 'root' })
export class TimelineFeedCache {
  private readonly auth = inject(AuthService);
  private readonly store = inject(GalleryStore);
  private snapshot: TimelineSnapshot | null = null;
  private photoSession: { owner: AuthStatus; token: string | null; paths: string[] } | null = null;

  constructor() {
    effect(() => {
      const owner = this.auth.status();
      const rows = this.store.photos();
      if (this.snapshot?.owner !== owner || this.snapshot?.token !== this.auth.token || rows !== this.snapshot.rows) this.snapshot = null;
      if (this.photoSession?.owner !== owner || this.photoSession?.token !== this.auth.token) this.photoSession = null;
    });
  }

  read(scope: string): TimelineSnapshot | null {
    const value = this.snapshot;
    return value?.scope === scope && value.owner === this.auth.status() && value.token === this.auth.token && value.rows === this.store.photos()
      ? value : null;
  }

  save(value: TimelineSnapshot): void {
    if (value.owner === this.auth.status() && value.token === this.auth.token && value.rows === this.store.photos()) this.snapshot = value;
  }

  capturePhotos(photos: TimelineGroup[]): void {
    const owner = this.auth.status();
    if (owner) this.photoSession = { owner, token: this.auth.token, paths: photos.flatMap(group => group.photos.map(photo => photo.path)) };
  }

  adjacent(path: string, delta: number): string | null {
    const session = this.photoSession;
    if (!session || session.owner !== this.auth.status() || session.token !== this.auth.token) return null;
    const index = session.paths.indexOf(path);
    return index < 0 ? null : session.paths[index + delta] ?? null;
  }
}
