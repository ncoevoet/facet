import { Component, inject, signal, viewChild, ElementRef, OnInit, DestroyRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatSliderModule } from '@angular/material/slider';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import * as L from 'leaflet';
import { createLeafletMap } from '../../shared/leaflet';

export interface GpsFilterData {
  lat?: number;
  lng?: number;
  radius_km?: number;
}

@Component({
  selector: 'app-gps-filter-map-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatSliderModule, TranslatePipe],
  // Leaflet requires ::ng-deep styles because its DOM is created outside Angular's view encapsulation.
  styles: [`
    :host ::ng-deep .leaflet-container { height: 100%; width: 100%; }
  `],
  template: `
    <h2 mat-dialog-title>{{ 'gallery.select_on_map' | translate }}</h2>
    <mat-dialog-content class="!p-0">
      <div #mapContainer class="w-full" style="height:350px"></div>
      <div class="flex items-center gap-3 px-4 py-3">
        <span class="text-sm opacity-70 shrink-0">{{ 'gallery.gps_radius' | translate }}:</span>
        <mat-slider class="flex-1" [min]="1" [max]="100" [step]="1">
          <input matSliderThumb [value]="radiusKm()" (valueChange)="onRadiusChange($event)" [attr.aria-label]="'gallery.gps_radius' | translate" />
        </mat-slider>
        <span class="text-sm font-medium w-12 text-right">{{ radiusKm() }} km</span>
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'ui.buttons.cancel' | translate }}</button>
      <button mat-flat-button [disabled]="!selectedLat()" (click)="confirm()">{{ 'ui.buttons.apply' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class GpsFilterMapDialogComponent implements OnInit {
  private readonly dialogRef = inject(MatDialogRef<GpsFilterMapDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  readonly data: GpsFilterData = inject(MAT_DIALOG_DATA) ?? {};
  private readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');

  readonly selectedLat = signal<number | null>(this.data.lat ?? null);
  readonly selectedLng = signal<number | null>(this.data.lng ?? null);
  readonly radiusKm = signal(this.data.radius_km ?? 10);

  private map: L.Map | null = null;
  private marker: L.Marker | null = null;
  private circle: L.Circle | null = null;

  ngOnInit(): void {
    setTimeout(() => this.initMap(), 0);
  }

  private initMap(): void {
    const container = this.mapContainer().nativeElement;
    const lat = this.selectedLat() ?? 48.8566;
    const lng = this.selectedLng() ?? 2.3522;
    const zoom = this.selectedLat() ? 10 : 5;

    this.map = createLeafletMap(container).setView([lat, lng], zoom);

    if (this.selectedLat() && this.selectedLng()) {
      this.placeMarker(this.selectedLat()!, this.selectedLng()!);
    }

    this.map.on('click', (e: L.LeafletMouseEvent) => {
      this.selectedLat.set(e.latlng.lat);
      this.selectedLng.set(e.latlng.lng);
      this.placeMarker(e.latlng.lat, e.latlng.lng);
    });

    this.destroyRef.onDestroy(() => {
      if (this.map) { this.map.remove(); this.map = null; }
    });
  }

  private placeMarker(lat: number, lng: number): void {
    if (!this.map) return;
    if (this.marker) this.marker.remove();
    if (this.circle) this.circle.remove();

    this.marker = L.marker([lat, lng]).addTo(this.map);
    this.circle = L.circle([lat, lng], {
      radius: this.radiusKm() * 1000,
      color: '#3b82f6',
      fillOpacity: 0.15,
    }).addTo(this.map);
  }

  onRadiusChange(value: number): void {
    this.radiusKm.set(value);
    if (this.circle && this.selectedLat() && this.selectedLng()) {
      this.circle.setRadius(value * 1000);
    }
  }

  confirm(): void {
    this.dialogRef.close({
      lat: this.selectedLat(),
      lng: this.selectedLng(),
      radius_km: this.radiusKm(),
    });
  }
}
