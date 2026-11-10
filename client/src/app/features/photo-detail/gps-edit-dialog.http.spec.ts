import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationStart, Router } from '@angular/router';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService, AuthStatus } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { GalleryStore } from '../gallery/gallery.store';
import type { GpsEditDialogComponent, GpsEditDialogData } from './gps-edit-dialog.component';
import { leafletMock, resetLeafletMock } from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);

const EDITOR: AuthStatus = {
  authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
  edition_password_required: false, login_password_required: false, user_id: 'alice',
  user_role: 'editor', display_name: 'Alice', features: {}, download_profiles: [],
};

describe('GPS dialog rendered controls and HTTP ownership', () => {
  let componentClass: typeof GpsEditDialogComponent;
  let fixture: ComponentFixture<GpsEditDialogComponent>;
  let component: GpsEditDialogComponent;
  let http: HttpTestingController;
  let auth: AuthService;
  let destroyed: boolean;
  let navigation: Subject<NavigationStart>;
  let closing: Subject<void>;
  let router: { url: string; events: Subject<NavigationStart> };
  let applied: ReturnType<typeof vi.fn<() => void>>;
  let store: { config: ReturnType<typeof signal<{ place_search_enabled: boolean }>>; patchPhoto: ReturnType<typeof vi.fn>; refreshPaths: ReturnType<typeof vi.fn> };
  let dialog: { close: ReturnType<typeof vi.fn>; beforeClosed: () => Subject<void> };
  let snack: { open: ReturnType<typeof vi.fn> };

  beforeAll(async () => {
    ({ GpsEditDialogComponent: componentClass } = await import('./gps-edit-dialog.component'));
  });

  beforeEach(() => {
    resetLeafletMock();
    destroyed = false;
    navigation = new Subject();
    closing = new Subject();
    router = { url: '/', events: navigation };
    applied = vi.fn<() => void>();
    store = { config: signal({ place_search_enabled: true }), patchPhoto: vi.fn(), refreshPaths: vi.fn() };
    dialog = { close: vi.fn(), beforeClosed: () => closing };
    snack = { open: vi.fn() };
  });

  afterEach(() => {
    if (fixture && !destroyed) fixture.destroy();
    http.verify();
  });

  async function open(batch = true): Promise<void> {
    const data: GpsEditDialogData = {
      path: '/photo.jpg', filename: batch ? 'Selection' : 'photo.jpg', lat: null, lng: null,
      ...(batch ? { batch: { photo_paths: ['/one.jpg', '/two.jpg', '/three.jpg'] }, onBatchApplied: applied } : {}),
    };
    TestBed.configureTestingModule({
      imports: [componentClass],
      providers: [
        provideHttpClient(), provideHttpClientTesting(), ApiService, AuthService, I18nService,
        { provide: MAT_DIALOG_DATA, useValue: data }, { provide: MatDialogRef, useValue: dialog },
        { provide: Router, useValue: router }, { provide: GalleryStore, useValue: store },
      ],
    });
    TestBed.overrideProvider(MatSnackBar, { useValue: snack });
    http = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    const checking = auth.checkStatus();
    http.expectOne('/api/auth/status').flush(EDITOR);
    await checking;
    const i18n = TestBed.inject(I18nService);
    i18n.locale.set('en');
    const translating = i18n.load();
    http.expectOne('/api/i18n/en').flush({ photo_detail: { gps: {
      batch_preview: 'Change {changed} photo, skip {skipped}', batch_preview_plural: 'Change {changed}, skip {skipped}',
      batch_applied: 'Applied {changed} photo, skipped {skipped}', batch_applied_plural: 'Applied {changed}, skipped {skipped}',
      osm_attribution: 'OSM credit', opens_new_tab: '(opens in new tab)',
    } } });
    await translating;
    fixture = TestBed.createComponent(componentClass);
    component = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne('/api/places').flush({ places: [], recent: [] });
    await settle();
  }

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function button(key: string): HTMLButtonElement {
    const found = (Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[])
      .find(element => element.textContent?.trim().endsWith(key));
    expect(found, key).toBeDefined();
    return found!;
  }

  function type(input: HTMLInputElement, value: string): void {
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  async function coordinates(latitude: string, longitude: string): Promise<void> {
    const inputs = fixture.nativeElement.querySelectorAll('input[type="number"]') as NodeListOf<HTMLInputElement>;
    type(inputs[0], latitude);
    type(inputs[1], longitude);
    await settle();
  }

  function query(value: string): void {
    const inputs = fixture.nativeElement.querySelectorAll('input[type="search"]') as NodeListOf<HTMLInputElement>;
    type(inputs[1], value);
  }

  async function preview(changed = 2, token = 'preview-token'): Promise<void> {
    button(I18N.photo_detail.gps.preview_batch).click();
    const request = http.expectOne('/api/photos/batch_gps');
    expect(request.request.method).toBe('POST');
    expect(request.request.body.preview).toBe(true);
    request.flush({ changed, skipped: 3 - changed, preview_token: token });
    await settle();
  }

  it('renders batch validation and previews before applying the exact draft and token', async () => {
    await open();
    expect(fixture.nativeElement.textContent).toContain(I18N.photo_detail.gps.batch_hint);
    expect(fixture.nativeElement.textContent).not.toContain(I18N.photo_detail.gps_clear);
    expect(button(I18N.photo_detail.gps.preview_batch).disabled).toBe(true);
    expect(button(I18N.ui.buttons.save).disabled).toBe(true);
    await coordinates('1', '');
    expect(button(I18N.photo_detail.gps.preview_batch).disabled).toBe(true);
    await coordinates('91', '2');
    expect(fixture.nativeElement.textContent).toContain(I18N.photo_detail.gps.invalid_coordinates);
    button(I18N.photo_detail.gps.preview_batch).click();
    http.expectNone('/api/photos/batch_gps');
    await coordinates('0', '0');
    expect(button(I18N.photo_detail.gps.preview_batch).disabled).toBe(false);
    expect(button(I18N.ui.buttons.save).disabled).toBe(true);
    await preview();
    expect(fixture.nativeElement.textContent).toContain('Change 2, skip 1');
    expect(button(I18N.ui.buttons.save).disabled).toBe(false);
    button(I18N.ui.buttons.save).click();
    const applying = http.expectOne('/api/photos/batch_gps');
    expect(applying.request.body).toEqual({ photo_paths: ['/one.jpg', '/two.jpg', '/three.jpg'],
      gps_latitude: 0, gps_longitude: 0, only_missing: true, preview: false, preview_token: 'preview-token' });
    fixture.detectChanges();
    expect(button(I18N.ui.buttons.save).disabled).toBe(true);
    button(I18N.ui.buttons.save).click();
    http.expectNone('/api/photos/batch_gps');
    expect(applied).not.toHaveBeenCalled();
    const result = { changed: 2, skipped: 1, preview_token: '' };
    applying.flush(result);
    await settle();
    expect(applied).toHaveBeenCalledOnce();
    expect(store.refreshPaths).toHaveBeenCalledExactlyOnceWith(null);
    expect(store.patchPhoto).not.toHaveBeenCalled();
    expect(dialog.close).toHaveBeenCalledExactlyOnceWith(result);
    expect(snack.open).toHaveBeenCalledWith('Applied 2, skipped 1', '', { duration: 4000 });
    http.expectNone(request => request.method === 'PUT' || request.method === 'DELETE');
  });

  it('uses the singular batch sentences when exactly one photo changes', async () => {
    await open();
    await coordinates('0', '0');
    await preview(1);
    expect(fixture.nativeElement.textContent).toContain('Change 1 photo, skip 2');
    button(I18N.ui.buttons.save).click();
    http.expectOne('/api/photos/batch_gps').flush({ changed: 1, skipped: 2, preview_token: '' });
    await settle();
    expect(snack.open).toHaveBeenCalledWith('Applied 1 photo, skipped 2', '', { duration: 4000 });
  });

  it('translates the provider credit and cues every new-tab link in its name', async () => {
    await open();
    const links = Array.from(fixture.nativeElement.querySelectorAll('a[target="_blank"]')) as HTMLAnchorElement[];
    expect(links.length).toBe(2);
    expect(links.map(link => link.textContent!.replace(/\s+/g, ' ').trim())).toEqual([
      'Photon (opens in new tab)', 'OSM credit (opens in new tab)',
    ]);
    expect(fixture.nativeElement.textContent).not.toContain('© OpenStreetMap contributors');
  });

  it('invalidates the preview through the only-missing checkbox and blocks an unchanged batch', async () => {
    await open();
    await coordinates('1', '2');
    await preview();
    const checkbox = fixture.nativeElement.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    checkbox.click();
    await settle();
    expect(checkbox.checked).toBe(false);
    expect(button(I18N.ui.buttons.save).disabled).toBe(true);
    expect(fixture.nativeElement.textContent).not.toContain('Change 2, skip 1');
    button(I18N.ui.buttons.save).click();
    http.expectNone('/api/photos/batch_gps');
    button(I18N.photo_detail.gps.preview_batch).click();
    const changedDraft = http.expectOne('/api/photos/batch_gps');
    expect(changedDraft.request.body).toMatchObject({ only_missing: false, preview: true, gps_latitude: 1, gps_longitude: 2 });
    changedDraft.flush({ changed: 0, skipped: 3, preview_token: 'zero' });
    await settle();
    expect(fixture.nativeElement.textContent).toContain('Change 0, skip 3');
    expect(button(I18N.ui.buttons.save).disabled).toBe(true);
    await preview(3, 'fresh');
    button(I18N.ui.buttons.save).click();
    const applying = http.expectOne('/api/photos/batch_gps');
    expect(applying.request.body).toMatchObject({ only_missing: false, preview: false, preview_token: 'fresh' });
    applying.flush({ changed: 3, skipped: 0, preview_token: '' });
    await settle();
    expect(applied).toHaveBeenCalledOnce();
  });

  it('keeps the draft on preview/apply errors and requires a fresh preview before retry', async () => {
    await open();
    await coordinates('1', '2');
    button(I18N.photo_detail.gps.preview_batch).click();
    http.expectOne('/api/photos/batch_gps').flush({}, { status: 400, statusText: 'Invalid preview' });
    await settle();
    expect(fixture.nativeElement.textContent).toContain(I18N.photo_detail.gps.batch_error);
    expect(button(I18N.ui.buttons.save).disabled).toBe(true);
    await preview();
    button(I18N.ui.buttons.save).click();
    http.expectOne('/api/photos/batch_gps').flush({}, { status: 409, statusText: 'Stale preview' });
    await settle();
    expect(button(I18N.ui.buttons.save).disabled).toBe(true);
    expect(component.selectedLat()).toBe(1);
    expect(applied).not.toHaveBeenCalled();
    expect(store.refreshPaths).not.toHaveBeenCalled();
    await preview(2, 'retry');
    button(I18N.ui.buttons.save).click();
    const applying = http.expectOne('/api/photos/batch_gps');
    expect(applying.request.body.preview_token).toBe('retry');
    applying.flush({ changed: 2, skipped: 1, preview_token: '' });
    await settle();
    expect(applied).toHaveBeenCalledOnce();
  });

  it.each(['cancel', 'destroy', 'identity', 'navigation'] as const)('handles a committed batch after %s without publishing to another owner', async loss => {
    await open();
    await coordinates('1', '2');
    await preview();
    button(I18N.ui.buttons.save).click();
    const applying = http.expectOne('/api/photos/batch_gps');
    expect(applying.request.body.preview).toBe(false);
    const published = new Promise<void>(resolve => applied.mockImplementation(resolve));
    let checking: Promise<AuthStatus> | undefined;
    if (loss === 'cancel') button(I18N.ui.buttons.cancel).click();
    if (loss === 'destroy') { fixture.destroy(); destroyed = true; }
    if (loss === 'identity') {
      checking = auth.checkStatus();
      http.expectOne('/api/auth/status').flush({ ...EDITOR, user_id: 'bob' });
    }
    expect(applying.cancelled).toBe(false);
    applying.flush({ changed: 2, skipped: 1, preview_token: '' });
    if (loss === 'navigation') {
      navigation.next(new NavigationStart(1, '/other'));
      navigation.next(new NavigationStart(2, '/'));
    }
    if (checking) await checking;
    if (destroyed) await published;
    else await settle();
    const publishes = loss === 'cancel' || loss === 'destroy';
    expect(applied).toHaveBeenCalledTimes(publishes ? 1 : 0);
    expect(store.refreshPaths).toHaveBeenCalledTimes(publishes ? 1 : 0);
    expect(snack.open).toHaveBeenCalledTimes(publishes ? 1 : 0);
    expect(dialog.close).not.toHaveBeenCalledWith(expect.objectContaining({ changed: 2 }));
  });

  it('filters an HTTP search response before limiting it, then previews and saves the chosen result', async () => {
    await open(false);
    query('  Berlin  ');
    http.expectNone('/api/places/search');
    button(I18N.photo_detail.gps.online_search).click();
    const lookup = http.expectOne(request => request.url === '/api/places/search');
    expect(lookup.request.params.get('q')).toBe('Berlin');
    const valid = Array.from({ length: 6 }, (_, index) => ({ label: index === 4 ? 'x'.repeat(600) : `Place ${index}`,
      latitude: index === 1 ? 90 : index === 2 ? -90 : index,
      longitude: index === 1 ? 180 : index === 2 ? -180 : index === 0 ? 0 : -index }));
    lookup.flush({ results: [null, {}, { label: ' ', latitude: 1, longitude: 2 },
      { label: 'x'.repeat(601), latitude: 1, longitude: 2 }, { label: 7, latitude: 1, longitude: 2 },
      { label: 'string coordinate', latitude: '1', longitude: 2 }, { label: 'infinite', latitude: Infinity, longitude: 2 },
      { label: 'longitude type', latitude: 1, longitude: '2' }, { label: 'longitude infinite', latitude: 1, longitude: Infinity },
      { label: 'latitude bounds', latitude: 91, longitude: 2 }, { label: 'longitude bounds', latitude: 1, longitude: -181 }, ...valid] });
    await settle();
    const labels = Array.from(fixture.nativeElement.querySelectorAll('ul button') as NodeListOf<HTMLButtonElement>).map(element => element.textContent?.trim());
    expect(labels).toEqual(valid.slice(0, 5).map(result => result.label));
    expect(component.selectedLat()).toBeNull();
    button('Place 0').click();
    await settle();
    expect(component.selectedLat()).toBe(0);
    http.expectNone('/api/photo/gps');
    button(I18N.ui.buttons.save).click();
    const save = http.expectOne('/api/photo/gps');
    expect(save.request.method).toBe('PUT');
    expect(save.request.body).toEqual({ path: '/photo.jpg', gps_latitude: 0, gps_longitude: 0 });
    save.flush({ gps_latitude: 0, gps_longitude: 0 });
    await settle();
    expect(store.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { gps_latitude: 0, gps_longitude: 0, gps_manually_set: 1 });
  });

  it('displays a valid 600-character Unicode label that the server can return', async () => {
    await open(false);
    query('Station');
    const task = component.searchOnline();
    const label = '🚋'.repeat(299) + ', ' + '🌳'.repeat(299);
    expect(Array.from(label)).toHaveLength(600);
    http.expectOne(request => request.url === '/api/places/search').flush({ results: [{ label, latitude: 1, longitude: 2 }] });
    await task;
    await settle();
    button(label).click();
    await settle();
    expect(component.selectedLat()).toBe(1);
    expect(component.selectedLng()).toBe(2);
    http.expectNone('/api/photo/gps');
  });

  it('guards invalid queries, disabled lookup, saving and duplicate search requests with positive recovery', async () => {
    await open();
    for (const invalid of ['ab', '🚋🚋', 'x'.repeat(201)]) {
      query(invalid);
      expect(button(I18N.photo_detail.gps.online_search).disabled).toBe(true);
      await component.searchOnline();
      http.expectNone(request => request.url === '/api/places/search');
    }
    query('🚋🚋🚋');
    store.config.set({ place_search_enabled: false });
    fixture.detectChanges();
    expect(button(I18N.photo_detail.gps.online_search).disabled).toBe(true);
    await component.searchOnline();
    http.expectNone(request => request.url === '/api/places/search');
    store.config.set({ place_search_enabled: true });
    await coordinates('1', '2');
    button(I18N.photo_detail.gps.preview_batch).click();
    const previewing = http.expectOne('/api/photos/batch_gps');
    fixture.detectChanges();
    expect(button(I18N.photo_detail.gps.online_search).disabled).toBe(true);
    await component.searchOnline();
    http.expectNone(request => request.url === '/api/places/search');
    previewing.flush({ changed: 1, skipped: 2, preview_token: 't' });
    await settle();
    button(I18N.photo_detail.gps.online_search).click();
    const searching = http.expectOne(request => request.url === '/api/places/search');
    expect(searching.request.params.get('q')).toBe('🚋🚋🚋');
    await component.searchOnline();
    http.expectNone(request => request.url === '/api/places/search');
    searching.flush({ results: [] });
    await settle();
    expect(fixture.nativeElement.textContent).toContain(I18N.photo_detail.gps.online_empty);
    expect(button(I18N.photo_detail.gps.online_search).disabled).toBe(false);
  });

  it('does not let a queued old response clear the busy state or replace a newer query', async () => {
    await open(false);
    query('Berlin');
    const oldTask = component.searchOnline();
    http.expectOne(request => request.url === '/api/places/search').flush({ results: [{ label: 'Old', latitude: 1, longitude: 2 }] });
    query('Paris');
    const newTask = component.searchOnline();
    const current = http.expectOne(request => request.url === '/api/places/search');
    expect(current.request.params.get('q')).toBe('Paris');
    await oldTask;
    expect(component.onlineBusy()).toBe(true);
    expect(component.onlineResults()).toEqual([]);
    current.flush({ results: [{ label: 'New', latitude: 3, longitude: 4 }] });
    await newTask;
    await settle();
    expect(button('New')).toBeDefined();
    expect(component.onlineBusy()).toBe(false);
  });

  it.each(['query', 'draft', 'cancel', 'destroy', 'identity', 'edition', 'navigation'] as const)('cancels the actual online HTTP read after %s and preserves supported recovery', async loss => {
    await open(false);
    query('Berlin');
    const task = component.searchOnline();
    const lookup = http.expectOne(request => request.url === '/api/places/search');
    if (loss === 'query') query('Paris');
    if (loss === 'draft') await coordinates('1', '2');
    if (loss === 'cancel') button(I18N.ui.buttons.cancel).click();
    if (loss === 'destroy') { fixture.destroy(); destroyed = true; }
    if (loss === 'navigation') navigation.next(new NavigationStart(1, '/other'));
    if (loss === 'identity' || loss === 'edition') {
      const checking = auth.checkStatus();
      http.expectOne('/api/auth/status').flush({ ...EDITOR,
        ...(loss === 'identity' ? { user_id: 'bob' } : { edition_authenticated: false }) });
      await checking;
      fixture.detectChanges();
    }
    expect(lookup.cancelled).toBe(true);
    await task;
    expect(component.onlineResults()).toEqual([]);
    http.expectNone('/api/photo/gps');
    if (loss === 'query' || loss === 'draft') {
      query('Fresh query');
      const retry = component.searchOnline();
      http.expectOne(request => request.url === '/api/places/search').flush({ results: [{ label: 'Fresh', latitude: 3, longitude: 4 }] });
      await retry;
      await settle();
      expect(button('Fresh')).toBeDefined();
    } else {
      await component.searchOnline();
      http.expectNone(request => request.url === '/api/places/search');
    }
  });

  it.each(['identity', 'edition', 'navigation'] as const)('discards a queued online response after %s loss and prevents another lookup', async loss => {
    await open(false);
    query('Berlin');
    const task = component.searchOnline();
    const lookup = http.expectOne(request => request.url === '/api/places/search');
    let checking: Promise<AuthStatus> | undefined;
    if (loss !== 'navigation') {
      checking = auth.checkStatus();
      http.expectOne('/api/auth/status').flush({ ...EDITOR,
        ...(loss === 'identity' ? { user_id: 'bob' } : { edition_authenticated: false }) });
    }
    lookup.flush({ results: [{ label: 'Old owner', latitude: 1, longitude: 2 }] });
    if (loss === 'navigation') navigation.next(new NavigationStart(1, '/other'));
    await Promise.all([task, checking]);
    await settle();
    expect(component.onlineResults()).toEqual([]);
    expect(dialog.close).toHaveBeenCalled();
    await component.searchOnline();
    http.expectNone(request => request.url === '/api/places/search');
    http.expectNone('/api/photo/gps');
  });

  it.each(['HTTP failure', 'malformed response'] as const)('reports %s and retries without losing offline coordinate entry', async failure => {
    await open(false);
    await coordinates('1', '2');
    query('Berlin');
    const failed = component.searchOnline();
    const lookup = http.expectOne(request => request.url === '/api/places/search');
    if (failure === 'HTTP failure') lookup.flush({}, { status: 502, statusText: 'Unavailable' });
    else lookup.flush({ results: null });
    await failed;
    await settle();
    expect(fixture.nativeElement.textContent).toContain(I18N.photo_detail.gps.online_error);
    expect(component.selectedLat()).toBe(1);
    button(I18N.photo_detail.gps.online_search).click();
    http.expectOne(request => request.url === '/api/places/search').flush({ results: [{ label: 'Retry', latitude: 3, longitude: 4 }] });
    await settle();
    expect(button('Retry')).toBeDefined();
    expect(fixture.nativeElement.textContent).not.toContain(I18N.photo_detail.gps.online_error);
  });
});
