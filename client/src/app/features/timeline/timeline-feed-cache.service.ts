import { Injectable, computed, effect, inject } from '@angular/core';
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
  /** The key, not `owner`: a same-session revalidation replaces the status object and may null it briefly. */
  session: string;
  token: string | null;
  scrollTop: number;
  rows: Photo[];
  membershipRevision: number;
}

/** Review marks don't change a timeline day or its thumbnail. */
function sameMembership(left: Photo[], right: Photo[]): boolean {
  if (left.length !== right.length) return false;
  const previous = new Map(left.map(photo => [photo.path, photo]));
  return right.every(photo => {
    const old = previous.get(photo.path);
    return !!old && old.filename === photo.filename && old.date_taken === photo.date_taken
      && old.preview_revision === photo.preview_revision && old.is_blink === photo.is_blink
      && old.burst_group_id === photo.burst_group_id && old.is_burst_lead === photo.is_burst_lead
      && old.duplicate_group_id === photo.duplicate_group_id && old.is_duplicate_lead === photo.is_duplicate_lead
      && old.sequence_kind === photo.sequence_kind && old.sequence_group_id === photo.sequence_group_id
      && old.sequence_override === photo.sequence_override
      && old.logical_review?.asset_id === photo.logical_review?.asset_id
      && old.logical_review?.group_revision === photo.logical_review?.group_revision;
  });
}

/** One bounded, memory-only return position. Never shared across credentials. */
@Injectable({ providedIn: 'root' })
export class TimelineFeedCache {
  private readonly auth = inject(AuthService);
  private readonly store = inject(GalleryStore);
  private settledRows: Photo[] = [];
  // A Gallery reload temporarily clears its rows; publish only the settled list.
  readonly rows = computed(() => {
    if (!this.store.loading()) this.settledRows = this.store.photos();
    return this.settledRows;
  }, { equal: sameMembership });
  readonly membershipRevision = this.store.timelineMembershipRevision.asReadonly();
  private snapshot: TimelineSnapshot | null = null;
  private photoSession: { session: string; token: string | null; paths: string[] } | null = null;

  constructor() {
    effect(() => {
      const session = this.auth.session();
      const rows = this.rows(); const revision = this.membershipRevision();
      if (this.snapshot?.session !== session || this.snapshot?.token !== this.auth.token || rows !== this.snapshot.rows
        || revision !== this.snapshot.membershipRevision) this.snapshot = null;
      if (this.photoSession?.session !== session || this.photoSession?.token !== this.auth.token) this.photoSession = null;
    });
  }

  read(scope: string): TimelineSnapshot | null {
    const value = this.snapshot;
    return value?.scope === scope && value.session === this.auth.session() && value.token === this.auth.token && value.rows === this.rows()
      && value.membershipRevision === this.membershipRevision()
      ? value : null;
  }

  save(value: TimelineSnapshot): void {
    if (value.session === this.auth.session() && value.token === this.auth.token && value.rows === this.rows()
      && value.membershipRevision === this.membershipRevision()) this.snapshot = value;
  }

  capturePhotos(photos: TimelineGroup[]): void {
    const session = this.auth.session();
    if (session) this.photoSession = { session, token: this.auth.token, paths: photos.flatMap(group => group.photos.map(photo => photo.path)) };
  }

  adjacent(path: string, delta: number): string | null {
    const session = this.photoSession;
    if (!session || session.session !== this.auth.session() || session.token !== this.auth.token) return null;
    const index = session.paths.indexOf(path);
    return index < 0 ? null : session.paths[index + delta] ?? null;
  }
}
