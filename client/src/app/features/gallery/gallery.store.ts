import { Injectable, inject, signal, computed, effect, untracked } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { Photo } from '../../shared/models/photo.model';

// --- API response types ---

export interface PhotosResponse {
  photos: Photo[];
  total: number;
  page: number;
  per_page: number;
  has_more: boolean;
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
    hide_tooltip: boolean;
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

// --- Filter state ---

export interface GalleryFilters {
  page: number;
  per_page: number;
  sort: string;
  sort_direction: string;
  type: string;
  camera: string;
  lens: string;
  tag: string;
  person_id: string;
  // Score ranges
  min_score: string;
  max_score: string;
  min_aesthetic: string;
  max_aesthetic: string;
  min_face_quality: string;
  max_face_quality: string;
  min_composition: string;
  max_composition: string;
  min_sharpness: string;
  max_sharpness: string;
  min_exposure: string;
  max_exposure: string;
  min_color: string;
  max_color: string;
  min_contrast: string;
  max_contrast: string;
  min_noise: string;
  max_noise: string;
  min_dynamic_range: string;
  max_dynamic_range: string;
  // Face ranges
  min_face_count: string;
  max_face_count: string;
  min_eye_sharpness: string;
  max_eye_sharpness: string;
  min_face_sharpness: string;
  max_face_sharpness: string;
  min_face_ratio: string;
  max_face_ratio: string;
  min_face_confidence: string;
  max_face_confidence: string;
  // Quality
  min_quality_score: string;
  max_quality_score: string;
  min_topiq: string;
  max_topiq: string;
  // Composition
  min_power_point: string;
  max_power_point: string;
  min_leading_lines: string;
  max_leading_lines: string;
  min_isolation: string;
  max_isolation: string;
  // Extended quality
  min_aesthetic_iaa: string;
  max_aesthetic_iaa: string;
  min_face_quality_iqa: string;
  max_face_quality_iqa: string;
  min_liqe: string;
  max_liqe: string;
  // Subject saliency
  min_subject_sharpness: string;
  max_subject_sharpness: string;
  min_subject_prominence: string;
  max_subject_prominence: string;
  min_subject_placement: string;
  max_subject_placement: string;
  min_bg_separation: string;
  max_bg_separation: string;
  // Technical
  min_saturation: string;
  max_saturation: string;
  min_luminance: string;
  max_luminance: string;
  min_histogram_spread: string;
  max_histogram_spread: string;
  // User ratings
  min_star_rating: string;
  max_star_rating: string;
  // EXIF ranges
  min_iso: string;
  max_iso: string;
  min_aperture: string;
  max_aperture: string;
  min_focal_length: string;
  max_focal_length: string;
  // Date range
  date_from: string;
  date_to: string;
  // Content
  composition_pattern: string;
  // Similar-to filter
  similar_to: string;
  similarity_mode: 'visual' | 'color' | 'person';
  min_similarity: string;
  // Semantic search
  semanticQuery: string;
  // Album filter
  album_id: string;
  // Folder filter
  path_prefix: string;
  // GPS filter
  gps_lat: string;
  gps_lng: string;
  gps_radius_km: string;
  // Display
  hide_details: boolean;
  hide_tooltip: boolean;
  hide_blinks: boolean;
  hide_bursts: boolean;
  hide_duplicates: boolean;
  hide_rejected: boolean;
  favorites_only: boolean;
  is_monochrome: boolean;
  search: string;
}

/** Keys excluded when building smart album filter JSON (display-only, ephemeral, or handled separately). */
export const SMART_ALBUM_EXCLUDE_KEYS = new Set([
  'page', 'per_page', 'semanticQuery', 'album_id',
  'similarity_mode', 'min_similarity',
  'hide_details', 'hide_tooltip', 'hide_blinks', 'hide_bursts',
  'hide_duplicates', 'hide_rejected',
  'gps_lat', 'gps_lng', 'gps_radius_km',
]);

/** Common string-typed filter keys shared across URL sync, API params, and filter counting. */
const RANGE_AND_SELECT_KEYS: (keyof GalleryFilters)[] = [
  'type', 'camera', 'lens', 'tag', 'person_id', 'composition_pattern', 'search',
  'min_score', 'max_score', 'min_aesthetic', 'max_aesthetic',
  'min_quality_score', 'max_quality_score', 'min_topiq', 'max_topiq',
  'min_face_quality', 'max_face_quality', 'min_composition', 'max_composition',
  'min_sharpness', 'max_sharpness', 'min_exposure', 'max_exposure',
  'min_color', 'max_color', 'min_contrast', 'max_contrast',
  'min_noise', 'max_noise', 'min_dynamic_range', 'max_dynamic_range',
  'min_saturation', 'max_saturation', 'min_luminance', 'max_luminance',
  'min_histogram_spread', 'max_histogram_spread',
  'min_power_point', 'max_power_point', 'min_leading_lines', 'max_leading_lines',
  'min_isolation', 'max_isolation',
  'min_aesthetic_iaa', 'max_aesthetic_iaa', 'min_face_quality_iqa', 'max_face_quality_iqa',
  'min_liqe', 'max_liqe',
  'min_subject_sharpness', 'max_subject_sharpness', 'min_subject_prominence', 'max_subject_prominence',
  'min_subject_placement', 'max_subject_placement', 'min_bg_separation', 'max_bg_separation',
  'min_face_count', 'max_face_count',
  'min_eye_sharpness', 'max_eye_sharpness', 'min_face_sharpness', 'max_face_sharpness',
  'min_face_ratio', 'max_face_ratio', 'min_face_confidence', 'max_face_confidence',
  'min_star_rating', 'max_star_rating',
  'min_iso', 'max_iso', 'min_aperture', 'max_aperture', 'min_focal_length', 'max_focal_length',
  'date_from', 'date_to',
  'path_prefix',
  'gps_lat', 'gps_lng', 'gps_radius_km',
];

export const DEFAULT_FILTERS: GalleryFilters = {
  page: 1,
  per_page: 64,
  sort: 'aggregate',
  sort_direction: 'DESC',
  type: '',
  camera: '',
  lens: '',
  tag: '',
  person_id: '',
  min_score: '',
  max_score: '',
  min_aesthetic: '',
  max_aesthetic: '',
  min_face_quality: '',
  max_face_quality: '',
  min_composition: '',
  max_composition: '',
  min_sharpness: '',
  max_sharpness: '',
  min_exposure: '',
  max_exposure: '',
  min_color: '',
  max_color: '',
  min_contrast: '',
  max_contrast: '',
  min_noise: '',
  max_noise: '',
  min_dynamic_range: '',
  max_dynamic_range: '',
  min_face_count: '',
  max_face_count: '',
  min_eye_sharpness: '',
  max_eye_sharpness: '',
  min_face_sharpness: '',
  max_face_sharpness: '',
  min_face_ratio: '',
  max_face_ratio: '',
  min_face_confidence: '',
  max_face_confidence: '',
  min_quality_score: '',
  max_quality_score: '',
  min_topiq: '',
  max_topiq: '',
  min_power_point: '',
  max_power_point: '',
  min_leading_lines: '',
  max_leading_lines: '',
  min_isolation: '',
  max_isolation: '',
  min_aesthetic_iaa: '',
  max_aesthetic_iaa: '',
  min_face_quality_iqa: '',
  max_face_quality_iqa: '',
  min_liqe: '',
  max_liqe: '',
  min_subject_sharpness: '',
  max_subject_sharpness: '',
  min_subject_prominence: '',
  max_subject_prominence: '',
  min_subject_placement: '',
  max_subject_placement: '',
  min_bg_separation: '',
  max_bg_separation: '',
  min_saturation: '',
  max_saturation: '',
  min_luminance: '',
  max_luminance: '',
  min_histogram_spread: '',
  max_histogram_spread: '',
  min_star_rating: '',
  max_star_rating: '',
  min_iso: '',
  max_iso: '',
  min_aperture: '',
  max_aperture: '',
  min_focal_length: '',
  max_focal_length: '',
  date_from: '',
  date_to: '',
  composition_pattern: '',
  path_prefix: '',
  semanticQuery: '',
  album_id: '',
  gps_lat: '',
  gps_lng: '',
  gps_radius_km: '',
  similar_to: '',
  similarity_mode: 'visual',
  min_similarity: '70',
  hide_details: true,
  hide_tooltip: false,
  hide_blinks: true,
  hide_bursts: true,
  hide_duplicates: true,
  hide_rejected: true,
  favorites_only: false,
  is_monochrome: false,
  search: '',
};

export type GalleryMode = 'grid' | 'mosaic';
const GALLERY_MODE_KEY = 'facet_gallery_mode';

const DRAWER_STATE_KEY = 'facet_filter_drawer_open';
const DISPLAY_OPTIONS_KEY = 'facet_display_options';
const CARD_WIDTH_KEY = 'facet_card_width';
type DisplayOptions = Pick<GalleryFilters,
  'hide_details' | 'hide_tooltip' | 'hide_blinks' | 'hide_bursts' | 'hide_duplicates' |
  'hide_rejected' | 'favorites_only' | 'is_monochrome'>;
const DISPLAY_OPTION_KEYS: (keyof DisplayOptions)[] = [
  'hide_details', 'hide_tooltip', 'hide_blinks', 'hide_bursts', 'hide_duplicates',
  'hide_rejected', 'favorites_only', 'is_monochrome',
];

function loadDisplayOptionsFromStorage(): Partial<DisplayOptions> {
  try {
    const raw = localStorage.getItem(DISPLAY_OPTIONS_KEY);
    if (raw) return JSON.parse(raw) as Partial<DisplayOptions>;
  } catch { /* ignore */ }
  return {};
}

function saveDisplayOptionsToStorage(filters: GalleryFilters): void {
  try {
    const opts: Partial<DisplayOptions> = {};
    for (const key of DISPLAY_OPTION_KEYS) {
      (opts as Record<string, boolean>)[key] = filters[key] as boolean;
    }
    localStorage.setItem(DISPLAY_OPTIONS_KEY, JSON.stringify(opts));
  } catch { /* ignore */ }
}

@Injectable({ providedIn: 'root' })
export class GalleryStore {
  private api = inject(ApiService);
  private auth = inject(AuthService);
  private albumService = inject(AlbumService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

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
  readonly activeFilterCount = computed(() => {
    const f = this.filters();
    let count = 0;
    // String filters — count each non-empty one
    const stringKeys: (keyof GalleryFilters)[] = [...RANGE_AND_SELECT_KEYS, 'similar_to', 'semanticQuery'];
    for (const key of stringKeys) {
      if (f[key]) count++;
    }
    if (f.favorites_only) count++;
    if (f.is_monochrome) count++;
    return count;
  });

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
        hide_tooltip: storedDisplay.hide_tooltip ?? (defaults?.hide_tooltip ?? false),
        hide_blinks: storedDisplay.hide_blinks ?? (defaults?.hide_blinks ?? true),
        hide_bursts: storedDisplay.hide_bursts ?? (defaults?.hide_bursts ?? true),
        hide_duplicates: storedDisplay.hide_duplicates ?? (defaults?.hide_duplicates ?? true),
        hide_rejected: storedDisplay.hide_rejected ?? (defaults?.hide_rejected ?? true),
        favorites_only: storedDisplay.favorites_only ?? false,
        is_monochrome: storedDisplay.is_monochrome ?? false,
      };

