import { TestBed } from '@angular/core/testing';
import type { Mock } from 'vitest';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';

// Mock Leaflet before importing the component. vi.doMock + dynamic import is
// used instead of vi.mock because the unit-test builder wraps spec modules,
// which defeats vi.mock hoisting and let the real Leaflet leak in under CI.
const mockMarkersLayer = {
  addTo: vi.fn().mockReturnThis(),
  clearLayers: vi.fn(),
};

const mockCircleMarker = {
  bindTooltip: vi.fn().mockReturnThis(),
  bindPopup: vi.fn().mockReturnThis(),
  addTo: vi.fn().mockReturnThis(),
};

const mockMarker = {
  bindPopup: vi.fn().mockReturnThis(),
  addTo: vi.fn().mockReturnThis(),
  on: vi.fn().mockReturnThis(),
  getPopup: vi.fn(() => ({ getElement: vi.fn(() => null) })),
};

const mockMap = {
  setView: vi.fn().mockReturnThis(),
  getBounds: vi.fn(() => ({
    getSouthWest: () => ({ lat: 40, lng: -5 }),
    getNorthEast: () => ({ lat: 55, lng: 15 }),
  })),
  getZoom: vi.fn(() => 5),
  on: vi.fn(),
  off: vi.fn(),
  remove: vi.fn(),
};

const leafletMock = {
  Icon: { Default: { mergeOptions: vi.fn() } },
  map: vi.fn(() => mockMap),
  tileLayer: vi.fn(() => ({ addTo: vi.fn() })),
  layerGroup: vi.fn(() => mockMarkersLayer),
  circleMarker: vi.fn(() => mockCircleMarker),
  marker: vi.fn(() => mockMarker),
};

vi.doMock('leaflet', () => leafletMock);

describe('MapComponent', () => {
  let MapComponent: typeof import('./map.component').MapComponent;
  let component: any;
  let mockApi: { get: Mock; thumbnailUrl: Mock };

  beforeAll(async () => {
    ({ MapComponent } = await import('./map.component'));
  });

  beforeEach(() => {
    vi.useFakeTimers();

    mockApi = {
      get: vi.fn(() => of({ clusters: [], photos: [] })),
      thumbnailUrl: vi.fn((path: string, size?: number) => `/thumbnail?path=${path}&size=${size}`),
    };

    TestBed.configureTestingModule({
      providers: [
        MapComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    component = TestBed.inject(MapComponent);
    // Provide a mock mapContainer viewChild
    Object.defineProperty(component, 'mapContainer', {
      value: () => ({ nativeElement: document.createElement('div') }),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('escapeHtml', () => {
    it('should escape HTML special characters', () => {
      expect(component.escapeHtml('<script>alert("xss")</script>')).not.toContain('<script>');
      expect(component.escapeHtml('a & b')).toBe('a &amp; b');
      // textContent/innerHTML does not escape quotes, but does escape <, >, &
      expect(component.escapeHtml('<b>bold</b>')).not.toContain('<b>');
    });

    it('should return plain text unchanged', () => {
      expect(component.escapeHtml('hello world')).toBe('hello world');
    });
  });

  describe('initMap', () => {
    it('should create a Leaflet map and set moveend handler', () => {
      const L = leafletMock;

      component.initMap();

      expect(L.map).toHaveBeenCalled();
      expect(mockMap.setView).toHaveBeenCalledWith([48.8566, 2.3522], 5);
      expect(mockMap.on).toHaveBeenCalledWith('moveend', expect.any(Function));
    });

    it('should trigger loadMarkers on init', () => {
      const spy = vi.spyOn(component, 'loadMarkers');
      component.initMap();
      expect(spy).toHaveBeenCalled();
    });
  });

  describe('loadMarkers', () => {
    beforeEach(() => {
      component.map = mockMap;
      component.markersLayer = mockMarkersLayer;
    });

    it('should return early when map is null', async () => {
      component.map = null;
      await component.loadMarkers();
      expect(mockApi.get).not.toHaveBeenCalled();
    });

    it('should call API with bounds and zoom', async () => {
      mockApi.get.mockReturnValue(of({ clusters: [], photos: [] }));
      await component.loadMarkers();

      expect(mockApi.get).toHaveBeenCalledWith('/photos/map', {
        bounds: '40,-5,55,15',
        zoom: 5,
        limit: 500,
      });
    });

    it('should set loading to false after completion', async () => {
      mockApi.get.mockReturnValue(of({ clusters: [], photos: [] }));
      await component.loadMarkers();
      expect(component.loading()).toBe(false);
    });

    it('should create circle markers for clusters', async () => {
      const L = leafletMock;
      mockApi.get.mockReturnValue(of({
        clusters: [
          { lat: 48.8, lng: 2.3, count: 10, representative_path: '/photo.jpg' },
        ],
        photos: [],
      }));

      await component.loadMarkers();

      expect(L.circleMarker).toHaveBeenCalledWith([48.8, 2.3], expect.objectContaining({
        fillColor: '#3b82f6',
      }));
      expect(mockCircleMarker.bindTooltip).toHaveBeenCalledWith('10', expect.any(Object));
      expect(mockCircleMarker.bindPopup).toHaveBeenCalled();
      expect(mockCircleMarker.addTo).toHaveBeenCalledWith(mockMarkersLayer);
    });

    it('should create standard markers for individual photos', async () => {
      const L = leafletMock;
      mockApi.get.mockReturnValue(of({
        clusters: [],
        photos: [
          { path: '/img.jpg', lat: 50, lng: 3, aggregate: 7.5, filename: 'img.jpg' },
        ],
      }));

      await component.loadMarkers();

      expect(L.marker).toHaveBeenCalledWith([50, 3]);
      expect(mockMarker.bindPopup).toHaveBeenCalled();
      expect(mockMarker.addTo).toHaveBeenCalledWith(mockMarkersLayer);
    });

    it('should handle null aggregate in photo markers', async () => {
      mockMarker.bindPopup.mockClear();
      mockApi.get.mockReturnValue(of({
        photos: [
          { path: '/img.jpg', lat: 50, lng: 3, aggregate: null, filename: 'img.jpg' },
        ],
      }));

      await component.loadMarkers();

      const popupHtml = mockMarker.bindPopup.mock.calls[0][0];
      expect(popupHtml).toContain('map.score');
    });

    it('should clear markers layer before adding new ones', async () => {
      mockApi.get.mockReturnValue(of({ clusters: [], photos: [] }));
      await component.loadMarkers();
      expect(mockMarkersLayer.clearLayers).toHaveBeenCalled();
    });

    it('should set loading false on API error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('fail')));
      await component.loadMarkers();
      expect(component.loading()).toBe(false);
    });
  });

  describe('ngOnDestroy', () => {
    it('should remove map and clean up handler', () => {
      component.map = mockMap;
      component.moveEndHandler = vi.fn();

      component.ngOnDestroy();

      expect(mockMap.off).toHaveBeenCalledWith('moveend', component.moveEndHandler);
      expect(mockMap.remove).toHaveBeenCalled();
      expect(component.map).toBeNull();
    });

    it('should do nothing when map is null', () => {
      component.map = null;
      expect(() => component.ngOnDestroy()).not.toThrow();
    });
  });
});
