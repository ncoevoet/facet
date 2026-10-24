import { AuthService } from '../../core/services/auth.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { Component, inject, signal, computed, effect, viewChild, ElementRef, DestroyRef, afterNextRender, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import * as L from 'leaflet';
import { createLeafletMap } from '../../shared/leaflet';
import type { components } from '../../core/api/schema';
import { GalleryStore } from '../gallery/gallery.store';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';

export interface GpsEditDialogData {
  path: string;
  filename: string;
  lat: number | null;
  lng: number | null;
  /** The photo's location was set in the viewer, so a rescan keeps it. */
  manuallySet?: boolean;
  onBatchApplied?: () => void;
  batch?: Pick<components['schemas']['BatchPhotoRequest'], 'photo_paths' | 'filters' | 'exclude'>;
}

export type SavedPlace = components['schemas']['SavedPlace'];
export type RecentPlace = components['schemas']['RecentPlace'];
type BatchGpsDraft = NonNullable<GpsEditDialogData['batch']> & { gps_latitude: number | null; gps_longitude: number | null; only_missing: boolean; saved_place_id?: number | null };
type GpsResult = components['schemas']['GpsUpdateResponse'];

@Component({
  selector: 'app-gps-edit-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule, MatSnackBarModule, TranslatePipe, FixedPipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="!flex items-center gap-2">
      <mat-icon>location_on</mat-icon><span class="truncate">{{ data.filename }}</span>
    </h2>
    <mat-dialog-content class="!px-4 !pb-2">
      <p class="text-sm mb-3">{{ (data.batch ? I18N.photo_detail.gps.batch_hint : I18N.photo_detail.gps.preview_hint) | translate }}</p>
      <label class="block text-sm mb-3">
        {{ I18N.photo_detail.gps.search | translate }}
        <input class="block w-full border rounded p-2 bg-transparent" type="search" [ngModel]="search()" (ngModelChange)="search.set($event)">
      </label>
      @if (loadingPlaces()) { <p role="status">{{ I18N.photo_detail.gps.loading | translate }}</p> }
      @if (placesError()) {
        <p role="alert">{{ placesError() | translate }}</p>
        <button mat-button (click)="loadPlaces()" [disabled]="loadingPlaces() || placeBusy()">{{ I18N.photo_detail.gps.retry | translate }}</button>
      }
      <h3 class="text-sm font-semibold">{{ I18N.photo_detail.gps.saved | translate }}</h3>
      <ul class="max-h-40 overflow-auto mb-3">
        @for (place of filteredPlaces(); track place.id) {
          <li class="flex flex-wrap items-center gap-1 border-b py-1">
            @if (editingId() === place.id) {
              <label class="grow text-sm">{{ I18N.photo_detail.gps.name | translate }}
                <input class="block w-full border rounded p-1 bg-transparent" maxlength="120" [ngModel]="editName()" (ngModelChange)="editName.set($event)">
              </label>
              <button mat-button (click)="renamePlace(place)" [disabled]="placeBusy() || !editNameValid()">{{ I18N.ui.buttons.save | translate }}</button>
              <button mat-button (click)="editingId.set(null)" [disabled]="placeBusy() || loadingPlaces()">{{ I18N.ui.buttons.cancel | translate }}</button>
            } @else {
              <button mat-button class="grow !justify-start" (click)="selectPlace(place)" [attr.aria-pressed]="selectedPlaceId() === place.id">{{ place.name }}</button>
              <button mat-button (click)="startRename(place)" [disabled]="placeBusy() || loadingPlaces()">{{ I18N.photo_detail.gps.rename | translate }}</button>
              <button mat-button (click)="deletePlace(place)" [disabled]="placeBusy() || loadingPlaces()">{{ I18N.photo_detail.gps.delete | translate }}</button>
            }
          </li>
        } @empty { @if (!loadingPlaces()) { <li class="text-sm py-2">{{ I18N.photo_detail.gps.no_places | translate }}</li> } }
      </ul>
      @if (recent().length) {
        <h3 class="text-sm font-semibold">{{ I18N.photo_detail.gps.recent | translate }}</h3>
        <ul class="max-h-24 overflow-auto mb-3">
          @for (point of recent(); track $index) {
            <li><button mat-button (click)="selectRecent(point)">{{ point.latitude | fixed:6 }}, {{ point.longitude | fixed:6 }}</button></li>
          }
        </ul>
      }
      <div #mapContainer class="w-full h-48 rounded"></div>
      @if (mapFailed()) { <p role="status" class="text-sm">{{ I18N.photo_detail.gps.map_unavailable | translate }}</p> }
      <p class="text-xs my-2">{{ I18N.photo_detail.gps_click_to_place | translate }}</p>
      <div class="flex gap-3">
        <label class="min-w-0 flex-1 text-sm">{{ I18N.photo_detail.gps.latitude | translate }}
          <input class="block w-full border rounded p-2 bg-transparent" type="number" min="-90" max="90" step="any" [ngModel]="selectedLat()" (ngModelChange)="setLatitude($event)">
        </label>
        <label class="min-w-0 flex-1 text-sm">{{ I18N.photo_detail.gps.longitude | translate }}
          <input class="block w-full border rounded p-2 bg-transparent" type="number" min="-180" max="180" step="any" [ngModel]="selectedLng()" (ngModelChange)="setLongitude($event)">
        </label>
      </div>
      @if (!coordinatesValid()) { <p role="alert" class="text-sm mt-1">{{ I18N.photo_detail.gps.invalid_coordinates | translate }}</p> }
      <div class="flex flex-wrap items-end gap-2 mt-3">
        <label class="grow text-sm">{{ I18N.photo_detail.gps.name | translate }}
          <input class="block w-full border rounded p-2 bg-transparent" maxlength="120" [ngModel]="placeName()" (ngModelChange)="placeName.set($event)">
        </label>
        <button mat-button (click)="createPlace()" [disabled]="!canCreatePlace()">{{ I18N.photo_detail.gps.save_place | translate }}</button>
      </div>
      @if (placeBusy()) { <p role="status">{{ I18N.photo_detail.gps.updating | translate }}</p> }
      @if (placeError()) { <p role="alert">{{ placeError() | translate }}</p> }
      @if (data.batch) {
        <label class="flex items-center gap-2 mt-3"><input type="checkbox" [ngModel]="onlyMissing()" (ngModelChange)="onlyMissing.set($event)">{{ I18N.photo_detail.gps.only_missing | translate }}</label>
        <p class="text-sm mt-2">{{ I18N.photo_detail.gps.batch_limit | translate }}</p>
        @if (previewCurrent()) { @if (batchPreview(); as preview) {
          <p role="status" class="mt-2">{{ I18N.photo_detail.gps.batch_preview | translate:{ changed: preview.result.changed, skipped: preview.result.skipped } }}</p>
        } }
      }
      @if (saveError()) { <p role="alert">{{ saveError() | translate }}</p> }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (!data.batch) { <button mat-button (click)="clearLocation()" class="!mr-auto">{{ I18N.photo_detail.gps_clear | translate }}</button> }
      @if (data.manuallySet) {
        <button mat-button (click)="useFileLocation()" [disabled]="saving() || placeBusy()">{{ I18N.photo_detail.gps.use_file_location | translate }}</button>
      }
      <button mat-button (click)="cancel()">{{ I18N.ui.buttons.cancel | translate }}</button>
      @if (data.batch) {
        <button mat-button (click)="previewBatch()" [disabled]="saving() || placeBusy() || !batchCoordinatesValid()">{{ I18N.photo_detail.gps.preview_batch | translate }}</button>
      }
      <button mat-flat-button (click)="save()" [disabled]="saving() || placeBusy() || (data.batch ? !canApplyBatch() : (!coordinatesValid() || unchanged()))">{{ I18N.ui.buttons.save | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class GpsEditDialogComponent {
  protected readonly I18N = i18nKeys();
  readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly owner = this.auth.status();
  private readonly url = this.router.url;
  private navigated = false;
  private readonly api = inject(ApiService);
  private readonly store = inject(GalleryStore);
  private readonly dialogRef = inject(MatDialogRef<GpsEditDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  readonly data: GpsEditDialogData = inject(MAT_DIALOG_DATA);

  readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');

  readonly selectedLat = signal<number | null>(this.data.lat);
  readonly selectedLng = signal<number | null>(this.data.lng);
  readonly saving = signal(false);
  readonly onlyMissing = signal(true);
  private readonly batchTarget = this.data.batch ? structuredClone(this.data.batch) : null;
  readonly batchCoordinatesValid = computed(() => this.coordinatesValid() && this.selectedLat() !== null && this.selectedLng() !== null);
  private readonly batchBody = computed(() => ({
    ...this.batchTarget, gps_latitude: this.selectedLat(), gps_longitude: this.selectedLng(),
    only_missing: this.onlyMissing(),
    ...(this.selectedPlaceId() === null ? {} : { saved_place_id: this.selectedPlaceId() }),
  }));
  readonly batchPreview = signal<{ body: BatchGpsDraft; result: components['schemas']['BatchGpsResponse'] } | null>(null);
  readonly previewCurrent = computed(() => !!this.batchPreview() && JSON.stringify(this.batchBody()) === JSON.stringify(this.batchPreview()!.body));
  readonly canApplyBatch = computed(() => this.batchCoordinatesValid() && this.previewCurrent() && this.batchPreview()!.result.changed > 0);

  readonly places = signal<SavedPlace[]>([]);
  readonly recent = signal<RecentPlace[]>([]);
  readonly search = signal('');
  readonly placeName = signal('');
  readonly editName = signal('');
  readonly editingId = signal<number | null>(null);
  readonly selectedPlaceId = signal<number | null>(null);
  readonly loadingPlaces = signal(false);
  readonly placeBusy = signal(false);
  readonly placesError = signal('');
  readonly placeError = signal('');
  readonly saveError = signal('');
  readonly mapFailed = signal(false);
  readonly filteredPlaces = computed(() => {
    const term = this.search().trim().toLocaleLowerCase();
    return this.places().filter(place => place.name.toLocaleLowerCase().includes(term));
  });
  readonly coordinatesValid = computed(() => {
    const lat = this.selectedLat(), lng = this.selectedLng();
    return (lat === null && lng === null) ||
      (lat !== null && lng !== null && Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180);
  });
  /** Still the coordinates the dialog opened with: saving would only pin them (gps_manually_set) without a change. */
  readonly unchanged = computed(() => this.selectedLat() === this.data.lat && this.selectedLng() === this.data.lng);
  readonly editNameValid = computed(() => this.editName().trim().length > 0 && Array.from(this.editName().trim()).length <= 120);
  readonly canCreatePlace = computed(() => !this.placeBusy() && !this.loadingPlaces() && this.coordinatesValid() && this.selectedLat() !== null && this.placeName().trim().length > 0 && Array.from(this.placeName().trim()).length <= 120 && this.places().length < 100);
  private destroyed = false;
  private dismissed = false;
  private map: L.Map | null = null;
  private marker: L.Marker | null = null;

  private current(): boolean {
    return !this.dismissed && !this.navigated && !this.destroyed && !this.destroyRef.destroyed && this.auth.status() === this.owner && this.auth.isEdition() && this.router.url === this.url;
  }

  private invalidateOwner(): void {
    this.dismissed = true;
    this.batchPreview.set(null);
    this.places.set([]);
    this.recent.set([]);
    this.dialogRef.close();
  }

  constructor() {
    effect(() => {
      if (this.auth.status() !== this.owner || !this.auth.isEdition()) this.invalidateOwner();
    });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) { this.navigated = true; this.invalidateOwner(); }
    });
    this.dialogRef.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.dismissed = true; this.batchPreview.set(null); });
    this.destroyRef.onDestroy(() => {
      this.destroyed = true;
      if (this.map) { this.map.remove(); this.map = null; }
    });
    void this.loadPlaces();
    afterNextRender(() => {
      try { this.initMap(); } catch {
        this.mapFailed.set(true);
        this.map?.remove();
        this.map = null;
      }
    });
  }

  private initMap(): void {
    const container = this.mapContainer().nativeElement;
    const lat = this.selectedLat() ?? 48.8566;
    const lng = this.selectedLng() ?? 2.3522;
    const zoom = this.selectedLat() !== null ? 13 : 5;

    this.map = createLeafletMap(container, undefined, () => { if (this.current()) this.mapFailed.set(true); }).setView([lat, lng], zoom);
    // Force Leaflet to recalculate container size after dialog renders
    this.map.invalidateSize();

    if (this.selectedLat() !== null && this.selectedLng() !== null) {
      this.placeMarker(this.selectedLat()!, this.selectedLng()!);
    }

    this.map.on('click', (e: L.LeafletMouseEvent) => {
      const wrapped = e.latlng.wrap();
      if (this.destroyed) return;
      this.selectedPlaceId.set(null);
      this.selectedLat.set(wrapped.lat);
      this.selectedLng.set(wrapped.lng);
      this.syncMarker();
    });
  }

  private placeMarker(lat: number, lng: number): void {
    if (!this.map) return;
    if (this.marker) this.marker.remove();
    this.marker = L.marker([lat, lng]).addTo(this.map);
  }

  clearLocation(): void {
    this.selectedPlaceId.set(null);
    this.selectedLat.set(null);
    this.selectedLng.set(null);
    if (this.marker) {
      this.marker.remove();
      this.marker = null;
    }
  }

  async loadPlaces(): Promise<void> {
    if (!this.current() || this.loadingPlaces() || this.placeBusy()) return;
    this.loadingPlaces.set(true);
    this.placesError.set('');
    try {
      const result = await firstValueFrom(this.api.get<components['schemas']['PlacesResponse']>('/places'));
      if (this.current()) { this.places.set(result.places); this.recent.set(result.recent); }
    } catch { if (this.current()) this.placesError.set(I18N.photo_detail.gps.load_error); }
    finally { if (this.current()) this.loadingPlaces.set(false); }
  }

  selectPlace(place: SavedPlace): void {
    this.selectRecent(place);
    this.selectedPlaceId.set(place.id);
  }

  selectRecent(point: Pick<RecentPlace, 'latitude' | 'longitude'>): void {
    this.selectedPlaceId.set(null);
    this.selectedLat.set(point.latitude);
    this.selectedLng.set(point.longitude);
    this.syncMarker();
    this.map?.setView([point.latitude, point.longitude], 13);
  }

  setLatitude(value: number | null): void {
    if (value !== this.selectedLat()) this.selectedPlaceId.set(null);
    this.selectedLat.set(value);
    this.syncMarker();
  }

  setLongitude(value: number | null): void {
    if (value !== this.selectedLng()) this.selectedPlaceId.set(null);
    this.selectedLng.set(value);
    this.syncMarker();
  }

  private syncMarker(): void {
    if (this.coordinatesValid() && this.selectedLat() !== null && this.selectedLng() !== null) this.placeMarker(this.selectedLat()!, this.selectedLng()!);
    else { this.marker?.remove(); this.marker = null; }
  }

  startRename(place: SavedPlace): void {
    this.editingId.set(place.id);
    this.editName.set(place.name);
  }

  async createPlace(): Promise<void> {
    if (!this.current() || !this.canCreatePlace()) return;
    const body = { name: this.placeName().trim(), latitude: this.selectedLat(), longitude: this.selectedLng() };
    this.placeBusy.set(true);
    this.placeError.set('');
    try {
      const place = await firstValueFrom(this.api.post<SavedPlace>('/places', body));
      if (this.current()) {
        this.places.update(places => [...places, place]);
        this.placeName.set('');
        if (this.selectedLat() === place.latitude && this.selectedLng() === place.longitude) this.selectedPlaceId.set(place.id);
      }
    } catch { if (this.current()) this.placeError.set(I18N.photo_detail.gps.place_error); }
    finally { if (this.current()) this.placeBusy.set(false); }
  }

  async renamePlace(place: SavedPlace): Promise<void> {
    if (!this.current() || this.placeBusy() || this.loadingPlaces() || !this.editNameValid()) return;
    const body = { name: this.editName().trim(), latitude: place.latitude, longitude: place.longitude };
    this.placeBusy.set(true);
    this.placeError.set('');
    try {
      const updated = await firstValueFrom(this.api.put<SavedPlace>(`/places/${place.id}`, body));
      if (this.current()) { this.places.update(places => places.map(p => p.id === updated.id ? updated : p)); this.editingId.set(null); }
    } catch { if (this.current()) this.placeError.set(I18N.photo_detail.gps.place_error); }
    finally { if (this.current()) this.placeBusy.set(false); }
  }

  async deletePlace(place: SavedPlace): Promise<void> {
    if (!this.current() || this.placeBusy() || this.loadingPlaces()) return;
    this.placeBusy.set(true);
    this.placeError.set('');
    try {
      await firstValueFrom(this.api.delete(`/places/${place.id}`));
      if (this.current()) {
        this.places.update(places => places.filter(p => p.id !== place.id));
        if (this.selectedPlaceId() === place.id) this.selectedPlaceId.set(null);
      }
    } catch { if (this.current()) this.placeError.set(I18N.photo_detail.gps.place_error); }
    finally { if (this.current()) this.placeBusy.set(false); }
  }

  cancel(): void { this.dismissed = true; this.batchPreview.set(null); this.dialogRef.close(undefined); }

  async useFileLocation(): Promise<void> {
    if (!this.current() || this.saving() || this.placeBusy()) return;

    this.saving.set(true);
    this.saveError.set('');
    try {
      const result = await firstValueFrom(this.api.delete<GpsResult>(`/photo/gps?path=${encodeURIComponent(this.data.path)}`));
      if (!this.current()) return;
      this.store.patchPhoto(this.data.path, { gps_latitude: result.gps_latitude, gps_longitude: result.gps_longitude, gps_manually_set: 0 });
      if (this.store.filters().no_gps) void this.store.loadPhotos();
      if (this.current()) this.dialogRef.close({ ...result, gps_manually_set: 0 });
    } catch {
      if (!this.current()) return;
      this.snackBar.open(this.i18n.t(I18N.notifications.connection_error), '', { duration: 3000 });
      if (this.current()) this.saveError.set(I18N.photo_detail.gps.save_error);
    } finally { if (this.current()) this.saving.set(false); }
  }

  async previewBatch(): Promise<void> {
    if (!this.current() || !this.batchTarget || this.saving() || this.placeBusy() || !this.batchCoordinatesValid()) return;
    const body = structuredClone(this.batchBody());
    this.saving.set(true);
    this.batchPreview.set(null);
    this.saveError.set('');
    try {
      const result = await firstValueFrom(this.api.post<components['schemas']['BatchGpsResponse']>('/photos/batch_gps', { ...body, preview: true }));
      if (this.current()) this.batchPreview.set({ body, result });
    } catch { if (this.current()) this.saveError.set(I18N.photo_detail.gps.batch_error); }
    finally { if (this.current()) this.saving.set(false); }
  }

  private async saveBatch(): Promise<void> {
    if (!this.current() || !this.canApplyBatch() || this.saving() || this.placeBusy()) return;
    const preview = this.batchPreview()!;
    this.saving.set(true);
    this.saveError.set('');
    try {
      const result = await firstValueFrom(this.api.post<components['schemas']['BatchGpsResponse']>('/photos/batch_gps', {
        ...preview.body, preview: false, preview_token: preview.result.preview_token,
      }));
      // A committed write remains server truth, but an expired dialog cannot
      // publish into a later session or navigation.
      if (!this.current()) return;
      this.data.onBatchApplied?.();
      void this.store.refreshPaths(null);
      this.snackBar.open(this.i18n.t(I18N.photo_detail.gps.batch_applied, { changed: result.changed, skipped: result.skipped }), '', { duration: 4000 });
      if (this.current()) this.dialogRef.close(result);
    } catch {
      if (this.current()) { this.batchPreview.set(null); this.saveError.set(I18N.photo_detail.gps.batch_error); }
    } finally { if (this.current()) this.saving.set(false); }
  }

  async save(): Promise<void> {
    if (this.batchTarget) { await this.saveBatch(); return; }
    if (!this.current() || this.saving() || this.placeBusy() || !this.coordinatesValid()) return;
    const body = {
      path: this.data.path,
      gps_latitude: this.selectedLat(),
      gps_longitude: this.selectedLng(),
      ...(this.selectedPlaceId() === null ? {} : { saved_place_id: this.selectedPlaceId() }),
    };
    this.saving.set(true);
    this.saveError.set('');
    try {
      const result = await firstValueFrom(this.api.put<GpsResult>('/photo/gps', body));
      if (!this.current()) return;
      this.store.patchPhoto(body.path, { gps_latitude: result.gps_latitude, gps_longitude: result.gps_longitude, gps_manually_set: 1 });
      if (this.store.filters().no_gps) void this.store.loadPhotos();
      if (this.current()) this.dialogRef.close(result);
    } catch {
      if (!this.current()) return;
      this.snackBar.open(this.i18n.t(I18N.notifications.connection_error), '', { duration: 3000 });
      if (this.current()) this.saveError.set(I18N.photo_detail.gps.save_error);
    } finally { if (this.current()) this.saving.set(false); }
  }
}
