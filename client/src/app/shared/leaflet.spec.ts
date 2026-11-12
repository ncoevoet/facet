import type { Mock } from 'vitest';

import {
  leafletMock,
  leafletMockMap as mockMap,
  leafletMockTileLayer as mockTileLayer,
  resetLeafletMock,
} from '../../testing/leaflet-mock';

// Mock Leaflet before importing the module. vi.doMock + dynamic import is used
// instead of vi.mock because the unit-test builder wraps spec modules, which
// defeats vi.mock hoisting — a static import of shared/leaflet here would bind
// the real Leaflet before the mock applies. The mock is shared across every
// leaflet-using spec so the registry-cached shared/leaflet binding is
// identical regardless of spec load order.

vi.doMock('leaflet', () => leafletMock);

describe('basemap tiles', () => {
  let createLeafletMap: typeof import('./leaflet').createLeafletMap;
  let setMapSource: typeof import('./leaflet').setMapSource;
  let OSM_TILES: typeof import('./leaflet').OSM_TILES;

  beforeAll(async () => {
    ({ createLeafletMap, setMapSource, OSM_TILES } = await import('./leaflet'));
  }, 20000);

  beforeEach(() => {
    resetLeafletMock();
  });

  it('defaults to the OSM layer', () => {
    createLeafletMap(document.createElement('div'), undefined, () => undefined);
    expect(mockTileLayer.on).toHaveBeenCalledWith('tileerror', expect.any(Function));
    const [url, options] = (leafletMock.tileLayer as Mock).mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe(OSM_TILES.url);
    expect(url).toBe('https://tile.openstreetmap.org/{z}/{x}/{y}.png?ngsw-bypass=1');
    expect(options['attribution']).toContain('OpenStreetMap');
    expect(options['maxZoom']).toBe(19);
  });

  it('renders a self-hosted spec with its own attribution and max zoom', () => {
    createLeafletMap(document.createElement('div'), undefined, undefined,
      { url: 'https://tiles.example/{z}/{x}/{y}.png', attribution: '&copy; Example', maxZoom: 20 });
    const [url, options] = (leafletMock.tileLayer as Mock).mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe('https://tiles.example/{z}/{x}/{y}.png');
    expect(options['attribution']).toBe('&copy; Example');
    expect(options['maxZoom']).toBe(20);
  });

  it('swaps the tile layer in place, keeping the map object', () => {
    const map = createLeafletMap(document.createElement('div'), undefined, undefined, OSM_TILES);
    expect(map).toBe(mockMap);
    const callsBefore = (leafletMock.tileLayer as Mock).mock.calls.length;

    setMapSource(map, { url: 'https://tiles.example/{z}/{x}/{y}.png', attribution: 'x', maxZoom: 19 });

    expect(mockMap.removeLayer).toHaveBeenCalledWith(mockTileLayer);
    expect((leafletMock.tileLayer as Mock).mock.calls.length).toBe(callsBefore + 1);
    const [url] = (leafletMock.tileLayer as Mock).mock.calls.at(-1) as [string];
    expect(url).toBe('https://tiles.example/{z}/{x}/{y}.png');
  });

  it('rewires the tile-error handler on every real swap', () => {
    const onTileError = (): void => undefined;
    const map = createLeafletMap(document.createElement('div'), undefined, onTileError, OSM_TILES);
    const handlerCalls = (mockTileLayer.on as Mock).mock.calls.length;

    // An identical spec is a no-op (no pointless tile flash): no rewire either.
    setMapSource(map, OSM_TILES, onTileError);
    expect((mockTileLayer.on as Mock).mock.calls.length).toBe(handlerCalls);

    setMapSource(map, { url: 'https://tiles.example/{z}/{x}/{y}.png', attribution: 'x', maxZoom: 19 }, onTileError);
    expect((mockTileLayer.on as Mock).mock.calls.length).toBe(handlerCalls + 1);
    expect((mockTileLayer.on as Mock).mock.calls.at(-1)).toEqual(['tileerror', onTileError]);
  });
});
