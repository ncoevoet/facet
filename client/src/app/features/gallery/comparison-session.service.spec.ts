import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { routes } from '../../app.routes';
import { AuthService } from '../../core/services/auth.service';
import { Photo } from '../../shared/models/photo.model';
import { ComparisonSessionService } from './comparison-session.service';

@Component({ template: 'fixture page' })
class PageStub {}
const photos = ['/a.jpg', '/b.jpg'].map(path => ({ path, filename: path } as Photo));

describe('ComparisonSessionService', () => {
  const status = signal({ user_id: 'alice', authenticated: true });
  let token: string | null;
  beforeEach(() => {
    token = 'first'; status.set({ user_id: 'alice', authenticated: true });
    const comparison = routes.find(route => route.path === 'photo-compare')!;
    TestBed.configureTestingModule({ providers: [
      { provide: AuthService, useValue: { status, identity: () => status().user_id, isEdition: () => false, get token() { return token; } } },
      provideRouter([{ path: '', component: PageStub }, { ...comparison, loadComponent: undefined, component: PageStub }]),
    ] });
  });
  afterEach(() => TestBed.resetTestingModule());
  it('captures cloned membership and collection URL, never caller mutations', () => {
    const service = TestBed.inject(ComparisonSessionService);
    const source = structuredClone(photos);
    expect(service.start(source, '/album/42?search=coast')).toBe(true);
    source[0].filename = 'changed'; source.pop();
    const first = service.snapshot();
    expect(first.photos).toEqual(photos); expect(first.returnUrl).toBe('/album/42?search=coast');
    first.photos.pop(); expect(service.snapshot().photos).toHaveLength(2);
    expect(service.start(photos, '//external.example')).toBe(false);
  });
  it('captures the full bounded queue without silently truncating to the visible-pane count', () => {
    const service = TestBed.inject(ComparisonSessionService);
    const queue = Array.from({ length: 100 }, (_, i) => ({ path: `/q${i}.jpg`, filename: `${i}.jpg` } as Photo));
    expect(service.start(queue, '/?tag=review')).toBe(true);
    expect(service.snapshot().photos).toEqual(queue);
    expect(service.start([...queue, { path: '/overflow.jpg' } as Photo], '/')).toBe(false);
    expect(service.snapshot().photos).toEqual(queue);
    expect(service.start([queue[0], queue[0]], '/')).toBe(false);
  });

  it('refuses expired credentials before cleanup runs and clears foreign membership', () => {
    const service = TestBed.inject(ComparisonSessionService);
    expect(service.start(photos, '/')).toBe(true);
    token = 'rotated'; expect(service.snapshot().photos).toEqual([]);
    token = 'first'; status.set({ user_id: 'bob', authenticated: true });
    expect(service.snapshot().photos).toEqual([]);
    TestBed.tick(); status.set({ user_id: 'alice', authenticated: true });
    expect(service.snapshot().photos).toEqual([]);
  });
  it('admits captured read-only comparison and redirects direct or expired entries', async () => {
    const service = TestBed.inject(ComparisonSessionService);
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/photo-compare'); expect(TestBed.inject(Router).url).toBe('/');
    expect(service.start(photos, '/')).toBe(true);
    await harness.navigateByUrl('/photo-compare'); expect(TestBed.inject(Router).url).toBe('/photo-compare');
    await harness.navigateByUrl('/'); service.clear();
    await harness.navigateByUrl('/photo-compare'); expect(TestBed.inject(Router).url).toBe('/');
  });
});
