import type { Mock } from 'vitest';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, ActivatedRoute, NavigationStart, Event as RouterEvent, Navigation } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, of, throwError } from 'rxjs';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { take } from 'rxjs/operators';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { Album, AlbumService } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { AssistantChangesService, AssistantChangeBatch } from '../../core/agent/assistant-changes.service';
import { I18N } from '../../core/i18n/keys';
import {
  GalleryStore,
  DEFAULT_FILTERS,
  FILTER_OPTIONS_TIMEOUT_MS,
  PhotosResponse,
  ViewerConfig,
  TypeCount,
} from './gallery.store';
import { Photo } from '../../shared/models/photo.model';
import { makePhoto } from '../../../testing/photo.fixture';
import { applyQueryParams, buildSyncParams } from './gallery-filters.util';

function makePhotosResponse(overrides: Partial<PhotosResponse> = {}): PhotosResponse {
  return {
    photos: [makePhoto()],
    total: 1,
    page: 1,
    per_page: 64,
    total_pages: 1,
    has_more: false,
    ...overrides,
  };
}

function makeConfig(overrides: Partial<ViewerConfig> = {}): ViewerConfig {
  return {
    pagination: { default_per_page: 64 },
    defaults: {
      type: '',
      sort: 'aggregate',
      sort_direction: 'DESC',
      hide_blinks: true,
      hide_bursts: true,
      hide_duplicates: true,
      hide_brackets: true,
      hide_panoramas: true,
      hide_details: true,
      tooltip_mode: "hover",
      panel_activation: "both",
      hide_rejected: true,
      gallery_mode: 'mosaic',
    },
    display: { tags_per_photo: 5, card_width_px: 300, image_width_px: 640 },
    sort_options_grouped: null,
    features: {
      show_similar_button: false,
      show_merge_suggestions: false,
      show_rating_controls: false,
      show_semantic_search: false,
      show_albums: false,
      show_critique: false,
      show_vlm_critique: false,
      show_memories: false,
      show_captions: false,
      show_timeline: false,
      show_map: false,
      show_capsules: false,
      show_folders: false,
    },
    quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
    search_threshold_default: 0.15,
    ...overrides,
  };
}