      // Overlay query params
      const params = this.route.snapshot.queryParams;
      const merged = this.applyQueryParams(base, params);
      this.filters.set(merged);
    } catch {
      // Use defaults if config fails
      const params = this.route.snapshot.queryParams;
      this.filters.set(this.applyQueryParams({ ...DEFAULT_FILTERS }, params));
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

      const params = this.buildApiParams(f);
      const res = await firstValueFrom(this.api.get<PhotosResponse>('/photos', params));
      if (seq !== this._loadSeq) return;
      this.photos.set(res.photos);
      this.total.set(res.total);
      this.hasMore.set(res.has_more);
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
        const params = this.buildApiParams(this.filters());
        const res = await firstValueFrom(this.api.get<PhotosResponse>('/photos', params));
        if (seq !== this._loadSeq) return;
        this.photos.update(current => [...current, ...res.photos]);
        this.total.set(res.total);
        this.hasMore.set(res.has_more);
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
    'hide_details', 'hide_tooltip',
  ]);

  /** Update a single filter and reload photos from page 1 */
  async updateFilter<K extends keyof GalleryFilters>(
    key: K,
    value: GalleryFilters[K],
  ): Promise<void> {
    const extra: Partial<GalleryFilters> = {};
    if (key === 'hide_rejected' && value) extra.favorites_only = false;
    if (key === 'favorites_only' && value) extra.hide_rejected = false;
    this.filters.update(current => ({ ...current, [key]: value, ...extra, page: 1 }));
    if ((DISPLAY_OPTION_KEYS as string[]).includes(key as string)) {
      saveDisplayOptionsToStorage(this.filters());
    }
    this.syncUrl();
    if (!GalleryStore.DISPLAY_ONLY_KEYS.has(key)) {
      await this.loadPhotos();
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
      hide_tooltip: defaults?.hide_tooltip ?? false,
      hide_blinks: defaults?.hide_blinks ?? true,
      hide_bursts: defaults?.hide_bursts ?? true,
      hide_duplicates: defaults?.hide_duplicates ?? true,
      hide_rejected: defaults?.hide_rejected ?? true,
    });
    this.resetCardWidth();
    this.setGalleryMode(defaults?.gallery_mode ?? 'grid');
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

  /** Set star rating for a photo (0 = clear) */
  async setRating(photoPath: string, rating: number): Promise<void> {
    try {
      await firstValueFrom(this.api.post('/photo/set_rating', { photo_path: photoPath, rating }));
      this.photos.update(photos =>
        photos.map(p => p.path === photoPath ? { ...p, star_rating: rating || null } : p),
      );
    } catch { /* ignore */ }
  }

  /** Toggle favorite flag for a photo */
  async toggleFavorite(photoPath: string): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.post<{ is_favorite: boolean }>('/photo/toggle_favorite', { photo_path: photoPath }),
      );
      this.photos.update(photos =>
        photos.map(p => p.path === photoPath
          ? { ...p, is_favorite: res.is_favorite, is_rejected: res.is_favorite ? false : p.is_rejected }
          : p),
      );
    } catch { /* ignore */ }
  }

  /** Toggle rejected flag for a photo */
  async toggleRejected(photoPath: string): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.post<{ is_rejected: boolean }>('/photo/toggle_rejected', { photo_path: photoPath }),
      );
      this.photos.update(photos =>
        photos.map(p => p.path === photoPath
          ? { ...p, is_rejected: res.is_rejected, is_favorite: res.is_rejected ? false : p.is_favorite }
          : p),
      );
    } catch { /* ignore */ }
  }

  /** Batch favorite multiple photos */
  async batchFavorite(paths: string[]): Promise<void> {
    await firstValueFrom(this.api.post('/photos/batch_favorite', { photo_paths: paths }));
    const pathSet = new Set(paths);
    this.photos.update(photos =>
      photos.map(p => pathSet.has(p.path) ? { ...p, is_favorite: true, is_rejected: false } : p),
    );
  }

  /** Batch reject multiple photos */
  async batchReject(paths: string[]): Promise<void> {
    await firstValueFrom(this.api.post('/photos/batch_reject', { photo_paths: paths }));
    const pathSet = new Set(paths);
    this.photos.update(photos =>
      photos.map(p => pathSet.has(p.path) ? { ...p, is_rejected: true, is_favorite: false, star_rating: null } : p),
    );
  }

  /** Batch set rating for multiple photos */
  async batchRating(paths: string[], rating: number): Promise<void> {
    await firstValueFrom(this.api.post('/photos/batch_rating', { photo_paths: paths, rating }));
    const pathSet = new Set(paths);
    this.photos.update(photos =>
      photos.map(p => pathSet.has(p.path) ? { ...p, star_rating: rating || null } : p),
    );
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
    const f = this.filters();
    const cfg = this.config();
    const defaults = cfg?.defaults;

    // Only include params that differ from defaults
    const params: Record<string, string> = {};
    if (f.sort !== (defaults?.sort ?? 'aggregate')) params['sort'] = f.sort;
    if (f.sort_direction !== (defaults?.sort_direction ?? 'DESC'))
      params['sort_direction'] = f.sort_direction;

    // All string filters: include if non-empty
    const stringKeys: (keyof GalleryFilters)[] = [...RANGE_AND_SELECT_KEYS, 'similar_to', 'album_id', 'semanticQuery'];
    for (const key of stringKeys) {
      if (f[key]) params[key] = String(f[key]);
    }
    if (f.similar_to && f.min_similarity) params['min_similarity'] = f.min_similarity;
    if (f.similar_to && f.similarity_mode && f.similarity_mode !== 'visual') params['similarity_mode'] = f.similarity_mode;

    // Boolean filters: only include when different from defaults
    if (f.hide_details !== (defaults?.hide_details ?? true))
      params['hide_details'] = String(f.hide_details);
    if (f.hide_blinks !== (defaults?.hide_blinks ?? true))
      params['hide_blinks'] = String(f.hide_blinks);
    if (f.hide_bursts !== (defaults?.hide_bursts ?? true))
      params['hide_bursts'] = String(f.hide_bursts);
    if (f.hide_duplicates !== (defaults?.hide_duplicates ?? true))
      params['hide_duplicates'] = String(f.hide_duplicates);
    if (f.hide_rejected !== (defaults?.hide_rejected ?? true))
      params['hide_rejected'] = String(f.hide_rejected);
    if (f.favorites_only) params['favorites_only'] = 'true';
    if (f.is_monochrome) params['is_monochrome'] = 'true';

    this.router.navigate([], {
      queryParams: params,
      replaceUrl: true,
    });
  }

  /** Apply URL query params over a base filter state */
  private applyQueryParams(
    base: GalleryFilters,
    params: Record<string, string>,
  ): GalleryFilters {
    const result = { ...base };

    // String params
    const stringKeys: (keyof GalleryFilters)[] = [
      ...RANGE_AND_SELECT_KEYS, 'sort', 'sort_direction', 'similar_to', 'min_similarity', 'semanticQuery', 'album_id',
    ];
    for (const key of stringKeys) {
      if (params[key]) (result as Record<string, unknown>)[key] = params[key];
    }
    if (params['similarity_mode'] && ['visual', 'color', 'person'].includes(params['similarity_mode'])) {
      result.similarity_mode = params['similarity_mode'] as GalleryFilters['similarity_mode'];
    }

    // Boolean params
    if (params['hide_details'] !== undefined) result.hide_details = params['hide_details'] !== 'false';
    if (params['hide_blinks'] !== undefined) result.hide_blinks = params['hide_blinks'] !== 'false';
    if (params['hide_bursts'] !== undefined) result.hide_bursts = params['hide_bursts'] !== 'false';
    if (params['hide_duplicates'] !== undefined)
      result.hide_duplicates = params['hide_duplicates'] !== 'false';
    if (params['hide_rejected'] !== undefined) result.hide_rejected = params['hide_rejected'] !== 'false';
    if (params['favorites_only'] !== undefined) result.favorites_only = params['favorites_only'] === 'true';
    if (params['is_monochrome'] !== undefined) result.is_monochrome = params['is_monochrome'] === 'true';
    if (params['page']) result.page = parseInt(params['page'], 10) || 1;

    return result;
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

  /** Build API params from filters, omitting empty values */
  private buildApiParams(f: GalleryFilters): Record<string, string | number | boolean> {
    const params: Record<string, string | number | boolean> = {
      page: f.page,
      per_page: f.per_page,
      sort: f.sort,
      sort_direction: f.sort_direction,
    };

    // All string filters: include if non-empty
    const stringKeys: (keyof GalleryFilters)[] = [...RANGE_AND_SELECT_KEYS, 'album_id'];
    for (const key of stringKeys) {
      if (f[key]) params[key] = String(f[key]);
    }

    // Boolean filters
    if (f.hide_blinks) params['hide_blinks'] = true;
    if (f.hide_bursts) params['hide_bursts'] = true;
    if (f.hide_duplicates) params['hide_duplicates'] = true;
    if (f.hide_rejected) params['hide_rejected'] = true;
    if (f.favorites_only) params['favorites_only'] = '1';
    if (f.is_monochrome) params['is_monochrome'] = '1';

    // Smart albums apply their filters directly — don't send album_id
    // (server would do an empty album_photos JOIN otherwise)
    if (this.currentAlbum()?.is_smart) {
      delete params['album_id'];
    }

    return params;
  }
}
