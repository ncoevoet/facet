import { StackNavigatorComponent } from './stack-navigator.component';
import { By } from '@angular/platform-browser';
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
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', t: (key: string, params?: Record<string, unknown>) => key === 'stacks.browse_position' ? params?.['position'] + ' of ' + params?.['count'] : key === 'stacks.open_member' ? key + ' ' + params?.['path'] : key } },
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

  it('ordinary cover opens ordered visible strip; buttons and arrows stay inside stack without pinning or replacing gallery filters', async () => {
    await open();
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('2 of 3');
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(3);
    expect(root().querySelector('[aria-current="true"]')?.getAttribute('aria-label')).toContain(paths[1]);
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

  it('keeps both keyboard arrows bounded to the permitted stack intersection of an exact list', async () => {
    store.pinnedPaths.set(['/outside.jpg', paths[1], paths[2]]);
    store.photos.set(['/outside.jpg', paths[1], paths[2]].map(path => makePhoto({ path })));
    await open();
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(2);
    expect(root().querySelector('[data-stack-position]')?.textContent).toContain('1 of 2');
    expect(button('[data-stack-prev]').disabled).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    http.expectNone(request => request.url === '/api/photo');
    await render();
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    await keyboardMember('ArrowRight', paths[2]);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    http.expectNone(request => request.url === '/api/photo');
    expect(router.url).toContain(encodeURIComponent(paths[2]));
    expect(store.pinnedPaths()).toEqual(['/outside.jpg', paths[1], paths[2]]);
  });

  it('keeps a one-member stack intersection bounded while ordinary nonstack photos use pinned-list order', async () => {
    store.pinnedPaths.set([paths[1], '/outside.jpg']);
    await open();
    expect(root().querySelectorAll('[data-stack-thumbnail]')).toHaveLength(1);
    expect(button('[data-stack-next]').disabled).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    http.expectNone(request => request.url === '/api/photo');
    await render();
    expect(router.url).toContain(encodeURIComponent(paths[1]));
    // An explicitly opened nonstack photo still follows the exact list.
    await router.navigate(['/photo'], { queryParams: { path: '/outside.jpg' } });
    await membership(null);
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
