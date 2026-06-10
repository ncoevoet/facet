import { Injectable, inject, signal, computed, effect, untracked } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { Photo } from '../../shared/models/photo.model';
import {
  type GalleryFilters, type GalleryMode, type TooltipMode, type DisplayOptions,
  DEFAULT_FILTERS, SMART_ALBUM_EXCLUDE_KEYS, DISPLAY_OPTION_KEYS,
  GALLERY_MODE_KEY, DRAWER_STATE_KEY, CARD_WIDTH_KEY,
  loadDisplayOptionsFromStorage, saveDisplayOptionsToStorage,
  countActiveFilters, applyQueryParams, buildSyncParams, buildApiParams,
} from './gallery-filters.util';

// Re-export the filter types/consts so existing importers of gallery.store keep working.
export type { GalleryFilters, GalleryMode, TooltipMode, DisplayOptions };
export { DEFAULT_FILTERS, SMART_ALBUM_EXCLUDE_KEYS };

// --- API response types ---

export interface HiddenSummary {
  total: number;
  blinks: number;
  bursts: number;
  duplicates: number;
}

export interface PhotosResponse {
  photos: Photo[];
  total: number;
  page: number;
  per_page: number;
  has_more: boolean;
  hidden_summary?: HiddenSummary;
}

/** Pre-mutation flag state, used to revert optimistic updates and power undo. */
export interface PhotoFlagSnapshot {
  is_favorite: boolean;
  is_rejected: boolean;
  star_rating: number | null;
}

export interface TypeCount {
  id: string;
  label: string;
  count: number;
}

export interface FilterOption {
  value: string;
  count: number;
}

export interface PersonOption {
  id: number;
  name: string | null;
  face_count: number;
}

export interface SortOption {
  column: string;
  label: string;
}

export interface ViewerConfig {
  pagination: { default_per_page: number };
  defaults: {
    type: string;
    sort: string;
    sort_direction: string;
    hide_blinks: boolean;
    hide_bursts: boolean;
    hide_duplicates: boolean;
    hide_details: boolean;
    tooltip_mode: TooltipMode;
    hide_rejected: boolean;
    gallery_mode: GalleryMode;
  };
  display: {
    tags_per_photo: number;
    card_width_px: number;
    image_width_px: number;
    thumbnail_slider?: {
      min_px: number;
      max_px: number;
      default_px: number;
      step_px: number;
    };
  };
  sort_options_grouped: Record<string, SortOption[]> | null;
  features: {
    show_similar_button: boolean;
    show_merge_suggestions: boolean;
    show_rating_controls: boolean;
    show_rating_badge: boolean;
    show_semantic_search: boolean;
    show_albums: boolean;
    show_critique: boolean;
    show_vlm_critique: boolean;
    show_memories: boolean;
    show_captions: boolean;
    show_timeline: boolean;
    show_map: boolean;
    show_capsules: boolean;
    show_folders: boolean;
  };
  quality_thresholds: {
    good: number;
    great: number;
    excellent: number;
    best: number;
  };
  [key: string]: unknown;
}

