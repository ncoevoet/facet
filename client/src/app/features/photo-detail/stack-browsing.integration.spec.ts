import { StackNavigatorComponent } from './stack-navigator.component';
import { By } from '@angular/platform-browser';
import { Location } from '@angular/common';
import { provideLocationMocks } from '@angular/common/testing';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController } from '@angular/common/http/testing';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationStart, NavigationEnd, Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, firstValueFrom, filter, merge, take } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AssistantChangesService, AssistantChangeBatch } from '../../core/agent/assistant-changes.service';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { GalleryStore } from '../gallery/gallery.store';
import { makePhoto } from '../../../testing/photo.fixture';
import { leafletMock } from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);
let PhotoDetailComponent: typeof import('./photo-detail.component').PhotoDetailComponent;
@Component({ template: '' })
class SourceComponent {}
const paths = ['/a.jpg', '/b.jpg', '/c.jpg'];
const stack = { id: 's1', revision: 1, editable: true, cover_path: paths[0], members: paths.map(path => ({ path })) };

describe('manual stack browsing through rendered viewer, Router and HTTP', () => {
  let harness: RouterTestingHarness;
  let http: HttpTestingController;
  let router: Router;
  let store: GalleryStore;
  let auth: AuthService;
  let assistantBatches: Subject<AssistantChangeBatch>;
  let snack = { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) };
  const root = () => harness.routeNativeElement!;
  const button = (selector: string) => root().querySelector<HTMLButtonElement>(selector)!;
  const sideData = () => {
    http.match('/api/filter_options/metric_ranges').forEach(request => request.flush({ ranges: {} }));
    http.match('/api/photos/keeper_hints').forEach(request => request.flush({}));
    http.match(request => request.url === '/api/photo/set').forEach(request => request.flush({ kind: null, members: [] }));
    // The object layer asks for each photo's marked objects.
    http.match(request => request.url === '/api/photo/objects').forEach(request => request.flush({ objects: [] }));
    // The face layer loads alongside each stack member; keep other requests strict.
    http.match(request => request.url === '/api/photo/faces').forEach(request => request.flush({ faces: [] }));
  };
  const render = async () => {
    harness.detectChanges();
    sideData();
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  const initialPhoto = async () => {
    harness.detectChanges();
    http.match(request => request.url === '/api/photo').forEach(request => request.flush(makePhoto({ path: request.request.params.get('path')! })));
    await render();
  };
  const membership = async (value: object | null = stack) => {
    await initialPhoto();
    const reads = http.match(request => request.url === '/api/stacks/by-photo');
    expect(reads.length).toBeGreaterThan(0);
    reads.filter(request => !request.cancelled).forEach(request => request.flush(value));
    await render();
  };
  const arrived = () => firstValueFrom(router.events.pipe(filter(event => event instanceof NavigationEnd), take(1)));
  const open = async (path = paths[1]) => {
    await router.navigate(['/photo'], { queryParams: { path }, state: { photo: makePhoto({ path }) } });
    await membership();
  };
  const clickMember = async (selector: string, path: string) => {
    const navigation = arrived();
    button(selector).click();
    const request = http.expectOne(request => request.url === '/api/photo');
    expect(request.request.params.get('path')).toBe(path);
    request.flush(makePhoto({ path }));
    await navigation;
    await membership();
  };
  const keyboardMember = async (key: string, path: string) => {
    const navigation = arrived();
    document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path }));
    await navigation;
    await membership();
  };
  // jsdom has no layout. Browser coverage measures the real toolbar; here the
  // geometry lets Router/HTTP tests assert the temporary host reservation.
  const measuredNavigator = () => {
    const host = root().querySelector<HTMLElement>('app-stack-navigator')!;
    vi.spyOn(host, 'getBoundingClientRect').mockReturnValue({ height: 105 } as DOMRect);
    return host;
  };
  const pendingMember = async () => {
    const navigation = arrived();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[2], stack_id: stack.id }));
    await navigation;
    await initialPhoto();
    const read = http.expectOne(request => request.url === '/api/stacks/by-photo');
    expect(read.request.params.get('path')).toBe(paths[2]);
    return read;
  };

  beforeAll(async () => { ({ PhotoDetailComponent } = await import('./photo-detail.component')); });
  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear();
    snack = { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) };
    assistantBatches = new Subject();
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(), provideLocationMocks(),
      provideRouter([{ path: '', component: SourceComponent }, { path: 'photo', component: PhotoDetailComponent }, { path: 'away', component: SourceComponent }]),
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', t: (key: string, params?: Record<string, unknown>) => key === 'stacks.browse_position' ? params?.['position'] + ' of ' + params?.['count'] : key === 'photo_detail.collection.position' ? 'Collection ' + params?.['position'] + ' / ' + params?.['total'] : key === 'stacks.open_member' ? key + ' ' + params?.['path'] : key } },
      { provide: AssistantChangesService, useValue: { batch$: assistantBatches.asObservable() } },
      { provide: MatSnackBar, useValue: snack },
    ] });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    router.setUpLocationChangeListener();
    auth = TestBed.inject(AuthService);
    auth.status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    store = TestBed.inject(GalleryStore);
    store.photos.set([makePhoto({ path: paths[1] }), makePhoto({ path: '/outside.jpg' })]);
    store.filters.update(filters => ({ ...filters, no_gps: 'true' }));
    harness = await RouterTestingHarness.create('/?no_gps=true');
  });
  afterEach(() => {
    sideData();
    harness.fixture.destroy();
    TestBed.resetTestingModule();
    http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });

  it('pans a zoomed photo without Router/HTTP navigation and restores navigation at Fit', async () => {
    await open();
    const canvas = root().querySelector<HTMLElement>('[data-photo-canvas]')!;
    Object.defineProperty(canvas, 'clientWidth', { value: 400 });
    Object.defineProperty(canvas, 'clientHeight', { value: 300 });
    const key = (value: string) => {
      canvas.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true }));
      harness.detectChanges();
    };
    const before = router.url;
    key('+'); key('ArrowRight');
    expect((canvas.querySelector('img') as HTMLImageElement).style.transform).toBe('scale(1.25) translate(-32px, 0px)');
    expect(router.url).toBe(before);
    http.expectNone(request => request.url === '/api/photo');
    key('Home'); expect((canvas.querySelector('img') as HTMLImageElement).style.transform).toBe('');
    const navigation = arrived(); key('ArrowRight');
    const request = http.expectOne(request => request.url === '/api/photo');
    expect(request.request.params.get('path')).toBe(paths[2]);
    request.flush(makePhoto({ path: paths[2] })); await navigation; await membership();
  });

  it('browses the originating collection without changing filters, selection, or Back destination', async () => {
    await open();
    const beforeFilters = { ...store.filters() };
    const beforeSelection = new Set(store.selectedPaths());
    const navigation = arrived();
    const sidebar = root().querySelector('app-photo-collection-sidebar')!;
    const thumbnails = sidebar.querySelectorAll<HTMLButtonElement>('button[title]');
    expect(thumbnails).toHaveLength(2);
    thumbnails[1].click();
    await navigation;
    await membership(null);
    expect(router.url).toContain(encodeURIComponent('/outside.jpg'));
    const images = root().querySelectorAll<HTMLImageElement>('div.cursor-grab > img');
    expect(new URL(images[0].src).searchParams.get('path')).toBe('/outside.jpg');
    expect(new URL(images[1].src).searchParams.get('path')).toBe('/outside.jpg');
    expect(new URL(images[2].src).searchParams.get('path')).toBe('/outside.jpg');
    expect(sidebar.querySelector('[aria-current="true"]')).not.toBeNull();
    expect(store.filters()).toEqual(beforeFilters);
    expect(store.selectedPaths()).toEqual(beforeSelection);
    const returned = arrived();
    button('button[aria-label="photo_detail.back"]').click();
    await returned;
    expect(router.url).toBe('/?no_gps=true');
  });

  it('leaves a stack cover through collection arrows without stepping into its members', async () => {
    const cover = makePhoto({ path: paths[0], stack_id: stack.id });
    store.photos.set([cover, makePhoto({ path: '/outside.jpg', filename: 'outside.jpg' })]);
    await router.navigate(['/photo'], { queryParams: { path: cover.path }, state: { photo: cover } });
    await membership();
    expect(button('[data-stack-next]').disabled).toBe(false);
    const beforeFilters = { ...store.filters() };

    const navigation = arrived();
    button('[data-photo-next]').click();
    await navigation;
    await membership(null);

    expect(router.url).toContain(encodeURIComponent('/outside.jpg'));
    expect(store.filters()).toEqual(beforeFilters);
    expect(root().querySelector('h1')?.textContent).toContain('outside.jpg');
  });

  it.each(['click', 'ArrowRight', 'ArrowLeft', 'unannotated'])('keeps collapsed collection navigation on non-cover members (%s)', async action => {
    const cover = makePhoto({ path: paths[0], stack_id: stack.id });
    const outside = makePhoto({ path: '/outside.jpg', filename: 'outside.jpg' });
    store.photos.set(action === 'ArrowLeft' ? [outside, cover] : [cover, outside]);
    store.total.set(2);
    const member = makePhoto({ path: action === 'ArrowRight' ? paths[2] : paths[1], stack_id: action === 'unannotated' ? null : stack.id });
    await router.navigate(['/photo'], { queryParams: { path: member.path }, state: { photo: member } });
    harness.detectChanges();
    http.match(request => request.url === '/api/photo').forEach(request => request.flush(member));
    await membership();
    expect(root().querySelector('app-photo-collection-sidebar [data-collection-current]')?.getAttribute('aria-label')).toBe(cover.filename);
    expect(root().querySelector('[data-photo-next]')).not.toBeNull();
    expect(root().querySelector('[data-photo-previous]')).not.toBeNull();
    expect(root().querySelector('[data-collection-position]')?.textContent).toContain(action === 'ArrowLeft' ? 'Collection 2 / 2' : 'Collection 1 / 2');
    if (action === 'ArrowLeft') await keyboardMember('ArrowLeft', paths[0]);
    const navigation = arrived();
    if (action === 'click' || action === 'unannotated') button('[data-photo-next]').click();
    else document.dispatchEvent(new KeyboardEvent('keydown', { key: action, bubbles: true }));
    await navigation;
    await membership(null);
    expect(router.url).toContain(encodeURIComponent('/outside.jpg'));
  });

  it('pages from a folded member using its cover slot', async () => {
    const cover = makePhoto({ path: paths[0], stack_id: stack.id });
    const member = makePhoto({ path: paths[1], stack_id: stack.id });
    store.photos.set([cover]); store.total.set(2); store.hasMore.set(true);
    await router.navigate(['/photo'], { queryParams: { path: member.path }, state: { photo: member } });
    harness.detectChanges();
    http.match(request => request.url === '/api/photo').forEach(request => request.flush(member));
    await membership();
    expect(button('[data-photo-next]').getAttribute('aria-label')).toBe('photo_detail.collection.next');
    expect(root().querySelector('[data-photo-inspector]')?.getAttribute('aria-label')).toBe('photo_detail.details');
    expect(root().querySelector('[data-photo-info] summary h2')).not.toBeNull();
    const favorite = button('[aria-label="rating.favorite"]');
    expect(favorite.getAttribute('aria-pressed')).toBe('false');
    const navigation = arrived();
    button('[data-photo-next]').click();
    const request = http.expectOne(request => request.url === '/api/photos');
    expect(request.request.params.get('page')).toBe('2');
    request.flush({ photos: [makePhoto({ path: '/next.jpg' })], total: 2, photo_total: 2, has_more: false });
    await navigation;
    await membership(null);
    expect(router.url).toContain(encodeURIComponent('/next.jpg'));
  });

  it('reports failed Next paging and retries the same collection page', async () => {
    store.photos.set([makePhoto({ path: '/outside.jpg' })]);
    store.hasMore.set(true);
    await router.navigate(['/photo'], { queryParams: { path: '/outside.jpg' }, state: { photo: store.photos()[0] } });
    await membership(null);
    button('[data-photo-next]').click();
    const failed = http.expectOne(request => request.url === '/api/photos');
    expect(failed.request.params.get('page')).toBe('2');
    failed.flush({}, { status: 503, statusText: 'Offline' });
    await render();
    expect(router.url).toContain(encodeURIComponent('/outside.jpg'));
    expect(button('[data-photo-next]').disabled).toBe(false);
    expect(snack.open).toHaveBeenCalledWith('gallery.load_error.page_failed', '', expect.anything());

    const navigation = arrived();
    button('[data-photo-next]').click();
    const retry = http.expectOne(request => request.url === '/api/photos');
    expect(retry.request.params.get('page')).toBe('2');
    expect(retry.request.params.get('no_gps')).toBe('true');
    retry.flush({ photos: [makePhoto({ path: '/next.jpg' })], total: 2, photo_total: 2, has_more: false });
    await navigation;
    await membership(null);
    expect(router.url).toContain(encodeURIComponent('/next.jpg'));
    expect(button('[data-photo-next]').disabled).toBe(true);
  });

  it('returns to an explicitly marked in-app origin without a prefetched photo', async () => {
    await router.navigate(['/photo'], { queryParams: { path: paths[1] }, state: { photoOrigin: 'in-app' } });
    await membership(null);
    const returned = arrived();
    button('button[aria-label="photo_detail.back"]').click();
    await returned;
    expect(router.url).toBe('/?no_gps=true');
  });

  it('keeps a direct photo entry safe after tag search, browser Back and viewer Escape', async () => {
    await router.navigate(['/photo'], { queryParams: { path: paths[1] }, replaceUrl: true });
    await membership(null);
    expect(TestBed.inject(Location).getState()).toEqual(expect.objectContaining({ photoBack: false }));
    const page = harness.routeDebugElement!.componentInstance as unknown as { navigateTag(tag: string, scope: 'library'): void };
    let navigation = arrived(); page.navigateTag('coast', 'library'); await navigation;
    navigation = arrived(); TestBed.inject(Location).back(); await navigation; await membership(null);
    const back = vi.spyOn(TestBed.inject(Location), 'back');
    navigation = arrived();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await navigation;
    expect(back).not.toHaveBeenCalled(); expect(router.url).toBe('/');
  });

  it('updates Back ownership when browser history reuses the same photo component', async () => {
    await open();
    const instance = harness.routeDebugElement!.componentInstance;
    await router.navigate(['/photo'], { queryParams: { path: '/outside.jpg' }, state: { photoBack: false, photo: makePhoto({ path: '/outside.jpg' }) } });
    await membership(null);
    expect(harness.routeDebugElement!.componentInstance).toBe(instance);
    const back = vi.spyOn(TestBed.inject(Location), 'back');
    const returned = arrived(); button('button[aria-label="photo_detail.back"]').click(); await returned;
    expect(back).not.toHaveBeenCalled(); expect(router.url).toBe('/');
  });

  it.each([false, true])('retains the photo visit collection after a library tag search and history Back (step=%s)', async step => {
    store.filters.update(filters => ({ ...filters, album_id: '7', date_from: '2026-10-01', date_to: '2026-10-31' }));
    await open();
    if (step) {
      const navigation = arrived();
      root().querySelectorAll<HTMLButtonElement>('app-photo-collection-sidebar button[title]')[1].click();
      await navigation;
      await membership(null);
    }
    const photoPage = () => harness.routeDebugElement!.componentInstance as unknown as {
      navigateTag(tag: string, scope: 'library' | 'collection'): void;
    };
    let navigation = arrived();
    photoPage().navigateTag('coast,ridge OR 夜景', 'library');
    await navigation;
    // A library visit replaces the singleton store's current query. The photo
    // visit's origin must survive independently of that later gallery state.
    store.filters.update(filters => ({ ...filters, album_id: '', date_from: '', date_to: '', no_gps: '',
      tag_groups: '{"all":["coast,ridge OR 夜景"]}' }));
    navigation = arrived();
    TestBed.inject(Location).back();
    await navigation;
    await membership(step ? null : stack);
    navigation = arrived();
    photoPage().navigateTag('夜景', 'collection');
    await navigation;
    const url = new URL(router.url, 'http://fixture');
    expect(url.searchParams.get('album_id')).toBe('7');
    expect(url.searchParams.get('date_from')).toBe('2026-10-01');
    expect(url.searchParams.get('date_to')).toBe('2026-10-31');
    expect(url.searchParams.get('no_gps')).toBe('true');
    expect(url.searchParams.get('tag_groups')).toBe('{"all":["夜景"]}');
  });

  it('restores each query when history navigation reuses the photo component', async () => {
    store.filters.update(filters => ({ ...filters, album_id: '7' }));
    await open();
    const instance = harness.routeDebugElement!.componentInstance;
    store.filters.update(filters => ({ ...filters, album_id: '99' }));
    await router.navigate(['/photo'], { queryParams: { path: '/outside.jpg' }, state: { photo: makePhoto({ path: '/outside.jpg' }) } });
    await membership(null);
    expect(harness.routeDebugElement!.componentInstance).toBe(instance);
    const navigation = arrived();
    TestBed.inject(Location).back();
    await navigation;
    await membership();
    expect(harness.routeDebugElement!.componentInstance).toBe(instance);
    const forward = arrived();
    TestBed.inject(Location).forward();
    await forward;
    await membership(null);
    expect(TestBed.inject(Location).getState()).toEqual(expect.objectContaining({
      photoTagOrigin: expect.objectContaining({ params: expect.objectContaining({ album_id: '99' }) }),
    }));
    const back = arrived();
    TestBed.inject(Location).back();
    await back;
    await membership();
    const returned = arrived();
    (instance as { navigateTag(tag: string, scope: 'collection'): void }).navigateTag('trip', 'collection');
    await returned;
    expect(new URL(router.url, 'http://fixture').searchParams.get('album_id')).toBe('7');
  });

  it('does not adopt an old photo visit collection after another account returns through Back', async () => {
    store.filters.update(filters => ({ ...filters, album_id: '7' }));
    await open();
    let navigation = arrived();
    await router.navigateByUrl('/away');
    await navigation;
    auth.status.update(status => ({ ...status!, user_id: 'bob' }));
    store.filters.update(filters => ({ ...filters, album_id: '99' }));
    navigation = arrived();
    TestBed.inject(Location).back();
    await navigation;
    await membership();
    const page = harness.routeDebugElement!.componentInstance as unknown as {
      tagCollectionAvailable(): boolean;
      navigateTag(tag: string, scope: 'collection' | 'library'): void;
    };
    expect(page.tagCollectionAvailable()).toBe(false);
    page.navigateTag('trip', 'collection');
    expect(router.url).toContain('/photo?');
    navigation = arrived();
    page.navigateTag('trip', 'library');
    await navigation;
    expect(router.url).toBe('/?tag_groups=%7B%22all%22:%5B%22trip%22%5D%7D');
  });

  it.each(['pinned', 'similar'])('keeps %s visits unavailable for query refinement after Back', async kind => {
    if (kind === 'pinned') store.pinnedPaths.set([paths[1]]);
    else store.filters.update(filters => ({ ...filters, similar_to: '/source.jpg' }));
    await open();
    const page = () => harness.routeDebugElement!.componentInstance as unknown as {
      tagCollectionAvailable(): boolean;
      navigateTag(tag: string, scope: 'collection' | 'library'): void;
    };
    let navigation = arrived();
    page().navigateTag('trip', 'library');
    await navigation;
    store.pinnedPaths.set(null);
    store.filters.update(filters => ({ ...filters, similar_to: '' }));
    navigation = arrived();
    TestBed.inject(Location).back();
    await navigation;
    await membership();
    expect(page().tagCollectionAvailable()).toBe(false);
    page().navigateTag('trip', 'collection');
    expect(router.url).toContain('/photo?');
  });

  it('does not navigate from a stale collection button after the account changes', async () => {
    await open();
    const thumbnail = root().querySelectorAll<HTMLButtonElement>('app-photo-collection-sidebar button[title]')[1];
    auth.status.update(status => ({ ...status!, user_id: 'bob' }));
    thumbnail.click();
    await initialPhoto();
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    expect(root().querySelector('app-photo-collection-sidebar')).toBeNull();
  });

  it('loads and retries the next collection page using the preserved query', async () => {
    await open();
    store.hasMore.set(true); store.total.set(3);
    await render();
    const load = () => button('app-photo-collection-sidebar div[tabindex] > button').click();
    load();
    const failed = http.expectOne(request => request.url === '/api/photos');
    expect(failed.request.params.get('no_gps')).toBe('true');
    expect(failed.request.params.get('page')).toBe('2');
    failed.flush({}, { status: 503, statusText: 'Offline' });
    await render();
    expect(store.photos()).toHaveLength(2);
    expect(store.filters().page).toBe(1);
    load();
    const retry = http.expectOne(request => request.url === '/api/photos');
    expect(retry.request.params.get('page')).toBe('2');
    retry.flush({ photos: [makePhoto({ path: '/next.jpg' })], total: 3, photo_total: 3, has_more: false });
    await render();
    expect(store.photos().map(photo => photo.path)).toEqual([paths[1], '/outside.jpg', '/next.jpg']);
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    expect(store.filters().no_gps).toBe('true');
  });

  it('refreshes and follows an explicitly changed primary without changing the gallery query', async () => {
    await open();
    store.selectedPaths.set(new Set([paths[1]]));
    const component = harness.routeDebugElement!.componentInstance as { onLogicalAssetApplied(change: object): Promise<void> };
    const applying = component.onLogicalAssetApplied({ operation: 'primary', assetId: 'asset', primaryPath: '/outside.jpg', members: [paths[1], '/outside.jpg'] });
    const read = http.expectOne(request => request.url === '/api/photo');
    expect(read.request.params.get('path')).toBe('/outside.jpg');
    read.flush(makePhoto({ path: '/outside.jpg', filename: 'chosen-primary.jpg' }));
    await applying;
    await membership(null);
    expect(router.url).toContain(encodeURIComponent('/outside.jpg'));
    expect(root().querySelector('[data-photo-detail-header]')?.textContent).toContain('chosen-primary.jpg');
    expect([...store.selectedPaths()]).toEqual(['/outside.jpg']);
    expect(store.filters().no_gps).toBe('true');
  });

  it('does not follow an obsolete primary refresh after navigating away', async () => {
    await open();
    const component = harness.routeDebugElement!.componentInstance as { onLogicalAssetApplied(change: object): Promise<void> };
    const applying = component.onLogicalAssetApplied({ operation: 'primary', assetId: 'asset', primaryPath: '/outside.jpg', members: [paths[1], '/outside.jpg'] });
    const read = http.expectOne(request => request.url === '/api/photo');
    await router.navigateByUrl('/away');
    read.flush(makePhoto({ path: '/outside.jpg' }));
    await applying;
    expect(router.url).toBe('/away');
  });

  it('reports a failed primary refresh without undoing the committed choice or navigating', async () => {
    await open();
    const notice = vi.spyOn(harness.routeDebugElement!.injector.get(MatSnackBar), 'open').mockReturnValue(snack.open() as never);
    const component = harness.routeDebugElement!.componentInstance as { onLogicalAssetApplied(change: object): Promise<void> };
    const applying = component.onLogicalAssetApplied({ operation: 'primary', assetId: 'asset', primaryPath: '/outside.jpg', members: [paths[1], '/outside.jpg'] });
    http.expectOne(request => request.url === '/api/photo').flush({}, { status: 503, statusText: 'Offline' });
    await applying;
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    expect(notice).toHaveBeenCalledWith('logical_assets.refresh_error', '', { duration: 5000 });
  });

  it('only follows the latest confirmed primary when refreshes complete out of order', async () => {
    await open();
    const component = harness.routeDebugElement!.componentInstance as { onLogicalAssetApplied(change: object): Promise<void> };
    const change = { operation: 'primary', assetId: 'asset', members: [paths[1], '/outside.jpg', paths[0]] };
    const first = component.onLogicalAssetApplied({ ...change, primaryPath: '/outside.jpg' });
    const old = http.expectOne(request => request.url === '/api/photo');
    const second = component.onLogicalAssetApplied({ ...change, primaryPath: paths[0] });
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[0] }));
    await second;
    await membership(null);
    old.flush(makePhoto({ path: '/outside.jpg' }));
    await first;
    expect(router.url).toContain(encodeURIComponent(paths[0]));
  });

  it('invalidates a pending primary refresh across same-component navigation ABA', async () => {
    await open();
    const component = harness.routeDebugElement!.componentInstance as { onLogicalAssetApplied(change: object): Promise<void> };
    const applying = component.onLogicalAssetApplied({ operation: 'primary', assetId: 'asset', primaryPath: '/outside.jpg', members: [paths[1], '/outside.jpg'] });
    const old = http.expectOne(request => request.url === '/api/photo');
    await router.navigate(['/photo'], { queryParams: { path: paths[0] }, state: { photo: makePhoto({ path: paths[0] }) } });
    await membership(null);
    await router.navigate(['/photo'], { queryParams: { path: paths[1] }, state: { photo: makePhoto({ path: paths[1] }) } });
    await membership(null);
    old.flush(makePhoto({ path: '/outside.jpg' }));
    await applying;
    expect(router.url).toContain(encodeURIComponent(paths[1]));
  });

  it('releases the temporary primary row so a later revisit reads current store metadata', async () => {
    await open();
    const component = harness.routeDebugElement!.componentInstance as { onLogicalAssetApplied(change: object): Promise<void> };
    const applying = component.onLogicalAssetApplied({ operation: 'primary', assetId: 'asset', primaryPath: '/outside.jpg', members: [paths[1], '/outside.jpg'] });
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: '/outside.jpg', filename: 'old-primary.jpg' }));
    await applying; await membership(null);
    store.photos.update(photos => photos.map(photo => photo.path === '/outside.jpg' ? { ...photo, filename: 'fresh-primary.jpg' } : photo));
    await router.navigate(['/photo'], { queryParams: { path: paths[1] } }); await membership(null);
    await router.navigate(['/photo'], { queryParams: { path: '/outside.jpg' } }); await membership(null);
    expect(root().querySelector('[data-photo-detail-header]')?.textContent).toContain('fresh-primary.jpg');
  });

  it('ordinary cover opens ordered visible strip; buttons and arrows stay inside stack without pinning or replacing gallery filters', async () => {
    await open();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('2 of 3');
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(3);
    expect(root().querySelector('app-stack-navigator [aria-current="true"]')?.getAttribute('aria-label')).toBe('stacks.open_member b.jpg · 2 of 3');
    expect(store.pinnedPaths()).toBeNull();
    await clickMember('[data-stack-next]', paths[2]);
    expect(button('[data-stack-next]').disabled).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    http.expectNone(request => request.url === '/api/photo');
    await keyboardMember('ArrowLeft', paths[1]);
    await clickMember('[data-stack-prev]', paths[0]);
    expect(button('[data-stack-prev]').disabled).toBe(true);
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 3');
    expect(store.filters().no_gps).toBe('true');
    expect(store.photos().map(photo => photo.path)).toEqual([paths[1], '/outside.jpg']);
    const returned = arrived();
    root().querySelector<HTMLButtonElement>('button[aria-label="photo_detail.back"]')!.click();
    await returned;
    expect(router.url).toBe('/?no_gps=true');
    expect(store.pinnedPaths()).toBeNull();
  });

  it('loads only thumbnails for other members and permits direct thumbnail navigation', async () => {
    await open();
    const stripImages = [...root().querySelectorAll<HTMLImageElement>('[data-stack-thumbnail] img')];
    expect(stripImages.every(image => image.src.includes('/thumbnail?') && image.src.includes('size=96'))).toBe(true);
    expect([...root().querySelectorAll<HTMLImageElement>('img')].filter(image => image.src.includes('/image?'))
      .every(image => decodeURIComponent(image.src).includes(paths[1]))).toBe(true);
    await clickMember('[data-stack-thumbnail]', paths[0]);
    expect(router.url).toContain(encodeURIComponent(paths[0]));
  });

  it.each(['success', 'null', 'error'] as const)('holds measured stack space without stale members until fresh membership %s', async outcome => {
    await open();
    const host = measuredNavigator();
    const read = await pendingMember();
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(0);
    expect(host.style.minHeight).toBe('105px');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    http.expectNone(request => request.url === '/api/photo');
    if (outcome === 'error') read.flush({}, { status: 503, statusText: 'Busy' });
    else read.flush(outcome === 'success' ? stack : null);
    await render();
    expect(host.style.minHeight).toBe('');
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(outcome === 'success' ? 3 : 0);
    if (outcome === 'error') {
      button('[role="alert"] button').click();
      await membership();
      expect(root().querySelector('[data-stack-position]')?.textContent).toContain('3 of 3');
      expect(host.style.minHeight).toBe('');
    }
  });

  it.each(['account', 'revision', 'history', 'assistant', 'pin', 'route'] as const)('releases pending member space after %s invalidation', async reason => {
    await open();
    const host = measuredNavigator();
    const read = await pendingMember();
    expect(host.style.minHeight).toBe('105px');
    if (reason === 'account') auth.status.update(status => ({ ...status!, user_id: 'bob' }));
    else if (reason === 'revision') TestBed.inject(PhotoStackService).revision.update(value => value + 1);
    else if (reason === 'history') store.notifyOrganizationRestored();
    else if (reason === 'assistant') assistantBatches.next({ paths: null });
    else if (reason === 'pin') store.pinnedPaths.set([paths[1]]);
    else await router.navigateByUrl('/away');
    await initialPhoto();
    if (reason === 'route') expect(root().querySelector('app-stack-navigator')).toBeNull();
    else expect(host.style.minHeight).toBe('');
    if (reason !== 'pin') expect(read.cancelled).toBe(true);
    http.match(request => request.url === '/api/stacks/by-photo').filter(request => !request.cancelled).forEach(request => request.flush(null));
  });

  it.each(['/outside.jpg', paths[2]])('does not reserve stack space for nonmember or pin-excluded target %s', async target => {
    if (target === paths[2]) store.pinnedPaths.set([paths[1]]);
    await open();
    const host = measuredNavigator();
    await router.navigate(['/photo'], { queryParams: { path: target }, state: { photo: makePhoto({ path: target }) } });
    await initialPhoto();
    const reads = http.match(request => request.url === '/api/stacks/by-photo').filter(request => !request.cancelled);
    expect(reads).toHaveLength(1);
    const [read] = reads;
    expect(read.request.params.get('path')).toBe(target);
    expect(host.style.minHeight).toBe('');
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
    read.flush(null);
    await render();
  });

  it.each(['cancel', 'error'] as const)('releases measured space when a guarded member navigation ends with %s, then reloads the current membership', async outcome => {
    await open();
    const host = measuredNavigator();
    const release = new Subject<boolean>();
    let entered!: () => void;
    const guardEntered = new Promise<void>(resolve => { entered = resolve; });
    const route = router.config.find(route => route.path === 'photo')!;
    route.canActivate = [() => { entered(); return release; }];
    route.runGuardsAndResolvers = 'always';
    const component = harness.routeDebugElement!.componentInstance as InstanceType<typeof PhotoDetailComponent>;
    const opening = vi.spyOn(component as unknown as { openSetMember(path: string): Promise<void> }, 'openSetMember');
    button('[data-stack-next]').click();
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[2] }));
    await guardEntered;
    harness.detectChanges();
    sideData();
    expect(host.style.minHeight).toBe('105px');
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    http.expectNone(request => request.url === '/api/photo');
    if (outcome === 'error') release.error(new Error('guard failed'));
    else { release.next(false); release.complete(); }
    await opening.mock.results[0].value;
    await initialPhoto();
    expect(host.style.minHeight).toBe('');
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    const read = http.expectOne(request => request.url === '/api/stacks/by-photo');
    expect(read.request.params.get('path')).toBe(paths[1]);
    read.flush(stack);
    await render();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('2 of 3');
  });

  it('drops a reserved target when another navigation supersedes its pending guard', async () => {
    await open();
    const host = measuredNavigator();
    const release = new Subject<boolean>();
    let entered!: () => void;
    const guardEntered = new Promise<void>(resolve => { entered = resolve; });
    const route = router.config.find(route => route.path === 'photo')!;
    route.canActivate = [snapshot => {
      if (snapshot.queryParamMap.get('path') !== paths[2]) return true;
      entered(); return release;
    }];
    route.runGuardsAndResolvers = 'always';
    button('[data-stack-next]').click();
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[2] }));
    await guardEntered;
    harness.detectChanges();
    expect(host.style.minHeight).toBe('105px');
    await router.navigate(['/photo'], { queryParams: { path: paths[0] }, state: { photo: makePhoto({ path: paths[0] }) } });
    await initialPhoto();
    expect(host.style.minHeight).toBe('');
    const reads = http.match(request => request.url === '/api/stacks/by-photo').filter(request => !request.cancelled);
    expect(reads).toHaveLength(1);
    const [read] = reads;
    expect(read.request.params.get('path')).toBe(paths[0]);
    release.next(true); release.complete();
    read.flush(stack);
    await render();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 3');
    expect(host.style.minHeight).toBe('');
  });

  it('reserves only the visible pinned intersection in a read-only stack and still refreshes membership', async () => {
    auth.status.update(status => ({ ...status!, edition_enabled: false, edition_authenticated: false }));
    store.pinnedPaths.set([paths[1], paths[2]]);
    await open();
    const host = measuredNavigator();
    expect(root().querySelector('[data-stack-manage]')).toBeNull();
    const read = await pendingMember();
    expect(host.style.minHeight).toBe('105px');
    read.flush({ ...stack, editable: false });
    await render();
    expect(host.style.minHeight).toBe('');
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('2 of 2');
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(2);
    expect(store.pinnedPaths()).toEqual([paths[1], paths[2]]);
  });

  it.each([true, false])('read-only=%s and partial stacks expose only returned members and no manage control', async readOnly => {
    if (readOnly) auth.status.update(status => ({ ...status!, edition_authenticated: false, user_role: 'viewer' }));
    await router.navigate(['/photo'], { queryParams: { path: paths[1] }, state: { photo: makePhoto({ path: paths[1] }) } });
    await membership({ ...stack, editable: false, members: stack.members.slice(1) });
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(2);
    expect(root().querySelector('[data-stack-manage]')).toBeNull();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 2');
  });

  it('keyboard Left follows the visible stack instead of the surrounding pinned-list order', async () => {
    const pinned = ['/outside.jpg', paths[1], paths[0], paths[2]];
    store.pinnedPaths.set(pinned);
    store.photos.set(pinned.map(path => makePhoto({ path })));
    await open();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('2 of 3');
    const navigation = arrived();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    http.match(request => request.url === '/api/photo').forEach(request =>
      request.flush(makePhoto({ path: request.request.params.get('path')! })));
    await navigation;
    await membership(router.url.includes(encodeURIComponent('/outside.jpg')) ? null : stack);
    expect(router.url).toContain(encodeURIComponent(paths[0]));
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 3');
    expect(store.pinnedPaths()).toEqual(pinned);
  });

  it('leaves the permitted stack intersection for the adjacent collection entry at its boundary', async () => {
    store.pinnedPaths.set(['/outside.jpg', paths[1], paths[2]]);
    store.photos.set(['/outside.jpg', paths[1], paths[2]].map(path => makePhoto({ path })));
    await open();
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(2);
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 2');
    expect(button('[data-stack-prev]').disabled).toBe(true);
    const navigation = arrived();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    await navigation;
    await membership(null);
    expect(router.url).toContain(encodeURIComponent('/outside.jpg'));
    expect(store.pinnedPaths()).toEqual(['/outside.jpg', paths[1], paths[2]]);
  });

  it('leaves a one-member stack intersection and returns using collection order', async () => {
    store.pinnedPaths.set([paths[1], '/outside.jpg']);
    await open();
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(1);
    expect(button('[data-stack-next]').disabled).toBe(true);
    const outgoing = arrived();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    await outgoing;
    await membership(null);
    expect(router.url).toContain(encodeURIComponent('/outside.jpg'));
    const navigation = arrived();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    await navigation;
    await membership();
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    expect(store.pinnedPaths()).toEqual([paths[1], '/outside.jpg']);
  });

  it('consumes owned arrow events without overriding a control that already handled the key', async () => {
    await open();
    const handled = new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true });
    handled.preventDefault();
    document.dispatchEvent(handled);
    http.expectNone(request => request.url === '/api/photo');
    const navigation = arrived();
    const arrow = new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true });
    document.dispatchEvent(arrow);
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[0] }));
    await navigation;
    await membership();
    expect(arrow.defaultPrevented).toBe(true);
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 3');
  });

  it.each([['not in any stack', 'none'], ['a failed lookup', 'error']])('leaves the arrows to the gallery for a photo with %s', async (_label, mode) => {
    await router.navigate(['/photo'], { queryParams: { path: paths[1] }, state: { photo: makePhoto({ path: paths[1] }) } });
    await initialPhoto();
    const reads = http.match(request => request.url === '/api/stacks/by-photo');
    reads.forEach(request => mode === 'error' ? request.flush('x', { status: 500, statusText: 'err' }) : request.flush(null));
    await render();
    const arrow = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
    document.dispatchEvent(arrow);
    await render();
    expect(router.url).toContain(encodeURIComponent('/outside.jpg'));
  });

  it.each([['an unstacked photo', undefined, true], ['a stacked photo', 'stack-1', false]])(
    'while the stack lookup is pending, leaves the arrows to the gallery only for %s', async (_label, stackId, leaves) => {
      await router.navigate(['/photo'], { queryParams: { path: paths[1] }, state: { photo: makePhoto({ path: paths[1], stack_id: stackId }) } });
      harness.detectChanges();
      http.match(request => request.url === '/api/photo').forEach(request => request.flush(makePhoto({ path: paths[1], stack_id: stackId })));
      await render();
      const arrow = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
      document.dispatchEvent(arrow);
      await render();
      expect(router.url.includes(encodeURIComponent('/outside.jpg'))).toBe(leaves);
      http.match(request => request.url === '/api/stacks/by-photo').filter(request => !request.cancelled).forEach(request => request.flush(null));
    });

  it('failure keeps current photo and allows retry; rejected router navigation also preserves it', async () => {
    await open();
    const failed = vi.spyOn(harness.routeDebugElement!.injector.get(MatSnackBar), 'open').mockReturnValue(snack.open() as never);
    button('[data-stack-next]').click();
    http.expectOne(request => request.url === '/api/photo').flush({}, { status: 503, statusText: 'Busy' });
    await render();
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    expect(failed).toHaveBeenCalled();
    await clickMember('[data-stack-next]', paths[2]);
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('3 of 3');
    router.resetConfig([{ path: '', component: SourceComponent }, { path: 'photo', component: PhotoDetailComponent, canActivate: [() => false], runGuardsAndResolvers: 'always' }]);
    const navigation = vi.spyOn(router, 'navigate');
    button('[data-stack-prev]').click();
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[1] }));
    await render();
    await navigation.mock.results[0].value;
    expect(router.url).toContain(encodeURIComponent(paths[2]));
    await membership();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('3 of 3');
  });

  it('stack read failure is visible and reload retries the authorized by-photo endpoint', async () => {
    await router.navigate(['/photo'], { queryParams: { path: paths[1] }, state: { photo: makePhoto({ path: paths[1] }) } });
    await initialPhoto();
    http.expectOne(request => request.url === '/api/stacks/by-photo').flush({}, { status: 503, statusText: 'Busy' });
    await render();
    expect(root().querySelector('[role="alert"]')?.textContent).toContain('stacks.error');
    button('[role="alert"] button').click();
    await membership();
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(3);
  });

  it.each(['account', 'route'] as const)('does not navigate on stale member completion after %s changes', async reason => {
    await open();
    button('[data-stack-next]').click();
    const request = http.expectOne(request => request.url === '/api/photo');
    if (reason === 'account') auth.status.update(status => ({ ...status!, user_id: 'bob' }));
    else await router.navigateByUrl('/away');
    request.flush(makePhoto({ path: paths[2] }));
    await render();
    expect(router.url).not.toContain(encodeURIComponent(paths[2]));
    if (reason === 'account') expect(root().querySelector('[data-stack-navigator]')).toBeNull();
  });

  it('cancels in-flight membership reads on route and account changes, including returning to the same path', async () => {
    await router.navigate(['/photo'], { queryParams: { path: paths[1] }, state: { photo: makePhoto({ path: paths[1] }) } });
    await initialPhoto();
    const read = http.expectOne(request => request.url === '/api/stacks/by-photo');
    await router.navigateByUrl('/away');
    expect(read.cancelled).toBe(true);
    await open();
    const refreshing = TestBed.inject(PhotoStackService);
    refreshing.revision.update(value => value + 1);
    harness.detectChanges();
    const secondRead = http.expectOne(request => request.url === '/api/stacks/by-photo');
    auth.status.update(status => ({ ...status!, user_id: 'bob' }));
    harness.detectChanges();
    expect(secondRead.cancelled).toBe(true);
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
    http.expectNone(request => request.url === '/api/stacks/by-photo');
  });

  it('rejects old membership completion immediately after retry or navigation starts, before effects clean up', async () => {
    await router.navigate(['/photo'], { queryParams: { path: paths[1] } });
    await initialPhoto();
    sideData();
    const navigator = harness.routeDebugElement!.query(By.directive(StackNavigatorComponent)).componentInstance as StackNavigatorComponent;
    const oldRead = http.expectOne(request => request.url === '/api/stacks/by-photo');
    navigator.retry();
    oldRead.flush(stack);
    expect(navigator.stack()).toBeNull();
    harness.detectChanges();
    const retryRead = http.expectOne(request => request.url === '/api/stacks/by-photo');
    const navigation = router.events.pipe(filter(event => event instanceof NavigationStart), take(1)).subscribe(() => {
      retryRead.flush(stack);
      expect(navigator.stack()).toBeNull();
    });
    await router.navigateByUrl('/away');
    navigation.unsubscribe();
  });

  it('does not consume the previous account member cache after an account switch during pending router guards', async () => {
    await open();
    const release = new Subject<boolean>();
    let entered!: () => void;
    const guardEntered = new Promise<void>(resolve => { entered = resolve; });
    const route = router.config.find(route => route.path === 'photo')!;
    route.canActivate = [() => { entered(); return release; }];
    route.runGuardsAndResolvers = 'always';
    const component = harness.routeDebugElement!.componentInstance as InstanceType<typeof PhotoDetailComponent>;
    const opening = vi.spyOn(component as unknown as { openSetMember(path: string): Promise<void> }, 'openSetMember');
    button('[data-stack-next]').click();
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[2] }));
    await guardEntered;
    auth.status.update(status => ({ ...status!, user_id: 'bob' }));
    release.next(true); release.complete();
    await opening.mock.results[0].value;
    await render();
    expect(component.photo()?.path).not.toBe(paths[2]);
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
    http.expectNone(request => request.url === '/api/photo');
  });

  it.each([null, paths])('rechecks current pin %j when a pending member response completes', async initial => {
    store.pinnedPaths.set(initial);
    await open();
    button('[data-stack-next]').click();
    const request = http.expectOne(request => request.url === '/api/photo');
    store.pinnedPaths.set([paths[1], '/outside.jpg']);
    request.flush(makePhoto({ path: paths[2] }));
    await render();
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    expect((harness.routeDebugElement!.componentInstance as InstanceType<typeof PhotoDetailComponent>).photo()?.path).toBe(paths[1]);
    expect(store.pinnedPaths()).toEqual([paths[1], '/outside.jpg']);
    http.expectNone(request => request.url === '/api/stacks/by-photo');
  });

  it('still opens a member when a changed current pin permits it', async () => {
    await open();
    const navigation = arrived();
    button('[data-stack-next]').click();
    const request = http.expectOne(request => request.url === '/api/photo');
    store.pinnedPaths.set([paths[1], paths[2]]);
    request.flush(makePhoto({ path: paths[2] }));
    await navigation;
    await membership();
    expect(router.url).toContain(encodeURIComponent(paths[2]));
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('2 of 2');
  });

  it.each([null, paths])('does not commit a member excluded from pin %j while router guards are pending', async initial => {
    store.pinnedPaths.set(initial);
    await open();
    const release = new Subject<boolean>();
    let entered!: () => void;
    const guardEntered = new Promise<void>(resolve => { entered = resolve; });
    const route = router.config.find(route => route.path === 'photo')!;
    route.canActivate = [() => { entered(); return release; }];
    route.runGuardsAndResolvers = 'always';
    const component = harness.routeDebugElement!.componentInstance as InstanceType<typeof PhotoDetailComponent>;
    const opening = vi.spyOn(component as unknown as { openSetMember(path: string): Promise<void> }, 'openSetMember');
    button('[data-stack-next]').click();
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[2] }));
    await guardEntered;
    store.pinnedPaths.set([paths[1], '/outside.jpg']);
    release.next(true); release.complete();
    await opening.mock.results[0].value;
    await render();
    http.match(request => request.url === '/api/stacks/by-photo').forEach(request => { if (!request.cancelled) request.flush(stack); });
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    expect(component.photo()?.path).toBe(paths[1]);
    expect(store.pinnedPaths()).toEqual([paths[1], '/outside.jpg']);
  });

  it('hides stack navigation when current allowlist excludes the active photo and restores it when included', async () => {
    await open();
    for (const allowed of [[paths[2]], [], ['/outside.jpg']]) {
      store.pinnedPaths.set(allowed);
      await render();
      expect(root().querySelector('[data-stack-navigator]')).toBeNull();
      expect(root().textContent).not.toContain('0 of');
    }
    store.pinnedPaths.set([paths[1], paths[2]]);
    await render();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 2');
    expect(button('[data-stack-next]').disabled).toBe(false);
    store.pinnedPaths.set(null);
    await render();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('2 of 3');
  });

  it('keeps the viewer open when Escape closes Manage, then Escape returns to its source gallery', async () => {
    await open();
    const navigatorElement = harness.routeDebugElement!.query(By.directive(StackNavigatorComponent));
    const manage = vi.spyOn(navigatorElement.componentInstance as StackNavigatorComponent, 'manage');
    const dialog = navigatorElement.injector.get(MatDialog);
    const opened = vi.spyOn(dialog, 'open');
    button('[data-stack-manage]').click(); await manage.mock.results[0].value;
    harness.detectChanges(); http.expectOne('/api/stacks/s1').flush(stack); await render();
    const closedOrNavigation = firstValueFrom(merge(opened.mock.results[0].value.afterClosed(), router.events.pipe(filter(event => event instanceof NavigationEnd))).pipe(take(1)));
    const escape = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true });
    document.body.dispatchEvent(escape);
    await closedOrNavigation;
    await harness.fixture.whenStable();
    expect(escape.defaultPrevented).toBe(true);
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    await membership();
    const navigation = arrived();
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true }));
    await navigation;
    expect(router.url).toBe('/?no_gps=true');
  });

  it('rechecks a pin changed during guarded editor member navigation', async () => {
    await open();
    const navigatorElement = harness.routeDebugElement!.query(By.directive(StackNavigatorComponent));
    const manage = vi.spyOn(navigatorElement.componentInstance as StackNavigatorComponent, 'manage');
    const opened = vi.spyOn(navigatorElement.injector.get(MatDialog), 'open');
    button('[data-stack-manage]').click(); await manage.mock.results[0].value;
    harness.detectChanges(); http.expectOne('/api/stacks/s1').flush(stack); await render();
    const editor = opened.mock.results[0].value.componentInstance.editor();
    const opening = vi.spyOn(editor, 'openMember');
    const release = new Subject<boolean>();
    let entered!: () => void;
    const guardEntered = new Promise<void>(resolve => { entered = resolve; });
    const route = router.config.find(route => route.path === 'photo')!;
    route.canActivate = [() => { entered(); return release; }];
    route.runGuardsAndResolvers = 'always';
    document.querySelector<HTMLButtonElement>('app-stack-dialog button[data-stack-focus="/c.jpg"]')!.click();
    await render();
    document.querySelector<HTMLButtonElement>('app-stack-dialog button[aria-label="stacks.open_member /c.jpg"]')!.click();
    http.expectOne(request => request.url === '/api/photo').flush(makePhoto({ path: paths[2] }));
    await guardEntered;
    store.pinnedPaths.set([paths[1]]);
    release.next(true); release.complete();
    await opening.mock.results[0].value;
    await render();
    http.match(request => request.url === '/api/stacks/by-photo').forEach(request => { if (!request.cancelled) request.flush(stack); });
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    expect(store.pinnedPaths()).toEqual([paths[1]]);
  });

  it('typing, dialogs, overlays, modifiers and slideshow suppress arrow shortcuts', async () => {
    await open();
    const input = document.createElement('input');
    root().append(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    input.remove();
    const overlay = document.createElement('mat-dialog-container');
    document.body.append(overlay);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    overlay.remove();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', ctrlKey: true, bubbles: true }));
    store.slideshowActive.set(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    http.expectNone(request => request.url === '/api/photo');
  });

  it.each([null, [paths[0]]])('refreshes the same-path strip after assistant stack or member changes (%s)', async changedPaths => {
    await open();
    assistantBatches.next({ paths: changedPaths });
    await membership({ ...stack, revision: 2, members: stack.members.slice(1) });
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(2);
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 2');
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    assistantBatches.next({ paths: null });
    await membership(null);
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
  });

  it.each([null, [paths[0]]])('ignores unrelated rows after loading and refuses a stale membership reply after assistant changes (%s)', async changedPaths => {
    await open();
    assistantBatches.next({ paths: ['/unrelated.jpg'] });
    await initialPhoto();
    http.expectNone(request => request.url === '/api/stacks/by-photo');
    const navigator = harness.routeDebugElement!.query(By.directive(StackNavigatorComponent)).componentInstance as StackNavigatorComponent;
    navigator.retry(); harness.detectChanges();
    const oldRead = http.expectOne(request => request.url === '/api/stacks/by-photo');
    assistantBatches.next({ paths: changedPaths });
    oldRead.flush(stack);
    expect(navigator.stack()).toBeNull();
    await membership(null);
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
  });

  it('reloads the visible stack after a shell history restore, including when the restore dissolves it', async () => {
    await open();
    store.notifyOrganizationRestored();
    await membership({ ...stack, revision: 2, members: stack.members.slice(1) });
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(2);
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 2');
    await clickMember('[data-stack-next]', paths[2]);
    store.notifyOrganizationRestored();
    await membership(null);
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
    expect(router.url).toContain(encodeURIComponent(paths[2]));
  });

  it('rejects a pre-restore membership response immediately and cancels replacement reads after an account change', async () => {
    await router.navigate(['/photo'], { queryParams: { path: paths[1] } });
    await initialPhoto();
    const navigator = harness.routeDebugElement!.query(By.directive(StackNavigatorComponent)).componentInstance as StackNavigatorComponent;
    const oldRead = http.expectOne(request => request.url === '/api/stacks/by-photo');
    store.notifyOrganizationRestored();
    oldRead.flush(stack);
    expect(navigator.stack()).toBeNull();
    await initialPhoto();
    const freshRead = http.expectOne(request => request.url === '/api/stacks/by-photo');
    auth.status.update(status => ({ ...status!, user_id: 'bob' }));
    store.notifyOrganizationRestored();
    await initialPhoto();
    expect(freshRead.cancelled).toBe(true);
    expect(root().querySelector('[data-stack-navigator]')).toBeNull();
    http.expectNone(request => request.url === '/api/stacks/by-photo');
  });

  it('manages separately and reloads permitted membership after close and Undo revision', async () => {
    await open();
    const navigatorElement = harness.routeDebugElement!.query(By.directive(StackNavigatorComponent));
    const dialog = navigatorElement.injector.get(MatDialog);
    const manage = vi.spyOn(navigatorElement.componentInstance as StackNavigatorComponent, 'manage');
    const opened = vi.spyOn(dialog, 'open');
    button('[data-stack-manage]').click();
    await manage.mock.results[0].value;
    expect(opened).toHaveBeenCalled();
    harness.detectChanges();
    http.expectOne('/api/stacks/s1').flush(stack);
    await render();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    http.expectNone(request => request.url === '/api/photo');
    const closed = firstValueFrom(opened.mock.results[0].value.afterClosed());
    dialog.closeAll();
    await closed;
    await membership();
    TestBed.inject(PhotoStackService).revision.update(value => value + 1);
    await membership({ ...stack, revision: 2, members: stack.members.slice(1) });
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(2);
  });
});