describe('GalleryStore', () => {
  let store: GalleryStore;
  let apiGet: Mock;
  let apiPost: Mock;
  let snackOpen: Mock;
  let routerNavigate: Mock;
  let routerEvents: Subject<RouterEvent>;
  let queryParams: Record<string, string>;
  let assistantBatches: Subject<AssistantChangeBatch>;
  const authIdentity = signal('0|');

  beforeEach(() => {
    authIdentity.set('0|');
    apiGet = vi.fn();
    apiPost = vi.fn(() => of({}));
    snackOpen = vi.fn();
    routerNavigate = vi.fn();
    routerEvents = new Subject<RouterEvent>();
    queryParams = {};
    assistantBatches = new Subject<AssistantChangeBatch>();

    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: apiGet, post: apiPost } },
        { provide: Router, useValue: { navigate: routerNavigate, events: routerEvents, currentNavigation: () => null } },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParams } },
        },
        { provide: AuthService, useValue: { identity: authIdentity, isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: AssistantChangesService, useValue: { batch$: assistantBatches.asObservable() } },
      ],
    });

    store = TestBed.inject(GalleryStore);
  });

  describe('review refresh ownership', () => {
    it('does not use another principal removed-photo cache for Undo', async () => {
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      store.photos.set([makePhoto({ path: '/alice', is_kept: true })]);
      apiGet.mockReturnValue(of(makePhotosResponse({ photos: [] })));
      await store.refreshReviewResults();
      authIdentity.set('bob');
      apiPost.mockClear();
      await store.restoreSnapshot(new Map([['/alice', { is_kept: false, is_rejected: false, is_favorite: false, star_rating: null }]]));
      expect(apiPost.mock.calls.some(([url]) => url === '/photos/batch_review')).toBe(false);
      expect(store.photos()).toEqual([]);
    });
    it.each([false, true])('discards old-principal refill/rebuild responses (rebuild=%s)', async rebuild => {
      const pending = new Subject<PhotosResponse>();
      apiGet.mockImplementation((url: string) => url === '/photos' ? pending : of({}));
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      store.photos.set([makePhoto({ path: '/alice', is_kept: true })]);
      const task = store.refreshReviewResults(rebuild);
      authIdentity.set('bob'); // No load or sequence change.
      store.photos.set([makePhoto({ path: '/bob' })]);
      pending.next(makePhotosResponse({ photos: [makePhoto({ path: '/alice-private' })] }));
      await task;
      expect(store.photos().map(p => p.path)).toEqual(['/bob']);
      expect(routerNavigate).not.toHaveBeenCalled();
    });
    it.each(['identity', 'scope'])('discards a rebuilt tail when %s changes without a new load', async change => {
      const pending = new Subject<PhotosResponse>();
      apiGet.mockImplementation((url: string, params: { page: number }) => url !== '/photos' ? of({}) : params.page === 1
        ? of(makePhotosResponse({ photos: [makePhoto({ path: '/first' })], has_more: true })) : pending);
      store.filters.update(f => ({ ...f, review_status: 'undecided', per_page: 1 }));
      store.photos.set([makePhoto({ path: '/first' }), makePhoto({ path: '/second' })]);
      const task = store.refreshReviewResults(true);
      await vi.waitFor(() => expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ page: 2 })));
      if (change === 'identity') authIdentity.set('bob');
      else store.filters.update(f => ({ ...f, path_prefix: '/new' }));
      store.photos.set([makePhoto({ path: '/current' })]);
      pending.next(makePhotosResponse({ photos: [makePhoto({ path: '/stale-tail' })] }));
      await task;
      expect(store.photos().map(p => p.path)).toEqual(['/current']);
      expect(routerNavigate).not.toHaveBeenCalled();
    });
  });

  describe('review progress and browser resume', () => {
    beforeEach(() => localStorage.removeItem('facet_review_queues_v1'));

    it('uses complete scoped counts and refreshes them after decisions outside a review tab', async () => {
      apiGet.mockImplementation((url: string) => of(url === '/photos/review_progress'
        ? { total: 120, undecided: 90, kept: 20, rejected: 10 } : makePhotosResponse()));
      await store.loadPhotos();
      await store.loadReviewProgress();
      expect(store.reviewProgress()).toEqual({ total: 120, undecided: 90, kept: 20, rejected: 10 });
      expect(store.reviewPercent()).toBe(25);
      await store.refreshReviewResults();
      expect(apiGet.mock.calls.filter(([url]) => url === '/photos/review_progress').length).toBeGreaterThan(1);
    });

    it('restores the remembered folder filters and first remaining undecided after changing filters', async () => {
      apiGet.mockImplementation((url: string) => of(url === '/photos/review_progress'
        ? { total: 3, undecided: 1, kept: 1, rejected: 1 } : makePhotosResponse({ photos: [makePhoto({ path: '/trip/remaining.jpg' })] })));
      await store.updateFilters({ path_prefix: '/trip/', camera: 'TripCam', review_status: 'undecided' });
      await store.updateFilters({ path_prefix: '/other/', camera: '', review_status: '' });
      expect(await store.continueReview()).toBe('/trip/remaining.jpg');
      expect(store.filters()).toMatchObject({ path_prefix: '/trip/', camera: 'TripCam', review_status: 'undecided', page: 1 });
    });

    it('ignores a late progress response after the scope changes', async () => {
      const old = new Subject<unknown>();
      apiGet.mockImplementation((url: string) => url === '/photos/review_progress' ? old : of(makePhotosResponse()));
      const first = store.loadReviewProgress();
      store.filters.update(f => ({ ...f, path_prefix: '/new/' }));
      apiGet.mockImplementation(() => of({ total: 0, undecided: 0, kept: 0, rejected: 0 }));
      await store.loadReviewProgress();
      old.next({ total: 10, undecided: 1, kept: 9, rejected: 0 });
      old.complete();
      await first;
      expect(store.reviewProgress()?.total).toBe(0);
      expect(store.reviewPercent()).toBe(0);
    });

    it('does not clear a new whole-view selection when an old review write finishes', async () => {
      const pending = new Subject<{ count: number }>();
      apiPost.mockReturnValue(pending);
      apiGet.mockReturnValue(of(makePhotosResponse()));
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      store.photos.set([makePhoto({ path: '/old.jpg' })]);
      const writing = store.batchReview(['/old.jpg'], 'kept');
      await store.updateFilters({ path_prefix: '/new/' });
      store.selectWholeView();
      pending.next({ count: 1 });
      pending.complete();
      await writing;
      expect(store.viewScopeSelected()).toBe(true);
    });

    it('shows 100% only when no undecided photos remain', () => {
      store.reviewProgress.set({ total: 1000, undecided: 1, kept: 999, rejected: 0 });
      expect(store.reviewPercent()).toBe(99);
      store.reviewProgress.set({ total: 1000, undecided: 0, kept: 999, rejected: 1 });
      expect(store.reviewPercent()).toBe(100);
    });

    it('retains aggregate results when only pagination advances', async () => {
      const pending = new Subject<{ total: number; undecided: number; kept: number; rejected: number }>();
      apiGet.mockReturnValue(pending);
      const counting = store.loadReviewProgress();
      store.filters.update(f => ({ ...f, page: 2 }));
      pending.next({ total: 200, undecided: 100, kept: 50, rejected: 50 });
      pending.complete();
      await counting;
      expect(store.reviewProgress()?.total).toBe(200);
    });

    it('does not clear a new whole-view selection when an old single reject finishes', async () => {
      const pending = new Subject<{ is_rejected: boolean; star_rating: number | null }>();
      apiPost.mockReturnValue(pending);
      apiGet.mockReturnValue(of(makePhotosResponse()));
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      store.photos.set([makePhoto({ path: '/old.jpg' })]);
      const writing = store.toggleRejected('/old.jpg');
      await store.updateFilters({ path_prefix: '/newer/' });
      store.selectWholeView();
      pending.next({ is_rejected: true, star_rating: null });
      pending.complete();
      await writing;
      expect(store.viewScopeSelected()).toBe(true);
    });

    it('hides the previous identity bookmark immediately on account changes', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      authIdentity.set('1|alice');
      await store.updateFilters({ path_prefix: '/alice/', review_status: 'undecided' });
      expect(store.reviewBookmark()?.filters.path_prefix).toBe('/alice/');
      authIdentity.set('1|bob');
      expect(store.reviewBookmark()).toBeNull();
      authIdentity.set('1|alice');
      expect(store.reviewBookmark()?.filters.path_prefix).toBe('/alice/');
    });

    it('does not apply a photo response or bookmark from a previous identity', async () => {
      const pending = new Subject<PhotosResponse>();
      authIdentity.set('1|alice');
      store.filters.update(f => ({ ...f, review_status: 'undecided', path_prefix: '/alice/' }));
      apiGet.mockImplementation((url: string) => url === '/photos' ? pending : of({ total: 0, undecided: 0, kept: 0, rejected: 0 }));
      const loading = store.loadPhotos();
      authIdentity.set('1|bob');
      pending.next(makePhotosResponse({ photos: [makePhoto({ path: '/alice/private.jpg' })] }));
      pending.complete();
      await loading;
      expect(store.photos()).toEqual([]);
      expect(store.reviewBookmark()).toBeNull();
    });

    it('keeps the current view when a remembered album was deleted', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilters({ album_id: '123', review_status: 'undecided' });
      await store.updateFilters({ album_id: '', review_status: '', path_prefix: '/current/' });
      const albums = TestBed.inject(AlbumService);
      albums.get = vi.fn(() => throwError(() => new HttpErrorResponse({ status: 404 })));
      expect(await store.continueReview()).toBeNull();
      expect(store.filters().path_prefix).toBe('/current/');
      expect(snackOpen).toHaveBeenCalled();
    });

    it('ignores a resume album lookup if the user navigates while it is pending', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilters({ album_id: '123', review_status: 'undecided' });
      const albumResult = new Subject<Album>();
      TestBed.inject(AlbumService).get = vi.fn(() => albumResult);
      const resuming = store.continueReview();
      await store.updateFilters({ album_id: '', review_status: '', path_prefix: '/newer/' });
      albumResult.next({ id: 123 } as Album);
      albumResult.complete();
      expect(await resuming).toBeNull();
      expect(store.filters().path_prefix).toBe('/newer/');
    });

    it('cancels an album resume on real navigation away without a filter change', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilters({ album_id: '123', camera: 'OldAlbum', review_status: 'undecided' });
      await store.updateFilters({ album_id: '', camera: 'Current', review_status: '' });
      const album = new Subject<Album>();
      TestBed.inject(AlbumService).get = vi.fn(() => album);
      routerNavigate.mockClear();
      const resuming = store.continueReview();
      routerEvents.next(new NavigationStart(7, '/photo?path=/other.jpg'));
      album.next({ id: 123, is_smart: true, smart_filter_json: '{}' } as Album);
      album.complete();
      expect(await resuming).toBeNull();
      expect(store.filters().camera).toBe('Current');
      expect(routerNavigate).not.toHaveBeenCalled();
    });

    it('ignores a resumed photo response after navigation away without a filter change', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilters({ path_prefix: '/remembered/', review_status: 'undecided' });
      await store.updateFilters({ path_prefix: '/current/', review_status: '' });
      const photos = new Subject<PhotosResponse>();
      apiGet.mockImplementation((url: string) => url === '/photos' ? photos : of({ total: 1, undecided: 1, kept: 0, rejected: 0 }));
      const resuming = store.continueReview();
      await Promise.resolve();
      await Promise.resolve();
      routerEvents.next(new NavigationStart(8, '/stats'));
      photos.next(makePhotosResponse({ photos: [makePhoto({ path: '/remembered/late.jpg' })] }));
      photos.complete();
      expect(await resuming).toBeNull();
      expect(store.photos()).toEqual([]);
    });

    it('allows its own marked query synchronization without cancelling resume', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilters({ path_prefix: '/remembered/', review_status: 'undecided' });
      const router = TestBed.inject(Router);
      const navigation = vi.spyOn(router, 'currentNavigation');
      routerNavigate.mockImplementation((_commands, extras) => {
        navigation.mockReturnValue({ extras } as Navigation);
        routerEvents.next(new NavigationStart(9, '/?review_queue=1'));
        return Promise.resolve(true);
      });
      expect(await store.continueReview()).toBe('/test.jpg');
    });

    it.each(['kept', 'rejected'])('declines an album queue whose current saved criterion changed to %s', async status => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilters({ album_id: '123', camera: 'Camera A', review_status: 'undecided' });
      await store.updateFilters({ album_id: '', camera: 'Current', review_status: '' });
      const before = store.filters();
      TestBed.inject(AlbumService).get = vi.fn(() => of({ id: 123, is_smart: true, smart_filter_json: JSON.stringify({ camera: 'Camera B', review_status: status }) } as Album));
      apiGet.mockClear();
      expect(await store.continueReview()).toBeNull();
      expect(store.filters()).toBe(before);
      expect(apiGet.mock.calls.filter(([url]) => url === '/photos')).toHaveLength(0);
      expect(snackOpen).toHaveBeenCalled();
    });

    it('tolerates malformed browser storage', () => {
      localStorage.setItem('facet_review_queues_v1', '{broken');
      expect(store.reviewBookmark()).toBeNull();
    });
  });

  describe('initial state', () => {
    it('should have DEFAULT_FILTERS as initial filters', () => {
      expect(store.filters()).toEqual(DEFAULT_FILTERS);
    });

    it('should have empty photos array', () => {
      expect(store.photos()).toEqual([]);
    });

    it('should have total 0', () => {
      expect(store.total()).toBe(0);
    });

    it('should have loading false', () => {
      expect(store.loading()).toBe(false);
    });

    it('should have hasMore false', () => {
      expect(store.hasMore()).toBe(false);
    });

    it('should have config null', () => {
      expect(store.config()).toBeNull();
    });
  });

  describe('activeFilterCount', () => {
    it('should return 0 with default filters', () => {
      expect(store.activeFilterCount()).toBe(0);
    });

    it('should count camera filter', () => {
      store.filters.set({ ...DEFAULT_FILTERS, camera: 'Canon EOS R5' });
      expect(store.activeFilterCount()).toBe(1);
    });

    it('should count multiple active filters', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        camera: 'Canon',
        lens: '50mm',
        tag: 'landscape',
        person_id: '5',
        min_score: '7',
        search: 'sunset',
      });
      expect(store.activeFilterCount()).toBe(6);
    });

    it('should count all 13 possible filter fields', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        camera: 'Canon',
        lens: '50mm',
        tag: 'landscape',
        person_id: '5',
        min_score: '7',
        max_score: '10',
        min_aesthetic: '6',
        max_aesthetic: '9',
        min_face_quality: '5',
        max_face_quality: '10',
        min_composition: '4',
        max_composition: '10',
        search: 'sunset',
      });
      expect(store.activeFilterCount()).toBe(13);
    });

    it('should not count non-filter fields like sort', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        sort: 'date_taken',
        sort_direction: 'ASC',
        hide_blinks: false,
      });
      expect(store.activeFilterCount()).toBe(0);
    });

    it('should count type as an active filter', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        type: 'portrait',
      });
      expect(store.activeFilterCount()).toBe(1);
    });
  });

  describe('loadConfig()', () => {
    it('should fetch config and apply defaults to filters', async () => {
      const cfg = makeConfig({
        pagination: { default_per_page: 32 },
        defaults: {
          type: 'portrait',
          sort: 'date_taken',
          sort_direction: 'ASC',
          hide_blinks: false,
          hide_bursts: false,
          hide_duplicates: false,
          hide_brackets: false,
          hide_panoramas: false,
          hide_details: false,
          tooltip_mode: "hover",
          panel_activation: "both",
          hide_rejected: false,
          gallery_mode: 'mosaic',
        },
      });
      apiGet.mockReturnValue(of(cfg));

      await store.loadConfig();

      expect(apiGet).toHaveBeenCalledWith('/config');
      expect(store.config()).toEqual(cfg);
      expect(store.filters().per_page).toBe(32);
      expect(store.filters().sort).toBe('date_taken');
      expect(store.filters().sort_direction).toBe('ASC');
      expect(store.filters().type).toBe('portrait');
      expect(store.filters().hide_blinks).toBe(false);
      expect(store.filters().hide_bursts).toBe(false);
      expect(store.filters().hide_duplicates).toBe(false);
    });

    it('should overlay URL query params on top of config defaults', async () => {
      const cfg = makeConfig();
      apiGet.mockReturnValue(of(cfg));

      // Simulate URL params via the ActivatedRoute snapshot
      Object.assign(queryParams, { camera: 'Sony A7', min_score: '8' });

      await store.loadConfig();

      expect(store.filters().camera).toBe('Sony A7');
      expect(store.filters().min_score).toBe('8');
      // Config defaults still apply for non-overridden fields
      expect(store.filters().sort).toBe('aggregate');
    });

    it('should use DEFAULT_FILTERS on error', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadConfig();

      expect(store.config()).toBeNull();
      expect(store.filters()).toEqual(DEFAULT_FILTERS);
    });

    it('seeds search_threshold from search_threshold_default, rounded to a percent', async () => {
      const cfg = makeConfig({ search_threshold_default: 0.05 });
      apiGet.mockReturnValue(of(cfg));

      await store.loadConfig();

      expect(store.filters().search_threshold).toBe('5');
    });

    it('leaves search_threshold empty when the config omits search_threshold_default', async () => {
      const cfg = makeConfig({});
      delete (cfg as Record<string, unknown>)['search_threshold_default'];
      apiGet.mockReturnValue(of(cfg));

      await store.loadConfig();

      expect(store.filters().search_threshold).toBe('');
    });

    it('leaves search_threshold empty on config load failure, so /photos omits semantic_threshold', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadConfig();

      expect(store.filters().search_threshold).toBe('');

      store.filters.update(f => ({ ...f, semanticQuery: 'sunset' }));
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.loadPhotos();

      const call = apiGet.mock.calls.find(([path]) => path === '/photos');
      expect(call?.[1]).toMatchObject({ semantic_q: 'sunset' });
      expect(call?.[1]).not.toHaveProperty('semantic_threshold');
    });

    it('should apply URL query params even on config error', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      Object.assign(queryParams, { tag: 'landscape', hide_blinks: 'false' });

      await store.loadConfig();

      expect(store.filters().tag).toBe('landscape');
      expect(store.filters().hide_blinks).toBe(false);
    });
  });

  describe('loadPhotos()', () => {
    it('should set loading, fetch photos, and update state', async () => {
      const response = makePhotosResponse({
        photos: [makePhoto({ filename: 'a.jpg' }), makePhoto({ filename: 'b.jpg' })],
        total: 100,
        has_more: true,
      });
      apiGet.mockReturnValue(of(response));

      const promise = store.loadPhotos();
      expect(store.loading()).toBe(true);

      await promise;

      expect(store.loading()).toBe(false);
      expect(store.photos()).toEqual(response.photos);
      expect(store.total()).toBe(100);
      expect(store.hasMore()).toBe(true);
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ page: 1, per_page: 64 }));
    });

    it('coerces the 0/1 flag columns the API sends into real booleans', async () => {
      // The API serialises these straight out of SQLite, so the wire carries 1/0
      // while Photo declares booleans. Without the normalisation at ingest this
      // assertion sees the integers.
      apiGet.mockReturnValue(of(makePhotosResponse({
        photos: [{
          ...makePhoto({ filename: 'a.jpg' }),
          is_favorite: 1,
          is_rejected: 0,
          is_burst_lead: 1,
        } as unknown as Photo],
      })));

      await store.loadPhotos();

      const p = store.photos()[0];
      expect(p.is_favorite).toBe(true);
      expect(p.is_rejected).toBe(false);
      expect(p.is_burst_lead).toBe(true);
    });

    it('keeps a null flag null instead of turning it into false', async () => {
      // NULL means "no stored value" — the state of is_favorite/is_rejected on
      // all but a handful of rows in a real library.
      apiGet.mockReturnValue(of(makePhotosResponse({
        photos: [makePhoto({ filename: 'a.jpg', is_favorite: null, is_rejected: null })],
      })));

      await store.loadPhotos();

      expect(store.photos()[0].is_favorite).toBeNull();
      expect(store.photos()[0].is_rejected).toBeNull();
    });

    it('should surface the error and NOT restore the previous photos on failure', async () => {
      // Set initial state
      store.photos.set([makePhoto({ filename: 'existing.jpg' })]);
      store.total.set(50);
      store.hasMore.set(true);

      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadPhotos();

      expect(store.loading()).toBe(false);
      expect(store.photos()).toEqual([]);
      expect(store.total()).toBe(0);
      expect(store.hasMore()).toBe(false);
      expect(store.loadError()).toBe(true);
    });

    it('should surface the error when the similar-photos branch fails', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, similar_to: '/a.jpg' });
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledWith(
        `/similar_photos/${encodeURIComponent('/a.jpg')}`, expect.any(Object),
      );
      expect(store.photos()).toEqual([]);
      expect(store.loadError()).toBe(true);
      expect(store.loading()).toBe(false);
    });

    it('keeps a translated no-visual-features reason visible and clears it on retry', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, similar_to: '/a.jpg', min_similarity: '0' });
      apiGet.mockReturnValue(of({ similar: [], total: 0, has_more: false, message: 'no_visual_features' }));
      await store.loadPhotos();
      expect(store.loadError()).toBe(true);
      expect(store.loadErrorKey()).toBe(I18N.similar.no_visual_features);
      expect(apiGet).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ min_similarity: '0' }));
      apiGet.mockReturnValue(of({ similar: [makePhoto()], total: 1, has_more: false }));
      await store.loadPhotos();
      expect(store.loadError()).toBe(false);
      expect(store.loadErrorKey()).toBeUndefined();
      expect(store.photos()).toHaveLength(1);
    });

    for (const [mode, code, key] of [
      ['color', 'no_histogram', I18N.similar.no_histogram],
      ['person', 'no_faces', I18N.similar.no_faces],
    ] as const) {
      it(`shows the translated reason for ${code} in ${mode} mode`, async () => {
        store.filters.set({ ...DEFAULT_FILTERS, similar_to: '/a.jpg', similarity_mode: mode });
        apiGet.mockReturnValue(of({ similar: [], total: 0, has_more: false, message: code }));
        await store.loadPhotos();
        expect(store.loadError()).toBe(true);
        expect(store.loadErrorKey()).toBe(key);
      });
    }

    it('should surface the error when a semantic /photos load fails (400 or 503)', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: 'sunset' });
      apiGet.mockReturnValue(throwError(() => new Error('503')));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ semantic_q: 'sunset' }));
      expect(store.photos()).toEqual([]);
      expect(store.loadError()).toBe(true);
      expect(store.loading()).toBe(false);
    });

    it('sends semantic_q with the other gallery filters to /photos and never calls /search', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: 'sunset', camera: 'Canon', hide_rejected: true });
      apiGet.mockReturnValue(of(makePhotosResponse({ total: 130, has_more: true })));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({
        semantic_q: 'sunset', camera: 'Canon', hide_rejected: true, page: 1,
      }));
      expect(apiGet.mock.calls.some(([path]) => path === '/search')).toBe(false);
      expect(store.total()).toBe(130);
      expect(store.hasMore()).toBe(true);
    });

    it('pages a semantic view through /photos with the same semantic_q', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: 'sunset' });
      apiGet.mockReturnValue(of(makePhotosResponse({ photos: [makePhoto({ path: '/a.jpg' })], total: 2, has_more: true })));
      await store.loadPhotos();
      apiGet.mockClear();
      apiGet.mockReturnValue(of(makePhotosResponse({ photos: [makePhoto({ path: '/b.jpg' })], total: 2, has_more: false })));

      await store.nextPage();

      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ semantic_q: 'sunset', page: 2 }));
      expect(store.photos().map(p => p.path)).toEqual(['/a.jpg', '/b.jpg']);
      expect(store.hasMore()).toBe(false);
    });

    it('reloads a semantic view when a hide toggle changes', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: 'sunset', hide_bursts: true });
      apiGet.mockReturnValue(of(makePhotosResponse()));

      await store.updateFilter('hide_bursts', false);

      const call = apiGet.mock.calls.find(([path]) => path === '/photos');
      expect(call?.[1]).toMatchObject({ semantic_q: 'sunset' });
      expect(call?.[1]).not.toHaveProperty('hide_bursts');
    });

    it('switches to relevance when a query is set and restores the default sort when it is cleared', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilter('sort', 'date_taken');
      await store.updateFilter('semanticQuery', 'sunset');
      expect(store.filters()).toMatchObject({ sort: 'relevance', sort_direction: 'DESC' });
      expect(apiGet).toHaveBeenLastCalledWith('/photos', expect.objectContaining({ semantic_q: 'sunset', sort: 'relevance' }));
      await store.updateFilter('semanticQuery', '');
      expect(store.filters().sort).toBe(DEFAULT_FILTERS.sort);
      expect(apiGet).toHaveBeenLastCalledWith('/photos', expect.objectContaining({ sort: DEFAULT_FILTERS.sort }));
    });

    it('keeps a sort the user picked while a query stays set and on a later clear', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilter('semanticQuery', 'sunset');
      await store.updateFilter('sort', 'date_taken');
      await store.updateFilter('semanticQuery', 'dog');
      expect(store.filters().sort).toBe('date_taken');
      await store.updateFilter('semanticQuery', '');
      expect(store.filters().sort).toBe('date_taken');
    });

    it('updateFilters applies the same relevance switch', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilters({ semanticQuery: 'sunset' });
      expect(store.filters().sort).toBe('relevance');
      await store.updateFilters({ semanticQuery: '' });
      expect(store.filters().sort).not.toBe('relevance');
    });

    it('omits semantic_threshold while the slider still sits on the server seed', async () => {
      // The seed is a rounded percent of the server's own fraction, so sending it
      // back would both freeze a later recalibration out and re-gate 0.075 at 0.08.
      apiGet.mockReturnValue(of(makeConfig({ search_threshold_default: 0.05 })));
      await store.loadConfig();
      store.filters.update(f => ({ ...f, semanticQuery: 'sunset' }));
      expect(store.filters().search_threshold).toBe('5');
      apiGet.mockReturnValue(of(makePhotosResponse()));

      await store.loadPhotos();

      const call = apiGet.mock.calls.find(([path]) => path === '/photos');
      expect(call?.[1]).not.toHaveProperty('semantic_threshold');
    });

    it('sends semantic_threshold once the user moves the slider off the seed', async () => {
      apiGet.mockReturnValue(of(makeConfig({ search_threshold_default: 0.05 })));
      await store.loadConfig();
      store.filters.update(f => ({ ...f, semanticQuery: 'sunset', search_threshold: '12' }));
      apiGet.mockReturnValue(of(makePhotosResponse()));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ semantic_threshold: 0.12 }));
    });

    it('filterKey changes on a slider-only move', async () => {
      apiGet.mockReturnValue(of(makeConfig({ search_threshold_default: 0.05 })));
      await store.loadConfig();
      const base = { ...store.filters(), semanticQuery: 'sunset' };

      expect(store.filterKey({ ...base, search_threshold: '12' })).not.toBe(store.filterKey(base));
    });

    it('should clear the error when a retried load succeeds', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      await store.loadPhotos();
      expect(store.loadError()).toBe(true);

      const response = makePhotosResponse({ photos: [makePhoto({ filename: 'retried.jpg' })], total: 1 });
      apiGet.mockReturnValue(of(response));

      await store.loadPhotos();

      expect(apiGet.mock.calls.filter(([url]) => url === '/photos')).toHaveLength(2);
      expect(store.loadError()).toBe(false);
      expect(store.photos()).toEqual(response.photos);
      expect(store.total()).toBe(1);
    });

    it('should clear a previous error at the start of a new load', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      await store.loadPhotos();
      expect(store.loadError()).toBe(true);

      apiGet.mockReturnValue(NEVER);
      void store.loadPhotos();

      expect(store.loadError()).toBe(false);
      expect(store.loading()).toBe(true);
    });

    it('should ignore a superseded load failure', async () => {
      const pending = new Subject<PhotosResponse>();
      apiGet.mockReturnValueOnce(pending.asObservable());
      const stale = store.loadPhotos();

      const response = makePhotosResponse({ photos: [makePhoto({ filename: 'fresh.jpg' })], total: 1 });
      apiGet.mockReturnValue(of(response));
      await store.loadPhotos();

      pending.error(new Error('Network error'));
      await stale;

      expect(store.loadError()).toBe(false);
      expect(store.photos()).toEqual(response.photos);
      expect(store.total()).toBe(1);
      expect(store.loading()).toBe(false);
    });

    it('should pass non-empty filter values as API params', async () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        camera: 'Canon',
        tag: 'landscape',
        min_score: '7',
        hide_blinks: true,
      });
      apiGet.mockReturnValue(of(makePhotosResponse()));

      await store.loadPhotos();

      expect(apiGet).toHaveBeenCalledWith(
        '/photos',
        expect.objectContaining({
          camera: 'Canon',
          tag: 'landscape',
          min_score: '7',
          hide_blinks: true,
        }),
      );
    });

    it('should omit empty string filter values from API params', async () => {
      apiGet.mockReturnValue(of(makePhotosResponse()));

      await store.loadPhotos();

      const params = apiGet.mock.calls[0][1];
      expect(params).not.toHaveProperty('camera');
      expect(params).not.toHaveProperty('lens');
      expect(params).not.toHaveProperty('tag');
      expect(params).not.toHaveProperty('person_id');
      expect(params).not.toHaveProperty('search');
    });
  });

  describe('fetchKeeperHints (via loadPhotos)', () => {
    it('posts the loaded photo paths to /photos/keeper_hints and patches the matching photo', async () => {
      const response = makePhotosResponse({
        photos: [makePhoto({ path: '/a.jpg', filename: 'a.jpg' }), makePhoto({ path: '/b.jpg', filename: 'b.jpg' })],
        total: 2,
      });
      apiGet.mockReturnValue(of(response));
      apiPost.mockReturnValue(of({ '/a.jpg': { has_better: true, best_path: '/b.jpg', keeper_prob: 0.4 } }));

      await store.loadPhotos();

      await vi.waitFor(() =>
        expect(apiPost).toHaveBeenCalledWith('/photos/keeper_hints', { paths: ['/a.jpg', '/b.jpg'] }),
      );
      await vi.waitFor(() =>
        expect(store.photos().find(p => p.path === '/a.jpg')?.keeper_hint).toEqual({
          has_better: true, best_path: '/b.jpg', keeper_prob: 0.4,
        }),
      );
      // Assert /b.jpg is still THERE before asserting it has no hint: with `?.`
      // a bug that dropped every unhinted photo from the store read the same as
      // "this photo correctly has no hint".
      expect(store.photos()).toHaveLength(2);
      const unhinted = store.photos().find(p => p.path === '/b.jpg');
      expect(unhinted).toBeDefined();
      expect(unhinted!.keeper_hint).toBeUndefined();
    });

    it('leaves photos untouched when the keeper-hints request fails', async () => {
      const response = makePhotosResponse({
        photos: [makePhoto({ path: '/a.jpg', filename: 'a.jpg' })],
        total: 1,
      });
      apiGet.mockReturnValue(of(response));
      apiPost.mockReturnValue(throwError(() => new Error('boom')));

      await store.loadPhotos();

      await vi.waitFor(() =>
        expect(apiPost).toHaveBeenCalledWith('/photos/keeper_hints', { paths: ['/a.jpg'] }),
      );
      expect(store.loading()).toBe(false);
      expect(store.photos()).toEqual(response.photos);
      expect(store.photos()[0].keeper_hint).toBeUndefined();
    });
  });

  describe('nextPage()', () => {
    it('should increment page and append photos', async () => {
      const existingPhotos = [makePhoto({ filename: 'a.jpg' })];
      const newPhotos = [makePhoto({ filename: 'b.jpg' })];
      store.photos.set(existingPhotos);
      store.hasMore.set(true);

      apiGet.mockReturnValue(
        of(makePhotosResponse({ photos: newPhotos, total: 2, has_more: false })),
      );

      await store.nextPage();

      expect(store.filters().page).toBe(2);
      expect(store.photos().length).toBe(2);
      expect(store.photos()[0].filename).toBe('a.jpg');
      expect(store.photos()[1].filename).toBe('b.jpg');
      expect(store.hasMore()).toBe(false);
      expect(store.loading()).toBe(false);
    });

    it('should skip when hasMore is false', async () => {
      store.hasMore.set(false);

      await store.nextPage();

      expect(apiGet).not.toHaveBeenCalled();
      expect(store.filters().page).toBe(1);
    });

    it('should skip when already loading', async () => {
      store.hasMore.set(true);
      store.loading.set(true);

      await store.nextPage();

      expect(apiGet).not.toHaveBeenCalled();
    });

    it('should revert page on error', async () => {
      store.hasMore.set(true);
      store.filters.set({ ...DEFAULT_FILTERS, page: 3 });

      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.nextPage();

      expect(store.filters().page).toBe(3);
      expect(store.loading()).toBe(false);
    });

    it('should notify on error and keep the already-loaded photos', async () => {
      const existingPhotos = [makePhoto({ filename: 'a.jpg' })];
      store.photos.set(existingPhotos);
      store.hasMore.set(true);

      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.nextPage();

      expect(snackOpen).toHaveBeenCalledWith('gallery.load_error.page_failed', '', expect.anything());
      expect(store.photos()).toEqual(existingPhotos);
      expect(store.loadError()).toBe(false);
      expect(store.hasMore()).toBe(true);
    });
  });

  describe('updateFilter()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should update a single filter and reset page to 1', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, page: 5 });

      await store.updateFilter('camera', 'Canon EOS R5');

      expect(store.filters().camera).toBe('Canon EOS R5');
      expect(store.filters().page).toBe(1);
    });

    it('should sync URL and reload photos', async () => {
      await store.updateFilter('tag', 'landscape');

      expect(routerNavigate).toHaveBeenCalledWith([], {
        queryParams: expect.objectContaining({ tag: 'landscape' }),
        replaceUrl: true,
      });
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.any(Object));
    });

    it('should clear favorites_only when hide_rejected is enabled', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: true, hide_rejected: false });

      await store.updateFilter('hide_rejected', true);

      expect(store.filters().hide_rejected).toBe(true);
      expect(store.filters().favorites_only).toBe(false);
    });

    it('should clear hide_rejected when favorites_only is enabled', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: false, hide_rejected: true });

      await store.updateFilter('favorites_only', true);

      expect(store.filters().favorites_only).toBe(true);
      expect(store.filters().hide_rejected).toBe(false);
    });

    it('should not affect the other flag when disabling hide_rejected', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, hide_rejected: true, favorites_only: false });

      await store.updateFilter('hide_rejected', false);

      expect(store.filters().hide_rejected).toBe(false);
      expect(store.filters().favorites_only).toBe(false);
    });

    it('should not affect the other flag when disabling favorites_only', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: true, hide_rejected: false });

      await store.updateFilter('favorites_only', false);

      expect(store.filters().favorites_only).toBe(false);
      expect(store.filters().hide_rejected).toBe(false);
    });

    it('should update search_threshold without reloading when no semantic query is set', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: '', page: 3 });

      await store.updateFilter('search_threshold', '20');

      expect(store.filters().search_threshold).toBe('20');
      // Unchanged: nothing to reload for -- the value only feeds
      // semantic_threshold, which is not sent without a query.
      expect(store.filters().page).toBe(3);
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('should reload when search_threshold changes while a semantic query is active', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: 'sunset', page: 3 });

      await store.updateFilter('search_threshold', '20');

      expect(store.filters().search_threshold).toBe('20');
      expect(store.filters().page).toBe(1);
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ semantic_q: 'sunset', semantic_threshold: 0.2 }));
    });
  });

  describe('updateFilterDebounced()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should update the filter and URL synchronously without an immediate reload', () => {
      store.updateFilterDebounced('min_score', '7');

      expect(store.filters().min_score).toBe('7');
      expect(store.filters().page).toBe(1);
      expect(routerNavigate).toHaveBeenCalled();
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('should coalesce rapid range updates into a single reload', async () => {
      vi.useFakeTimers();
      try {
        store.updateFilterDebounced('min_score', '5');
        store.updateFilterDebounced('min_score', '6');
        store.updateFilterDebounced('min_score', '7');
        expect(apiGet).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(300);
      } finally {
        vi.useRealTimers();
      }

      expect(apiGet.mock.calls.filter(([url]) => url === '/photos')).toHaveLength(1);
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ min_score: '7' }));
    });

    it('should let an immediate updateFilter cancel a pending debounced reload', async () => {
      vi.useFakeTimers();
      try {
        store.updateFilterDebounced('min_score', '7');
        await store.updateFilter('camera', 'Canon');
        await vi.advanceTimersByTimeAsync(300);
      } finally {
        vi.useRealTimers();
      }

      expect(apiGet.mock.calls.filter(([url]) => url === '/photos')).toHaveLength(1);
    });
  });

  describe('updateFilters()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should merge multiple updates and reset page to 1', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, page: 3 });

      await store.updateFilters({ camera: 'Sony', lens: '85mm', min_score: '7' });

      expect(store.filters().camera).toBe('Sony');
      expect(store.filters().lens).toBe('85mm');
      expect(store.filters().min_score).toBe('7');
      expect(store.filters().page).toBe(1);
    });

    it('should sync URL and reload photos', async () => {
      await store.updateFilters({ sort: 'date_taken', sort_direction: 'ASC' });

      expect(routerNavigate).toHaveBeenCalled();
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.any(Object));
    });

    it('should clear favorites_only when hide_rejected is enabled', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: true, hide_rejected: false });

      await store.updateFilters({ hide_rejected: true });

      expect(store.filters().hide_rejected).toBe(true);
      expect(store.filters().favorites_only).toBe(false);
    });

    it('should clear hide_rejected when favorites_only is enabled', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, favorites_only: false, hide_rejected: true });

      await store.updateFilters({ favorites_only: true });

      expect(store.filters().favorites_only).toBe(true);
      expect(store.filters().hide_rejected).toBe(false);
    });
  });

  describe('resetFilters()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should restore config defaults when config is loaded', async () => {
      const cfg = makeConfig({
        pagination: { default_per_page: 32 },
        defaults: {
          type: '',
          sort: 'date_taken',
          sort_direction: 'ASC',
          hide_blinks: false,
          hide_bursts: true,
          hide_duplicates: true,
          hide_brackets: true,
          hide_panoramas: true,
          hide_details: true,
          tooltip_mode: "hover",
          panel_activation: "both",
          hide_rejected: true,
          gallery_mode: 'mosaic',
        },
      });
      store.config.set(cfg);
      store.filters.set({
        ...DEFAULT_FILTERS,
        camera: 'Canon',
        min_score: '7',
        page: 5,
      });

      await store.resetFilters();

      expect(store.filters().per_page).toBe(32);
      expect(store.filters().sort).toBe('date_taken');
      expect(store.filters().sort_direction).toBe('ASC');
      expect(store.filters().hide_blinks).toBe(false);
      expect(store.filters().camera).toBe('');
      expect(store.filters().min_score).toBe('');
      expect(store.filters().page).toBe(1);
    });

    it('re-seeds search_threshold from the loaded config, same as loadConfig()', async () => {
      const cfg = makeConfig({ search_threshold_default: 0.05 });
      store.config.set(cfg);
      store.filters.set({ ...DEFAULT_FILTERS, search_threshold: '30', page: 5 });

      await store.resetFilters();

      expect(store.filters().search_threshold).toBe('5');
    });

    it('should use DEFAULT_FILTERS when no config is loaded', async () => {
      store.filters.set({ ...DEFAULT_FILTERS, camera: 'Canon', page: 3 });

      await store.resetFilters();

      expect(store.filters()).toEqual(DEFAULT_FILTERS);
    });

    it('should sync URL and reload photos', async () => {
      await store.resetFilters();

      expect(routerNavigate).toHaveBeenCalled();
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.any(Object));
    });
  });

  describe('filter journal', () => {
    const journal = () => TestBed.inject(UserActivityJournal);
    const filterEntries = () => journal().since().items.filter(i => i.kind === 'filters');

    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('records typing a search through updateFilter', async () => {
      await store.updateFilter('search', 'sunset');
      expect(filterEntries().map(i => i.value)).toEqual([{ changed: { search: 'sunset' } }]);
    });

    it('records a slider drag as one merged entry', () => {
      vi.useFakeTimers();
      try {
        for (const v of ['4', '5', '6', '7']) store.updateFilterDebounced('min_score', v);
      } finally {
        vi.useRealTimers();
      }
      expect(filterEntries().map(i => i.value)).toEqual([{ changed: { min_score: '7' } }]);
    });

    it('records updateFilters and a reset as {reset: true}', async () => {
      await store.updateFilters({ camera: 'Canon', lens: '50mm' });
      expect(filterEntries().map(i => i.value)).toEqual([{ changed: { camera: 'Canon', lens: '50mm' } }]);
      await store.resetFilters();
      expect(filterEntries().map(i => i.value)).toEqual([{ changed: { camera: 'Canon', lens: '50mm' } }, { reset: true }]);
    });

    it('includes the sort side-change of a semantic query, but not a sort-only change', async () => {
      await store.updateFilter('sort', 'date_taken');
      expect(filterEntries()).toEqual([]);
      await store.updateFilter('semanticQuery', 'dog');
      expect(filterEntries().map(i => i.value)).toEqual([
        { changed: { semanticQuery: 'dog', sort: 'relevance' } },
      ]);
    });

    it('records the hide toggles, favorites_only and showAllHidden, which are real query filters', async () => {
      await store.updateFilter('hide_rejected', false);
      await store.updateFilter('favorites_only', true);
      expect(filterEntries().map(i => i.value)).toEqual([
        { changed: { hide_rejected: false, favorites_only: true } },
      ]);
      store.showAllHidden();
      await Promise.resolve();
      const last = filterEntries().at(-1)!.value as { changed: Record<string, boolean> };
      expect(last.changed['hide_bursts']).toBe(false);
    });

    it('records nothing for page, layout or an unchanged value', async () => {
      await store.updateFilter('hide_details', false);
      await store.updateFilter('camera', '');
      expect(filterEntries()).toEqual([]);
    });

    it('records nothing for an edit made inside a UI tool scope', async () => {
      await journal().suppress(async () => {
        await store.updateFilter('search', 'agent');
        await store.updateFilters({ camera: 'Sony' });
        await store.resetFilters();
      });
      expect(filterEntries()).toEqual([]);
    });

    it('does not touch the journal when the config and the URL are restored, and does on a user edit', async () => {
      const spy = vi.spyOn(store as unknown as { journalFilters: () => void }, 'journalFilters');
      Object.assign(queryParams, { camera: 'Sony A7' });
      apiGet.mockReturnValue(of(makeConfig()));
      await store.loadConfig();
      expect(store.filters().camera).toBe('Sony A7');
      expect(spy).not.toHaveBeenCalled();
      apiGet.mockReturnValue(of(makePhotosResponse()));
      await store.updateFilter('tag', 'x');
      expect(spy).toHaveBeenCalledTimes(1);
    });
  });

  describe('viewFilterParams', () => {
    it('projects the five hide toggles as explicit "1"/"0" strings', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: false, hide_panoramas: true,
      });

      expect(store.viewFilterParams()).toEqual({
        hide_blinks: '1', hide_bursts: '0', hide_duplicates: '1', hide_brackets: '0', hide_panoramas: '1',
      });
    });

    it('stays referentially stable across an unrelated filter change', () => {
      const before = store.viewFilterParams();
      store.filters.update(f => ({ ...f, camera: 'Canon', page: 2, sort: 'date_taken' }));
      expect(store.viewFilterParams()).toBe(before);
    });

    it('produces a new value once a hide toggle actually changes', () => {
      const before = store.viewFilterParams();
      store.filters.update(f => ({ ...f, hide_bursts: false }));
      const after = store.viewFilterParams();
      expect(after).not.toBe(before);
      expect(after.hide_bursts).toBe('0');
    });
  });

  describe('showAllHidden() / restoreHidden()', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('stashes the current hide toggles and clears all five', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });

      store.showAllHidden();

      expect(store.hiddenFiltersStash()).toEqual({
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      expect(store.filters().hide_blinks).toBe(false);
      expect(store.filters().hide_bursts).toBe(false);
      expect(store.filters().hide_duplicates).toBe(false);
      expect(store.filters().hide_brackets).toBe(false);
      expect(store.filters().hide_panoramas).toBe(false);
    });

    it('restoreHidden() brings back the stashed toggles and clears the stash', () => {
      store.filters.set({
        ...DEFAULT_FILTERS,
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      store.showAllHidden();

      store.restoreHidden();

      expect(store.filters().hide_blinks).toBe(true);
      expect(store.filters().hide_bursts).toBe(false);
      expect(store.filters().hide_duplicates).toBe(true);
      expect(store.filters().hide_brackets).toBe(true);
      expect(store.filters().hide_panoramas).toBe(true);
      expect(store.hiddenFiltersStash()).toBeNull();
    });

    it('restoreHidden() is a no-op without a prior showAllHidden()', () => {
      const before = store.filters();
      store.restoreHidden();
      expect(store.filters()).toBe(before);
    });
  });

  describe('loadTypeCounts()', () => {
    it('should fetch and set type counts', async () => {
      const counts: TypeCount[] = [
        { id: 'portrait', label: 'Portrait', count: 100 },
        { id: 'landscape', label: 'Landscape', count: 50 },
      ];
      apiGet.mockReturnValue(of({ types: counts }));

      await store.loadTypeCounts();

      expect(apiGet).toHaveBeenCalledWith('/type_counts', {
        hide_blinks: '1', hide_bursts: '1', hide_duplicates: '1', hide_brackets: '1', hide_panoramas: '1',
      });
      expect(store.types()).toEqual(counts);
    });

    it('sends the EFFECTIVE hide-toggle state, not the config default', async () => {
      apiGet.mockReturnValue(of({ types: [] }));
      store.filters.update(f => ({ ...f, hide_bursts: false }));

      await store.loadTypeCounts();

      expect(apiGet).toHaveBeenCalledWith('/type_counts', expect.objectContaining({ hide_bursts: '0' }));
    });

    it('should set empty array on error', async () => {
      store.types.set([{ id: 'old', label: 'Old', count: 1 }]);
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));

      await store.loadTypeCounts();

      expect(store.types()).toEqual([]);
    });

    it('should set empty array when the request never responds', async () => {
      store.types.set([{ id: 'old', label: 'Old', count: 1 }]);
      apiGet.mockReturnValue(NEVER);

      vi.useFakeTimers();
      try {
        const pending = store.loadTypeCounts();
        await vi.advanceTimersByTimeAsync(FILTER_OPTIONS_TIMEOUT_MS + 1);
        await pending;
      } finally {
        vi.useRealTimers();
      }

      expect(store.types()).toEqual([]);
    });
  });

  describe('loadFilterOptions()', () => {
    it('should load all options in parallel', async () => {
      apiGet.mockImplementation((path: string) => {
        switch (path) {
          case '/filter_options/cameras':
            return of({ cameras: [['Canon EOS R5', 50]] });
          case '/filter_options/lenses':
            return of({ lenses: [['RF 50mm', 30]] });
          case '/filter_options/tags':
            return of({ tags: [['landscape', 20]] });
          case '/filter_options/persons':
            return of({ persons: [[1, 'Alice', 15]] });
          case '/filter_options/patterns':
            return of({ patterns: [['rule_of_thirds', 40]] });
          case '/filter_options/apertures':
            return of({ apertures: [] });
          case '/filter_options/focal_lengths':
            return of({ focal_lengths: [] });
          default:
            return throwError(() => new Error(`Unexpected path: ${path}`));
        }
      });

      await store.loadFilterOptions();

      expect(store.cameras()).toEqual([{ value: 'Canon EOS R5', count: 50 }]);
      expect(store.lenses()).toEqual([{ value: 'RF 50mm', count: 30 }]);
      expect(store.tags()).toEqual([{ value: 'landscape', count: 20 }]);
      expect(store.persons()).toEqual([{ id: 1, name: 'Alice', face_count: 15 }]);
      expect(store.patterns()).toEqual([{ value: 'rule_of_thirds', count: 40 }]);
    });

    it('should use empty array for individual failures', async () => {
      apiGet.mockImplementation((path: string) => {
        if (path === '/filter_options/cameras') {
          return of({ cameras: [['Canon', 10]] });
        }
        return throwError(() => new Error('Failed'));
      });

      await store.loadFilterOptions();

      expect(store.cameras()).toEqual([{ value: 'Canon', count: 10 }]);
      expect(store.lenses()).toEqual([]);
      expect(store.tags()).toEqual([]);
      expect(store.persons()).toEqual([]);
      expect(store.patterns()).toEqual([]);
    });

    it('should time out a hung endpoint and still populate the other dropdowns', async () => {
      apiGet.mockImplementation((path: string) => {
        switch (path) {
          case '/filter_options/cameras':
            return of({ cameras: [['Canon EOS R5', 50]] });
          case '/filter_options/lenses':
            return of({ lenses: [['RF 50mm', 30]] });
          case '/filter_options/tags':
            return of({ tags: [['landscape', 20]] });
          case '/filter_options/persons':
            return of({ persons: [[1, 'Alice', 15]] });
          case '/filter_options/patterns':
            return of({ patterns: [['rule_of_thirds', 40]] });
          case '/filter_options/colors':
            return of({ temps: [['warm', 12]], hue_buckets: [['blue', 8]] });
          default:
            return NEVER;
        }
      });

      vi.useFakeTimers();
      try {
        const pending = store.loadFilterOptions();
        await vi.advanceTimersByTimeAsync(FILTER_OPTIONS_TIMEOUT_MS + 1);
        await pending;
      } finally {
        vi.useRealTimers();
      }

      expect(store.metricRanges()).toEqual({});
      expect(store.cameras()).toEqual([{ value: 'Canon EOS R5', count: 50 }]);
      expect(store.lenses()).toEqual([{ value: 'RF 50mm', count: 30 }]);
      expect(store.tags()).toEqual([{ value: 'landscape', count: 20 }]);
      expect(store.persons()).toEqual([{ id: 1, name: 'Alice', face_count: 15 }]);
      expect(store.patterns()).toEqual([{ value: 'rule_of_thirds', count: 40 }]);
      expect(store.colorTemps()).toEqual([{ value: 'warm', count: 12 }]);
      expect(store.hueBuckets()).toEqual([{ value: 'blue', count: 8 }]);
    });
  });

  describe('pinned list (showPaths)', () => {
    const paths = ['/b.jpg', '/a.jpg'];
    const byPaths = () => of({ photos: [makePhoto({ path: '/b.jpg' }), makePhoto({ path: '/a.jpg' })], total: 2, missing: ['/gone.jpg'] });

    beforeEach(async () => {
      apiGet.mockImplementation((path: string) => of(path === '/config' ? makeConfig() : makePhotosResponse()));
      apiPost.mockImplementation((path: string) => path === '/photos/by_paths' ? byPaths() : of({}));
      await store.showPaths(paths);
      apiGet.mockClear();
    });

    it('clears a path selection so the previous view does not carry over', async () => {
      store.selectedPaths.set(new Set(['/old.jpg']));
      await store.showPaths(paths);
      expect(store.selectedPaths().size).toBe(0);
    });

    it('clears a view-scoped selection too', async () => {
      store.selectionScope.set('view');
      store.excludedPaths.set(new Set(['/x.jpg']));
      await store.showPaths(paths);
      expect(store.viewScopeSelected()).toBe(false);
      expect(store.selectionScope()).toBe('paths');
      expect(store.excludedPaths().size).toBe(0);
    });

    const expectFilteredReload = () => {
      expect(store.pinnedPaths()).toBeNull();
      expect(apiGet.mock.calls.some(c => c[0] === '/photos')).toBe(true);
    };

    it('posts the paths to /photos/by_paths, never GET /photos, and keeps the requested order', () => {
      expect(apiPost).toHaveBeenCalledWith('/photos/by_paths', { paths });
      expect(apiGet).not.toHaveBeenCalled();
      expect(store.photos().map(p => p.path)).toEqual(paths);
      expect(store.total()).toBe(2);
      expect(store.hasMore()).toBe(false);
      expect(store.pinnedMissing()).toEqual(['/gone.jpg']);
      expect(store.canScopeSelectionToView()).toBe(false);
      expect(store.filterPayload()).toBeNull();
    });

    it('updateFilter drops the pin and loads the filtered view', async () => {
      await store.updateFilter('camera', 'X100');
      expectFilteredReload();
    });

    it('updateFilterDebounced drops the pin once its reload fires', async () => {
      vi.useFakeTimers();
      try {
        store.updateFilterDebounced('min_score', '7');
        await vi.advanceTimersByTimeAsync(400);
      } finally {
        vi.useRealTimers();
      }
      expectFilteredReload();
    });

    it('loadConfig drops the pin (it replaces the filters wholesale)', async () => {
      await store.loadConfig();
      expect(store.pinnedPaths()).toBeNull();
    });

    it('showAllHidden drops the pin and loads the filtered view', async () => {
      store.showAllHidden();
      await vi.waitFor(() => expect(apiGet.mock.calls.some(c => c[0] === '/photos')).toBe(true));
      expect(store.pinnedPaths()).toBeNull();
    });

    it('restoreHidden drops the pin and loads the filtered view', async () => {
      store.hiddenFiltersStash.set({
        hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      store.restoreHidden();
      await vi.waitFor(() => expect(apiGet.mock.calls.some(c => c[0] === '/photos')).toBe(true));
      expect(store.pinnedPaths()).toBeNull();
    });

    it('nextPage keeps the pin and fetches nothing', async () => {
      store.hasMore.set(true);
      await store.nextPage();
      expect(store.pinnedPaths()).toEqual(paths);
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('reloadPhotos keeps the pin and re-posts the paths', async () => {
      apiPost.mockClear();
      await store.reloadPhotos();
      expect(store.pinnedPaths()).toEqual(paths);
      expect(apiPost).toHaveBeenCalledWith('/photos/by_paths', { paths });
      expect(apiGet.mock.calls.some(c => c[0] === '/photos')).toBe(false);
    });

    it('updateFilters drops the pin and loads the filtered view', async () => {
      await store.updateFilters({ camera: 'X100' });
      expectFilteredReload();
    });

    it('resetFilters drops the pin and loads the filtered view', async () => {
      await store.resetFilters();
      expectFilteredReload();
    });

    it('Keep top N% refuses while a list is pinned, calling nothing', async () => {
      expect(await store.selectBottomPercent(50)).toBeNull();
      expect(apiGet.mock.calls.some(c => String(c[0]).includes('select_bottom_percent'))).toBe(false);
    });

    it('clearPinned reloads the filtered view', async () => {
      await store.clearPinned();
      expectFilteredReload();
    });
  });

  describe('syncUrl (via updateFilter)', () => {
    beforeEach(() => {
      apiGet.mockReturnValue(of(makePhotosResponse()));
    });

    it('should only include non-default params in URL', async () => {
      await store.updateFilter('camera', 'Canon');

      expect(routerNavigate).toHaveBeenCalledWith([], {
        queryParams: { camera: 'Canon' },
        replaceUrl: true,
      });
    });

    it('should include sort when it differs from config defaults', async () => {
      const cfg = makeConfig();
      store.config.set(cfg);

      await store.updateFilter('sort', 'date_taken');

      expect(routerNavigate).toHaveBeenCalledWith([], {
        queryParams: expect.objectContaining({ sort: 'date_taken' }),
        replaceUrl: true,
      });
    });

    it('should include hide_blinks when it differs from config defaults', async () => {
      const cfg = makeConfig();
      store.config.set(cfg);

      await store.updateFilter('hide_blinks', false);

      expect(routerNavigate).toHaveBeenCalledWith([], {
        queryParams: expect.objectContaining({ hide_blinks: 'false' }),
        replaceUrl: true,
      });
    });

    it('should not include hide_blinks when it matches config default', async () => {
      const cfg = makeConfig();
      store.config.set(cfg);

      await store.updateFilter('camera', 'Canon');

      const params = routerNavigate.mock.calls[0][1].queryParams;
      expect(params).not.toHaveProperty('hide_blinks');
    });
  });
  describe('refreshPaths (assistant writes, in place)', () => {
    const paths = ['/b.jpg', '/a.jpg', '/c.jpg'];
    const byPathsBodies = () => apiPost.mock.calls
      .filter(c => c[0] === '/photos/by_paths')
      .map(c => c[1] as { paths: string[]; filters?: Record<string, unknown> });
    const echoByPaths = (override: (p: string) => Partial<Photo> = () => ({}), missing: string[] = []) =>
      apiPost.mockImplementation((path: string, body?: { paths?: string[] }) => path === '/photos/by_paths'
        ? of({
          photos: (body?.paths ?? []).filter(p => !missing.includes(p)).map(p => makePhoto({ path: p, ...override(p) })),
          total: 0,
          missing: missing.filter(p => (body?.paths ?? []).includes(p)),
        })
        : of({}));

    describe('pinned view', () => {
      beforeEach(async () => {
        apiGet.mockImplementation((path: string) => of(path === '/config' ? makeConfig() : makePhotosResponse()));
        echoByPaths();
        await store.showPaths(paths);
        apiPost.mockClear();
      });

      it('changes only the named photo and leaves the pin intact', async () => {
        const order = store.pinnedPaths();
        const before = store.photos();
        echoByPaths(() => ({ is_rejected: true }));
        await store.refreshPaths(['/a.jpg']);
        const after = store.photos();
        expect(after.find(p => p.path === '/a.jpg')?.is_rejected).toBeTruthy();
        expect(after.filter(p => p.path !== '/a.jpg')).toEqual(before.filter(p => p.path !== '/a.jpg'));
        expect(after.map(p => p.path)).toEqual(before.map(p => p.path));
        expect(store.pinnedPaths()).toEqual(order);
        expect(byPathsBodies()).toEqual([{ paths: ['/a.jpg'] }]);
      });

      it('removes a photo the server reports missing from the grid, the pin and the selection', async () => {
        store.selectedPaths.set(new Set(['/a.jpg', '/b.jpg']));
        echoByPaths(() => ({}), ['/a.jpg']);
        await store.refreshPaths(['/a.jpg']);
        expect(store.photos().map(p => p.path)).not.toContain('/a.jpg');
        expect(store.pinnedPaths()).not.toContain('/a.jpg');
        expect(store.selectedPaths().has('/a.jpg')).toBe(false);
        expect(store.selectedPaths().has('/b.jpg')).toBe(true);
      });

      it('on a null batch posts the full pinned list once and keeps the pin', async () => {
        const order = store.pinnedPaths();
        const seen: number[] = [];
        const stop = setInterval(() => seen.push(store.photos().length), 0);
        echoByPaths(() => ({ is_rejected: true }));
        await store.refreshPaths(null);
        clearInterval(stop);
        expect(byPathsBodies()).toEqual([{ paths }]);
        expect(store.pinnedPaths()).toEqual(order);
        expect(store.photos().map(p => p.path)).toEqual(paths);
        expect(store.photos().every(p => p.is_rejected)).toBe(true);
        expect(seen.every(n => n === 3)).toBe(true);
      });

      it('a null reload keeps the pin order and fields the refetch did not return (C17)', async () => {
        store.photos.update(rows => rows.map(p => ({ ...p, caption: `old-${p.path}` })));
        echoByPaths();
        apiPost.mockImplementation((path: string, body?: { paths?: string[] }) => of({
          photos: [...(body?.paths ?? [])].reverse().map(p => ({ path: p, star_rating: 2 })),
          total: 0,
          missing: [],
        }));
        await store.refreshPaths(null);
        expect(store.photos().map(p => p.path)).toEqual(paths);
        expect(store.photos().every(p => p.caption === `old-${p.path}` && p.star_rating === 2)).toBe(true);
      });

      it('sends nothing for a path that is not loaded', async () => {
        await store.refreshPaths(['/elsewhere.jpg']);
        expect(apiPost).not.toHaveBeenCalled();
      });
    });

    describe('filter view', () => {
      const many = Array.from({ length: 600 }, (_, n) => `/p${n}.jpg`);
      beforeEach(async () => {
        apiGet.mockImplementation((path: string) => of(path === '/config'
          ? makeConfig()
          : makePhotosResponse({ photos: many.map(p => makePhoto({ path: p })), total: 600 })));
        store.filters.set({ ...DEFAULT_FILTERS, hide_rejected: true, camera: 'Canon', album_id: '4', type: '' });
        await store.loadConfig();
        store.filters.update(f => ({ ...f, hide_rejected: true, camera: 'Canon', album_id: '4', type: 'portrait' }));
        await store.loadPhotos();
        apiGet.mockClear();
        apiPost.mockClear();
        echoByPaths();
      });

      it('sends the view filters (hide_rejected, camera, album, type) and no paging or sort', async () => {
        await store.refreshPaths(['/p1.jpg']);
        const [body] = byPathsBodies();
        expect(body.paths).toEqual(['/p1.jpg']);
        expect(body.filters).toMatchObject({ hide_rejected: true, camera: 'Canon', album_id: '4', type: 'portrait' });
        for (const key of ['page', 'per_page', 'sort', 'sort_direction']) expect(body.filters).not.toHaveProperty(key);
      });

      it('sends the viewer default type explicitly when the filter has none', async () => {
        store.config.set(makeConfig({ defaults: { ...makeConfig().defaults, type: 'top_picks' } }));
        store.filters.update(f => ({ ...f, type: '' }));
        await store.refreshPaths(['/p1.jpg']);
        expect(byPathsBodies()[0].filters).toMatchObject({ type: 'top_picks' });
      });

      it('chunks 600 loaded paths into two requests of at most 500', async () => {
        await store.refreshPaths(many);
        const bodies = byPathsBodies();
        expect(bodies.map(b => b.paths.length)).toEqual([500, 100]);
      });

      it('removes a photo that no longer matches the filters', async () => {
        echoByPaths(() => ({}), ['/p2.jpg']);
        store.selectedPaths.set(new Set(['/p2.jpg']));
        await store.refreshPaths(['/p2.jpg', '/p3.jpg']);
        expect(store.photos().some(p => p.path === '/p2.jpg')).toBe(false);
        expect(store.photos().some(p => p.path === '/p3.jpg')).toBe(true);
        expect(store.total()).toBe(599);
        expect(store.selectedPaths().size).toBe(0);
      });

      it('applies two overlapping refreshes for different paths in arrival order (S1)', async () => {
        const slow = new Subject<unknown>();
        apiPost.mockReturnValueOnce(slow);
        const first = store.refreshPaths(['/p1.jpg']);
        echoByPaths(() => ({ star_rating: 5 }));
        const second = store.refreshPaths(['/p2.jpg']);
        await Promise.resolve();
        slow.next({ photos: [makePhoto({ path: '/p1.jpg', star_rating: 3 })], total: 1, missing: [] });
        slow.complete();
        await Promise.all([first, second]);
        expect(store.photos().find(p => p.path === '/p1.jpg')?.star_rating).toBe(3);
        expect(store.photos().find(p => p.path === '/p2.jpg')?.star_rating).toBe(5);
      });

      it('lets a later batch win for the same path because refreshes run in order', async () => {
        const slow = new Subject<unknown>();
        apiPost.mockReturnValueOnce(slow);
        const first = store.refreshPaths(['/p1.jpg']);
        echoByPaths(() => ({ star_rating: 5 }));
        const second = store.refreshPaths(['/p1.jpg']);
        slow.next({ photos: [makePhoto({ path: '/p1.jpg', star_rating: 1 })], total: 1, missing: [] });
        slow.complete();
        await Promise.all([first, second]);
        expect(store.photos().find(p => p.path === '/p1.jpg')?.star_rating).toBe(5);
      });

      it('applies a slow null batch even when a fast path batch follows it (S2)', async () => {
        const reply = new Subject<PhotosResponse>();
        apiGet.mockImplementation((path: string) => path === '/photos' ? reply : of({}));
        const first = store.refreshPaths(null);
        echoByPaths(() => ({ star_rating: 4 }));
        const second = store.refreshPaths(['/p9.jpg']);
        await Promise.resolve();
        reply.next(makePhotosResponse({ photos: [makePhoto({ path: '/p9.jpg' })], total: 1, has_more: false }));
        reply.complete();
        await Promise.all([first, second]);
        expect(store.photos().map(p => p.path)).toEqual(['/p9.jpg']);
        expect(store.photos()[0].star_rating).toBe(4);
      });

      it('a failed refresh does not block the next one', async () => {
        apiPost.mockReturnValueOnce(throwError(() => new Error('boom')));
        const first = store.refreshPaths(['/p1.jpg']);
        echoByPaths(() => ({ star_rating: 2 }));
        const second = store.refreshPaths(['/p2.jpg']);
        await Promise.all([first, second]);
        expect(store.photos().find(p => p.path === '/p2.jpg')?.star_rating).toBe(2);
      });

      it('keeps the appended page when the user pages during the view refetch (S3)', async () => {
        const page1 = Array.from({ length: 2 }, (_, n) => makePhoto({ path: `/q${n}.jpg` }));
        const page2 = Array.from({ length: 2 }, (_, n) => makePhoto({ path: `/q${n + 2}.jpg` }));
        apiGet.mockImplementation((path: string) => of(path === '/photos'
          ? makePhotosResponse({ photos: page1, total: 4, has_more: true })
          : {}));
        await store.loadPhotos();
        const slow = new Subject<PhotosResponse>();
        let slowUsed = 0;
        apiGet.mockImplementation((path: string, params?: { page?: number }) => {
          if (path !== '/photos') return of({});
          if (params?.page === 2) return of(makePhotosResponse({ photos: page2, total: 4, has_more: false }));
          return slowUsed++ === 0 ? slow.pipe(take(1)) : of(makePhotosResponse({ photos: page1, total: 4, has_more: true }));
        });
        const run = store.refreshPaths(null);
        await Promise.resolve();
        await store.nextPage();
        expect(store.photos().length).toBe(4);
        slow.next(makePhotosResponse({ photos: page1, total: 4, has_more: true }));
        await run;
        expect(store.photos().map(p => p.path)).toEqual(['/q0.jpg', '/q1.jpg', '/q2.jpg', '/q3.jpg']);
      });

      it('never duplicates rows when a null batch arrives during an in-flight nextPage (S4)', async () => {
        const page1 = Array.from({ length: 2 }, (_, n) => makePhoto({ path: `/q${n}.jpg` }));
        const page2 = Array.from({ length: 2 }, (_, n) => makePhoto({ path: `/q${n + 2}.jpg` }));
        apiGet.mockImplementation((path: string) => of(path === '/photos'
          ? makePhotosResponse({ photos: page1, total: 4, has_more: true })
          : {}));
        await store.loadPhotos();
        const pageTwo = new Subject<PhotosResponse>();
        apiGet.mockImplementation((path: string, params?: { page?: number }) => {
          if (path !== '/photos') return of({});
          return params?.page === 2 ? pageTwo.pipe(take(1)) : of(makePhotosResponse({ photos: page1, total: 4, has_more: true }));
        });
        const paging = store.nextPage();
        const refresh = store.refreshPaths(null);
        await refresh;
        apiGet.mockImplementation((path: string, params?: { page?: number }) => path === '/photos'
          ? of(params?.page === 2
            ? makePhotosResponse({ photos: page2, total: 4, has_more: false })
            : makePhotosResponse({ photos: page1, total: 4, has_more: true }))
          : of({}));
        pageTwo.next(makePhotosResponse({ photos: page2, total: 4, has_more: false }));
        await paging;
        await vi.waitFor(() => expect(store.photos().length).toBe(4));
        const seen = store.photos().map(p => p.path);
        expect(new Set(seen).size).toBe(seen.length);
        expect(seen).toEqual(['/q0.jpg', '/q1.jpg', '/q2.jpg', '/q3.jpg']);
      });

      it('discards a refresh when the view was reloaded meanwhile', async () => {
        const pending = new Subject<unknown>();
        apiPost.mockReturnValueOnce(pending);
        const run = store.refreshPaths(['/p1.jpg']);
        await store.loadPhotos();
        pending.next({ photos: [makePhoto({ path: '/p1.jpg', star_rating: 5 })], total: 1, missing: [] });
        pending.complete();
        await run;
        expect(store.photos().find(p => p.path === '/p1.jpg')?.star_rating).not.toBe(5);
      });

      it('on a null batch reloads in place: view scope, exclusions and rows survive, no by_paths', async () => {
        store.selectWholeView();
        store.excludedPaths.set(new Set(['/p5.jpg']));
        const lengths: number[] = [];
        const reply = new Subject<PhotosResponse>();
        apiGet.mockImplementation((path: string) => {
          lengths.push(store.photos().length);
          return path === '/photos' ? reply : of({});
        });
        const run = store.refreshPaths(null);
        expect(store.photos().length).toBe(600);
        await Promise.resolve();
        reply.next(makePhotosResponse({ photos: [makePhoto({ path: '/p9.jpg' })], total: 1, has_more: false }));
        reply.complete();
        await run;
        expect(store.viewScopeSelected()).toBe(true);
        expect(store.excludedPaths().has('/p5.jpg')).toBe(true);
        expect(store.photos().map(p => p.path)).toEqual(['/p9.jpg']);
        expect(lengths.every(n => n === 600)).toBe(true);
        expect(apiPost.mock.calls.some(c => c[0] === '/photos/by_paths')).toBe(false);
      });
    });

    describe('semantic views', () => {
      const semanticReply = () => makePhotosResponse({
        photos: [makePhoto({ path: '/s1.jpg' }), makePhoto({ path: '/s2.jpg' })], total: 2,
      });

      it('refreshes a rating via by_paths without semantic keys and drops a row the filters no longer match', async () => {
        apiGet.mockImplementation((path: string) => of(path === '/photos' ? semanticReply() : makeConfig()));
        store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: 'dog', search_threshold: '12' });
        await store.loadPhotos();
        echoByPaths(() => ({ star_rating: 4 }), ['/s2.jpg']);
        await store.refreshPaths(['/s1.jpg', '/s2.jpg']);
        const filters = byPathsBodies()[0].filters ?? {};
        expect(filters).not.toHaveProperty('semantic_q');
        expect(filters).not.toHaveProperty('semantic_threshold');
        expect(store.photos().map(p => p.path)).toEqual(['/s1.jpg']);
        expect(store.photos()[0].star_rating).toBe(4);
      });

      it('refetches the loaded pages through /photos on a null batch', async () => {
        apiGet.mockImplementation((path: string) => of(path === '/photos' ? semanticReply() : makeConfig()));
        store.filters.set({ ...DEFAULT_FILTERS, semanticQuery: 'dog' });
        await store.loadPhotos();
        apiPost.mockClear();
        apiGet.mockClear();
        await store.refreshPaths(null);
        expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ semantic_q: 'dog', page: 1 }));
        expect(apiGet.mock.calls.some(([path]) => path === '/search')).toBe(false);
        expect(byPathsBodies()).toEqual([]);
      });
    });

    describe('batch$ subscription', () => {
      it('does not load the gallery for a null batch before its first load', async () => {
        assistantBatches.next({ paths: null });
        await Promise.resolve();
        expect(apiGet).not.toHaveBeenCalled();
        expect(apiPost).not.toHaveBeenCalled();
      });

      it('refreshes in place when a batch arrives after the first load', async () => {
        apiGet.mockImplementation((path: string) => of(path === '/config' ? makeConfig() : makePhotosResponse()));
        await store.loadPhotos();
        apiPost.mockClear();
        echoByPaths(() => ({ star_rating: 2 }));
        assistantBatches.next({ paths: ['/test.jpg'] });
        await vi.waitFor(() => expect(store.photos()[0].star_rating).toBe(2));
      });
    });
  });
});

