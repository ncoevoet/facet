import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';

// Mock Leaflet before importing the component
const mockMarkersLayer = {
  addTo: jest.fn().mockReturnThis(),
  clearLayers: jest.fn(),
};

const mockCircleMarker = {
  bindTooltip: jest.fn().mockReturnThis(),
  bindPopup: jest.fn().mockReturnThis(),
  addTo: jest.fn().mockReturnThis(),
};

const mockMarker = {
  bindPopup: jest.fn().mockReturnThis(),
  addTo: jest.fn().mockReturnThis(),
  on: jest.fn().mockReturnThis(),
  getPopup: jest.fn(() => ({ getElement: jest.fn(() => null) })),
};

const mockMap = {
  setView: jest.fn().mockReturnThis(),
  getBounds: jest.fn(() => ({
    getSouthWest: () => ({ lat: 40, lng: -5 }),
    getNorthEast: () => ({ lat: 55, lng: 15 }),
  })),
  getZoom: jest.fn(() => 5),
  on: jest.fn(),
  off: jest.fn(),
  remove: jest.fn(),
};

jest.mock('leaflet', () => ({
  Icon: { Default: { mergeOptions: jest.fn() } },
  map: jest.fn(() => mockMap),
  tileLayer: jest.fn(() => ({ addTo: jest.fn() })),
  layerGroup: jest.fn(() => mockMarkersLayer),
  circleMarker: jest.fn(() => mockCircleMarker),
  marker: jest.fn(() => mockMarker),
}));

import { MapComponent } from './map.component';

describe('MapComponent', () => {
   
  let component: any;
  let mockApi: { get: jest.Mock; thumbnailUrl: jest.Mock };

  beforeEach(() => {
    jest.useFakeTimers();

    mockApi = {
      get: jest.fn(() => of({ clusters: [], photos: [] })),
      thumbnailUrl: jest.fn((path: string, size?: number) => `/thumbnail?path=${path}&size=${size}`),
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
    jest.useRealTimers();
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
      const L = jest.requireMock('leaflet');

      component.initMap();

      expect(L.map).toHaveBeenCalled();
      expect(mockMap.setView).toHaveBeenCalledWith([48.8566, 2.3522], 5);
      expect(mockMap.on).toHaveBeenCalledWith('moveend', expect.any(Function));
    });

    it('should trigger loadMarkers on init', () => {
      const spy = jest.spyOn(component, 'loadMarkers');
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
      const L = jest.requireMock('leaflet');
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
      const L = jest.requireMock('leaflet');
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
      component.moveEndHandler = jest.fn();

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
