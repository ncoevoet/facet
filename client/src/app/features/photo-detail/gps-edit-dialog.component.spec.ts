import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NEVER, of, throwError, Subject } from 'rxjs';
import { GalleryStore } from '../gallery/gallery.store';
import { Router, ActivatedRoute } from '@angular/router';
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
  let mockDialogRef: { close: Mock };
  let mockApi: { put: Mock; get: Mock; post: Mock; delete: Mock };
  let mockStore: { patchPhoto: Mock; filters: Mock; loadPhotos: Mock };
  let mockSnackBar: { open: Mock };
  let fixture: ComponentFixture<GpsEditDialogComponent>;

  beforeAll(async () => {
    ({ GpsEditDialogComponent: GpsEditDialogComponentClass } = await import('./gps-edit-dialog.component'));
  });

  function createComponent(data: GpsEditDialogData, render = false, places: SavedPlace[] = []) {
    TestBed.resetTestingModule();
    mockDialogRef = { close: vi.fn() };
    mockApi = { put: vi.fn(() => of({ gps_latitude: data.lat, gps_longitude: data.lng })), get: vi.fn(() => of({ places, recent: [] })), post: vi.fn(), delete: vi.fn() };
    mockStore = { patchPhoto: vi.fn(), filters: vi.fn(() => ({ no_gps: '' })), loadPhotos: vi.fn() };
    mockSnackBar = { open: vi.fn() };

    TestBed.configureTestingModule({
      imports: [GpsEditDialogComponentClass],
      providers: [
        GpsEditDialogComponentClass,
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: data },
        { provide: ApiService, useValue: mockApi },
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

  it('captures inputs, prevents duplicate saves and patches actual GPS even after destruction', async () => {
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
    expect(mockStore.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { gps_latitude: 3, gps_longitude: 4, gps_manually_set: 1 });
    expect(mockDialogRef.close).not.toHaveBeenCalled();
  });

  it('cancelling a pending save closes once and still applies confirmed GPS to the gallery', async () => {
    createComponent({ path: '/photo.jpg', filename: 'photo.jpg', lat: 1, lng: 2 });
    const pending = new Subject<{ gps_latitude: number; gps_longitude: number }>();
    mockApi.put.mockReturnValue(pending);
    const saving = component.save();
    component.cancel();
    pending.next({ gps_latitude: 3, gps_longitude: 4 });
    pending.complete();
    await saving;
    expect(mockDialogRef.close).toHaveBeenCalledExactlyOnceWith(undefined);
    expect(mockStore.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { gps_latitude: 3, gps_longitude: 4, gps_manually_set: 1 });
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
    const button = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>).find(b => b.textContent?.trim() === 'Work')!;
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

  it('ignores map clicks after destruction and reports a rejected pending save', async () => {
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
    expect(mockSnackBar.open).toHaveBeenCalled();
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
    expect(mockStore.loadPhotos).toHaveBeenCalledOnce();
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
  describe('missing-location membership with the real gallery store', () => {
    let store: GalleryStore;
    const photo = makePhoto({ path: '/photo.jpg', gps_latitude: null, gps_longitude: null, gps_manually_set: 1 });
    let serverPhotos = [photo];

    beforeEach(() => {
      TestBed.resetTestingModule();
      serverPhotos = [photo];
      mockApi = {
        get: vi.fn((url: string) => of(url === '/places' ? { places: [], recent: [] } : {
          photos: serverPhotos, total: serverPhotos.length, page: 1, per_page: 64, total_pages: 1, has_more: false,
        })),
        put: vi.fn(), delete: vi.fn(), post: vi.fn(() => of({})),
      };
      mockDialogRef = { close: vi.fn() };
      TestBed.configureTestingModule({
        providers: [
          GpsEditDialogComponentClass, GalleryStore,
          { provide: MAT_DIALOG_DATA, useValue: { path: '/photo.jpg', filename: 'photo.jpg', lat: null, lng: null, manuallySet: true } },
          { provide: MatDialogRef, useValue: mockDialogRef },
          { provide: ApiService, useValue: mockApi },
          { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
          { provide: AuthService, useValue: { identity: () => '0|', isEdition: () => true } },
          { provide: AlbumService, useValue: { list: () => of({ albums: [] }), update: () => of({}) } },
          { provide: I18nService, useValue: { t: (key: string) => key } },
        ],
      });
      component = TestBed.inject(GpsEditDialogComponentClass);
      store = TestBed.inject(GalleryStore);
      store.filters.update(f => ({ ...f, no_gps: '1', camera: 'Canon' }));
      store.photos.set([photo]);
      store.total.set(1);
    });

    it('returns a photo to missing-location results after saving coordinates and then clearing them', async () => {
      component.setLatitude(0);
      component.setLongitude(0);
      mockApi.put.mockReturnValueOnce(of({ gps_latitude: 0, gps_longitude: 0 }));
      serverPhotos = [];
      await component.save();
      expect(store.photos()).toEqual([]);
      expect(store.total()).toBe(0);

      component.clearLocation();
      mockApi.put.mockReturnValueOnce(of({ gps_latitude: null, gps_longitude: null }));
      serverPhotos = [photo];
      await component.save();
      expect(store.photos().map(p => p.path)).toEqual(['/photo.jpg']);
      expect(store.total()).toBe(1);
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
      expect(store.photos().map(p => p.path)).toEqual(visible ? ['/photo.jpg'] : []);
      expect(store.total()).toBe(visible ? 1 : 0);
      expect(mockApi.get).toHaveBeenCalledWith('/photos', expect.objectContaining({ no_gps: '1', camera: 'Canon' }));
      expect(store.filters()).toMatchObject({ no_gps: '1', camera: 'Canon' });
    });
  });

});