describe('GalleryStore selection', () => {
  let store: GalleryStore;
  let apiGet: Mock;
  let apiPost: Mock;

  beforeEach(() => {
    apiGet = vi.fn(() => of(makePhotosResponse()));
    apiPost = vi.fn(() => of({}));
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: apiGet, post: apiPost } },
        { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { identity: () => '0|', isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.photos.set([
      makePhoto({ path: '/a.jpg' }),
      makePhoto({ path: '/b.jpg' }),
      makePhoto({ path: '/c.jpg' }),
      makePhoto({ path: '/d.jpg' }),
    ]);
    // Four rows on screen out of a 650-row view: the whole point of the
    // 'view' scope is that those two numbers differ.
    store.total.set(650);
  });

  it('toggles a single photo', () => {
    store.toggleSelection(store.photos()[1]);
    expect([...store.selectedPaths()]).toEqual(['/b.jpg']);
    store.toggleSelection(store.photos()[1]);
    expect(store.selectionCount()).toBe(0);
  });

  it('shift-click extends the range from the last selected index', () => {
    store.toggleSelection(store.photos()[0]);
    store.toggleSelection(store.photos()[2], { shiftKey: true } as MouseEvent);
    expect([...store.selectedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
  });

  it('selectAllLoaded selects every loaded photo as an explicit path set', () => {
    store.selectAllLoaded();
    expect(store.selectionCount()).toBe(4);
    expect(store.selectionScope()).toBe('paths');
    expect([...store.selectedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
  });

  it('selectAllLoaded is idempotent, and stays on the loaded photos', () => {
    store.selectAllLoaded();
    store.selectAllLoaded();
    expect(store.selectionCount()).toBe(4);
    expect(store.selectionScope()).toBe('paths');
  });

  it('clearSelection empties both sets, returns to path scope and resets the anchor', () => {
    store.selectWholeView();
    store.toggleSelection(store.photos()[0]);
    store.clearSelection();
    expect(store.selectionCount()).toBe(0);
    expect(store.selectionScope()).toBe('paths');
    expect(store.excludedPaths().size).toBe(0);
    store.toggleSelection(store.photos()[2], { shiftKey: true } as MouseEvent);
    expect([...store.selectedPaths()]).toEqual(['/c.jpg']);
  });

  it('restoreSelection rehydrates a saved set', () => {
    store.restoreSelection(['/a.jpg', '/d.jpg']);
    expect([...store.selectedPaths()].sort()).toEqual(['/a.jpg', '/d.jpg']);
    expect(store.selectionScope()).toBe('paths');
  });

  it('invertSelection swaps the selection for its complement', () => {
    store.toggleSelection(store.photos()[0]);
    store.toggleSelection(store.photos()[2]);
    store.invertSelection();
    expect([...store.selectedPaths()].sort()).toEqual(['/b.jpg', '/d.jpg']);
  });

  it('invertSelection twice returns the original selection', () => {
    store.toggleSelection(store.photos()[1]);
    store.invertSelection();
    store.invertSelection();
    expect([...store.selectedPaths()]).toEqual(['/b.jpg']);
  });

  it('invertSelection resets the range anchor so the next shift-click starts fresh', () => {
    store.toggleSelection(store.photos()[0]);
    store.invertSelection();
    store.toggleSelection(store.photos()[2], { shiftKey: true } as MouseEvent);
    expect([...store.selectedPaths()].sort()).toEqual(['/b.jpg', '/d.jpg']);
  });

  describe('whole-view scope', () => {
    it('select-all on an empty selection covers the view, not the loaded page', () => {
      store.selectAll();

      expect(store.selectionScope()).toBe('view');
      expect(store.selectionCount()).toBe(650);
    });

    // The whole feature: the filter the grid was already fetched with IS the
    // selection, so declaring it costs nothing.
    it('makes no request to do it', () => {
      store.selectAll();

      expect(apiGet).not.toHaveBeenCalled();
      expect(apiPost).not.toHaveBeenCalled();
    });

    // Was 'invertSelection on an empty selection selects everything', where
    // "everything" meant the four loaded rows.
    it('invertSelection on an empty selection covers the view too, still without a request', () => {
      store.invertSelection();

      expect(store.selectionScope()).toBe('view');
      expect(store.selectionCount()).toBe(650);
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('select-all over an existing view selection re-ticks what was unticked', () => {
      store.selectWholeView();
      store.toggleSelection(store.photos()[1]);

      store.selectAll();

      expect(store.selectionScope()).toBe('view');
      expect(store.excludedPaths().size).toBe(0);
      expect(store.selectionCount()).toBe(650);
    });

    it('select-all from a PARTIAL selection stays on the loaded photos', () => {
      store.toggleSelection(store.photos()[0]);

      store.selectAll();

      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(4);
    });

    it('counts the view minus what the user unticked', () => {
      store.selectWholeView();

      store.toggleSelection(store.photos()[1]);

      expect([...store.excludedPaths()]).toEqual(['/b.jpg']);
      expect(store.selectedPaths().size).toBe(0);
      expect(store.selectionCount()).toBe(649);
    });

    it('re-ticking an unticked photo puts it back', () => {
      store.selectWholeView();
      store.toggleSelection(store.photos()[1]);

      store.toggleSelection(store.photos()[1]);

      expect(store.excludedPaths().size).toBe(0);
      expect(store.selectionCount()).toBe(650);
    });

    it('shift-click unticks a whole range', () => {
      store.selectWholeView();

      store.toggleSelection(store.photos()[0]);
      store.toggleSelection(store.photos()[2], { shiftKey: true } as MouseEvent);

      expect([...store.excludedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
      expect(store.selectionCount()).toBe(647);
    });

    it('inverting it yields exactly what was unticked, with no round trip', () => {
      store.selectWholeView();
      store.toggleSelection(store.photos()[1]);

      store.invertSelection();

      expect(store.selectionScope()).toBe('paths');
      expect([...store.selectedPaths()]).toEqual(['/b.jpg']);
      expect(store.excludedPaths().size).toBe(0);
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('a filter change drops it — the view it named is gone', async () => {
      store.selectWholeView();
      apiGet.mockReturnValue(of(makePhotosResponse({ total: 12 })));

      await store.updateFilter('camera', 'Canon');

      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(0);
    });

    it('survives paging — appending a page does not change what the view IS', async () => {
      store.selectWholeView();
      store.hasMore.set(true);
      apiGet.mockReturnValue(of(makePhotosResponse({ total: 650, has_more: true })));

      await store.nextPage();

      expect(store.selectionScope()).toBe('view');
    });

    // Both rank server-side outside the gallery WHERE clause, so no filter
    // payload reproduces them. Falling back to the loaded photos beats a
    // shortcut that does nothing at all.
    it('falls back to the loaded photos under a similarity view', () => {
      store.filters.update(f => ({ ...f, similar_to: '/x.jpg' }));

      store.selectAll();

      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(4);
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('select-all still refuses the view scope under a semantic search', () => {
      store.filters.update(f => ({ ...f, semanticQuery: 'sunset' }));

      store.selectAll();

      expect(store.canScopeSelectionToView()).toBe(false);
      expect(store.selectionScope()).toBe('paths');
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('falls back to the loaded photos under a semantic search', () => {
      store.filters.update(f => ({ ...f, semanticQuery: 'sunset' }));

      store.invertSelection();

      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(4);
      expect(apiGet).not.toHaveBeenCalled();
    });
  });

  describe('resolving a whole-view selection to numbers and paths', () => {
    it('countInView asks the server rather than trusting the last page response', async () => {
      apiGet.mockReturnValue(of({ total: 650 }));

      expect(await store.countInView()).toBe(650);
      expect(apiGet).toHaveBeenCalledWith('/photos/count', expect.objectContaining({ page: '1' }));
    });

    it('pathsInView drops the unticked photos', async () => {
      store.selectWholeView();
      store.toggleSelection(store.photos()[0]);
      apiGet.mockReturnValue(of({ total: 3, paths: ['/a.jpg', '/b.jpg', '/c.jpg'] }));

      expect(await store.pathsInView()).toEqual(['/b.jpg', '/c.jpg']);
    });

    it('both refuse a view that cannot be expressed as a filter', async () => {
      store.filters.update(f => ({ ...f, similar_to: '/x.jpg' }));

      expect(await store.countInView()).toBeNull();
      expect(await store.pathsInView()).toBeNull();
      expect(apiGet).not.toHaveBeenCalled();
    });

    it('countInView resolves null and notifies when the server request fails', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      expect(await store.countInView()).toBeNull();

      expect(apiGet).toHaveBeenCalledWith('/photos/count', expect.any(Object));
      expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
    });

    it('pathsInView resolves null and notifies when the server request fails', async () => {
      apiGet.mockReturnValue(throwError(() => new Error('Network error')));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      expect(await store.pathsInView()).toBeNull();

      expect(apiGet).toHaveBeenCalledWith('/photos/paths', expect.any(Object));
      expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
    });

    // The server refuses past its own cap rather than truncating, so the
    // caller gets none of the paths — "action failed" would read as a bug,
    // where the filter is the thing the user can actually change.
    it('pathsInView names the size, not a generic failure, on the 412', async () => {
      apiGet.mockReturnValue(throwError(() => new HttpErrorResponse({
        status: 412,
        error: { detail: 'Too many photos for this action (10000 max). Narrow the filters.' },
      })));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      expect(await store.pathsInView()).toBeNull();

      expect(snackOpen).toHaveBeenCalledWith('gallery.selection.paths_too_many', '', expect.anything());
      expect(snackOpen.mock.calls.some(c => c[0] === 'errors.action_failed')).toBe(false);
    });
  });
});

describe('GalleryStore batch mutations by selection scope', () => {
  let store: GalleryStore;
  let apiPost: Mock;

  beforeEach(() => {
    apiPost = vi.fn(() => of({ success: true, count: 2 }));
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: vi.fn(() => of(makePhotosResponse())), post: apiPost } },
        { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { identity: () => '0|', isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.photos.set([makePhoto({ path: '/a.jpg' }), makePhoto({ path: '/b.jpg' })]);
    store.total.set(650);
  });

  const lastBody = () => apiPost.mock.calls.at(-1)![1] as Record<string, unknown>;

  it('sends an explicit path list under path scope', async () => {
    store.selectAllLoaded();

    await store.batchFavorite(['/a.jpg', '/b.jpg']);

    expect(apiPost).toHaveBeenCalledWith('/photos/batch_favorite', { photo_paths: ['/a.jpg', '/b.jpg'] });
  });

  it('sends the filter and the exclusions under view scope, never a path list', async () => {
    store.selectWholeView();
    store.toggleSelection(store.photos()[0]);

    await store.batchReject([]);

    expect(apiPost.mock.calls.at(-1)![0]).toBe('/photos/batch_reject');
    // The server takes exactly one target form and 422s on both.
    expect(lastBody()['photo_paths']).toBeUndefined();
    expect(lastBody()['exclude']).toEqual(['/a.jpg']);
  });

  // GalleryParams types the hide toggles as `str`, so a raw JSON `true` --
  // which is what buildApiParams holds -- would 422 where 'true' parses.
  it('stringifies the filter values, exactly as the query string does', async () => {
    store.filters.update(f => ({ ...f, hide_bursts: true, camera: 'Canon' }));
    store.selectWholeView();

    await store.batchFavorite([]);

    const filters = lastBody()['filters'] as Record<string, unknown>;
    expect(filters['hide_bursts']).toBe('true');
    expect(filters['page']).toBe('1');
    expect(filters['camera']).toBe('Canon');
  });

  it('carries the rating alongside the filter', async () => {
    store.selectWholeView();

    await store.batchRating([], 4);

    expect(lastBody()['rating']).toBe(4);
    expect(lastBody()['filters']).toBeDefined();
  });

  it('patches the loaded photos optimistically under view scope', async () => {
    store.selectWholeView();
    store.toggleSelection(store.photos()[0]);

    await store.batchReject([]);

    expect(store.photos()[0].is_rejected).toBeFalsy(); // unticked
    expect(store.photos()[1].is_rejected).toBe(true);
  });

  it('reports how far the action reached versus how much the snapshot covers', async () => {
    // A "Keep top N%" selection: 5,000 paths, two of them on screen. Five
    // requests of BATCH_PATHS_PER_REQUEST, so five times whatever the server
    // says each one changed.
    const paths = ['/a.jpg', ...Array.from({ length: 4999 }, (_, i) => `/p${i}.jpg`)];

    const res = await store.batchReject(paths);

    expect(res!.targeted).toBe(5000);
    expect(res!.snapshot.size).toBe(1);
    expect(res!.count).toBe(10); // whatever the server says it changed
  });

  it('reports the whole view as targeted under view scope', async () => {
    store.selectWholeView();
    store.toggleSelection(store.photos()[0]);

    const res = await store.batchFavorite([]);

    expect(res!.targeted).toBe(649);
    expect(res!.snapshot.size).toBe(1);
  });

  // "Keep top N%" restores up to _SELECT_BOTTOM_MAX (5,000) paths, and the
  // server binds photo_paths to BATCH_PATHS_PER_REQUEST (1,000): one POST of
  // the whole selection is a 422, so the documented workflow breaks on exactly
  // the large library it exists for.
  describe('a path selection larger than the server cap', () => {
    const paths = Array.from({ length: 2500 }, (_, i) => `/p${i}.jpg`);

    const sentChunks = () => apiPost.mock.calls.map(c => (c[1] as { photo_paths: string[] }).photo_paths);

    it('splits it into one request per chunk, none over the cap', async () => {
      await store.batchReject(paths);

      const chunks = sentChunks();
      expect(chunks.map(c => c.length)).toEqual([1000, 1000, 500]);
      expect(chunks.flat()).toEqual(paths);
      expect(apiPost.mock.calls.every(c => c[0] === '/photos/batch_reject')).toBe(true);
    });

    it('sums what every chunk changed into one count', async () => {
      apiPost
        .mockReturnValueOnce(of({ count: 1000 }))
        .mockReturnValueOnce(of({ count: 1000 }))
        .mockReturnValueOnce(of({ count: 500 }));

      const res = await store.batchRating(paths, 4);

      expect(res!.count).toBe(2500);
      expect(res!.targeted).toBe(2500);
      // The rating rides along on every chunk, not just the first.
      expect(apiPost.mock.calls.every(c => (c[1] as { rating: number }).rating === 4)).toBe(true);
    });

    // The chunks that landed are the server's truth now: reverting them would
    // put the UI back to a state the database no longer holds.
    it('keeps the chunks that landed and reverts only the ones that did not', async () => {
      store.photos.set([
        makePhoto({ path: '/p0.jpg' }),     // first chunk — written
        makePhoto({ path: '/p1500.jpg' }),  // second chunk — the one that fails
        makePhoto({ path: '/p2400.jpg' }),  // third chunk — never sent
      ]);
      apiPost
        .mockReturnValueOnce(of({ count: 1000 }))
        .mockReturnValueOnce(throwError(() => new Error('Network error')));

      const res = await store.batchReject(paths);

      expect(res).toBeNull();
      expect(apiPost).toHaveBeenCalledTimes(2); // stops at the failure
      expect(store.photos()[0].is_rejected).toBe(true);
      expect(store.photos()[1].is_rejected).toBeFalsy();
      expect(store.photos()[2].is_rejected).toBeFalsy();
    });

    it('names how many photos did change instead of a blanket failure', async () => {
      apiPost
        .mockReturnValueOnce(of({ count: 1000 }))
        .mockReturnValueOnce(throwError(() => new Error('Network error')));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await store.batchReject(paths);

      expect(snackOpen).toHaveBeenCalledWith('gallery.selection.batch_partial', '', expect.anything());
      expect(snackOpen.mock.calls.some(c => c[0] === 'errors.action_failed')).toBe(false);
    });

    it('falls back to the plain failure when the very first chunk fails', async () => {
      apiPost.mockReturnValueOnce(throwError(() => new Error('Network error')));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await store.batchReject(paths);

      expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
      expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.batch_partial')).toBe(false);
    });
  });
});

describe('GalleryStore optimistic mutations', () => {
  let store: GalleryStore;
  let apiPost: Mock;
  let snackOpen: Mock;

  beforeEach(() => {
    apiPost = vi.fn(() => of({}));
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: vi.fn(), post: apiPost } },
        { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { identity: () => '0|', isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.photos.set([
      makePhoto({ path: '/a.jpg', is_favorite: false, is_rejected: false, star_rating: 3 }),
      makePhoto({ path: '/b.jpg', is_favorite: true, is_rejected: false, star_rating: null }),
    ]);
  });

  it('rebuilds a review queue when a single rating changes its sort order', async () => {
    const all = Array.from({ length: 4 }, (_, i) => makePhoto({ path: `/p${i}.jpg`, star_rating: i + 1 }));
    store.photos.set(all);
    store.filters.set({ ...DEFAULT_FILTERS, review_status: 'undecided', sort: 'star_rating', sort_direction: 'ASC', per_page: 2, page: 2 });
    const reordered = [...all.slice(1), { ...all[0], star_rating: 5 }];
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockImplementation((_url: string, params: { page: number }) => of(makePhotosResponse({
      photos: reordered.slice((params.page - 1) * 2, params.page * 2), total: 4, has_more: params.page === 1,
    })));
    await store.setRating('/p0.jpg', 5);
    expect(store.photos().map(p => p.path)).toEqual(['/p1.jpg', '/p2.jpg', '/p3.jpg', '/p0.jpg']);
  });

  it('rebuilds favorites-only rejected pages when a single rejection clears a favorite', async () => {
    const all = Array.from({ length: 4 }, (_, i) => makePhoto({ path: `/p${i}.jpg`, is_rejected: true, is_favorite: true, star_rating: 4 }));
    store.photos.set(all);
    store.filters.set({ ...DEFAULT_FILTERS, review_status: 'rejected', favorites_only: true, per_page: 2, page: 2 });
    const remaining = all.slice(1);
    apiPost.mockReturnValue(of({ is_rejected: true, star_rating: 0 }));
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockImplementation((_url: string, params: { page: number }) => of(makePhotosResponse({
      photos: remaining.slice((params.page - 1) * 2, params.page * 2), total: 3, has_more: params.page === 1,
    })));
    await store.toggleRejected('/p0.jpg');
    expect(store.photos().map(p => p.path)).toEqual(['/p1.jpg', '/p2.jpg', '/p3.jpg']);
    expect(store.total()).toBe(3);
  });

  it('keeps a photo without changing stars or favorite and snapshots its decision', async () => {
    const result = await store.batchReview(['/a.jpg'], 'kept');
    expect(apiPost).toHaveBeenCalledWith('/photos/batch_review', { photo_paths: ['/a.jpg'], decision: 'kept' });
    expect(store.photos()[0]).toMatchObject({ is_kept: true, is_rejected: false, star_rating: 3 });
    expect(result?.snapshot.get('/a.jpg')?.is_kept).toBe(false);
  });

  it('reloads Needs review from page one after saving, and Undo restores a removed keeper', async () => {
    store.photos.update(photos => photos.map(p => ({ ...p, is_kept: false })));
    store.filters.set({ ...DEFAULT_FILTERS, review_status: 'undecided', page: 3 });
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse({ photos: [makePhoto({ path: '/b.jpg' })], total: 1 })));
    const result = await store.batchReview(['/a.jpg'], 'kept');
    expect(store.photos().map(p => p.path)).toEqual(['/b.jpg']);
    expect(store.filters().page).toBe(1);
    expect(store.total()).toBe(1);
    expect(result?.snapshot.get('/a.jpg')).toMatchObject({ is_kept: false, star_rating: 3 });
    await store.restoreSnapshot(result!.snapshot);
    expect(apiPost).toHaveBeenCalledWith('/photos/batch_review', { photo_paths: ['/a.jpg'], decision: 'undecided' });
  });

  it('Undo restores kept plus favorite and stars after rejection', async () => {
    store.photos.set([makePhoto({ path: '/a.jpg', is_kept: true, is_favorite: true, star_rating: 4 })]);
    const result = await store.batchReject(['/a.jpg']);
    expect(store.photos()[0]).toMatchObject({ is_kept: false, is_rejected: true });
    await store.restoreSnapshot(result!.snapshot);
    expect(apiPost).toHaveBeenCalledWith('/photos/batch_review', { photo_paths: ['/a.jpg'], decision: 'kept' });
    expect(store.photos()[0]).toMatchObject({ is_kept: true, is_rejected: false, is_favorite: true, star_rating: 4 });
  });

  it('single-photo review never targets the selected whole view', async () => {
    store.selectionScope.set('view');
    await store.batchReview(['/a.jpg'], 'kept', false);
    expect(apiPost).toHaveBeenCalledWith('/photos/batch_review', { photo_paths: ['/a.jpg'], decision: 'kept' });
  });

  it('refreshes the review queue after a partially successful batch', async () => {
    const refresh = vi.spyOn(store, 'refreshReviewResults').mockResolvedValue();
    const paths = Array.from({ length: 1001 }, (_, i) => `/p${i}.jpg`);
    apiPost.mockReturnValueOnce(of({ count: 1000 })).mockReturnValueOnce(throwError(() => new Error('offline')));
    expect(await store.batchReview(paths, 'kept')).toBeNull();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('Undo restores rejection with the same cleared metadata as other reject actions', async () => {
    store.photos.set([makePhoto({ path: '/a.jpg', is_kept: false, is_rejected: true, is_favorite: true, star_rating: 4 })]);
    const result = await store.batchReview(['/a.jpg'], 'kept');
    await store.restoreSnapshot(result!.snapshot);
    expect(apiPost).toHaveBeenLastCalledWith('/photos/batch_review', { photo_paths: ['/a.jpg'], decision: 'rejected' });
    expect(store.photos()[0]).toMatchObject({ is_kept: false, is_rejected: true, is_favorite: false, star_rating: null });
  });

  it('refills only the tail of 1100 loaded rows and keeps nextPage contiguous', async () => {
    const all = Array.from({ length: 1300 }, (_, i) => makePhoto({ path: `/p${i}.jpg`, is_kept: false }));
    store.photos.set(all.slice(0, 1100));
    store.filters.set({ ...DEFAULT_FILTERS, review_status: 'undecided', page: 18 });
    let remaining = all.slice(3);
    apiPost.mockImplementation((url: string, body: { decision?: string }) => {
      if (url === '/photos/batch_review' && body.decision === 'undecided') remaining = all;
      return of({});
    });
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockImplementation((_url: string, params: { page: number; per_page: number }) => of(makePhotosResponse({ photos: remaining.slice((params.page - 1) * params.per_page, params.page * params.per_page), total: remaining.length, has_more: params.page * params.per_page < remaining.length })));
    const result = await store.batchReview(all.slice(0, 3).map(p => p.path), 'kept');
    expect(get.mock.calls.filter(([url]) => url === '/photos')).toHaveLength(1);
    expect(get).toHaveBeenLastCalledWith('/photos', expect.objectContaining({ page: 18, per_page: 64 }));
    expect(store.photos().map(p => p.path)).toEqual(remaining.slice(0, 1152).map(p => p.path));
    expect(apiPost).toHaveBeenCalledWith('/photos/keeper_hints', { paths: remaining.slice(1088, 1152).map(p => p.path) });
    await store.nextPage();
    expect(store.photos().map(p => p.path)).toEqual(remaining.slice(0, 1216).map(p => p.path));
    await store.restoreSnapshot(result!.snapshot);
    expect(store.photos().map(p => p.path)).toEqual(all.slice(0, 1216).map(p => p.path));
    expect(snackOpen).not.toHaveBeenCalled();
  });
  it('rebuilds sorted review pages when batch rating moves a row out of the prefix', async () => {
    const all = Array.from({ length: 4 }, (_, i) => makePhoto({ path: `/p${i}.jpg`, star_rating: i + 1 }));
    store.photos.set(all);
    store.filters.set({ ...DEFAULT_FILTERS, review_status: 'undecided', sort: 'star_rating', sort_direction: 'ASC', per_page: 2, page: 2 });
    const reordered = [...all.slice(1), { ...all[0], star_rating: 5 }];
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockImplementation((_url: string, params: { page: number }) => of(makePhotosResponse({
      photos: reordered.slice((params.page - 1) * 2, params.page * 2), total: 4, has_more: params.page === 1,
    })));
    await store.batchRating(['/p0.jpg'], 5);
    expect(store.photos().map(p => p.path)).toEqual(['/p1.jpg', '/p2.jpg', '/p3.jpg', '/p0.jpg']);
  });

  it('rebuilds review pages when unfavoriting removes an early favorites-only row', async () => {
    const all = Array.from({ length: 4 }, (_, i) => makePhoto({ path: `/p${i}.jpg`, is_favorite: true }));
    store.photos.set(all);
    store.filters.set({ ...DEFAULT_FILTERS, review_status: 'undecided', favorites_only: true, per_page: 2, page: 2 });
    const remaining = all.slice(1);
    apiPost.mockImplementation((url: string) => of(url === '/photo/toggle_favorite' ? { is_favorite: false } : {}));
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockImplementation((_url: string, params: { page: number }) => of(makePhotosResponse({
      photos: remaining.slice((params.page - 1) * 2, params.page * 2), total: 3, has_more: params.page === 1,
    })));
    await store.toggleFavorite('/p0.jpg');
    expect(store.photos().map(p => p.path)).toEqual(['/p1.jpg', '/p2.jpg', '/p3.jpg']);
    expect(store.total()).toBe(3);
  });

  it('rebuilds rejected favorites-only pages when batch rejection clears a prefix favorite', async () => {
    const all = Array.from({ length: 4 }, (_, i) => makePhoto({ path: `/p${i}.jpg`, is_rejected: true, is_favorite: true, star_rating: 4 }));
    store.photos.set(all);
    store.filters.set({ ...DEFAULT_FILTERS, review_status: 'rejected', favorites_only: true, per_page: 2, page: 2 });
    const remaining = all.slice(1);
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockImplementation((_url: string, params: { page: number }) => of(makePhotosResponse({
      photos: remaining.slice((params.page - 1) * 2, params.page * 2), total: 3, has_more: params.page === 1,
    })));
    await store.batchReject(['/p0.jpg']);
    expect(store.photos().map(p => p.path)).toEqual(['/p1.jpg', '/p2.jpg', '/p3.jpg']);
    expect(store.total()).toBe(3);
  });

  it('ignores pending tail refill after filters change', async () => {
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    const response = new Subject<PhotosResponse>();
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValueOnce(response).mockReturnValue(of(makePhotosResponse({ photos: [makePhoto({ path: '/new.jpg' })] })));
    const pending = store.refreshReviewResults();
    await store.updateFilter('review_status', 'kept');
    response.next(makePhotosResponse({ photos: [makePhoto({ path: '/stale.jpg' })] }));
    await pending;
    expect(store.photos().map(p => p.path)).toEqual(['/new.jpg']);
  });
  it('selecting review clears ranked modes and retains ordinary filters', async () => {
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse()));
    store.filters.update(f => ({ ...f, similar_to: '/a.jpg', semanticQuery: 'sunset', search: 'beach', album_id: '3' }));
    await store.updateFilter('review_status', 'undecided');
    expect(store.filters()).toMatchObject({ similar_to: '', semanticQuery: '', search: 'beach', album_id: '3' });
    expect(get).toHaveBeenCalledWith('/photos', expect.objectContaining({ review_status: 'undecided' }));
  });

  it('keeps the earliest removed photos available for Undo with more than 1000 loaded', async () => {
    const photos = Array.from({ length: 1100 }, (_, i) => makePhoto({ path: `/p${i}.jpg`, is_kept: false }));
    store.photos.set(photos);
    store.filters.set({ ...DEFAULT_FILTERS, review_status: 'undecided', per_page: 1200 });
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse({ photos: photos.slice(3), total: 1097 })));
    const result = await store.batchReview(photos.slice(0, 3).map(photo => photo.path), 'kept');
    await store.restoreSnapshot(result!.snapshot);
    expect(apiPost).toHaveBeenCalledWith('/photos/batch_review', {
      photo_paths: ['/p0.jpg', '/p1.jpg', '/p2.jpg'], decision: 'undecided',
    });
  });

  it('notifies when an Undo photo is no longer available instead of claiming restoration', async () => {
    await store.restoreSnapshot(new Map([['/missing.jpg', { is_favorite: false, is_rejected: false, is_kept: false, star_rating: null }]]));
    expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
  });

  it('rolls back a failed review decision', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('offline')));
    expect(await store.batchReview(['/a.jpg'], 'kept')).toBeNull();
    expect(store.photos()[0].is_kept).toBeFalsy();
  });

  describe('user activity journal', () => {
    const kinds = (): string[] => TestBed.inject(UserActivityJournal).since().items.map(i => i.kind);

    it('records a rating, a favorite toggle, and a reject toggle', async () => {
      apiPost.mockReturnValue(of({ is_favorite: true, is_rejected: true, star_rating: null }));
      await store.setRating('/a.jpg', 3);
      await store.toggleFavorite('/a.jpg');
      await store.toggleRejected('/b.jpg');
      expect(kinds()).toEqual(['rating', 'favorite', 'reject']);
    });

    it('records a batch action but not a failed one', async () => {
      apiPost.mockReturnValue(of({ count: 2 }));
      await store.batchFavorite(['/a.jpg', '/b.jpg']);
      apiPost.mockReturnValue(throwError(() => new Error('boom')));
      await store.batchReject(['/a.jpg']);
      const items = TestBed.inject(UserActivityJournal).since().items;
      expect(items.map(i => i.kind)).toEqual(['favorite']);
      expect(items[0].paths).toEqual(['/a.jpg', '/b.jpg']);
    });

    it('records the person actions with ids, and nothing for a failed one', async () => {
      apiPost.mockReturnValue(of({ id: 9, name: 'Anna', face_count: 2 }));
      expect(await store.createPerson(' Anna ', [1, 2], '/a.jpg')).not.toBeNull();
      await store.assignFace(5, 9, '/a.jpg', 'Anna');
      await store.unassignPerson('/a.jpg', 9);
      apiPost.mockReturnValue(throwError(() => new Error('boom')));
      await store.assignFace(6, 9, '/a.jpg', 'Anna');
      await store.unassignPerson('/a.jpg', 9);
      await store.createPerson('Bob');
      const items = TestBed.inject(UserActivityJournal).since().items;
      expect(items.map(i => [i.kind, i.paths, i.value])).toEqual([
        ['person', ['/a.jpg'], { action: 'create', person_id: 9, name: 'Anna', count: 2 }],
        ['person', ['/a.jpg'], { action: 'assign', person_id: 9 }],
        ['person', ['/a.jpg'], { action: 'unassign', person_id: 9 }],
      ]);
    });

    it('records nothing for a failed rating', async () => {
      apiPost.mockReturnValue(throwError(() => new Error('boom')));
      await store.setRating('/a.jpg', 3);
      expect(kinds()).toEqual([]);
    });
  });

  it('toggleFavorite applies the flag synchronously before the API resolves', () => {
    apiPost.mockReturnValue(of({ is_favorite: true }));
    void store.toggleFavorite('/a.jpg');
    expect(store.photos()[0].is_favorite).toBe(true);
  });

  it('toggleFavorite reverts and notifies on API error', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('boom')));
    await store.toggleFavorite('/a.jpg');
    expect(store.photos()[0].is_favorite).toBe(false);
    expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
  });

  it('toggleFavorite reconciles with server truth', async () => {
    apiPost.mockReturnValue(of({ is_favorite: false }));
    await store.toggleFavorite('/a.jpg');
    expect(store.photos()[0].is_favorite).toBe(false);
  });

  it('toggleRejected clears favorite optimistically', () => {
    apiPost.mockReturnValue(of({ is_rejected: true }));
    void store.toggleRejected('/b.jpg');
    expect(store.photos()[1].is_rejected).toBe(true);
    expect(store.photos()[1].is_favorite).toBe(false);
  });

  it('toggleRejected clears the star rating, not just is_rejected/is_favorite', () => {
    apiPost.mockReturnValue(of({ is_rejected: true, star_rating: 0 }));
    void store.toggleRejected('/a.jpg'); // starts at star_rating: 3
    expect(store.photos()[0].star_rating).toBeNull();
  });

  it('toggleRejected reconciles the star rating from the server response', async () => {
    apiPost.mockReturnValue(of({ is_rejected: true, star_rating: 0 }));
    await store.toggleRejected('/a.jpg');
    expect(store.photos()[0].star_rating).toBe(0);
  });

  it('un-rejecting keeps the prior star rating (server sends null = unchanged)', async () => {
    store.photos.update(photos =>
      photos.map(p => p.path === '/a.jpg' ? { ...p, is_rejected: true, star_rating: null } : p));
    apiPost.mockReturnValue(of({ is_rejected: false, star_rating: null }));
    await store.toggleRejected('/a.jpg');
    expect(store.photos()[0].is_rejected).toBe(false);
    expect(store.photos()[0].star_rating).toBeNull();
  });

  it('ignores a second toggleFavorite call for the same path while the first is still in flight', async () => {
    const response = new Subject<{ is_favorite: boolean }>();
    apiPost.mockReturnValue(response.asObservable());

    const first = store.toggleFavorite('/a.jpg');
    const second = store.toggleFavorite('/a.jpg'); // dropped -- a call for this path is already in flight

    response.next({ is_favorite: true });
    response.complete();
    await Promise.all([first, second]);

    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(store.photos()[0].is_favorite).toBe(true);
  });

  it('does not let an in-flight toggleFavorite block a later call once it has settled', async () => {
    apiPost.mockReturnValue(of({ is_favorite: true }));
    await store.toggleFavorite('/a.jpg');
    apiPost.mockReturnValue(of({ is_favorite: false }));
    await store.toggleFavorite('/a.jpg');

    expect(apiPost).toHaveBeenCalledTimes(2);
    expect(store.photos()[0].is_favorite).toBe(false);
  });

  it('a pending toggleFavorite also blocks a toggleRejected for the same path (shared guard)', async () => {
    const response = new Subject<{ is_favorite: boolean }>();
    apiPost.mockReturnValue(response.asObservable());

    const first = store.toggleFavorite('/a.jpg');
    const second = store.toggleRejected('/a.jpg'); // dropped -- overlapping fields, same path in flight

    response.next({ is_favorite: true });
    response.complete();
    await Promise.all([first, second]);

    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(store.photos()[0].is_rejected).toBe(false);
  });

  it('batchReject returns the pre-mutation snapshot on success', async () => {
    const res = await store.batchReject(['/a.jpg', '/b.jpg']);
    expect(res).not.toBeNull();
    expect(res!.snapshot.get('/a.jpg')).toEqual({ is_favorite: false, is_rejected: false, is_kept: false, star_rating: 3 });
    expect(res!.snapshot.get('/b.jpg')).toEqual({ is_favorite: true, is_rejected: false, is_kept: false, star_rating: null });
    expect(store.photos()[0].is_rejected).toBe(true);
    expect(store.photos()[0].star_rating).toBeNull();
  });

  it('batchReject reverts everything and returns null on error', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('boom')));
    const res = await store.batchReject(['/a.jpg', '/b.jpg']);
    expect(res).toBeNull();
    expect(store.photos()[0].is_rejected).toBe(false);
    expect(store.photos()[0].star_rating).toBe(3);
    expect(store.photos()[1].is_favorite).toBe(true);
    expect(snackOpen).toHaveBeenCalled();
  });

  it('batchRating applies optimistically and reverts on error', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('boom')));
    const result = await store.batchRating(['/a.jpg'], 5);
    expect(result).toBeNull();
    expect(store.photos()[0].star_rating).toBe(3);
  });

  it('setRating reverts on error', async () => {
    apiPost.mockReturnValue(throwError(() => new Error('boom')));
    await store.setRating('/a.jpg', 5);
    expect(store.photos()[0].star_rating).toBe(3);
  });

  it('reverts a rating and a favourite the server refused with 503 library_busy', async () => {
    const busy = new HttpErrorResponse({ status: 503, error: { detail: 'library_busy' } });
    apiPost.mockReturnValue(throwError(() => busy));
    await store.setRating('/a.jpg', 5);
    await store.toggleFavorite('/a.jpg');
    expect(store.photos()[0].star_rating).toBe(3);
    expect(store.photos()[0].is_favorite).toBe(false);
  });
});