@Injectable({ providedIn: 'root' })
export class GalleryStore {
  private api = inject(ApiService);
  private auth = inject(AuthService);
  private albumService = inject(AlbumService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private snackBar = inject(MatSnackBar);
  private i18n = inject(I18nService);

  // --- State signals ---
  readonly filters = signal<GalleryFilters>({ ...DEFAULT_FILTERS });
  readonly currentAlbum = signal<Album | null>(null);
  readonly initializing = signal(false);
  private smartSaveTimer: ReturnType<typeof setTimeout> | null = null;
  readonly photos = signal<Photo[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  private _loadSeq = 0;
  readonly hasMore = signal(false);
  readonly config = signal<ViewerConfig | null>(null);
  readonly filterDrawerOpen = signal(localStorage.getItem(DRAWER_STATE_KEY) === 'true');
  readonly slideshowActive = signal(false);
  readonly cardWidth = signal(parseInt(localStorage.getItem(CARD_WIDTH_KEY) ?? '', 10) || 0);
  readonly galleryMode = signal<GalleryMode>((localStorage.getItem(GALLERY_MODE_KEY) as GalleryMode) || 'grid');

  // Hidden-photo summary (populated from /photos response)
  readonly hiddenSummary = signal<HiddenSummary>({ total: 0, blinks: 0, bursts: 0, duplicates: 0 });

  // --- Selection state (store-level so it survives navigation and is visible to services) ---
  readonly selectedPaths = signal<Set<string>>(new Set());
  readonly selectionCount = computed(() => this.selectedPaths().size);
  private lastSelectedIndex = -1;

  /** Toggle a photo's selection; shift-click extends from the last selected index. */
  toggleSelection(photo: Photo, event?: MouseEvent): void {
    const photos = this.photos();
    const clickedIndex = photos.findIndex(p => p.path === photo.path);
    const next = new Set(this.selectedPaths());

    if (event?.shiftKey && this.lastSelectedIndex >= 0 && clickedIndex >= 0) {
      const start = Math.min(this.lastSelectedIndex, clickedIndex);
      const end = Math.max(this.lastSelectedIndex, clickedIndex);
      for (let i = start; i <= end; i++) {
        next.add(photos[i].path);
      }
    } else if (next.has(photo.path)) {
      next.delete(photo.path);
    } else {
      next.add(photo.path);
    }

    if (clickedIndex >= 0) this.lastSelectedIndex = clickedIndex;
    this.selectedPaths.set(next);
  }

  /** Select every currently loaded photo. */
  selectAllLoaded(): void {
    this.selectedPaths.set(new Set(this.photos().map(p => p.path)));
  }

  clearSelection(): void {
    this.selectedPaths.set(new Set());
    this.lastSelectedIndex = -1;
  }

  /** Restore a previously captured selection (used by undo). */
  restoreSelection(paths: Iterable<string>): void {
    this.selectedPaths.set(new Set(paths));
  }

  // Filter options
  readonly types = signal<TypeCount[]>([]);
  readonly cameras = signal<FilterOption[]>([]);
  readonly lenses = signal<FilterOption[]>([]);
  readonly tags = signal<FilterOption[]>([]);
  readonly persons = signal<PersonOption[]>([]);
  readonly patterns = signal<FilterOption[]>([]);

  /** Reverse-geocoded place name for the active GPS filter. */
  readonly gpsLocationName = signal('');

  private readonly gpsCoords = computed(() => {
    const f = this.filters();
    return f.gps_lat && f.gps_lng ? `${f.gps_lat},${f.gps_lng}` : '';
  });

  private gpsLocationEffect = effect(() => {
    const coords = this.gpsCoords();
    if (!coords) {
      this.gpsLocationName.set('');
      return;
    }
    const [lat, lng] = coords.split(',');
    firstValueFrom(this.api.get<{ display_name: string }>('/filter_options/location_name', { lat, lng }))
      .then(res => this.gpsLocationName.set(res.display_name || `${(+lat).toFixed(2)}, ${(+lng).toFixed(2)}`))
      .catch(() => this.gpsLocationName.set(`${(+lat).toFixed(2)}, ${(+lng).toFixed(2)}`));
  });

  // --- Computed ---
  readonly activeFilterCount = computed(() => countActiveFilters(this.filters()));

  constructor() {
    // Auto-save album filters on change (debounced) — persists filter state for all albums
    effect(() => {
      const f = this.filters();
      const album = this.currentAlbum();
      if (!album) return;
      if (untracked(() => this.initializing())) return;
      const isEdition = untracked(() => this.auth.isEdition());
      if (!isEdition) return;

      const filterJson: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(f)) {
        if (v && v !== '' && !SMART_ALBUM_EXCLUDE_KEYS.has(k)) {
          filterJson[k] = v;
        }
      }
      const json = JSON.stringify(filterJson);

      untracked(() => {
        if (this.smartSaveTimer) clearTimeout(this.smartSaveTimer);
        this.smartSaveTimer = setTimeout(() => {
          firstValueFrom(this.albumService.update(album.id, { smart_filter_json: json })).catch(() => {});
        }, 500);
      });
    });
  }

  /** Load viewer config and apply defaults */
  async loadConfig(): Promise<void> {
    try {
      const cfg = await firstValueFrom(this.api.get<ViewerConfig>('/config'));
      this.config.set(cfg);

      // Initialize card width from localStorage or config default
      if (!this.cardWidth()) {
        const defaultPx = cfg.display?.thumbnail_slider?.default_px ?? cfg.display?.card_width_px ?? 168;
        this.cardWidth.set(defaultPx);
      }

      // Initialize gallery mode from localStorage or config default
      if (!localStorage.getItem(GALLERY_MODE_KEY) && cfg.defaults?.gallery_mode) {
        this.galleryMode.set(cfg.defaults.gallery_mode);
      }

      // Apply config defaults to filters, then overlay localStorage display options, then URL params
      const defaults = cfg.defaults;
      const storedDisplay = loadDisplayOptionsFromStorage();
      const base: GalleryFilters = {
        ...DEFAULT_FILTERS,
        per_page: cfg.pagination?.default_per_page ?? 64,
        sort: defaults?.sort ?? 'aggregate',
        sort_direction: defaults?.sort_direction ?? 'DESC',
        type: defaults?.type ?? '',
        hide_details: storedDisplay.hide_details ?? (defaults?.hide_details ?? true),
        tooltip_mode: storedDisplay.tooltip_mode ?? (defaults?.tooltip_mode ?? 'hover'),
        hide_blinks: storedDisplay.hide_blinks ?? (defaults?.hide_blinks ?? true),
        hide_bursts: storedDisplay.hide_bursts ?? (defaults?.hide_bursts ?? true),
        hide_duplicates: storedDisplay.hide_duplicates ?? (defaults?.hide_duplicates ?? true),
        hide_rejected: storedDisplay.hide_rejected ?? (defaults?.hide_rejected ?? true),
        favorites_only: storedDisplay.favorites_only ?? false,
        is_monochrome: storedDisplay.is_monochrome ?? false,
      };

      // Overlay query params
      const params = this.route.snapshot.queryParams;
      const merged = applyQueryParams(base, params);
      this.filters.set(merged);
    } catch {
      // Use defaults if config fails
      const params = this.route.snapshot.queryParams;
      this.filters.set(applyQueryParams({ ...DEFAULT_FILTERS }, params));
    }
  }

  /** Load photos based on current filters (replaces list) */
  async loadPhotos(): Promise<void> {
    // Always load from page 1 — only nextPage() uses page > 1
    this.filters.update(current => ({ ...current, page: 1 }));
    const seq = ++this._loadSeq;
    const prevPhotos = this.photos();
    const prevTotal = this.total();
    const prevHasMore = this.hasMore();
    this.photos.set([]);
    this.loading.set(true);
    try {
      const f = this.filters();

      if (f.similar_to) {
        const res = await this.fetchSimilarPage(f, (f.page - 1) * f.per_page);
        if (seq !== this._loadSeq) return;
        this.photos.set(res.similar ?? []);
        this.total.set(res.total);
        this.hasMore.set(res.has_more);
        return;
      }

      if (f.semanticQuery) {
        const res = await firstValueFrom(
          this.api.get<{ photos: Photo[]; total: number; query: string }>('/search', {
            q: f.semanticQuery,
            limit: f.per_page,
            threshold: 0.15,
          }),
        );
        if (seq !== this._loadSeq) return;
        this.photos.set(res.photos);
        this.total.set(res.total);
        this.hasMore.set(false);
        return;
      }

      const params = buildApiParams(f, this.currentAlbum()?.is_smart ?? false);
      const res = await firstValueFrom(this.api.get<PhotosResponse>('/photos', params));
      if (seq !== this._loadSeq) return;
      this.photos.set(res.photos);
      this.total.set(res.total);
      this.hasMore.set(res.has_more);
      this.hiddenSummary.set(
        res.hidden_summary ?? { total: 0, blinks: 0, bursts: 0, duplicates: 0 },
      );
    } catch {
      if (seq !== this._loadSeq) return;
      // Network error — restore previous state
      this.photos.set(prevPhotos);
      this.total.set(prevTotal);
      this.hasMore.set(prevHasMore);
    } finally {
      if (seq === this._loadSeq) {
        this.loading.set(false);
      }
    }
  }

  /** Load next page and append to existing photos */
  async nextPage(): Promise<void> {
    if (!this.hasMore() || this.loading()) return;

    const seq = this._loadSeq;
    this.loading.set(true);
    const f = this.filters();
    const nextPage = f.page + 1;
    this.filters.update(current => ({ ...current, page: nextPage }));
    try {
      if (f.similar_to) {
        const res = await this.fetchSimilarPage(f, (nextPage - 1) * f.per_page);
        if (seq !== this._loadSeq) return;
        this.photos.update(current => [...current, ...(res.similar ?? [])]);
        this.total.set(res.total);
        this.hasMore.set(res.has_more);
      } else {
        const params = buildApiParams(this.filters(), this.currentAlbum()?.is_smart ?? false);
        const res = await firstValueFrom(this.api.get<PhotosResponse>('/photos', params));
        if (seq !== this._loadSeq) return;
        this.photos.update(current => [...current, ...res.photos]);
        this.total.set(res.total);
        this.hasMore.set(res.has_more);
        if (res.hidden_summary) {
          this.hiddenSummary.set(res.hidden_summary);
        }
      }
    } catch {
      if (seq !== this._loadSeq) return;
      // Revert page increment on error
      this.filters.update(current => ({ ...current, page: f.page }));
    } finally {
      if (seq === this._loadSeq) {
        this.loading.set(false);
      }
    }
  }

  /** Display-only keys that never affect the API query */
  private static readonly DISPLAY_ONLY_KEYS: ReadonlySet<keyof GalleryFilters> = new Set([
    'hide_details', 'tooltip_mode',
  ]);

  /** Update a single filter and reload photos from page 1 */
  async updateFilter<K extends keyof GalleryFilters>(
    key: K,
    value: GalleryFilters[K],
  ): Promise<void> {
    const extra: Partial<GalleryFilters> = {};
    if (key === 'hide_rejected' && value) extra.favorites_only = false;
    if (key === 'favorites_only' && value) extra.hide_rejected = false;
    // Reload person dropdown when person filter is cleared (was seeded with filtered subset)
    const wasPersonFiltered = !!this.filters().person_id;
    this.filters.update(current => ({ ...current, [key]: value, ...extra, page: 1 }));
    if ((DISPLAY_OPTION_KEYS as string[]).includes(key as string)) {
      saveDisplayOptionsToStorage(this.filters());
    }
    this.syncUrl();
    if (!GalleryStore.DISPLAY_ONLY_KEYS.has(key)) {
      await this.loadPhotos();
    }
    if (key === 'person_id' && wasPersonFiltered && !value) {
      this.reloadPersonOptions();
    }
  }

  /** Update multiple filters at once and reload */
  async updateFilters(updates: Partial<GalleryFilters>): Promise<void> {
    const extra: Partial<GalleryFilters> = {};
    if (updates.hide_rejected) extra.favorites_only = false;
    if (updates.favorites_only) extra.hide_rejected = false;
    this.filters.update(current => ({ ...current, ...updates, ...extra, page: 1 }));
    if (Object.keys(updates).some(k => (DISPLAY_OPTION_KEYS as string[]).includes(k))) {
      saveDisplayOptionsToStorage(this.filters());
    }
    this.syncUrl();
    await this.loadPhotos();
  }

  /** Reset all filters to config defaults */
  async resetFilters(): Promise<void> {
    this.currentAlbum.set(null);
    const cfg = this.config();
    const defaults = cfg?.defaults;
    this.filters.set({
      ...DEFAULT_FILTERS,
      per_page: cfg?.pagination?.default_per_page ?? 64,
      sort: defaults?.sort ?? 'aggregate',
      sort_direction: defaults?.sort_direction ?? 'DESC',
      hide_details: defaults?.hide_details ?? true,
      tooltip_mode: defaults?.tooltip_mode ?? 'hover',
      hide_blinks: defaults?.hide_blinks ?? true,
      hide_bursts: defaults?.hide_bursts ?? true,
      hide_duplicates: defaults?.hide_duplicates ?? true,
      hide_rejected: defaults?.hide_rejected ?? true,
    });
    this.resetCardWidth();
    // Preserve user's gallery mode preference from localStorage
    if (!localStorage.getItem(GALLERY_MODE_KEY)) {
      this.setGalleryMode(defaults?.gallery_mode ?? 'grid');
    }
    saveDisplayOptionsToStorage(this.filters());
    this.syncUrl();
    await this.loadPhotos();
  }

  setFilterDrawerOpen(open: boolean): void {
    this.filterDrawerOpen.set(open);
    try { localStorage.setItem(DRAWER_STATE_KEY, String(open)); } catch { /* ignore */ }
  }

  setCardWidth(px: number): void {
    this.cardWidth.set(px);
    try { localStorage.setItem(CARD_WIDTH_KEY, String(px)); } catch { /* ignore */ }
  }

  resetCardWidth(): void {
    const cfg = this.config();
    const defaultPx = cfg?.display?.thumbnail_slider?.default_px ?? cfg?.display?.card_width_px ?? 168;
    this.cardWidth.set(defaultPx);
    try { localStorage.removeItem(CARD_WIDTH_KEY); } catch { /* ignore */ }
  }

  setGalleryMode(mode: GalleryMode): void {
    this.galleryMode.set(mode);
    try { localStorage.setItem(GALLERY_MODE_KEY, mode); } catch { /* ignore */ }
  }

  /** Load type counts (for the type toggle bar) */
  async loadTypeCounts(): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.get<{types: TypeCount[]}>('/type_counts'));
      this.types.set(res.types.filter(t => t.id).sort((a, b) => b.count - a.count));
    } catch {
      this.types.set([]);
    }
  }

  /** Load all filter dropdown options in parallel */
  async loadFilterOptions(): Promise<void> {
    const [camerasRes, lensesRes, tagsRes, personsRes, patternsRes] = await Promise.all([
      firstValueFrom(this.api.get<{cameras: [string, number][]}>('/filter_options/cameras')).catch(() => ({cameras: []})),
      firstValueFrom(this.api.get<{lenses: [string, number][]}>('/filter_options/lenses')).catch(() => ({lenses: []})),
      firstValueFrom(this.api.get<{tags: [string, number][]}>('/filter_options/tags')).catch(() => ({tags: []})),
      firstValueFrom(this.api.get<{persons: [number, string | null, number][]}>('/filter_options/persons',
        this.filters().person_id ? { ids: this.filters().person_id } : undefined)).catch(() => ({persons: []})),
      firstValueFrom(this.api.get<{patterns: [string, number][]}>('/filter_options/patterns')).catch(() => ({patterns: []})),
    ]);
    this.cameras.set((camerasRes.cameras ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.lenses.set((lensesRes.lenses ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.tags.set((tagsRes.tags ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.persons.set(
      (personsRes.persons ?? [])
        .map(([id, name, face_count]: [number, string | null, number]) => ({id, name, face_count})),
    );
    this.patterns.set((patternsRes.patterns ?? []).map(([value, count]: [string, number]) => ({value, count})));
  }

  /** Reload person dropdown without filter restriction */
  private async reloadPersonOptions(): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.get<{persons: [number, string | null, number][]}>('/filter_options/persons'),
      );
      this.persons.set(
        (res.persons ?? []).map(([id, name, face_count]: [number, string | null, number]) => ({id, name, face_count})),
      );
    } catch { /* keep existing list */ }
  }

  /** Patch one photo's fields in place. */
  patchPhoto(path: string, partial: Partial<Photo>): void {
    this.photos.update(photos =>
      photos.map(p => p.path === path ? { ...p, ...partial } : p),
    );
  }

  /** Patch many photos at once. */
  private patchPhotos(pathSet: ReadonlySet<string>, partial: Partial<Photo>): void {
    this.photos.update(photos =>
      photos.map(p => pathSet.has(p.path) ? { ...p, ...partial } : p),
    );
  }

  /** Capture pre-mutation flag state for the given paths (revert / undo input). */
  private snapshotFlags(paths: string[]): Map<string, PhotoFlagSnapshot> {
    const pathSet = new Set(paths);
    const snap = new Map<string, PhotoFlagSnapshot>();
    for (const p of this.photos()) {
      if (pathSet.has(p.path)) {
        snap.set(p.path, {
          is_favorite: !!p.is_favorite,
          is_rejected: !!p.is_rejected,
          star_rating: p.star_rating ?? null,
        });
      }
    }
    return snap;
  }

  private revertSnapshot(snap: Map<string, PhotoFlagSnapshot>): void {
    this.photos.update(photos =>
      photos.map(p => snap.has(p.path) ? { ...p, ...snap.get(p.path)! } : p),
    );
  }

  private notifyActionFailed(): void {
    this.snackBar.open(this.i18n.t('errors.action_failed'), '', { duration: 3000 });
  }

  /** Set star rating for a photo (0 = clear). Optimistic with revert on error. */
  async setRating(photoPath: string, rating: number): Promise<void> {
    const snap = this.snapshotFlags([photoPath]);
    this.patchPhoto(photoPath, { star_rating: rating || null });
    try {
      await firstValueFrom(this.api.post('/photo/set_rating', { photo_path: photoPath, rating }));
    } catch {
      this.revertSnapshot(snap);
      this.notifyActionFailed();
    }
  }

  /** Toggle favorite flag for a photo. Optimistic, reconciled with server truth. */
  async toggleFavorite(photoPath: string): Promise<void> {
    const snap = this.snapshotFlags([photoPath]);
    const prev = snap.get(photoPath);
    if (!prev) return;
    const next = !prev.is_favorite;
    this.patchPhoto(photoPath, {
      is_favorite: next,
      is_rejected: next ? false : prev.is_rejected,
    });
    try {
      const res = await firstValueFrom(
        this.api.post<{ is_favorite: boolean }>('/photo/toggle_favorite', { photo_path: photoPath }),
      );
      this.patchPhoto(photoPath, {
        is_favorite: res.is_favorite,
        is_rejected: res.is_favorite ? false : prev.is_rejected,
      });
    } catch {
      this.revertSnapshot(snap);
      this.notifyActionFailed();
    }
  }

  /** Toggle rejected flag for a photo. Optimistic, reconciled with server truth. */
  async toggleRejected(photoPath: string): Promise<void> {
    const snap = this.snapshotFlags([photoPath]);
    const prev = snap.get(photoPath);
    if (!prev) return;
    const next = !prev.is_rejected;
    this.patchPhoto(photoPath, {
      is_rejected: next,
      is_favorite: next ? false : prev.is_favorite,
    });
    try {
      const res = await firstValueFrom(
        this.api.post<{ is_rejected: boolean }>('/photo/toggle_rejected', { photo_path: photoPath }),
      );
      this.patchPhoto(photoPath, {
        is_rejected: res.is_rejected,
        is_favorite: res.is_rejected ? false : prev.is_favorite,
      });
    } catch {
      this.revertSnapshot(snap);
      this.notifyActionFailed();
    }
  }

  /**
   * Batch favorite multiple photos. Optimistic with revert on error.
   * Returns the pre-mutation snapshot for undo, or null on failure.
   */
  async batchFavorite(paths: string[]): Promise<Map<string, PhotoFlagSnapshot> | null> {
    const snap = this.snapshotFlags(paths);
    this.patchPhotos(new Set(paths), { is_favorite: true, is_rejected: false });
    try {
      await firstValueFrom(this.api.post('/photos/batch_favorite', { photo_paths: paths }));
      return snap;
    } catch {
      this.revertSnapshot(snap);
      this.notifyActionFailed();
      return null;
    }
  }

  /**
   * Batch reject multiple photos. Optimistic with revert on error.
   * Returns the pre-mutation snapshot for undo, or null on failure.
   */
  async batchReject(paths: string[]): Promise<Map<string, PhotoFlagSnapshot> | null> {
    const snap = this.snapshotFlags(paths);
    this.patchPhotos(new Set(paths), { is_rejected: true, is_favorite: false, star_rating: null });
    try {
      await firstValueFrom(this.api.post('/photos/batch_reject', { photo_paths: paths }));
      return snap;
    } catch {
      this.revertSnapshot(snap);
      this.notifyActionFailed();
      return null;
    }
  }

  /**
   * Batch set rating for multiple photos. Optimistic with revert on error.
   * Returns the pre-mutation snapshot for undo, or null on failure.
   */
  async batchRating(paths: string[], rating: number): Promise<Map<string, PhotoFlagSnapshot> | null> {
    const snap = this.snapshotFlags(paths);
    this.patchPhotos(new Set(paths), { star_rating: rating || null });
    try {
      await firstValueFrom(this.api.post('/photos/batch_rating', { photo_paths: paths, rating }));
      return snap;
    } catch {
      this.revertSnapshot(snap);
      this.notifyActionFailed();
      return null;
    }
  }

  /** Unassign a person from a photo */
  async unassignPerson(photoPath: string, personId: number): Promise<void> {
    try {
      await firstValueFrom(this.api.post('/photo/unassign_person', { photo_path: photoPath, person_id: personId }));
      this.photos.update(photos =>
        photos.map(p => p.path === photoPath
          ? { ...p, persons: p.persons.filter(pr => pr.id !== personId) }
          : p),
      );
    } catch { /* ignore */ }
  }

  /**
   * Create a new person, optionally attaching faces atomically.
   * Returns the new person record on success, null on failure.
   */
  async createPerson(name: string, faceIds: number[] = [], photoPath?: string): Promise<PersonOption | null> {
    const trimmed = name.trim();
    if (!trimmed) return null;
    try {
      const res = await firstValueFrom(
        this.api.post<{ id: number; name: string; face_count: number }>(
          '/persons',
          { name: trimmed, face_ids: faceIds },
        ),
      );
      const newPerson: PersonOption = { id: res.id, name: res.name, face_count: res.face_count };
      this.persons.update(list => [newPerson, ...list]);
      if (photoPath && faceIds.length > 0) {
        this.photos.update(photos =>
          photos.map(p => {
            if (p.path !== photoPath) return p;
            return {
              ...p,
              persons: [...p.persons, { id: newPerson.id, name: trimmed }],
              unassigned_faces: Math.max(0, p.unassigned_faces - faceIds.length),
            };
          }),
        );
      }
      return newPerson;
    } catch {
      return null;
    }
  }

  /** Assign a single face to a person */
  async assignFace(faceId: number, personId: number, photoPath: string, personName: string): Promise<void> {
    try {
      await firstValueFrom(this.api.post(`/face/${faceId}/assign`, { person_id: personId }));
      this.photos.update(photos =>
        photos.map(p => {
          if (p.path !== photoPath) return p;
          const alreadyHas = p.persons.some(pr => pr.id === personId);
          return {
            ...p,
            persons: alreadyHas ? p.persons : [...p.persons, { id: personId, name: personName }],
            unassigned_faces: Math.max(0, p.unassigned_faces - 1),
          };
        }),
      );
    } catch { /* ignore */ }
  }

  /** Sync current filters to URL query params */
  private syncUrl(): void {
    this.router.navigate([], {
      queryParams: buildSyncParams(this.filters(), this.config()?.defaults),
      replaceUrl: true,
    });
  }

  /** Fetch a page of similar photos from the API */
  private fetchSimilarPage(f: GalleryFilters, offset: number): Promise<{ similar: Photo[]; total: number; has_more: boolean }> {
    const minSim = (parseInt(f.min_similarity || '70', 10) / 100).toString();
    return firstValueFrom(
      this.api.get<{ similar: Photo[]; total: number; has_more: boolean }>(
        `/similar_photos/${encodeURIComponent(f.similar_to)}`,
        { limit: f.per_page, offset, min_similarity: minSim, mode: f.similarity_mode || 'visual', full: 1 },
      ),
    );
  }

}
