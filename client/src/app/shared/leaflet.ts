import * as L from 'leaflet';

// Fix Leaflet default marker icon paths (broken when bundled). Icons are
// vendored from node_modules to /leaflet-images at build time (see angular.json
// assets) so the map works offline instead of fetching from a CDN.
L.Icon.Default.mergeOptions({
  iconRetinaUrl: '/leaflet-images/marker-icon-2x.png',
  iconUrl: '/leaflet-images/marker-icon.png',
  shadowUrl: '/leaflet-images/marker-shadow.png',
});

/** Where a map opens when it has no point to show yet (Paris). */
export const DEFAULT_MAP_CENTER = { lat: 48.8566, lng: 2.3522 } as const;

/**
 * Create a Leaflet map with the standard OSM tile layer.
 *
 * `onTileError` is wired here because `tileerror` fires on the tile layer, which
 * the caller never sees, and Leaflet does not forward it to the map. Without it a
 * tile outage is indistinguishable from an empty part of the world: the map just
 * renders a grey plane.
 */
export function createLeafletMap(
  container: HTMLElement,
  options?: L.MapOptions,
  onTileError?: () => void,
): L.Map {
  const map = L.map(container, options);
  // Let the browser load OSM tiles directly: the app service worker can fail
  // these cross-origin image requests even when the tile server is reachable.
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png?ngsw-bypass=1', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  });
  if (onTileError) tiles.on('tileerror', onTileError);
  tiles.addTo(map);
  return map;
}
