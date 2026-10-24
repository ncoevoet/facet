import { Injectable, inject, signal, computed, effect, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, ActivatedRoute, NavigationStart } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom, timeout } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { UserActivityJournal, UserActivityKind, activityName } from '../../core/agent/user-activity-journal.service';
import { Photo, KeeperHint, normalisePhotoFlagsAll } from '../../shared/models/photo.model';
import { I18N } from '../../core/i18n/keys';
import { readReviewQueue, saveReviewQueue } from './review-queue.util';
import type { components } from '../../core/api/schema';
import {
  type GalleryFilters, type GalleryMode, type TooltipMode, type PanelActivation, type DisplayOptions,
  type ViewFilterParams,
  DEFAULT_FILTERS, DISPLAY_OPTION_KEYS,
  GALLERY_MODE_KEY, DRAWER_STATE_KEY, CARD_WIDTH_KEY,
  loadDisplayOptionsFromStorage, saveDisplayOptionsToStorage,
  countActiveFilters, applyQueryParams, applySavedAlbumFilters, buildSyncParams, buildApiParams,
  buildViewFilterParams, viewFilterParamsEqual, anyHideToggleActive,
  seededSearchThreshold, buildByPathsFilters, BY_PATHS_MAX, semanticSortPatch, smartAlbumFilterJson, exclusiveHidePatch,
} from './gallery-filters.util';

// Re-export the filter types/consts so existing importers of gallery.store keep working.
export type { GalleryFilters, GalleryMode, TooltipMode, PanelActivation, DisplayOptions, ViewFilterParams };
export { DEFAULT_FILTERS, anyHideToggleActive };

/** The five hide toggles the hidden-photos banner clears and restores together. */
export type HiddenFilterFlags = Pick<GalleryFilters,
  'hide_blinks' | 'hide_bursts' | 'hide_duplicates' | 'hide_brackets' | 'hide_panoramas'>;

export const FILTER_OPTIONS_TIMEOUT_MS = 20000;
export const REVIEW_RESUME_NAVIGATION = 'facetReviewResume';

/**
 * How many photo paths one batch-mutation request may name.
 *
 * The server's own bound on the field — `BatchPhotoRequest.photo_paths`,
 * `Field(default=None, max_length=1000)` — not a client-side preference: a
 * longer list is a 422, not a slow request.
 */
export const BATCH_PATHS_PER_REQUEST = 1000;

/**
 * Split a path list into request-sized chunks for any `photo_paths` endpoint.
 *
 * A list at or under the cap yields one chunk holding it unchanged, so the
 * common case is the single request it always was — including the empty list,
 * which yields one empty chunk: callers that must not post an empty target
 * (undo's replay, junk sweep's reject-all) check for it before calling.
 *
 * Undo cannot reach the cap today — `GalleryComponent.UNDO_MAX_PHOTOS` = 500
 * gates its only caller — but `restoreSnapshot` is a public store method, so it
 * chunks rather than relying on a bound held one file away.
 */
export function chunkPhotoPaths(paths: string[]): string[][] {
  if (paths.length <= BATCH_PATHS_PER_REQUEST) return [paths];
  const chunks: string[][] = [];
  for (let i = 0; i < paths.length; i += BATCH_PATHS_PER_REQUEST) {
    chunks.push(paths.slice(i, i + BATCH_PATHS_PER_REQUEST));
  }
  return chunks;
}

// --- API response types ---

export interface HiddenSummary {
  total: number;
  blinks: number;
  bursts: number;
  duplicates: number;
  brackets: number;
  panoramas: number;
}

