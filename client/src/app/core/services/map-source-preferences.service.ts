import { Injectable, signal } from '@angular/core';

import { OSM_TILES, TileSpec } from '../../shared/leaflet';

const STORAGE_KEY = 'facet_map_source';

export type MapSourceChoice = 'osm' | 'custom';

/** The `/api/config` fields the basemap choice reads. */
export interface MapTileConfig {
  map_tile_url?: string;
  map_tile_attribution?: string;
  map_tile_max_zoom?: number;
}

/** Per-browser basemap choice, persisted in localStorage like the thumbnail
 *  ratio and the card actions — a viewing preference of this browser, never
 *  library data or a server query parameter. OSM is the default: it plots the
 *  WGS-84 coordinates EXIF GPS carries exactly. The custom pick only renders
 *  when the operator configured `viewer.map_tile_url`, so a stale choice can
 *  never grey the map out. */
@Injectable({ providedIn: 'root' })
export class MapSourcePreferences {
  readonly source = signal<MapSourceChoice>(this.read());

  /** The tiles to render for the current choice. */
  tiles(config: MapTileConfig | null | undefined): TileSpec {
    if (this.source() === 'custom' && config?.map_tile_url) {
      return {
        url: config.map_tile_url,
        attribution: config.map_tile_attribution || '&copy; Self-hosted map tiles',
        maxZoom: typeof config.map_tile_max_zoom === 'number' ? config.map_tile_max_zoom : 19,
      };
    }
    return OSM_TILES;
  }

  /** Whether the switch to the custom source is offered at all. */
  hasCustom(config: MapTileConfig | null | undefined): boolean {
    return !!config?.map_tile_url;
  }

  set(source: MapSourceChoice): void {
    this.source.set(source);
    try { localStorage.setItem(STORAGE_KEY, source); } catch { /* browser storage unavailable */ }
  }

  private read(): MapSourceChoice {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'custom' ? 'custom' : 'osm';
    } catch { return 'osm'; }
  }
}
