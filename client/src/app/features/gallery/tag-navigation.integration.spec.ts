import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { HttpRequest, provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Location } from '@angular/common';
import { provideLocationMocks } from '@angular/common/testing';
import { NavigationEnd, provideRouter, Router, RouteReuseStrategy } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, filter, firstValueFrom, take } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService } from '../../core/services/scan.service';
import { ThemeService } from '../../core/services/theme.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { GalleryReuseStrategy } from '../../core/gallery-reuse.strategy';
import { makePhoto } from '../../../testing/photo.fixture';
import { leafletMock } from '../../../testing/leaflet-mock';
import { GalleryComponent } from './gallery.component';
import { GalleryStore } from './gallery.store';

vi.doMock('leaflet', () => leafletMock);
let PhotoDetailComponent: typeof import('../photo-detail/photo-detail.component').PhotoDetailComponent;
beforeAll(async () => { ({ PhotoDetailComponent } = await import('../photo-detail/photo-detail.component')); });
const tag = 'coast,ridge OR 夜景';
const photo = makePhoto({ path: '/trip/a.jpg', tags_list: [tag], manual_tags: ['trip'] });
const config = {
  pagination: { default_per_page: 64 },
  defaults: { sort: 'star_rating', sort_direction: 'ASC', gallery_mode: 'grid', hide_details: true },
  display: { card_width_px: 168, image_width_px: 640, tags_per_photo: 5 },
  features: { show_rating_controls: true }, cull: { trash_available: true },
  quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
  sort_options_grouped: [], search_threshold_default: 0.15,
};
const album = { id: 7, name: 'Private October', is_smart: false, is_public: false, photo_count: 1 };

