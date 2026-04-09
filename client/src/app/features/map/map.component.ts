import {
  Component, OnInit, OnDestroy, inject, signal, effect, viewChild, ElementRef,
} from '@angular/core';
import { Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { MapFiltersService } from './map-filters.service';
import * as L from 'leaflet';
import { createLeafletMap } from '../../shared/leaflet';

interface MapCluster {
  lat: number;
  lng: number;
  count: number;
  representative_path: string;
}

interface MapPhoto {
  path: string;
  lat: number;
  lng: number;
  aggregate: number;
  filename: string;
  date_taken?: string;
  category?: string;
}

interface MapResponse {
  clusters?: MapCluster[];
  photos?: MapPhoto[];
}


@Component({
  selector: 'app-map',
  standalone: true,
  imports: [MatIconModule, MatButtonModule, MatProgressSpinnerModule],
  template: `
    <div class="relative h-full">
      @if (loading()) {
        <div class="absolute inset-0 flex items-center justify-center z-[1000] bg-black/20">
          <mat-spinner diameter="40" />
        </div>
      }
      <div #mapContainer class="h-full w-full"></div>
    </div>
  `,
  // Leaflet requires ::ng-deep styles because its DOM is created outside Angular's
  // view encapsulation — className is set via Leaflet JS API (bindTooltip),
  // not Angular templates, so Tailwind utilities cannot be used here.
  styles: [`
    :host ::ng-deep .leaflet-container {
      height: 100%;
      width: 100%;
      font-family: inherit;
    }
    :host ::ng-deep .cluster-count-label {
      background: transparent !important;
      border: none !important;
      box-shadow: none !important;
      color: white;
      font-weight: bold;
      font-size: 0.75rem;
    }
  `],
  host: { class: 'block h-full' },
})
export class MapComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly mapFilters = inject(MapFiltersService);
  private readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');

  /** Escape HTML special characters to prevent XSS in Leaflet popups. */
  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /** Translate a category key via i18n, falling back to title-cased name. */
  private translateCategory(name: string): string {
    const key = `category_names.${name}`;
    const translated = this.i18n.t(key);
    return translated === key ? name.replace(/_/g, ' ') : translated;
  }

  protected readonly loading = signal(false);

  private map: L.Map | null = null;
  private markersLayer = L.layerGroup();
  private moveEndHandler: (() => void) | null = null;
  private initTimeout: ReturnType<typeof setTimeout> | null = null;
  private moveEndDebounce: ReturnType<typeof setTimeout> | null = null;

  // Reload markers when date filters change
  private dateFilterEffect = effect(() => {
    this.mapFilters.dateFrom();
    this.mapFilters.dateTo();
    // Only reload if map is already initialized
    if (this.map) {
      this.loadMarkers();
    }
  });

  ngOnInit(): void {
    // Defer map init to next tick so the container has dimensions
    this.initTimeout = setTimeout(() => {
      this.initTimeout = null;
      this.initMap();
    }, 0);
  }

  ngOnDestroy(): void {
    if (this.initTimeout !== null) {
      clearTimeout(this.initTimeout);
    }
    if (this.moveEndDebounce !== null) {
      clearTimeout(this.moveEndDebounce);
    }
    if (this.map) {
      if (this.moveEndHandler) {
        this.map.off('moveend', this.moveEndHandler);
      }
      this.map.remove();
      this.map = null;
    }
  }

  private initMap(): void {
    const container = this.mapContainer().nativeElement;
    this.map = createLeafletMap(container).setView([48.8566, 2.3522], 5);

    this.markersLayer.addTo(this.map);

    this.moveEndHandler = () => {
      if (this.moveEndDebounce !== null) {
        clearTimeout(this.moveEndDebounce);
      }
      this.moveEndDebounce = setTimeout(() => {
        this.moveEndDebounce = null;
        this.loadMarkers();
      }, 300);
    };
    this.map.on('moveend', this.moveEndHandler);

    // Initial load
    this.loadMarkers();
  }

  private async loadMarkers(): Promise<void> {
    if (!this.map) return;

    const bounds = this.map.getBounds();
    const zoom = this.map.getZoom();
    const boundsStr = [
      bounds.getSouthWest().lat,
      bounds.getSouthWest().lng,
      bounds.getNorthEast().lat,
      bounds.getNorthEast().lng,
    ].join(',');

    this.loading.set(true);

    try {
      const params: Record<string, string | number> = { bounds: boundsStr, zoom, limit: 500 };
      const dateFrom = this.mapFilters.dateFrom();
      const dateTo = this.mapFilters.dateTo();
      if (dateFrom) params['date_from'] = dateFrom;
      if (dateTo) params['date_to'] = dateTo;

      const data = await firstValueFrom(
        this.api.get<MapResponse>('/photos/map', params),
      );

      this.markersLayer.clearLayers();

      if (data.clusters) {
        for (const cluster of data.clusters) {
          const radius = Math.min(40, Math.max(14, 10 + Math.log2(cluster.count) * 5));
          const marker = L.circleMarker([cluster.lat, cluster.lng], {
            radius,
            fillColor: '#3b82f6',
            color: '#1d4ed8',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.7,
          });

          // Count label via tooltip
          marker.bindTooltip(String(cluster.count), {
            permanent: true,
            direction: 'center',
            className: 'cluster-count-label',
          });

          if (cluster.representative_path) {
            const thumbUrl = this.escapeHtml(this.api.thumbnailUrl(cluster.representative_path, 160));
            const countLabel = this.escapeHtml(this.i18n.t('map.cluster_photos', { count: cluster.count }));
            marker.bindPopup(
              `<div style="text-align:center">` +
              `<img src="${thumbUrl}" alt="${countLabel}" style="max-width:150px;border-radius:6px;display:block;margin:0 auto" />` +
              `<div style="margin-top:4px;font-size:13px;font-weight:500">${countLabel}</div>` +
              `</div>`,
              { maxWidth: 200, minWidth: 160 },
            );
          }

          marker.addTo(this.markersLayer);
        }
      }

      if (data.photos) {
        for (const photo of data.photos) {
          const marker = L.marker([photo.lat, photo.lng]);

          const thumbUrl = this.escapeHtml(this.api.thumbnailUrl(photo.path, 160));
          const score = photo.aggregate != null ? photo.aggregate.toFixed(1) : '--';
          const scoreLabel = this.escapeHtml(this.i18n.t('map.score', { score }));
          marker.bindPopup(
            `<div style="text-align:center;cursor:pointer" data-photo-path="${this.escapeHtml(photo.path)}">` +
            `<img src="${thumbUrl}" alt="${this.escapeHtml(photo.filename)}" style="max-width:150px;border-radius:6px;display:block;margin:0 auto" />` +
            `<div style="margin-top:4px;font-size:13px">${this.escapeHtml(photo.filename)}</div>` +
            (photo.date_taken ? `<div style="font-size:11px;opacity:0.7">${this.escapeHtml(photo.date_taken)}</div>` : '') +
            `<div style="display:flex;align-items:center;justify-content:center;gap:4px;margin-top:2px;font-size:11px">` +
            (photo.category ? `<span style="background:var(--mat-sys-primary-container,#e3e8ff);color:var(--mat-sys-on-primary-container,#1a1c2e);padding:1px 6px;border-radius:10px;font-size:10px">${this.escapeHtml(this.translateCategory(photo.category))}</span>` : '') +
            `<span style="opacity:0.7">${scoreLabel}</span>` +
            `</div>` +
            `</div>`,
            { maxWidth: 200, minWidth: 160 },
          );

          marker.on('popupopen', () => {
            const popup = marker.getPopup();
            const el = popup?.getElement()?.querySelector('[data-photo-path]') as HTMLElement | null;
            el?.addEventListener('click', () => {
              this.router.navigate(['/photo'], { queryParams: { path: photo.path } });
            });
          });

          marker.addTo(this.markersLayer);
        }
      }
    } catch (err) {
      console.error('Failed to load map data', err);
    } finally {
      this.loading.set(false);
    }
  }
}
