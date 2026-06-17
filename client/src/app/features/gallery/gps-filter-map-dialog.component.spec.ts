import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import type { GpsFilterMapDialogComponent } from './gps-filter-map-dialog.component';

// Mock Leaflet via vi.doMock + dynamic import: the unit-test builder wraps
// spec modules, which defeats vi.mock hoisting and can leak the real Leaflet. The
// shared singleton makes every leaflet-using spec's registry binding identical.
import { leafletMock } from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);

describe('GpsFilterMapDialogComponent', () => {
  let GpsFilterMapDialogComponentClass: typeof GpsFilterMapDialogComponent;
  let component: GpsFilterMapDialogComponent;
  let mockDialogRef: { close: Mock };

  beforeAll(async () => {
    ({ GpsFilterMapDialogComponent: GpsFilterMapDialogComponentClass } = await import('./gps-filter-map-dialog.component'));
  });

  function createComponent(data: Record<string, unknown> = {}) {
    TestBed.resetTestingModule();
    mockDialogRef = { close: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        GpsFilterMapDialogComponentClass,
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    component = TestBed.inject(GpsFilterMapDialogComponentClass);
  }

  it('should initialize with default values when no data provided', () => {
    createComponent();

    expect(component.selectedLat()).toBeNull();
    expect(component.selectedLng()).toBeNull();
    expect(component.radiusKm()).toBe(10);
  });

  it('should initialize with provided data', () => {
    createComponent({ lat: 48.8566, lng: 2.3522, radius_km: 25 });

    expect(component.selectedLat()).toBe(48.8566);
    expect(component.selectedLng()).toBe(2.3522);
    expect(component.radiusKm()).toBe(25);
  });

  it('should update radius on onRadiusChange', () => {
    createComponent();

    component.onRadiusChange(50);

    expect(component.radiusKm()).toBe(50);
  });

  it('should close dialog with coordinates on confirm', () => {
    createComponent({ lat: 48.8566, lng: 2.3522, radius_km: 10 });

    component.confirm();

    expect(mockDialogRef.close).toHaveBeenCalledWith({
      lat: 48.8566,
      lng: 2.3522,
      radius_km: 10,
    });
  });

  it('should close dialog with null lat when no location selected', () => {
    createComponent();

    component.confirm();

    expect(mockDialogRef.close).toHaveBeenCalledWith({
      lat: null,
      lng: null,
      radius_km: 10,
    });
  });
});
