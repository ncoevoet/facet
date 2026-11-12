import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpContext } from '@angular/common/http';
import { Component, inject, signal, computed, effect, viewChild, ElementRef, DestroyRef, afterNextRender, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom, Subject, takeUntil } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import * as L from 'leaflet';
import { createLeafletMap, DEFAULT_MAP_CENTER } from '../../shared/leaflet';
import type { components } from '../../core/api/schema';
import { GalleryStore } from '../gallery/gallery.store';
import { ApiService } from '../../core/services/api.service';
import { GeoPhotosService } from '../../core/services/geo-photos.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { normalizeOnlineQuery } from './online-query';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { HANDLE_PLACE_SEARCH_ERRORS_LOCALLY } from '../../core/utils/place-search-error.util';
import { googleMapsSearchUrl, isResolvableMapsLink, parseGoogleMapsInput, type LatLng, MAPS_LINK_MAX_INPUT } from '../../shared/utils/google-maps-link';

/** The keyCode browsers report for a keydown the IME is still processing. */
const IME_PROCESS_KEY_CODE = 229;

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
type MapsLinkResponse = components['schemas']['MapsLinkResponse'];

@Component({
  selector: 'app-gps-edit-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule, MatSnackBarModule, TranslatePipe, FixedPipe, PluralKeyPipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="!flex !items-center !gap-3 !text-base !font-semibold !m-0 !px-4 !pt-5 !pb-4 before:!content-none">
      <span class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
        <mat-icon aria-hidden="true" class="!text-xl !leading-none !w-5 !h-5 text-[var(--mat-sys-on-primary-container)]">location_on</mat-icon>
      </span>
      <span class="truncate">{{ data.filename }}</span>
    </h2>
    <mat-dialog-content class="!px-4 !pb-2">
      <p class="text-sm mb-3">{{ (data.batch ? I18N.photo_detail.gps.batch_hint : I18N.photo_detail.gps.preview_hint) | translate }}</p>
      <label class="block text-sm mb-3">
        {{ I18N.photo_detail.gps.search | translate }}
        <input class="block w-full border rounded p-2 bg-transparent" type="search" [ngModel]="search()" (ngModelChange)="search.set($event)">
      </label>
      <label class="block text-sm mb-2">
        {{ I18N.photo_detail.gps.online_query | translate }}
        <!-- Native maxlength counts UTF-16 units; the request guard limits code points to 200. -->
        <input class="block w-full border rounded p-2 bg-transparent" type="search" maxlength="400" aria-describedby="gps-online-notice" [ngModel]="onlineQuery()" (ngModelChange)="setOnlineQuery($event)" (keydown.enter)="onOnlineEnter($event)">
      </label>
      <p id="gps-online-notice" class="text-xs mb-2">{{ I18N.photo_detail.gps.online_notice | translate }}</p>
      <p class="text-xs mb-2"><a href="https://photon.komoot.io" target="_blank" rel="noopener noreferrer">Photon<span class="sr-only"> {{ I18N.photo_detail.gps.opens_new_tab | translate }}</span></a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">{{ I18N.photo_detail.gps.osm_attribution | translate }}<span class="sr-only"> {{ I18N.photo_detail.gps.opens_new_tab | translate }}</span></a></p>
      <button mat-stroked-button (click)="searchOnline()" [disabled]="saving() || onlineBusy() || !onlineQueryValid() || !onlineEnabled() || !auth.isEdition()"><mat-icon>search</mat-icon>{{ I18N.photo_detail.gps.online_search | translate }}</button>
      @if (!onlineEnabled()) { <p role="status">{{ I18N.photo_detail.gps.online_disabled | translate }}</p> }
      @if (onlineBusy()) { <p role="status">{{ I18N.photo_detail.gps.online_loading | translate }}</p> }
      @if (onlineError()) { <p role="alert">{{ onlineError() | translate }}</p> }
      @if (onlineSearched() && !onlineResults().length) { <p role="status">{{ I18N.photo_detail.gps.online_empty | translate }}</p> }
      <p role="status" class="sr-only">@if (onlineResults().length) { {{ onlineResults().length | pluralKey:I18N.photo_detail.gps.online_results:I18N.photo_detail.gps.online_results_plural | translate:{ count: onlineResults().length } }} }</p>
      <ul class="m-0 max-h-40 list-none overflow-y-auto overflow-x-hidden p-0 mb-3" [attr.aria-label]="I18N.photo_detail.gps.online_results_label | translate">
        @for (result of onlineResults(); track $index) {
          <li><button mat-button class="!h-auto !py-2 !text-left" (click)="selectOnlineResult(result)">{{ result.label }}</button></li>
        }
      </ul>
      <div class="flex flex-wrap items-end gap-2">
        <label class="grow text-sm">{{ I18N.photo_detail.gps.maps_link | translate }}
          <input class="block w-full border rounded p-2 bg-transparent" type="text" inputmode="url" autocomplete="off" spellcheck="false" [attr.maxlength]="mapsMaxInput" aria-describedby="gps-maps-hint" [ngModel]="mapsInput()" (ngModelChange)="setMapsInput($event)" (paste)="onMapsPaste($event)" (keydown.enter)="onMapsEnter($event)">
        </label>
        <button mat-button (click)="applyMapsInput()" [disabled]="saving() || mapsBusy() || !mapsInput().trim()">{{ I18N.photo_detail.gps.maps_go | translate }}</button>
      </div>
      <p id="gps-maps-hint" class="text-xs mt-1 mb-2">{{ I18N.photo_detail.gps.maps_hint | translate }}</p>
      @if (mapsBusy()) { <p role="status" class="text-sm">{{ I18N.photo_detail.gps.maps_resolving | translate }}</p> }
      @if (mapsError()) { <p role="alert" class="text-sm">{{ mapsError() | translate }}</p> }
      <p role="status" class="text-sm">@if (mapsPoint(); as point) { {{ I18N.photo_detail.gps.maps_moved | translate:{ lat: (point.lat | fixed:6), lng: (point.lng | fixed:6) } }} }</p>
      <button mat-button class="mb-3" (click)="openGoogleMaps()"><mat-icon>open_in_new</mat-icon>{{ I18N.photo_detail.gps.maps_pick | translate }}<span class="sr-only"> {{ I18N.photo_detail.gps.opens_new_tab | translate }}</span></button>
      @if (loadingPlaces()) { <p role="status">{{ I18N.photo_detail.gps.loading | translate }}</p> }
      @if (placesError()) {
        <p role="alert">{{ placesError() | translate }}</p>
        <button mat-stroked-button (click)="loadPlaces()" [disabled]="loadingPlaces() || placeBusy()">{{ I18N.photo_detail.gps.retry | translate }}</button>
      }
      <h3 class="text-sm font-semibold">{{ I18N.photo_detail.gps.saved | translate }}</h3>
      <ul class="m-0 max-h-40 list-none overflow-y-auto overflow-x-hidden p-0 mb-3">
        @for (place of filteredPlaces(); track place.id) {
          <li class="flex flex-wrap items-center gap-1 border-b py-1">
            @if (editingId() === place.id) {
              <label class="grow text-sm">{{ I18N.photo_detail.gps.name | translate }}
                <input class="block w-full border rounded p-1 bg-transparent" maxlength="120" [ngModel]="editName()" (ngModelChange)="editName.set($event)">
              </label>
              <button mat-flat-button (click)="renamePlace(place)" [disabled]="placeBusy() || !editNameValid()">{{ I18N.ui.buttons.save | translate }}</button>
              <button mat-button (click)="editingId.set(null)" [disabled]="placeBusy() || loadingPlaces()">{{ I18N.ui.buttons.cancel | translate }}</button>
            } @else {
              <button mat-button class="grow !justify-start" [class.!bg-[var(--mat-sys-secondary-container)]]="selectedPlaceId() === place.id" (click)="selectPlace(place)" [attr.aria-pressed]="selectedPlaceId() === place.id"><mat-icon>{{ selectedPlaceId() === place.id ? 'check_circle' : 'place' }}</mat-icon>{{ place.name }}</button>
              <button mat-icon-button (click)="startRename(place)" [disabled]="placeBusy() || loadingPlaces()" [attr.title]="I18N.photo_detail.gps.rename | translate" [attr.aria-label]="I18N.photo_detail.gps.rename | translate"><mat-icon aria-hidden="true">edit</mat-icon></button>
              <button mat-icon-button class="!text-[var(--mat-sys-error)]" (click)="deletePlace(place)" [disabled]="placeBusy() || loadingPlaces()" [attr.title]="I18N.photo_detail.gps.delete | translate" [attr.aria-label]="I18N.photo_detail.gps.delete | translate"><mat-icon aria-hidden="true">delete</mat-icon></button>
            }
          </li>
        } @empty { @if (!loadingPlaces()) { <li class="text-sm py-2">{{ I18N.photo_detail.gps.no_places | translate }}</li> } }
      </ul>
      @if (recent().length) {
        <h3 class="text-sm font-semibold">{{ I18N.photo_detail.gps.recent | translate }}</h3>
        <ul class="m-0 max-h-24 list-none overflow-y-auto overflow-x-hidden p-0 mb-3">
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
        <button mat-stroked-button (click)="createPlace()" [disabled]="!canCreatePlace()"><mat-icon>bookmark_add</mat-icon>{{ I18N.photo_detail.gps.save_place | translate }}</button>
      </div>
      @if (placeBusy()) { <p role="status">{{ I18N.photo_detail.gps.updating | translate }}</p> }
      @if (placeError()) { <p role="alert">{{ placeError() | translate }}</p> }
      @if (data.batch) {
        <label class="flex items-center gap-2 mt-3"><input type="checkbox" [ngModel]="onlyMissing()" (ngModelChange)="onlyMissing.set($event)">{{ I18N.photo_detail.gps.only_missing | translate }}</label>
        <p class="text-sm mt-2">{{ I18N.photo_detail.gps.batch_limit | translate }}</p>
        @if (previewCurrent()) { @if (batchPreview(); as preview) {
          <p role="status" class="mt-2">{{ preview.result.changed | pluralKey:I18N.photo_detail.gps.batch_preview:I18N.photo_detail.gps.batch_preview_plural | translate:{ changed: preview.result.changed, skipped: preview.result.skipped } }}</p>
        } }
      }
      @if (saveError()) { <p role="alert">{{ saveError() | translate }}</p> }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (!data.batch) { <button mat-button (click)="clearLocation()" class="!mr-auto !text-[var(--mat-sys-error)]"><mat-icon>location_off</mat-icon>{{ I18N.photo_detail.gps_clear | translate }}</button> }
      @if (data.manuallySet) {
        <button mat-button (click)="useFileLocation()" [disabled]="saving() || placeBusy()">{{ I18N.photo_detail.gps.use_file_location | translate }}</button>
      }
      <button mat-button (click)="cancel()">{{ I18N.ui.buttons.cancel | translate }}</button>
      @if (data.batch) {
        <button mat-stroked-button (click)="previewBatch()" [disabled]="saving() || placeBusy() || !batchCoordinatesValid()">{{ I18N.photo_detail.gps.preview_batch | translate }}</button>
      }
      <button mat-flat-button (click)="save()" [disabled]="saving() || placeBusy() || (data.batch ? !canApplyBatch() : (!coordinatesValid() || unchanged()))">{{ I18N.ui.buttons.save | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class GpsEditDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly auth = inject(AuthService);
  private readonly owner = this.auth.identity();
  private readonly api = inject(ApiService);
  private readonly store = inject(GalleryStore);
  private readonly geoPhotos = inject(GeoPhotosService);
  private readonly dialogRef = inject(MatDialogRef<GpsEditDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly staleness = inject(StalenessGuardFactory).create(this.destroyRef, { onNavigate: () => this.invalidateOwner() });
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
  readonly onlineQuery = signal('');
  readonly onlineResults = signal<components['schemas']['PlaceSearchResult'][]>([]);
  readonly onlineBusy = signal(false);
  readonly onlineSearched = signal(false);
  readonly onlineError = signal('');
  readonly onlineEnabled = computed(() => this.store.config()?.place_search_enabled ?? false);
  readonly onlineQueryValid = computed(() => normalizeOnlineQuery(this.onlineQuery()) !== null);
  private onlineSequence = 0;
  private readonly cancelOnline = new Subject<void>();
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
  protected readonly mapsMaxInput = MAPS_LINK_MAX_INPUT;
  readonly mapsInput = signal('');
  readonly mapsBusy = signal(false);
  readonly mapsError = signal('');
  /** The point the last paste moved the pin to, announced to screen readers. */
  readonly mapsPoint = signal<LatLng | null>(null);
  private mapsSequence = 0;
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
    return !this.dismissed && !this.destroyed && !this.destroyRef.destroyed && this.sessionCurrent();
  }

  /** Same session and page as at opening. A committed write is still published
   *  after a plain Cancel/Escape; only a later session or navigation drops it. */
  private sessionCurrent(): boolean {
    return this.staleness.session();
  }

  private dismiss(): void {
    this.dismissed = true;
    this.batchPreview.set(null);
    this.invalidateOnline();
  }

  private invalidateOwner(): void {
    this.dismiss();
    this.places.set([]);
    this.recent.set([]);
    this.dialogRef.close();
  }

  constructor() {
    effect(() => {
      if (this.auth.identity() !== this.owner || !this.auth.isEdition()) this.invalidateOwner();
    });
    effect(() => { this.auth.status(); this.invalidateOnline(); });
    this.dialogRef.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => this.dismiss());
    this.destroyRef.onDestroy(() => {
      this.destroyed = true;
      this.invalidateOnline();
      this.cancelOnline.complete();
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

  private invalidateOnline(): void {
    this.onlineSequence++;
    this.cancelOnline.next();
    this.onlineBusy.set(false);
    this.onlineResults.set([]);
    this.onlineSearched.set(false);
    this.onlineError.set('');
  }

  setOnlineQuery(query: string): void {
    this.invalidateOnline();
    this.onlineQuery.set(query);
  }

  /** Enter that commits an IME candidate is part of typing, which never sends the query. */
  onOnlineEnter(event: Event): void {
    // Safari fires compositionend before the keydown of the Enter that commits an
    // IME candidate, so that Enter carries isComposing false and keyCode 229.
    const key = event as KeyboardEvent;
    if (key.isComposing || key.keyCode === IME_PROCESS_KEY_CODE) return;
    void this.searchOnline();
  }

  async searchOnline(): Promise<void> {
    if (!this.current() || this.saving() || this.onlineBusy() || !this.onlineQueryValid() || !this.onlineEnabled()) return;
    this.invalidateOnline();
    const sequence = this.onlineSequence;
    const auth = this.auth.status();
    this.onlineBusy.set(true);
    try {
      const response = await firstValueFrom(this.api.get<components['schemas']['PlaceSearchResponse']>('/places/search', { q: normalizeOnlineQuery(this.onlineQuery()) ?? '' }, new HttpContext().set(HANDLE_PLACE_SEARCH_ERRORS_LOCALLY, true)).pipe(takeUntil(this.cancelOnline)));
      if (sequence !== this.onlineSequence || auth !== this.auth.status() || this.destroyed || this.dismissed) return;
      this.onlineResults.set(response.results.filter(result => this.validOnlineResult(result)).slice(0, 5));
      this.onlineSearched.set(true);
    } catch {
      if (sequence === this.onlineSequence && auth === this.auth.status() && !this.destroyed && !this.dismissed) this.onlineError.set(I18N.photo_detail.gps.online_error);
    } finally {
      if (sequence === this.onlineSequence) this.onlineBusy.set(false);
    }
  }

  private validOnlineResult(result: components['schemas']['PlaceSearchResult']): boolean {
    return typeof result?.label === 'string' && result.label.trim().length > 0 && Array.from(result.label).length <= 600 &&
      typeof result.latitude === 'number' && typeof result.longitude === 'number' && Number.isFinite(result.latitude) && Number.isFinite(result.longitude) && Math.abs(result.latitude) <= 90 && Math.abs(result.longitude) <= 180;
  }

  selectOnlineResult(result: components['schemas']['PlaceSearchResult']): void {
    if (!this.current() || this.saving()) return;
    this.selectRecent(result);
  }

  setMapsInput(text: string): void {
    this.mapsSequence++;
    this.mapsBusy.set(false);
    this.mapsError.set('');
    this.mapsPoint.set(null);
    this.mapsInput.set(text);
  }

  /** A paste replaces the field and is read at once: the user copied it to use it. */
  onMapsPaste(event: ClipboardEvent): void {
    const text = event.clipboardData?.getData('text');
    if (!text) return;
    event.preventDefault();
    this.setMapsInput(text);
    void this.applyMapsInput();
  }

  onMapsEnter(event: Event): void {
    const key = event as KeyboardEvent;
    if (key.isComposing || key.keyCode === IME_PROCESS_KEY_CODE) return;
    event.preventDefault();
    void this.applyMapsInput();
  }

  /** Move the pin to a pasted point or link; never saves (the user reviews, then Saves). */
  async applyMapsInput(): Promise<void> {
    if (!this.current() || this.saving() || this.mapsBusy()) return;
    const text = this.mapsInput().trim();
    this.mapsError.set('');
    this.mapsPoint.set(null);
    if (!text) return;
    const local = parseGoogleMapsInput(text);
    if (local) { this.applyMapsPoint(local); return; }
    if (!isResolvableMapsLink(text)) { this.mapsError.set(I18N.photo_detail.gps.maps_unrecognized); return; }
    const sequence = ++this.mapsSequence;
    this.mapsBusy.set(true);
    try {
      const result = await firstValueFrom(this.api.post<MapsLinkResponse>('/geo/resolve_maps_link', { url: text }));
      if (sequence !== this.mapsSequence || !this.current()) return;
      this.applyMapsPoint({ lat: result.latitude, lng: result.longitude });
    } catch (error) {
      if (sequence !== this.mapsSequence || !this.current()) return;
      const response = error as { status?: number; error?: { detail?: unknown } } | null;
      const unrecognized = response?.status === 422 && response.error?.detail !== 'unreachable';
      this.mapsError.set(unrecognized ? I18N.photo_detail.gps.maps_unrecognized : I18N.photo_detail.gps.maps_unreachable);
    } finally {
      if (sequence === this.mapsSequence) this.mapsBusy.set(false);
    }
  }

  /** Any pin the user places by another route wins over a short-link answer still in flight. */
  private cancelMapsResolve(): void {
    this.mapsSequence++;
    this.mapsBusy.set(false);
  }

  private applyMapsPoint(point: LatLng): void {
    this.movePin({ latitude: point.lat, longitude: point.lng });
    this.mapsPoint.set(point);
  }

  /** Google Maps in a new tab, at the pin, else the selection's first geotagged photo, else the map's centre. */
  openGoogleMaps(): void {
    window.open(googleMapsSearchUrl(this.googleMapsPoint()), '_blank', 'noopener');
  }

  private googleMapsPoint(): LatLng {
    const lat = this.selectedLat(), lng = this.selectedLng();
    if (lat !== null && lng !== null && this.coordinatesValid()) return { lat, lng };
    if (this.batchTarget) {
      const listed = this.batchTarget.photo_paths ? new Set(this.batchTarget.photo_paths) : null;
      const excluded = new Set(this.batchTarget.exclude ?? []);
      const geotagged = this.store.photos().find(photo => (listed ? listed.has(photo.path) : !excluded.has(photo.path))
        && typeof photo.gps_latitude === 'number' && typeof photo.gps_longitude === 'number');
      if (geotagged) return { lat: geotagged.gps_latitude!, lng: geotagged.gps_longitude! };
    } else if (this.data.lat !== null && this.data.lng !== null) {
      return { lat: this.data.lat, lng: this.data.lng };
    }
    const center = this.map?.getCenter().wrap();
    return center ? { lat: center.lat, lng: center.lng } : DEFAULT_MAP_CENTER;
  }

  private initMap(): void {
    const container = this.mapContainer().nativeElement;
    const lat = this.selectedLat() ?? DEFAULT_MAP_CENTER.lat;
    const lng = this.selectedLng() ?? DEFAULT_MAP_CENTER.lng;
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
      this.cancelMapsResolve();
      this.invalidateOnline();
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
    this.cancelMapsResolve();
    this.invalidateOnline();
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
    this.cancelMapsResolve();
    this.movePin(point);
  }

  private movePin(point: Pick<RecentPlace, 'latitude' | 'longitude'>): void {
    this.invalidateOnline();
    this.selectedPlaceId.set(null);
    this.selectedLat.set(point.latitude);
    this.selectedLng.set(point.longitude);
    this.syncMarker();
    this.map?.setView([point.latitude, point.longitude], 13);
  }

  setLatitude(value: number | null): void {
    this.cancelMapsResolve();
    this.invalidateOnline();
    if (value !== this.selectedLat()) this.selectedPlaceId.set(null);
    this.selectedLat.set(value);
    this.syncMarker();
  }

  setLongitude(value: number | null): void {
    this.cancelMapsResolve();
    this.invalidateOnline();
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

  cancel(): void { this.dismiss(); this.dialogRef.close(undefined); }

  async useFileLocation(): Promise<void> {
    if (!this.current() || this.saving() || this.placeBusy()) return;
    this.invalidateOnline();
    this.saving.set(true);
    this.saveError.set('');
    try {
      const result = await firstValueFrom(this.api.delete<GpsResult>(`/photo/gps?path=${encodeURIComponent(this.data.path)}`));
      // The write is done on the server, so the store follows it even after a plain dismissal,
      // but never into a later session or page.
      if (!this.sessionCurrent()) return;
      this.store.patchPhoto(this.data.path, { gps_latitude: result.gps_latitude, gps_longitude: result.gps_longitude, gps_manually_set: 0 });
      void this.store.refreshPaths(null);
      void this.geoPhotos.refresh();
      if (this.current()) this.dialogRef.close({ ...result, gps_manually_set: 0 });
    } catch {
      if (!this.current()) return;
      this.snackBar.open(this.i18n.t(I18N.notifications.connection_error), '', { duration: 3000 });
      this.saveError.set(I18N.photo_detail.gps.save_error);
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
    this.invalidateOnline();
    this.saving.set(true);
    this.saveError.set('');
    try {
      const result = await firstValueFrom(this.api.post<components['schemas']['BatchGpsResponse']>('/photos/batch_gps', {
        ...preview.body, preview: false, preview_token: preview.result.preview_token,
      }));
      // A committed write remains server truth, but an expired dialog cannot
      // publish into a later session or navigation.
      if (!this.sessionCurrent()) return;
      this.data.onBatchApplied?.();
      void this.store.refreshPaths(null);
      void this.geoPhotos.refresh();
      this.snackBar.open(this.i18n.t(result.changed === 1 ? I18N.photo_detail.gps.batch_applied : I18N.photo_detail.gps.batch_applied_plural, { changed: result.changed, skipped: result.skipped }), '', { duration: 4000 });
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
    this.invalidateOnline();
    this.saving.set(true);
    this.saveError.set('');
    try {
      const result = await firstValueFrom(this.api.put<GpsResult>('/photo/gps', body));
      if (!this.sessionCurrent()) return;
      this.store.patchPhoto(body.path, { gps_latitude: result.gps_latitude, gps_longitude: result.gps_longitude, gps_manually_set: 1 });
      void this.store.refreshPaths(null);
      void this.geoPhotos.refresh();
      if (this.current()) this.dialogRef.close(result);
    } catch {
      if (!this.current()) return;
      this.snackBar.open(this.i18n.t(I18N.notifications.connection_error), '', { duration: 3000 });
      this.saveError.set(I18N.photo_detail.gps.save_error);
    } finally { if (this.current()) this.saving.set(false); }
  }
}
