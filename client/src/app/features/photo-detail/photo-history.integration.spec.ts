import { APP_BASE_HREF, BrowserPlatformLocation, Location, PlatformLocation } from '@angular/common';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationEnd, Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { NEVER, filter, firstValueFrom, take } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { privateImageSessionKey, resetPrivateImageSession } from '../../shared/utils/private-image-session';
import { makePhoto } from '../../../testing/photo.fixture';
import { leafletMock } from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);
let PhotoDetailComponent: typeof import('./photo-detail.component').PhotoDetailComponent;
@Component({ template: '' })
class SourceComponent {}

describe('private photo history through the Router and browser history', () => {
  let harness: RouterTestingHarness;
  let http: HttpTestingController;
  let router: Router;
  let auth: AuthService;
  const alicePhoto = makePhoto({ path: '/alice/private.jpg', filename: 'Alice private portrait.jpg' });
  const arrived = () => firstValueFrom(router.events.pipe(filter(event => event instanceof NavigationEnd), take(1)));
  const sideData = () => {
    http.match('/api/filter_options/metric_ranges').forEach(request => request.flush({ ranges: {} }));
    http.match('/api/photos/keeper_hints').forEach(request => request.flush({}));
    http.match(request => request.url === '/api/photo/set').forEach(request => request.flush({ kind: null, members: [] }));
    http.match(request => request.url === '/api/photo/objects').forEach(request => request.flush({ objects: [] }));
    http.match(request => request.url === '/api/photo/faces').forEach(request => request.flush({ faces: [] }));
    http.match(request => request.url === '/api/stacks/by-photo').forEach(request => request.flush(null));
  };
  const render = async () => {
    harness.detectChanges();
    sideData();
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  const openAlicePhoto = async () => {
    await router.navigate(['/photo'], { queryParams: { path: alicePhoto.path }, state: { photo: alicePhoto, photoSession: privateImageSessionKey() } });
    await render();
    expect(history.state.photo.path).toBe(alicePhoto.path);
    expect(harness.routeNativeElement!.textContent).toContain(alicePhoto.filename);
    http.expectNone(request => request.url === '/api/photo');
  };

  beforeAll(async () => { ({ PhotoDetailComponent } = await import('./photo-detail.component')); });
  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear();
    history.replaceState(null, '', '/');
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(),
      // Exercise the real history.state consumed by PhotoDetail, not SpyLocation's separate state.
      { provide: PlatformLocation, useClass: BrowserPlatformLocation }, { provide: APP_BASE_HREF, useValue: '/' },
      provideRouter([{ path: '', component: SourceComponent }, { path: 'photo', component: PhotoDetailComponent }, { path: 'away', component: SourceComponent }]),
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', t: (key: string) => key } },
      { provide: AssistantChangesService, useValue: { batch$: NEVER } },
    ] });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    router.setUpLocationChangeListener();
    auth = TestBed.inject(AuthService);
    auth.status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    harness = await RouterTestingHarness.create('/');
  });
  afterEach(() => {
    sideData();
    harness.fixture.destroy();
    TestBed.resetTestingModule();
    http.verify({ ignoreCancelled: true });
    history.replaceState(null, '', '/');
    localStorage.clear(); sessionStorage.clear();
  });

  it('keeps the same-session snapshot fast path when Back returns from another page', async () => {
    await openAlicePhoto();
    await router.navigateByUrl('/away');
    const back = arrived();
    TestBed.inject(Location).back();
    await back;
    await render();
    expect(harness.routeNativeElement!.textContent).toContain(alicePhoto.filename);
    http.expectNone(request => request.url === '/api/photo');
  });

  it.each([{ user: 'bob', status: 401 }, { user: 'bob', status: 404 }, { user: 'alice', status: 404 }])('does not replay old metadata on Back for $user after a new session and API $status', async ({ user, status }) => {
    await openAlicePhoto();
    await router.navigateByUrl('/away');
    // The credential-session boundary also changes for a new login by the same account.
    resetPrivateImageSession();
    auth.status.update(value => ({ ...value!, user_id: user }));
    const back = arrived();
    TestBed.inject(Location).back();
    await back;
    await render();
    expect(harness.routeNativeElement!.textContent).not.toContain(alicePhoto.filename);
    expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    const request = http.expectOne(request => request.url === '/api/photo');
    expect(request.request.params.get('path')).toBe(alicePhoto.path);
    const redirected = arrived();
    request.flush({}, { status, statusText: 'Unavailable' });
    await redirected;
    await render();
    expect(router.url).toBe('/');
    expect(harness.routeNativeElement!.textContent).not.toContain(alicePhoto.filename);
  });
});