export interface PhotosResponse {
  photos: Photo[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_more: boolean;
  hidden_summary?: HiddenSummary;
}

/** How many photos the current filters match, across every page. */
export interface PhotoCountResponse {
  total: number;
}

/** Every path the current filters match — unordered, and bounded server-side:
 *  a view past the cap is refused with a 412, never truncated. */
export interface PhotoPathsResponse {
  total: number;
  paths: string[];
}

/** Pre-mutation flag state, used to revert optimistic updates and power undo. */
export interface PhotoFlagSnapshot {
  is_favorite: boolean;
  is_rejected: boolean;
  is_kept?: boolean;
  star_rating: number | null;
}

/**
 * What a selection names.
 *
 * `'paths'` is an explicit list of photo paths. `'view'` is every row the
 * current filters match — the client never enumerates it, so it stays exact
 * however far past the loaded pages the view runs.
 */
export type SelectionScope = 'paths' | 'view';

/** Outcome of a batch mutation: what it touched, and what the server changed. */
export interface BatchResult {
  /** Pre-mutation flags for the photos the client could capture — LOADED ones
   *  only. Smaller than `targeted` whenever the action reached past the page,
   *  which is exactly when undo must not be offered. */
  snapshot: Map<string, PhotoFlagSnapshot>;
  /** How many photos the action was aimed at, as the client understood it. */
  targeted: number;
  /** How many rows the server reports it changed. */
  count: number;
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

export interface MetricRange {
  min: number;
  max: number;
  buckets: number[];
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
    hide_brackets: boolean;
    hide_panoramas: boolean;
    hide_details: boolean;
    tooltip_mode: TooltipMode;
    panel_activation: PanelActivation;
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
  /** Photos-column names of metrics hidden by the licensing policy (commercial mode). */
  unavailable_metrics?: string[];
  /** Extended-IQA score columns at least one photo carries (their model has run). */
  populated_scores?: string[];
  /** Default merge-suggestion threshold of the active face-recognition model. */
  face_merge_threshold?: number;
  features: {
    show_similar_button: boolean;
    show_merge_suggestions: boolean;
    show_rating_controls: boolean;
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
    show_my_taste?: boolean;
    show_scenes?: boolean;
    show_junk_sweep?: boolean;
    show_social_export?: boolean;
  };
  quality_thresholds: {
    good: number;
    great: number;
    excellent: number;
    best: number;
  };
  /** Resolved semantic-search cosine gate (0-1) for the active encoder, always
   *  present -- the client seeds its filter state from this rather than a
   *  hardcoded constant. */
  search_threshold_default: number;
  /** Per-badge opt-out for the gallery card (`viewer.badges`). Every key
   *  defaults to true except shadow clipping — see DEFAULT_BADGE_VISIBILITY. */
  badges?: Record<string, boolean>;
  /** One definition of "clipped" shared by the card badge, the histogram
   *  markers and the gallery filter, plus each histogram surface's own house
   *  default channel mode (validated with `isHistogramMode` before use — the
   *  server sends a plain string). */
  clipping?: {
    badge_percent?: number;
    indicator_percent?: number;
    histogram_mode?: string;
    tooltip_histogram_mode?: string;
  };
  /** Min narrative-moment posterior below which a moment label is shown dimmed + "(uncertain)". 0 = never dim. */
  moment_confidence_min?: number;
  /** Social-export crop presets surfaced to the download menu. */
  social_export?: {
    presets: { key: string; label_key: string; aspect: string }[];
  };
  /** Named darktable styles for the edited-look cull preview. Empty/absent = feature hidden. */
  cull_styles?: { name: string; label_key: string }[];
  /** Whether the "Trash rejects" cull action can succeed server-side (config allows it AND
   *  send2trash is importable). Absent/undefined reads as unavailable (fail-closed). */
  cull?: { allow_trash: boolean; trash_available: boolean };
  /** RAW rows whose stored thumbnail still comes from the pre-fix rendering.
   *  Served from the stats cache, so it is an estimate that trails the last refresh
   *  by at most one TTL — never a number to drive anything but the advisory banner. */
  render_migration?: { pending: number };
  [key: string]: unknown;
}

/** One page of `/api/similar_photos`; `message` is a machine code from
 *  `SimilarPhotosResponse` (`no_visual_features`, `no_histogram`, `no_faces`). */
type SimilarPage = Pick<components['schemas']['SimilarPhotosResponse'], 'total' | 'has_more' | 'message'> & {
  similar: Photo[];
};

/** Machine code from /similar_photos -> the translated reason shown instead of an empty grid. */
const SIMILAR_REASON_KEYS = {
  no_visual_features: I18N.similar.no_visual_features,
  no_histogram: I18N.similar.no_histogram,
  no_faces: I18N.similar.no_faces,
} as const;

/** The journal entry a batch endpoint stands for, with the value the user chose. */
const BATCH_ACTIVITY: Record<string, { kind: UserActivityKind; value: (extra: Record<string, unknown>) => unknown }> = {
  '/photos/batch_favorite': { kind: 'favorite', value: () => true },
  '/photos/batch_reject': { kind: 'reject', value: () => true },
  '/photos/batch_rating': { kind: 'rating', value: extra => extra['rating'] ?? null },
};

@Injectable({ providedIn: 'root' })
export class GalleryStore {
  private api = inject(ApiService);
  private auth = inject(AuthService);
  private albumService = inject(AlbumService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private snackBar = inject(MatSnackBar);
  private i18n = inject(I18nService);
  private assistantChanges = inject(AssistantChangesService);
  private journal = inject(UserActivityJournal);

  readonly reviewProgress = signal<components['schemas']['ReviewProgressResponse'] | null>(null);
  readonly reviewPercent = computed(() => {
    const progress = this.reviewProgress();
    return progress?.total ? Math.floor(100 * (progress.kept + progress.rejected) / progress.total) : 0;
  });
  private readonly bookmarkVersion = signal(0);
  readonly reviewBookmark = computed(() => {
    this.bookmarkVersion();
    return readReviewQueue(this.auth.identity());
  });
  private reviewProgressSeq = 0;
  private resumeSeq = 0;
  private readonly transientReviewStatus = signal(false);

  private reviewProgressKey(): string {
    const scope = buildApiParams(this.filters(), this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default);
    delete scope['page'];
    delete scope['per_page'];
    return JSON.stringify([scope, this.currentAlbum()?.smart_filter_json]);
  }

  async startReviewQueue(): Promise<void> {
    await this.updateFilter('review_status', 'undecided', true);
  }

  /** The same full query as the grid; pagination never affects the aggregate. */
  async loadReviewProgress(): Promise<void> {
    const seq = ++this.reviewProgressSeq;
    const identity = this.auth.identity();
    const key = this.reviewProgressKey();
    this.reviewProgress.set(null);
    if (this.pinnedPaths() !== null || this.filters().similar_to) return;
    const params = buildApiParams(this.filters(), this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default);
    const album = this.currentAlbum();
    if (album?.is_smart && album.smart_filter_json) {
      try {
        const saved = JSON.parse(album.smart_filter_json).review_status;
        const status = this.transientReviewStatus() || !this.auth.isEdition() ? saved : this.filters().review_status;
        if (status) params['scope_review_status'] = status;
      } catch { return; }
    }
    try {
      const progress = await firstValueFrom(this.api.get<components['schemas']['ReviewProgressResponse']>('/photos/review_progress', params));
      if (seq === this.reviewProgressSeq && identity === this.auth.identity() && key === this.reviewProgressKey()) this.reviewProgress.set(progress);
    } catch { /* Counts unavailable: never show a guessed denominator. */ }
  }

  /** Restore this browser's queue and return its first remaining photo, skipping deleted/decided rows. */
  async continueReview(ownsView: () => boolean = () => true): Promise<string | null> {
    const queue = this.reviewBookmark();
    if (!queue || !ownsView()) return null;
    const seq = ++this.resumeSeq;
    const identity = this.auth.identity();
    const loadSeq = this._loadSeq;
    const originKey = this.filterKey();
    let album: Album | null = null;
    if (queue.filters.album_id) {
      try { album = await firstValueFrom(this.albumService.get(+queue.filters.album_id)); }
      catch {
        if (seq === this.resumeSeq && ownsView() && identity === this.auth.identity() && loadSeq === this._loadSeq) this.notifyActionFailed();
        return null;
      }
    }
    if (seq !== this.resumeSeq || !ownsView() || identity !== this.auth.identity() || loadSeq !== this._loadSeq || originKey !== this.filterKey()) return null;
    let restored = queue.filters;
    if (album) {
      // Album criteria can change after bookmarking: the current saved scope wins.
      const base = { ...DEFAULT_FILTERS, per_page: restored.per_page, sort: restored.sort, sort_direction: restored.sort_direction,
        hide_blinks: restored.hide_blinks, hide_bursts: restored.hide_bursts, hide_duplicates: restored.hide_duplicates,
        hide_brackets: restored.hide_brackets, hide_panoramas: restored.hide_panoramas, hide_rejected: restored.hide_rejected };
      try {
        restored = applySavedAlbumFilters(base, album.smart_filter_json ?? '{}', String(album.id));
      } catch { this.notifyActionFailed(); return null; }
      if (restored.review_status && restored.review_status !== 'undecided') {
        this.notifyActionFailed();
        return null;
      }
    }
    this.cancelRangeLoad();
    this.clearSelection();
    this.transientReviewStatus.set(true);
    this.currentAlbum.set(album);
    this.filters.set({ ...restored, review_status: 'undecided', album_id: queue.filters.album_id || '0', page: 1 });
    // Keep the current component mounted; album_id in the URL also supports reload.
    await this.router.navigate([], {
      queryParams: { ...this.galleryQueryParams(), album_id: this.filters().album_id || '0' },
      replaceUrl: true,
      state: { [REVIEW_RESUME_NAVIGATION]: seq },
    });
    if (seq !== this.resumeSeq || !ownsView() || identity !== this.auth.identity()) return null;
    const scopeKey = this.filterKey();
    const acceptsResume = () => seq === this.resumeSeq && ownsView() && scopeKey === this.filterKey();
    const loading = this.loadPhotos(acceptsResume);
    const expected = this._loadSeq;
    await loading;
    if (expected !== this._loadSeq || !acceptsResume() || identity !== this.auth.identity()) return null;
    const first = this.photos()[0]?.path ?? null;
    this.focusedPath.set(first);
    return first;
  }

  // --- State signals ---
  readonly filters = signal<GalleryFilters>({ ...DEFAULT_FILTERS });
  readonly currentAlbum = signal<Album | null>(null);
  readonly initializing = signal(false);
  /** Bumped each time the gallery page initialises, so a caller that navigated to it can await a real mount rather than a delay. */
  readonly galleryMounts = signal(0);
  private smartSaveTimer: ReturnType<typeof setTimeout> | null = null;
  private rangeLoadTimer: ReturnType<typeof setTimeout> | null = null;
  readonly photos = signal<Photo[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  /** Set when the current photo request failed; the grid stays empty rather than
   *  silently reinstating the previous view's photos. Cleared on every new load. */
  readonly loadError = signal(false);
  /** i18n key explaining a load error the server diagnosed (e.g. a source photo
   *  with nothing to compare), shown instead of the generic failure message. */
  readonly loadErrorKey = signal<string | undefined>(undefined);
  private _loadSeq = 0;
  /** In-place refreshes run one after another so batches land in arrival order; a failure never blocks the next. */
  private refreshChain: Promise<void> = Promise.resolve();
  /** A null batch arrived while a page fetch was in flight: `nextPage` runs the view refetch when it completes. */
  private viewRefreshOwed = false;
  /** False until the gallery has asked for photos once: a write seen from /culling or /stats must not load it. */
  private loadedOnce = false;
  /**
   * An explicit, ordered photo list shown in place of the filtered view (set by the
   * assistant's `ui_show_photos`). Deliberately NOT a GalleryFilters key: it never reaches
   * the URL, a smart album or buildApiParams. `loadPhotos` clears it unless `showPaths`
   * raised `pinnedLoad`, so every filter writer that reloads also drops the pin.
   */
  readonly pinnedPaths = signal<string[] | null>(null);
  /** Requested paths the server did not return for the current pin (invisible, unknown). */
  readonly pinnedMissing = signal<string[]>([]);
  private pinnedLoad = false;
  /**
   * The photo the keyboard cursor last stood on, mirrored by the gallery's `setCursor` for
   * `ui_get_context`. Unlike the cursor it survives the window losing focus (the user switching to
   * the agent), and goes only when its photo leaves the list or the cursor is dropped on purpose.
   * Hover never sets it.
   */
  readonly focusedPath = signal<string | null>(null);
  readonly hasMore = signal(false);
  readonly config = signal<ViewerConfig | null>(null);
  readonly filterDrawerOpen = signal(localStorage.getItem(DRAWER_STATE_KEY) === 'true');
  readonly slideshowActive = signal(false);
  readonly cardWidth = signal(parseInt(localStorage.getItem(CARD_WIDTH_KEY) ?? '', 10) || 0);
  readonly galleryMode = signal<GalleryMode>((localStorage.getItem(GALLERY_MODE_KEY) as GalleryMode) || 'grid');
  /** Row-windowed rendering for large galleries; 'off' opts back into full DOM rendering. */
  readonly virtualScroll = signal(localStorage.getItem('facet_virtual_scroll') !== 'off');

  // Hidden-photo summary (populated from /photos response)
  readonly hiddenSummary = signal<HiddenSummary>({ total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });

  /** The gallery's EFFECTIVE hide-toggle state as explicit '1'/'0' wire strings —
   *  see buildViewFilterParams. Consumers that fetch independently of the gallery
   *  grid (timeline, folders, type counts) read this rather than re-deriving it,
   *  so they stay in sync with whatever the user has actually toggled. The custom
   *  `equal` keeps this signal stable across unrelated filter churn (camera, page,
   *  sort…), so effects that depend on it only re-fire when a hide toggle changes. */
  readonly viewFilterParams = computed(
    () => buildViewFilterParams(this.filters()),
    { equal: viewFilterParamsEqual },
  );

  /**
   * The hide toggles as they stood before "Show all" cleared them.
   *
   * View state, not a filter: "Show all" used to be one-way, so peeking at the
   * blinks and burst frames a filter was holding back meant walking to the
   * sidebar and re-ticking boxes from memory. Lives on the store (rather than a
   * single component) because both the gallery banner and the timeline's
   * reachability banner offer the same show-all/restore affordance.
   */
  readonly hiddenFiltersStash = signal<HiddenFilterFlags | null>(null);

  // --- View snapshot for back-navigation restoration ---
  readonly viewSnapshot = signal<{ scrollTop: number; albumId: string | null; filterKey: string } | null>(null);

  /** Cheap equality token for the current query state (or an explicit candidate filter set). */
  filterKey(f: GalleryFilters = this.filters()): string {
    return JSON.stringify(buildApiParams(f, this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default));
  }

  // --- Selection state (store-level so it survives navigation and is visible to services) ---
  //
  // Two scopes, because the gallery paginates. A 'paths' selection names
  // photos, so it deliberately survives navigation and filter changes. A 'view'
  // selection names the VIEW: nothing is enumerated, mutations send the filter
  // and the server derives the rows, which is what makes "select all" mean all
  // 650 rather than the 64 fetched so far. `excludedPaths` carries the few the
  // user then unticked.
  readonly selectedPaths = signal<Set<string>>(new Set());
  readonly selectionScope = signal<SelectionScope>('paths');
  /** Photos unticked out of a 'view'-scoped selection. Always empty under 'paths'. */
  readonly excludedPaths = signal<Set<string>>(new Set());
  private lastSelectedIndex = -1;

  readonly selectionCount = computed(() =>
    this.viewScopeSelected()
      ? Math.max(0, this.total() - this.excludedPaths().size)
      : this.selectedPaths().size,
  );

  /** True while the selection means "every photo the current filters match". */
  readonly viewScopeSelected = computed(() => this.selectionScope() === 'view');

  /**
   * Whether the current view can be handed to the server AS a filter.
   *
   * `similar_to` ranks server-side outside the gallery's WHERE clause, and the
   * filter-scoped endpoints (cull, export, writes, select_bottom_percent) do not
   * know `semantic_q`: no payload reproduces either, so a 'view'-scoped
   * selection under either would quietly stand for a different set of photos
   * than the one on screen. Select-all falls back to the loaded photos there —
   * a shortcut that does less is still better than one that no-ops.
   */
  readonly canScopeSelectionToView = computed(() => {
    const f = this.filters();
    return !f.similar_to && !f.semanticQuery && this.pinnedPaths() === null;
  });

  /** The loaded photos the selection covers, in grid order — either scope. */
  readonly selectedLoadedPaths = computed(() => {
    if (this.viewScopeSelected()) {
      const excluded = this.excludedPaths();
      return this.photos().filter(p => !excluded.has(p.path)).map(p => p.path);
    }
    const selected = this.selectedPaths();
    return this.photos().filter(p => selected.has(p.path)).map(p => p.path);
  });

  /**
   * Toggle a photo's selection; shift-click extends from the last selected index.
   *
   * Under 'view' scope the sets are mirrored: everything is already selected,
   * so what a click builds is the EXCLUSION list.
   */
  toggleSelection(photo: Photo, event?: MouseEvent): void {
    const photos = this.photos();
    const clickedIndex = photos.findIndex(p => p.path === photo.path);
    const target = this.viewScopeSelected() ? this.excludedPaths : this.selectedPaths;
    const next = new Set(target());

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
    target.set(next);
  }

  /**
   * Select everything.
   *
   * From an EMPTY selection that means the whole filtered view, and it costs no
   * request: the filter set the grid was already fetched with is the selection.
   * From a partial one it widens to the loaded photos only — which is what the
   * button in the selection bar reads as — and the bar then offers the
   * escalation to the whole view explicitly rather than taking it silently.
   */
  selectAll(): void {
    // Already view-scoped: "select all" can only mean re-ticking whatever was
    // unticked. Falling through would DESELECT the view down to the loaded page.
    const meansEverything = this.viewScopeSelected() || this.selectionCount() === 0;
    if (meansEverything && this.canScopeSelectionToView()) {
      this.selectWholeView();
      return;
    }
    this.selectAllLoaded();
  }

  /** Select every currently loaded photo, as an explicit path set. */
  selectAllLoaded(): void {
    this.selectionScope.set('paths');
    this.excludedPaths.set(new Set());
    this.selectedPaths.set(new Set(this.photos().map(p => p.path)));
  }

  /** Select the whole filtered view without enumerating it. Makes no request. */
  selectWholeView(): void {
    this.selectedPaths.set(new Set());
    this.excludedPaths.set(new Set());
    this.selectionScope.set('view');
    this.lastSelectedIndex = -1;
  }

  /**
   * Swap the selection for its complement. Three cases, none of them a request:
   *
   * - Empty selection: the complement of nothing is everything, and everything
   *   is the filter — not the page of it that happens to be loaded. This is the
   *   case the old "deliberately bounded to what is loaded" note got wrong once
   *   the view outgrew a page.
   * - 'view' scope: the complement of "all but these" is "these", which the
   *   exclusion list already spells out exactly.
   * - A partial 'paths' selection: the complement over the LOADED photos, and
   *   still deliberately bounded there. Inverting a hand-picked keep list is
   *   the "pick the keepers, invert, reject" move, and it must not reach photos
   *   the user never looked at.
   */
  invertSelection(): void {
    if (this.viewScopeSelected()) {
      const excluded = this.excludedPaths();
      this.selectionScope.set('paths');
      this.excludedPaths.set(new Set());
      this.selectedPaths.set(new Set(excluded));
      this.lastSelectedIndex = -1;
      return;
    }
    const selected = this.selectedPaths();
    if (selected.size === 0 && this.canScopeSelectionToView()) {
      this.selectWholeView();
      return;
    }
    this.selectedPaths.set(new Set(
      this.photos().filter(p => !selected.has(p.path)).map(p => p.path),
    ));
    this.lastSelectedIndex = -1;
  }

  clearSelection(): void {
    this.selectedPaths.set(new Set());
    this.excludedPaths.set(new Set());
    this.selectionScope.set('paths');
    this.lastSelectedIndex = -1;
  }

  /**
   * Drop a 'view'-scoped selection.
   *
   * A path selection survives a filter change on purpose: it names photos, and
   * photos do not move. A view selection names the view, so the moment the
   * filters change it stands for a different set of photos — and the next batch
   * action would send the NEW filter. Called from loadPhotos(), which every
   * filter change goes through; pagination (nextPage) deliberately does not,
   * since appending a page does not change what the view is.
   */
  private resetViewScope(): void {
    if (!this.viewScopeSelected()) return;
    this.selectedPaths.set(new Set());
    this.excludedPaths.set(new Set());
    this.selectionScope.set('paths');
    this.lastSelectedIndex = -1;
  }

  /** Restore a previously captured selection (used by undo). */
  restoreSelection(paths: Iterable<string>): void {
    this.selectionScope.set('paths');
    this.excludedPaths.set(new Set());
    this.selectedPaths.set(new Set(paths));
  }

  /**
   * The current view as the filter payload the server accepts in place of a
   * path list. Null when the view cannot be expressed as one.
   *
   * Every value is stringified because this same shape travels as a query
   * string on `GET /photos`, where `ApiService` runs it through `String()` —
   * and the server's `GalleryParams` types the hide toggles as `str`, so a raw
   * JSON `true` in a POST body would 422 where `'true'` parses.
   */
  filterPayload(): Record<string, string> | null {
    if (!this.canScopeSelectionToView()) return null;
    const params = buildApiParams(this.filters(), this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default);
    return Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]));
  }

