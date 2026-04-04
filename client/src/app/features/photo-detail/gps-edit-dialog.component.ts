import { Component, inject, signal, viewChild, ElementRef, DestroyRef, afterNextRender } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import * as L from 'leaflet';
import { createLeafletMap } from '../../shared/leaflet';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';

export interface GpsEditDialogData {
  path: string;
  filename: string;
  lat: number | null;
  lng: number | null;
}

@Component({
  selector: 'app-gps-edit-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule, MatSnackBarModule, TranslatePipe, FixedPipe],
  // Leaflet requires ::ng-deep styles because its DOM is created outside Angular's view encapsulation.
  styles: [`
    :host ::ng-deep .leaflet-container { width: 100%; }
  `],
  template: `
    <h2 mat-dialog-title class="!flex items-center gap-2">
      <mat-icon class="!text-xl !w-5 !h-5 !leading-5 shrink-0">location_on</mat-icon>
      <span class="truncate">{{ data.filename }}</span>
    </h2>
    <mat-dialog-content class="!p-0">
      <div #mapContainer class="w-full h-64"></div>
      <div class="px-4 py-2 text-xs text-[var(--mat-sys-on-surface-variant)]">
        @if (selectedLat() !== null) {
          {{ selectedLat()! | fixed:6 }}, {{ selectedLng()! | fixed:6 }}
        } @else {
          {{ 'photo_detail.gps_click_to_place' | translate }}
        }
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (selectedLat() !== null) {
        <button mat-button (click)="clearLocation()" class="!mr-auto">{{ 'photo_detail.gps_clear' | translate }}</button>
      }
      <button mat-button mat-dialog-close>{{ 'ui.buttons.cancel' | translate }}</button>
      <button mat-flat-button (click)="save()" [disabled]="saving()">{{ 'ui.buttons.save' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class GpsEditDialogComponent {
  private readonly api = inject(ApiService);
  private readonly dialogRef = inject(MatDialogRef<GpsEditDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  readonly data: GpsEditDialogData = inject(MAT_DIALOG_DATA);

  readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');

  readonly selectedLat = signal<number | null>(this.data.lat);
  readonly selectedLng = signal<number | null>(this.data.lng);
  readonly saving = signal(false);

  private map: L.Map | null = null;
  private marker: L.Marker | null = null;

  constructor() {
    this.destroyRef.onDestroy(() => {
      if (this.map) { this.map.remove(); this.map = null; }
    });
    afterNextRender(() => this.initMap());
  }

  private initMap(): void {
    const container = this.mapContainer().nativeElement;
    const lat = this.selectedLat() ?? 48.8566;
    const lng = this.selectedLng() ?? 2.3522;
    const zoom = this.selectedLat() !== null ? 13 : 5;

    this.map = createLeafletMap(container).setView([lat, lng], zoom);
    // Force Leaflet to recalculate container size after dialog renders
    this.map.invalidateSize();

    if (this.selectedLat() !== null && this.selectedLng() !== null) {
      this.placeMarker(this.selectedLat()!, this.selectedLng()!);
    }

    this.map.on('click', (e: L.LeafletMouseEvent) => {
      this.selectedLat.set(e.latlng.lat);
      this.selectedLng.set(e.latlng.lng);
      this.placeMarker(e.latlng.lat, e.latlng.lng);
    });
  }

  private placeMarker(lat: number, lng: number): void {
    if (!this.map) return;
    if (this.marker) this.marker.remove();
    this.marker = L.marker([lat, lng]).addTo(this.map);
  }

  clearLocation(): void {
    this.selectedLat.set(null);
    this.selectedLng.set(null);
    if (this.marker) {
      this.marker.remove();
      this.marker = null;
    }
  }

  async save(): Promise<void> {
    this.saving.set(true);
    try {
      await firstValueFrom(this.api.put('/photo/gps', {
        path: this.data.path,
        gps_latitude: this.selectedLat(),
        gps_longitude: this.selectedLng(),
      }));
      this.dialogRef.close({
        gps_latitude: this.selectedLat(),
        gps_longitude: this.selectedLng(),
      });
    } catch {
      this.snackBar.open(this.i18n.t('notifications.connection_error'), '', { duration: 3000 });
    } finally {
      this.saving.set(false);
    }
  }
}
