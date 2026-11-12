import * as L from 'leaflet';

// Fix Leaflet default marker icon paths (broken when bundled). Icons are
// vendored from node_modules to /leaflet-images at build time (see angular.json
// assets) so the map works offline instead of fetching from a CDN.
L.Icon.Default.mergeOptions({
  iconRetinaUrl: '/leaflet-images/marker-icon-2x.png',
  iconUrl: '/leaflet-images/marker-icon.png',
  shadowUrl: '/leaflet-images/marker-shadow.png',
});

/** The basemap tiles one map renders. OSM is the default everywhere: it plots
 *  the WGS-84 coordinates EXIF GPS carries exactly. A self-hosted alternative
 *  (`viewer.map_tile_url`) replaces it when the operator configures one and
 *  the user picks it — Facet embeds no third-party commercial tiles (Google's
 *  terms forbid that), so the operator points at a server whose terms they
 *  control, typically behind the same reverse proxy. */
export interface TileSpec {
  url: string;
  attribution: string;
  maxZoom: number;
}

export const OSM_TILES: TileSpec = {
  // Let the browser load tiles directly: the app service worker can fail
  // these cross-origin image requests even when the tile server is reachable.
  url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png?ngsw-bypass=1',
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom: 19,
};

function buildTileLayer(tiles: TileSpec, onTileError?: () => void): L.TileLayer {
  const layer = L.tileLayer(tiles.url, { attribution: tiles.attribution, maxZoom: tiles.maxZoom });
  if (onTileError) layer.on('tileerror', onTileError);
  return layer;
}

// The tile layer per live map, so a source switch can remove exactly the one
// it added and nothing else (a marker group is never touched by this). The
// applied spec rides along: the basemap effect re-runs on every config change,
// and re-adding an identical layer would flash the tiles for nothing.
const tileLayers = new WeakMap<L.Map, L.TileLayer>();
const appliedSpecs = new WeakMap<L.Map, TileSpec>();

function sameSpec(a: TileSpec, b: TileSpec): boolean {
  return a.url === b.url && a.attribution === b.attribution && a.maxZoom === b.maxZoom;
}

/**
 * Create a Leaflet map with the chosen tiles (OSM unless told otherwise).
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
  tiles: TileSpec = OSM_TILES,
): L.Map {
  const map = L.map(container, options);
  const layer = buildTileLayer(tiles, onTileError);
  tileLayers.set(map, layer);
  appliedSpecs.set(map, tiles);
  layer.addTo(map);
  return map;
}

/** Swap the basemap of a live map, keeping zoom, centre and markers. */
export function setMapSource(map: L.Map, tiles: TileSpec, onTileError?: () => void): void {
  const applied = appliedSpecs.get(map);
  if (applied && sameSpec(applied, tiles)) return;
  const current = tileLayers.get(map);
  if (current) map.removeLayer(current);
  const layer = buildTileLayer(tiles, onTileError);
  tileLayers.set(map, layer);
  appliedSpecs.set(map, tiles);
  layer.addTo(map);
}