describe('tag pivots through actual gallery, photo, menus, Router and HTTP', () => {
  let harness: RouterTestingHarness;
  let http: HttpTestingController;
  let router: Router;
  let store: GalleryStore;
  let requests: Subject<HttpRequest<unknown>>;
  const requested = (url: string) => firstValueFrom(requests.pipe(filter(request => request.url === url), take(1)));
  const arrived = () => firstValueFrom(router.events.pipe(filter(event => event instanceof NavigationEnd), take(1)));
  const sideData = () => {
    http.match(request => request.url.startsWith('/api/filter_options/') || request.url === '/api/type_counts')
      .forEach(request => request.flush({ types: [], cameras: [], lenses: [], tags: [], persons: [], ranges: {} }));
    http.match('/api/photos/keeper_hints').forEach(request => request.flush({}));
    http.match('/api/photos/review_progress').forEach(request => request.flush({ total: 1, undecided: 1, kept: 0, rejected: 0 }));
    http.match(request => request.url === '/api/photo/set').forEach(request => request.flush({ kind: null, members: [] }));
    http.match(request => request.url === '/api/photo/faces').forEach(request => request.flush({ faces: [] }));
  };
  const render = async () => {
    harness.detectChanges(); sideData(); await Promise.resolve(); harness.detectChanges(); sideData();
  };
  const flushPage = async (status = 200) => {
    const request = http.expectOne(request => request.url === '/api/photos');
    const ready = requested('/api/type_counts');
    if (status === 200) request.flush({ photos: [photo], total: 1, page: 1, per_page: 64, total_pages: 1, has_more: false });
    else request.flush({}, { status, statusText: status === 403 ? 'Forbidden' : 'Not Found' });
    await ready;
    await render(); sideData(); await render();
    return request.request;
  };
  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear(); requests = new Subject();
    TestBed.configureTestingModule({ providers: [
      { provide: RouteReuseStrategy, useClass: GalleryReuseStrategy },
      provideRouter([{ path: '', component: GalleryComponent }, { path: 'photo', component: PhotoDetailComponent }]),
      provideLocationMocks(), provideNativeDateAdapter(),
      provideHttpClient(withXhr(), withInterceptors([(request, next) => { requests.next(request); return next(request); }])),
      provideHttpClientTesting(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      { provide: ScanService, useValue: { canLaunch: signal(false) } },
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', languages: signal([]), t: (key: string) => key } },
      { provide: AssistantChangesService, useValue: { batch$: NEVER, active: signal(false), activity: signal([]) } },
      { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
      { provide: MatSnackBar, useValue: { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) } },
    ] });
    TestBed.inject(AuthService).status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    http = TestBed.inject(HttpTestingController); router = TestBed.inject(Router); router.setUpLocationChangeListener(); store = TestBed.inject(GalleryStore);
    harness = await RouterTestingHarness.create('/?album_id=7&date_from=2026-10-01&date_to=2026-10-31');
    const albumStarted = requested('/api/albums/7');
    http.expectOne('/api/config').flush(config);
    await albumStarted;
    const photosStarted = requested('/api/photos');
    http.expectOne('/api/albums/7').flush(album);
    await photosStarted;
    await flushPage();
  });
  afterEach(() => {
    sideData(); harness.fixture.destroy(); TestBed.resetTestingModule(); http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });

  it.each([200, 403, 404])('retains the dated album query after a library tag pivot and Back (response=%s)', async status => {
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toContain(album.name);
    const card = harness.routeNativeElement!.querySelector<HTMLElement>('app-photo-card [role="button"]')!;
    expect(card).not.toBeNull();
    const navigation = arrived();
    card.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    await navigation; harness.detectChanges();
    await vi.waitFor(() => {
      harness.detectChanges();
      http.match(request => request.url === '/api/photo').forEach(request => request.flush(photo));
      http.match(request => request.url === '/api/stacks/by-photo').forEach(request => request.flush(null));
      sideData();
      expect(harness.routeNativeElement!.querySelector('[data-testid="ai-tag-chip"] button')).not.toBeNull();
    });
    await render();
    const chip = harness.routeNativeElement!.querySelector<HTMLButtonElement>('[data-testid="ai-tag-chip"] button')!;
    expect(chip).not.toBeNull(); chip.click(); await render();
    const library = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')]
      .find(button => button.textContent!.includes('photo_detail.tag_search_library'))!;
    expect(library).not.toBeUndefined();
    const libraryStarted = requested('/api/photos');
    const libraryNavigation = arrived();
    library.click();
    await libraryNavigation;
    harness.detectChanges();
    http.expectOne('/api/config').flush(config);
    await libraryStarted;
    const libraryRequest = await flushPage();
    expect(libraryRequest.params.has('album_id')).toBe(false);
    expect(libraryRequest.params.has('date_from')).toBe(false);
    expect(libraryRequest.params.get('tag_groups')).toBe(JSON.stringify({ all: [tag] }));
    expect(store.currentAlbum()).toBeNull();
    const returned = arrived(); TestBed.inject(Location).back(); await returned; harness.detectChanges();
    await vi.waitFor(() => {
      harness.detectChanges();
      http.match(request => request.url === '/api/photo').forEach(request => request.flush(photo));
      http.match(request => request.url === '/api/stacks/by-photo').forEach(request => request.flush(null));
      sideData();
      expect(harness.routeNativeElement!.querySelector('[data-testid="ai-tag-chip"] button')).not.toBeNull();
    });
    await render();
    harness.routeNativeElement!.querySelector<HTMLButtonElement>('[data-testid="manual-tag-chip"] button')!.click(); await render();
    const refine = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')]
      .find(button => button.textContent!.includes('photo_detail.tag_refine_collection'))!;
    expect(refine).not.toBeUndefined();
    const albumStarted = requested('/api/albums/7');
    const refinedNavigation = arrived();
    refine.click();
    await refinedNavigation;
    harness.detectChanges();
    http.expectOne('/api/config').flush(config);
    await albumStarted;
    const photosStarted = requested('/api/photos');
    const albumRead = http.expectOne('/api/albums/7');
    if (status === 200) albumRead.flush(album);
    else albumRead.flush({}, { status, statusText: status === 403 ? 'Forbidden' : 'Not Found' });
    await photosStarted;
    const refined = await flushPage(status);
    expect(refined.params.get('album_id')).toBe('7');
    expect(refined.params.get('date_from')).toBe('2026-10-01');
    expect(refined.params.get('date_to')).toBe('2026-10-31');
    expect(refined.params.get('tag_groups')).toBe('{"all":["trip"]}');
    if (status === 200) expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toContain(album.name);
    else {
      expect(store.loadError()).toBe(true);
      expect(store.photos()).toEqual([]);
      expect(harness.routeNativeElement!.textContent).toContain('gallery.load_error.retry');
      http.expectNone(request => request.url === '/api/photos');
      const retry = [...harness.routeNativeElement!.querySelectorAll<HTMLButtonElement>('button')]
        .find(button => button.textContent!.includes('gallery.load_error.retry'))!;
      retry.click();
      const retried = http.expectOne(request => request.url === '/api/photos');
      expect(retried.request.params.get('album_id')).toBe('7');
      expect(retried.request.params.get('date_from')).toBe('2026-10-01');
      expect(retried.request.params.get('date_to')).toBe('2026-10-31');
      expect(retried.request.params.get('tag_groups')).toBe('{"all":["trip"]}');
      retried.flush({ photos: [photo], total: 1, page: 1, per_page: 64, total_pages: 1, has_more: false });
      await vi.waitFor(() => {
        sideData(); harness.detectChanges();
        expect(store.loadError()).toBe(false);
        expect(harness.routeNativeElement!.querySelectorAll('app-photo-card')).toHaveLength(1);
      });
    }
    http.expectNone(request => request.url === '/api/photos');
  });
});
