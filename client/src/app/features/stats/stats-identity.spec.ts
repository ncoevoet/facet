import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, ActivatedRoute } from '@angular/router';
import { NEVER } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';
import { GalleryStore } from '../gallery/gallery.store';
import { StatsComponent } from './stats.component';

describe('statistics owner and lifecycle boundaries', () => {
  const auth = { identity: signal('owner-a'), isAuthenticated: signal(true), status: signal<object>({}), token: 'token-a' as string | null };
  let http: HttpTestingController;

  beforeEach(() => {
    auth.identity.set('owner-a'); auth.isAuthenticated.set(true); auth.status.set({}); auth.token = 'token-a';
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(), provideHttpClientTesting(), StatsComponent,
      { provide: AuthService, useValue: auth },
      { provide: GalleryStore, useValue: { types: signal([]) } },
      { provide: I18nService, useValue: { t: (key: string) => key } },
      { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
    ] });
    http = TestBed.inject(HttpTestingController);
  });

  it('drops the previous owner response and reloads the new owner', async () => {
    const page = TestBed.inject(StatsComponent);
    TestBed.tick();
    const old = http.expectOne(req => req.url === '/api/stats/overview');
    expect(old.request.context.get(HANDLE_SERVER_ERROR_LOCALLY)).toBe(true);
    auth.token = 'token-b'; auth.identity.set('owner-b');
    TestBed.tick();
    const current = http.expectOne(req => req.url === '/api/stats/overview');
    old.flush({ total_photos: 999 });
    await Promise.resolve();
    expect(page.statsFilters.overview()).toBeNull();
    http.expectNone(req => req.url === '/api/stats/gear');
    current.flush({ total_photos: 3 });
    await vi.waitFor(() => expect(page.statsFilters.overview()?.total_photos).toBe(3));
    http.expectOne(req => req.url === '/api/stats/gear').flush({ cameras: [], lenses: [], combos: [] });
    http.expectOne(req => req.url === '/api/stats/categories').flush([]);
    http.expectOne(req => req.url === '/api/stats/score_distribution').flush([]);
    http.expectOne(req => req.url === '/api/stats/top_cameras').flush([]);
    http.verify();
  });

  it('does not launch dependent reads after the owning component is destroyed', async () => {
    const page = TestBed.inject(StatsComponent);
    TestBed.tick();
    const pending = http.expectOne(req => req.url === '/api/stats/overview');
    TestBed.resetTestingModule();
    pending.flush({ total_photos: 999 });
    await Promise.resolve();
    expect(page.statsFilters.overview()).toBeNull();
    http.expectNone(req => req.url.startsWith('/api/stats/'));
    http.verify();
  });

  it('clears previous data and reloads after a same-owner credential refresh', async () => {
    const page = TestBed.inject(StatsComponent);
    TestBed.tick();
    const old = http.expectOne(req => req.url === '/api/stats/overview');
    auth.token = 'new-token'; auth.status.set({ refreshed: true });
    TestBed.tick();
    const current = http.expectOne(req => req.url === '/api/stats/overview');
    old.flush({ total_photos: 999 });
    await Promise.resolve();
    expect(page.statsFilters.overview()).toBeNull();
    http.expectNone(req => req.url === '/api/stats/gear');
    current.flush({ total_photos: 4 });
    await vi.waitFor(() => expect(page.statsFilters.overview()?.total_photos).toBe(4));
    http.expectOne(req => req.url === '/api/stats/gear').flush({ cameras: [], lenses: [], combos: [] });
    http.expectOne(req => req.url === '/api/stats/categories').flush([]);
    http.expectOne(req => req.url === '/api/stats/score_distribution').flush([]);
    http.expectOne(req => req.url === '/api/stats/top_cameras').flush([]);
    http.verify();
  });

  it('keeps Retry focused on repeated failure and does not start a duplicate request', async () => {
    const page = TestBed.inject(StatsComponent) as any;
    TestBed.tick();
    http.expectOne(req => req.url === '/api/stats/overview').flush('failed', { status: 500, statusText: 'Failed' });
    await vi.waitFor(() => expect(page.loadFailed()).toBe(true));
    const button = document.createElement('button');
    button.setAttribute('data-stats-retry', ''); document.body.append(button); button.focus();
    page.retryLoad();
    const retry = http.expectOne(req => req.url === '/api/stats/overview');
    expect(page.retrying()).toBe(true);
    expect(document.activeElement).toBe(button);
    page.retryLoad();
    http.expectNone(req => req.url === '/api/stats/overview');
    retry.flush('failed', { status: 500, statusText: 'Failed' });
    await vi.waitFor(() => expect(page.retrying()).toBe(false));
    expect(page.loadFailed()).toBe(true);
    expect(document.activeElement).toBe(button);
    button.remove(); http.verify();
  });

  it('does not steal focus when a user moves away while retrying', async () => {
    const page = TestBed.inject(StatsComponent) as any;
    TestBed.tick();
    http.expectOne(req => req.url === '/api/stats/overview').flush('failed', { status: 500, statusText: 'Failed' });
    await vi.waitFor(() => expect(page.loadFailed()).toBe(true));
    const retryButton = document.createElement('button');
    retryButton.setAttribute('data-stats-retry', ''); document.body.append(retryButton); retryButton.focus();
    page.retryLoad();
    const retry = http.expectOne(req => req.url === '/api/stats/overview');
    const elsewhere = document.createElement('button'); document.body.append(elsewhere); elsewhere.focus();
    retry.flush({ total_photos: 1 });
    await vi.waitFor(() => http.expectOne(req => req.url === '/api/stats/gear').flush({ cameras: [], lenses: [], combos: [] }));
    http.expectOne(req => req.url === '/api/stats/categories').flush([]);
    http.expectOne(req => req.url === '/api/stats/score_distribution').flush([]);
    http.expectOne(req => req.url === '/api/stats/top_cameras').flush([]);
    await vi.waitFor(() => expect(page.retrying()).toBe(false));
    TestBed.tick();
    expect(document.activeElement).toBe(elsewhere);
    retryButton.remove(); elsewhere.remove(); http.verify();
  });

  it('moves focus to the heading after a successful retry when Retry still holds focus', async () => {
    const page = TestBed.inject(StatsComponent) as any;
    TestBed.tick();
    http.expectOne(req => req.url === '/api/stats/overview').flush('failed', { status: 500, statusText: 'Failed' });
    await vi.waitFor(() => expect(page.loadFailed()).toBe(true));
    const heading = document.createElement('h1'); heading.id = 'stats-heading'; heading.tabIndex = -1; document.body.append(heading);
    const retryButton = document.createElement('button'); retryButton.setAttribute('data-stats-retry', '');
    document.body.append(retryButton); retryButton.focus();
    page.retryLoad();
    http.expectOne(req => req.url === '/api/stats/overview').flush({ total_photos: 1 });
    await vi.waitFor(() => http.expectOne(req => req.url === '/api/stats/gear').flush({ cameras: [], lenses: [], combos: [] }));
    http.expectOne(req => req.url === '/api/stats/categories').flush([]);
    http.expectOne(req => req.url === '/api/stats/score_distribution').flush([]);
    http.expectOne(req => req.url === '/api/stats/top_cameras').flush([]);
    await vi.waitFor(() => expect(page.retrying()).toBe(false));
    retryButton.remove(); TestBed.tick();
    expect(document.activeElement).toBe(heading);
    heading.remove(); http.verify();
  });
});