describe('GalleryStore restoreSnapshot', () => {
  let store: GalleryStore;
  let apiPost: Mock;
  let snackOpen: Mock;

  beforeEach(() => {
    apiPost = vi.fn(() => of({}));
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: vi.fn(), post: apiPost } },
        { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { identity: () => '0|', isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
  });

  it('undoes a batch reject: clears rejected, restores favorite and rating', async () => {
    store.photos.set([
      makePhoto({ path: '/a.jpg', is_rejected: true, is_favorite: false, star_rating: null }),
      makePhoto({ path: '/b.jpg', is_rejected: true, is_favorite: false, star_rating: null }),
    ]);
    const snap = new Map([
      ['/a.jpg', { is_favorite: true, is_rejected: false, star_rating: 4 }],
      ['/b.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
    ]);

    await store.restoreSnapshot(snap);

    const calls = apiPost.mock.calls.map(c => [c[0], c[1]]);
    expect(calls).toContainEqual(['/photo/toggle_rejected', { photo_path: '/a.jpg' }]);
    expect(calls).toContainEqual(['/photo/toggle_rejected', { photo_path: '/b.jpg' }]);
    expect(calls).toContainEqual(['/photos/batch_favorite', { photo_paths: ['/a.jpg'] }]);
    expect(calls).toContainEqual(['/photos/batch_rating', { photo_paths: ['/a.jpg'], rating: 4 }]);
    expect(store.photos()[0].is_rejected).toBe(false);
    expect(store.photos()[0].is_favorite).toBe(true);
    expect(store.photos()[0].star_rating).toBe(4);
    expect(store.photos()[1].is_rejected).toBe(false);
  });

  it('undoes a batch favorite: un-favorites only previously-unfavorited photos', async () => {
    store.photos.set([
      makePhoto({ path: '/a.jpg', is_favorite: true }),
      makePhoto({ path: '/b.jpg', is_favorite: true }),
    ]);
    const snap = new Map([
      ['/a.jpg', { is_favorite: true, is_rejected: false, star_rating: null }],
      ['/b.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
    ]);

    await store.restoreSnapshot(snap);

    const calls = apiPost.mock.calls.map(c => [c[0], c[1]]);
    expect(calls).toEqual([['/photo/toggle_favorite', { photo_path: '/b.jpg' }]]);
    expect(store.photos()[0].is_favorite).toBe(true);
    expect(store.photos()[1].is_favorite).toBe(false);
  });

  it('no-ops when state already matches the snapshot', async () => {
    store.photos.set([makePhoto({ path: '/a.jpg', is_favorite: false, is_rejected: false, star_rating: null })]);
    await store.restoreSnapshot(new Map([
      ['/a.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
    ]));
    expect(apiPost).not.toHaveBeenCalled();
  });

  // Undo replays the same `photo_paths` endpoints the batch writes use, and the
  // server caps that field at BATCH_PATHS_PER_REQUEST: an unchunked replay of a
  // large snapshot 422s and the whole undo reports as failed. The gallery's own
  // caller stays under the cap (UNDO_MAX_PHOTOS = 500), but the store is public.
  describe('a snapshot larger than the server cap', () => {
    const paths = Array.from({ length: 1500 }, (_, i) => `/p${i}.jpg`);

    const sentTo = (endpoint: string) =>
      apiPost.mock.calls
        .filter(c => c[0] === endpoint)
        .map(c => (c[1] as { photo_paths: string[] }).photo_paths);

    it('splits a re-reject into one request per chunk, none over the cap', async () => {
      store.photos.set(paths.map(path => makePhoto({ path, is_rejected: false })));

      await store.restoreSnapshot(new Map(
        paths.map(path => [path, { is_favorite: false, is_rejected: true, star_rating: null }]),
      ));

      const chunks = sentTo('/photos/batch_review');
      expect(chunks.map(c => c.length)).toEqual([1000, 500]);
      expect(chunks.flat()).toEqual(paths);
    });

    it('splits the favorite and rating replays too, carrying the rating on each', async () => {
      store.photos.set(paths.map(path =>
        makePhoto({ path, is_rejected: false, is_favorite: false, star_rating: null })));

      await store.restoreSnapshot(new Map(
        paths.map(path => [path, { is_favorite: true, is_rejected: false, star_rating: 4 }]),
      ));

      expect(sentTo('/photos/batch_favorite').map(c => c.length)).toEqual([1000, 500]);
      expect(sentTo('/photos/batch_rating').map(c => c.length)).toEqual([1000, 500]);
      expect(apiPost.mock.calls
        .filter(c => c[0] === '/photos/batch_rating')
        .every(c => (c[1] as { rating: number }).rating === 4)).toBe(true);
    });
  });

  it('reverts only the photos whose restore call succeeded, and notifies on partial failure', async () => {
    store.photos.set([
      makePhoto({ path: '/a.jpg', is_rejected: true, is_favorite: false, star_rating: null }),
      makePhoto({ path: '/b.jpg', is_rejected: true, is_favorite: false, star_rating: null }),
    ]);
    const snap = new Map([
      ['/a.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
      ['/b.jpg', { is_favorite: false, is_rejected: false, star_rating: null }],
    ]);
    // /b.jpg's inverse call fails server-side; /a.jpg's succeeds.
    apiPost.mockImplementation((url: string, body: { photo_path?: string }) => {
      if (url === '/photo/toggle_rejected' && body.photo_path === '/b.jpg') {
        return throwError(() => new Error('boom'));
      }
      return of({});
    });

    await store.restoreSnapshot(snap);

    // /a.jpg's call succeeded server-side, so local state is reverted to match.
    expect(store.photos().find(p => p.path === '/a.jpg')!.is_rejected).toBe(false);
    // /b.jpg's call failed server-side (still rejected there), so local state must
    // NOT be blindly reverted to "unrejected" -- that would disagree with the server.
    expect(store.photos().find(p => p.path === '/b.jpg')!.is_rejected).toBe(true);
    expect(snackOpen).toHaveBeenCalled();
  });
  it.each(['semanticQuery', 'similar_to'] as const)('activating %s clears review filtering through both update APIs', async key => {
    vi.spyOn(store, 'loadPhotos').mockResolvedValue();
    const value = key === 'semanticQuery' ? 'sunset' : '/a.jpg';
    for (const bulk of [false, true]) {
      store.filters.set({ ...DEFAULT_FILTERS, review_status: 'undecided', camera: 'Canon' });
      if (bulk) await store.updateFilters({ [key]: value });
      else await store.updateFilter(key, value);
      expect(store.filters()).toMatchObject({ review_status: '', [key]: value, camera: 'Canon' });
      const restored = applyQueryParams(DEFAULT_FILTERS, buildSyncParams(store.filters(), undefined));
      expect(restored).toMatchObject({ review_status: '', [key]: value });
    }
  });

  it('explicit bulk review activation wins over ranked modes and uses the review ordering', async () => {
    vi.spyOn(store, 'loadPhotos').mockResolvedValue();
    await store.updateFilters({ review_status: 'undecided', similar_to: '/a.jpg', semanticQuery: 'sunset', camera: 'Canon' });
    expect(store.filters()).toMatchObject({ review_status: 'undecided', similar_to: '', semanticQuery: '', sort: 'date_taken', sort_direction: 'ASC', camera: 'Canon' });
    const restored = applyQueryParams(DEFAULT_FILTERS, buildSyncParams(store.filters(), undefined));
    expect(restored).toMatchObject({ review_status: 'undecided', similar_to: '', semanticQuery: '' });
  });

});

describe('GalleryStore smart-album auto-save', () => {
  let store: GalleryStore;
  let albumUpdate: Mock;
  let snackOpen: Mock;

  const smartAlbum: Album = {
    id: 7,
    name: 'Keepers',
    description: '',
    cover_photo_path: null,
    first_photo_path: null,
    is_smart: true,
    is_shared: false,
    smart_filter_json: '{}',
    scoring_context: null,
    photo_count: 3,
    created_at: '',
    updated_at: '',
  };

  beforeEach(() => {
    albumUpdate = vi.fn(() => of({}));
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: { get: vi.fn(() => of({})), post: vi.fn(() => of({})) } },
        { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { identity: () => '0|', isEdition: vi.fn(() => true) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: albumUpdate } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: AssistantChangesService, useValue: { batch$: NEVER } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.currentAlbum.set(smartAlbum);
  });

  async function changeFiltersAndSettle(): Promise<void> {
    store.filters.set({ ...DEFAULT_FILTERS, camera: 'Canon' });
    TestBed.tick();
    await vi.advanceTimersByTimeAsync(500);
  }

  it('persists the filters without a snackbar when the write succeeds', async () => {
    vi.useFakeTimers();
    try {
      await changeFiltersAndSettle();
    } finally {
      vi.useRealTimers();
    }

    expect(albumUpdate).toHaveBeenCalledTimes(1);
    const [albumId, body] = albumUpdate.mock.calls[0];
    expect(albumId).toBe(7);
    expect(JSON.parse(body.smart_filter_json)).toMatchObject({ camera: 'Canon' });
    expect(snackOpen).not.toHaveBeenCalled();
  });

  it('keeps the saved smart-album decision criterion during a temporary review queue', async () => {
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse()));
    store.currentAlbum.set({ ...smartAlbum, smart_filter_json: JSON.stringify({ camera: 'Canon' }) });
    store.filters.set({ ...DEFAULT_FILTERS, camera: 'Canon' });
    vi.useFakeTimers();
    try {
      await store.startReviewQueue();
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
    } finally { vi.useRealTimers(); }
    expect(albumUpdate).not.toHaveBeenCalled();
    expect(get).toHaveBeenCalledWith('/photos/review_progress', expect.not.objectContaining({ scope_review_status: 'undecided' }));
  });

  it('preserves temporary queue mode across reload without changing the saved smart criterion', async () => {
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockImplementation((url: string) => of(url === '/config' ? makeConfig() : makePhotosResponse()));
    TestBed.inject(ActivatedRoute).snapshot.queryParams = { review_queue: '1', review_status: 'undecided' };
    store.currentAlbum.set({ ...smartAlbum, smart_filter_json: JSON.stringify({ camera: 'Canon' }) });
    vi.useFakeTimers();
    try {
      await store.loadConfig();
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
    } finally { vi.useRealTimers(); }
    expect(store.filters().review_status).toBe('undecided');
    expect(albumUpdate).not.toHaveBeenCalled();
  });

  it('uses current saved album content criteria on resume and saves only a later intentional edit', async () => {
    localStorage.removeItem('facet_review_queues_v1');
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse()));
    store.currentAlbum.set({ ...smartAlbum, smart_filter_json: JSON.stringify({ camera: 'Camera A' }) });
    await store.updateFilters({ album_id: '7', camera: 'Camera A', review_status: 'undecided' });
    store.currentAlbum.set(null);
    store.filters.set({ ...DEFAULT_FILTERS, camera: 'Unrelated' });
    TestBed.inject(AlbumService).get = vi.fn(() => of({ ...smartAlbum, smart_filter_json: JSON.stringify({ camera: 'Camera B', sort: 'filename', sort_direction: 'DESC' }) }));
    vi.useFakeTimers();
    try {
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
      albumUpdate.mockClear();
      await store.continueReview();
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
      expect(store.filters()).toMatchObject({ camera: 'Camera B', review_status: 'undecided', sort: 'filename' });
      expect(albumUpdate).not.toHaveBeenCalled();
      await store.updateFilter('camera', 'Camera C');
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
      expect(JSON.parse(albumUpdate.mock.calls.at(-1)![1].smart_filter_json).camera).toBe('Camera C');
    } finally { vi.useRealTimers(); }
  });

  it('saves a later sidebar edit without leaking the temporary queue sort or status', async () => {
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse()));
    store.currentAlbum.set({ ...smartAlbum, smart_filter_json: JSON.stringify({ camera: 'Camera B', sort: 'filename', sort_direction: 'DESC' }) });
    store.filters.set({ ...DEFAULT_FILTERS, camera: 'Camera B', sort: 'filename', sort_direction: 'DESC' });
    vi.useFakeTimers();
    try {
      await store.startReviewQueue();
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
      expect(albumUpdate).not.toHaveBeenCalled();
      await store.updateFilter('camera', 'Camera C');
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
      const saved = JSON.parse(albumUpdate.mock.calls.at(-1)![1].smart_filter_json);
      expect(saved).toMatchObject({ camera: 'Camera C', sort: 'filename', sort_direction: 'DESC' });
      expect(saved.review_status).toBeUndefined();
    } finally { vi.useRealTimers(); }
  });

  it.each(['single', 'grouped'])('keeps display-only %s edits in the same temporary album query and selection', async mode => {
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse({ has_more: true })));
    store.currentAlbum.set({ ...smartAlbum, smart_filter_json: JSON.stringify({ camera: 'Camera B', sort: 'filename', sort_direction: 'DESC' }) });
    store.filters.set({ ...DEFAULT_FILTERS, camera: 'Camera B', sort: 'filename', sort_direction: 'DESC' });
    vi.useFakeTimers();
    try {
      await store.startReviewQueue();
      store.filters.update(f => ({ ...f, page: 2 }));
      store.selectWholeView();
      const query = store.filterKey();
      const rows = store.photos();
      get.mockClear();
      if (mode === 'grouped') await store.updateFilters({ hide_details: false, tooltip_mode: 'off', panel_activation: 'click' });
      else {
        await store.updateFilter('hide_details', false);
        await store.updateFilter('tooltip_mode', 'off');
        await store.updateFilter('panel_activation', 'click');
      }
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
      expect(store.filters()).toMatchObject({ page: 2, review_status: 'undecided', sort: 'date_taken', sort_direction: 'ASC', hide_details: false, tooltip_mode: 'off', panel_activation: 'click' });
      expect(store.filterKey()).toBe(query);
      expect(store.photos()).toBe(rows);
      expect(store.viewScopeSelected()).toBe(true);
      expect(get.mock.calls.filter(([url]) => url === '/photos')).toHaveLength(0);
      expect(albumUpdate).not.toHaveBeenCalled();
      expect(TestBed.inject(Router).navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: expect.objectContaining({ review_status: 'undecided', sort: 'date_taken', sort_direction: 'ASC', review_queue: '1' }) }));
      await store.nextPage();
      expect(get).toHaveBeenLastCalledWith('/photos', expect.objectContaining({ page: 3, review_status: 'undecided', sort: 'date_taken', sort_direction: 'ASC' }));
    } finally { vi.useRealTimers(); }
  });

  it.each(['single', 'grouped'])('reverses queue order through a %s sort edit without leaving Needs review', async mode => {
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse()));
    store.currentAlbum.set({ ...smartAlbum, smart_filter_json: JSON.stringify({ camera: 'Camera B', sort: 'filename', sort_direction: 'DESC' }) });
    store.filters.set({ ...DEFAULT_FILTERS, camera: 'Camera B', sort: 'filename', sort_direction: 'DESC' });
    vi.useFakeTimers();
    try {
      await store.startReviewQueue();
      if (mode === 'grouped') await store.updateFilters({ sort_direction: 'DESC' });
      else await store.updateFilter('sort_direction', 'DESC');
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
      expect(store.filters()).toMatchObject({ review_status: 'undecided', sort: 'date_taken', sort_direction: 'DESC' });
      expect(get).toHaveBeenCalledWith('/photos', expect.objectContaining({ review_status: 'undecided', sort: 'date_taken', sort_direction: 'DESC' }));
      expect(albumUpdate).not.toHaveBeenCalled();
    } finally { vi.useRealTimers(); }
  });

  it('still saves an intentional review-status edit from the existing filter control', async () => {
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse()));
    vi.useFakeTimers();
    try {
      await store.updateFilter('review_status', 'kept');
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
    } finally { vi.useRealTimers(); }
    expect(JSON.parse(albumUpdate.mock.calls.at(-1)![1].smart_filter_json).review_status).toBe('kept');
  });

  it('reports a rejected write instead of letting it pass for a save', async () => {
    albumUpdate.mockReturnValue(throwError(() => new Error('403')));

    vi.useFakeTimers();
    try {
      await changeFiltersAndSettle();
    } finally {
      vi.useRealTimers();
    }

    expect(snackOpen).toHaveBeenCalledWith('albums.smart_save_failed', '', { duration: 5000 });
  });
  it('selecting no geolocation clears radius and ranked modes, keeps ordinary filters, and reloads page one', async () => {
    const get = TestBed.inject(ApiService).get as Mock;
    get.mockReturnValue(of(makePhotosResponse()));
    store.filters.update(f => ({ ...f, page: 3, gps_lat: '0', gps_lng: '0', gps_radius_km: '5', similar_to: '/a.jpg', semanticQuery: 'sunset', camera: 'Canon' }));
    await store.updateFilter('no_gps', '1');
    expect(store.filters()).toMatchObject({ no_gps: '1', page: 1, gps_lat: '', gps_lng: '', gps_radius_km: '', similar_to: '', semanticQuery: '', camera: 'Canon' });
    expect(get).toHaveBeenCalledWith('/photos', expect.objectContaining({ no_gps: '1', camera: 'Canon' }));
  });

  it.each(['semanticQuery', 'similar_to', 'gps_lat', 'gps_lng', 'gps_radius_km'] as const)('activating %s clears missing-location filtering through either update entry point', async key => {
    const value = key === 'semanticQuery' ? 'sunset' : key === 'similar_to' ? '/a.jpg' : '0';
    vi.spyOn(store, 'loadPhotos').mockResolvedValue();
    for (const bulk of [false, true]) {
      store.filters.set({ ...DEFAULT_FILTERS, no_gps: '1', camera: 'Canon' });
      if (bulk) await store.updateFilters({ [key]: value });
      else await store.updateFilter(key, value);
      expect(store.filters().no_gps).toBe('');
      expect(store.filters()[key]).toBe(value);
      const restored = applyQueryParams(DEFAULT_FILTERS, buildSyncParams(store.filters(), undefined));
      expect(restored).toMatchObject({ no_gps: '', [key]: value, camera: 'Canon' });
    }
  });

  it('enabling missing-location filtering through a multi-filter update clears incompatible modes', async () => {
    vi.spyOn(store, 'loadPhotos').mockResolvedValue();
    store.filters.set({ ...DEFAULT_FILTERS, gps_lat: '0', gps_lng: '0', gps_radius_km: '5', similar_to: '/a.jpg', semanticQuery: 'sunset' });
    await store.updateFilters({ no_gps: '1' });
    expect(store.filters()).toMatchObject({ no_gps: '1', gps_lat: '', gps_lng: '', gps_radius_km: '', similar_to: '', semanticQuery: '' });
  });

  it.each([false, true])('keeps review and missing-location filters together, then clears both for ranked search (bulk=%s)', async bulk => {
    vi.spyOn(store, 'loadPhotos').mockResolvedValue();
    if (bulk) await store.updateFilters({ review_status: 'kept', no_gps: '1' });
    else {
      await store.updateFilter('review_status', 'kept');
      await store.updateFilter('no_gps', '1');
    }
    expect(store.filters()).toMatchObject({ review_status: 'kept', no_gps: '1' });
    expect(applyQueryParams(DEFAULT_FILTERS, buildSyncParams(store.filters(), undefined)))
      .toMatchObject({ review_status: 'kept', no_gps: '1' });
    if (bulk) await store.updateFilters({ semanticQuery: 'sunset' });
    else await store.updateFilter('semanticQuery', 'sunset');
    expect(store.filters()).toMatchObject({ review_status: '', no_gps: '', semanticQuery: 'sunset' });
  });

  it('persists missing-location filtering in smart albums', async () => {
    vi.useFakeTimers();
    try {
      store.filters.set({ ...DEFAULT_FILTERS, no_gps: '1', camera: 'Canon' });
      TestBed.tick();
      await vi.advanceTimersByTimeAsync(500);
    } finally { vi.useRealTimers(); }
    expect(JSON.parse(albumUpdate.mock.calls[0][1].smart_filter_json)).toMatchObject({ no_gps: '1', camera: 'Canon' });
  });

});
