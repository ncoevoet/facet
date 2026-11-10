import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Location } from '@angular/common';
import { NavigationEnd, NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { GalleryHistoryPosition, GalleryVisitPositions } from './gallery-visit-positions.service';

describe('tab-local gallery visit positions', () => {
  let service: GalleryVisitPositions;
  let entry: number | undefined;
  let events: Subject<NavigationStart | NavigationEnd>;
  let owner: ReturnType<typeof signal<string>>;
  const url = '/?album_id=7';
  const position = (scroll: number): GalleryHistoryPosition => ({ owner: 'alice', url, scroll, path: '/trip/a.jpg', page: 2, anchor: null });
  const restore = (previous: number, navigation: number, identity = 'alice', target = url) => {
    entry = navigation;
    events.next(new NavigationStart(navigation, target, 'popstate', { navigationId: previous }));
    return service.restore(identity, target, navigation);
  };
  beforeEach(() => {
    entry = 10; events = new Subject(); owner = signal('alice');
    TestBed.configureTestingModule({ providers: [
      { provide: Location, useValue: { getState: () => ({ navigationId: entry }),
        replaceState: () => { throw new DOMException('History writes refused', 'SecurityError'); } } },
      { provide: Router, useValue: { events } },
      { provide: AuthService, useValue: { identity: owner } },
    ] });
    service = TestBed.inject(GalleryVisitPositions);
    TestBed.tick();
  });
  afterEach(() => TestBed.resetTestingModule());

  it('keeps the latest scroll through rapid Back/Forward and Router id replacement without history writes', () => {
    for (let scroll = 0; scroll <= 5000; scroll++) service.remember(position(scroll));
    expect(restore(10, 11)?.scroll).toBe(5000);
    expect(restore(11, 12)?.scroll).toBe(5000);
  });
  it('rebinds a kept gallery on NavigationEnd without requiring a new component or user input', () => {
    service.remember(position(260));
    entry = 11;
    events.next(new NavigationStart(11, url, 'popstate', { navigationId: 10 }));
    events.next(new NavigationEnd(11, url, url));
    expect(restore(11, 12)?.scroll).toBe(260);
  });
  it('binds positions to the exact account, URL and restored navigation', () => {
    service.remember(position(260));
    expect(restore(10, 11, 'bob')).toBeNull();
    expect(restore(10, 12, 'alice', '/')).toBeNull();
    expect(service.restore('alice', url, 99)).toBeNull();
    expect(restore(10, 13)?.scroll).toBe(260);
  });
  it('drops positions when the account changes, including logout and a later return', () => {
    service.remember(position(260));
    owner.set('signed-out'); TestBed.tick();
    owner.set('alice'); TestBed.tick();
    expect(restore(10, 11)).toBeNull();
  });
  it('bounds retained visits and does not fabricate a position for an evicted entry', () => {
    for (let id = 1; id <= 40; id++) { entry = id; service.remember(position(id)); }
    expect(restore(8, 41)).toBeNull();
    expect(restore(9, 43)?.scroll).toBe(9);
    expect(restore(40, 42)?.scroll).toBe(40);
  });
  it('ignores entries without a Router history identity', () => {
    entry = Number.NaN; service.remember(position(260));
    expect(restore(Number.NaN, 11)).toBeNull();
  });
  it('purges the previous account synchronously before recording a new account', () => {
    service.remember(position(260));
    owner.set('bob'); entry = 11; service.remember({ ...position(50), owner: 'bob' });
    owner.set('alice');
    expect(restore(10, 12)).toBeNull();
  });
});
