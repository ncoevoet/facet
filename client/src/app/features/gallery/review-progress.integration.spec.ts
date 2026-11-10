import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpRequest, provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, filter, firstValueFrom, take } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService } from '../../core/services/scan.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { GalleryComponent } from './gallery.component';
import { GalleryStore } from './gallery.store';

const counts = { total: 2, undecided: 2, kept: 0, rejected: 0 };
const rows = [makePhoto({ path: '/trip/a.jpg' }), makePhoto({ path: '/trip/b.jpg' })];
const page = { photos: rows, total: 2, page: 1, per_page: 64, total_pages: 1, has_more: false };
const config = {
  pagination: { default_per_page: 64 },
  defaults: { sort: 'star_rating', sort_direction: 'ASC', gallery_mode: 'grid', hide_details: true },
  display: { card_width_px: 168, image_width_px: 640, tags_per_photo: 5 },
  features: { show_rating_controls: true },
  quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
  sort_options_grouped: [], search_threshold_default: 0.15,
};

describe('rendered review progress with real store and HTTP', () => {
  let fixture: ComponentFixture<GalleryComponent>;
  let store: GalleryStore;
  let http: HttpTestingController;
  let auth: AuthService;
  let requests: Subject<HttpRequest<unknown>>;
  const requested = (url: string) => firstValueFrom(requests.pipe(filter(request => request.url === url), take(1)));
  const banner = () => fixture.nativeElement.querySelector('section[aria-label="gallery.review_progress.title {}"]') as HTMLElement | null;
  const progressRequests = () => http.match(request => request.url === '/api/photos/review_progress');
  const flushSideData = () => {
    for (const request of http.match(request => request.url.startsWith('/api/filter_options/') || request.url === '/api/type_counts')) {
      request.flush({ types: [], cameras: [], lenses: [], tags: [], persons: [], patterns: [], temps: [], hue_buckets: [], ranges: {} });
    }
    for (const request of http.match('/api/photos/keeper_hints')) request.flush({});
  };

  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear();
    requests = new Subject();
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(withXhr(), withInterceptors([(request, next) => { requests.next(request); return next(request); }])), provideHttpClientTesting(), provideRouter([]), provideNativeDateAdapter(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: { review_status: 'undecided', review_queue: '1', sort: 'star_rating' }, paramMap: convertToParamMap({}) } } },
      { provide: ScanService, useValue: { canLaunch: signal(false) } },
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', t: (key: string, params?: unknown) => `${key} ${JSON.stringify(params ?? {})}` } },
      { provide: AssistantChangesService, useValue: { batch$: NEVER } },
      { provide: MatSnackBar, useValue: { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) } },
    ] });
    auth = TestBed.inject(AuthService);
    auth.status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    http = TestBed.inject(HttpTestingController);
    store = TestBed.inject(GalleryStore);
    fixture = TestBed.createComponent(GalleryComponent);
    Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(true), configurable: true });
    // A wide screen: below lg the notices start folded into one bar, which gallery.component.spec covers.
    Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(true), configurable: true });
    fixture.detectChanges();
    const photosStarted = requested('/api/photos');
    http.expectOne('/api/config').flush(config);
    await photosStarted;
    const sideDataStarted = requested('/api/filter_options/metric_ranges');
    http.expectOne(request => request.url === '/api/photos').flush(page);
    progressRequests().forEach(request => request.flush(counts));
    await sideDataStarted;
    flushSideData();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(store.photos()).toHaveLength(2);
    expect(banner()).not.toBeNull();
  });

  afterEach(() => {
    fixture.destroy();
    TestBed.resetTestingModule();
    http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });

  it('renders the banner as a card of the floating bottom-right notice stack', () => {
    expect(banner()?.closest('[data-gallery-notices]')).not.toBeNull();
  });

  it('keeps the banner mounted and requests counts only once after a successful rating rebuild', async () => {
    const previous = banner();
    const rating = store.setRating('/trip/a.jpg', 4);
    const write = http.expectOne('/api/photo/set_rating');
    expect(write.request.body).toEqual({ photo_path: '/trip/a.jpg', rating: 4 });
    const photosStarted = requested('/api/photos');
    write.flush({ success: true });
    await photosStarted;
    fixture.detectChanges();
    const requests = progressRequests();
    expect(requests).toHaveLength(1);
    expect(banner()).toBe(previous);
    expect(store.reviewProgress()).toEqual(counts);
    http.expectOne(request => request.url === '/api/photos').flush({ ...page, photos: [{ ...rows[0], star_rating: 4 }, rows[1]] });
    expect(requests[0].cancelled).toBe(false);
    requests[0].flush(counts);
    await rating;
    flushSideData();
    fixture.detectChanges();
    expect(banner()).toBe(previous);
    expect(store.photos()[0]).toMatchObject({ path: '/trip/a.jpg', star_rating: 4 });
  });

  it('keeps a closed banner closed across a rating rebuild, and reopens it for another scope', async () => {
    banner()!.querySelector<HTMLButtonElement>('button[aria-label="ui.buttons.dismiss {}"]')!.click();
    fixture.detectChanges();
    expect(banner()).toBeNull();
    const rating = store.setRating('/trip/a.jpg', 4);
    const photosStarted = requested('/api/photos');
    http.expectOne('/api/photo/set_rating').flush({ success: true });
    await photosStarted;
    http.expectOne(request => request.url === '/api/photos').flush({ ...page, photos: [{ ...rows[0], star_rating: 4 }, rows[1]] });
    progressRequests().forEach(request => request.flush({ ...counts, undecided: 1, kept: 1 }));
    await rating;
    flushSideData();
    fixture.detectChanges();
    expect(store.reviewProgress()).toEqual({ ...counts, undecided: 1, kept: 1 });
    expect(banner()).toBeNull();

    store.filters.update(filters => ({ ...filters, path_prefix: '/other/' }));
    const read = store.loadReviewProgress();
    http.match(request => request.url === '/api/photos/review_progress').forEach(request => request.flush(counts));
    await read;
    fixture.detectChanges();
    expect(banner()).not.toBeNull();
  });

  it('hides a previous scope immediately and refuses its queued late count response', async () => {
    const previous = banner();
    const oldRead = store.loadReviewProgress();
    const oldRequest = http.expectOne(request => request.url === '/api/photos/review_progress');
    oldRequest.flush({ total: 99, undecided: 99, kept: 0, rejected: 0 });
    store.filters.update(filters => ({ ...filters, path_prefix: '/other/' }));
    expect(store.reviewProgress()).toBeNull();
    fixture.detectChanges();
    expect(banner()).toBeNull();
    await oldRead;
    expect(store.reviewProgress()).toBeNull();
    const newRead = store.loadReviewProgress();
    const request = http.expectOne(request => request.url === '/api/photos/review_progress');
    expect(request.request.params.get('path_prefix')).toBe('/other/');
    request.flush({ total: 3, undecided: 0, kept: 3, rejected: 0 });
    await newRead;
    fixture.detectChanges();
    expect(banner()).not.toBe(previous);
    expect(store.reviewPercent()).toBe(100);
  });

  it('hides counts synchronously when the identity changes and does not restore a prior account snapshot', async () => {
    const oldRead = store.loadReviewProgress();
    http.expectOne(request => request.url === '/api/photos/review_progress').flush({ total: 99, undecided: 99, kept: 0, rejected: 0 });
    auth.status.update(status => status ? { ...status, user_id: 'bob' } : status);
    expect(store.reviewProgress()).toBeNull();
    fixture.detectChanges();
    expect(banner()).toBeNull();
    await oldRead;
    const bobRead = store.loadReviewProgress();
    http.expectOne(request => request.url === '/api/photos/review_progress').flush({ total: 0, undecided: 0, kept: 0, rejected: 0 });
    await bobRead;
    expect(store.reviewProgress()?.total).toBe(0);
    auth.status.update(status => status ? { ...status, user_id: 'alice' } : status);
    expect(store.reviewProgress()).toBeNull();
    fixture.detectChanges();
    expect(banner()).toBeNull();
  });

  it('retains same-scope counts through cancellation but clears a failed read and recovers on retry', async () => {
    const previous = banner();
    const first = store.loadReviewProgress();
    const cancelled = http.expectOne(request => request.url === '/api/photos/review_progress');
    const second = store.loadReviewProgress();
    expect(cancelled.cancelled).toBe(true);
    fixture.detectChanges();
    expect(banner()).toBe(previous);
    http.expectOne(request => request.url === '/api/photos/review_progress').flush({ total: 2, undecided: 1, kept: 1, rejected: 0 });
    await Promise.all([first, second]);
    expect(store.reviewProgress()?.kept).toBe(1);
    const failed = store.loadReviewProgress();
    fixture.detectChanges();
    expect(banner()).toBe(previous);
    http.expectOne(request => request.url === '/api/photos/review_progress').flush({}, { status: 503, statusText: 'Busy' });
    await failed;
    fixture.detectChanges();
    expect(banner()).toBeNull();
    const retry = store.loadReviewProgress();
    http.expectOne(request => request.url === '/api/photos/review_progress').flush(counts);
    await retry;
    fixture.detectChanges();
    expect(banner()).not.toBeNull();
    expect(store.reviewProgress()).toEqual(counts);
  });

  it('uses the saved smart-album decision criterion in a temporary queue request', async () => {
    store.currentAlbum.set({ id: 7, name: 'Kept trip', description: '', cover_photo_path: null, first_photo_path: null, is_shared: false, scoring_context: null, photo_count: 2, created_at: '', updated_at: '', is_smart: true, smart_filter_json: JSON.stringify({ review_status: 'kept' }) });
    expect(store.reviewProgress()).toBeNull();
    const reading = store.loadReviewProgress();
    const request = http.expectOne(request => request.url === '/api/photos/review_progress');
    expect(request.request.params.get('scope_review_status')).toBe('kept');
    request.flush({ total: 2, undecided: 0, kept: 2, rejected: 0 });
    await reading;
    fixture.detectChanges();
    expect(store.reviewPercent()).toBe(100);
  });

  async function loadExplicitSmartQueue(): Promise<string> {
    // Hold the saved album fixture constant; album autosave is tested separately.
    store.initializing.set(true);
    store.currentAlbum.set({ id: 7, name: 'Kept trip', description: '', cover_photo_path: null,
      first_photo_path: null, is_shared: false, scoring_context: null, photo_count: 2,
      created_at: '', updated_at: '', is_smart: true, smart_filter_json: JSON.stringify({ review_status: 'kept' }) });
    const photosStarted = requested('/api/photos');
    const updating = store.updateFilter('review_status', 'undecided');
    await photosStarted;
    const request = http.expectOne(request => request.url === '/api/photos/review_progress');
    expect(request.request.params.get('scope_review_status')).toBe('undecided');
    request.flush({ total: 5, undecided: 5, kept: 0, rejected: 0 });
    http.expectOne(request => request.url === '/api/photos').flush(page);
    await updating;
    flushSideData();
    fixture.detectChanges();
    expect(store.reviewProgress()?.total).toBe(5);
    return JSON.stringify(store.filters());
  }

  it('keeps explicit temporary smart-album criteria and matching counts when edition is locked', async () => {
    const filters = await loadExplicitSmartQueue();
    const owner = auth.identity();
    const pending = store.loadReviewProgress();
    const request = http.expectOne(request => request.url === '/api/photos/review_progress');
    expect(request.request.params.get('scope_review_status')).toBe('undecided');
    auth.status.update(status => status ? { ...status, edition_authenticated: false } : status);
    expect(auth.identity()).toBe(owner); expect(JSON.stringify(store.filters())).toBe(filters);
    request.flush({ total: 99, undecided: 99, kept: 0, rejected: 0 }); await pending;
    expect(store.reviewProgress()).toEqual({ total: 99, undecided: 99, kept: 0, rejected: 0 });
    const fresh = store.loadReviewProgress();
    const next = http.expectOne(request => request.url === '/api/photos/review_progress');
    expect(next.request.params.get('scope_review_status')).toBe('undecided');
    next.flush({ total: 3, undecided: 2, kept: 1, rejected: 0 }); await fresh; fixture.detectChanges();
    expect(store.reviewProgress()?.total).toBe(3); expect(store.reviewPercent()).toBe(33);
  });

  it('invalidates smart-album counts when starting a temporary queue changes only its effective criterion', async () => {
    const filters = await loadExplicitSmartQueue();
    const photosStarted = requested('/api/photos');
    const starting = store.startReviewQueue();
    expect(JSON.stringify(store.filters())).toBe(filters);
    expect(store.reviewProgress()).toBeNull();
    fixture.detectChanges();
    expect(banner()).toBeNull();
    await photosStarted;
    const request = http.expectOne(request => request.url === '/api/photos/review_progress');
    expect(request.request.params.get('scope_review_status')).toBe('kept');
    request.flush({ total: 3, undecided: 0, kept: 3, rejected: 0 });
    http.expectOne(request => request.url === '/api/photos').flush(page);
    await starting;
    flushSideData();
    fixture.detectChanges();
    expect(store.reviewProgress()?.total).toBe(3);
    expect(store.reviewPercent()).toBe(100);
  });

  it('keeps an announced summary mounted during a successful Keep refresh', async () => {
    const previous = banner();
    const keeping = store.batchReview(['/trip/a.jpg'], 'kept', false);
    const write = http.expectOne('/api/photos/batch_review');
    expect(write.request.body).toEqual({ photo_paths: ['/trip/a.jpg'], decision: 'kept' });
    const photosStarted = requested('/api/photos');
    write.flush({ success: true, count: 1 });
    await photosStarted;
    fixture.detectChanges();
    expect(banner()).toBe(previous);
    const request = http.expectOne(request => request.url === '/api/photos/review_progress');
    request.flush({ total: 2, undecided: 1, kept: 1, rejected: 0 });
    http.expectOne(request => request.url === '/api/photos').flush({ ...page, photos: rows.slice(1), total: 1 });
    await keeping;
    flushSideData();
    fixture.detectChanges();
    expect(banner()).toBe(previous);
    const summary = banner()!.querySelector('[role="status"]');
    expect(summary?.textContent).toContain('"kept":1');
    expect(summary?.querySelector('button, progress')).toBeNull();
    expect(store.photos().map(photo => photo.path)).toEqual(['/trip/b.jpg']);
  });
});