  /**
   * How many photos the current filters match, across every page.
   *
   * Asked of the server rather than read off `total()`: a whole-view mutation
   * is about to change rows the user cannot see, so the number it is confirmed
   * against must not be whichever page response happened to land last.
   */
  async countInView(): Promise<number | null> {
    const params = this.filterPayload();
    if (!params) return null;
    try {
      const res = await firstValueFrom(this.api.get<PhotoCountResponse>('/photos/count', params));
      return res.total;
    } catch {
      this.notifyActionFailed();
      return null;
    }
  }

  /**
   * Every path the current filters match, minus the excluded ones.
   *
   * The on-demand escape hatch for the handful of actions that genuinely need
   * strings client-side (copy filenames, download, add to album) — never for
   * selection, which is the whole point of the 'view' scope: this costs one
   * response covering the entire filtered set.
   *
   * The server refuses rather than truncates past its own cap (412, the shape
   * `/api/cull/apply` and `/api/export/sidecars` already use), because half a
   * view silently copied or added to an album is worse than none. Say so in
   * those words: "action failed" reads as a bug the user cannot act on, while
   * "too many photos" names the filter as the way out.
   */
  async pathsInView(): Promise<string[] | null> {
    const params = this.filterPayload();
    if (!params) return null;
    try {
      const res = await firstValueFrom(
        this.api.get<PhotoPathsResponse>('/photos/paths', params),
      );
      const excluded = this.excludedPaths();
      return res.paths.filter(p => !excluded.has(p));
    } catch (err) {
      if (err instanceof HttpErrorResponse && err.status === 412) {
        this.snackBar.open(
          this.i18n.t(I18N.gallery.selection.paths_too_many), '', { duration: 5000 },
        );
      } else {
        this.notifyActionFailed();
      }
      return null;
    }
  }

  // Filter options
  readonly types = signal<TypeCount[]>([]);
  readonly cameras = signal<FilterOption[]>([]);
  readonly lenses = signal<FilterOption[]>([]);
  readonly tags = signal<FilterOption[]>([]);
  readonly persons = signal<PersonOption[]>([]);
  readonly patterns = signal<FilterOption[]>([]);
  readonly colorTemps = signal<FilterOption[]>([]);
  readonly hueBuckets = signal<FilterOption[]>([]);
  readonly metricRanges = signal<Record<string, MetricRange>>({});

  /** Reverse-geocoded place name for the active GPS filter. */
  readonly gpsLocationName = signal('');

  private readonly gpsCoords = computed(() => {
    const f = this.filters();
    return f.gps_lat && f.gps_lng ? `${f.gps_lat},${f.gps_lng}` : '';
  });

  private _gpsLocationSeq = 0;

  private gpsLocationEffect = effect(() => {
    const coords = this.gpsCoords();
    const seq = ++this._gpsLocationSeq;
    if (!coords) {
      this.gpsLocationName.set('');
      return;
    }
    const [lat, lng] = coords.split(',');
    firstValueFrom(this.api.get<{ display_name: string }>('/filter_options/location_name', { lat, lng }))
      .then(res => {
        if (seq !== this._gpsLocationSeq) return;
        this.gpsLocationName.set(res.display_name || `${(+lat).toFixed(2)}, ${(+lng).toFixed(2)}`);
      })
      .catch(() => {
        if (seq !== this._gpsLocationSeq) return;
        this.gpsLocationName.set(`${(+lat).toFixed(2)}, ${(+lng).toFixed(2)}`);
      });
  });

  // --- Computed ---
  readonly activeFilterCount = computed(() => countActiveFilters(this.filters()));

