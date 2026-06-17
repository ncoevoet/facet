import { vi } from 'vitest';

// Shared Leaflet mock for every spec whose component imports `shared/leaflet`
// (map, photo-detail, gps-edit-dialog, gps-filter-map-dialog). The Angular
// Vitest builder shares one module registry per worker, so whichever spec loads
// `shared/leaflet` first binds `createLeafletMap` to its leaflet mock. When each
// spec defined its own partial mock, that binding could lack methods another
// spec relied on (e.g. map.component.spec needs getBounds/off) — an
// order-dependent CI flake. A single shared singleton makes the bound module and
// its returned objects identical regardless of load order.

export const leafletMockLayerGroup = {
  addTo: vi.fn().mockReturnThis(),
  clearLayers: vi.fn(),
};

export const leafletMockCircleMarker = {
  bindTooltip: vi.fn().mockReturnThis(),
  bindPopup: vi.fn().mockReturnThis(),
  addTo: vi.fn().mockReturnThis(),
};

export const leafletMockMarker = {
  bindTooltip: vi.fn().mockReturnThis(),
  bindPopup: vi.fn().mockReturnThis(),
  addTo: vi.fn().mockReturnThis(),
  on: vi.fn().mockReturnThis(),
  remove: vi.fn(),
  getPopup: vi.fn(() => ({ getElement: vi.fn(() => null) })),
};

export const leafletMockCircle = {
  addTo: vi.fn().mockReturnThis(),
  remove: vi.fn(),
  setRadius: vi.fn(),
};

export const leafletMockMap = {
  setView: vi.fn().mockReturnThis(),
  getBounds: vi.fn(() => ({
    getSouthWest: () => ({ lat: 40, lng: -5 }),
    getNorthEast: () => ({ lat: 55, lng: 15 }),
  })),
  getZoom: vi.fn(() => 5),
  on: vi.fn(),
  off: vi.fn(),
  remove: vi.fn(),
  invalidateSize: vi.fn(),
};

export const leafletMock = {
  Icon: { Default: { mergeOptions: vi.fn() } },
  map: vi.fn(() => leafletMockMap),
  tileLayer: vi.fn(() => ({ addTo: vi.fn() })),
  layerGroup: vi.fn(() => leafletMockLayerGroup),
  circleMarker: vi.fn(() => leafletMockCircleMarker),
  marker: vi.fn(() => leafletMockMarker),
  circle: vi.fn(() => leafletMockCircle),
};

export function resetLeafletMock(): void {
  for (const obj of [
    leafletMock,
    leafletMockMap,
    leafletMockMarker,
    leafletMockCircleMarker,
    leafletMockCircle,
    leafletMockLayerGroup,
    leafletMock.Icon.Default,
  ]) {
    for (const value of Object.values(obj)) {
      if (typeof value === 'function' && 'mockClear' in value) {
        (value as { mockClear: () => void }).mockClear();
      }
    }
  }
}
