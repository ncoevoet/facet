import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService, type AuthStatus } from '../../core/services/auth.service';
import type { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineFeedCache, type TimelineGroup } from './timeline-feed-cache.service';

const groups: TimelineGroup[] = [{ date: '2026-11-01', count: 2, photos: [{ path: '/a.jpg' }, { path: '/b.jpg' }] as Photo[] }];
const alice = () => ({ user_id: 'alice', authenticated: true }) as AuthStatus;

describe('TimelineFeedCache', () => {
  function setup() {
    const auth = { status: signal<AuthStatus | null>(alice()), session: signal<string | null>('alice|a'), token: 'a' as string | null };
    TestBed.configureTestingModule({ providers: [
      { provide: AuthService, useValue: auth },
      { provide: GalleryStore, useValue: { photos: signal<Photo[]>([]), loading: signal(false), timelineMembershipRevision: signal(0) } },
    ] });
    const cache = TestBed.inject(TimelineFeedCache); TestBed.tick();
    const snapshot = { scope: 'scope', owner: auth.status()!, session: auth.session()!, token: auth.token, scrollTop: 120, rows: cache.rows(),
      membershipRevision: cache.membershipRevision(), groups, next_cursor: null, has_more: false };
    cache.save(snapshot);
    cache.capturePhotos(groups);
    return { auth, cache };
  }
  afterEach(() => TestBed.resetTestingModule());

  it('keeps the return snapshot and photo session through a same-session revalidation and its transient null', () => {
    const { auth, cache } = setup();
    auth.status.set(alice()); TestBed.tick();
    expect(cache.read('scope')?.scrollTop).toBe(120); expect(cache.adjacent('/a.jpg', 1)).toBe('/b.jpg');
    auth.status.set(null); TestBed.tick();
    expect(cache.read('scope')?.scrollTop).toBe(120); expect(cache.adjacent('/a.jpg', 1)).toBe('/b.jpg');
    auth.status.set(alice()); TestBed.tick();
    expect(cache.read('scope')?.scrollTop).toBe(120); expect(cache.adjacent('/b.jpg', -1)).toBe('/a.jpg');
  });

  it('drops both on sign-out, even when the same session is confirmed again', () => {
    const { auth, cache } = setup();
    auth.status.set(null); auth.session.set(null); TestBed.tick();
    expect(cache.read('scope')).toBeNull(); expect(cache.adjacent('/a.jpg', 1)).toBeNull();
    auth.status.set(alice()); auth.session.set('alice|a'); TestBed.tick();
    expect(cache.read('scope')).toBeNull(); expect(cache.adjacent('/a.jpg', 1)).toBeNull();
  });

  it('drops both when the session names another account or the token changes', () => {
    const { auth, cache } = setup();
    auth.token = 'rotated';
    expect(cache.read('scope')).toBeNull(); expect(cache.adjacent('/a.jpg', 1)).toBeNull();
    auth.token = 'a'; auth.status.set({ user_id: 'bob', authenticated: true } as AuthStatus); auth.session.set('bob|a'); TestBed.tick();
    expect(cache.read('scope')).toBeNull(); expect(cache.adjacent('/a.jpg', 1)).toBeNull();
    auth.status.set(alice()); auth.session.set('alice|a'); TestBed.tick();
    expect(cache.read('scope')).toBeNull(); expect(cache.adjacent('/a.jpg', 1)).toBeNull();
  });
});
