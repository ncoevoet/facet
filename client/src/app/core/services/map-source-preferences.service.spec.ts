import { TestBed } from '@angular/core/testing';

import { OSM_TILES } from '../../shared/leaflet';
import { MapSourcePreferences } from './map-source-preferences.service';

describe('MapSourcePreferences', () => {
  beforeEach(() => {
    localStorage.removeItem('facet_map_source');
  });

  afterEach(() => {
    localStorage.removeItem('facet_map_source');
  });

  it('defaults to OSM, the source that plots EXIF GPS (WGS-84) exactly', () => {
    expect(TestBed.inject(MapSourcePreferences).source()).toBe('osm');
  });

  it('persists the choice to localStorage', () => {
    TestBed.inject(MapSourcePreferences).set('custom');
    expect(localStorage.getItem('facet_map_source')).toBe('custom');
  });

  it('a fresh instance reads the persisted choice', () => {
    TestBed.inject(MapSourcePreferences).set('custom');
    TestBed.resetTestingModule();
    expect(TestBed.inject(MapSourcePreferences).source()).toBe('custom');
  });

  it('falls back to OSM on an unknown stored value', () => {
    localStorage.setItem('facet_map_source', 'mapquest');
    expect(TestBed.inject(MapSourcePreferences).source()).toBe('osm');
  });

  it('resolves the OSM choice to the OSM tiles whatever the config says', () => {
    const prefs = TestBed.inject(MapSourcePreferences);
    expect(prefs.tiles({ map_tile_url: 'https://tiles.example/{z}/{x}/{y}.png' })).toBe(OSM_TILES);
    expect(prefs.tiles(null)).toBe(OSM_TILES);
  });

  it('resolves the custom choice to the configured tiles, with fallbacks', () => {
    const prefs = TestBed.inject(MapSourcePreferences);
    prefs.set('custom');

    expect(prefs.tiles({ map_tile_url: '/tiles/{z}/{x}/{y}.png', map_tile_attribution: '&copy; Nas', map_tile_max_zoom: 20 }))
      .toEqual({ url: '/tiles/{z}/{x}/{y}.png', attribution: '&copy; Nas', maxZoom: 20 });
    expect(prefs.tiles({ map_tile_url: '/tiles/{z}/{x}/{y}.png' }))
      .toEqual({ url: '/tiles/{z}/{x}/{y}.png', attribution: '&copy; Self-hosted map tiles', maxZoom: 19 });
    // A stale choice with nothing configured can never grey the map out.
    expect(prefs.tiles(null)).toBe(OSM_TILES);
    expect(prefs.tiles({})).toBe(OSM_TILES);
  });

  it('offers the custom switch only when a URL is configured', () => {
    const prefs = TestBed.inject(MapSourcePreferences);
    expect(prefs.hasCustom(null)).toBe(false);
    expect(prefs.hasCustom({})).toBe(false);
    expect(prefs.hasCustom({ map_tile_url: '/tiles/{z}/{x}/{y}.png' })).toBe(true);
  });
});
