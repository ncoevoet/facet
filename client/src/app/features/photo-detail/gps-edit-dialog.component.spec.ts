import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import type { GpsEditDialogComponent, GpsEditDialogData } from './gps-edit-dialog.component';

// Mock Leaflet via vi.doMock + dynamic import: the unit-test builder wraps
// spec modules, which defeats vi.mock hoisting and can leak the real Leaflet. The
// shared singleton makes every leaflet-using spec's registry binding identical.
import { leafletMock } from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);

describe('GpsEditDialogComponent', () => {
  let GpsEditDialogComponentClass: typeof GpsEditDialogComponent;
  let component: GpsEditDialogComponent;
  let mockDialogRef: { close: Mock };
  let mockApi: { put: Mock };
  let mockSnackBar: { open: Mock };

  beforeAll(async () => {
    ({ GpsEditDialogComponent: GpsEditDialogComponentClass } = await import('./gps-edit-dialog.component'));
  });

  function createComponent(data: GpsEditDialogData) {
    TestBed.resetTestingModule();
    mockDialogRef = { close: vi.fn() };
    mockApi = { put: vi.fn(() => of({})) };
    mockSnackBar = { open: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        GpsEditDialogComponentClass,
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: data },
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    component = TestBed.inject(GpsEditDialogComponentClass);
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
});
