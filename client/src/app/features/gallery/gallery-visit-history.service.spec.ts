import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService } from '../../core/services/auth.service';
import { GalleryVisitHistoryService } from './gallery-visit-history.service';
import { buildSyncParams, DEFAULT_FILTERS } from './gallery-filters.util';

describe('GalleryVisitHistoryService', () => {
  const identity = signal('1|alice');
  const status = signal<object | null>({ authenticated: true });
  let token = 'session-a';
  let service: GalleryVisitHistoryService;

  beforeEach(() => {
    identity.set('1|alice'); status.set({ authenticated: true }); token = 'session-a';
    TestBed.configureTestingModule({ providers: [{ provide: AuthService, useValue: { identity, status, get token() { return token; } } }] });
    service = TestBed.inject(GalleryVisitHistoryService);
  });

  it('retains exact query/sort and literal values while omitting page and display state', () => {
    service.remember('/album/12?search=birds%20%26%20rain&min_score=0&sort=date_taken&page=4&hide_details=false');
    const visit = service.visits()[0];
    expect(visit.albumId).toBe('12');
    expect(visit.criteria).toEqual([['min_score', '0'], ['search', 'birds & rain']]);
    expect(service.restoreUrl(visit)).toBe('/album/12?min_score=0&search=birds+%26+rain&sort=date_taken');
  });

  it('bounds and deduplicates visits without recording external, non-gallery or unknown query state', () => {
    for (let i = 0; i < 15; i++) service.remember('/?tag=tag' + i);
    service.remember('/?tag=tag13');
    expect(service.visits()).toHaveLength(10);
    expect(service.visits()[0].criteria).toEqual([['tag', 'tag13']]);
    const before = service.visits();
    for (const url of ['https://example.org/?tag=x', '//example.org/?tag=x', '/photo?path=x', '/?token=secret', '/?sort=aggregate', '/?tag=x#section']) service.remember(url);
    expect(service.visits()).toBe(before);
  });

  it('ignores default query fields and counts only active criteria', () => {
    const defaults = new URLSearchParams(buildSyncParams({ ...DEFAULT_FILTERS }, undefined));
    service.remember('/?' + defaults);
    expect(service.visits()).toHaveLength(0);
    const filtered = new URLSearchParams(buildSyncParams({ ...DEFAULT_FILTERS, search: 'birds', min_iso: '100', max_iso: '400' }, undefined));
    service.remember('/?' + filtered);
    expect(service.visits()[0].criteria).toEqual([['max_iso', '400'], ['min_iso', '100'], ['search', 'birds']]);
  });

  it('retains a bare album, excludes invalid and oversized entries, and clears old callbacks', () => {
    service.remember('/album/7');
    const visit = service.visits()[0];
    expect(visit.albumId).toBe('7');
    expect(service.restoreUrl(visit)).toBe('/album/7');
    for (const url of ['/?album_id=nope', '/album/nope', '/?search=' + 'x'.repeat(4096)]) service.remember(url);
    expect(service.visits()).toEqual([visit]);
    service.remember('/?album_id=0&search=birds');
    expect(service.visits()[0].albumId).toBeNull();
    service.clear();
    expect(service.visits()).toEqual([]);
    expect(service.restoreUrl(visit)).toBeNull();
  });

  it('refuses stale callbacks synchronously on account or token changes and clears on logout', () => {
    service.remember('/?tag=private');
    const first = service.visits()[0];
    identity.set('1|bob');
    expect(service.restoreUrl(first)).toBeNull();
    expect(service.visits()).toEqual([]);
    service.remember('/?tag=bob');
    const second = service.visits()[0];
    token = 'rotated';
    expect(service.restoreUrl(second)).toBeNull();
    service.remember('/?search=current');
    status.set(null); TestBed.tick();
    expect(service.visits()).toEqual([]);
    service.remember('/?search=logged-out');
    expect(service.visits()).toEqual([]);
  });
});
