import { createEnvironmentInjector, EnvironmentInjector, signal, ChangeDetectorRef, runInInjectionContext } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ActivatedRoute, Event as RouterEvent, NavigationStart, NavigationCancel, NavigationError, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { firstValueFrom, of, Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { GalleryStore, PhotosResponse } from './gallery.store';
import { GalleryComponent } from './gallery.component';
import { CardActionsService } from './card-actions.service';
import { ScanService } from '../../core/services/scan.service';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { UndoService } from '../../core/services/undo.service';
import { SequenceOverrideService } from '../../core/services/sequence-override.service';
import { PageHelpService } from '../../core/services/page-help.service';

const EMPTY_PAGE: PhotosResponse = {
  photos: [], total: 0, page: 1, per_page: 64, total_pages: 1, has_more: false,
};
const COUNTS = { total: 10, undecided: 8, kept: 1, rejected: 1 };

describe('GalleryStore read cancellation with HttpClient', () => {
  let store: GalleryStore;
  let owner: EnvironmentInjector;
  let destroyed: boolean;
  let http: HttpTestingController;
  let identity: ReturnType<typeof signal<string>>;
  let events: Subject<RouterEvent>;
  let snack: ReturnType<typeof vi.fn>;
  let outlet: { attachEvents: Subject<unknown>; detachEvents: Subject<unknown> };

  function destroyStore(): void {
    owner.destroy();
    destroyed = true;
  }

  function request(url: string): TestRequest {
    return http.expectOne(r => r.url === `/api${url}`);
  }

  beforeEach(() => {
    identity = signal('alice');
    events = new Subject<RouterEvent>();
    snack = vi.fn();
    destroyed = false;
    outlet = { attachEvents: new Subject(), detachEvents: new Subject() };
    TestBed.configureTestingModule({ providers: [
      ApiService, provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: AuthService, useValue: { status: signal({ user_id: 'alice', edition_authenticated: true }), identity, session: signal('alice'), isEdition: vi.fn(() => false) } },
      { provide: Router, useValue: { url: '/', events, navigate: vi.fn(), currentNavigation: () => null } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {}, paramMap: { get: () => null } } } },
      { provide: RouterOutlet, useValue: outlet },
      { provide: ChangeDetectorRef, useValue: { detectChanges: vi.fn() } },
      { provide: CardActionsService, useValue: { config: signal({}) } },
      { provide: ScanService, useValue: { canLaunch: signal(false) } },
      { provide: MatDialog, useValue: {} }, { provide: MatBottomSheet, useValue: {} },
      { provide: LiveAnnouncer, useValue: { announce: vi.fn() } },
      { provide: PhotoActionsService, useValue: {} }, { provide: UndoService, useValue: {} },
      { provide: SequenceOverrideService, useValue: {} },
      { provide: PageHelpService, useValue: { setDescription: vi.fn() } },
      { provide: AlbumService, useValue: { update: vi.fn(() => of({})) } },
      { provide: I18nService, useValue: { t: (key: string) => key } },
      { provide: MatSnackBar, useValue: { open: snack } },
      { provide: AssistantChangesService, useValue: { batch$: new Subject() } },
      { provide: UserActivityJournal, useValue: { record: vi.fn(), recordFilters: vi.fn() } },
    ] });
    http = TestBed.inject(HttpTestingController);
    owner = createEnvironmentInjector([GalleryStore], TestBed.inject(EnvironmentInjector));
    store = owner.get(GalleryStore);
    TestBed.tick();
  });

  afterEach(() => {
    if (!destroyed) destroyStore();
    http.verify();
  });

  it.each(['parked', 'cancelled'] as const)('defers a pending range filter through %s navigation and resumes page one', async outcome => {
    vi.useFakeTimers();
    try {
      const initial = store.loadPhotos();
      request('/photos').flush(EMPTY_PAGE);
      request('/photos/review_progress').flush(COUNTS);
      await initial;
      store.filters.update(filters => ({ ...filters, page: 3 }));
      store.updateFilterDebounced('min_score', '7');
      events.next(new NavigationStart(51, '/photo?path=a'));
      if (outcome === 'parked') store.parkListingReads();
      await vi.advanceTimersByTimeAsync(300);
      const background = http.match(r => r.url === '/api/photos' || r.url === '/api/photos/review_progress');
      for (const read of background) read.flush(read.request.url.endsWith('/photos') ? EMPTY_PAGE : COUNTS);
      expect(background).toHaveLength(0);
      let resumed: Promise<void> | undefined;
      if (outcome === 'parked') resumed = store.resumeListingReads();
      else events.next(new NavigationCancel(51, '/photo?path=a', 'guard refused'));
      await Promise.resolve();
      const page = request('/photos');
      expect(page.request.params.get('min_score')).toBe('7');
      expect(page.request.params.get('page')).toBe('1');
      page.flush(EMPTY_PAGE);
      request('/photos/review_progress').flush(COUNTS);
      await resumed;
      await vi.advanceTimersByTimeAsync(300);
      http.expectNone(r => r.url === '/api/photos');
    } finally { vi.useRealTimers(); }
  });

  it.each(['pin', 'replacement', 'owner', 'token', 'destroy'] as const)('keeps deferred range intent scoped through %s', async outcome => {
    vi.useFakeTimers();
    try {
      const initial = outcome === 'pin' ? store.showPaths(['/pinned.jpg']) : store.loadPhotos();
      if (outcome === 'pin') request('/photos/by_paths').flush({ photos: [makePhoto({ path: '/pinned.jpg' })] });
      else {
        request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/old.jpg' })], total: 1 });
        request('/photos/review_progress').flush(COUNTS);
      }
      await initial;
      http.match(r => r.url === '/api/photos/keeper_hints').forEach(read => read.flush({}));
      const rows = store.photos();
      store.updateFilterDebounced('min_score', '7');
      store.parkListingReads();
      expect(store.photos()).toBe(rows);
      if (outcome === 'owner') { identity.set('bob'); TestBed.tick(); }
      if (outcome === 'token') Object.defineProperty(TestBed.inject(AuthService), 'token', { value: 'rotated', configurable: true });
      if (outcome === 'destroy') destroyStore();
      if (outcome === 'replacement') {
        const replacement = store.showPaths(['/replacement.jpg']);
        request('/photos/by_paths').flush({ photos: [makePhoto({ path: '/replacement.jpg' })] });
        await replacement;
      }
      await vi.advanceTimersByTimeAsync(300);
      http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/review_progress');
      if (outcome === 'pin') {
        const resumed = store.resumeListingReads();
        const page = request('/photos');
        expect(page.request.params.get('min_score')).toBe('7');
        expect(page.request.params.get('page')).toBe('1');
        expect(store.pinnedPaths()).toBeNull();
        page.flush(EMPTY_PAGE); request('/photos/review_progress').flush(COUNTS);
        await resumed;
      } else if (outcome !== 'destroy') {
        await store.resumeListingReads();
        http.expectNone(r => r.url === '/api/photos');
      }
      http.match(r => r.url === '/api/photos/keeper_hints').forEach(read => read.flush({}));
      if (outcome === 'replacement') expect(store.pinnedPaths()).toEqual(['/replacement.jpg']);
    } finally { vi.useRealTimers(); }
  });

  it('bounds a burst of 30 filter changes to one active page and one progress request', async () => {
    const pages: TestRequest[] = [];
    const progress: TestRequest[] = [];
    const loads: Promise<void>[] = [];
    const activePages: number[] = [];
    const activeProgress: number[] = [];
    for (let i = 0; i < 30; i++) {
      loads.push(store.updateFilter('camera', `Camera ${i}`));
      pages.push(request('/photos'));
      progress.push(request('/photos/review_progress'));
      activePages.push(pages.filter(r => !r.cancelled).length);
      activeProgress.push(progress.filter(r => !r.cancelled).length);
    }
    expect(activePages).toEqual(Array(30).fill(1));
    expect(activeProgress).toEqual(Array(30).fill(1));
    expect(pages.slice(0, -1).every(r => r.cancelled)).toBe(true);
    expect(progress.slice(0, -1).every(r => r.cancelled)).toBe(true);
    expect(pages[29].request.params.get('camera')).toBe('Camera 29');
    pages[29].flush(EMPTY_PAGE);
    progress[29].flush(COUNTS);
    await Promise.all(loads);
    expect(store.reviewProgress()).toEqual(COUNTS);
    expect(store.loadError()).toBe(false);
    expect(store.loading()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['pinned', 'similar'] as const)('cancels old progress when a %s view needs no aggregate request', async mode => {
    const oldLoad = store.loadPhotos();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    const newLoad = mode === 'pinned' ? store.showPaths(['/pin.jpg']) : store.updateFilter('similar_to', '/seed.jpg');
    const next = request(mode === 'pinned' ? '/photos/by_paths' : `/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    http.expectNone(r => r.url === '/api/photos/review_progress');
    next.flush(mode === 'pinned' ? { photos: [], total: 0, missing: [] } : { similar: [], total: 0, has_more: false });
    await Promise.all([oldLoad, newLoad]);
    expect(store.reviewProgress()).toBeNull();
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['pinned', 'similar'] as const)('cancels the obsolete %s page read', async mode => {
    const oldLoad = mode === 'pinned' ? store.showPaths(['/pin.jpg']) : store.updateFilter('similar_to', '/seed.jpg');
    const oldPage = request(mode === 'pinned' ? '/photos/by_paths' : `/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    const nextLoad = store.updateFilter('similar_to', '');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldPage.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([oldLoad, nextLoad]);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['identity', 'navigation', 'destroy'] as const)('cancels reads on %s without a UI error', async change => {
    const loading = store.loadPhotos();
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    if (change === 'identity') { identity.set('bob'); TestBed.tick(); }
    else if (change === 'navigation') events.next(new NavigationStart(1, '/stats'));
    else destroyStore();
    expect(page.cancelled).toBe(true);
    expect(progress.cancelled).toBe(true);
    await loading;
    expect(store.loading()).toBe(false);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it('keeps a fresh new-principal read when the identity effect runs after it starts', async () => {
    const oldLoad = store.loadPhotos();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    identity.set('bob');
    const nextLoad = store.loadPhotos();
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    TestBed.tick();
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    expect(page.cancelled).toBe(false);
    expect(progress.cancelled).toBe(false);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([oldLoad, nextLoad]);
    expect(store.reviewProgress()).toEqual(COUNTS);
    expect(store.loadError()).toBe(false);
  });

  it('keeps the first page and progress read when initialization effects first run', async () => {
    destroyStore();
    owner = createEnvironmentInjector([GalleryStore], TestBed.inject(EnvironmentInjector));
    destroyed = false;
    store = owner.get(GalleryStore);
    const loading = store.loadPhotos();
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    TestBed.tick();
    expect(page.cancelled).toBe(false);
    expect(progress.cancelled).toBe(false);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await loading;
    expect(store.reviewProgress()).toEqual(COUNTS);
  });

  it.each(['/?camera=Canon', '/#gallery'])('keeps a new read across same-path URL synchronization to %s', async url => {
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    events.next(new NavigationStart(1, url));
    TestBed.tick();
    expect(page.cancelled).toBe(false);
    expect(progress.cancelled).toBe(false);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await loading;
    expect(store.reviewProgress()).toEqual(COUNTS);
  });

  it.each(['ordinary', 'similar'] as const)('cancels an obsolete %s pagination request without reverting the new page or showing an error', async mode => {
    store.photos.set([makePhoto({ path: '/old.jpg' })]);
    store.hasMore.set(true);
    if (mode === 'similar') store.filters.update(f => ({ ...f, similar_to: '/seed.jpg' }));
    const paging = store.nextPage();
    const oldPage = request(mode === 'similar' ? `/similar_photos/${encodeURIComponent('/seed.jpg')}` : '/photos');
    const loading = store.updateFilters({ camera: 'Canon', similar_to: '' });
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldPage.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([paging, loading]);
    expect(store.filters().page).toBe(1);
    expect(store.photos()).toEqual([]);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each([['/', 'cancel'], ['/', 'error'], ['/album/2', 'cancel'], ['/album/2', 'error']] as const)('recovers a cancelled initial listing from %s when navigation ends with %s', async (origin, ending) => {
    (TestBed.inject(Router) as unknown as { url: string }).url = origin;
    const loading = store.loadPhotos();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    events.next(new NavigationStart(1, '/stats'));
    events.next(ending === 'cancel' ? new NavigationCancel(1, '/stats', 'guard refused')
      : new NavigationError(1, '/stats', new Error('route failed')));
    const progress = request('/photos/review_progress');
    await Promise.resolve();
    const page = request('/photos');
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    page.flush({ ...EMPTY_PAGE, total: 1, photos: [makePhoto({ path: '/restored.jpg' })] });
    progress.flush(COUNTS);
    await loading;
    await Promise.resolve();
    request('/photos/keeper_hints').flush({});
    expect(store.photos().map(p => p.path)).toEqual(['/restored.jpg']);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it('resumes the real store through its own gallery outlet attach after photo navigation and Back', async () => {
    const gallery = runInInjectionContext(owner, () => new GalleryComponent());
    vi.spyOn(store, 'loadTypeCounts').mockResolvedValue();
    vi.spyOn(store, 'loadFilterOptions').mockResolvedValue();
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, has_more: true, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    store.selectedPaths.set(new Set(['/a.jpg']));
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    outlet.detachEvents.next(gallery);
    await store.refreshPaths(['/a.jpg']);
    http.expectNone(r => r.url === '/api/photos');
    outlet.attachEvents.next({});
    http.expectNone(r => r.url === '/api/photos/review_progress');
    outlet.attachEvents.next(gallery);
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    request('/photos/by_paths').flush({ photos: [makePhoto({ path: '/a.jpg', is_favorite: true })] });
    await Promise.resolve();
    await Promise.resolve();
    expect(store.selectedPaths()).toEqual(new Set(['/a.jpg']));
    await vi.waitFor(() => expect(store.photos()[0].is_favorite).toBe(true));
    const paging = store.nextPage();
    request('/photos').flush({ ...EMPTY_PAGE, page: 2 });
    await paging;
    expect(store.filters().page).toBe(2);
  });

  it.each([false, true])('restores interrupted similarity pages on return (pagination=%s)', async pagination => {
    const firstLoad = store.updateFilter('similar_to', '/seed.jpg');
    const first = request(`/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    let interrupted: Promise<void> = firstLoad;
    if (pagination) {
      first.flush({ similar: [makePhoto({ path: '/first.jpg' })], total: 2, has_more: true });
      await firstLoad;
      interrupted = store.nextPage();
      request(`/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    }
    store.selectedPaths.set(new Set(['/first.jpg']));
    events.next(new NavigationStart(1, '/photo?path=/first.jpg'));
    store.parkListingReads();
    const resuming = store.resumeListingReads();
    const page = request(`/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    expect(page.request.params.get('offset')).toBe('0');
    if (pagination) {
      // The returning viewport can ask for another page before recovery finishes.
      void store.nextPage();
      expect(store.filters().page).toBe(2);
      http.expectNone(r => r.url.includes('/similar_photos/') && r.params.get('offset') === '128');
    }
    page.flush({ similar: [makePhoto({ path: '/first.jpg' })], total: 2, has_more: pagination });
    if (pagination) {
      await Promise.resolve();
      const tail = request(`/similar_photos/${encodeURIComponent('/seed.jpg')}`);
      expect(tail.request.params.get('offset')).toBe('64');
      tail.flush({ similar: [makePhoto({ path: '/second.jpg' })], total: 2, has_more: false });
    }
    await Promise.all([interrupted, resuming]);
    expect(store.photos().map(p => p.path)).toEqual(pagination ? ['/first.jpg', '/second.jpg'] : ['/first.jpg']);
    expect(store.selectedPaths()).toEqual(new Set(['/first.jpg']));
    expect(store.loadError()).toBe(false);
  });

  it.each(['unchanged', 'hint-pending', 'rating'] as const)('does not refetch pages or counts on Back after %s', async reason => {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, has_more: true, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    const hints = request('/photos/keeper_hints');
    if (reason !== 'hint-pending') hints.flush({});
    const writing = reason === 'rating' ? store.setRating('/a.jpg', 4) : Promise.resolve();
    const rating = reason === 'rating' ? request('/photo/set_rating') : null;
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/a.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/a.jpg', '/photo?path=/a.jpg'));
    if (rating) rating.flush({ success: true });
    await writing;
    if (reason === 'hint-pending') expect(hints.cancelled).toBe(true);
    await store.resumeListingReads();
    if (reason === 'hint-pending') request('/photos/keeper_hints').flush({});
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/review_progress');
    if (reason === 'rating') expect(store.photos()[0].star_rating).toBe(4);
  });

  it('retries interrupted similarity pages after a failed foreground rebuild instead of skipping a page', async () => {
    const url = `/similar_photos/${encodeURIComponent('/seed.jpg')}`;
    const initial = store.updateFilter('similar_to', '/seed.jpg');
    request(url).flush({ similar: [makePhoto({ path: '/first.jpg' })], total: 3, has_more: true });
    await initial;
    const interrupted = store.nextPage();
    const oldTail = request(url);
    events.next(new NavigationStart(1, '/photo?path=/first.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/first.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/first.jpg', '/photo?path=/first.jpg'));
    expect(oldTail.cancelled).toBe(true);
    const failed = store.nextPage(undefined, { whileParked: true });
    request(url).flush({}, { status: 500, statusText: 'failed' });
    await Promise.all([interrupted, failed]);
    const retry = store.nextPage(undefined, { whileParked: true });
    const first = request(url);
    expect(first.request.params.get('offset')).toBe('0');
    first.flush({ similar: [makePhoto({ path: '/first.jpg' })], total: 3, has_more: true });
    await Promise.resolve();
    const tail = request(url);
    expect(tail.request.params.get('offset')).toBe('64');
    tail.flush({ similar: [makePhoto({ path: '/second.jpg' })], total: 3, has_more: true });
    await retry;
    expect(store.photos().map(photo => photo.path)).toEqual(['/first.jpg', '/second.jpg']);
    expect(store.loadError()).toBe(false);
  });

  it.each(['success', 'failure', 'navigation'] as const)('recovers an interrupted ordinary listing from a photo without overlapping requests (%s)', async outcome => {
    const initial = store.loadPhotos();
    const obsolete = request('/photos');
    request('/photos/review_progress');
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/a.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/a.jpg', '/photo?path=/a.jpg'));
    expect(obsolete.cancelled).toBe(true);
    const recovering = store.nextPage(undefined, { whileParked: true });
    const page = request('/photos');
    await store.nextPage(undefined, { whileParked: true });
    http.expectNone(r => r.url === '/api/photos');
    if (outcome === 'navigation') {
      events.next(new NavigationStart(2, '/stats'));
      expect(page.cancelled).toBe(true);
    } else if (outcome === 'failure') page.flush({}, { status: 500, statusText: 'failed' });
    else page.flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/a.jpg' })] });
    await Promise.all([initial, recovering]);
    if (outcome === 'success') request('/photos/keeper_hints').flush({});
    if (outcome === 'failure') {
      const retry = store.nextPage(undefined, { whileParked: true });
      request('/photos').flush(EMPTY_PAGE);
      await retry;
    }
    expect(store.loading()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['ordinary', 'similar'] as const)('recovers an interrupted %s review refill even when all current rows remain loaded', async mode => {
    store.filters.update(f => ({ ...f, review_status: 'undecided', ...(mode === 'similar' ? { similar_to: '/seed.jpg' } : {}) }));
    const loaded = Array.from({ length: 64 }, (_, i) => makePhoto({ path: `/p${i}.jpg` }));
    store.photos.set(loaded);
    store.hasMore.set(true);
    const repairing = store.refreshReviewResults();
    if (mode === 'ordinary') request('/photos/review_progress');
    const obsolete = request('/photos');
    events.next(new NavigationStart(1, '/photo?path=/p63.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p63.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/p63.jpg', '/photo?path=/p63.jpg'));
    expect(obsolete.cancelled).toBe(true);
    const recovering = store.nextPage(undefined, { whileParked: true });
    const tail = request(mode === 'similar' ? `/similar_photos/${encodeURIComponent('/seed.jpg')}` : '/photos');
    expect(tail.request.params.get(mode === 'similar' ? 'offset' : 'page')).toBe(mode === 'similar' ? '0' : '1');
    tail.flush(mode === 'similar' ? { similar: loaded, total: 64, has_more: false } : { ...EMPTY_PAGE, photos: loaded, total: 64 });
    await Promise.all([repairing, recovering]);
    if (mode === 'ordinary') request('/photos/keeper_hints').flush({});
    expect(store.photos()).toHaveLength(64);
    expect(store.loading()).toBe(false);
    expect(store.loadError()).toBe(false);
  });

  it('reloads every loaded page when a grid Keep repair is interrupted before ArrowRight pages past the end', async () => {
    vi.mocked(TestBed.inject(AuthService).isEdition).mockReturnValue(true);
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/a.jpg' })], total: 300, has_more: true });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    const server = Array.from({ length: 300 }, (_, i) => makePhoto({ path: `/p${i}.jpg` }));
    store.photos.set(server.slice(0, 128));
    store.filters.update(f => ({ ...f, page: 2 }));
    const keeping = store.batchReview(['/p10.jpg'], 'kept');
    request('/photos/batch_review').flush({ count: 1 });
    let repair!: TestRequest;
    await vi.waitFor(() => { repair = request('/photos'); });
    expect(repair.request.params.get('page')).toBe('2');
    events.next(new NavigationStart(1, '/photo?path=/p127.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p127.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/p127.jpg', '/photo?path=/p127.jpg'));
    expect(repair.cancelled).toBe(true);
    expect(request('/photos/review_progress').cancelled).toBe(true);
    await keeping;
    const remaining = server.filter(photo => photo.path !== '/p10.jpg');
    const recovering = store.nextPage(undefined, { whileParked: true });
    for (let page = 1; page <= 2; page++) {
      let read!: TestRequest;
      await vi.waitFor(() => { read = request('/photos'); });
      expect(read.request.params.get('page')).toBe(String(page));
      read.flush({ ...EMPTY_PAGE, photos: remaining.slice((page - 1) * 64, page * 64), total: 299, has_more: true });
    }
    await recovering;
    request('/photos/keeper_hints').flush({});
    const paths = store.photos().map(photo => photo.path);
    expect(paths).not.toContain('/p10.jpg');
    expect(paths).toContain('/p64.jpg');
    expect(paths.indexOf('/p128.jpg')).toBe(paths.indexOf('/p127.jpg') + 1);
    const returning = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await returning;
    http.expectNone(r => r.url === '/api/photos');
  });

  it.each(['full', 'targeted'] as const)('preserves a newer %s write during foreground full recovery', async kind => {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/p0.jpg' })], total: 300, has_more: true });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    store.photos.set(Array.from({ length: 128 }, (_, i) => makePhoto({ path: `/p${i}.jpg` })));
    store.filters.update(f => ({ ...f, page: 2 }));
    const paging = store.nextPage();
    const obsolete = request('/photos');
    const deferred = store.refreshPaths(null);
    request('/photos/review_progress').flush(COUNTS);
    await deferred;
    events.next(new NavigationStart(1, '/photo?path=/p127.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p127.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/p127.jpg', '/photo?path=/p127.jpg'));
    expect(obsolete.cancelled).toBe(true);
    await paging;
    const recovering = store.nextPage(undefined, { whileParked: true });
    // The deferred full refresh must invalidate the prefix, even while pagination was loading.
    const first = request('/photos');
    expect(first.request.params.get('page')).toBe('1');
    await store.refreshPaths(kind === 'full' ? null : ['/p0.jpg']);
    first.flush({ ...EMPTY_PAGE, photos: Array.from({ length: 64 }, (_, i) => makePhoto({ path: `/p${i}.jpg` })), total: 300, has_more: true });
    for (let page = 2; page <= 3; page++) {
      let read!: TestRequest;
      await vi.waitFor(() => { read = request('/photos'); });
      expect(read.request.params.get('page')).toBe(String(page));
      read.flush({ ...EMPTY_PAGE, photos: Array.from({ length: 64 }, (_, i) => makePhoto({ path: `/p${(page - 1) * 64 + i}.jpg` })), total: 300, has_more: true });
    }
    await recovering;
    request('/photos/keeper_hints').flush({});
    const returning = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    if (kind === 'targeted') {
      let read!: TestRequest;
      await vi.waitFor(() => { read = request('/photos/by_paths'); });
      expect(read.request.body.paths).toEqual(['/p0.jpg']);
      read.flush({ photos: [makePhoto({ path: '/p0.jpg', star_rating: 5 })] });
    } else {
      for (let page = 1; page <= 3; page++) {
        let read!: TestRequest;
        await vi.waitFor(() => { read = request('/photos'); });
        expect(read.request.params.get('page')).toBe(String(page));
        read.flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: `/fresh${page}.jpg` })], total: 3 });
      }
    }
    await returning;
    if (kind === 'targeted') expect(store.photos()[0].star_rating).toBe(5);
    else {
      request('/photos/keeper_hints').flush({});
      expect(store.photos().map(photo => photo.path)).toEqual(['/fresh1.jpg', '/fresh2.jpg', '/fresh3.jpg']);
    }
  });

  it('invalidates the loaded prefix when a targeted repair is cancelled behind pagination', async () => {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/p0.jpg' })], total: 300, has_more: true });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    store.photos.set(Array.from({ length: 128 }, (_, i) => makePhoto({ path: `/p${i}.jpg` })));
    store.filters.update(f => ({ ...f, page: 2 }));
    const paging = store.nextPage();
    const obsolete = request('/photos');
    const repairing = store.refreshPaths(['/p0.jpg']);
    request('/photos/review_progress').flush(COUNTS);
    let targeted!: TestRequest;
    await vi.waitFor(() => { targeted = request('/photos/by_paths'); });
    events.next(new NavigationStart(1, '/photo?path=/p127.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p127.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/p127.jpg', '/photo?path=/p127.jpg'));
    expect(obsolete.cancelled).toBe(true);
    expect(targeted.cancelled).toBe(true);
    await Promise.all([paging, repairing]);
    const recovering = store.nextPage(undefined, { whileParked: true });
    for (let page = 1; page <= 3; page++) {
      let read!: TestRequest;
      await vi.waitFor(() => { read = request('/photos'); });
      expect(read.request.params.get('page')).toBe(String(page));
      read.flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: `/fresh${page}.jpg`, star_rating: 5 })], total: 3 });
    }
    await recovering;
    request('/photos/keeper_hints').flush({});
    expect(store.photos().map(photo => photo.path)).toEqual(['/fresh1.jpg', '/fresh2.jpg', '/fresh3.jpg']);
    const returning = store.resumeListingReads();
    await returning;
    request('/photos/keeper_hints').flush({});
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/by_paths');
  });

  async function loadAndParkThreePages(pendingHints = false): Promise<void> {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/a.jpg' })], total: 300, has_more: true });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    const hints = request('/photos/keeper_hints');
    if (!pendingHints) hints.flush({});
    store.photos.set(Array.from({ length: 192 }, (_, i) => makePhoto({ path: `/p${i}.jpg` })));
    store.filters.update(f => ({ ...f, page: 3 }));
    events.next(new NavigationStart(1, '/photo?path=/p191.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p191.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/p191.jpg', '/photo?path=/p191.jpg'));
  }

  it.each(['failed', 'cancelled'] as const)('retains claimed full-refresh debt when foreground recovery is %s', async outcome => {
    await loadAndParkThreePages();
    await store.resumeListingReads();
    const paging = store.nextPage();
    const obsolete = request('/photos');
    const deferred = store.refreshPaths(null);
    request('/photos/review_progress').flush(COUNTS);
    await deferred;
    store.parkListingReads();
    expect(obsolete.cancelled).toBe(true);
    await paging;
    await store.refreshPaths(['/p0.jpg']);
    const recovering = store.nextPage(undefined, { whileParked: true });
    const first = request('/photos');
    expect(first.request.params.get('page')).toBe('1');
    if (outcome === 'failed') first.flush({}, { status: 500, statusText: 'Failed' });
    else {
      events.next(new NavigationStart(2, '/photo?path=/p190.jpg'));
      store.parkListingReads();
      expect(first.cancelled).toBe(true);
      (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p190.jpg';
      events.next(new NavigationEnd(2, '/photo?path=/p190.jpg', '/photo?path=/p190.jpg'));
    }
    await recovering;
    const retrying = store.nextPage(undefined, { whileParked: true });
    for (let page = 1; page <= 4; page++) {
      let read!: TestRequest;
      await vi.waitFor(() => { read = request('/photos'); });
      expect(read.request.params.get('page')).toBe(String(page));
      read.flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: `/fresh${page}.jpg` })], total: 4 });
    }
    await retrying;
    request('/photos/keeper_hints').flush({});
    expect(store.photos().map(photo => photo.path)).toEqual(['/fresh1.jpg', '/fresh2.jpg', '/fresh3.jpg', '/fresh4.jpg']);
    const returning = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await returning;
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/by_paths');
  });

  it('retries cancelled advisory hints on Back without a listing or count reload', async () => {
    await loadAndParkThreePages(true);
    // The cancelled request concerned /a.jpg, which is no longer loaded.
    store.photos.set([makePhoto({ path: '/a.jpg' })]);
    await store.resumeListingReads();
    const hints = request('/photos/keeper_hints');
    expect(hints.request.body.paths).toEqual(['/a.jpg']);
    hints.flush({ '/a.jpg': { better_path: '/b.jpg' } });
    await Promise.resolve();
    expect(store.photos()[0].keeper_hint).toEqual({ better_path: '/b.jpg' });
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/review_progress');
  });

  it('drops cancelled hint debt for removed rows instead of retrying an old queue later', async () => {
    await loadAndParkThreePages(true);
    store.photos.set([makePhoto({ path: '/remaining.jpg' })]);
    await store.resumeListingReads();
    http.expectNone(r => r.url === '/api/photos/keeper_hints');
    store.parkListingReads();
    store.photos.set([makePhoto({ path: '/a.jpg' })]);
    await store.resumeListingReads();
    http.expectNone(r => r.url === '/api/photos/keeper_hints');
  });

  it('coalesces parked path refreshes into one by_paths read on Back', async () => {
    await loadAndParkThreePages();
    await store.refreshPaths(['/p0.jpg']);
    await store.refreshPaths(['/p64.jpg', '/p0.jpg']);
    const resuming = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    const rows = request('/photos/by_paths');
    expect(rows.request.body.paths).toEqual(['/p0.jpg', '/p64.jpg']);
    rows.flush({ photos: [makePhoto({ path: '/p0.jpg', star_rating: 5 }), makePhoto({ path: '/p64.jpg' })] });
    await resuming;
    http.expectNone(r => r.url === '/api/photos');
    expect(store.photos()[0].star_rating).toBe(5);
  });

  it('does not discard another parked write when Keep repairs only the tail', async () => {
    await loadAndParkThreePages();
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    await store.refreshPaths(['/p0.jpg']);
    store.patchPhoto('/p191.jpg', { is_kept: true });
    const keeping = store.refreshReviewResults(false, { whileParked: true });
    request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/tail.jpg' })], total: 299, has_more: true });
    await keeping;
    request('/photos/keeper_hints').flush({});
    const resuming = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    request('/photos/by_paths').flush({ photos: [makePhoto({ path: '/p0.jpg', star_rating: 5 })] });
    await resuming;
    expect(store.photos()[0].star_rating).toBe(5);
  });

  it.each(['ordinary', 'similar'] as const)('foreground interrupted %s pagination fetches only the missing tail', async mode => {
    const url = mode === 'similar' ? `/similar_photos/${encodeURIComponent('/seed.jpg')}` : '/photos';
    const initial = mode === 'similar' ? store.updateFilter('similar_to', '/seed.jpg') : store.loadPhotos();
    request(url).flush(mode === 'similar'
      ? { similar: Array.from({ length: 64 }, (_, i) => makePhoto({ path: `/p${i}.jpg` })), total: 200, has_more: true }
      : { ...EMPTY_PAGE, photos: Array.from({ length: 64 }, (_, i) => makePhoto({ path: `/p${i}.jpg` })), total: 200, has_more: true });
    if (mode === 'ordinary') request('/photos/review_progress').flush(COUNTS);
    await initial;
    if (mode === 'ordinary') request('/photos/keeper_hints').flush({});
    const paging = store.nextPage();
    const obsolete = request(url);
    events.next(new NavigationStart(1, '/photo?path=/p63.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p63.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/p63.jpg', '/photo?path=/p63.jpg'));
    expect(obsolete.cancelled).toBe(true);
    const recovering = store.nextPage(undefined, { whileParked: true });
    const tail = request(url);
    expect(tail.request.params.get(mode === 'similar' ? 'offset' : 'page')).toBe(mode === 'similar' ? '64' : '2');
    tail.flush(mode === 'similar' ? { similar: [makePhoto({ path: '/next.jpg' })], total: 65, has_more: false }
      : { ...EMPTY_PAGE, photos: [makePhoto({ path: '/next.jpg' })], total: 65 });
    await Promise.all([paging, recovering]);
    if (mode === 'ordinary') request('/photos/keeper_hints').flush({});
    expect(store.photos()).toHaveLength(65);
    expect(store.photos()[64].path).toBe('/next.jpg');
  });

  it('allows an explicit photo page read while other parked refreshes remain deferred', async () => {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 2, has_more: true, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/a.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/a.jpg', '/photo?path=/a.jpg'));
    const paging = store.nextPage(undefined, { whileParked: true });
    request('/photos').flush({ ...EMPTY_PAGE, total: 2, photos: [makePhoto({ path: '/b.jpg' })] });
    await paging;
    request('/photos/keeper_hints').flush({});
    expect(store.photos().map(photo => photo.path)).toEqual(['/a.jpg', '/b.jpg']);
    await store.refreshPaths(['/a.jpg']);
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/review_progress');
  });

  it('repairs confirmed Keep membership while parked without rewriting the photo URL', async () => {
    vi.mocked(TestBed.inject(AuthService).isEdition).mockReturnValue(true);
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    store.parkListingReads();
    const router = TestBed.inject(Router);
    (router as unknown as { url: string }).url = '/photo?path=/a.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/a.jpg', '/photo?path=/a.jpg'));
    const keeping = store.batchReview(['/a.jpg'], 'kept');
    request('/photos/batch_review').flush({ count: 1 });
    await keeping;
    const repairing = store.refreshReviewResults(false, { whileParked: true });
    request('/photos').flush(EMPTY_PAGE);
    await repairing;
    expect(store.photos()).toEqual([]);
    expect(router.navigate).not.toHaveBeenCalled();
    const returning = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await returning;
    http.expectNone('/api/photos');
  });

  it('recovers an attached gallery after an unknown route redirects back without outlet attach', async () => {
    const initial = store.loadPhotos();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    events.next(new NavigationStart(1, '/unknown-route'));
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    events.next(new NavigationEnd(1, '/unknown-route', '/'));
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    request('/photos').flush(EMPTY_PAGE);
    await initial;
    await Promise.resolve();
    expect(store.loading()).toBe(false);
    expect(store.loadError()).toBe(false);
  });

  it('retains Undo for a confirmed Keep that removes a photo during the parked refresh', async () => {
    vi.mocked(TestBed.inject(AuthService).isEdition).mockReturnValue(true);
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    const snapshot = new Map([['/a.jpg', { is_kept: false, is_rejected: false, is_favorite: false, star_rating: null }]]);
    const keeping = store.batchReview(['/a.jpg'], 'kept');
    const write = request('/photos/batch_review');
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    store.parkListingReads();
    write.flush({ count: 1 });
    await keeping;
    const resuming = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    request('/photos').flush(EMPTY_PAGE);
    await resuming;
    expect(store.photos()).toEqual([]);
    const undo = store.restoreSnapshot(snapshot);
    let reset!: TestRequest;
    await vi.waitFor(() => { reset = request('/photos/batch_review'); });
    expect(reset.request.body).toEqual({ photo_paths: ['/a.jpg'], decision: 'undecided' });
    reset.flush({ count: 1 });
    let restored!: TestRequest;
    await vi.waitFor(() => { restored = request('/photos'); });
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) {
      if (!progress.cancelled) progress.flush(COUNTS);
    }
    restored.flush({ ...EMPTY_PAGE, total: 1, photos: [makePhoto({ path: '/a.jpg', is_kept: false })] });
    await undo;
    request('/photos/keeper_hints').flush({});
    expect(store.photos()[0].is_kept).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['none', 'targeted', 'full'] as const)('preserves cancelled repair scope and page two after Back (queued=%s)', async queued => {
    store.filters.update(f => ({ ...f, per_page: 2 }));
    const photos = Array.from({ length: 4 }, (_, i) => makePhoto({ path: `/p${i}.jpg` }));
    const loading = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, photos: photos.slice(0, 2), total: 6, has_more: true });
    request('/photos/review_progress').flush(COUNTS);
    await loading;
    request('/photos/keeper_hints').flush({});
    const paging = store.nextPage();
    request('/photos').flush({ ...EMPTY_PAGE, photos: photos.slice(2), total: 6, has_more: true });
    await paging;
    request('/photos/keeper_hints').flush({});
    const selected = new Set(['/p2.jpg']);
    store.selectedPaths.set(selected);
    const writing = firstValueFrom(TestBed.inject(ApiService).put('/photo/gps', {
      path: '/p2.jpg', gps_latitude: 1, gps_longitude: 2,
    })).then(() => store.refreshPaths(['/p2.jpg']));
    const write = request('/photo/gps');
    expect(write.request.body.path).toBe('/p2.jpg');
    write.flush({ gps_latitude: 1, gps_longitude: 2 });
    let obsolete!: TestRequest;
    await vi.waitFor(() => { obsolete = request('/photos/by_paths'); });
    expect(obsolete.request.body.paths).toEqual(['/p2.jpg']);
    const writes = [writing];
    if (queued !== 'none') {
      for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
      writes.push(firstValueFrom(TestBed.inject(ApiService).put('/photo/gps', {
        path: '/p3.jpg', gps_latitude: 1, gps_longitude: 2,
      })).then(() => store.refreshPaths(queued === 'full' ? null : ['/p3.jpg'])));
      request('/photo/gps').flush({ gps_latitude: 1, gps_longitude: 2 });
      let progress!: TestRequest;
      await vi.waitFor(() => { progress = request('/photos/review_progress'); });
      progress.flush(COUNTS);
    }
    events.next(new NavigationStart(1, '/photo?path=/p2.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p2.jpg';
    events.next(new NavigationEnd(1, '/photo?path=/p2.jpg', '/photo?path=/p2.jpg'));
    expect(obsolete.cancelled).toBe(true);
    await Promise.all(writes);
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) expect(progress.cancelled).toBe(true);
    events.next(new NavigationStart(2, '/'));
    (TestBed.inject(Router) as unknown as { url: string }).url = '/';
    events.next(new NavigationEnd(2, '/', '/'));
    const returning = store.resumeListingReads();
    if (queued === 'full') {
      for (let page = 1; page <= 2; page++) {
        let repair!: TestRequest;
        await vi.waitFor(() => { repair = request('/photos'); });
        expect(repair.request.params.get('page')).toBe(String(page));
        repair.flush({ ...EMPTY_PAGE, photos: photos.slice((page - 1) * 2, page * 2)
          .map(photo => ({ ...photo, gps_latitude: 1, gps_longitude: 2 })), total: 6, has_more: true });
      }
    } else {
      let repair!: TestRequest;
      await vi.waitFor(() => { repair = request('/photos/by_paths'); });
      const repairedPaths = queued === 'targeted' ? ['/p2.jpg', '/p3.jpg'] : ['/p2.jpg'];
      expect(repair.request.body.paths).toEqual(repairedPaths);
      repair.flush({ photos: repairedPaths.map(path => makePhoto({ path, gps_latitude: 1, gps_longitude: 2 })) });
    }
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
    await returning;
    for (const hints of http.match(r => r.url === '/api/photos/keeper_hints')) if (!hints.cancelled) hints.flush({});
    expect(store.photos().map(photo => photo.path)).toEqual(photos.map(photo => photo.path));
    expect(store.photos().find(photo => photo.path === '/p2.jpg')?.gps_latitude).toBe(1);
    expect(store.filters().page).toBe(2);
    expect(store.selectedPaths()).toBe(selected);
    http.expectNone(r => r.url === '/api/photos');
  });

  it.each(['success', 'failure', 'cancellation', 'active', 'active-failure', 'active-identity', 'active-filter', 'parked', 'active-queued-identity', 'active-queued-query', 'active-queued-rejected', 'active-queued-destroyed'] as const)('refills filtered page offsets after membership loss and %s before nextPage', async outcome => {
    const activeRetry = outcome.startsWith('active');
    let acceptPaging = true;
    store.filters.update(f => ({ ...f, per_page: 2, no_gps: '1' }));
    const photos = Array.from({ length: 6 }, (_, i) => makePhoto({ path: `/gps${i}.jpg` }));
    const loading = store.loadPhotos();
    const first = request('/photos');
    expect(first.request.params.get('no_gps')).toBe('1');
    first.flush({ ...EMPTY_PAGE, photos: photos.slice(0, 2), total: 6, has_more: true });
    request('/photos/review_progress').flush(COUNTS);
    await loading;
    request('/photos/keeper_hints').flush({});
    const paging = store.nextPage();
    request('/photos').flush({ ...EMPTY_PAGE, photos: photos.slice(2, 4), total: 6, has_more: true });
    await paging;
    request('/photos/keeper_hints').flush({});
    store.selectedPaths.set(new Set(['/gps2.jpg', '/gps3.jpg']));
    const writing = firstValueFrom(TestBed.inject(ApiService).put('/photo/gps', {
      path: '/gps2.jpg', gps_latitude: 1, gps_longitude: 2,
    })).then(() => store.refreshPaths(['/gps2.jpg']));
    request('/photo/gps').flush({ gps_latitude: 1, gps_longitude: 2 });
    let obsolete!: TestRequest;
    await vi.waitFor(() => { obsolete = request('/photos/by_paths'); });
    events.next(new NavigationStart(1, '/photo?path=/gps2.jpg'));
    store.parkListingReads();
    expect(obsolete.cancelled).toBe(true);
    await writing;
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) expect(progress.cancelled).toBe(true);
    events.next(new NavigationStart(2, '/'));
    (TestBed.inject(Router) as unknown as { url: string }).url = '/';
    events.next(new NavigationEnd(2, '/', '/'));
    let returning = store.resumeListingReads();
    let target!: TestRequest;
    await vi.waitFor(() => { target = request('/photos/by_paths'); });
    expect(target.request.body.paths).toEqual(['/gps2.jpg']);
    expect(target.request.body.filters.no_gps).toBe('1');
    target.flush({ photos: [] });
    const remaining = photos.filter(photo => photo.path !== '/gps2.jpg');
    await vi.waitFor(() => { expect(store.photos().some(photo => photo.path === '/gps2.jpg')).toBe(false); });
    let refills = http.match(r => r.url === '/api/photos');
    if (outcome !== 'success') {
      expect(refills).toHaveLength(1);
      if (outcome === 'failure' || activeRetry || outcome === 'parked') refills[0].flush({}, { status: 500, statusText: 'Failed' });
      else {
        events.next(new NavigationStart(3, '/photo?path=/gps3.jpg'));
        store.parkListingReads();
        expect(refills[0].cancelled).toBe(true);
      }
      for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
      await returning;
      if (activeRetry) returning = store.nextPage(() => acceptPaging);
      else if (outcome === 'parked') {
        events.next(new NavigationStart(3, '/photo?path=/gps3.jpg'));
        store.parkListingReads();
        (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/gps3.jpg';
        events.next(new NavigationEnd(3, '/photo?path=/gps3.jpg', '/photo?path=/gps3.jpg'));
        returning = store.nextPage(undefined, { whileParked: true });
      } else {
        store.parkListingReads();
        events.next(new NavigationStart(4, '/'));
        (TestBed.inject(Router) as unknown as { url: string }).url = '/';
        events.next(new NavigationEnd(4, '/', '/'));
        returning = store.resumeListingReads();
      }
      if (activeRetry) await store.nextPage(); // Concurrent paging cannot bypass the structural repair.
      let retry!: TestRequest;
      await vi.waitFor(() => { retry = request('/photos'); });
      refills = [retry];
      if (outcome === 'active-identity' || outcome === 'active-filter') {
        if (outcome === 'active-identity') { identity.set('bob'); TestBed.tick(); }
        const newLoad = outcome === 'active-filter' ? store.updateFilter('camera', 'Canon') : store.loadPhotos();
        expect(retry.cancelled).toBe(true);
        request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/new-scope.jpg', star_rating: 2 })], total: 1 });
        for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
        await Promise.all([returning, newLoad]);
        const hints = http.match(r => r.url === '/api/photos/keeper_hints').filter(read => !read.cancelled);
        expect(hints).toHaveLength(1);
        hints[0].flush({ '/new-scope.jpg': { better_path: '/better.jpg' } });
        await vi.waitFor(() => { expect(store.photos()[0].keeper_hint).toEqual({ better_path: '/better.jpg' }); });
        expect(store.photos().map(photo => [photo.path, photo.star_rating])).toEqual([['/new-scope.jpg', 2]]);
        expect(store.filters().page).toBe(1);
        http.expectNone(r => r.url === '/api/photos');
        return;
      }
      if (outcome === 'active-failure') {
        expect(retry.request.params.get('page')).toBe('1');
        retry.flush({}, { status: 500, statusText: 'Failed again' });
        for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
        await returning;
        expect(store.filters().page).toBe(2);
        expect(store.photos().map(photo => photo.path)).toEqual(['/gps0.jpg', '/gps1.jpg', '/gps3.jpg']);
        http.expectNone(r => r.url === '/api/photos');
        returning = store.nextPage();
        await vi.waitFor(() => { retry = request('/photos'); });
        refills = [retry];
      }
    }
    if (refills.length) {
      expect(refills).toHaveLength(1);
      // The direct refill keeps the rows before the last loaded page and reads only that page;
      // a retry owed after a failure or a cancellation refetches every loaded page.
      const fromPage = outcome === 'success' ? 2 : 1;
      for (let page = fromPage; page <= 2; page++) {
        let refill = refills[0];
        if (page > fromPage) await vi.waitFor(() => { refill = request('/photos'); });
        expect(refill.request.params.get('page')).toBe(String(page));
        refill.flush({ ...EMPTY_PAGE, photos: remaining.slice((page - 1) * 2, page * 2), total: 5, has_more: true });
        if (page === 2 && outcome.startsWith('active-queued')) {
          // Change ownership after HTTP completion queues the repair continuation,
          // before an auth effect or replacement load can invalidate its sequence.
          if (outcome === 'active-queued-identity') identity.set('bob');
          if (outcome === 'active-queued-query') store.filters.update(f => ({ ...f, camera: 'Canon' }));
          if (outcome === 'active-queued-rejected') acceptPaging = false;
          if (outcome === 'active-queued-destroyed') destroyStore();
          let settled = false;
          const completion = returning.then(() => { settled = true; });
          const unexpected: TestRequest[] = [];
          await vi.waitFor(() => {
            // Settle any erroneous tail request so the assertion reports its effect,
            // rather than hanging on an unflushed request or a fixed microtask count.
            const reads = http.match(r => r.url === '/api/photos');
            unexpected.push(...reads);
            for (const read of reads) if (!read.cancelled) read.flush({ ...EMPTY_PAGE, photos: [], total: 5, has_more: false });
            for (const read of http.match(r => r.url === '/api/photos/review_progress')) if (!read.cancelled) read.flush(COUNTS);
            for (const read of http.match(r => r.url === '/api/photos/keeper_hints')) if (!read.cancelled) read.flush({});
            expect(settled).toBe(true);
          });
          await completion;
          expect(unexpected.map(read => read.request.params.get('page'))).toEqual([]);
          expect(store.filters().page).toBe(2);
          return;
        }
      }
    }
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
    if (!activeRetry) await returning;
    if (outcome === 'parked') await store.resumeListingReads();
    for (const hints of http.match(r => r.url === '/api/photos/keeper_hints')) if (!hints.cancelled) hints.flush({});
    const tail = activeRetry ? returning : store.nextPage();
    let last!: TestRequest;
    await vi.waitFor(() => { last = request('/photos'); });
    expect(last.request.params.get('page')).toBe('3');
    last.flush({ ...EMPTY_PAGE, photos: remaining.slice(4), total: 5, has_more: false });
    await tail;
    for (const hints of http.match(r => r.url === '/api/photos/keeper_hints')) if (!hints.cancelled) hints.flush({});
    expect(store.photos().map(photo => photo.path)).toEqual(remaining.map(photo => photo.path));
    expect(store.total()).toBe(5);
    expect(store.selectedPaths()).toEqual(new Set(['/gps3.jpg']));
  });

  it.each(['attach', 'explicit'] as const)('retains failed targeted debt for %s retry without a later redundant Back read', async retryKind => {
    await loadAndParkThreePages();
    await store.refreshPaths(['/p64.jpg']);
    const returning = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    let failed!: TestRequest;
    await vi.waitFor(() => { failed = request('/photos/by_paths'); });
    expect(failed.request.body.paths).toEqual(['/p64.jpg']);
    failed.flush({}, { status: 500, statusText: 'Failed' });
    await returning;
    expect(store.photos()[64].path).toBe('/p64.jpg');
    if (retryKind === 'attach') store.parkListingReads();
    const retrying = retryKind === 'attach' ? store.resumeListingReads() : store.refreshPaths(['/p64.jpg']);
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
    let retry!: TestRequest;
    await vi.waitFor(() => { retry = request('/photos/by_paths'); });
    retry.flush({ photos: [makePhoto({ path: '/p64.jpg', star_rating: 5 })] });
    await retrying;
    expect(store.photos()[64].star_rating).toBe(5);
    store.parkListingReads();
    await store.resumeListingReads();
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/by_paths' || r.url === '/api/photos/review_progress');
  });

  it.each(['failure', 'cancellation', 'identity'] as const)('retains every chunk of a large targeted repair after %s', async outcome => {
    store.filters.update(f => ({ ...f, per_page: 300 }));
    const photos = Array.from({ length: 600 }, (_, i) => makePhoto({ path: `/chunk${i}.jpg`, star_rating: 1 }));
    const loading = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, photos: photos.slice(0, 300), total: 600, has_more: true });
    request('/photos/review_progress').flush(COUNTS);
    await loading;
    request('/photos/keeper_hints').flush({});
    const paging = store.nextPage();
    request('/photos').flush({ ...EMPTY_PAGE, photos: photos.slice(300), total: 600, has_more: false });
    await paging;
    request('/photos/keeper_hints').flush({});
    const paths = photos.map(photo => photo.path);
    const repairing = store.refreshPaths(paths);
    request('/photos/review_progress').flush(COUNTS);
    let chunks: TestRequest[] = [];
    await vi.waitFor(() => {
      if (chunks.length === 0) chunks = http.match(r => r.url === '/api/photos/by_paths');
      expect(chunks).toHaveLength(2);
    });
    expect(chunks.map(chunk => chunk.request.body.paths.length)).toEqual([500, 100]);
    expect(chunks.flatMap(chunk => chunk.request.body.paths)).toEqual(paths);
    if (outcome !== 'cancellation') {
      chunks[0].flush({}, { status: 500, statusText: 'Failed' });
      await repairing;
      expect(chunks[1].cancelled).toBe(false);
    }
    if (outcome === 'identity') {
      identity.set('bob');
      TestBed.tick();
      const loadingNew = store.loadPhotos();
      expect(chunks[1].cancelled).toBe(true);
      request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/bob.jpg', star_rating: 2 })], total: 1 });
      for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
      await loadingNew;
      request('/photos/keeper_hints').flush({ '/bob.jpg': { better_path: '/other.jpg' } });
      await vi.waitFor(() => { expect(store.photos()[0].keeper_hint).toEqual({ better_path: '/other.jpg' }); });
      store.parkListingReads();
      await store.resumeListingReads();
      expect(store.photos().map(photo => [photo.path, photo.star_rating])).toEqual([['/bob.jpg', 2]]);
      http.expectNone(r => r.url === '/api/photos/by_paths' || r.url === '/api/photos');
      return;
    }
    events.next(new NavigationStart(1, '/photo?path=/chunk0.jpg'));
    store.parkListingReads();
    expect(chunks[1].cancelled).toBe(true);
    if (outcome === 'cancellation') expect(chunks[0].cancelled).toBe(true);
    await repairing;
    events.next(new NavigationStart(2, '/'));
    (TestBed.inject(Router) as unknown as { url: string }).url = '/';
    events.next(new NavigationEnd(2, '/', '/'));
    const returning = store.resumeListingReads();
    let retries: TestRequest[] = [];
    await vi.waitFor(() => {
      if (retries.length === 0) retries = http.match(r => r.url === '/api/photos/by_paths');
      expect(retries).toHaveLength(2);
    });
    expect(retries.flatMap(chunk => chunk.request.body.paths)).toEqual(paths);
    for (const retry of retries) retry.flush({ photos: retry.request.body.paths.map((path: string) => makePhoto({ path, star_rating: 5 })) });
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
    await returning;
    expect(store.photos().map(photo => photo.path)).toEqual(paths);
    expect(store.photos().every(photo => photo.star_rating === 5)).toBe(true);
    expect(store.filters().page).toBe(2);
    http.expectNone(r => r.url === '/api/photos');
  });

  it('keeps a targeted repair after a second cancellation on the return trip', async () => {
    await loadAndParkThreePages();
    await store.refreshPaths(['/p64.jpg']);
    events.next(new NavigationStart(2, '/'));
    (TestBed.inject(Router) as unknown as { url: string }).url = '/';
    events.next(new NavigationEnd(2, '/', '/'));
    const returning = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    let obsolete!: TestRequest;
    await vi.waitFor(() => { obsolete = request('/photos/by_paths'); });
    expect(obsolete.request.body.paths).toEqual(['/p64.jpg']);
    events.next(new NavigationStart(3, '/photo?path=/p65.jpg'));
    store.parkListingReads();
    (TestBed.inject(Router) as unknown as { url: string }).url = '/photo?path=/p65.jpg';
    events.next(new NavigationEnd(3, '/photo?path=/p65.jpg', '/photo?path=/p65.jpg'));
    expect(obsolete.cancelled).toBe(true);
    await returning;
    events.next(new NavigationStart(4, '/'));
    (TestBed.inject(Router) as unknown as { url: string }).url = '/';
    events.next(new NavigationEnd(4, '/', '/'));
    const retrying = store.resumeListingReads();
    let retry!: TestRequest;
    await vi.waitFor(() => { retry = request('/photos/by_paths'); });
    expect(retry.request.body.paths).toEqual(['/p64.jpg']);
    retry.flush({ photos: [makePhoto({ path: '/p64.jpg', star_rating: 5 })] });
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
    await retrying;
    expect(store.photos()[64].star_rating).toBe(5);
    expect(store.photos()).toHaveLength(192);
    expect(store.filters().page).toBe(3);
    http.expectNone(r => r.url === '/api/photos');
  });

  it.each(['identity', 'filter'] as const)('drops cancelled targeted debt when the %s changes', async change => {
    await loadAndParkThreePages();
    await store.refreshPaths(['/p64.jpg']);
    const returning = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    let obsolete!: TestRequest;
    await vi.waitFor(() => { obsolete = request('/photos/by_paths'); });
    expect(obsolete.request.body.paths).toEqual(['/p64.jpg']);
    if (change === 'identity') { identity.set('bob'); TestBed.tick(); }
    const loading = change === 'filter' ? store.updateFilter('camera', 'Canon') : store.loadPhotos();
    expect(obsolete.cancelled).toBe(true);
    request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/new-scope.jpg', star_rating: 2 })], total: 1 });
    const progress = http.match(r => r.url === '/api/photos/review_progress').filter(read => !read.cancelled);
    expect(progress).toHaveLength(1);
    progress[0].flush(COUNTS);
    await Promise.all([returning, loading]);
    const hints = http.match(r => r.url === '/api/photos/keeper_hints').filter(read => !read.cancelled);
    expect(hints).toHaveLength(1);
    hints[0].flush({ '/new-scope.jpg': { better_path: '/better.jpg' } });
    await vi.waitFor(() => { expect(store.photos()[0].keeper_hint).toEqual({ better_path: '/better.jpg' }); });
    store.parkListingReads();
    await store.resumeListingReads();
    expect(store.photos().map(photo => [photo.path, photo.star_rating])).toEqual([['/new-scope.jpg', 2]]);
    http.expectNone(r => r.url === '/api/photos/by_paths' || r.url === '/api/photos');
  });

  it('cancels foreground photo recovery on real Back and preserves a later confirmed write', async () => {
    await loadAndParkThreePages();
    const paging = store.nextPage(undefined, { whileParked: true });
    const originalTail = request('/photos');
    store.parkListingReads();
    expect(originalTail.cancelled).toBe(true);
    await paging;
    const recovering = store.nextPage(undefined, { whileParked: true });
    const obsolete = request('/photos');
    events.next(new NavigationStart(2, '/'));
    expect(obsolete.cancelled).toBe(true);
    (TestBed.inject(Router) as unknown as { url: string }).url = '/';
    events.next(new NavigationEnd(2, '/', '/'));
    const returning = store.resumeListingReads();
    const writing = firstValueFrom(TestBed.inject(ApiService).put('/photo/gps', {
      path: '/p64.jpg', gps_latitude: 1, gps_longitude: 2,
    })).then(() => store.refreshPaths(['/p64.jpg']));
    const write = request('/photo/gps');
    expect(write.request.body.path).toBe('/p64.jpg');
    write.flush({ gps_latitude: 1, gps_longitude: 2 });
    // Real Back cancelled the parked request and its loading state; the full repair
    // runs first, then the confirmed write's targeted repair follows the chain.
    for (let page = 1; page <= 4; page++) {
      let read!: TestRequest;
      await vi.waitFor(() => { read = request('/photos'); });
      expect(read.request.params.get('page')).toBe(String(page));
      read.flush({ ...EMPTY_PAGE, photos: Array.from({ length: 64 }, (_, i) => makePhoto({ path: `/p${(page - 1) * 64 + i}.jpg` })), total: 256, has_more: false });
    }
    let repair!: TestRequest;
    await vi.waitFor(() => { repair = request('/photos/by_paths'); });
    expect(repair.request.body.paths).toEqual(['/p64.jpg']);
    repair.flush({ photos: [makePhoto({ path: '/p64.jpg', gps_latitude: 1, gps_longitude: 2 })] });
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) if (!progress.cancelled) progress.flush(COUNTS);
    await Promise.all([recovering, returning, writing]);
    for (const hints of http.match(r => r.url === '/api/photos/keeper_hints')) if (!hints.cancelled) hints.flush({});
    expect(store.photos()[64].gps_latitude).toBe(1);
    expect(store.photos()).toHaveLength(256);
    expect(store.filters().page).toBe(4);
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/by_paths');
  });

  it('coalesces parked confirmed writes and assistant changes into one in-place refresh on return', async () => {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, has_more: true, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    store.selectedPaths.set(new Set(['/a.jpg']));
    const selected = store.selectedPaths();
    const writing = store.setRating('/a.jpg', 4);
    const rating = request('/photo/set_rating');
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    store.parkListingReads();
    events.next(new NavigationEnd(1, '/photo?path=/a.jpg', '/photo?path=/a.jpg'));
    rating.flush({ success: true });
    await writing;
    await store.refreshPaths(['/a.jpg']);
    await store.refreshPaths(null);
    await store.refreshReviewResults();
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/review_progress');
    // Back's NavigationEnd alone must not start work for another page.
    events.next(new NavigationEnd(2, '/stats', '/stats'));
    http.expectNone(r => r.url === '/api/photos');
    const resumed = store.resumeListingReads();
    const duplicateAttach = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, has_more: true, photos: [makePhoto({ path: '/a.jpg', star_rating: 4 })] });
    await Promise.all([resumed, duplicateAttach]);
    request('/photos/keeper_hints').flush({});
    expect(store.selectedPaths()).toBe(selected);
    expect(store.photos()[0].star_rating).toBe(4);
    expect(store.loadError()).toBe(false);
    http.expectNone(r => r.url === '/api/photos');
    // Paging is live again without a filter change or a new gallery init.
    const paging = store.nextPage();
    request('/photos').flush({ ...EMPTY_PAGE, page: 2, total: 1 });
    await paging;
    expect(store.filters().page).toBe(2);
  });

  it('cancels a pending review tail refill before loading a new filter', async () => {
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    store.photos.set([makePhoto({ path: '/kept.jpg', is_kept: true })]);
    const refill = store.refreshReviewResults();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([refill, loading]);
    expect(store.loadError()).toBe(false);
  });

  it('cancels assistant page refreshes and discards queued refreshes after the view changes', async () => {
    const initial = store.loadPhotos();
    request('/photos').flush(EMPTY_PAGE);
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    store.filters.update(f => ({ ...f, page: 2 }));
    const refresh = store.refreshPaths(null);
    const oldProgress = request('/photos/review_progress');
    const queued = store.refreshPaths(null);
    const queuedProgress = request('/photos/review_progress');
    await Promise.resolve();
    const oldPage = request('/photos');
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    expect(queuedProgress.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([refresh, queued, loading]);
    http.expectNone(r => r.url === '/api/photos');
    expect(store.loadError()).toBe(false);
  });

  it('cancels a read-only by-path refresh without cancelling a pending rating write', async () => {
    const initial = store.showPaths(['/pin.jpg']);
    request('/photos/by_paths').flush({ photos: [makePhoto({ path: '/pin.jpg' })], total: 1, missing: [] });
    await initial;
    const refreshing = store.refreshPaths(['/pin.jpg']);
    await Promise.resolve();
    const oldRead = request('/photos/by_paths');
    const writing = store.setRating('/pin.jpg', 4);
    const rating = request('/photo/set_rating');
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldRead.cancelled).toBe(true);
    expect(rating.cancelled).toBe(false);
    rating.flush({ success: true });
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([refreshing, writing, loading]);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it('cancels obsolete keeper-hint reads after a replacement load', async () => {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/old.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    const hints = request('/photos/keeper_hints');
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(hints.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await loading;
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['navigation', 'destroy'] as const)('allows an already-submitted rating write to finish after %s', async change => {
    store.photos.set([makePhoto({ path: '/rated.jpg' })]);
    store.filters.update(f => ({ ...f, sort: 'star_rating' }));
    const writing = store.setRating('/rated.jpg', 4);
    const rating = request('/photo/set_rating');
    const loading = store.loadPhotos();
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    if (change === 'navigation') events.next(new NavigationStart(1, '/stats'));
    else destroyStore();
    expect(page.cancelled).toBe(true);
    expect(progress.cancelled).toBe(true);
    expect(rating.cancelled).toBe(false);
    rating.flush({ success: true });
    await Promise.all([writing, loading]);
    // A write may finish, but a destroyed store must not start new reads.
    const followup = http.match(r => r.url === '/api/photos/review_progress');
    expect(followup).toHaveLength(0);
    expect(snack).not.toHaveBeenCalled();
  });
});