  constructor() {
    effect(() => { this.auth.identity(); untracked(() => this.clearForeignReviewedPhotos()); });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart
        && this.router.currentNavigation?.()?.extras?.state?.[REVIEW_RESUME_NAVIGATION] !== this.resumeSeq) this.resumeSeq++;
    });
    effect(() => {
      this.auth.identity();
      untracked(() => { this.reviewProgressSeq++; this.resumeSeq++; this.reviewProgress.set(null); });
    });
    this.assistantChanges.batch$.pipe(takeUntilDestroyed()).subscribe(batch => void this.refreshPaths(batch.paths));
    // Auto-save album filters on change (debounced) — persists filter state for all albums
    effect(() => {
      const f = this.filters();
      const album = this.currentAlbum();
      const temporaryQueue = this.transientReviewStatus();
      if (this.smartSaveTimer) { clearTimeout(this.smartSaveTimer); this.smartSaveTimer = null; }
      if (!album || temporaryQueue) return;
      if (untracked(() => this.initializing())) return;
      const isEdition = untracked(() => this.auth.isEdition());
      if (!isEdition) return;

      const json = smartAlbumFilterJson(f);

      untracked(() => {
        if (this.smartSaveTimer) clearTimeout(this.smartSaveTimer);
        this.smartSaveTimer = setTimeout(() => {
          firstValueFrom(this.albumService.update(album.id, { smart_filter_json: json })).catch(() => {
            // The filters stay applied on screen whether or not the write
            // landed, so a swallowed rejection reads exactly like a save.
            this.snackBar.open(this.i18n.t(I18N.albums.smart_save_failed), '', { duration: 5000 });
          });
        }, 500);
      });
    });
  }

  /** Re-fetch viewer config (features + edition/identity flags) WITHOUT re-applying
   *  filter defaults — used after an auth identity change (login, edition grant or
   *  drop) so config-derived UI reflects the new rights without clobbering the
   *  user's active filters. */
  async refreshConfig(): Promise<void> {
    try {
      this.config.set(await firstValueFrom(this.api.get<ViewerConfig>('/config')));
    } catch {
      // Keep the existing config on failure.
    }
  }

  /** Load viewer config and apply defaults */
  async loadConfig(): Promise<void> {
    this.transientReviewStatus.set(this.route.snapshot.queryParams['review_queue'] === '1');
    // loadConfig replaces `filters` wholesale, so an explicit list shown under the old ones is stale.
    this.pinnedPaths.set(null);
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
        // No `?? 0.15` fallback: a client-side default would silently diverge
        // from the server's calibrated per-model value the moment the two
        // disagreed. A MISSING field resolves to '' rather than a guess, which
        // is what makes /search omit `threshold` and resolve its own.
        search_threshold: seededSearchThreshold(cfg.search_threshold_default),
        sort: defaults?.sort ?? 'aggregate',
        sort_direction: defaults?.sort_direction ?? 'DESC',
        type: defaults?.type ?? '',
        hide_details: storedDisplay.hide_details ?? (defaults?.hide_details ?? true),
        tooltip_mode: storedDisplay.tooltip_mode ?? (defaults?.tooltip_mode ?? 'hover'),
        panel_activation: storedDisplay.panel_activation ?? (defaults?.panel_activation ?? 'both'),
        hide_blinks: storedDisplay.hide_blinks ?? (defaults?.hide_blinks ?? true),
        hide_bursts: storedDisplay.hide_bursts ?? (defaults?.hide_bursts ?? true),
        hide_duplicates: storedDisplay.hide_duplicates ?? (defaults?.hide_duplicates ?? true),
        hide_brackets: storedDisplay.hide_brackets ?? (defaults?.hide_brackets ?? true),
        hide_panoramas: storedDisplay.hide_panoramas ?? (defaults?.hide_panoramas ?? true),
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
  async loadPhotos(acceptResult: () => boolean = () => true): Promise<void> {
    // Always load from page 1 — only nextPage() uses page > 1
    const pinned = this.pinnedLoad ? this.pinnedPaths() : null;
    this.pinnedLoad = false;
    if (!pinned) {
      this.pinnedPaths.set(null);
    }
    this.resetViewScope();
    this.filters.update(current => ({ ...current, page: 1 }));
    const seq = ++this._loadSeq;
    const identity = this.auth.identity();
    this.loadedOnce = true;
    void this.loadReviewProgress();
    this.photos.set([]);
    this.loadError.set(false);
    this.loadErrorKey.set(undefined);
    this.loading.set(true);
    try {
      const f = this.filters();

      if (pinned) {
        const res = await firstValueFrom(
          this.api.post<{ photos: Photo[]; total: number; missing: string[] }>('/photos/by_paths', { paths: pinned }),
        );
        if (seq !== this._loadSeq || identity !== this.auth.identity() || !acceptResult()) return;
        this.photos.set(normalisePhotoFlagsAll(res.photos));
        this.total.set(res.photos.length);
        this.hasMore.set(false);
        this.pinnedMissing.set(res.missing);
        this.hiddenSummary.set({ total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });
        return;
      }

      if (f.similar_to) {
        const res = await this.fetchSimilarPage(f, (f.page - 1) * f.per_page);
        if (seq !== this._loadSeq || identity !== this.auth.identity() || !acceptResult()) return;
        this.photos.set(normalisePhotoFlagsAll(res.similar ?? []));
        this.total.set(res.total);
        this.hasMore.set(res.has_more);
        const reasonKey = res.message ? SIMILAR_REASON_KEYS[res.message] : undefined;
        if (reasonKey) {
          this.loadErrorKey.set(reasonKey);
          this.loadError.set(true);
        }
        return;
      }

      const params = buildApiParams(f, this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default);
      const res = await firstValueFrom(this.api.get<PhotosResponse>('/photos', params));
      if (seq !== this._loadSeq || identity !== this.auth.identity() || !acceptResult()) return;
      this.photos.set(normalisePhotoFlagsAll(res.photos));
      if (f.review_status === 'undecided') {
        saveReviewQueue(this.auth.identity(), f);
        this.bookmarkVersion.update(n => n + 1);
      }
      this.total.set(res.total);
      this.hasMore.set(res.has_more);
      this.hiddenSummary.set(
        res.hidden_summary ?? { total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 },
      );
      void this.fetchKeeperHints(res.photos.map(p => p.path));
    } catch {
      if (seq !== this._loadSeq || identity !== this.auth.identity() || !acceptResult()) return;
      this.total.set(0);
      this.hasMore.set(false);
      this.loadError.set(true);
    } finally {
      if (seq === this._loadSeq && identity === this.auth.identity() && acceptResult()) {
        this.loading.set(false);
      }
    }
  }

  /**
   * Show exactly these photos, in this order, until any filter change reloads the view.
   * Resolves with the requested paths the server did not return.
   */
  async showPaths(paths: string[]): Promise<string[]> {
    // The previous view's selection names photos this list may not hold.
    this.clearSelection();
    this.pinnedPaths.set(paths);
    this.pinnedMissing.set([]);
    this.pinnedLoad = true;
    await this.loadPhotos();
    return this.pinnedMissing();
  }

  /**
   * Bring the rows an assistant write changed up to date WITHOUT reloading the grid: the pin,
   * the scroll position and the selection all survive.
   * `paths` null means the write's scope is not enumerable, so the whole view is refetched and swapped
   * in when it lands. Best effort: a failed refetch leaves the rows as they are. A no-op until the
   * gallery has loaded once, so a write seen from /culling or /stats never loads it behind the user.
   */
  async refreshPaths(paths: string[] | null): Promise<void> {
    if (!this.loadedOnce) return;
    void this.loadReviewProgress();
    const loadSeq = this._loadSeq;
    const run = this.refreshChain.then(() => this.runRefresh(paths, loadSeq));
    this.refreshChain = run.catch(() => undefined);
    await run;
  }

  private async runRefresh(paths: string[] | null, loadSeq: number): Promise<void> {
    try {
      if (paths === null) {
        if (this.pinnedPaths() !== null) await this.refreshPinnedList(loadSeq);
        else await this.refreshViewInPlace(loadSeq);
        return;
      }
      const loaded = new Set(this.photos().map(p => p.path));
      const wanted = [...new Set(paths)].filter(path => loaded.has(path));
      if (wanted.length === 0) return;
      const pinned = this.pinnedPaths() !== null;
      const f = this.filters();
      const membership = !pinned && !f.similar_to;
      const filters = membership
        ? buildByPathsFilters(f, this.currentAlbum()?.is_smart ?? false, this.config()?.defaults?.type ?? '', this.config()?.search_threshold_default)
        : undefined;
      const { rows, missing } = await this.fetchByPaths(wanted, filters);
      if (!this.claimRefresh(loadSeq)) return;
      this.mergeRows(rows);
      // A similarity view ranks outside the gallery's WHERE clause: by_paths cannot say a photo left it.
      if (pinned || membership) this.dropMissing(missing);
    } catch {
      // Best effort: the rows stay as they were.
    }
  }

  /** True when this refresh may land: the view was not reloaded since it started. */
  private claimRefresh(loadSeq: number): boolean {
    return loadSeq === this._loadSeq;
  }

  /** POST the paths in chunks of the server cap; `missing` is requested minus returned. */
  private async fetchByPaths(
    paths: string[],
    filters?: Record<string, string | number | boolean>,
  ): Promise<{ rows: Photo[]; missing: string[] }> {
    const chunks: string[][] = [];
    for (let i = 0; i < paths.length; i += BY_PATHS_MAX) chunks.push(paths.slice(i, i + BY_PATHS_MAX));
    const responses = await Promise.all(chunks.map(chunk => firstValueFrom(
      this.api.post<{ photos: Photo[] }>('/photos/by_paths', filters ? { paths: chunk, filters } : { paths: chunk }),
    )));
    const rows = normalisePhotoFlagsAll(responses.flatMap(res => res.photos));
    const returned = new Set(rows.map(p => p.path));
    return { rows, missing: paths.filter(path => !returned.has(path)) };
  }

  private mergeRows(rows: Photo[]): void {
    const fresh = new Map(rows.map(p => [p.path, p] as const));
    this.photos.update(current => current.map(p => {
      const next = fresh.get(p.path);
      return next ? { ...p, ...next } : p;
    }));
  }

  /** Remove photos that are no longer part of the view, and out of the pin with them. */
  private dropMissing(missing: string[]): void {
    if (missing.length === 0) return;
    const gone = new Set(missing);
    this.removePhotos(gone);
    if (this.pinnedPaths() === null) return;
    this.pinnedPaths.update(current => current && current.filter(path => !gone.has(path)));
    this.pinnedMissing.update(current => [...new Set([...current, ...missing])]);
  }

  /** Refetch the whole pinned list quietly: the pin and the grid stay up until the rows swap. */
  private async refreshPinnedList(loadSeq: number): Promise<void> {
    const pinned = this.pinnedPaths() ?? [];
    if (pinned.length === 0) return;
    const { rows, missing } = await this.fetchByPaths(pinned);
    if (!this.claimRefresh(loadSeq)) return;
    const fresh = new Map(rows.map(p => [p.path, p] as const));
    const old = new Map(this.photos().map(p => [p.path, p] as const));
    this.photos.set(pinned.filter(path => fresh.has(path)).map(path => ({ ...old.get(path), ...fresh.get(path) }) as Photo));
    this.total.set(rows.length);
    this.dropMissing(missing);
  }

  /**
   * Refetch the loaded pages of a filter view and swap them in when they land. Unlike `loadPhotos`
   * this blanks nothing and leaves `selectedPaths`, `excludedPaths` and a view-scoped selection alone.
   * A similarity view keeps its rows: its membership is not a filter. A semantic search is a filter.
   */
  private async refreshViewInPlace(loadSeq: number): Promise<void> {
    if (this.filters().similar_to) {
      // A similarity view keeps its membership: refresh the rows on screen without filters and never remove one.
      const { rows } = await this.fetchByPaths(this.photos().map(p => p.path));
      if (this.claimRefresh(loadSeq)) this.mergeRows(rows);
      return;
    }
    // One re-run when the user paged mid-fetch; a page fetch in flight defers the refetch to `nextPage`.
    for (let attempt = 0; attempt < 2; attempt++) {
      if (this.loading()) {
        this.viewRefreshOwed = true;
        return;
      }
      const f = this.filters();
      const base = buildApiParams(f, this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default);
      const pages: PhotosResponse[] = [];
      for (let page = 1; page <= f.page; page++) {
        pages.push(await firstValueFrom(this.api.get<PhotosResponse>('/photos', { ...base, page })));
      }
      if (!this.claimRefresh(loadSeq)) return;
      if (this.filters().page !== f.page) continue;
      const last = pages[pages.length - 1];
      const rows = normalisePhotoFlagsAll(pages.flatMap(res => res.photos));
      this.photos.set(rows);
      this.total.set(last.total);
      this.hasMore.set(last.has_more);
      this.hiddenSummary.set(
        pages[0].hidden_summary ?? { total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 },
      );
      void this.fetchKeeperHints(rows.map(p => p.path));
      return;
    }
  }

  /** Reload what is on screen without it counting as a filter change: a pinned list stays pinned. */
  async reloadPhotos(): Promise<void> {
    this.pinnedLoad = this.pinnedPaths() !== null;
    await this.loadPhotos();
  }

  /** Drop the explicit list and reload the filtered view. */
  async clearPinned(): Promise<void> {
    if (this.pinnedPaths() === null) return;
    await this.loadPhotos();
  }

  /** Load next page and append to existing photos */
  async nextPage(acceptResult: () => boolean = () => true): Promise<void> {
    if (this.pinnedPaths() !== null) return;
    if (!this.hasMore() || this.loading()) return;

    const seq = this._loadSeq;
    const identity = this.auth.identity();
    this.loading.set(true);
    const f = this.filters();
    const nextPage = f.page + 1;
    this.filters.update(current => ({ ...current, page: nextPage }));
    let key = this.filterKey();
    const current = () => seq === this._loadSeq && identity === this.auth.identity() && key === this.filterKey() && acceptResult();
    try {
      if (f.similar_to) {
        const res = await this.fetchSimilarPage(f, (nextPage - 1) * f.per_page);
        if (!current()) return;
        this.photos.update(current => [...current, ...normalisePhotoFlagsAll(res.similar ?? [])]);
        this.total.set(res.total);
        this.hasMore.set(res.has_more);
      } else {
        const params = buildApiParams(this.filters(), this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default);
        const res = await firstValueFrom(this.api.get<PhotosResponse>('/photos', params));
        if (!current()) return;
        this.photos.update(current => [...current, ...normalisePhotoFlagsAll(res.photos)]);
        this.total.set(res.total);
        this.hasMore.set(res.has_more);
        if (res.hidden_summary) {
          this.hiddenSummary.set(res.hidden_summary);
        }
        void this.fetchKeeperHints(res.photos.map(p => p.path));
      }
    } catch {
      if (!current()) return;
      // Revert page increment on error
      this.filters.update(current => ({ ...current, page: f.page }));
      key = this.filterKey();
      this.snackBar.open(this.i18n.t(I18N.gallery.load_error.page_failed), '', { duration: 3000 });
    } finally {
      if (current()) {
        this.loading.set(false);
      }
      if (this.viewRefreshOwed && current()) {
        this.viewRefreshOwed = false;
        void this.refreshPaths(null);
      }
    }
  }

  /** Display-only keys that never affect the API query */
  private static readonly DISPLAY_ONLY_KEYS: ReadonlySet<keyof GalleryFilters> = new Set([
    'hide_details', 'tooltip_mode', 'panel_activation',
  ]);

  private static readonly JOURNAL_SKIPPED_KEYS: ReadonlySet<string> = new Set([
    'page', 'per_page', ...GalleryStore.DISPLAY_ONLY_KEYS,
  ]);

  private static readonly SORT_KEYS: ReadonlySet<string> = new Set(['sort', 'sort_direction']);

  // A threshold edit has no query to reload until semantic search is active.
  private isDisplayOnlyFilter(key: keyof GalleryFilters): boolean {
    return GalleryStore.DISPLAY_ONLY_KEYS.has(key)
      || (key === 'search_threshold' && !this.filters().semanticQuery);
  }

  /** An explicit sidebar edit leaves temporary album review mode before saving. */
  private leaveTemporaryReview(): void {
    if (!this.transientReviewStatus()) return;
    const album = this.currentAlbum();
    if (album) {
      try {
        const saved = JSON.parse(album.smart_filter_json ?? '{}') as Partial<GalleryFilters>;
        this.filters.update(current => ({ ...current, review_status: saved.review_status ?? '',
          sort: saved.sort ?? this.config()?.defaults.sort ?? DEFAULT_FILTERS.sort,
          sort_direction: saved.sort_direction ?? this.config()?.defaults.sort_direction ?? DEFAULT_FILTERS.sort_direction }));
      } catch { /* Existing malformed album handling remains responsible for reporting it. */ }
    }
    this.transientReviewStatus.set(false);
  }

  /** Update a single filter; reload from page 1 only when the query changes. */
  async updateFilter<K extends keyof GalleryFilters>(
    key: K,
    value: GalleryFilters[K],
    transientReview = false,
  ): Promise<void> {
    const isDisplayOnly = this.isDisplayOnlyFilter(key);
    if (transientReview) this.transientReviewStatus.set(true);
    else if (!isDisplayOnly && !GalleryStore.SORT_KEYS.has(key)) this.leaveTemporaryReview();
    const update = { [key]: value } as Partial<GalleryFilters>;
    const gpsPatch: Partial<GalleryFilters> = {};
    const reviewPatch: Partial<GalleryFilters> = {};
    if (key === 'review_status' && value) { reviewPatch.similar_to = ''; reviewPatch.semanticQuery = ''; }
    else if ((key === 'semanticQuery' || key === 'similar_to') && value) reviewPatch.review_status = '';
    if (key === 'review_status' && value === 'undecided') { reviewPatch.sort = 'date_taken'; reviewPatch.sort_direction = 'ASC'; }
    if (key === 'no_gps' && value) {
      gpsPatch.gps_lat = ''; gpsPatch.gps_lng = ''; gpsPatch.gps_radius_km = '';
      gpsPatch.similar_to = ''; gpsPatch.semanticQuery = '';
    } else if (value && ['semanticQuery', 'similar_to', 'gps_lat', 'gps_lng', 'gps_radius_km'].includes(key)) {
      gpsPatch.no_gps = '';
    }
    const extra: Partial<GalleryFilters> = {
      ...gpsPatch,
      ...semanticSortPatch(this.filters(), { ...update, ...gpsPatch, ...reviewPatch }, this.config()?.defaults),
      ...reviewPatch,
      ...exclusiveHidePatch(update),
    };
    // Reload person dropdown when person filter is cleared (was seeded with filtered subset)
    const wasPersonFiltered = !!this.filters().person_id;
    const before = this.filters();
    this.filters.update(current => ({
      ...current, [key]: value, ...extra, ...(isDisplayOnly ? {} : { page: 1 }),
    }));
    this.journalFilters(before, this.filters());
    if ((DISPLAY_OPTION_KEYS as string[]).includes(key as string)) {
      saveDisplayOptionsToStorage(this.filters());
    }
    this.syncUrl();
    if (!isDisplayOnly) {
      this.cancelRangeLoad();
      await this.loadPhotos();
    }
    if (key === 'person_id' && wasPersonFiltered && !value) {
      this.reloadPersonOptions();
    }
  }

  /** Update a range filter; reload is debounced so a slider drag fires one request. */
  updateFilterDebounced<K extends keyof GalleryFilters>(key: K, value: GalleryFilters[K]): void {
    this.leaveTemporaryReview();
    const before = this.filters();
    this.filters.update(current => ({ ...current, [key]: value, page: 1 }));
    this.journalFilters(before, this.filters());
    this.syncUrl();
    this.scheduleRangeLoad();
  }

  /** Records what a user edit changed; `page` and display-only keys (layout, tooltip) are noise, and so is a change of sort alone. */
  private journalFilters(before: GalleryFilters, after: GalleryFilters): void {
    const changed: Record<string, unknown> = {};
    for (const key of Object.keys(after) as (keyof GalleryFilters)[]) {
      if (GalleryStore.JOURNAL_SKIPPED_KEYS.has(key) || before[key] === after[key]) continue;
      changed[key] = after[key];
    }
    if (Object.keys(changed).every(key => GalleryStore.SORT_KEYS.has(key))) return;
    this.journal.recordFilters({ changed });
  }

  private scheduleRangeLoad(): void {
    if (this.rangeLoadTimer) clearTimeout(this.rangeLoadTimer);
    this.rangeLoadTimer = setTimeout(() => {
      this.rangeLoadTimer = null;
      void this.loadPhotos();
    }, 300);
  }

  private cancelRangeLoad(): void {
    if (this.rangeLoadTimer) {
      clearTimeout(this.rangeLoadTimer);
      this.rangeLoadTimer = null;
    }
  }

  /** Update multiple filters; reload only when the query changes. */
  async updateFilters(updates: Partial<GalleryFilters>): Promise<void> {
    const keys = Object.keys(updates) as (keyof GalleryFilters)[];
    const isDisplayOnly = keys.length > 0 && keys.every(key => this.isDisplayOnlyFilter(key));
    if (keys.some(key => !this.isDisplayOnlyFilter(key) && !GalleryStore.SORT_KEYS.has(key))) this.leaveTemporaryReview();
    const gpsPatch: Partial<GalleryFilters> = {};
    const reviewPatch: Partial<GalleryFilters> = {};
    if (updates.review_status) { reviewPatch.similar_to = ''; reviewPatch.semanticQuery = ''; }
    else if (updates.semanticQuery || updates.similar_to) reviewPatch.review_status = '';
    if (updates.review_status === 'undecided') { reviewPatch.sort = 'date_taken'; reviewPatch.sort_direction = 'ASC'; }
    if (updates.no_gps) {
      gpsPatch.gps_lat = ''; gpsPatch.gps_lng = ''; gpsPatch.gps_radius_km = '';
      gpsPatch.similar_to = ''; gpsPatch.semanticQuery = '';
    } else if (updates.semanticQuery || updates.similar_to || updates.gps_lat || updates.gps_lng || updates.gps_radius_km) {
      gpsPatch.no_gps = '';
    }
    const extra: Partial<GalleryFilters> = {
      ...gpsPatch,
      ...semanticSortPatch(this.filters(), { ...updates, ...gpsPatch, ...reviewPatch }, this.config()?.defaults),
      ...reviewPatch,
      ...exclusiveHidePatch(updates),
    };
    const before = this.filters();
    this.filters.update(current => ({ ...current, ...updates, ...extra, ...(isDisplayOnly ? {} : { page: 1 }) }));
    this.journalFilters(before, this.filters());
    if (Object.keys(updates).some(k => (DISPLAY_OPTION_KEYS as string[]).includes(k))) {
      saveDisplayOptionsToStorage(this.filters());
    }
    this.syncUrl();
    if (!isDisplayOnly) {
      this.cancelRangeLoad();
      await this.loadPhotos();
    }
  }

  /** Clear all five hide toggles, stashing their prior state so restoreHidden()
   *  can bring them back. */
  showAllHidden(): void {
    const f = this.filters();
    this.hiddenFiltersStash.set({
      hide_blinks: f.hide_blinks,
      hide_bursts: f.hide_bursts,
      hide_duplicates: f.hide_duplicates,
      hide_brackets: f.hide_brackets,
      hide_panoramas: f.hide_panoramas,
    });
    void this.updateFilters({
      hide_blinks: false,
      hide_bursts: false,
      hide_duplicates: false,
      hide_brackets: false,
      hide_panoramas: false,
    });
  }

  /** Restore the hide toggles stashed by showAllHidden(), if any. */
  restoreHidden(): void {
    const stash = this.hiddenFiltersStash();
    if (!stash) return;
    this.hiddenFiltersStash.set(null);
    void this.updateFilters({ ...stash });
  }

  /** Reset all filters to config defaults */
  async resetFilters(): Promise<void> {
    this.currentAlbum.set(null);
    this.journal.recordFilters({ reset: true });
    const cfg = this.config();
    const defaults = cfg?.defaults;
    this.filters.set({
      ...DEFAULT_FILTERS,
      per_page: cfg?.pagination?.default_per_page ?? 64,
      // Same re-seed loadConfig() does -- otherwise reset drops back to the
      // unseeded '' and the sidebar readout/thumb render as if the gate were 0.
      search_threshold: seededSearchThreshold(cfg?.search_threshold_default),
      sort: defaults?.sort ?? 'aggregate',
      sort_direction: defaults?.sort_direction ?? 'DESC',
      hide_details: defaults?.hide_details ?? true,
      tooltip_mode: defaults?.tooltip_mode ?? 'hover',
      panel_activation: defaults?.panel_activation ?? 'both',
      hide_blinks: defaults?.hide_blinks ?? true,
      hide_bursts: defaults?.hide_bursts ?? true,
      hide_duplicates: defaults?.hide_duplicates ?? true,
      hide_brackets: defaults?.hide_brackets ?? true,
      hide_panoramas: defaults?.hide_panoramas ?? true,
      hide_rejected: defaults?.hide_rejected ?? true,
    });
    this.resetCardWidth();
    // Preserve user's gallery mode preference from localStorage
    if (!localStorage.getItem(GALLERY_MODE_KEY)) {
      this.setGalleryMode(defaults?.gallery_mode ?? 'grid');
    }
    saveDisplayOptionsToStorage(this.filters());
    this.cancelRangeLoad();
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

  setVirtualScroll(enabled: boolean): void {
    this.virtualScroll.set(enabled);
    try { localStorage.setItem('facet_virtual_scroll', enabled ? 'on' : 'off'); } catch { /* ignore */ }
  }

  /** Fetch a filter-option endpoint, giving up after FILTER_OPTIONS_TIMEOUT_MS. */
  private fetchFilterOption<T>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
    const request = params ? this.api.get<T>(path, params) : this.api.get<T>(path);
    return firstValueFrom(request.pipe(timeout(FILTER_OPTIONS_TIMEOUT_MS)));
  }

  /** Load type counts (for the type toggle bar) */
  async loadTypeCounts(): Promise<void> {
    try {
      const res = await this.fetchFilterOption<{types: TypeCount[]}>('/type_counts', { ...this.viewFilterParams() });
      this.types.set(res.types.filter(t => t.id).sort((a, b) => b.count - a.count));
    } catch {
      this.types.set([]);
    }
  }

  /** Load all filter dropdown options in parallel */
  async loadFilterOptions(): Promise<void> {
    const [camerasRes, lensesRes, tagsRes, personsRes, patternsRes, colorsRes, rangesRes] = await Promise.all([
      this.fetchFilterOption<{cameras: [string, number][]}>('/filter_options/cameras').catch(() => ({cameras: []})),
      this.fetchFilterOption<{lenses: [string, number][]}>('/filter_options/lenses').catch(() => ({lenses: []})),
      this.fetchFilterOption<{tags: [string, number][]}>('/filter_options/tags').catch(() => ({tags: []})),
      this.fetchFilterOption<{persons: [number, string | null, number][]}>('/filter_options/persons',
        this.filters().person_id ? { ids: this.filters().person_id } : undefined).catch(() => ({persons: []})),
      this.fetchFilterOption<{patterns: [string, number][]}>('/filter_options/patterns').catch(() => ({patterns: []})),
      this.fetchFilterOption<{temps: [string, number][]; hue_buckets: [string, number][]}>('/filter_options/colors')
        .catch(() => ({temps: [], hue_buckets: []})),
      this.fetchFilterOption<{ranges: Record<string, MetricRange>}>('/filter_options/metric_ranges').catch(() => ({ranges: {}})),
    ]);
    this.cameras.set((camerasRes.cameras ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.lenses.set((lensesRes.lenses ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.tags.set((tagsRes.tags ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.persons.set(
      (personsRes.persons ?? [])
        .map(([id, name, face_count]: [number, string | null, number]) => ({id, name, face_count})),
    );
    this.patterns.set((patternsRes.patterns ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.colorTemps.set((colorsRes.temps ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.hueBuckets.set((colorsRes.hue_buckets ?? []).map(([value, count]: [string, number]) => ({value, count})));
    this.metricRanges.set(rangesRes.ranges ?? {});
  }

  /** Reload person dropdown without filter restriction */
  async reloadPersonOptions(): Promise<void> {
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

  /**
   * Drop deleted photos from local state without a refetch.
   *
   * `POST /api/photo/delete` removes the DB row immediately (decision 5), so
   * by the time its response returns these rows are already gone server-side
   * -- filtering them out here is correct, and the existing bulk-action
   * pattern's `await this.store.loadPhotos()` refetch would be pure added
   * latency for a delete specifically (decision 6 bullet 4).
   */
  removePhotos(paths: Iterable<string>): void {
    const pathSet = new Set(paths);
    if (pathSet.size === 0) return;
    const before = this.photos().length;
    this.photos.update(photos => photos.filter(p => !pathSet.has(p.path)));
    const removed = before - this.photos().length;
    this.total.update(total => Math.max(0, total - removed));
    this.selectedPaths.update(selected => {
      const next = new Set(selected);
      for (const path of pathSet) next.delete(path);
      return next;
    });
    // Under 'view' scope `excludedPaths` is what NARROWS the effective
    // selection away from "everything" (selectionCount = total - excluded.size).
    // Dropping a deleted path out of it WIDENS that selection back by one --
    // which exactly cancels the `total` decrement above for a photo that was
    // excluded, so selectionCount lands correctly whether the deleted photo
    // was selected or excluded.
    this.excludedPaths.update(excluded => {
      const next = new Set(excluded);
      for (const path of pathSet) next.delete(path);
      return next;
    });
  }

  /** Fetch "a better shot exists in this group" hints and merge them in.
   *  Head-gated server-side: returns {} (a no-op) when no keeper head is
   *  trained, so the default gallery pays nothing. Best-effort, fire-and-forget. */
  private async fetchKeeperHints(paths: string[]): Promise<void> {
    if (!paths.length) return;
    const current = this.captureReviewView();
    try {
      const hints = await firstValueFrom(
        this.api.post<Record<string, KeeperHint>>('/photos/keeper_hints', { paths }),
      );
      if (!current()) return;
      for (const [path, hint] of Object.entries(hints)) {
        this.patchPhoto(path, { keeper_hint: hint });
      }
    } catch {
      // Best-effort: leave photos without hints on failure.
    }
  }

  /** Patch many photos at once. */
  private patchPhotos(pathSet: ReadonlySet<string>, partial: Partial<Photo>): void {
    this.photos.update(photos =>
      photos.map(p => pathSet.has(p.path) ? { ...p, ...partial } : p),
    );
  }

  /**
   * Mark the given photos as carrying (or no longer carrying) a pending
   * panorama correction.
   *
   * Kept out of `patchPhotos`' flag snapshot machinery: a correction is not a
   * rating, it is undone by dropping it server-side, and the tile badge only
   * needs the value the server already accepted.
   */
  patchSequenceOverride(paths: string[], value: string | null): void {
    // A correction written now cannot have been applied yet -- the detector is a
    // batch pass -- so the pending flag moves with the value it qualifies.
    this.patchPhotos(new Set(paths), {
      sequence_override: value,
      sequence_override_pending: value ? 1 : null,
    });
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
          is_kept: !!p.is_kept,
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
    this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
  }

  /** Async decision completions may refresh only the view they started in. */
  captureReviewView(): () => boolean {
    const seq = this._loadSeq;
    const identity = this.auth.identity();
    const key = this.filterKey();
    return () => seq === this._loadSeq && identity === this.auth.identity() && key === this.filterKey();
  }

  /** Set star rating for a photo (0 = clear). Optimistic with revert on error. */
  async setRating(photoPath: string, rating: number): Promise<void> {
    const isOrigin = this.captureReviewView();
    const snap = this.snapshotFlags([photoPath]);
    this.patchPhoto(photoPath, { star_rating: rating || null });
    try {
      await firstValueFrom(this.api.post('/photo/set_rating', { photo_path: photoPath, rating }));
      this.journal.record('rating', [photoPath], rating);
      if (isOrigin()) await this.refreshReviewResults(true);
    } catch {
      if (isOrigin()) this.revertSnapshot(snap);
      this.notifyActionFailed();
    }
  }

  /**
   * Paths with an in-flight toggleFavorite/toggleRejected call. Shared between
   * both methods (not just per-method) because they mutate overlapping fields
   * (rejecting clears favorite and vice versa): a reject fired while a favorite
   * call for the same photo is still pending is just as much a race as a second
   * favorite click. A second call for a path already in flight is dropped
   * rather than queued -- the in-flight call's own response reconciliation
   * already brings local state to server truth, so queuing would only replay
   * a now-stale intent.
   */
  private readonly toggleInFlight = new Set<string>();

  /** Toggle favorite flag for a photo. Optimistic, reconciled with server truth. */
  async toggleFavorite(photoPath: string): Promise<void> {
    const isOrigin = this.captureReviewView();
    if (this.toggleInFlight.has(photoPath)) return;
    this.toggleInFlight.add(photoPath);
    try {
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
        if (!isOrigin()) { void this.loadReviewProgress(); return; }
        this.patchPhoto(photoPath, {
          is_favorite: res.is_favorite,
          is_rejected: res.is_favorite ? false : prev.is_rejected,
        });
        this.journal.record('favorite', [photoPath], res.is_favorite);
        if (isOrigin()) await this.refreshReviewResults(this.filters().favorites_only);
      } catch {
        if (isOrigin()) this.revertSnapshot(snap);
        this.notifyActionFailed();
      }
    } finally {
      this.toggleInFlight.delete(photoPath);
    }
  }

  /** Toggle rejected flag for a photo. Optimistic, reconciled with server truth. */
  async toggleRejected(photoPath: string): Promise<void> {
    const isOrigin = this.captureReviewView();
    if (this.toggleInFlight.has(photoPath)) return;
    this.toggleInFlight.add(photoPath);
    try {
      const snap = this.snapshotFlags([photoPath]);
      const prev = snap.get(photoPath);
      if (!prev) return;
      const next = !prev.is_rejected;
      this.patchPhoto(photoPath, {
        is_rejected: next,
        is_kept: next ? false : prev.is_kept,
        is_favorite: next ? false : prev.is_favorite,
        star_rating: next ? null : prev.star_rating,
      });
      try {
        const res = await firstValueFrom(
          this.api.post<{ is_rejected: boolean; star_rating: number | null }>('/photo/toggle_rejected', { photo_path: photoPath }),
        );
        if (!isOrigin()) { void this.loadReviewProgress(); return; }
        this.patchPhoto(photoPath, {
          is_rejected: res.is_rejected,
          is_kept: res.is_rejected ? false : prev.is_kept,
          is_favorite: res.is_rejected ? false : prev.is_favorite,
          star_rating: res.star_rating === null ? prev.star_rating : res.star_rating,
        });
        this.journal.record('reject', [photoPath], res.is_rejected);
        if (isOrigin()) await this.refreshReviewResults(this.filters().review_status === 'rejected');
      } catch {
        if (isOrigin()) this.revertSnapshot(snap);
        this.notifyActionFailed();
      }
    } finally {
      this.toggleInFlight.delete(photoPath);
    }
  }

  /**
   * The wire shapes naming the photos a batch mutation acts on — one per
   * request, in the order they must be sent.
   *
   * Exactly one of the two forms per request, which is also what the server
   * enforces: `photo_paths` for a path selection, or the filter the grid itself
   * was fetched with plus the unticked photos, from which the server derives
   * the rows — no path list on the wire, and no cap.
   *
   * A path selection is split across as many requests as it takes, because the
   * two caps do not meet: the server binds `BatchPhotoRequest.photo_paths` to
   * BATCH_PATHS_PER_REQUEST entries (`Field(default=None, max_length=1000)`)
   * while "Keep top N%" hands the client up to `_SELECT_BOTTOM_MAX` = 5000 of
   * them to act on. One POST of the whole list simply 422s.
   */
  private batchBodies(paths: string[], useSelectionScope = true): Record<string, unknown>[] {
    const filters = useSelectionScope && this.viewScopeSelected() ? this.filterPayload() : null;
    if (filters) return [{ filters, exclude: [...this.excludedPaths()] }];
    return chunkPhotoPaths(paths).map(chunk => ({ photo_paths: chunk }));
  }

  /**
   * Run one batch mutation: patch the loaded photos optimistically, post, and
   * report what it touched.
   *
   * The optimistic patch and the snapshot only ever cover LOADED photos — the
   * others are not on screen to patch and have no state to remember. That gap
   * is why `BatchResult` carries `targeted` as well: a caller offering undo has
   * to know the snapshot is partial, rather than infer coverage from its size.
   *
   * A path selection larger than the server's cap goes out as several requests
   * (see `batchBodies`), so a failure can land with earlier chunks already
   * written. Those rows are the server's truth now: only the photos whose own
   * request never landed are reverted, and the user is told how many did
   * change rather than shown a blanket "action failed" over a half-applied
   * write.
   */
  private async runBatch(
    paths: string[],
    endpoint: string,
    patch: Partial<Photo>,
    extraBody: Record<string, unknown> = {},
    useSelectionScope = true,
  ): Promise<BatchResult | null> {
    const originSeq = this._loadSeq;
    const originIdentity = this.auth.identity();
    const originKey = this.filterKey();
    const current = () => originSeq === this._loadSeq && originIdentity === this.auth.identity() && originKey === this.filterKey();
    const viewScoped = useSelectionScope && this.viewScopeSelected();
    const targeted = viewScoped ? this.selectionCount() : paths.length;
    const loaded = viewScoped ? this.selectedLoadedPaths() : paths;
    const snapshot = this.snapshotFlags(loaded);
    this.patchPhotos(new Set(loaded), patch);
    const persisted = new Set<string>();
    let count = 0;
    for (const body of this.batchBodies(paths, useSelectionScope)) {
      const chunk = body['photo_paths'] as string[] | undefined;
      try {
        const res = await firstValueFrom(
          this.api.post<{ count?: number }>(endpoint, { ...body, ...extraBody }),
        );
        count += res?.count ?? chunk?.length ?? targeted;
        chunk?.forEach(p => persisted.add(p));
      } catch {
        if (current()) this.revertSnapshot(new Map([...snapshot].filter(([p]) => !persisted.has(p))));
        if (count > 0) {
          this.snackBar.open(
            this.i18n.t(I18N.gallery.selection.batch_partial, { count }), '', { duration: 5000 },
          );
        } else {
          this.notifyActionFailed();
        }
        if (count > 0 && current()) await this.refreshReviewResults(endpoint === '/photos/batch_rating'
          || (endpoint === '/photos/batch_reject' && this.filters().review_status === 'rejected'));
        return null;
      }
    }
    const kind = BATCH_ACTIVITY[endpoint];
    if (kind) this.journal.record(kind.kind, paths, kind.value(extraBody));
    if (current()) await this.refreshReviewResults(endpoint === '/photos/batch_rating'
      || (endpoint === '/photos/batch_reject' && this.filters().review_status === 'rejected'));
    else void this.loadReviewProgress();
    return { snapshot, targeted, count };
  }

  private readonly reviewedPhotos = new Map<string, Photo>();
  private reviewedPhotosIdentity: string | undefined;

  private clearForeignReviewedPhotos(): void {
    const identity = this.auth.identity();
    if (identity !== this.reviewedPhotosIdentity) {
      this.reviewedPhotos.clear();
      this.reviewedPhotosIdentity = identity;
    }
  }

  /** Repair shifted offsets with one tail-page request; Undo can restore earlier rows. */
  async refreshReviewResults(rebuild = false): Promise<void> {
    this.clearForeignReviewedPhotos();
    const f = this.filters();
    const identity = this.auth.identity();
    // Pagination changes during a rebuild, but the query and principal must not.
    const scope = () => this.filterKey({ ...this.filters(), page: 1 });
    const key = scope();
    let seq = this._loadSeq;
    const current = () => seq === this._loadSeq && identity === this.auth.identity() && key === scope() && this.pinnedPaths() === null;
    void this.loadReviewProgress();
    if (!f.review_status || this.pinnedPaths() !== null) return;
    const previous = this.photos();
    if (rebuild) {
      const pages = Math.max(1, Math.ceil(previous.length / f.per_page));
      const loading = this.loadPhotos(current);
      seq = this._loadSeq;
      await loading;
      if (!current()) return;
      for (let page = 1; page < pages && this.hasMore() && current(); page++) await this.nextPage(current);
      if (!current()) return;
    } else {
      const retained = previous.filter(photo => f.review_status === 'kept' ? !!photo.is_kept
        : f.review_status === 'rejected' ? !!photo.is_rejected : !photo.is_kept && !photo.is_rejected);
      const page = Math.max(1, Math.ceil(retained.length / f.per_page));
      const offset = (page - 1) * f.per_page;
      this.resetViewScope();
      seq = ++this._loadSeq;
      this.loadError.set(false);
      this.loadErrorKey.set(undefined);
      this.loading.set(true);
      try {
        const params = buildApiParams({ ...f, page }, this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default);
        const res = await firstValueFrom(this.api.get<PhotosResponse>('/photos', params));
        if (!current()) return;
        this.photos.set([...retained.slice(0, offset), ...normalisePhotoFlagsAll(res.photos)]);
        this.filters.update(current => ({ ...current, page }));
        this.total.set(res.total);
        this.hasMore.set(res.has_more);
        this.hiddenSummary.set(res.hidden_summary ?? { total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });
        void this.fetchKeeperHints(res.photos.map(photo => photo.path));
      } catch {
        if (!current()) return;
        this.loadError.set(true);
        return;
      } finally {
        if (current()) this.loading.set(false);
      }
    }
    if (!current()) return;
    const currentPaths = new Set(this.photos().map(photo => photo.path));
    for (const photo of previous) {
      if (currentPaths.has(photo.path)) continue;
      // Reinsert to retain the latest removed photos when the cache is capped.
      this.reviewedPhotos.delete(photo.path);
      this.reviewedPhotos.set(photo.path, photo);
    }
    while (this.reviewedPhotos.size > 1000) this.reviewedPhotos.delete(this.reviewedPhotos.keys().next().value!);
    this.syncUrl();
  }

  async batchReview(paths: string[], decision: 'kept' | 'undecided', useSelectionScope = true): Promise<BatchResult | null> {
    return this.runBatch(paths, '/photos/batch_review', { is_kept: decision === 'kept', is_rejected: false }, { decision }, useSelectionScope);
  }

  /**
   * Batch favorite multiple photos. Optimistic with revert on error.
   * Returns what the action touched for undo, or null on failure.
   */
  async batchFavorite(paths: string[]): Promise<BatchResult | null> {
    return this.runBatch(paths, '/photos/batch_favorite', { is_favorite: true, is_rejected: false });
  }

  /**
   * Batch reject multiple photos. Optimistic with revert on error.
   * Returns what the action touched for undo, or null on failure.
   */
  async batchReject(paths: string[]): Promise<BatchResult | null> {
    return this.runBatch(
      paths, '/photos/batch_reject', { is_rejected: true, is_kept: false, is_favorite: false, star_rating: null },
    );
  }

  /**
   * Select the bottom (100 - keepPercent)% of the CURRENT filtered view, ranked
   * by the current sort on the server, so the user can review/reject them
   * ("Keep top N%"). Replaces the current selection with the returned paths.
   * Read-only — mutates no photo here; the reject is the existing batch action.
   * Returns the server summary (counts + truncated flag), or null on failure.
   */
  async selectBottomPercent(
    keepPercent: number,
  ): Promise<{ total: number; keep: number; cut: number; truncated: boolean; paths: string[] } | null> {
    const f = this.filters();
    if (!this.canScopeSelectionToView()) {
      this.notifyActionFailed();
      return null;
    }
    const params = buildApiParams(f, this.currentAlbum()?.is_smart ?? false, this.config()?.search_threshold_default);
    try {
      const res = await firstValueFrom(
        this.api.get<{ total: number; keep: number; cut: number; truncated: boolean; paths: string[] }>(
          '/photos/select_bottom_percent', { ...params, keep_percent: keepPercent },
        ),
      );
      this.restoreSelection(res.paths);
      return res;
    } catch {
      this.notifyActionFailed();
      return null;
    }
  }

  /**
   * Batch set rating for multiple photos. Optimistic with revert on error.
   * Returns what the action touched for undo, or null on failure.
   */
  async batchRating(paths: string[], rating: number): Promise<BatchResult | null> {
    return this.runBatch(paths, '/photos/batch_rating', { star_rating: rating || null }, { rating });
  }

  /** Run up to `limit` path-keyed async tasks concurrently. Returns the paths whose task rejected. */
  private async runChunked(tasks: { path: string; run: () => Promise<unknown> }[], limit = 10): Promise<Set<string>> {
    const failed = new Set<string>();
    for (let i = 0; i < tasks.length; i += limit) {
      const batch = tasks.slice(i, i + limit);
      const results = await Promise.allSettled(batch.map(t => t.run()));
      results.forEach((r, idx) => { if (r.status === 'rejected') failed.add(batch[idx].path); });
    }
    return failed;
  }

  /**
   * Restore photos to a previously captured flag snapshot via inverse API
   * calls, then patch local state. Powers undo of batch operations.
   *
   * Each API call's outcome is tracked per photo path: only paths whose calls
   * all succeeded are reverted locally to the snapshot's target state. A path
   * with any failed call keeps its current (unreverted) local state, since we
   * cannot know how much of its restore actually landed server-side, and the
   * user is notified rather than left with a UI that silently disagrees with
   * the server.
   */
  async restoreSnapshot(snapshot: Map<string, PhotoFlagSnapshot>): Promise<void> {
    const isOrigin = this.captureReviewView();
    // Reject has one meaning across every public write, including Undo.
    const snap = new Map([...snapshot].map(([path, flags]) => [path, flags.is_rejected
      ? { ...flags, is_kept: false, is_favorite: false, star_rating: null }
      : flags]));
    this.clearForeignReviewedPhotos();
    const current = new Map([...this.reviewedPhotos, ...this.photos().map(p => [p.path, p] as const)]);
    const toKeep: string[] = [];
    const toReset: string[] = [];
    const toUnreject: string[] = [];
    const toReject: string[] = [];
    const toFavorite: string[] = [];
    const toUnfavorite: string[] = [];
    const ratingGroups = new Map<number, string[]>();
    const failed = new Set<string>();

    for (const [path, want] of snap) {
      const now = current.get(path);
      if (!now) { failed.add(path); continue; }
      if (!want.is_rejected && !!want.is_kept !== !!now.is_kept) {
        (want.is_kept ? toKeep : toReset).push(path);
      }
      if (!want.is_rejected && now.is_rejected) toUnreject.push(path);
      if (want.is_rejected) { toReject.push(path); continue; }
      if (want.is_favorite && !now.is_favorite) toFavorite.push(path);
      if (!want.is_favorite && now.is_favorite) toUnfavorite.push(path);
      const wantRating = want.star_rating ?? 0;
      if (wantRating !== (now.star_rating ?? 0)) {
        const group = ratingGroups.get(wantRating) ?? [];
        group.push(path);
        ratingGroups.set(wantRating, group);
      }
    }

    // Chunked to the server's `photo_paths` cap like every other batch write:
    // a chunk that fails marks only its own paths failed, so the rest of the
    // restore still lands and only what genuinely did not revert is reported.
    const runBatch = async (
      endpoint: string, paths: string[], extra: Record<string, unknown> = {},
    ): Promise<void> => {
      if (!paths.length) return;
      for (const chunk of chunkPhotoPaths(paths)) {
        try {
          await firstValueFrom(this.api.post(endpoint, { photo_paths: chunk, ...extra }));
        } catch {
          chunk.forEach(p => failed.add(p));
        }
      }
    };

    // Order matters: clear rejected first (rejecting wipes rating+favorite
    // server-side), then re-apply rejected/favorite/rating states
    (await this.runChunked(toUnreject.map(path => ({
      path,
      run: () => firstValueFrom(this.api.post('/photo/toggle_rejected', { photo_path: path })),
    })))).forEach(p => failed.add(p));
    await runBatch('/photos/batch_review', toKeep, { decision: 'kept' });
    await runBatch('/photos/batch_review', toReset, { decision: 'undecided' });
    await runBatch('/photos/batch_favorite', toFavorite);
    (await this.runChunked(toUnfavorite.map(path => ({
      path,
      run: () => firstValueFrom(this.api.post('/photo/toggle_favorite', { photo_path: path })),
    })))).forEach(p => failed.add(p));
    for (const [rating, paths] of ratingGroups) {
      await runBatch('/photos/batch_rating', paths, { rating });
    }
    await runBatch('/photos/batch_review', toReject, { decision: 'rejected' });

    const succeeded = new Map([...snap].filter(([path]) => !failed.has(path)));
    if (succeeded.size > 0 && isOrigin()) this.revertSnapshot(succeeded);
    if (failed.size > 0) this.notifyActionFailed();
    if (isOrigin()) await this.refreshReviewResults(true);
  }

  /** Unassign a person from a photo */
  async unassignPerson(photoPath: string, personId: number): Promise<void> {
    try {
      await firstValueFrom(this.api.post('/photo/unassign_person', { photo_path: photoPath, person_id: personId }));
      this.journal.record('person', [photoPath], { action: 'unassign', person_id: personId });
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
      this.journal.record('person', photoPath ? [photoPath] : [], {
        action: 'create', person_id: res.id, name: activityName(trimmed), count: faceIds.length,
      });
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

  /** Assign a single face to a person. Returns true on success, false on failure. */
  async assignFace(faceId: number, personId: number, photoPath: string, personName: string): Promise<boolean> {
    try {
      await firstValueFrom(this.api.post(`/face/${faceId}/assign`, { person_id: personId }));
      this.journal.record('person', [photoPath], { action: 'assign', person_id: personId });
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
      return true;
    } catch {
      return false;
    }
  }

  private galleryQueryParams(): Record<string, unknown> {
    return {
      ...buildSyncParams(this.filters(), this.config()?.defaults, this.config()?.search_threshold_default),
      ...(this.transientReviewStatus() ? { review_queue: '1' } : {}),
    };
  }

  /** Sync current filters to URL query params */
  private syncUrl(): void {
    this.router.navigate([], {
      queryParams: this.galleryQueryParams(),
      replaceUrl: true,
    });
  }

  /** Fetch a page of similar photos from the API */
  private fetchSimilarPage(f: GalleryFilters, offset: number): Promise<SimilarPage> {
    const minSim = (parseInt(f.min_similarity || '70', 10) / 100).toString();
    return firstValueFrom(
      this.api.get<SimilarPage>(
        `/similar_photos/${encodeURIComponent(f.similar_to)}`,
        { limit: f.per_page, offset, min_similarity: minSim, mode: f.similarity_mode || 'visual', full: 1 },
      ),
    );
  }

}
