import { HttpContext, provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { HANDLE_PLACE_SEARCH_ERRORS_LOCALLY } from '../../core/utils/place-search-error.util';
import { errorInterceptor } from '../../core/interceptors/error.interceptor';
import { retryInterceptor } from '../../core/interceptors/retry.interceptor';
import { signal } from '@angular/core';
import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NEVER, of, throwError, Subject } from 'rxjs';
import { GalleryStore } from '../gallery/gallery.store';
import { Router, ActivatedRoute, NavigationStart } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService } from '../../core/services/album.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import type { GpsEditDialogComponent, GpsEditDialogData, SavedPlace } from './gps-edit-dialog.component';

// Mock Leaflet via vi.doMock + dynamic import: the unit-test builder wraps
// spec modules, which defeats vi.mock hoisting and can leak the real Leaflet. The
// shared singleton makes every leaflet-using spec's registry binding identical.
import { leafletMock, leafletMockMap } from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);

describe('GpsEditDialogComponent', () => {
  let GpsEditDialogComponentClass: typeof GpsEditDialogComponent;
  let component: GpsEditDialogComponent;
  let mockDialogRef: { close: Mock; beforeClosed: Mock };
  let mockApi: { put: Mock; get: Mock; post: Mock; delete: Mock };
  let mockStore: { patchPhoto: Mock; filters: Mock; loadPhotos: Mock; refreshPaths: Mock; config: Mock };
  let mockSnackBar: { open: Mock };
  const navigation = new Subject<NavigationStart>();
  const closing = new Subject<void>();
  const authStatus = signal({ authenticated: true, edition_authenticated: true, user_id: 'editor' });
  const identity = () => `${authStatus().authenticated ? 1 : 0}|${authStatus().user_id}`;
  let fixture: ComponentFixture<GpsEditDialogComponent>;

  beforeAll(async () => {
    ({ GpsEditDialogComponent: GpsEditDialogComponentClass } = await import('./gps-edit-dialog.component'));
  });

  function createComponent(data: GpsEditDialogData, render = false, places: SavedPlace[] = []) {
    TestBed.resetTestingModule();
    authStatus.set({ authenticated: true, edition_authenticated: true, user_id: 'editor' });
    mockDialogRef = { close: vi.fn(), beforeClosed: vi.fn(() => closing) };
    mockApi = { put: vi.fn(() => of({ gps_latitude: data.lat, gps_longitude: data.lng })), get: vi.fn(() => of({ places, recent: [] })), post: vi.fn(), delete: vi.fn() };
    mockStore = { patchPhoto: vi.fn(), filters: vi.fn(() => ({ no_gps: '' })), loadPhotos: vi.fn(), refreshPaths: vi.fn(), config: vi.fn(() => ({ place_search_enabled: true })) };
    mockSnackBar = { open: vi.fn() };

    TestBed.configureTestingModule({
      imports: [GpsEditDialogComponentClass],
      providers: [
        GpsEditDialogComponentClass,
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: Router, useValue: { url: '/', events: navigation } },
        { provide: MAT_DIALOG_DATA, useValue: data },
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: { identity, status: authStatus, isEdition: () => authStatus().edition_authenticated } },
        { provide: GalleryStore, useValue: mockStore },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
    TestBed.overrideProvider(MatSnackBar, { useValue: mockSnackBar });
    if (render) {
      fixture = TestBed.createComponent(GpsEditDialogComponentClass);
      component = fixture.componentInstance;
      fixture.detectChanges();
    } else component = TestBed.inject(GpsEditDialogComponentClass);
  }

  describe('online lookup with the real API and error/retry interceptors', () => {
    let http: HttpTestingController;
    let events: Subject<NavigationStart>;
    let logout: Mock;
    let revalidate: Mock;

    beforeEach(async () => {
      TestBed.resetTestingModule();
      authStatus.set({ authenticated: true, edition_authenticated: true, user_id: 'editor' });
      events = new Subject(); logout = vi.fn(); revalidate = vi.fn(() => Promise.resolve(null));
      mockSnackBar = { open: vi.fn() };
      TestBed.configureTestingModule({ imports: [GpsEditDialogComponentClass], providers: [
        provideHttpClient(withXhr(), withInterceptors([errorInterceptor, retryInterceptor])), provideHttpClientTesting(),
        { provide: MAT_DIALOG_DATA, useValue: { path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null } },
        { provide: MatDialogRef, useValue: { close: vi.fn(), beforeClosed: () => NEVER } },
        { provide: Router, useValue: { url: '/', events } },
        { provide: AuthService, useValue: { identity, status: authStatus, isEdition: () => authStatus().edition_authenticated, logout, revalidate } },
        { provide: GalleryStore, useValue: { patchPhoto: vi.fn(), filters: () => ({ no_gps: '' }), config: () => ({ place_search_enabled: true }) } },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      ] });
      TestBed.overrideProvider(MatSnackBar, { useValue: mockSnackBar });
      http = TestBed.inject(HttpTestingController);
      fixture = TestBed.createComponent(GpsEditDialogComponentClass);
      component = fixture.componentInstance;
      http.expectOne('/api/places').flush({ places: [], recent: [] });
      fixture.detectChanges(); await fixture.whenStable();
      component.setOnlineQuery('Private address');
    });
    afterEach(() => { fixture.destroy(); http.verify({ ignoreCancelled: true }); });
    const request = () => http.expectOne(req => req.url === '/api/places/search');

    it.each([
      ['one non-BMP', '😀', false], ['two non-BMP', '😀😀', false], ['three non-BMP', '😀😀😀', true],
      ['two BMP', 'ab', false], ['three BMP', 'abc', true],
      ['200 mixed codepoints', 'a'.repeat(199) + '😀', true],
      ['200 non-BMP codepoints', '😀'.repeat(200), true], ['201 non-BMP codepoints', '😀'.repeat(201), false],
    ] as const)('matches the HTTP query boundary for %s', async (_name, query, valid) => {
      component.setOnlineQuery(query); fixture.detectChanges();
      expect(component.onlineQueryValid()).toBe(valid);
      if (valid) {
        const input = fixture.nativeElement.querySelector('input[type="search"][maxlength]') as HTMLInputElement;
        expect(input.maxLength).toBeGreaterThanOrEqual(query.length);
      }
      const task = component.searchOnline();
      if (valid) {
        const lookup = request(); expect(lookup.request.params.get('q')).toBe(query);
        lookup.flush({ results: [] });
      } else http.expectNone(req => req.url === '/api/places/search');
      await task;
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    it.each([
      [429, 'Wait before searching again'], [502, 'Online place search is unavailable'], [503, 'Online place search is disabled'],
    ])('handles expected %s inline without a global toast or private crash report', async (status, detail) => {
      const task = component.searchOnline();
      const lookup = request();
      expect(lookup.request.params.get('q')).toBe('Private address');
      lookup.flush({ detail }, { status: status as number, statusText: 'Lookup refused' });
      await task; fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent).toContain('photo_detail.gps.online_error');
      expect(mockSnackBar.open).not.toHaveBeenCalled();
      expect(logout).not.toHaveBeenCalled(); expect(revalidate).not.toHaveBeenCalled();
      http.expectNone('/api/client-errors');
      http.expectNone(req => req.url === '/api/places/search');
    });

    it.each([[500, 'Unexpected fault'], [502, 'Unexpected gateway response']])('still reports unexpected %s failures without the private query', async (status, detail) => {
      const task = component.searchOnline();
      request().flush({ detail }, { status: status as number, statusText: 'Unexpected failure' });
      const report = http.expectOne('/api/client-errors');
      expect(JSON.stringify(report.request.body)).not.toContain('Private address');
      expect(report.request.body.extra).toEqual({ request_url: '/api/places/search', request_method: 'GET', status });
      report.flush({}); await task;
      expect(mockSnackBar.open).toHaveBeenCalledWith('errors.server_error', '', expect.anything());
    });

    it.each([401, 403])('preserves global authentication handling for %s', async status => {
      const task = component.searchOnline();
      request().flush({ detail: 'Access denied' }, { status, statusText: 'Authentication refused' });
      await task; await fixture.whenStable();
      if (status === 401) expect(logout).toHaveBeenCalledOnce();
      else { expect(revalidate).toHaveBeenCalledOnce(); expect(mockSnackBar.open).toHaveBeenCalled(); }
      http.expectNone('/api/client-errors');
    });

    it('keeps the default global behavior for an API lookup without a local handler', () => {
      TestBed.inject(ApiService).get('/places/search', { q: 'Private address' }).subscribe({ error: () => {} });
      request().flush({ detail: 'Online place search is disabled' }, { status: 503, statusText: 'Disabled' });
      http.expectOne('/api/client-errors').flush({});
      expect(mockSnackBar.open).toHaveBeenCalledWith('errors.server_error', '', expect.anything());
    });

    it('does not suppress another endpoint even when the local lookup context is reused', () => {
      const context = new HttpContext().set(HANDLE_PLACE_SEARCH_ERRORS_LOCALLY, true);
      TestBed.inject(ApiService).get('/photos', {}, context).subscribe({ error: () => {} });
      http.expectOne('/api/photos').flush({ detail: 'Wait before searching again' }, { status: 429, statusText: 'Throttled' });
      http.expectNone('/api/client-errors');
      expect(mockSnackBar.open).toHaveBeenCalledWith('errors.rate_limited', '', expect.anything());
    });

    it('allows an explicit retry after a handled failure without automatic HTTP retries', async () => {
      const first = component.searchOnline();
      request().flush({ detail: 'Online place search is unavailable' }, { status: 502, statusText: 'Unavailable' });
      await first;
      http.expectNone('/api/client-errors');
      http.expectNone(req => req.url === '/api/places/search');
      const retry = component.searchOnline();
      request().flush({ results: [{ label: 'Result', latitude: 1, longitude: 2 }] });
      await retry;
      expect(component.onlineError()).toBe('');
      expect(component.onlineResults()).toEqual([{ label: 'Result', latitude: 1, longitude: 2 }]);
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    const onlineInput = (): HTMLInputElement => fixture.nativeElement.querySelector('input[aria-describedby="gps-online-notice"]');

    it('describes the query by the privacy notice', () => {
      expect(onlineInput().getAttribute('aria-describedby')).toBe('gps-online-notice');
      expect(fixture.nativeElement.querySelector('#gps-online-notice')).not.toBeNull();
    });

    it('keeps the result-count live region in the DOM before any search', () => {
      const regions = [...fixture.nativeElement.querySelectorAll('[role="status"].sr-only')] as HTMLElement[];
      expect(regions.length).toBe(1);
      expect(regions[0].textContent?.trim()).toBe('');
    });

    it.each([
      [1, 'photo_detail.gps.online_results'], [2, 'photo_detail.gps.online_results_plural'],
    ] as const)('searches on Enter and announces %i result(s) in a named list', async (count, key) => {
      onlineInput().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
      request().flush({ results: Array.from({ length: count }, (_, i) => ({ label: `P${i}`, latitude: i, longitude: i })) });
      await vi.waitFor(() => expect(component.onlineResults().length).toBe(count));
      fixture.detectChanges();
      const list: HTMLElement = fixture.nativeElement.querySelector('ul[aria-label="photo_detail.gps.online_results_label"]');
      expect(list.querySelectorAll('li').length).toBe(count);
      const region: HTMLElement = fixture.nativeElement.querySelector('[role="status"].sr-only');
      expect(region.textContent).toContain(key);
    });

    it('does not search on the Enter that commits an IME composition', () => {
      onlineInput().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true }));
      http.expectNone(req => req.url === '/api/places/search');
    });

    it('does not search on the Enter Safari sends after committing an IME candidate', () => {
      onlineInput().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229 }));
      http.expectNone(req => req.url === '/api/places/search');
    });

    it('cancels an obsolete lookup on real navigation without reporting a failure', async () => {
      const pending = component.searchOnline(); const lookup = request();
      events.next(new NavigationStart(1, '/other'));
      expect(lookup.cancelled).toBe(true);
      await pending;
      expect(component.onlineError()).toBe('');
      expect(mockSnackBar.open).not.toHaveBeenCalled();
      http.expectNone('/api/client-errors');
    });
  });

  it('invalidates a visible batch preview and saved places when ownership is lost', async () => {
    createComponent({ path: '', filename: '', lat: 1, lng: 2, batch: { photo_paths: ['/alice'] } });
    mockApi.post.mockReturnValue(of({ changed: 1, skipped: 0, preview_token: 't' }));
    await component.previewBatch();
    authStatus.set({ authenticated: true, edition_authenticated: true, user_id: 'bob' });
    TestBed.tick();
    expect(component.batchPreview()).toBeNull(); expect(component.places()).toEqual([]);
    mockApi.post.mockClear(); await component.save(); await component.previewBatch(); await component.createPlace();
    expect(mockApi.post).not.toHaveBeenCalled();
  });
  it('keeps the dialog open when the same session is revalidated into a new status object', async () => {
    createComponent({ path: '', filename: '', lat: 1, lng: 2, batch: { photo_paths: ['/alice'] } });
    mockApi.post.mockReturnValue(of({ changed: 1, skipped: 0, preview_token: 't' }));
    await component.previewBatch();
    authStatus.set({ ...authStatus() });
    TestBed.tick();
    expect(mockDialogRef.close).not.toHaveBeenCalled();
    expect(component.batchPreview()).not.toBeNull();
  });
  for (const loss of ['identity', 'edition', 'dismissal', 'navigation', 'destroy']) {
    function invalidate() {
      if (loss === 'identity') authStatus.set({ authenticated: true, edition_authenticated: true, user_id: 'bob' });
      if (loss === 'edition') authStatus.set({ authenticated: true, edition_authenticated: false, user_id: 'editor' });
      if (loss === 'dismissal') closing.next();
      if (loss === 'navigation') { navigation.next(new NavigationStart(1, '/other')); navigation.next(new NavigationStart(2, '/')); }
      if (loss === 'destroy') TestBed.resetTestingModule();
    }
    it(`discards batch preview and blocks commands after ${loss}`, async () => {
      createComponent({ path: '', filename: '', lat: 1, lng: 2, batch: { photo_paths: ['/alice'] } });
      const pending = new Subject<unknown>(); mockApi.post.mockReturnValue(pending);
      const task = component.previewBatch();
      invalidate(); pending.next({ changed: 1, skipped: 0, preview_token: 't' }); await task;
      expect(component.batchPreview()).toBeNull();
      mockApi.post.mockReturnValue(of({ changed: 1 })); mockApi.post.mockClear();
      await component.previewBatch(); await component.save(); await component.useFileLocation();
      expect(mockApi.post).not.toHaveBeenCalled(); expect(mockApi.delete).not.toHaveBeenCalled();
    });
    // A plain dismissal or teardown still publishes a write the server committed;
    // only a changed session or page drops it.
    const publishes = loss === 'dismissal' || loss === 'destroy';
    it.each(['batch', 'save', 'reset'])(`${publishes ? 'publishes' : 'suppresses'} late %s writes after ${loss}`, async mode => {
      const applied = vi.fn();
      createComponent({ path: '/alice', filename: '', lat: 1, lng: 2, manuallySet: true,
        ...(mode === 'batch' ? { batch: { photo_paths: ['/alice'] }, onBatchApplied: applied } : {}) });
      mockApi.post.mockReturnValue(of({ changed: 1, skipped: 0, preview_token: 't' }));
      if (mode === 'batch') await component.previewBatch();
      const pending = new Subject<unknown>();
      mockApi.post.mockReturnValue(pending); mockApi.put.mockReturnValue(pending); mockApi.delete.mockReturnValue(pending);
      const task = mode === 'reset' ? component.useFileLocation() : component.save();
      invalidate(); mockDialogRef.close.mockClear();
      pending.next({ changed: 1, gps_latitude: 1, gps_longitude: 2 }); await task;
      expect(mockDialogRef.close).not.toHaveBeenCalled();
      const write = { batch: mockApi.post, save: mockApi.put, reset: mockApi.delete }[mode];
      expect(write).toHaveBeenCalledTimes(mode === 'batch' ? 2 : 1);
      if (mode === 'batch') expect(mockApi.post).toHaveBeenLastCalledWith('/photos/batch_gps', expect.objectContaining({ preview: false, preview_token: 't' }));
      if (publishes) {
        expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(null);
        if (mode !== 'batch') expect(mockStore.patchPhoto).toHaveBeenCalledTimes(1);
        if (mode === 'batch') expect(applied).toHaveBeenCalledTimes(1);
        return;
      }
      expect(mockStore.patchPhoto).not.toHaveBeenCalled(); expect(mockStore.refreshPaths).not.toHaveBeenCalled();
      if (mode === 'batch') expect(applied).not.toHaveBeenCalled();
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });
  }

  it('sends the cleared only-missing flag and the chosen saved place with preview and apply', async () => {
    createComponent({ path: '', filename: 'selection', lat: null, lng: null, batch: { photo_paths: ['/one.jpg'] } });
    component.selectPlace({ id: 7, name: 'Home', latitude: 1, longitude: 2 } as SavedPlace);
    mockApi.post.mockReturnValue(of({ changed: 1, skipped: 0, preview_token: 'token' }));
    await component.previewBatch();
    component.onlyMissing.set(false);
    expect(component.canApplyBatch()).toBe(false);
    await component.previewBatch();
    await component.save();
    const sent = { photo_paths: ['/one.jpg'], only_missing: false, saved_place_id: 7 };
    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_gps', expect.objectContaining({ ...sent, preview: true }));
    expect(mockApi.post).toHaveBeenLastCalledWith('/photos/batch_gps', expect.objectContaining({ ...sent, preview: false, preview_token: 'token' }));
  });

  it('keeps a blank or partial batch draft from previewing or clearing photos', async () => {
    createComponent({ path: '', filename: 'selection', lat: null, lng: null, batch: { photo_paths: ['/partial.jpg'] } });
    expect(component.batchCoordinatesValid()).toBe(false);
    await component.previewBatch();
    await component.save();
    component.setLatitude(1);
    expect(component.batchCoordinatesValid()).toBe(false);
    await component.previewBatch();
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(mockApi.put).not.toHaveBeenCalled();
  });

  it('requires a fresh batch preview, captures its target and publishes a dismissed completion', async () => {
    const target = { photo_paths: ['/one.jpg', '/two.jpg'] };
    const onBatchApplied = vi.fn();
    createComponent({ path: '', filename: 'selection', lat: null, lng: null, batch: target, onBatchApplied });
    component.selectRecent({ latitude: 1, longitude: 2 });
    await component.save();
    expect(mockApi.post).not.toHaveBeenCalled();
    mockApi.post.mockReturnValue(of({ changed: 1, skipped: 1, preview_token: 'token' }));
    await component.previewBatch();
    expect(component.canApplyBatch()).toBe(true);
    component.setLatitude(3);
    expect(component.canApplyBatch()).toBe(false);
    component.setLatitude(1);
    const pending = new Subject<{ changed: number; skipped: number; preview_token: string }>();
    mockApi.post.mockReturnValue(pending);
    const saving = component.save();
    target.photo_paths.push('/later.jpg');
    component.cancel();
    TestBed.resetTestingModule();
    pending.next({ changed: 1, skipped: 1, preview_token: 'token' });
    pending.complete();
    await saving;
    expect(mockApi.post).toHaveBeenLastCalledWith('/photos/batch_gps', expect.objectContaining({
      photo_paths: ['/one.jpg', '/two.jpg'], preview: false, preview_token: 'token', only_missing: true,
    }));
    expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(null);
    expect(mockStore.loadPhotos).not.toHaveBeenCalled();
    expect(onBatchApplied).toHaveBeenCalledTimes(1);
    expect(mockDialogRef.close).toHaveBeenCalledTimes(1);
  });

  it('invalidates a batch preview after apply fails and keeps the draft', async () => {
    createComponent({ path: '', filename: 'selection', lat: null, lng: null, batch: { filters: { no_gps: '1' } } });
    component.selectRecent({ latitude: 1, longitude: 2 });
    mockApi.post.mockReturnValue(of({ changed: 2, skipped: 0, preview_token: 'token' }));
    await component.previewBatch();
    mockApi.post.mockReturnValue(throwError(() => ({ status: 409 })));
    await component.save();
    expect(component.canApplyBatch()).toBe(false);
    expect(component.selectedLat()).toBe(1);
    expect(mockDialogRef.close).not.toHaveBeenCalled();
  });

  const place: SavedPlace = { id: 1, name: 'Home', latitude: 1, longitude: 2 } as SavedPlace;

  it.each(['identity', 'edition', 'navigation'])('closes the dialog and clears the saved places after %s loss', loss => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 }, false, [place]);
    TestBed.tick();
    mockDialogRef.close.mockClear();
    if (loss === 'identity') authStatus.set({ authenticated: true, edition_authenticated: true, user_id: 'bob' });
    if (loss === 'edition') authStatus.set({ authenticated: true, edition_authenticated: false, user_id: 'editor' });
    if (loss === 'navigation') navigation.next(new NavigationStart(1, '/other'));
    TestBed.tick();
    expect(mockDialogRef.close).toHaveBeenCalled();
    expect(component.places()).toEqual([]);
    expect(component.recent()).toEqual([]);
  });

  it('keeps the dialog and an in-flight save when the status is revalidated for the same user', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 });
    TestBed.tick();
    const pending = new Subject<{ gps_latitude: number; gps_longitude: number }>();
    mockApi.put.mockReturnValue(pending);
    const saving = component.save();
    authStatus.set({ authenticated: true, edition_authenticated: true, user_id: 'editor' });
    TestBed.tick();
    pending.next({ gps_latitude: 3, gps_longitude: 4 });
    pending.complete();
    await saving;
    expect(mockDialogRef.close).toHaveBeenCalledExactlyOnceWith({ gps_latitude: 3, gps_longitude: 4 });
  });

  it('searches only explicitly, previews a result, then saves without the previous bookmark', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null });
    component.setOnlineQuery('Berlin');
    expect(mockApi.get).toHaveBeenCalledTimes(1);
    const result = { label: 'Berlin', latitude: 52.5, longitude: 13.4 };
    mockApi.get.mockReturnValue(of({ results: [result] }));
    await component.searchOnline();
    expect(mockApi.get).toHaveBeenLastCalledWith('/places/search', { q: 'Berlin' }, expect.any(HttpContext));
    expect(component.selectedLat()).toBeNull();
    component.selectedPlaceId.set(99);
    component.selectOnlineResult(result);
    expect(component.selectedPlaceId()).toBeNull();
    expect(mockApi.put).not.toHaveBeenCalled();
    await component.save();
    expect(mockApi.put).toHaveBeenCalledWith('/photo/gps', { path: '/photo.jpg', gps_latitude: 52.5, gps_longitude: 13.4 });
    expect(mockStore.refreshPaths).toHaveBeenCalledWith(null);
  });

  it('cancels and discards pending search on query edits, draft edits, dismissal and auth changes', async () => {
    for (const invalidate of ['query', 'draft', 'dismiss', 'auth']) {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 });
      const pending = new Subject<{ results: { label: string; latitude: number; longitude: number }[] }>();
      mockApi.get.mockReturnValue(pending);
      component.setOnlineQuery('Berlin');
      const searching = component.searchOnline();
      if (invalidate === 'query') component.setOnlineQuery('Paris');
      if (invalidate === 'draft') component.setLatitude(7);
      if (invalidate === 'dismiss') component.cancel();
      if (invalidate === 'auth') { authStatus.set({ authenticated: true, edition_authenticated: false, user_id: 'editor' }); TestBed.tick(); }
      expect(pending.observed).toBe(false);
      pending.next({ results: [{ label: 'Old', latitude: 3, longitude: 4 }] });
      await searching;
      expect(component.onlineResults()).toEqual([]);
      expect(mockApi.put).not.toHaveBeenCalled();
    }
  });

  it('keeps offline coordinates and saved places usable after lookup failure and rejects invalid results', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 });
    component.setOnlineQuery('Berlin');
    mockApi.get.mockReturnValue(throwError(() => new Error('offline')));
    await component.searchOnline();
    expect(component.onlineError()).toBeTruthy();
    mockApi.get.mockReturnValue(of({ results: [{ label: 'bad', latitude: NaN, longitude: 2 }, { label: 'Berlin', latitude: 52, longitude: 13 }] }));
    await component.searchOnline();
    expect(component.onlineResults()).toEqual([{ label: 'Berlin', latitude: 52, longitude: 13 }]);
    expect(component.selectedLat()).toBe(1);
    component.selectRecent({ latitude: 0, longitude: 0 });
    expect(component.selectedLat()).toBe(0);
  });

  it('should initialize with provided coordinates', () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 48.8566, lng: 2.3522 });

    expect(component.selectedLat()).toBe(48.8566);
    expect(component.selectedLng()).toBe(2.3522);
    expect(component.saving()).toBe(false);
  });

  it('should initialize with null coordinates', () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null });

    expect(component.selectedLat()).toBeNull();
    expect(component.selectedLng()).toBeNull();
  });

  it('previews a saved place, filters it and cancels without a photo write', () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null });
    const work = { id: 1, name: 'Work', latitude: 0, longitude: 0, last_used_at: null, use_count: 0 };
    component.places.set([work]);
    component.search.set('wo');
    expect(component.filteredPlaces()).toEqual([work]);
    component.selectPlace(work);
    expect(component.selectedLat()).toBe(0);
    component.cancel();
    expect(mockDialogRef.close).toHaveBeenCalledWith(undefined);
    expect(mockApi.put).not.toHaveBeenCalled();
    expect(mockStore.patchPhoto).not.toHaveBeenCalled();
  });

  it('captures inputs, prevents duplicate saves and still publishes the saved location after destruction', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 });
    const pending = new Subject<{ gps_latitude: number; gps_longitude: number }>();
    mockApi.put.mockReturnValue(pending);
    const saving = component.save();
    component.selectedLat.set(30);
    await component.save();
    TestBed.resetTestingModule();
    pending.next({ gps_latitude: 3, gps_longitude: 4 });
    pending.complete();
    await saving;
    expect(mockApi.put).toHaveBeenCalledTimes(1);
    expect(mockApi.put).toHaveBeenCalledWith('/photo/gps', { path: '/photo.jpg', gps_latitude: 1, gps_longitude: 2 });
    expect(mockStore.patchPhoto).toHaveBeenCalledExactlyOnceWith('/photo.jpg', { gps_latitude: 3, gps_longitude: 4, gps_manually_set: 1 });
    expect(mockDialogRef.close).not.toHaveBeenCalled();
  });

  it('cancelling a pending save closes once and still applies the saved location to the gallery', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 });
    const pending = new Subject<{ gps_latitude: number; gps_longitude: number }>();
    mockApi.put.mockReturnValue(pending);
    const saving = component.save();
    component.cancel();
    pending.next({ gps_latitude: 3, gps_longitude: 4 });
    pending.complete();
    await saving;
    expect(mockDialogRef.close).toHaveBeenCalledExactlyOnceWith(undefined);
    expect(mockStore.patchPhoto).toHaveBeenCalledExactlyOnceWith('/photo.jpg', { gps_latitude: 3, gps_longitude: 4, gps_manually_set: 1 });
  });

  it('rejects incomplete, nonfinite and out of range points but accepts zero', () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 0, lng: 0 });
    expect(component.coordinatesValid()).toBe(true);
    component.setLatitude(null);
    expect(component.coordinatesValid()).toBe(false);
    component.setLatitude(Infinity);
    expect(component.coordinatesValid()).toBe(false);
    component.setLatitude(91);
    expect(component.coordinatesValid()).toBe(false);
  });

  it('creates Work once, searches it on another open and selects it through the rendered dialog', async () => {
    const work = { id: 7, name: 'Work', latitude: 12, longitude: 34, last_used_at: null, use_count: 0 };
    createComponent({ path: '/one.jpg', filename: 'one.jpg', lat: 12, lng: 34 }, true);
    await fixture.whenStable();
    mockApi.post.mockReturnValue(of(work));
    component.placeName.set(' Work ');
    await component.createPlace();
    expect(mockApi.post).toHaveBeenCalledWith('/places', { name: 'Work', latitude: 12, longitude: 34 });
    expect(mockStore.patchPhoto).not.toHaveBeenCalled();
    createComponent({ path: '/two.jpg', filename: 'two.jpg', lat: null, lng: null }, true, [work]);
    await fixture.whenStable();
    expect(mockApi.get).toHaveBeenCalledWith('/places');
    const input = fixture.nativeElement.querySelector('input[type="search"]') as HTMLInputElement;
    input.value = 'work';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    const button = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>).find(b => b.textContent?.trim().endsWith('Work'))!;
    button.click();
    fixture.detectChanges();
    expect(component.selectedLat()).toBe(12);
    expect(mockStore.patchPhoto).not.toHaveBeenCalled();
    mockApi.put.mockReturnValue(of({ gps_latitude: 12, gps_longitude: 34 }));
    await component.save();
    expect(mockApi.put).toHaveBeenCalledWith('/photo/gps', { path: '/two.jpg', gps_latitude: 12, gps_longitude: 34, saved_place_id: 7 });
  });

  it('renames original bookmark coordinates, deletes it, and selects recent without changing photos', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 3, lng: 4 });
    const work = { id: 7, name: 'Work', latitude: 12, longitude: 34, last_used_at: null, use_count: 0 };
    await Promise.resolve();
    component.places.set([work]);
    component.selectPlace(work);
    component.setLatitude(50);
    expect(component.selectedPlaceId()).toBeNull();
    component.startRename(work);
    component.editName.set('Office');
    mockApi.put.mockReturnValue(of({ ...work, name: 'Office' }));
    await component.renamePlace(work);
    expect(mockApi.put).toHaveBeenCalledWith('/places/7', { name: 'Office', latitude: 12, longitude: 34 });
    expect(component.places()[0].name).toBe('Office');
    mockApi.delete.mockReturnValue(of({ success: true }));
    await component.deletePlace(work);
    expect(component.places()).toEqual([]);
    component.selectRecent({ latitude: 0, longitude: 0 });
    expect(component.selectedLat()).toBe(0);
    expect(component.selectedLng()).toBe(0);
    expect(component.selectedPlaceId()).toBeNull();
    expect(mockStore.patchPhoto).not.toHaveBeenCalled();
  });

  it('keeps manual entry usable when map initialization fails', async () => {
    leafletMock.map.mockImplementationOnce(() => { throw new Error('map unavailable'); });
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null }, true);
    await fixture.whenStable();
    expect(component.mapFailed()).toBe(true);
    component.setLatitude(0);
    component.setLongitude(0);
    await component.save();
    expect(mockApi.put).toHaveBeenCalledWith('/photo/gps', { path: '/photo.jpg', gps_latitude: 0, gps_longitude: 0 });
  });

  it('ignores map clicks and rejected saves after destruction', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 }, true);
    const click = leafletMockMap.on.mock.calls.filter(call => call[0] === 'click').at(-1)![1];
    const pending = new Subject();
    mockApi.put.mockReturnValue(pending);
    const saving = component.save();
    fixture.destroy();
    click({ latlng: { wrap: () => ({ lat: 5, lng: 6 }) } });
    pending.error(new Error('Rejected'));
    await saving;
    expect(component.selectedLat()).toBe(1);
    expect(mockDialogRef.close).not.toHaveBeenCalled();
    expect(mockStore.patchPhoto).not.toHaveBeenCalled();
    expect(mockSnackBar.open).not.toHaveBeenCalled();
  });

  it('a map click places the point without re-centring or re-zooming the map', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 }, true);
    await fixture.whenStable();
    const click = leafletMockMap.on.mock.calls.filter(call => call[0] === 'click').at(-1)![1];
    leafletMockMap.setView.mockClear();
    click({ latlng: { wrap: () => ({ lat: 5, lng: 6 }) } });
    expect(component.selectedLat()).toBe(5);
    expect(component.selectedLng()).toBe(6);
    expect(leafletMockMap.setView).not.toHaveBeenCalled();
    component.selectRecent({ latitude: 7, longitude: 8 });
    expect(leafletMockMap.setView).toHaveBeenCalledWith([7, 8], 13);
  });

  it('disables Save while the coordinates equal the initial ones, so a GPS-less photo is not pinned', () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null }, true);
    const saveButton = () => Array.from(fixture.nativeElement.querySelectorAll('mat-dialog-actions button') as NodeListOf<HTMLButtonElement>).at(-1)!;
    expect(saveButton().disabled).toBe(true);
    component.setLatitude(3);
    component.setLongitude(4);
    fixture.detectChanges();
    expect(saveButton().disabled).toBe(false);
  });

  it('Cancel closes without a result, so the caller keeps the location', () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null }, true);
    const buttons = Array.from(fixture.nativeElement.querySelectorAll('mat-dialog-actions button')) as HTMLButtonElement[];
    buttons[1].click();
    expect(mockDialogRef.close).toHaveBeenCalledWith(undefined);
    expect(mockApi.put).not.toHaveBeenCalled();
  });

  it('reloads missing-location results after a confirmed assignment', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 0, lng: 0 });
    mockStore.filters.mockReturnValue({ no_gps: '1' });
    await component.save();
    expect(mockStore.refreshPaths).toHaveBeenCalledWith(null);
    expect(mockStore.loadPhotos).not.toHaveBeenCalled();
  });

  describe('Google Maps links and coordinates', () => {
    const PIN_URL = 'https://www.google.com/maps/place/X/@1,2,12z/data=!3m1!4b1!4m6!3m5!8m2!3d32.6064!4d-116.3239';
    const DMS_TEXT = `32°36'23.0"N 116°19'26.0"W`;
    let open: ReturnType<typeof vi.spyOn>;

    beforeEach(() => { open = vi.spyOn(window, 'open').mockReturnValue(null); });
    afterEach(() => open.mockRestore());

    function single() { createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null }); }

    it('moves the pin to a pasted coordinate pair without saving', async () => {
      single();
      component.setMapsInput('32.6064, -116.3239');
      await component.applyMapsInput();
      expect(component.selectedLat()).toBe(32.6064);
      expect(component.selectedLng()).toBe(-116.3239);
      expect(component.mapsPoint()).toEqual({ lat: 32.6064, lng: -116.3239 });
      expect(mockApi.post).not.toHaveBeenCalled();
      expect(mockApi.put).not.toHaveBeenCalled();
      expect(mockDialogRef.close).not.toHaveBeenCalled();
    });

    it('reads the dropped pin of a full URL and clears a chosen saved place', async () => {
      single();
      component.selectedPlaceId.set(7);
      component.setMapsInput(PIN_URL);
      await component.applyMapsInput();
      expect([component.selectedLat(), component.selectedLng()]).toEqual([32.6064, -116.3239]);
      expect(component.selectedPlaceId()).toBeNull();
    });

    it('resolves a short link on the server, then the user still saves', async () => {
      single();
      mockApi.post.mockReturnValue(of({ latitude: 10.5, longitude: 20.25 }));
      component.setMapsInput(' https://maps.app.goo.gl/AbC ');
      await component.applyMapsInput();
      expect(mockApi.post).toHaveBeenCalledWith('/geo/resolve_maps_link', { url: 'https://maps.app.goo.gl/AbC' });
      expect([component.selectedLat(), component.selectedLng()]).toEqual([10.5, 20.25]);
      expect(mockApi.put).not.toHaveBeenCalled();
      mockApi.put.mockReturnValue(of({ gps_latitude: 10.5, gps_longitude: 20.25 }));
      await component.save();
      expect(mockApi.put).toHaveBeenCalledWith('/photo/gps', { path: '/photo.jpg', gps_latitude: 10.5, gps_longitude: 20.25 });
    });

    it.each(['Pine Valley', 'https://evil.example/maps/x', '95, 10'])('refuses %s locally without a request', async text => {
      single();
      component.setMapsInput(text);
      await component.applyMapsInput();
      expect(component.mapsError()).toBe('photo_detail.gps.maps_unrecognized');
      expect(component.selectedLat()).toBeNull();
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it.each([
      [{ status: 422, error: { detail: 'no_coordinates' } }, 'photo_detail.gps.maps_unrecognized'],
      [{ status: 422, error: { detail: 'unsupported_host' } }, 'photo_detail.gps.maps_unrecognized'],
      [{ status: 422, error: { detail: 'unreachable' } }, 'photo_detail.gps.maps_unreachable'],
      [{ status: 0 }, 'photo_detail.gps.maps_unreachable'],
    ])('reports a refused short link %j', async (error, key) => {
      single();
      mockApi.post.mockReturnValue(throwError(() => error));
      component.setMapsInput('https://maps.app.goo.gl/AbC');
      await component.applyMapsInput();
      expect(component.mapsError()).toBe(key);
      expect(component.mapsBusy()).toBe(false);
      expect(component.selectedLat()).toBeNull();
    });

    it('drops a short-link answer once the field has been edited', async () => {
      single();
      const pending = new Subject<{ latitude: number; longitude: number }>();
      mockApi.post.mockReturnValue(pending);
      component.setMapsInput('https://maps.app.goo.gl/AbC');
      const resolving = component.applyMapsInput();
      expect(component.mapsBusy()).toBe(true);
      component.setMapsInput('something else');
      pending.next({ latitude: 1, longitude: 2 });
      pending.complete();
      await resolving;
      expect(component.selectedLat()).toBeNull();
      expect(component.mapsBusy()).toBe(false);
    });

    it('opens Google Maps at the pin, in a new tab without an opener', () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 32.6064, lng: -116.3239 });
      component.openGoogleMaps();
      expect(open).toHaveBeenCalledWith('https://www.google.com/maps/search/?api=1&query=32.606400,-116.323900', '_blank', 'noopener');
    });

    it('opens a batch at the first geotagged photo of the selection, else the default centre', () => {
      createComponent({ path: '', filename: 'Set location', lat: null, lng: null, batch: { photo_paths: ['/b.jpg', '/c.jpg'] } });
      Object.assign(mockStore, { photos: () => [
        makePhoto({ path: '/a.jpg', gps_latitude: 1, gps_longitude: 1 }),
        makePhoto({ path: '/b.jpg', gps_latitude: null, gps_longitude: null }),
        makePhoto({ path: '/c.jpg', gps_latitude: 3, gps_longitude: 4 }),
      ] });
      component.openGoogleMaps();
      expect(open).toHaveBeenLastCalledWith('https://www.google.com/maps/search/?api=1&query=3.000000,4.000000', '_blank', 'noopener');
      createComponent({ path: '', filename: 'Set location', lat: null, lng: null, batch: { filters: {}, exclude: ['/a.jpg'] } });
      Object.assign(mockStore, { photos: () => [makePhoto({ path: '/a.jpg', gps_latitude: 1, gps_longitude: 1 })] });
      component.openGoogleMaps();
      expect(open).toHaveBeenLastCalledWith('https://www.google.com/maps/search/?api=1&query=48.856600,2.352200', '_blank', 'noopener');
    });

    it('reads a paste into the rendered field at once and describes the field by its hint', async () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null }, true);
      await fixture.whenStable();
      const input = fixture.nativeElement.querySelector('input[aria-describedby="gps-maps-hint"]') as HTMLInputElement;
      expect(fixture.nativeElement.querySelector('#gps-maps-hint')).not.toBeNull();
      const paste = new Event('paste', { cancelable: true }) as ClipboardEvent;
      Object.defineProperty(paste, 'clipboardData', { value: { getData: () => DMS_TEXT } });
      input.dispatchEvent(paste);
      await fixture.whenStable();
      fixture.detectChanges();
      expect(paste.defaultPrevented).toBe(true);
      expect(component.selectedLat()).toBeCloseTo(32 + 36 / 60 + 23 / 3600, 9);
      expect(component.selectedLng()).toBeCloseTo(-(116 + 19 / 60 + 26 / 3600), 9);
      expect(fixture.nativeElement.textContent).toContain('photo_detail.gps.maps_moved');
      const pick = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
        .find(b => b.textContent?.includes('photo_detail.gps.maps_pick'))!;
      pick.click();
      expect(open).toHaveBeenCalledWith(expect.stringContaining('query=32.606389,-116.323889'), '_blank', 'noopener');
    });

    it('does not read the Enter that commits an IME candidate', async () => {
      single();
      component.setMapsInput('1, 2');
      component.onMapsEnter(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true }));
      await Promise.resolve();
      expect(component.selectedLat()).toBeNull();
      component.onMapsEnter(new KeyboardEvent('keydown', { key: 'Enter' }));
      await Promise.resolve();
      expect(component.selectedLat()).toBe(1);
    });
  });

  describe('clearLocation', () => {
    it('should set coordinates to null', () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 48.8566, lng: 2.3522 });

      component.clearLocation();

      expect(component.selectedLat()).toBeNull();
      expect(component.selectedLng()).toBeNull();
    });
  });

  describe('save', () => {
    it('should call API and close dialog on success', async () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 48.8566, lng: 2.3522 });

      await component.save();

      expect(mockApi.put).toHaveBeenCalledWith('/photo/gps', {
        path: '/photo.jpg',
        gps_latitude: 48.8566,
        gps_longitude: 2.3522,
      });
      expect(mockDialogRef.close).toHaveBeenCalledWith({
        gps_latitude: 48.8566,
        gps_longitude: 2.3522,
      });
    });

    it('writes the location to the gallery copy even if Back already closed the dialog', async () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 48.8566, lng: 2.3522 });
      await component.save();

      expect(mockStore.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { gps_latitude: 48.8566, gps_longitude: 2.3522, gps_manually_set: 1 });
    });

    it('should send null coordinates when cleared', async () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null });

      await component.save();

      expect(mockApi.put).toHaveBeenCalledWith('/photo/gps', {
        path: '/photo.jpg',
        gps_latitude: null,
        gps_longitude: null,
      });
      expect(mockDialogRef.close).toHaveBeenCalledWith({
        gps_latitude: null,
        gps_longitude: null,
      });
    });

    it('preserves null GPS in the gallery after a confirmed clear', async () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 });
      component.clearLocation();
      mockApi.put.mockReturnValue(of({ gps_latitude: null, gps_longitude: null }));
      await component.save();
      expect(mockStore.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { gps_latitude: null, gps_longitude: null, gps_manually_set: 1 });
    });

    it('should show snackbar on error', async () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 48.8566, lng: 2.3522 });
      mockApi.put.mockReturnValue(throwError(() => new Error('Network error')));

      await component.save();

      expect(mockDialogRef.close).not.toHaveBeenCalled();
      expect(mockSnackBar.open).toHaveBeenCalled();
    });

    it('should set saving state during request', async () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 48.8566, lng: 2.3522 });

      expect(component.saving()).toBe(false);

      const promise = component.save();
      expect(component.saving()).toBe(true);

      await promise;
      expect(component.saving()).toBe(false);
    });
  });

  describe('use the file\'s location', () => {
    const KEY = 'photo_detail.gps.use_file_location';
    const findButton = () => Array.from(fixture.nativeElement.querySelectorAll('mat-dialog-actions button') as NodeListOf<HTMLButtonElement>)
      .find(b => b.textContent?.trim() === KEY);

    it('is hidden when the location was not set in the viewer', () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 }, true);
      expect(findButton()).toBeUndefined();
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2, manuallySet: false }, true);
      expect(findButton()).toBeUndefined();
    });

    it('is shown when flagged and calls DELETE /photo/gps, then closes like a save', async () => {
      createComponent({ path: '/a b.jpg', filename: 'a b.jpg', lat: 1, lng: 2, manuallySet: true }, true);
      const result = { gps_latitude: 48.5, gps_longitude: 2.25 };
      mockApi.delete.mockReturnValue(of(result));
      const button = findButton();
      expect(button).toBeDefined();
      button!.click();
      await fixture.whenStable();
      expect(mockApi.delete).toHaveBeenCalledWith('/photo/gps?path=' + encodeURIComponent('/a b.jpg'));
      expect(mockStore.patchPhoto).toHaveBeenCalledWith('/a b.jpg', { gps_latitude: 48.5, gps_longitude: 2.25, gps_manually_set: 0 });
      expect(mockDialogRef.close).toHaveBeenCalledWith({ ...result, gps_manually_set: 0 });
    });

    it('keeps the dialog open and reports the failure', async () => {
      createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2, manuallySet: true });
      mockApi.delete.mockReturnValue(throwError(() => new Error('boom')));
      await component.useFileLocation();
      expect(mockDialogRef.close).not.toHaveBeenCalled();
      expect(mockStore.patchPhoto).not.toHaveBeenCalled();
      expect(component.saveError()).toBe('photo_detail.gps.save_error');
    });
  });
  describe('batch completion with the real gallery store', () => {
    let store: GalleryStore;
    let serverPhotos = [makePhoto({ path: '/old.jpg' })];
    let pending: Subject<{ changed: number; skipped: number; preview_token: string }>;

    beforeEach(async () => {
      TestBed.resetTestingModule();
      serverPhotos = [makePhoto({ path: '/old.jpg' })];
      pending = new Subject();
      mockApi = {
        get: vi.fn((url: string) => of(url === '/places' ? { places: [], recent: [] } : {
          photos: serverPhotos, total: serverPhotos.length, page: 1, per_page: 64, total_pages: 1, has_more: false,
        })),
        put: vi.fn(), delete: vi.fn(),
        post: vi.fn((url: string, body: { preview?: boolean }) => url === '/photos/batch_gps'
          ? body.preview ? of({ changed: 1, skipped: 0, preview_token: 'token' }) : pending
          : of({ photos: serverPhotos, total: serverPhotos.length, missing: [] })),
      };
      TestBed.configureTestingModule({ providers: [
        GpsEditDialogComponentClass, GalleryStore,
        { provide: MAT_DIALOG_DATA, useValue: { path: '', filename: 'selection', lat: null, lng: null, batch: { photo_paths: ['/old.jpg'] } } },
        { provide: MatDialogRef, useValue: { close: vi.fn(), beforeClosed: vi.fn(() => closing) } },
        { provide: ApiService, useValue: mockApi },
        { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { identity, status: authStatus, isEdition: () => true } },
        { provide: AlbumService, useValue: { list: () => of({ albums: [] }), update: () => of({}) } },
        { provide: I18nService, useValue: { t: (key: string) => key } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
      ] });
      component = TestBed.inject(GpsEditDialogComponentClass);
      store = TestBed.inject(GalleryStore);
      store.filters.update(f => ({ ...f, no_gps: '1', camera: 'Canon' }));
      await store.loadPhotos();
      component.selectRecent({ latitude: 1, longitude: 2 });
      await component.previewBatch();
    });

    async function finish(saving: Promise<void>) {
      pending.next({ changed: 1, skipped: 0, preview_token: 'token' });
      pending.complete();
      await saving;
      // Drain the store's serialized refresh queue to inspect the settled view.
      await store.refreshPaths([]);
    }

    it('preserves a newer whole-view selection and exclusions after dismissed save completes', async () => {
      const saving = component.save();
      component.cancel();
      serverPhotos = [makePhoto({ path: '/new.jpg' }), makePhoto({ path: '/excluded.jpg' })];
      store.filters.update(f => ({ ...f, no_gps: '', camera: 'Nikon' }));
      await store.loadPhotos();
      store.selectWholeView();
      store.excludedPaths.set(new Set(['/excluded.jpg']));
      await finish(saving);
      expect(store.viewScopeSelected()).toBe(true);
      expect([...store.excludedPaths()]).toEqual(['/excluded.jpg']);
      expect(store.filters().camera).toBe('Nikon');
      expect(store.photos().map(p => p.path)).toEqual(['/new.jpg', '/excluded.jpg']);
    });

    it('keeps the newer pinned list and refreshes it after dismissed completion', async () => {
      const saving = component.save();
      component.cancel();
      serverPhotos = [makePhoto({ path: '/pin.jpg', gps_latitude: 0, gps_longitude: 0 })];
      await store.showPaths(['/pin.jpg']);
      serverPhotos = [makePhoto({ path: '/pin.jpg', gps_latitude: 5, gps_longitude: 6 })];
      await finish(saving);
      expect(store.pinnedPaths()).toEqual(['/pin.jpg']);
      expect(store.photos().map(p => p.path)).toEqual(['/pin.jpg']);
      expect(store.photos()[0].gps_latitude).toBe(5);
      expect(mockApi.post).toHaveBeenLastCalledWith('/photos/by_paths', { paths: ['/pin.jpg'] });
    });

    it('recomputes the current missing-GPS membership and count after apply', async () => {
      const saving = component.save();
      serverPhotos = [];
      await finish(saving);
      expect(store.photos()).toEqual([]);
      expect(store.total()).toBe(0);
      expect(store.filters()).toMatchObject({ no_gps: '1', camera: 'Canon' });
      // Review progress is fetched after the page, so the page is the last /photos call, not the last call.
      const pageCalls = mockApi.get.mock.calls.filter(call => call[0] === '/photos');
      expect(pageCalls.at(-1)).toEqual(['/photos', expect.objectContaining({ no_gps: '1', camera: 'Canon' })]);
    });
  });

  describe('missing-location membership with the real gallery store', () => {
    let store: GalleryStore;
    const photo = makePhoto({ path: '/photo.jpg', gps_latitude: null, gps_longitude: null, gps_manually_set: 1 });
    let serverPhotos = [photo];

    beforeEach(async () => {
      TestBed.resetTestingModule();
      serverPhotos = [photo];
      mockApi = {
        get: vi.fn((url: string) => of(url === '/places' ? { places: [], recent: [] } : {
          photos: serverPhotos, total: serverPhotos.length, page: 1, per_page: 64, total_pages: 1, has_more: false,
        })),
        put: vi.fn(), delete: vi.fn(), post: vi.fn(() => of({})),
      };
      authStatus.set({ authenticated: true, edition_authenticated: true, user_id: 'editor' });
      mockDialogRef = { close: vi.fn(), beforeClosed: vi.fn(() => closing) };
      TestBed.configureTestingModule({
        providers: [
          GpsEditDialogComponentClass, GalleryStore,
          { provide: MAT_DIALOG_DATA, useValue: { path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null, manuallySet: true } },
          { provide: MatDialogRef, useValue: mockDialogRef },
          { provide: ApiService, useValue: mockApi },
          { provide: AuthService, useValue: { identity, status: authStatus, isEdition: () => authStatus().edition_authenticated } },
          { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
          { provide: AlbumService, useValue: { list: () => of({ albums: [] }), update: () => of({}) } },
          { provide: I18nService, useValue: { t: (key: string) => key } },
        ],
      });
      component = TestBed.inject(GpsEditDialogComponentClass);
      store = TestBed.inject(GalleryStore);
      store.filters.update(f => ({ ...f, no_gps: '1', camera: 'Canon' }));
      store.photos.set([photo]);
      store.total.set(1);
      await store.loadPhotos();
    });

    it('returns a photo to missing-location results after saving coordinates and then clearing them', async () => {
      component.setLatitude(0);
      component.setLongitude(0);
      mockApi.put.mockReturnValueOnce(of({ gps_latitude: 0, gps_longitude: 0 }));
      serverPhotos = [];
      await component.save();
      await store.refreshPaths(null);
      expect(store.photos()).toEqual([]);
      expect(store.total()).toBe(0);

      component.clearLocation();
      mockApi.put.mockReturnValueOnce(of({ gps_latitude: null, gps_longitude: null }));
      serverPhotos = [photo];
      await component.save();
      await store.refreshPaths(null);
      expect(store.photos().map(p => p.path)).toEqual(['/photo.jpg']);
      expect(store.total()).toBe(1);
      expect(store.filters()).toMatchObject({ no_gps: '1', camera: 'Canon' });
    });

    it('preserves a newly pinned selection when an online-place save finishes in a changed view', async () => {
      store.config.set({ ...store.config()!, place_search_enabled: true });
      const result = { label: 'Berlin', latitude: 52.5, longitude: 13.4 };
      component.selectOnlineResult(result);
      const pending = new Subject<{ gps_latitude: number; gps_longitude: number }>();
      mockApi.put.mockReturnValue(pending);
      const saving = component.save();
      const other = makePhoto({ path: '/other.jpg', gps_latitude: 3, gps_longitude: 4 });
      store.pinnedPaths.set(['/other.jpg']);
      store.photos.set([other]);
      store.selectedPaths.set(new Set(['/other.jpg']));
      mockApi.post.mockReturnValue(of({ photos: [other] }));
      pending.next({ gps_latitude: 52.5, gps_longitude: 13.4 });
      pending.complete();
      await saving;
      await store.refreshPaths(null);
      expect(store.pinnedPaths()).toEqual(['/other.jpg']);
      expect(store.selectedPaths()).toEqual(new Set(['/other.jpg']));
      expect(store.photos().map(p => p.path)).toEqual(['/other.jpg']);
      expect(store.filters()).toMatchObject({ no_gps: '1', camera: 'Canon' });
    });

    it.each([
      { result: { gps_latitude: 0, gps_longitude: 0 }, visible: false },
      { result: { gps_latitude: null, gps_longitude: null }, visible: true },
    ])('refreshes membership from the file-location response: %j', async ({ result, visible }) => {
      if (visible) { store.photos.set([]); store.total.set(0); }
      serverPhotos = visible ? [{ ...photo, gps_manually_set: 0 }] : [];
      mockApi.delete.mockReturnValue(of(result));
      await component.useFileLocation();
      await store.refreshPaths(null);
      expect(store.photos().map(p => p.path)).toEqual(visible ? ['/photo.jpg'] : []);
      expect(store.total()).toBe(visible ? 1 : 0);
      expect(mockApi.get).toHaveBeenCalledWith('/photos', expect.objectContaining({ no_gps: '1', camera: 'Canon' }));
      expect(store.filters()).toMatchObject({ no_gps: '1', camera: 'Canon' });
    });
  });

});
