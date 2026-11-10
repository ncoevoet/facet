import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
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
      { provide: GalleryStore, useValue: { types: signal([]), loadTypeCounts: vi.fn(() => Promise.resolve()) } },
      { provide: I18nService, useValue: { t: (key: string) => key, locale: signal('en'), translations: () => ({}) } },
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
    http.verify();
  });

  /** Render the real template (not the bare class) so the retry button and heading are the page's own elements. */
  function render(): { fixture: ComponentFixture<StatsComponent>; page: any; host: HTMLElement } {
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges();
    return { fixture, page: fixture.componentInstance, host: fixture.nativeElement };
  }
  // The rendered page also mounts the eager Timeline tab, which makes its own read.
  const verifyRendered = () => {
    http.match(req => req.url === '/api/stats/timeline').forEach(request => request.flush([]));
    http.verify();
  };
  const failOverview = async (fixture: ComponentFixture<StatsComponent>, page: any) => {
    http.expectOne(req => req.url === '/api/stats/overview').flush('failed', { status: 500, statusText: 'Failed' });
    await vi.waitFor(() => expect(page.loadFailed()).toBe(true));
    fixture.detectChanges();
  };

  it('does not reload, or wipe loaded data, when a status refresh changes neither identity nor token', async () => {
    const page = TestBed.inject(StatsComponent);
    TestBed.tick();
    http.expectOne(req => req.url === '/api/stats/overview').flush({ total_photos: 5 });
    await vi.waitFor(() => http.expectOne(req => req.url === '/api/stats/gear').flush({ cameras: [], lenses: [], combos: [] }));
    http.expectOne(req => req.url === '/api/stats/categories').flush([]);
    http.expectOne(req => req.url === '/api/stats/score_distribution').flush([]);
    await vi.waitFor(() => expect(page.statsFilters.overview()?.total_photos).toBe(5));
    auth.status.set({ edition_authenticated: true });
    TestBed.tick();
    http.expectNone(req => req.url.startsWith('/api/stats/'));
    expect(page.statsFilters.overview()?.total_photos).toBe(5);
    verifyRendered();
  });

  it('keeps Retry focused on repeated failure and does not start a duplicate request', async () => {
    const { fixture, page, host } = render();
    await failOverview(fixture, page);
    const button = host.querySelector<HTMLButtonElement>('[data-stats-retry]')!;
    expect(button).not.toBeNull();
    button.focus();
    button.click();
    const retry = http.expectOne(req => req.url === '/api/stats/overview');
    expect(page.retrying()).toBe(true);
    expect(document.activeElement).toBe(button);
    button.click();
    http.expectNone(req => req.url === '/api/stats/overview');
    retry.flush('failed', { status: 500, statusText: 'Failed' });
    await vi.waitFor(() => expect(page.retrying()).toBe(false));
    fixture.detectChanges();
    expect(page.loadFailed()).toBe(true);
    expect(document.activeElement).toBe(host.querySelector('[data-stats-retry]'));
    verifyRendered();
  });

  it('does not steal focus when a user moves away while retrying', async () => {
    const { fixture, page, host } = render();
    await failOverview(fixture, page);
    const retryButton = host.querySelector<HTMLButtonElement>('[data-stats-retry]')!;
    retryButton.focus();
    page.retryLoad();
    const retry = http.expectOne(req => req.url === '/api/stats/overview');
    const elsewhere = document.createElement('button'); document.body.append(elsewhere); elsewhere.focus();
    retry.flush({ total_photos: 1 });
    await vi.waitFor(() => http.expectOne(req => req.url === '/api/stats/gear').flush({ cameras: [], lenses: [], combos: [] }));
    http.expectOne(req => req.url === '/api/stats/categories').flush([]);
    http.expectOne(req => req.url === '/api/stats/score_distribution').flush([]);
    await vi.waitFor(() => expect(page.retrying()).toBe(false));
    fixture.detectChanges(); TestBed.tick();
    expect(document.activeElement).toBe(elsewhere);
    elsewhere.remove(); verifyRendered();
  });

  it('moves focus to the rendered heading after a successful retry when Retry still holds focus', async () => {
    const { fixture, page, host } = render();
    await failOverview(fixture, page);
    const heading = host.querySelector<HTMLElement>('#stats-heading')!;
    expect(heading).not.toBeNull();
    expect(heading.getAttribute('tabindex')).toBe('-1');
    const retryButton = host.querySelector<HTMLButtonElement>('[data-stats-retry]')!;
    retryButton.focus();
    retryButton.click();
    http.expectOne(req => req.url === '/api/stats/overview').flush({ total_photos: 1 });
    await vi.waitFor(() => http.expectOne(req => req.url === '/api/stats/gear').flush({ cameras: [], lenses: [], combos: [] }));
    http.expectOne(req => req.url === '/api/stats/categories').flush([]);
    http.expectOne(req => req.url === '/api/stats/score_distribution').flush([]);
    await vi.waitFor(() => expect(page.retrying()).toBe(false));
    fixture.detectChanges(); TestBed.tick();
    expect(host.querySelector('[data-stats-retry]')).toBeNull();
    expect(document.activeElement).toBe(heading);
    verifyRendered();
  });

  it('keeps the tabs and the other sections when only one section read fails', async () => {
    const { fixture, page, host } = render();
    http.expectOne(req => req.url === '/api/stats/overview').flush({ total_photos: 1 });
    await vi.waitFor(() => http.expectOne(req => req.url === '/api/stats/gear').flush('failed', { status: 500, statusText: 'Failed' }));
    http.expectOne(req => req.url === '/api/stats/categories').flush([]);
    http.expectOne(req => req.url === '/api/stats/score_distribution').flush([]);
    await vi.waitFor(() => expect(page.gearFailed()).toBe(true));
    fixture.detectChanges();
    expect(page.loadFailed()).toBe(false);
    expect(host.querySelector('mat-tab-group')).not.toBeNull();
    expect(host.querySelector('[role="alert"] [mat-stroked-button], [role="alert"] button')).not.toBeNull();
    verifyRendered();
  });
});
