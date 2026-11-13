import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import type { Mock } from 'vitest';
import { Observable, of, throwError, Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { PageContextService } from '../../core/agent/page-context.service';
import { MapFiltersService } from './map-filters.service';
import { GalleryStore } from '../gallery/gallery.store';

// Mock Leaflet before importing the component. vi.doMock + dynamic import is
// used instead of vi.mock because the unit-test builder wraps spec modules,
// which defeats vi.mock hoisting and let the real Leaflet leak in under CI. The
// mock is shared across every leaflet-using spec so the registry-cached
// shared/leaflet binding is identical regardless of spec load order.
import {
  leafletMock,
  leafletMockMap as mockMap,
  leafletMockLayerGroup as mockMarkersLayer,
  leafletMockCircleMarker as mockCircleMarker,
  leafletMockMarker as mockMarker,
  leafletMockTileLayer as mockTileLayer,
  resetLeafletMock,
} from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);

describe('MapComponent', () => {
  let MapComponent: typeof import('./map.component').MapComponent;
  let component: any;
  let mockApi: { get: Mock; thumbnailUrl: Mock };
  // The production config IS a signal; the stub must be one too, so the
  // basemap effect re-runs when the config arrives after the map init'ed.
  let cfg: ReturnType<typeof signal<{ map_tile_url?: string } | null>>;

  // Explicit hook timeout above the default 10s: under full-suite load, many
  // workers resolving dynamic import() chunks concurrently can contend for
  // longer than that, and this hook flaking looks like a broken suite rather
  // than the load-dependent timing issue it actually is.
  beforeAll(async () => {
    ({ MapComponent } = await import('./map.component'));
  }, 20000);

  beforeEach(() => {
    vi.useFakeTimers();
    resetLeafletMock();

    mockApi = {
      get: vi.fn(() => of({ clusters: [], photos: [] })),
      thumbnailUrl: vi.fn((path: string, size?: number) => `/thumbnail?path=${path}&size=${size}`),
    };
    // The basemap reads the startup config through the store; a signal stub
    // keeps the real store's auth-driven constructor effects out of this spec
    // while still exercising the config-arrives-late reactivity.
    cfg = signal<{ map_tile_url?: string } | null>({});

    TestBed.configureTestingModule({
      providers: [
        MapComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}), locale: () => 'en' } },
        { provide: GalleryStore, useValue: { config: () => cfg() } },
      ],
    });
    component = TestBed.inject(MapComponent);
    // Provide a mock mapContainer viewChild
    Object.defineProperty(component, 'mapContainer', {
      value: () => ({ nativeElement: document.createElement('div') }),
    });
  });

  afterEach(() => {
    localStorage.removeItem('facet_map_source');
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('page context', () => {
    it('registers the map page and reads its date range live', () => {
      const context = TestBed.inject(PageContextService);
      expect(context.snapshot()).toEqual({ id: 'map', date_from: '', date_to: '' });
      component.mapFilters.dateTo.set('2026-02-01');
      expect(context.snapshot()).toMatchObject({ date_to: '2026-02-01' });
    });
  });

  describe('escapeHtml', () => {
    it('should escape HTML special characters', () => {
      expect(component.escapeHtml('<script>alert("xss")</script>')).not.toContain('<script>');
      expect(component.escapeHtml('a & b')).toBe('a &amp; b');
      // textContent/innerHTML escapes <, >, & natively.
      expect(component.escapeHtml('<b>bold</b>')).not.toContain('<b>');
    });

    it('should escape quote characters so they cannot break out of a double-quoted HTML attribute', () => {
      // Every caller interpolates this into src="...", alt="..." or
      // data-photo-path="...". An unescaped `"` would close the attribute
      // early, letting the rest of the string inject a new attribute/handler.
      expect(component.escapeHtml('photo".onerror="alert(1)')).toBe('photo&quot;.onerror=&quot;alert(1)');
      expect(component.escapeHtml("it's a test")).toBe('it&#39;s a test');
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
      expect(L.tileLayer).toHaveBeenCalledWith('https://tile.openstreetmap.org/{z}/{x}/{y}.png?ngsw-bypass=1', expect.objectContaining({ attribution: expect.stringContaining('OpenStreetMap') }));
      const [tileTemplate] = (L.tileLayer as Mock).mock.calls[0] as [string];
      const tileUrl = new URL(tileTemplate.replace('{z}/{x}/{y}', '5/17/11'));
      expect(tileUrl.searchParams.get('ngsw-bypass')).toBe('1');
      expect(tileUrl.origin).toBe('https://tile.openstreetmap.org');
      expect(mockMap.setView).toHaveBeenCalledWith([0, 0], 2);
      expect(mockMap.on).toHaveBeenCalledWith('moveend', expect.any(Function));
    });

    it('swaps only the tile layer when the basemap choice changes', () => {
      const L = leafletMock;
      component.initMap();
      const callsBefore = (L.tileLayer as Mock).mock.calls.length;

      component.mapSource.set('custom');
      TestBed.tick();
      // Nothing configured yet: the choice falls back to OSM, no swap happens.
      expect(mockMap.removeLayer).not.toHaveBeenCalled();

      // The config arrives after the map is up — the persisted 'custom' choice
      // must pick it up without any further user action.
      cfg.set({ map_tile_url: 'https://tiles.example/{z}/{x}/{y}.png' });
      TestBed.tick();
      expect(mockMap.removeLayer).toHaveBeenCalledWith(mockTileLayer);
      expect((L.tileLayer as Mock).mock.calls.length).toBe(callsBefore + 1);
      const [url] = (L.tileLayer as Mock).mock.calls.at(-1) as [string];
      expect(url).toBe('https://tiles.example/{z}/{x}/{y}.png');
    });

    it('shows the source control only once a tile URL is configured', () => {
      const fixture = TestBed.createComponent(MapComponent);
      fixture.detectChanges();
      const root = fixture.nativeElement as HTMLElement;
      expect(root.querySelector('[data-map-source]')).toBeNull();

      cfg.set({ map_tile_url: 'https://tiles.example/{z}/{x}/{y}.png' });
      fixture.detectChanges();
      expect(root.querySelector('[data-map-source]')).not.toBeNull();
      fixture.destroy();
    });

    it('fits all authorized photo coordinates, including a single-location zoom cap', async () => {
      mockApi.get.mockImplementation((url: string) => url === '/photos/map/count'
        ? of({ count: 4, bounds: [37.5, 66.8, 43.2, 76.9] }) : of({ photos: [], clusters: [] }));
      component.initMap(); await Promise.resolve();
      expect(mockMap.fitBounds).toHaveBeenCalledWith([[37.5, 66.8], [43.2, 76.9]], { padding: [32, 32], maxZoom: 12, animate: false });
    });

    it('caps initial zoom for one photo location', async () => {
      mockApi.get.mockImplementation((url: string) => url === '/photos/map/count'
        ? of({ count: 1, bounds: [40, 70, 40, 70] }) : of({ photos: [], clusters: [] }));
      component.initMap(); await Promise.resolve();
      expect(mockMap.fitBounds).toHaveBeenCalledWith([[40, 70], [40, 70]], { padding: [32, 32], maxZoom: 12, animate: false });
    });

    it.each([
      { count: 1, bounds: [40, 70, 40, 70], capped: true },
      { count: 4, bounds: [37.5, 66.8, 43.2, 76.9], capped: false },
    ])('fits the initial extent with real Leaflet zoom behavior: $count locations', async ({ count, bounds, capped }) => {
      const leaflet = await vi.importActual<typeof import('leaflet')>('leaflet');
      const container = document.createElement('div');
      Object.defineProperties(container, { clientWidth: { value: 800 }, clientHeight: { value: 600 } });
      document.body.append(container);
      const realMap = leaflet.map(container, { zoomAnimation: false, fadeAnimation: false }).setView([0, 0], 2);
      mockMap.fitBounds.mockImplementation((extent: import('leaflet').LatLngBoundsExpression, options: import('leaflet').FitBoundsOptions) => {
        realMap.fitBounds(extent, options);
        return mockMap;
      });
      mockApi.get.mockImplementation((url: string) => url === '/photos/map/count'
        ? of({ count, bounds }) : of({ photos: [], clusters: [] }));
      try {
        component.initMap();
        await Promise.resolve();
        expect(realMap.getZoom()).toBe(capped ? 12 : realMap.getBoundsZoom([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], false, leaflet.point(64, 64)));
        expect(realMap.getBounds().contains([bounds[0], bounds[1]])).toBe(true);
        expect(realMap.getBounds().contains([bounds[2], bounds[3]])).toBe(true);
        if (!capped) expect(realMap.getZoom()).toBeLessThan(12);
      } finally {
        mockMap.fitBounds.mockReset().mockReturnValue(mockMap);
        realMap.remove();
        container.remove();
      }
    });

    it.each([
      { count: 1, bounds: [40, 70, Number.NaN, 70] },
      { count: 0, bounds: null },
    ])('uses the default viewport when bounds are unavailable or invalid', async data => {
      mockApi.get.mockImplementation((url: string) => url === '/photos/map/count' ? of(data) : of({ photos: [], clusters: [] }));
      component.initMap(); await Promise.resolve();
      expect(mockMap.fitBounds).not.toHaveBeenCalled();
      expect(mockApi.get.mock.calls.filter(([url]) => url === '/photos/map')).toHaveLength(1);
    });

    it('preserves a user pan made before the initial extent arrives', async () => {
      const pending = new Subject<{ count: number; bounds: number[] }>();
      mockApi.get.mockImplementation((url: string) => url === '/photos/map/count' ? pending : of({ photos: [], clusters: [] }));
      component.initMap(); component.moveEndHandler(); mockMap.fitBounds.mockClear();
      pending.next({ count: 1, bounds: [40, 70, 40, 70] }); pending.complete(); await Promise.resolve();
      expect(mockMap.fitBounds).not.toHaveBeenCalled();
    });

    it('discards a late initial extent after the map is destroyed', async () => {
      const pending = new Subject<{ count: number; bounds: number[] }>();
      mockApi.get.mockImplementation((url: string) => url === '/photos/map/count' ? pending : of({ photos: [], clusters: [] }));
      component.initMap(); component.ngOnDestroy(); mockMap.fitBounds.mockClear();
      pending.next({ count: 1, bounds: [40, 70, 40, 70] }); pending.complete(); await Promise.resolve();
      expect(mockMap.fitBounds).not.toHaveBeenCalled();
    });

    it('loads markers only after the initial extent has been resolved', async () => {
      const pending = new Subject<{ count: number; bounds: number[] }>();
      mockApi.get.mockImplementation((url: string) => url === '/photos/map/count' ? pending : of({ photos: [], clusters: [] }));
      const spy = vi.spyOn(component, 'loadMarkers');
      component.initMap();
      expect(spy).not.toHaveBeenCalled();
      pending.next({ count: 1, bounds: [40, 70, 40, 70] }); pending.complete(); await Promise.resolve();
      expect(spy).toHaveBeenCalledOnce();
    });
  });

  describe('tile outage', () => {
    /** Fire the handler `createLeafletMap` registered on the tile layer. */
    const failTiles = () => {
      const [event, handler] = mockTileLayer.on.mock.calls[0] as [string, () => void];
      expect(event).toBe('tileerror');
      handler();
    };

    it('raises the banner when the tile server fails', () => {
      component.initMap();
      expect(component.tileError()).toBe(false);

      failTiles();

      expect(component.tileError()).toBe(true);
    });

    // Every pan refetches tiles, so an outage fires this over and over: without
    // a sticky dismissal the banner the user closed would come straight back.
    it('keeps the banner down once dismissed', () => {
      component.initMap();
      failTiles();

      component.dismissTileError();
      failTiles();

      expect(component.tileError()).toBe(false);
    });
  });

  describe('data load failure', () => {
    it('raises a retryable banner when the data request fails', async () => {
      component.initMap();
      mockApi.get.mockImplementation((url: string) =>
        url === '/photos/map/count' ? of({ count: 1, bounds: null })
                                    : throwError(() => new Error('boom')));
      await component.loadMarkers();
      expect(component.loadError()).toBe(true);
    });

    it('clears the banner on the next successful load', async () => {
      mockApi.get.mockImplementation((url: string) =>
        url === '/photos/map/count' ? of({ count: 1, bounds: null })
                                    : throwError(() => new Error('boom')));
      component.initMap();
      await component.loadMarkers();
      expect(component.loadError()).toBe(true);

      mockApi.get.mockImplementation(() => of({ clusters: [], photos: [] }));
      await component.loadMarkers();
      expect(component.loadError()).toBe(false);
    });

    it('keeps the banner down once dismissed, until a load succeeds', async () => {
      component.initMap();
      mockApi.get.mockImplementation((url: string) =>
        url === '/photos/map/count' ? of({ count: 1, bounds: null })
                                    : throwError(() => new Error('boom')));
      await component.loadMarkers();

      component.dismissLoadError();
      await component.loadMarkers();
      expect(component.loadError()).toBe(false);

      // A successful load re-arms the flag: the next real failure shows again.
      mockApi.get.mockImplementation(() => of({ clusters: [], photos: [] }));
      await component.loadMarkers();
      mockApi.get.mockImplementation((url: string) =>
        url === '/photos/map/count' ? of({ count: 1, bounds: null })
                                    : throwError(() => new Error('boom')));
      await component.loadMarkers();
      expect(component.loadError()).toBe(true);
    });
  });

  it('a superseded request failing after a newer success raises no banner', async () => {
    component.initMap();
    let failStale!: (err: unknown) => void;
    mockApi.get.mockImplementation((url: string) =>
      url === '/photos/map/count' ? of({ count: 1, bounds: null })
                                  : new Observable(sub => { failStale = err => sub.error(err); }));
    const stale = component.loadMarkers();
    await Promise.resolve();

    mockApi.get.mockImplementation(() => of({ clusters: [], photos: [] }));
    await component.loadMarkers();
    failStale(new Error('boom'));
    await stale;
    expect(component.loadError()).toBe(false);
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

  describe('empty state (no photos with a location)', () => {
    function serve(count: number): void {
      mockApi.get.mockImplementation((url: string) =>
        url === '/photos/map/count' ? of({ count }) : of({ clusters: [], photos: [] }));
    }

    async function settle(): Promise<void> {
      await vi.runOnlyPendingTimersAsync();
      await Promise.resolve();
    }

    it('shows when the library has no geotagged photo at all', async () => {
      serve(0);
      component.initMap();
      await settle();
      expect(mockApi.get).toHaveBeenCalledWith('/photos/map/count');
      expect(component.noGpsResults()).toBe(true);
    });

    it('stays hidden when only the current viewport is empty', async () => {
      serve(12);
      component.initMap();
      await settle();
      expect(component.noGpsResults()).toBe(false);
    });

    it('does not reappear when a pan lands on an empty area', async () => {
      serve(12);
      component.initMap();
      await settle();
      const [, onMoveEnd] = mockMap.on.mock.calls.find(call => call[0] === 'moveend') as [string, () => void];
      onMoveEnd();
      await settle();
      expect(component.noGpsResults()).toBe(false);
    });

    it('stays hidden when the count cannot be read', async () => {
      mockApi.get.mockImplementation((url: string) =>
        url === '/photos/map/count' ? throwError(() => new Error('offline')) : of({ clusters: [], photos: [] }));
      component.initMap();
      await settle();
      expect(component.noGpsResults()).toBe(false);
    });

    it('never captures the pointer, so the map under it still pans and zooms', () => {
      const fixture = TestBed.createComponent(MapComponent);
      (fixture.componentInstance as unknown as { noGpsResults: { set(v: boolean): void } }).noGpsResults.set(true);
      fixture.detectChanges();
      const icon = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('mat-icon'))
        .find(el => el.textContent?.trim() === 'location_off') as HTMLElement;
      expect(icon).toBeTruthy();
      for (let el: HTMLElement | null = icon; el && el !== fixture.nativeElement; el = el.parentElement) {
        expect(el.classList.contains('pointer-events-auto')).toBe(false);
      }
      expect(icon.closest('.pointer-events-none')).not.toBeNull();
      fixture.destroy();
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

describe('MapComponent dates control', () => {
  let MapComponent: typeof import('./map.component').MapComponent;
  let stubConfig: { map_tile_url?: string };
  beforeAll(async () => {
    ({ MapComponent } = await import('./map.component'));
  }, 20000);
  beforeEach(() => {
    resetLeafletMock();
    stubConfig = {};
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get: vi.fn(() => of({ clusters: [], photos: [] })), thumbnailUrl: vi.fn(() => '') } },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}), locale: () => 'en' } },
        { provide: GalleryStore, useValue: { config: () => stubConfig } },
      ],
    });
  });

  it('opens the dates in a control popover above the Leaflet panes, not a details element', async () => {
    const fixture = TestBed.createComponent(MapComponent);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('details')).toBeNull();
    const wrapper = root.querySelector<HTMLElement>('[data-map-dates]')!;
    // The dates pill and the basemap pill share one floating row above the
    // Leaflet panes; the row carries the stacking, the pill sits inside it.
    const float = wrapper.parentElement!;
    expect(float.classList.contains('z-[1001]')).toBe(true);
    expect(float.classList.contains('absolute')).toBe(true);
    const trigger = wrapper.querySelector<HTMLButtonElement>('app-control-popover button')!;
    expect(trigger.querySelector('mat-icon')!.textContent!.trim()).toBe('date_range');
    trigger.click(); fixture.detectChanges();
    expect(document.querySelector('app-date-range-filter mat-form-field')).not.toBeNull();
    fixture.destroy();
  });

  it('marks the trigger when a date is set', () => {
    const fixture = TestBed.createComponent(MapComponent);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-map-dates-dot]')).toBeNull();
    TestBed.inject(MapFiltersService).dateFrom.set('2024-01-01'); fixture.detectChanges();
    expect(root.querySelector('[data-map-dates-dot]')).not.toBeNull();
    fixture.destroy();
  });

  describe('date inputs', () => {
    const setInput = (fixture: { detectChanges(): void }, which: 'from' | 'to', value: string) => {
      const inputs = document.querySelectorAll<HTMLInputElement>('app-date-range-filter input[type="date"]');
      const input = inputs[which === 'from' ? 0 : 1];
      input.value = value;
      input.dispatchEvent(new Event('change'));
      fixture.detectChanges();
    };

    it('requests markers with date_from, shows the dot for date-to alone, and hides it once both are cleared', async () => {
      const api = TestBed.inject(ApiService) as unknown as { get: Mock };
      const fixture = TestBed.createComponent(MapComponent);
      fixture.detectChanges();
      (fixture.componentInstance as any).map = mockMap;
      const root = fixture.nativeElement as HTMLElement;
      const filters = TestBed.inject(MapFiltersService);
      root.querySelector<HTMLButtonElement>('[data-map-dates] app-control-popover button')!.click();
      fixture.detectChanges();
      api.get.mockClear();
      setInput(fixture, 'from', '2024-03-01');
      expect(filters.dateFrom()).toBe('2024-03-01');
      await fixture.whenStable();
      expect(api.get).toHaveBeenCalledWith('/photos/map', expect.objectContaining({ date_from: '2024-03-01' }));
      expect(root.querySelector('[data-map-dates-dot]')).not.toBeNull();
      setInput(fixture, 'from', '');
      expect(filters.dateFrom()).toBe('');
      expect(root.querySelector('[data-map-dates-dot]')).toBeNull();
      setInput(fixture, 'to', '2024-04-01');
      expect(filters.dateTo()).toBe('2024-04-01');
      expect(root.querySelector('[data-map-dates-dot]')).not.toBeNull();
      setInput(fixture, 'to', '');
      expect(filters.dateTo()).toBe('');
      expect(root.querySelector('[data-map-dates-dot]')).toBeNull();
      fixture.destroy();
    });
  });
});
