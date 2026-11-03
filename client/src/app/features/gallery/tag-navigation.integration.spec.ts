import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { HttpRequest, provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { Location } from '@angular/common';
import { provideLocationMocks } from '@angular/common/testing';
import { NavigationEnd, provideRouter, Router, RouteReuseStrategy } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatSidenavContent } from '@angular/material/sidenav';
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
    http.match(request => request.url === '/api/photo/objects').forEach(request => request.flush({ objects: [] }));
  };
  const render = async () => {
    harness.detectChanges(); sideData(); await Promise.resolve(); harness.detectChanges(); sideData();
  };
  const flushPage = async (status = 200, hasMore = false) => {
    const request = http.expectOne(request => request.url === '/api/photos');
    const ready = requested('/api/type_counts');
    if (status === 200) request.flush({ photos: [photo], total: hasMore ? 2 : 1, page: 1, per_page: 64, total_pages: hasMore ? 2 : 1, has_more: hasMore });
    else request.flush({}, { status, statusText: status === 403 ? 'Forbidden' : 'Not Found' });
    await ready;
    await render(); sideData(); await render();
    return request.request;
  };
  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear(); requests = new Subject();
    TestBed.configureTestingModule({ providers: [
      { provide: RouteReuseStrategy, useClass: GalleryReuseStrategy },
      provideRouter([{ path: '', component: GalleryComponent }, { path: 'album/:albumId', component: GalleryComponent }, { path: 'photo', component: PhotoDetailComponent }]),
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
    sideData(); harness.fixture.destroy(); TestBed.resetTestingModule(); vi.restoreAllMocks(); http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });

  it('ignores a delayed album response after a newer album route initializes', async () => {
    await harness.navigateByUrl('/album/1', GalleryComponent);
    const oldAlbumStarted = requested('/api/albums/1');
    http.expectOne('/api/config').flush(config);
    await oldAlbumStarted;
    const oldAlbum = http.expectOne('/api/albums/1');

    await harness.navigateByUrl('/album/2', GalleryComponent);
    const newAlbumStarted = requested('/api/albums/2');
    http.expectOne('/api/config').flush(config);
    await newAlbumStarted;
    const pageStarted = requested('/api/photos');
    http.expectOne('/api/albums/2').flush({ ...album, id: 2, name: 'Current album' });
    await pageStarted;
    await flushPage();
    expect(store.currentAlbum()?.id).toBe(2);

    if (!oldAlbum.cancelled) oldAlbum.flush({ ...album, id: 1, name: 'Departed album' });
    await render();
    const obsoletePages = http.match(request => request.url === '/api/photos');
    for (const request of obsoletePages) request.flush({ photos: [], total: 0, page: 1, per_page: 64, total_pages: 1, has_more: false });
    await render();
    expect(router.url).toBe('/album/2');
    expect(store.currentAlbum()?.id).toBe(2);
    expect(store.filters().album_id).toBe('2');
    expect(obsoletePages).toHaveLength(0);
  });

  it.each(['ready', 'config-ready', 'early-back', 'page-started', 'failed-page', 'identity', 'destroy'] as const)('defers parked initialization and preserves its lifecycle (%s)', async outcome => {
    vi.spyOn(MatSidenavContent.prototype, 'scrollTo').mockImplementation(function (this: MatSidenavContent, options) {
      if (options.top !== undefined) this.getElementRef().nativeElement.scrollTop = options.top;
    });
    const scrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
    try {
      await harness.navigateByUrl('/album/1', GalleryComponent);
      const pendingConfig = http.expectOne('/api/config');
      let pendingAlbum: TestRequest;
      if (outcome !== 'config-ready') {
        const albumStarted = requested('/api/albums/1');
        pendingConfig.flush(config);
        await albumStarted;
        pendingAlbum = http.expectOne('/api/albums/1');
      }
      let interruptedPage: TestRequest | undefined;
      if (outcome === 'page-started') {
        const pageStarted = requested('/api/photos');
        pendingAlbum!.flush({ ...album, id: 1, name: 'Parked album' });
        await pageStarted;
        interruptedPage = http.expectOne(request => request.url === '/api/photos');
      }
      await harness.navigateByUrl('/photo?path=%2Ftrip%2Fa.jpg', PhotoDetailComponent);
      http.match(request => request.url === '/api/photo').forEach(request => request.flush(photo));
      http.match(request => request.url === '/api/stacks/by-photo').forEach(request => request.flush(null));
      await render();
      if (outcome === 'config-ready') {
        const albumStarted = requested('/api/albums/1');
        pendingConfig.flush(config);
        await albumStarted;
        pendingAlbum = http.expectOne('/api/albums/1');
      }
      if (interruptedPage) expect(interruptedPage.cancelled).toBe(true);
      else expect(pendingAlbum!.cancelled).toBe(false);
      if (outcome === 'early-back') {
        const back = arrived(); TestBed.inject(Location).back(); await back; harness.detectChanges();
        await render();
        http.expectNone(request => request.url === '/api/photos');
      }
      if (!interruptedPage) pendingAlbum!.flush({ ...album, id: 1, name: 'Parked album' });
      await render();
      expect(store.currentAlbum()?.id).toBe(1);
      if (outcome !== 'early-back') http.expectNone(request => request.url === '/api/photos');
      if (outcome === 'identity') TestBed.inject(AuthService).status.set({ ...TestBed.inject(AuthService).status()!, user_id: 'bob' });
      if (outcome === 'destroy') {
        await harness.navigateByUrl('/album/2', GalleryComponent);
        const albumStarted = requested('/api/albums/2');
        http.expectOne('/api/config').flush(config);
        await albumStarted;
        const pageStarted = requested('/api/photos');
        http.expectOne('/api/albums/2').flush({ ...album, id: 2 });
        await pageStarted;
        const page = http.expectOne(request => request.url === '/api/photos');
        expect(page.request.params.get('album_id')).toBe('2');
        page.flush({ photos: [photo], total: 1, page: 1, per_page: 64, total_pages: 1, has_more: false });
        await render();
        expect(store.initializing()).toBe(false);
        expect(store.currentAlbum()?.id).toBe(2);
        http.expectNone(request => request.url === '/api/photos');
        return;
      }
      let successfulPages = 0;
      const settlePages = () => {
        for (const page of http.match(request => request.url === '/api/photos')) {
          successfulPages++;
          expect(page.request.params.get('album_id')).toBe('1');
          page.flush({ photos: [photo], total: 1, page: 1, per_page: 64, total_pages: 1, has_more: false });
        }
      };
      settlePages();
      await render();
      if (outcome !== 'early-back') {
        const back = arrived(); TestBed.inject(Location).back(); await back; harness.detectChanges();
      }
      await render();
      if (outcome === 'identity') {
        http.expectNone(request => request.url === '/api/photos');
        expect(store.initializing()).toBe(false);
        return;
      }
      if (outcome === 'failed-page') {
        http.expectOne(request => request.url === '/api/photos').flush({}, { status: 500, statusText: 'Failed' });
        await render();
        expect(store.loadError()).toBe(true);
        const retry = store.reloadPhotos();
        settlePages(); await retry;
      } else settlePages();
      await render();
      expect(store.initializing()).toBe(false);
      expect(router.url).toBe('/album/1');
      expect(store.currentAlbum()?.id).toBe(1);
      expect(store.photos().map(item => item.path)).toEqual([photo.path]);
      expect(successfulPages).toBe(1);
    } finally {
      if (scrollIntoView) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', scrollIntoView);
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
    }
  });

  it.each(['success', 'failure'] as const)('ignores an obsolete config %s after another album initializes', async outcome => {
    await harness.navigateByUrl('/album/1', GalleryComponent);
    const obsoleteConfig = http.expectOne('/api/config');
    await harness.navigateByUrl('/album/2', GalleryComponent);
    const albumStarted = requested('/api/albums/2');
    http.expectOne('/api/config').flush(config);
    await albumStarted;
    const pageStarted = requested('/api/photos');
    http.expectOne('/api/albums/2').flush({ ...album, id: 2, name: 'Current album' });
    await pageStarted;
    await flushPage();
    const filters = store.filters();
    if (outcome === 'success') obsoleteConfig.flush({ ...config, defaults: { ...config.defaults, sort: 'filename' } });
    else obsoleteConfig.flush({}, { status: 500, statusText: 'Failed' });
    await render();
    expect(store.filters()).toBe(filters);
    expect(store.currentAlbum()?.id).toBe(2);
    expect(store.initializing()).toBe(false);
    http.expectNone('/api/albums/1');
    http.expectNone(request => request.url === '/api/photos');
  });

  it.each(['identity', 'token'] as const)('refuses pending initialization after %s rotation', async change => {
    await harness.navigateByUrl('/album/1', GalleryComponent);
    const pending = http.expectOne('/api/config');
    const auth = TestBed.inject(AuthService);
    const filters = store.filters();
    if (change === 'identity') auth.status.set({ ...auth.status()!, user_id: 'bob' });
    else vi.spyOn(auth, 'token', 'get').mockReturnValue('rotated-session');
    pending.flush(config);
    await render();
    expect(store.filters()).toBe(filters);
    expect(store.currentAlbum()).toBeNull();
    expect(store.initializing()).toBe(false);
    http.expectNone('/api/albums/1');
    http.expectNone(request => request.url === '/api/photos');
  });

  it.each([{ status: 200, interrupt: null }, { status: 200, interrupt: 'wheel' }, { status: 200, interrupt: 'page_failure' }, { status: 403, interrupt: null }, { status: 404, interrupt: null }])('retains the dated album query after a library tag pivot and Back (%j)', async ({ status, interrupt }) => {
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toContain(album.name);
    const selectedPhoto = status === 200 ? { ...photo, path: '/trip/b.jpg' } : photo;
    if (status === 200) {
      store.hasMore.set(true);
      const paging = store.nextPage();
      http.expectOne(request => request.url === '/api/photos').flush({
        photos: [selectedPhoto], total: 2, page: 2, per_page: 64, total_pages: 2, has_more: false,
      });
      await paging; await render();
    }
    const card = harness.routeNativeElement!.querySelectorAll<HTMLElement>('app-photo-card [role="button"]')[status === 200 ? 1 : 0];
    expect(card).not.toBeUndefined();
    document.body.appendChild(harness.fixture.nativeElement);
    const initialScroll = harness.routeNativeElement!.querySelector<HTMLElement>('mat-sidenav-content')!;
    initialScroll.scrollTop = 260;
    vi.spyOn(MatSidenavContent.prototype, 'scrollTo').mockImplementation(function (this: MatSidenavContent, options) {
      if (options.top !== undefined) this.getElementRef().nativeElement.scrollTop = options.top;
    });
    card.focus();
    expect(document.activeElement).toBe(card);
    const navigation = arrived();
    card.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    await navigation; harness.detectChanges();
    await vi.waitFor(() => {
      harness.detectChanges();
      http.match(request => request.url === '/api/photo').forEach(request => request.flush(selectedPhoto));
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
      http.match(request => request.url === '/api/photo').forEach(request => request.flush(selectedPhoto));
      http.match(request => request.url === '/api/stacks/by-photo').forEach(request => request.flush(null));
      sideData();
      expect(harness.routeNativeElement!.querySelector('[data-testid="ai-tag-chip"] button')).not.toBeNull();
    });
    await render();
    if (status === 200) {
      const originalAlbumStarted = requested('/api/albums/7');
      const back = arrived(); TestBed.inject(Location).back(); await back; harness.detectChanges();
      http.expectOne('/api/config').flush(config);
      await originalAlbumStarted;
      const originalPhotosStarted = requested('/api/photos');
      http.expectOne('/api/albums/7').flush(album);
      await originalPhotosStarted;
      const anchorPageStarted = requested('/api/photos');
      await flushPage(200, true);
      await anchorPageStarted;
      const anchorPage = http.expectOne(request => request.url === '/api/photos');
      expect(anchorPage.request.params.get('page')).toBe('2');
      expect(anchorPage.request.params.get('album_id')).toBe('7');
      const restoringScroll = harness.routeNativeElement!.querySelector<HTMLElement>('mat-sidenav-content')!;
      if (interrupt === 'wheel') {
        restoringScroll.scrollTop = 91;
        document.dispatchEvent(new WheelEvent('wheel', { bubbles: true }));
      }
      if (interrupt === 'page_failure') {
        anchorPage.flush({}, { status: 503, statusText: 'Unavailable' });
        await vi.waitFor(() => {
          sideData(); harness.detectChanges();
          expect(store.loading()).toBe(false);
          expect(store.filters().page).toBe(1);
        });
        expect(restoringScroll.scrollTop).toBe(0);
        expect(document.activeElement?.closest('[data-pidx]')).toBeNull();
        http.expectNone(request => request.url === '/api/photos');
        return;
      }
      anchorPage.flush({ photos: [selectedPhoto], total: 2, page: 2, per_page: 64, total_pages: 2, has_more: false });
      if (interrupt === 'wheel') {
        await vi.waitFor(() => {
          sideData(); harness.detectChanges();
          expect(store.photos()).toHaveLength(2);
        });
        expect(restoringScroll.scrollTop).toBe(91);
        expect(document.activeElement?.closest('[data-pidx]')).toBeNull();
        return;
      }
      await vi.waitFor(() => {
        harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector<HTMLElement>('mat-sidenav-content')!.scrollTop).toBe(260);
        expect(document.activeElement?.closest('[data-pidx]')?.getAttribute('data-pidx')).toBe('1');
      }, { timeout: 5000 }); // Frame-driven focus can exceed the default 1s under full-suite load.
      const scrolled = harness.routeNativeElement!.querySelector<HTMLElement>('mat-sidenav-content')!;
      scrolled.scrollTop = 333;
      scrolled.dispatchEvent(new Event('scroll'));
      const historyWrite = vi.spyOn(TestBed.inject(Location), 'replaceState')
        .mockImplementation(() => { throw new DOMException('History writes refused', 'SecurityError'); });
      for (let event = 0; event < 1000; event++) scrolled.dispatchEvent(new Event('scroll'));
      expect(historyWrite).not.toHaveBeenCalled();
      historyWrite.mockRestore();
      const reopen = arrived();
      harness.routeNativeElement!.querySelectorAll<HTMLElement>('app-photo-card [role="button"]')[1]
        .dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      await reopen;
      await vi.waitFor(() => {
        harness.detectChanges();
        http.match(request => request.url === '/api/photo').forEach(request => request.flush(selectedPhoto));
        http.match(request => request.url === '/api/stacks/by-photo').forEach(request => request.flush(null));
        sideData();
        expect(harness.routeNativeElement!.querySelector('[data-testid="manual-tag-chip"] button')).not.toBeNull();
      });
    }
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
  }, 15000);
});
