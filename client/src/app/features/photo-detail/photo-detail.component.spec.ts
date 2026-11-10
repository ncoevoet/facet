import type { Navigation } from '@angular/router';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { TimelineFeedCache } from '../timeline/timeline-feed-cache.service';
import { GalleryStore } from '../gallery/gallery.store';
import { GALLERY_REVISIT } from '../../core/gallery-reuse.strategy';
import { makePhoto } from '../../../testing/photo.fixture';
import type { Mock, MockInstance } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, ParamMap, Router, NavigationStart, NavigationEnd, convertToParamMap } from '@angular/router';
import { Location } from '@angular/common';
import { MatDialog } from '@angular/material/dialog';
import { BehaviorSubject, finalize, Observable, of, Subject, throwError } from 'rxjs';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { ApplicationRef, Component, computed, signal } from '@angular/core';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { MatMenuModule, MatMenuTrigger } from '@angular/material/menu';
import { MatSelect, MatSelectModule } from '@angular/material/select';
import { OverlayContainer } from '@angular/cdk/overlay';
import { ApiService } from '../../core/services/api.service';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { KeyboardMappingService, KEYMAP_STORAGE_KEY } from '../../core/services/keyboard-mapping.service';
import { AssistantChangesService, AssistantChangeBatch } from '../../core/agent/assistant-changes.service';
import { privateImageSessionKey, resetPrivateImageSession } from '../../shared/utils/private-image-session';

// Mock Leaflet via vi.doMock + dynamic import: the component pulls in shared/leaflet
// (which runs L.Icon.Default.mergeOptions at module load). Without this mock, importing
// the real component caches the real shared/leaflet in the shared module registry and
// poisons map.component.spec's leaflet mock (createLeafletMap keeps the real L) — a
// flaky CI failure. The shared singleton keeps the real Leaflet out of the registry and
// makes every leaflet-using spec's binding identical regardless of load order.
import { leafletMock, leafletMockMap } from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);

let PhotoDetailComponent: typeof import('./photo-detail.component').PhotoDetailComponent;

describe('PhotoDetailComponent', () => {
  // The open metric tab is remembered across tests otherwise.
  afterEach(() => {
    localStorage.removeItem('facet_photo_detail_tab');
    history.replaceState(null, '', location.href);
  });

   
  let component: any;
  let changes$: Subject<AssistantChangeBatch>;
  let mockApi: { get: Mock; post: Mock; put: Mock; delete: Mock; imageUrl: Mock; downloadUrl: Mock; getRaw: Mock };
  let mockRouter: { url: string; navigate: Mock; currentNavigation: () => Navigation | null; events: Observable<unknown> };
  let mockLocation: { back: Mock; path: Mock; getState: Mock; replaceState: Mock };
  let mockRoute: { snapshot: { queryParamMap: { get: Mock } }; queryParamMap: BehaviorSubject<ParamMap> };
  let mockAuth: { status: ReturnType<typeof signal>; identity: () => string; session: () => string | null; isEdition: ReturnType<typeof signal>; downloadProfiles: ReturnType<typeof signal> };
  let mockDialog: { open: Mock; openDialogs: unknown[] };

  const samplePhoto = {
    path: '/photos/test.jpg',
    filename: 'test.jpg',
    aggregate: 8.5,
    aesthetic: 7.2,
    face_count: 1,
    face_quality: 6.5,
    face_ratio: 0.1,
    comp_score: 7.0,
    tech_sharpness: 8.0,
    color_score: 7.5,
    exposure_score: 8.0,
    category: 'portrait',
    tags: 'nature,landscape',
    tags_list: ['nature', 'landscape'],
    manual_tags: [],
    date_taken: '2025-01-15',
    camera_model: 'Canon R5',
    lens_model: 'RF 50mm',
    focal_length: 50,
    f_stop: 1.8,
    shutter_speed: 0.005,
    iso: 400,
    persons: [{ id: 1, name: 'Alice' }],
    star_rating: 3,
    is_favorite: false,
    is_rejected: false,
    image_width: 6000,
    image_height: 4000,
  };

  function createComponent(prepare?: (store: GalleryStore) => void) {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        PhotoDetailComponent,
        { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
        { provide: ApiService, useValue: mockApi },
        { provide: Router, useValue: mockRouter },
        { provide: Location, useValue: mockLocation },
        { provide: ActivatedRoute, useValue: mockRoute },
        { provide: AuthService, useValue: mockAuth },
        { provide: MatDialog, useValue: mockDialog },
        { provide: I18nService, useValue: { t: (k: string) => k, locale: () => 'en', translations: () => ({}) } },
      ],
    });
    prepare?.(TestBed.inject(GalleryStore));
    component = TestBed.inject(PhotoDetailComponent);
  }

  it('keeps a Timeline photo without advancing into the parked Gallery review queue', async () => {
    history.replaceState({ photoOrigin: 'timeline', photo: samplePhoto }, '', location.href);
    createComponent();
    const store = TestBed.inject(GalleryStore);
    const photo = makePhoto({ path: '/timeline-only.jpg' });
    store.photos.set([makePhoto({ path: '/unrelated-gallery.jpg' })]);
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    vi.spyOn(store, 'loadReviewProgress').mockResolvedValue();
    component.photo.set(photo);
    await component.reviewPhoto('kept');
    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_review', { photo_paths: ['/timeline-only.jpg'], decision: 'kept' });
    expect(component.photo()).toMatchObject({ path: '/timeline-only.jpg', is_kept: true });
    expect(mockRouter.navigate).not.toHaveBeenCalled();
  });

  it('uses only the captured Timeline preview for arrows and retains Timeline Back ownership', async () => {
    history.replaceState({ photoOrigin: 'timeline', photo: samplePhoto }, '', location.href);
    createComponent();
    const a = makePhoto({ path: '/timeline-a.jpg' }); const b = makePhoto({ path: '/timeline-b.jpg' });
    TestBed.inject(TimelineFeedCache).capturePhotos([{ date: '2026-11-01', count: 30, photos: [a, b] }]);
    TestBed.inject(GalleryStore).photos.set([a, makePhoto({ path: '/wrong-neighbor.jpg' })]);
    component.photo.set(a);
    await component.navigateAdjacentPhoto(1);
    expect(mockRouter.navigate).toHaveBeenCalledExactlyOnceWith(['/photo'], {
      queryParams: { path: b.path }, state: { photoOrigin: 'timeline' }, replaceUrl: true,
    });
    component.goBack(); expect(mockLocation.back).toHaveBeenCalledOnce();
  });

  // Explicit hook timeout above the default 10s: under full-suite load, many
  // workers resolving dynamic import() chunks concurrently can contend for
  // longer than that, and this hook flaking looks like a broken suite rather
  // than the load-dependent timing issue it actually is.
  beforeAll(async () => {
    ({ PhotoDetailComponent } = await import('./photo-detail.component'));
  }, 20000);

  beforeEach(() => {
    vi.spyOn(PhotoStackService.prototype, 'byPhoto').mockReturnValue(of(null));
    changes$ = new Subject<AssistantChangeBatch>();
    mockApi = {
      get: vi.fn(() => of(samplePhoto)),
      post: vi.fn(() => of({})),
      put: vi.fn(() => of({})),
      delete: vi.fn(() => of({})),
      imageUrl: vi.fn((path: string) => `/image?path=${encodeURIComponent(path)}`),
      downloadUrl: vi.fn((path: string, type = 'original', profile?: string) => `/api/download?path=${encodeURIComponent(path)}&type=${type}${profile ? '&profile=' + profile : ''}`),
      getRaw: vi.fn(() => of(new Blob(['test'], { type: 'image/jpeg' }))),
    };
    mockRouter = { url: '/photo', navigate: vi.fn(), currentNavigation: () => null, events: new Subject() };
    mockLocation = { back: vi.fn(), path: vi.fn(() => '/photo'), getState: vi.fn(() => history.state ?? {}), replaceState: vi.fn() };
    mockRoute = {
      snapshot: {
        queryParamMap: { get: vi.fn((key: string) => key === 'path' ? '/photos/test.jpg' : null) },
      },
      queryParamMap: new BehaviorSubject(convertToParamMap({ path: '/photos/test.jpg' })),
    };
    const status = signal({ user_id: 'test' });
    mockAuth = { status, identity: () => status().user_id, session: computed(() => status()?.user_id ?? null), isEdition: signal(true), downloadProfiles: signal([]) };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(undefined) })), openDialogs: [] };
  });

  it('opens the manual editor with no detections and patches confirmed membership after navigation', async () => {
    createComponent();
    const original = makePhoto({ path: '/zero.jpg', face_count: 0, unassigned_faces: 0, persons: [] });
    const next = makePhoto({ path: '/next.jpg', persons: [{ id: 8, name: 'Next' }] });
    const store = TestBed.inject(GalleryStore);
    store.photos.set([original, next]);
    vi.spyOn(store, 'reloadPersonOptions').mockResolvedValue();
    component.photo.set(original);
    await component.openManualFaces(original);
    const options = mockDialog.open.mock.calls[0][1];
    expect(options.data.path).toBe('/zero.jpg');
    component.photo.set(next);
    mockApi.get.mockReturnValue(of({ ...original, persons: [{ id: 5, name: 'Ada' }], unassigned_faces: 0 }));
    await options.data.onCommitted();
    expect(store.photos()[0].persons).toEqual([{ id: 5, name: 'Ada' }]);
    expect(component.photo().path).toBe('/next.jpg');
    expect(component.photo().persons).toEqual(next.persons);
  });

  it.each([{ persons: [] }, { persons: [{ id: 8, name: 'Grace' }] }])('refreshes a person-filtered gallery after a manual mark is removed or reassigned: %j', async ({ persons }) => {
    createComponent();
    const original = makePhoto({ path: '/manual.jpg', persons: [{ id: 5, name: 'Ada' }] });
    const remaining = makePhoto({ path: '/remaining.jpg', persons: [{ id: 5, name: 'Ada' }] });
    const other = makePhoto({ path: '/other.jpg', persons: [{ id: 9, name: 'Other' }] });
    const store = TestBed.inject(GalleryStore);
    store.filters.update(f => ({ ...f, person_id: '5', camera: 'Canon' }));
    mockApi.get.mockReturnValue(of({ photos: [original, remaining], total: 2, has_more: false }));
    await store.loadPhotos();
    store.photos.set([original, remaining]);
    store.total.set(2);
    vi.spyOn(store, 'reloadPersonOptions').mockResolvedValue();
    component.photo.set(original);
    await component.openManualFaces(original);
    const committed = mockDialog.open.mock.calls[0][1].data.onCommitted;
    component.photo.set(other);
    mockApi.get.mockImplementation((url: string) => {
      if (url === '/photo') return of({ ...original, persons });
      if (url === '/photos') return of({ photos: [remaining], total: 1, has_more: false });
      return of({});
    });

    mockApi.post.mockReturnValue(of({ photos: [] }));
    await committed();

    expect(store.photos().map(p => p.path)).toEqual(['/remaining.jpg']);
    expect(store.total()).toBe(1);
    expect(store.filters()).toMatchObject({ person_id: '5', camera: 'Canon' });
    expect(mockApi.post).toHaveBeenCalledWith('/photos/by_paths', expect.objectContaining({
      paths: ['/manual.jpg'], filters: expect.objectContaining({ person_id: '5', camera: 'Canon' }),
    }));
    expect(component.photo()).toEqual(other);
    expect(mockRouter.navigate).not.toHaveBeenCalled();
  });

  it.each([
    ['manual_faces_need_review', false], ['manual_faces_need_review', true],
    ['faces_need_names', false], ['faces_need_names', true],
  ] as const)('refreshes the %s queue without clearing newer selection or pins (pinned=%s)', async (queue, pinned) => {
    createComponent();
    const original = makePhoto({ path: '/manual.jpg' });
    const other = makePhoto({ path: '/other.jpg' });
    const store = TestBed.inject(GalleryStore);
    store.filters.update(f => ({ ...f, [queue]: true }));
    mockApi.get.mockReturnValue(of({ photos: [original, other], total: 2, has_more: false }));
    await store.loadPhotos();
    vi.spyOn(store, 'reloadPersonOptions').mockResolvedValue();
    component.photo.set(original);
    await component.openManualFaces(original);
    const committed = mockDialog.open.mock.calls[0][1].data.onCommitted;
    store.selectedPaths.set(new Set(['/other.jpg']));
    if (pinned) store.pinnedPaths.set(['/manual.jpg', '/other.jpg']);
    component.photo.set(other);
    mockApi.get.mockReturnValue(of({ ...original, persons: [] }));
    mockApi.post.mockReturnValue(of({ photos: pinned ? [original] : [] }));
    await committed();
    expect(store.selectedPaths()).toEqual(new Set(['/other.jpg']));
    expect(store.pinnedPaths()).toEqual(pinned ? ['/manual.jpg', '/other.jpg'] : null);
    expect(store.photos().map(p => p.path)).toEqual(pinned ? ['/manual.jpg', '/other.jpg'] : ['/other.jpg']);
    expect(component.photo()).toEqual(other);
    expect(mockApi.post).toHaveBeenCalledWith('/photos/by_paths', pinned
      ? { paths: ['/manual.jpg'] }
      : expect.objectContaining({ filters: expect.objectContaining({ [queue]: '1' }) }));
  });

  it('refreshes persisted person membership after the detail component is destroyed', async () => {
    createComponent();
    const original = makePhoto({ path: '/zero.jpg', persons: [] });
    const store = TestBed.inject(GalleryStore);
    store.photos.set([original]);
    vi.spyOn(store, 'reloadPersonOptions').mockResolvedValue();
    component.photo.set(original);
    await component.openManualFaces(original);
    const committed = mockDialog.open.mock.calls[0][1].data.onCommitted;
    mockApi.get.mockReturnValue(of({ ...original, persons: [{ id: 5, name: 'Ada' }] }));
    TestBed.resetTestingModule();
    await committed();
    expect(store.photos()[0].persons).toEqual([{ id: 5, name: 'Ada' }]);
  });

  function renderDetail() {
    TestBed.configureTestingModule({
      imports: [PhotoDetailComponent],
      providers: [
        { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
        { provide: ApiService, useValue: mockApi },
        { provide: Router, useValue: mockRouter },
        { provide: Location, useValue: mockLocation },
        { provide: ActivatedRoute, useValue: mockRoute },
        { provide: AuthService, useValue: mockAuth },
        { provide: MatDialog, useValue: mockDialog },
        { provide: I18nService, useValue: { t: (key: string) => key, locale: () => 'en', translations: () => ({}) } },
      ],
    });
    const view = TestBed.createComponent(PhotoDetailComponent);
    vi.spyOn(view.componentInstance, 'ngOnInit').mockResolvedValue(undefined);
    return view;
  }

  it('names decision segments with their visible labels and updates the pressed state after confirmed edits', async () => {
    mockApi.post.mockImplementation((url: string) => of(url === '/photo/toggle_rejected'
      ? { is_rejected: true, is_favorite: null, star_rating: null } : {}));
    const view = renderDetail();
    const translations: Record<string, string> = { 'review.keep': 'Behalten', 'gallery.metadata.undecided': 'Unentschieden', 'gallery.selection.reject': 'Ablehnen' };
    vi.spyOn(TestBed.inject(I18nService), 't').mockImplementation(key => translations[key] ?? key);
    view.componentInstance.photo.set(makePhoto({ path: samplePhoto.path }));
    view.detectChanges();
    await view.whenStable();
    const root = view.nativeElement as HTMLElement;
    const keep = root.querySelector<HTMLButtonElement>('[data-photo-keep]')!;
    const undecided = root.querySelector<HTMLButtonElement>('[data-photo-undecided]')!;
    const reject = root.querySelector<HTMLButtonElement>('[data-photo-reject]')!;
    for (const [button, label] of [[keep, 'Behalten'], [undecided, 'Unentschieden'], [reject, 'Ablehnen']] as const) {
      expect(button.getAttribute('aria-label')).toBeNull();
      expect(button.textContent).toContain(label);
    }
    keep.click(); await view.whenStable(); view.detectChanges();
    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_review', { photo_paths: [samplePhoto.path], decision: 'kept' });
    expect(keep.getAttribute('aria-pressed')).toBe('true');
    expect(undecided.getAttribute('aria-pressed')).toBe('false');
    undecided.click(); await view.whenStable(); view.detectChanges();
    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_review', { photo_paths: [samplePhoto.path], decision: 'undecided' });
    expect(undecided.getAttribute('aria-pressed')).toBe('true');
    reject.click(); await view.whenStable(); view.detectChanges();
    expect(reject.getAttribute('aria-pressed')).toBe('true');
    expect(undecided.getAttribute('aria-pressed')).toBe('false');
    const zoom = root.querySelector<HTMLButtonElement>('app-rendition-readout button[aria-label="gallery.compare.rendition.zoom_out"]')!;
    expect(zoom.disabled).toBe(true);
  });

  it('refreshes rendered face boxes after every committed manual edit', async () => {
    let faces: object[] = [];
    mockApi.get.mockImplementation((url: string) => {
      if (url === '/photo/faces') return of({ faces });
      if (url === '/photo') return of(samplePhoto);
      return of({});
    });
    const view = renderDetail();
    vi.spyOn(TestBed.inject(GalleryStore), 'reloadPersonOptions').mockResolvedValue();
    view.componentInstance.photo.set(makePhoto({ path: samplePhoto.path, image_width: 6000, image_height: 4000 }));
    view.detectChanges();
    await view.whenStable();
    (view.componentInstance as any).dialog = mockDialog;
    await (view.componentInstance as any).openManualFaces(view.componentInstance.photo());
    const committed = mockDialog.open.mock.calls.at(-1)![1].data.onCommitted;
    expect(view.nativeElement.querySelectorAll('[data-face]')).toHaveLength(0);
    for (const box of [[0.1, 0.2, 0.3, 0.4], [0.2, 0.3, 0.5, 0.6]]) {
      faces = [{ id: 42, person_id: 1, person_name: 'Alice', box }];
      await committed();
      view.detectChanges();
      const rect = view.nativeElement.querySelector('[data-face]');
      expect(rect).not.toBeNull();
      expect(Number(rect.getAttribute('x'))).toBe(box[0] * 6000);
      expect(view.nativeElement.querySelector('app-photo-face-layer text').textContent).toContain('Alice');
    }
    faces = [];
    await committed();
    view.detectChanges();
    expect(view.nativeElement.querySelectorAll('[data-face]')).toHaveLength(0);
  });

  it.each(['navigate', 'destroy'] as const)('does not reload obsolete face boxes after %s', async (leave) => {
    mockApi.get.mockImplementation((url: string) => url === '/photo/faces' ? of({ faces: [] }) : of(samplePhoto));
    const view = renderDetail();
    vi.spyOn(TestBed.inject(GalleryStore), 'reloadPersonOptions').mockResolvedValue();
    view.componentInstance.photo.set(makePhoto({ path: samplePhoto.path }));
    view.detectChanges();
    await view.whenStable();
    (view.componentInstance as any).dialog = mockDialog;
    await (view.componentInstance as any).openManualFaces(view.componentInstance.photo());
    const committed = mockDialog.open.mock.calls.at(-1)![1].data.onCommitted;
    if (leave === 'destroy') {
      view.destroy();
    } else {
      view.componentInstance.photo.set(makePhoto({ path: '/other.jpg' }));
      view.detectChanges();
      await view.whenStable();
    }
    mockApi.get.mockClear();
    await committed();
    expect(mockApi.get.mock.calls.filter(([url]) => url === '/photo/faces')).toEqual([]);
    expect(mockApi.get).toHaveBeenCalledWith('/photo', { path: samplePhoto.path });
  });

  it('offers on-demand distributions for finite scores in the remembered metric tab', () => {
    localStorage.setItem('facet_photo_detail_tab', 'quality');
    const photo = makePhoto({ path: samplePhoto.path, aesthetic: 7.2 });
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? photo : {}));
    const view = renderDetail();
    TestBed.inject(GalleryStore).metricRanges.set({
      min_aesthetic: { column: 'aesthetic', min: 0, max: 10, buckets: [1, 1] },
    });
    view.componentInstance.photo.set(photo);
    view.detectChanges();
    const charts = view.debugElement.queryAll(By.css('[data-photo-inspector] app-photo-metrics-tabs app-metric-distribution'));
    expect(charts.some(row => row.componentInstance.column() === 'aesthetic' && row.componentInstance.value() === 7.2)).toBe(true);
    expect(mockApi.get.mock.calls.some(([url]) => url === '/stats/metric_distribution')).toBe(false);
  });

  it('places the aggregate in its library distribution on the metric tabs\' assessment line', () => {
    let photo = makePhoto({ path: samplePhoto.path, aggregate: 6.4 });
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? photo : {}));
    const view = renderDetail();
    TestBed.inject(GalleryStore).metricRanges.set({
      min_score: { column: 'aggregate', min: 0, max: 10, buckets: [1, 1] },
    });
    view.componentInstance.photo.set(photo);
    view.detectChanges();
    const ranks = () => view.debugElement.queryAll(By.css('[data-photo-inspector] app-photo-metrics-tabs app-photo-assessment app-metric-rank'));
    expect(ranks()).toHaveLength(1);
    expect(ranks()[0].componentInstance.value()).toBe(6.4);
    expect(ranks()[0].nativeElement.querySelector('[tabindex="0"]')).not.toBeNull();
    photo = makePhoto({ path: samplePhoto.path, aggregate: null });
    view.componentInstance.photo.set(photo); view.detectChanges();
    expect(ranks()).toHaveLength(0);
  });

  it('loads the library distributions on a deep-linked open', async () => {
    createComponent();
    const ensure = vi.spyOn(TestBed.inject(GalleryStore), 'ensureMetricRanges').mockResolvedValue();
    await component.ngOnInit();
    expect(ensure).toHaveBeenCalled();
  });

  it.each([
    { kept: true, decision: 'undecided', icon: 'flag' },
    { kept: false, decision: 'kept', icon: 'outlined_flag' },
  ])('Keep toggle on a photo with is_kept=$kept sends $decision, shows $icon and flips its state', async ({ kept, decision, icon }) => {
    const view = renderDetail();
    view.componentInstance.photo.set(makePhoto({ is_kept: kept, is_rejected: !kept }));
    mockApi.post.mockReturnValue(of({}));
    view.detectChanges();
    const keep = view.nativeElement.querySelector('[data-photo-keep]') as HTMLButtonElement;
    expect(keep.getAttribute('aria-pressed')).toBe(String(kept));
    expect(keep.querySelector('mat-icon')!.textContent!.trim()).toBe(icon);
    keep.click();
    await view.whenStable();
    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_review', { photo_paths: [view.componentInstance.photo()!.path], decision });
    view.detectChanges();
    expect(view.componentInstance.photo()).toMatchObject({ is_kept: !kept, is_rejected: false });
    expect(keep.getAttribute('aria-pressed')).toBe(String(!kept));
    expect(keep.querySelector('mat-icon')!.textContent!.trim()).not.toBe(icon);
  });

  describe('Keep and Undecided for a non-edition multi-user account', () => {
    beforeEach(() => {
      mockAuth.isEdition.set(false);
      mockAuth.status.set({ multi_user: true, authenticated: true });
    });

    it('hides Keep and Undecided but keeps the rating, favourite and reject controls on an ordinary photo', () => {
      const view = renderDetail();
      view.componentInstance.photo.set(makePhoto());
      view.detectChanges();
      const root = view.nativeElement as HTMLElement;
      expect(root.querySelector('[data-photo-keep]')).toBeNull();
      expect(root.querySelector('[data-photo-undecided]')).toBeNull();
      expect(root.querySelector('[data-photo-reject]')).not.toBeNull();
    });

    it('shows Keep and Undecided for a logical-review photo, which saves through the account endpoint', () => {
      const view = renderDetail();
      const state = { asset_id: 'asset', group_revision: 1, revision: 0, input_token: 'old', source_path: samplePhoto.path,
        values: { star_rating: 3, is_favorite: 0, is_kept: 0, is_rejected: 0 },
        origins: { star_rating: 'file', is_favorite: 'file', is_kept: 'file', is_rejected: 'file' } };
      view.componentInstance.photo.set(makePhoto({ logical_review: state } as any));
      view.detectChanges();
      const root = view.nativeElement as HTMLElement;
      expect(root.querySelector('[data-photo-keep]')).not.toBeNull();
      expect(root.querySelector('[data-photo-undecided]')).not.toBeNull();
    });

    it('ignores the keep shortcut on an ordinary photo', () => {
      createComponent();
      component.photo.set({ ...samplePhoto });
      const reviewPhoto = vi.spyOn(component, 'reviewPhoto').mockResolvedValue(undefined);
      const event = new KeyboardEvent('keydown', { cancelable: true, key: 'k' });
      component.onReviewKey(event);
      expect(event.defaultPrevented).toBe(false);
      expect(reviewPhoto).not.toHaveBeenCalled();
    });
  });

  it('shows catalog removal only for rejected, non-kept photos and guards direct invocation', async () => {
    const view = renderDetail();
    const detail = view.componentInstance as any;
    const remove = vi.spyOn(detail.photoActions, 'removeFromCatalog').mockResolvedValue([]);
    const trash = vi.spyOn(detail.photoActions, 'deletePhotos').mockResolvedValue(null);
    const confirmation = vi.spyOn(detail.dialog, 'open');
    for (const state of [{ is_rejected: false, is_kept: false }, { is_rejected: false, is_kept: true }, { is_rejected: true, is_kept: true }]) {
      detail.photo.set(makePhoto(state)); view.detectChanges();
      expect(view.nativeElement.querySelector('[aria-label="photo_detail.remove_catalog.action"]')).toBeNull();
      await detail.removeFromCatalog();
      detail.deletePhoto();
    }
    expect(remove).not.toHaveBeenCalled();
    expect(trash).not.toHaveBeenCalled();
    expect(confirmation).not.toHaveBeenCalled();
    detail.photo.set(makePhoto({ is_rejected: true, is_kept: false })); view.detectChanges();
    const button = view.nativeElement.querySelector('[aria-label="photo_detail.remove_catalog.action"]') as HTMLButtonElement;
    expect(button).not.toBeNull();
    expect(button.className).toContain('mat-sys-error');
    button.click(); await view.whenStable();
    expect(remove).toHaveBeenCalledExactlyOnceWith([detail.photo().path], expect.any(Function));
  });

  it('refuses a stale trash confirmation after the photo becomes kept', async () => {
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? makePhoto({ path: samplePhoto.path, is_rejected: true, is_kept: false }) : { faces: [] }));
    const view = renderDetail(); const detail = view.componentInstance as any;
    view.detectChanges(); await view.whenStable();
    const closed = new Subject<unknown>();
    const open = vi.spyOn(detail.dialog, 'open').mockReturnValue({ afterClosed: () => closed } as any);
    const erase = vi.spyOn(detail.photoActions, 'deletePhotos').mockResolvedValue(null);
    detail.photo.set(makePhoto({ is_rejected: true, is_kept: false }));
    detail.deletePhoto();
    await vi.waitFor(() => expect(open).toHaveBeenCalled());
    detail.photo.set(makePhoto({ is_rejected: false, is_kept: true }));
    closed.next({ include_companions: false });
    await view.whenStable();
    expect(erase).not.toHaveBeenCalled();
  });

  it.each(['deleted', 'removed_missing'] as const)('repairs the gallery without touching the newer photo after late trash (%s)', async outcome => {
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? makePhoto({ path: samplePhoto.path, is_rejected: true, is_kept: false }) : { faces: [] }));
    const view = renderDetail(); const detail = view.componentInstance as any;
    view.detectChanges(); await view.whenStable();
    const closed = new Subject<unknown>();
    vi.spyOn(detail.dialog, 'open').mockReturnValue({ afterClosed: () => closed } as any);
    let finish!: (value: any) => void;
    const result = new Promise(resolve => { finish = resolve; });
    const erase = vi.spyOn(detail.photoActions, 'deletePhotos').mockReturnValue(result as any);
    const back = vi.spyOn(detail, 'goBack');
    const remove = vi.spyOn(detail.store, 'removePhotos');
    const snack = vi.spyOn(detail.snackBar, 'open');
    const original = makePhoto({ is_rejected: true, is_kept: false });
    detail.photo.set(original); detail.deletePhoto();
    await vi.waitFor(() => expect(detail.dialog.open).toHaveBeenCalled());
    closed.next({ include_companions: false });
    expect(erase).toHaveBeenCalledExactlyOnceWith([original.path], { include_companions: false });
    const newer = makePhoto({ path: '/newer-photo.jpg' });
    detail.photo.set(newer);
    snack.mockClear();
    finish({ deleted: outcome === 'deleted' ? [original.path] : [], removed_missing: outcome === 'removed_missing' ? [original.path] : [] });
    await result; await view.whenStable();
    expect(back).not.toHaveBeenCalled();
    expect(detail.photo()).toBe(newer);
    expect(remove).toHaveBeenCalledExactlyOnceWith([original.path]);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['owner', 'token'] as const)('does not reconcile late trash into a changed %s', async invalidation => {
    const view = renderDetail(); const detail = view.componentInstance as any;
    view.detectChanges(); await view.whenStable();
    Object.assign(mockAuth, { token: 'original-token' });
    const closed = new Subject<unknown>();
    const open = vi.spyOn(detail.dialog, 'open').mockReturnValue({ afterClosed: () => closed } as any);
    let finish!: (value: any) => void;
    const response = new Promise(resolve => { finish = resolve; });
    const erase = vi.spyOn(detail.photoActions, 'deletePhotos').mockReturnValue(response as any);
    const remove = vi.spyOn(detail.store, 'removePhotos');
    const back = vi.spyOn(detail, 'goBack');
    const snack = vi.spyOn(detail.snackBar, 'open');
    const original = makePhoto({ is_rejected: true, is_kept: false });
    detail.photo.set(original); detail.deletePhoto();
    await vi.waitFor(() => expect(open).toHaveBeenCalled());
    closed.next({ include_companions: false });
    expect(erase).toHaveBeenCalledTimes(1);
    if (invalidation === 'owner') mockAuth.status.set({ user_id: 'other-account' });
    else Object.assign(mockAuth, { token: 'rotated-token' });
    snack.mockClear();
    finish({ deleted: [original.path], removed_missing: [] });
    await response; await view.whenStable();
    expect(remove).not.toHaveBeenCalled();
    expect(back).not.toHaveBeenCalled();
    expect(snack).not.toHaveBeenCalled();
  });

  it('folds the secondary header actions into a More menu below md while the title keeps min-w-0', () => {
    const view = renderDetail();
    view.componentInstance.photo.set(makePhoto({}));
    view.detectChanges();
    const root = view.nativeElement as HTMLElement;
    const more = root.querySelector('button[aria-label="nav.more"]') as HTMLButtonElement;
    expect(more.classList.contains('md:!hidden')).toBe(true);
    const refresh = root.querySelector('button[aria-label="photo_refresh.title"]') as HTMLButtonElement;
    expect(refresh.classList.contains('max-md:!hidden')).toBe(true);
    expect(root.querySelector('h1')?.textContent).toContain(view.componentInstance.photo()!.filename);
    expect(root.querySelector('h1')?.getAttribute('title')).toBe(view.componentInstance.photo()!.filename);
  });

  it('uses distinct icons for face visibility and drawing a manual face box', () => {
    localStorage.removeItem('facet_face_box_mode');
    const view = renderDetail(); view.componentInstance.photo.set(makePhoto({})); view.detectChanges();
    const root = view.nativeElement as HTMLElement;
    const visibility = root.querySelector('[data-face-box-mode] mat-icon')?.textContent?.trim();
    const drawing = root.querySelector('[aria-label="manual_faces.title"] mat-icon')?.textContent?.trim();
    expect(drawing).toBe('highlight_alt'); expect(drawing).not.toBe(visibility);
  });

  it('cycles the face-box button hover, always, off, remembering each and telling the layer', () => {
    localStorage.removeItem('facet_face_box_mode');
    localStorage.removeItem('facet_show_face_boxes');
    const view = renderDetail();
    view.componentInstance.photo.set(makePhoto({}));
    view.detectChanges();
    const root = view.nativeElement as HTMLElement;
    const button = () => root.querySelector('button[data-face-box-mode]') as HTMLButtonElement;
    const layer = () => view.debugElement.query((d) => d.name === 'app-photo-face-layer').componentInstance as { mode: () => string };
    const seen: [string | null, string, string | null][] = [];
    for (let i = 0; i < 4; i++) {
      seen.push([button().getAttribute('aria-label'), layer().mode(), localStorage.getItem('facet_face_box_mode')]);
      button().click();
      view.detectChanges();
    }
    expect(seen).toEqual([
      ['photo_faces.box_mode_hover', 'hover', null],
      ['photo_faces.box_mode_always', 'always', 'always'],
      ['photo_faces.box_mode_off', 'off', 'off'],
      ['photo_faces.box_mode_hover', 'hover', 'hover'],
    ]);
    localStorage.removeItem('facet_face_box_mode');
  });

  it('a Persons avatar opens the face menu on its largest face, even with boxes off; See all photos navigates', async () => {
    localStorage.setItem('facet_face_box_mode', 'off');
    mockAuth.isEdition.set(true);
    mockApi.get.mockImplementation((url: string) => url === '/photo/faces'
      ? of({ faces: [
        { id: 11, face_index: 0, person_id: 1, person_name: 'Alice', box: [0, 0, 0.1, 0.1] },
        { id: 12, face_index: 1, person_id: 1, person_name: 'Alice', box: [0.2, 0.2, 0.7, 0.7] },
        { id: 13, face_index: 2, person_id: 4, person_name: 'Bob', box: [0, 0, 0.9, 0.9] },
      ] })
      : of(samplePhoto));
    const view = renderDetail();
    view.componentInstance.photo.set(makePhoto({ persons: [{ id: 1, name: 'Alice' }], image_width: 1000, image_height: 800 }));
    view.detectChanges();
    await view.whenStable();
    view.detectChanges();
    const avatar = view.nativeElement.querySelector('button[data-person-avatar]') as HTMLButtonElement;
    expect(avatar.getAttribute('aria-haspopup')).toBe('menu');
    avatar.click();
    view.detectChanges();
    await view.whenStable();
    expect(mockRouter.navigate).not.toHaveBeenCalled();
    const menu = view.debugElement.query((d) => d.name === 'app-person-face-menu' && d.parent?.name !== 'app-photo-face-layer').componentInstance as { target: () => unknown };
    expect(menu.target()).toEqual({ person: { id: 1, name: 'Alice' }, face: { id: 12, automatic: true } });
    const items = [...document.querySelectorAll('.mat-mdc-menu-panel [mat-menu-item]')] as HTMLElement[];
    expect(items.some((b) => b.textContent!.includes('photo_faces.not_person'))).toBe(true);
    items.find((b) => b.textContent!.includes('photo_faces.view_photos'))!.click();
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], { queryParams: { person_id: '1' } });
    localStorage.removeItem('facet_face_box_mode');
  });

  it('opens the critique dialog from the header Analysis button and from Why this score?', async () => {
    const view = renderDetail();
    TestBed.inject(GalleryStore).config.set({ features: { show_critique: true, show_vlm_critique: true } } as never);
    const photo = makePhoto();
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? photo : {}));
    const open = vi.spyOn(TestBed.inject(PhotoActionsService), 'openCritique').mockImplementation(() => undefined);
    view.componentInstance.photo.set(photo);
    view.detectChanges(); await view.whenStable(); view.detectChanges();
    const root = view.nativeElement as HTMLElement;
    const button = root.querySelector<HTMLButtonElement>('button[aria-label="photo_detail.analysis"]')!;
    expect(button.hasAttribute('aria-expanded')).toBe(false);
    expect(button.hasAttribute('aria-controls')).toBe(false);
    button.click();
    expect(open).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ path: photo.path }));
    root.querySelector<HTMLButtonElement>('[data-photo-inspector] app-photo-metrics-tabs [data-explain-score]')!.click();
    expect(open).toHaveBeenCalledTimes(2);
    expect(open.mock.calls[1][0]).toMatchObject({ path: photo.path });
    expect(root.querySelector('app-photo-analysis')).toBeNull();
    expect(mockRouter.navigate).not.toHaveBeenCalled();
    expect(mockApi.post.mock.calls.filter(([url]) => url === '/critique/vlm')).toHaveLength(0);
  });

  it('lays the inspector out like the gallery rail: untitled Review, then the metric tabs, no accordions', async () => {
    localStorage.setItem('facet_photo_detail_tab', 'technical');
    const view = renderDetail();
    const photo = makePhoto({ camera_model: 'X100V', iso: 200, persons: [{ id: 1, name: 'Alice' }], unassigned_faces: 2 });
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? photo : {}));
    TestBed.inject(GalleryStore).config.set({ features: { show_critique: false } } as never);
    view.componentInstance.photo.set(photo);
    view.detectChanges(); await view.whenStable(); view.detectChanges();
    const aside = (view.nativeElement as HTMLElement).querySelector<HTMLElement>('[data-photo-inspector]')!;
    for (const removed of ['[data-photo-info]', '[data-photo-analysis]', '[data-metric-section]', '#photo-analysis']) {
      expect(aside.querySelector(removed)).toBeNull();
    }
    const review = aside.querySelector<HTMLElement>('[data-photo-review]')!;
    expect(review.classList.contains('border-t')).toBe(false);
    expect(review.querySelector('h2')!.classList.contains('sr-only')).toBe(true);
    // The favourite shares the stars' row but not their "Rating" group, so it is not announced as a rating.
    const row = review.querySelector<HTMLElement>('[data-photo-rating-row]')!;
    expect(row.querySelector('[role="group"][aria-label="photo_detail.rating"]')).not.toBeNull();
    expect(row.querySelector(':scope > button[aria-label="rating.favorite"]')).not.toBeNull();
    expect(row.querySelector('[role="group"] button[aria-label="rating.favorite"]')).toBeNull();
    const tabs = aside.querySelector<HTMLElement>('app-photo-metrics-tabs')!;
    expect(tabs).not.toBeNull();
    expect(review.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(tabs.querySelectorAll('[role="tab"]')).toHaveLength(5);
    expect(tabs.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute('aria-label')).toBe('photo_detail.technical');
    const people = aside.querySelector<HTMLElement>('[data-photo-people]')!;
    expect(people.tagName).toBe('SECTION');
    expect(people.textContent).toContain('Alice');
    expect(people.textContent).toContain('photo_detail.unassigned_faces');
    // Metadata sources and related files close the panel as one single-open Material accordion, both collapsed.
    const fileDetails = aside.querySelector<HTMLElement>('mat-accordion[data-file-details]')!;
    expect(fileDetails).not.toBeNull();
    expect(aside.lastElementChild).toBe(fileDetails);
    for (const panel of ['[data-photo-provenance]', '[data-related-files]']) {
      expect(fileDetails.querySelector(`mat-expansion-panel${panel}`)).not.toBeNull();
      expect(fileDetails.querySelector(`${panel} mat-expansion-panel-header`)!.getAttribute('aria-expanded')).toBe('false');
    }
    expect(aside.querySelector('details[data-logical-asset]')).toBeNull();
    expect(mockApi.get.mock.calls.filter(([url]) => url === '/photo/provenance')).toHaveLength(0);
    expect(mockApi.get.mock.calls.filter(([url]) => url === '/photo/related_files')).toHaveLength(0);
  });

  it('orders the inspector Review, date line, Describe, metric tabs, set, file details and pins Review on wide screens', async () => {
    const view = renderDetail();
    const photo = makePhoto({ camera_model: 'Canon EOS R6', focal_length: 85, f_stop: 2.8, shutter_speed: '0.01', iso: 4000,
      caption: 'A street', tags_list: ['street'], gps_latitude: 1, gps_longitude: 2, persons: [{ id: 1, name: 'Alice' }],
      burst_group_id: 7 });
    const set = { kind: 'burst', count: 5, ev_span: null, members: [1, 2, 3, 4, 5].map(n => ({ path: `/m${n}.jpg`, ev_offset: null, ai_edit_of: null, is_blink: false, preview_revision: null })) };
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? photo : url === '/photo/set' ? set : {}));
    view.componentInstance.photo.set(photo);
    for (let i = 0; i < 3; i++) {
      view.detectChanges();
      await new Promise<void>(resolve => setTimeout(resolve, 0));
    }
    view.detectChanges();
    const aside = (view.nativeElement as HTMLElement).querySelector<HTMLElement>('[data-photo-inspector]')!;
    const order = ['[data-photo-review]', '[data-photo-when]', '[data-photo-describe]', 'app-photo-metrics-tabs', '[data-photo-set]', '[data-file-details]']
      .map(selector => aside.querySelector<HTMLElement>(selector)!);
    order.forEach(element => expect(element).not.toBeNull());
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    const describe = aside.querySelector<HTMLElement>('[data-photo-describe]')!;
    const fields = ['[data-photo-caption]', '[data-testid="tags-section"]', '[data-photo-location]', '[data-photo-people]']
      .map(selector => describe.querySelector<HTMLElement>(selector)!);
    fields.forEach(element => expect(element).not.toBeNull());
    for (let i = 1; i < fields.length; i++) {
      expect(fields[i - 1].compareDocumentPosition(fields[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(aside.querySelector('[data-photo-review]')!.className).toContain('lg:sticky');
    expect(aside.querySelector('[data-photo-set-strip]')!.className).toContain('lg:grid-cols-5');
    // Date and category share one line; the capture settings sit under it, always visible.
    const when = aside.querySelector<HTMLElement>('[data-photo-when]')!;
    expect(when.querySelector('[data-photo-date]')!.parentElement).toBe(when.querySelector('[data-photo-category]')!.parentElement);
    const exposure = when.querySelector<HTMLElement>('[data-photo-exposure]')!;
    expect([...exposure.querySelectorAll('span')].map(span => span.textContent!.trim())).toEqual(['Canon EOS R6', '85mm', 'f/2.8', '1/100', 'ISO 4000']);
    expect(exposure.getAttribute('aria-label')).toBe('photo_detail.capture_settings');
    // The rendition help sits beside the image readout, icon-only, not in the inspector (the metric tabs keep their own).
    expect([...aside.querySelectorAll('app-context-help')].filter(help => !help.closest('app-photo-metrics-tabs'))).toHaveLength(0);
    const readoutHelp = (view.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-image-readout] app-context-help button')!;
    expect(readoutHelp.getAttribute('aria-label')).toBe('gallery.compare.rendition.sources');
    expect(readoutHelp.textContent!.trim()).toBe('help_outline');
  });

  it('collapses empty caption, tags and location into compact add actions for editors only', async () => {
    const view = renderDetail();
    const photo = makePhoto({ caption: null, tags_list: [], manual_tags: [], gps_latitude: null, gps_longitude: null });
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? photo : {}));
    view.componentInstance.photo.set(photo);
    view.detectChanges(); await view.whenStable(); view.detectChanges();
    const root = view.nativeElement as HTMLElement;
    const add = root.querySelector<HTMLElement>('[data-photo-add]')!;
    expect([...add.querySelectorAll('button')].map(button => button.getAttribute('aria-label') ?? button.textContent!.trim()))
      .toEqual(['photo_detail.add_caption', 'manual_tags.add', 'photo_detail.add_location']);
    for (const absent of ['[data-photo-caption]', '[data-testid="tags-section"]', '[data-photo-location]']) {
      expect(root.querySelector(absent)).toBeNull();
    }
    expect(root.querySelector('[data-photo-describe]')!.textContent).not.toContain('—');
    mockAuth.isEdition.set(false); view.detectChanges();
    expect(root.querySelector('[data-photo-add]')).toBeNull();
  });

  it('recreates the location map on a visible container after changing GPS photos', async () => {
    const view = renderDetail();
    let photo = makePhoto({ gps_latitude: 1, gps_longitude: 2 });
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? photo : {}));
    let created!: () => void;
    let creation = new Promise<void>(resolve => { created = resolve; });
    leafletMock.map.mockClear(); leafletMockMap.remove.mockClear();
    leafletMock.map.mockImplementationOnce(() => { created(); return leafletMockMap; });
    view.componentInstance.photo.set(photo); view.detectChanges(); await creation;
    expect(leafletMock.map).toHaveBeenCalledOnce();
    creation = new Promise<void>(resolve => { created = resolve; });
    leafletMock.map.mockImplementationOnce(() => { created(); return leafletMockMap; });
    photo = makePhoto({ path: '/new-gps.jpg', gps_latitude: 3, gps_longitude: 4 });
    view.componentInstance.photo.set(photo); view.detectChanges(); await view.whenStable(); view.detectChanges(); await creation;
    expect(leafletMockMap.remove).toHaveBeenCalledOnce();
    expect(leafletMockMap.setView).toHaveBeenLastCalledWith([3, 4], 13);
    expect(leafletMock.map).toHaveBeenCalledTimes(2);
    view.destroy();
  });

  it('renders NULL and zero extended metrics in the actual detail template', () => {
    localStorage.setItem('facet_photo_detail_tab', 'quality');
    const view = renderDetail();
    TestBed.inject(GalleryStore).config.set({ populated_scores: ['aesthetic_v25', 'qrealign_score', 'deqa_score'] } as never);
    let observed = makePhoto({ aesthetic_v25: null, qrealign_score: 0, deqa_score: null });
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? observed : {}));
    view.componentInstance.photo.set(observed);
    view.detectChanges();
    expect(view.nativeElement.querySelector('[data-testid="qrealign_score-score"]').textContent.trim()).toBe('0.0');
    expect(view.nativeElement.querySelector('[aria-label="manual_faces.title"]')).not.toBeNull();
    for (const key of ['aesthetic_v25', 'deqa_score']) {
      expect(view.nativeElement.querySelector(`[data-testid="${key}-score"]`).textContent).toContain('tooltip.not_computed');
    }
    TestBed.inject(GalleryStore).config.set({ populated_scores: [] } as never);
    view.detectChanges();
    expect(view.nativeElement.querySelector('[data-testid="aesthetic_v25-row"]')).toBeNull();
    expect(view.nativeElement.querySelector('[data-testid="qrealign_score-score"]').textContent.trim()).toBe('0.0');
    observed = makePhoto();
    view.componentInstance.photo.set(observed);
    view.detectChanges();
    expect(view.nativeElement.querySelectorAll('app-extended-quality [data-testid$="-row"]').length).toBe(0);
  });

  it('shows an explicit face-IQA decline in the normal quality section, without hiding a real zero', () => {
    localStorage.setItem('facet_photo_detail_tab', 'quality');
    const observed = makePhoto({ face_quality_iqa: null, assessment_states: { face_quality_iqa: 'not_applicable' } });
    mockApi.get.mockImplementation((url: string) => of(url === '/photo' ? observed : {}));
    const view = renderDetail();
    view.componentInstance.photo.set(observed); view.detectChanges();
    const quality = view.nativeElement.querySelector('[data-photo-inspector] app-photo-metrics-tabs') as HTMLElement;
    const decline = quality.querySelector<HTMLDetailsElement>('[data-face-iqa-decline]')!;
    expect(decline.querySelector('summary')?.textContent).toContain('photo_detail.assessment.not_applicable');
    decline.open = true; decline.dispatchEvent(new Event('toggle')); view.detectChanges();
    expect(decline.textContent).toContain('photo_detail.assessment.face_iqa_declined_help');
    view.componentInstance.photo.set({ ...observed, face_quality_iqa: 0 }); view.detectChanges();
    expect(quality.querySelector('[data-face-iqa-decline]')).toBeNull();
    const row = Array.from(quality.querySelectorAll('app-metric-score-row')).find(node => node.textContent?.includes('tooltip.face_quality_iqa'));
    expect(row?.textContent).toContain('0.0');
    view.componentInstance.photo.set({ ...observed, assessment_states: {} }); view.detectChanges();
    expect(quality.querySelector('[data-face-iqa-decline]')).toBeNull();
  });

  it('should create', () => {
    createComponent();
    expect(component).toBeTruthy();
  });

  it.each(['k', 'K'])('ignores %s from a dialog button without saving or advancing', key => {
    createComponent();
    component.photo.set(makePhoto());
    mockDialog.openDialogs.push({});
    const event = new KeyboardEvent('keydown', { key, cancelable: true });
    const button = document.createElement('button');
    Object.defineProperty(event, 'target', { value: button });
    component.onReviewKey(event);
    expect(event.defaultPrevented).toBe(false);
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(mockRouter.navigate).not.toHaveBeenCalled();
  });

  it.each(['kept', 'undecided', 'rejected'])('refreshes progress after %s outside a review-status queue', async decision => {
    createComponent();
    const store = TestBed.inject(GalleryStore);
    const photo = makePhoto();
    component.photo.set(photo);
    store.photos.set([photo]);
    const count = vi.spyOn(store, 'loadReviewProgress').mockResolvedValue();
    mockApi.post.mockReturnValue(of({ is_rejected: true, is_favorite: null, star_rating: null }));
    if (decision === 'rejected') await component.toggleRejected(photo.path);
    else await component.reviewPhoto(decision);
    expect(count).toHaveBeenCalled();
  });

  function enterPhotoFromGallery(path: string): void {
    mockRouter.url = '/';
    (mockRouter.events as Subject<unknown>).next(new NavigationStart(1, '/photo?path=' + encodeURIComponent(path)));
    component.store.parkListingReads();
    mockRouter.url = '/photo?path=' + encodeURIComponent(path);
    (mockRouter.events as Subject<unknown>).next(new NavigationEnd(1, mockRouter.url, mockRouter.url));
  }

  describe('delayed review responses', () => {
    it.each(['kept', 'undecided', 'rejected'])('preserves navigation after %s', async decision => {
      createComponent();
      const store = TestBed.inject(GalleryStore);
      const a = makePhoto({ path: '/a.jpg' });
      const b = makePhoto({ path: '/b.jpg' });
      store.photos.set([a, b]);
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      const refresh = vi.spyOn(store, 'refreshReviewResults').mockResolvedValue();
      component.photo.set(a);
      const response = new Subject<any>();
      mockApi.post.mockReturnValue(response);
      const pending = decision === 'rejected' ? component.toggleRejected(a.path) : component.reviewPhoto(decision);
      component.photo.set(b);
      response.next({ is_rejected: true, is_favorite: null, star_rating: null });
      await pending;
      expect(component.photo()).toBe(b);
      expect(TestBed.inject(UserActivityJournal).since().items).toEqual([expect.objectContaining({
        kind: decision === 'rejected' ? 'reject' : 'review', paths: [a.path],
        value: decision === 'rejected' ? true : decision,
      })]);
      expect(mockRouter.navigate).not.toHaveBeenCalled();
      expect(refresh).toHaveBeenCalledOnce();
      expect(store.photos()[0]).toMatchObject({ path: a.path, is_kept: decision === 'kept', is_rejected: decision === 'rejected' });
    });
    it.each(['kept', 'undecided', 'rejected'])('preserves closed detail after %s', async decision => {
      createComponent();
      const store = TestBed.inject(GalleryStore);
      const a = makePhoto({ path: '/a.jpg' });
      component.photo.set(a);
      store.photos.set([a]);
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      const refresh = vi.spyOn(store, 'refreshReviewResults').mockResolvedValue();
      const response = new Subject<any>();
      mockApi.post.mockReturnValue(response);
      const pending = decision === 'rejected' ? component.toggleRejected(a.path) : component.reviewPhoto(decision);
      TestBed.resetTestingModule();
      response.next({ is_rejected: true, is_favorite: null, star_rating: null });
      await pending;
      expect(component.photo()).toBe(a);
      expect(refresh).toHaveBeenCalledOnce();
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });
    it.each(['kept', 'undecided', 'rejected'])('applies and journals %s that lands after the gallery view changed', async decision => {
      createComponent();
      const store = TestBed.inject(GalleryStore);
      const a = makePhoto({ path: '/a.jpg' });
      store.photos.set([a]);
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      const refresh = vi.spyOn(store, 'refreshReviewResults').mockResolvedValue();
      component.photo.set(a);
      const response = new Subject<any>();
      mockApi.post.mockReturnValue(response);
      const pending = decision === 'rejected' ? component.toggleRejected(a.path) : component.reviewPhoto(decision);
      store.filters.update(f => ({ ...f, path_prefix: '/elsewhere/' }));
      response.next({ is_rejected: true, is_favorite: null, star_rating: null });
      await pending;
      expect(component.photo()).toMatchObject({ path: a.path, is_kept: decision === 'kept', is_rejected: decision === 'rejected' });
      expect(refresh).not.toHaveBeenCalled();
      expect(mockRouter.navigate).not.toHaveBeenCalled();
      expect(TestBed.inject(UserActivityJournal).since().items).toEqual([expect.objectContaining({
        kind: decision === 'rejected' ? 'reject' : 'review', paths: [a.path],
        value: decision === 'rejected' ? true : decision,
      })]);
    });

    it('merges delayed Keep into current metadata', async () => {
      createComponent();
      const a = makePhoto({ star_rating: 1 });
      component.photo.set(a);
      const response = new Subject<any>();
      mockApi.post.mockReturnValue(response);
      const pending = component.reviewPhoto('kept');
      component.photo.set({ ...a, star_rating: 5, is_favorite: true });
      response.next({});
      await pending;
      expect(component.photo()).toMatchObject({ is_kept: true, star_rating: 5, is_favorite: true });
    });
    it('does not override Back started during a parked Keep refill', async () => {
      createComponent();
      const store = TestBed.inject(GalleryStore);
      const current = makePhoto({ path: '/current.jpg' });
      store.photos.set([current]);
      store.hasMore.set(true);
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      component.photo.set(current);
      enterPhotoFromGallery(current.path);
      const tail = new Subject<any>();
      let cancelled = false;
      mockApi.get.mockReturnValue(tail.pipe(finalize(() => { cancelled = true; })));
      const keeping = component.reviewPhoto('kept');
      await Promise.resolve();
      expect(mockApi.get).toHaveBeenCalledWith('/photos', expect.anything());
      (mockRouter.events as Subject<unknown>).next(new NavigationStart(2, '/'));
      await keeping;
      expect(cancelled).toBe(true);
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });
    it('advances last loaded row to refilled successor then supports Next', async () => {
      createComponent();
      const store = TestBed.inject(GalleryStore);
      const all = Array.from({ length: 128 }, (_, i) => makePhoto({ path: `/p${i + 1}.jpg` }));
      store.photos.set(all.slice(0, 64));
      store.hasMore.set(true);
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      component.photo.set(all[63]);
      enterPhotoFromGallery(all[63].path);
      const remaining = all.filter(p => p.path !== all[63].path);
      mockApi.get.mockImplementation((_url: string, params: { page: number }) => of({ photos: remaining.slice((params.page - 1) * 64, params.page * 64), total: 127, has_more: params.page === 1 }));
      await component.reviewPhoto('kept');
      expect(component.photo().path).toBe('/p65.jpg');
      mockRoute.snapshot.queryParamMap.get.mockReturnValue('/p65.jpg');
      await component.navigateAdjacentPhoto(1);
      expect(component.photo().path).toBe('/p66.jpg');
    });
  });

  describe('ngOnInit', () => {
    // The Angular Vitest builder runs with isolate: false, so this jsdom
    // `history` is the SAME object every later spec file in the worker sees.
    // Drive it only through the real replaceState API: shadowing the getter with
    // Object.defineProperty(history, 'state', { value }) outlives this file and
    // freezes history.state for whichever spec runs next (the gallery set-scope
    // tests failed that way, on the runs where the scheduler put them after
    // this file). src/test-setup.ts now fails the offending test outright.
    afterEach(() => {
      history.replaceState(null, '', location.href);
    });

    it('loads the current session photo snapshot without refetching it', async () => {
      history.replaceState({ photo: samplePhoto, photoSession: privateImageSessionKey() }, '', location.href);

      createComponent();
      await component.ngOnInit();

      expect(component.photo()).toEqual(samplePhoto);
      // The photo is not refetched; the only read is the library distributions.
      expect(mockApi.get.mock.calls.map(call => call[0])).toEqual(['/filter_options/metric_ranges']);
    });

    it.each(['missing', 'previous-session', 'wrong-path'] as const)('reauthorizes a %s history snapshot before exposing its metadata', async reason => {
      const oldSession = privateImageSessionKey();
      if (reason === 'previous-session') resetPrivateImageSession();
      const snapshot = { ...samplePhoto, filename: 'private-old-account.jpg', path: reason === 'wrong-path' ? '/other.jpg' : samplePhoto.path };
      history.replaceState({ photo: snapshot, ...(reason === 'missing' ? {} : { photoSession: oldSession }) }, '', location.href);
      const response = new Subject<typeof samplePhoto>();
      mockApi.get.mockImplementation((url: string) => url === '/photo' ? response : of({ ranges: {} }));
      createComponent();
      const loading = component.ngOnInit();

      expect(component.photo()).toBeNull();
      expect(mockApi.get).toHaveBeenCalledWith('/photo', { path: samplePhoto.path });
      response.next(samplePhoto);
      await loading;
      expect(component.photo()).toEqual(samplePhoto);
    });

    it('does not accept a pending initial API read after the same account starts a new credential session', async () => {
      history.replaceState({}, '', location.href);
      const response = new Subject<typeof samplePhoto>();
      mockApi.get.mockImplementation((url: string) => url === '/photo' ? response : of({ ranges: {} }));
      createComponent();
      const loading = component.ngOnInit();
      resetPrivateImageSession();
      response.next(samplePhoto);
      await loading;
      expect(component.photo()).toBeNull();
    });

    it('should load photo from API when no history state', async () => {
      history.replaceState({}, '', location.href);

      createComponent();
      await component.ngOnInit();

      expect(mockApi.get).toHaveBeenCalledWith('/photo', { path: '/photos/test.jpg' });
      expect(component.photo()).toBeTruthy();
    });

    it('should navigate to root when no path query param', async () => {
      history.replaceState({}, '', location.href);
      mockRoute.snapshot.queryParamMap.get = vi.fn(() => null);

      createComponent();
      await component.ngOnInit();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], { replaceUrl: true });
    });

    it('a link to a photo that no longer loads goes to the gallery without leaving the dead entry behind', async () => {
      history.replaceState({}, '', location.href);
      mockApi.get.mockReturnValue(throwError(() => new Error('404')));

      createComponent();
      await component.ngOnInit();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], { replaceUrl: true });
    });

    it('drops a first load that lands after Back moved the address', async () => {
      history.replaceState({}, '', location.href);
      const response = new Subject<typeof samplePhoto>();
      mockApi.get.mockReturnValue(response);

      createComponent();
      const init = component.ngOnInit();
      mockRoute.snapshot.queryParamMap.get = vi.fn((key: string) => key === 'path' ? '/photos/other.jpg' : null);
      response.next(samplePhoto);
      await init;

      expect(component.photo()).toBeNull();
    });

    it('a first load that fails after the page was left does not replace where the user went', async () => {
      history.replaceState({}, '', location.href);
      const response = new Subject<typeof samplePhoto>();
      mockApi.get.mockReturnValue(response);

      createComponent();
      const view = TestBed.createComponent(PhotoDetailComponent);
      view.detectChanges();
      view.destroy();
      response.error(new Error('404'));
      await new Promise<void>(resolve => setTimeout(resolve, 0));

      expect(mockApi.get).toHaveBeenCalledWith('/photo', { path: '/photos/test.jpg' });
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('a first load that fails after Back moved the address does not leave for the gallery', async () => {
      history.replaceState({}, '', location.href);
      const response = new Subject<typeof samplePhoto>();
      mockApi.get.mockReturnValue(response);

      createComponent();
      const init = component.ngOnInit();
      mockRoute.snapshot.queryParamMap.get = vi.fn((key: string) => key === 'path' ? '/photos/other.jpg' : null);
      response.error(new Error('404'));
      await init;

      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('should populate tags_list from tags when missing', async () => {
      history.replaceState({}, '', location.href);
      mockApi.get.mockReturnValue(of({ ...samplePhoto, tags_list: undefined, tags: 'a, b', persons: undefined }));

      createComponent();
      await component.ngOnInit();

      const photo = component.photo();
      expect(photo.tags_list).toEqual(['a', 'b']);
      expect(photo.persons).toEqual([]);
    });
  });

  describe('following the URL', () => {
    const earlier = { ...samplePhoto, path: '/photos/earlier.jpg', filename: 'earlier.jpg' };
    const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0));

    afterEach(() => {
      history.replaceState(null, '', location.href);
    });

    async function openedFromGallery() {
      history.replaceState({ photo: samplePhoto, photoSession: privateImageSessionKey() }, '', location.href);
      createComponent();
      await component.ngOnInit();
    }

    async function urlMovesTo(path: string) {
      mockRoute.snapshot.queryParamMap.get = vi.fn((key: string) => key === 'path' ? path : null);
      mockRoute.queryParamMap.next(convertToParamMap({ path }));
      await flush();
    }

    it('opening the page does not fetch the photo it was handed', async () => {
      await openedFromGallery();
      await flush();

      expect(mockApi.get).not.toHaveBeenCalledWith('/photo', expect.anything());
    });

    it('Back to a photo the gallery holds shows its current copy without fetching', async () => {
      await openedFromGallery();
      component.store.photos.set([{ ...earlier, star_rating: 4 }]);

      await urlMovesTo(earlier.path);

      expect(component.photo()).toMatchObject({ path: earlier.path, star_rating: 4 });
      expect(mockApi.get).not.toHaveBeenCalledWith('/photo', expect.anything());
    });

    it('Back to a photo the gallery does not hold fetches it', async () => {
      await openedFromGallery();
      mockApi.get.mockReturnValue(of(earlier));

      await urlMovesTo(earlier.path);

      expect(mockApi.get).toHaveBeenCalledWith('/photo', { path: earlier.path });
      expect(component.photo().path).toBe(earlier.path);
    });

    it('drops a fetch that lands after the URL moved on again', async () => {
      await openedFromGallery();
      const response = new Subject<typeof earlier>();
      mockApi.get.mockReturnValue(response);

      await urlMovesTo(earlier.path);
      await urlMovesTo(samplePhoto.path);
      response.next(earlier);
      await flush();

      expect(component.photo().path).toBe(samplePhoto.path);
    });

    it('drops a reused-route read after credentials rotate and the same identity returns', async () => {
      await openedFromGallery();
      const response = new Subject<typeof earlier>();
      mockApi.get.mockReturnValue(response);
      mockRoute.snapshot.queryParamMap.get.mockReturnValue(earlier.path);
      const pending = component.showPhotoAt(earlier.path);
      resetPrivateImageSession();
      response.next(earlier);
      await pending;
      expect(component.photo().path).toBe(samplePhoto.path);
    });

    it('does not start a reused-route read from a component owned by an older credential session', async () => {
      await openedFromGallery();
      mockApi.get.mockClear();
      resetPrivateImageSession();
      mockRoute.snapshot.queryParamMap.get.mockReturnValue(earlier.path);
      await component.showPhotoAt(earlier.path);
      expect(mockApi.get).not.toHaveBeenCalledWith('/photo', expect.anything());
      expect(component.photo().path).toBe(samplePhoto.path);
    });

    it('the not-found page has a way back', () => {
      createComponent();
      const view = TestBed.createComponent(PhotoDetailComponent);
      vi.spyOn(view.componentInstance, 'ngOnInit').mockResolvedValue(undefined);
      (view.componentInstance as unknown as { photoMissing: { set(v: boolean): void } }).photoMissing.set(true);
      view.detectChanges();

      (view.nativeElement.querySelector('button') as HTMLButtonElement).click();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], expect.objectContaining({ replaceUrl: true }));
    });

    it('a fetch that fails after the URL moved on leaves the photo shown alone', async () => {
      await openedFromGallery();
      const response = new Subject<typeof earlier>();
      mockApi.get.mockReturnValue(response);

      await urlMovesTo(earlier.path);
      await urlMovesTo(samplePhoto.path);
      response.error(new Error('404'));
      await flush();

      expect(component.photo().path).toBe(samplePhoto.path);
      expect(component.photoMissing()).toBe(false);
    });

    it('ignores a URL change to the photo already shown', async () => {
      await openedFromGallery();
      mockApi.get.mockClear();

      await urlMovesTo(samplePhoto.path);

      expect(mockApi.get).not.toHaveBeenCalledWith('/photo', expect.anything());
    });

    it('Forward to a photo that no longer loads says so, and Back still works', async () => {
      await openedFromGallery();
      component.store.photos.set([samplePhoto]);
      mockApi.get.mockReturnValue(throwError(() => new Error('404')));

      await urlMovesTo(earlier.path);
      expect(component.photo()).toBeNull();
      expect(component.photoMissing()).toBe(true);

      await urlMovesTo(samplePhoto.path);
      expect(component.photo().path).toBe(samplePhoto.path);
      expect(component.photoMissing()).toBe(false);
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('a face assigned before moving on does not change the next photo', async () => {
      await openedFromGallery();
      component.store.photos.set([{ ...earlier, unassigned_faces: 2 }]);
      let assigned = () => {};
      vi.spyOn(component.photoActions, 'openAddPerson').mockImplementation((...args: unknown[]) => { assigned = args[1] as () => void; });

      component.openAddPerson(component.photo());
      await urlMovesTo(earlier.path);
      assigned();

      expect(component.photo().unassigned_faces).toBe(2);
    });

    it('a rating that lands after Back does not touch the photo Back showed', async () => {
      await openedFromGallery();
      component.store.photos.set([{ ...earlier, star_rating: 1 }]);
      const saved = new Subject<unknown>();
      mockApi.post.mockReturnValue(saved);

      const rating = component.setRating(samplePhoto.path, 5);
      await urlMovesTo(earlier.path);
      saved.next({});
      await rating;

      expect(component.photo()).toMatchObject({ path: earlier.path, star_rating: 1 });
    });
  });

  describe('star rating display', () => {
    it('should have stars array [1,2,3,4,5]', () => {
      createComponent();
      expect(component.stars).toEqual([1, 2, 3, 4, 5]);
    });
  });

  describe('fullImageUrl', () => {
    it('should return image URL when photo is set', () => {
      createComponent();
      component.photo.set(samplePhoto);

      expect(component.fullImageUrl()).toBe(`/image?path=${encodeURIComponent(samplePhoto.path)}`);
    });

    it('should return empty string when no photo', () => {
      createComponent();
      expect(component.fullImageUrl()).toBe('');
    });
  });

  describe('hasExif', () => {
    it('should return true when EXIF data exists', () => {
      createComponent();
      component.photo.set(samplePhoto);
      expect(component.hasExif()).toBe(true);
    });

    it('should return false when no photo', () => {
      createComponent();
      expect(component.hasExif()).toBe(false);
    });

    it('should return false when no EXIF fields are set', () => {
      createComponent();
      component.photo.set({
        ...samplePhoto,
        camera_model: null,
        lens_model: null,
        focal_length: null,
        f_stop: null,
        shutter_speed: null,
        iso: null,
      });
      expect(component.hasExif()).toBe(false);
    });
  });

  describe('onFullImageLoad', () => {
    const loadedImage = (src: string, width = 600, height = 400): HTMLImageElement => {
      const img = document.createElement('img'); img.src = src;
      Object.defineProperties(img, { complete: { value: true }, naturalWidth: { value: width }, naturalHeight: { value: height } });
      return img;
    };

    it('accepts only decoded pixels for the current source and refuses a late former frame', () => {
      createComponent();
      component.photo.set(samplePhoto); TestBed.tick();
      expect(component.fullImageLoaded()).toBe(false);
      const img = loadedImage(component.fullImageUrl());
      component.onFullImageLoad({ target: img });
      expect(component.fullImageLoaded()).toBe(true);
      expect(component.displayedRendition()).toEqual({ kind: 'source', phase: 'ready', width: 600, height: 400 });
      component.photo.set({ ...samplePhoto, aggregate: 9 }); TestBed.tick();
      expect(component.fullImageLoaded()).toBe(true);
      component.photo.set({ ...samplePhoto, path: '/new.jpg' });
      expect(component.fullImageLoaded()).toBe(false);
      TestBed.tick();
      component.onFullImageLoad({ target: img });
      expect(component.fullImageLoaded()).toBe(false);
      component.onFullImageLoad({ target: loadedImage(component.fullImageUrl(), 0, 0) });
      expect(component.fullImageLoaded()).toBe(false);
    });

    it('keeps a current image that loads before the scheduled reset runs', () => {
      createComponent();
      component.photo.set(samplePhoto);
      component.onFullImageLoad({ target: loadedImage(component.fullImageUrl()) });
      expect(component.fullImageLoaded()).toBe(true);
      TestBed.tick();
      expect(component.fullImageLoaded()).toBe(true);
    });

    it('exposes one named image throughout loading, source success and failure', () => {
      createComponent();
      const fixture = TestBed.createComponent(PhotoDetailComponent);
      const view: any = fixture.componentInstance;
      view.photo.set(samplePhoto as never); fixture.detectChanges();
      const assertSingleImage = () => {
        const images = [...fixture.nativeElement.querySelectorAll('[data-photo-canvas] > img')] as HTMLImageElement[];
        expect(images.filter(img => img.getAttribute('aria-hidden') !== 'true').map(img => img.alt)).toEqual([samplePhoto.filename]);
        expect(images.slice(1).every(img => img.alt === '' && img.getAttribute('aria-hidden') === 'true')).toBe(true);
      };
      assertSingleImage();
      view.onFullImageLoad({ target: loadedImage(view.fullImageUrl()) }); fixture.detectChanges(); assertSingleImage();
      view.onFullImageError({ target: loadedImage(view.fullImageUrl()) }); fixture.detectChanges(); assertSingleImage();
      fixture.destroy();
    });

    it('replaces both image elements when the displayed photo changes', () => {
      createComponent();
      const fixture = TestBed.createComponent(PhotoDetailComponent);
      fixture.componentInstance.photo.set(samplePhoto as never);
      fixture.detectChanges();
      const before = [...fixture.nativeElement.querySelectorAll('div.cursor-grab > img')];
      expect(before).toHaveLength(3);
      fixture.componentInstance.photo.set({ ...samplePhoto, path: '/new.jpg' } as never);
      fixture.detectChanges();
      const after = [...fixture.nativeElement.querySelectorAll('div.cursor-grab > img')];
      expect(after).toHaveLength(3);
      expect(after[0]).not.toBe(before[0]);
      expect(after[1]).not.toBe(before[1]);
      expect(after[2]).not.toBe(before[2]);
      fixture.destroy();
    });

    it('opens and retries a photo on HTTP LAN without randomUUID', () => {
      vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) });
      try {
        createComponent(); component.photo.set(samplePhoto); TestBed.tick();
        component.retryFullImage(); TestBed.tick();
        expect(new URL(component.fullImageUrl()).searchParams.get('facet_retry')).toMatch(/^[0-9a-f-]{36}-1$/);
      } finally { vi.unstubAllGlobals(); }
    });

    it('keeps the measured thumbnail after source failure, retries fresh and rejects a former owner', () => {
      createComponent(); component.photo.set(samplePhoto); TestBed.tick();
      component.onThumbnailState({ target: loadedImage(component.thumbnailImageUrl(), 640, 420) });
      const src = component.fullImageUrl();
      component.onFullImageError({ target: loadedImage(src, 0, 0) });
      expect(component.sourceRendition().phase).toBe('failed');
      expect(component.displayedRendition()).toEqual({ kind: 'thumbnail', phase: 'ready', width: 640, height: 420 });
      component.retryFullImage(); TestBed.tick();
      expect(component.fullImageUrl()).not.toBe(src);
      expect(component.sourceRendition().phase).toBe('loading');
      component.onFullImageLoad({ target: loadedImage(src) });
      expect(component.fullImageLoaded()).toBe(false);
      mockAuth.status.set({ user_id: 'different' });
      const pending = component.fullImageUrl();
      component.retryFullImage();
      expect(component.fullImageUrl()).toBe(pending);
      component.onFullImageLoad({ target: loadedImage(pending) });
      expect(component.fullImageLoaded()).toBe(false);
    });
  });

  describe('assistant change refresh', () => {
    const flushAsync = async (): Promise<void> => { await new Promise(resolve => setTimeout(resolve, 0)); };
    const fresh = { ...samplePhoto, star_rating: 5 };
    const photoGets = (): unknown[][] => mockApi.get.mock.calls.filter(c => c[0] === '/photo');

    beforeEach(() => {
      createComponent();
      component.photo.set(samplePhoto);
      mockApi.get.mockClear();
      mockApi.get.mockImplementation(() => of(fresh));
    });

    it('refetches /photo once when the batch contains the path and updates the rating', async () => {
      changes$.next({ paths: [samplePhoto.path, '/other.jpg'] });
      await flushAsync();
      expect(photoGets()).toEqual([['/photo', { path: samplePhoto.path }]]);
      expect(component.photo().star_rating).toBe(5);
    });

    it('ignores a batch of other paths', async () => {
      changes$.next({ paths: ['/other.jpg'] });
      await flushAsync();
      expect(photoGets()).toHaveLength(0);
    });

    it('refetches once on a null batch', async () => {
      changes$.next({ paths: null });
      await flushAsync();
      expect(photoGets()).toHaveLength(1);
    });

    it('goes back on a 404', async () => {
      mockApi.get.mockImplementation(() => throwError(() => ({ status: 404 })));
      changes$.next({ paths: [samplePhoto.path] });
      await flushAsync();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], expect.objectContaining({ replaceUrl: true }));
    });

    it('stays on the page on a 500', async () => {
      mockApi.get.mockImplementation(() => throwError(() => ({ status: 500 })));
      changes$.next({ paths: [samplePhoto.path] });
      await flushAsync();
      expect(mockLocation.back).not.toHaveBeenCalled();
      expect(component.photo().path).toBe(samplePhoto.path);
    });

    it('discards a result when the photo changed during flight', async () => {
      const inflight = new Subject<unknown>();
      mockApi.get.mockImplementation(() => inflight);
      changes$.next({ paths: [samplePhoto.path] });
      const next = { ...samplePhoto, path: '/photos/next.jpg' };
      component.photo.set(next);
      inflight.next(fresh);
      inflight.complete();
      await flushAsync();
      expect(component.photo().path).toBe('/photos/next.jpg');
      expect(component.photo().star_rating).toBe(samplePhoto.star_rating);
    });

    it('does not go back on a 404 that lands after the photo changed', async () => {
      const inflight = new Subject<unknown>();
      mockApi.get.mockImplementation(() => inflight);
      changes$.next({ paths: [samplePhoto.path] });
      component.photo.set({ ...samplePhoto, path: '/photos/next.jpg' });
      inflight.error({ status: 404 });
      await flushAsync();
      expect(mockLocation.back).not.toHaveBeenCalled();
    });
  });

  describe('goBack', () => {
    it('returns a directly opened photo to the saved gallery query instead of leaving the app', () => {
      history.replaceState({}, '', location.href);
      createComponent();
      vi.spyOn(TestBed.inject(GalleryStore), 'readGallerySessionQuery').mockReturnValue({ search: 'saved' });
      const escape = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
      component.goBack(escape);
      expect(mockLocation.back).not.toHaveBeenCalled();
      expect(mockRouter.navigate).toHaveBeenCalledExactlyOnceWith(['/'], { queryParams: { search: 'saved' }, replaceUrl: true });
      expect(escape.defaultPrevented).toBe(true);
    });
    it('keeps a direct entry unowned after tag search and a popstate restoration', () => {
      history.replaceState({}, '', location.href);
      createComponent(); component.rememberTagOrigin();
      const persisted = mockLocation.replaceState.mock.calls.at(-1)![2];
      expect(persisted.photoBack).toBe(false);
      history.replaceState(persisted, '', location.href);
      mockRouter.currentNavigation = () => ({ trigger: 'popstate', extras: { state: persisted }, previousNavigation: { id: 4 } }) as Navigation;
      createComponent(); component.goBack();
      expect(mockLocation.back).not.toHaveBeenCalled();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], expect.objectContaining({ replaceUrl: true }));
    });

    it.each(['in-app', 'timeline'])('preserves the in-app Back marker for %s openers', origin => {
      history.replaceState({ photoOrigin: origin }, '', location.href);
      createComponent(); component.goBack();
      expect(mockLocation.back).toHaveBeenCalledOnce();
    });

    it('keeps explicit false ownership through photo replacement even with prefetched photo state', () => {
      history.replaceState({ photoBack: false, photo: samplePhoto }, '', location.href);
      createComponent();
      expect(component.photoNavigationState(samplePhoto).photoBack).toBe(false);
      component.goBack(); expect(mockLocation.back).not.toHaveBeenCalled();
    });

    it('should call location.back()', () => {
      history.replaceState({ photo: samplePhoto }, '', location.href);
      createComponent();
      component.goBack();
      expect(mockLocation.back).toHaveBeenCalled();
    });

    it('goes back on Escape, but not on one a dialog already handled', () => {
      history.replaceState({ photo: samplePhoto }, '', location.href);
      createComponent();
      const handled = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
      handled.preventDefault();
      component.goBack(handled);
      expect(mockLocation.back).not.toHaveBeenCalled();
      component.goBack(new KeyboardEvent('keydown', { key: 'Escape' }));
      expect(mockLocation.back).toHaveBeenCalledTimes(1);
    });
  });

  describe('download', () => {
    it('should fetch blob and set downloading state', async () => {
      createComponent();
      URL.createObjectURL = vi.fn(() => 'blob:mock');
      URL.revokeObjectURL = vi.fn();
      const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el);
      const removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el);
      // jsdom treats the click on a blob: href as a cross-document navigation
      // and logs "Not implemented: navigation to another Document". Stub it,
      // and restore it: the prototype is shared with every later spec file.
      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

      expect(component.downloading()).toBe(false);

      const promise = component.download('/photos/test.jpg');
      expect(component.downloading()).toBe(true);

      await promise;
      expect(component.downloading()).toBe(false);
      expect(mockApi.getRaw).toHaveBeenCalled();

      appendSpy.mockRestore();
      removeSpy.mockRestore();
      clickSpy.mockRestore();
    });
  });

  describe('downloadSocialCrop', () => {
    it('downloads via the social_crop endpoint for the chosen preset', async () => {
      createComponent();
      URL.createObjectURL = vi.fn(() => 'blob:mock');
      URL.revokeObjectURL = vi.fn();
      const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el);
      const removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el);
      // jsdom treats the click on a blob: href as a cross-document navigation
      // and logs "Not implemented: navigation to another Document". Stub it,
      // and restore it: the prototype is shared with every later spec file.
      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

      const promise = component.downloadSocialCrop('/photos/test.jpg', 'square');
      expect(component.downloading()).toBe(true);

      await promise;
      expect(component.downloading()).toBe(false);
      expect(mockApi.getRaw).toHaveBeenCalledWith(
        `/api/photo/social_crop?path=${encodeURIComponent('/photos/test.jpg')}&preset=square`,
      );

      appendSpy.mockRestore();
      removeSpy.mockRestore();
      clickSpy.mockRestore();
    });
  });

  describe('user activity journal', () => {
    it.each(['kept', 'undecided'] as const)('reports %s only after success and respects assistant suppression', async decision => {
      createComponent();
      component.photo.set({ ...samplePhoto });
      const journal = TestBed.inject(UserActivityJournal);
      mockApi.post.mockReturnValue(throwError(() => new Error('offline')));
      await component.reviewPhoto(decision);
      expect(journal.since().items).toEqual([]);
      mockApi.post.mockReturnValue(of({ count: 1 }));
      await journal.suppress(() => component.reviewPhoto(decision));
      expect(journal.since().items).toEqual([]);
      await component.reviewPhoto(decision);
      expect(journal.since().items).toEqual([expect.objectContaining({ kind: 'review', paths: [samplePhoto.path], value: decision })]);
    });

    it.each(['kept', 'undecided'] as const)('discards queued %s journal confirmation after a direct account switch', async decision => {
      createComponent();
      component.photo.set({ ...samplePhoto });
      const journal = TestBed.inject(UserActivityJournal);
      TestBed.tick();
      const response = new Subject<{ count: number }>();
      mockApi.post.mockReturnValue(response);
      const pending = component.reviewPhoto(decision);
      response.next({ count: 1 });
      mockAuth.status.set({ user_id: 'bob' });
      await pending;
      expect(journal.since().items).toEqual([]);
    });

    const kinds = (): string[] => TestBed.inject(UserActivityJournal).since().items.map(i => i.kind);

    it('records rating, favorite, reject and manual-tag edits', async () => {
      createComponent();
      component.photo.set({ ...samplePhoto, star_rating: 0, manual_tags: [] });
      mockApi.post.mockReturnValue(of({}));
      await component.setRating('/photos/test.jpg', 4);
      mockApi.post.mockReturnValue(of({ is_favorite: true, is_rejected: null }));
      await component.toggleFavorite('/photos/test.jpg');
      mockApi.post.mockReturnValue(of({ is_rejected: true, is_favorite: null, star_rating: null }));
      await component.toggleRejected('/photos/test.jpg');
      mockApi.put.mockReturnValue(of({ tag: 'x', skipped_existing: false }));
      await component['addManualTag'](component.photo()!, 'x');
      mockApi.delete.mockReturnValue(of({}));
      await component['removeManualTag'](component.photo()!, 'x');
      expect(kinds()).toEqual(['rating', 'favorite', 'reject', 'tags', 'tags']);
    });

    it('records nothing when the call fails', async () => {
      createComponent();
      component.photo.set({ ...samplePhoto });
      mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
      await component.setRating('/photos/test.jpg', 4);
      expect(kinds()).toEqual([]);
    });
  });

  describe('physical review completion ownership', () => {
    for (const action of ['reviewPhoto', 'toggleRejected'] as const) {
      for (const invalidation of ['owner', 'token'] as const) {
        it.each(['success', 'error'])(`discards ${action} %s after ${invalidation} changes`, async outcome => {
          createComponent();
          Object.assign(mockAuth, { token: 'old-token' }); TestBed.tick();
          const initial = makePhoto({ path: samplePhoto.path, is_kept: false, is_rejected: false });
          component.photo.set(initial); component.store.photos.set([initial]);
          const response = new Subject<unknown>(); mockApi.post.mockReturnValue(response);
          const recorded = vi.spyOn(TestBed.inject(UserActivityJournal), 'record');
          const notice = vi.spyOn(component.snackBar, 'open');
          const pending = action === 'reviewPhoto' ? component.reviewPhoto('kept') : component.toggleRejected(initial.path);
          if (invalidation === 'owner') mockAuth.status.set({ user_id: 'bob' });
          else Object.assign(mockAuth, { token: 'new-token' });
          if (outcome === 'success') response.next({ is_rejected: true, is_favorite: null, star_rating: null });
          else response.error(new Error('old review failed'));
          await pending;
          expect(component.store.photos()[0]).toMatchObject({ is_kept: false, is_rejected: false });
          expect(recorded).not.toHaveBeenCalled(); expect(notice).not.toHaveBeenCalled();
          expect(mockRouter.navigate).not.toHaveBeenCalled();
        });
      }
      it(`does not advance ${action} after credentials change during the gallery refresh`, async () => {
        createComponent(); Object.assign(mockAuth, { token: 'original' });
        const initial = makePhoto({ path: samplePhoto.path });
        component.photo.set(initial);
        component.store.photos.set([initial, makePhoto({ path: '/next.jpg' })]);
        component.store.filters.update((value: object) => ({ ...value, review_status: 'undecided' }));
        let finish!: () => void;
        const refresh = new Promise<void>(resolve => { finish = resolve; });
        const refreshing = vi.spyOn(component.store, 'refreshReviewResults').mockReturnValue(refresh);
        mockApi.post.mockReturnValue(of({ is_rejected: true, is_favorite: null, star_rating: null }));
        const pending = action === 'reviewPhoto' ? component.reviewPhoto('kept') : component.toggleRejected(initial.path);
        await vi.waitFor(() => expect(refreshing).toHaveBeenCalled());
        Object.assign(mockAuth, { token: 'rotated' }); finish(); await pending;
        expect(mockRouter.navigate).not.toHaveBeenCalled();
        expect(component.photo().path).toBe(initial.path);
      });
      it.each(['success', 'error'])(`settles ${action} %s after destruction without touching the closed view`, async outcome => {
        createComponent();
        const initial = makePhoto({ path: samplePhoto.path, is_kept: false, is_rejected: false });
        component.photo.set(initial); component.store.photos.set([initial]);
        const response = new Subject<unknown>(); mockApi.post.mockReturnValue(response);
        const notice = vi.spyOn(component.snackBar, 'open');
        const pending = action === 'reviewPhoto' ? component.reviewPhoto('kept') : component.toggleRejected(initial.path);
        component.destroyRef = { destroyed: true };
        if (outcome === 'success') response.next({ is_rejected: true, is_favorite: null, star_rating: null });
        else response.error(new Error('closed view failed'));
        await pending;
        expect(component.photo()).toBe(initial);
        expect(notice).not.toHaveBeenCalled(); expect(mockRouter.navigate).not.toHaveBeenCalled();
        expect(component.store.photos()[0]).toMatchObject(outcome === 'error'
          ? { is_kept: false, is_rejected: false }
          : action === 'reviewPhoto' ? { is_kept: true, is_rejected: false } : { is_kept: false, is_rejected: true });
      });
    }

    for (const action of ['setRating', 'toggleFavorite'] as const) {
      for (const invalidation of ['owner', 'token'] as const) {
        it.each(['success', 'error'])(`discards ${action} %s after ${invalidation} changes`, async outcome => {
          createComponent();
          Object.assign(mockAuth, { token: 'old-token' });
          TestBed.tick();
          component.photo.set({ ...samplePhoto, star_rating: 0, is_favorite: false });
          const response = new Subject<unknown>();
          mockApi.post.mockReturnValue(response);
          const journal = TestBed.inject(UserActivityJournal);
          const recorded = vi.spyOn(journal, 'record');
          const notice = vi.spyOn(component.snackBar, 'open');
          const pending = component[action](samplePhoto.path, 5);
          if (invalidation === 'owner') mockAuth.status.set({ user_id: 'bob' });
          else Object.assign(mockAuth, { token: 'new-token' });
          component.store.photos.set([{ ...samplePhoto, star_rating: 1, is_favorite: false }]);
          if (outcome === 'success') response.next({ is_favorite: true, is_rejected: null });
          else response.error(new Error('old session failed'));
          await pending;
          expect(component.store.photos()[0]).toMatchObject({ star_rating: 1, is_favorite: false });
          expect(recorded).not.toHaveBeenCalled();
          expect(notice).not.toHaveBeenCalled();
        });
      }
      it.each(['success', 'error'])(`settles ${action} %s after destruction without touching the old view`, async outcome => {
        createComponent();
        const oldPhoto = { ...samplePhoto, star_rating: 0, is_favorite: false };
        component.photo.set(oldPhoto);
        component.store.photos.set([oldPhoto]);
        const response = new Subject<unknown>(); mockApi.post.mockReturnValue(response);
        const notice = vi.spyOn(component.snackBar, 'open');
        const pending = component[action](samplePhoto.path, 5);
        // This test creates the component through its injector; replace only its
        // lifetime token so the singleton store remains alive as it does on navigation.
        component.destroyRef = { destroyed: true };
        if (outcome === 'success') response.next({ is_favorite: true, is_rejected: null });
        else response.error(new Error('closed view failed'));
        await pending;
        expect(component.photo()).toBe(oldPhoto);
        expect(notice).not.toHaveBeenCalled();
        expect(component.store.photos()[0]).toMatchObject(outcome === 'error'
          ? { star_rating: 0, is_favorite: false }
          : action === 'setRating' ? { star_rating: 5 } : { is_favorite: true });
      });
      it(`keeps same-session ${action} store repair after leaving the photo`, async () => {
        createComponent();
        component.photo.set({ ...samplePhoto, star_rating: 0, is_favorite: false });
        component.store.photos.set([{ ...samplePhoto, star_rating: 0, is_favorite: false }]);
        const response = new Subject<unknown>(); mockApi.post.mockReturnValue(response);
        const pending = component[action](samplePhoto.path, 5);
        component.photo.set({ ...samplePhoto, path: '/other.jpg', star_rating: 1, is_favorite: false });
        response.next({ is_favorite: true, is_rejected: null }); await pending;
        expect(component.store.photos()[0]).toMatchObject(action === 'setRating' ? { star_rating: 5 } : { is_favorite: true });
        expect(component.photo()).toMatchObject({ path: '/other.jpg', star_rating: 1, is_favorite: false });
      });
    }
  });

  describe('logical review actions', () => {
    it('does not apply a logical completion after a real NavigationStart', async () => {
      const events = new Subject<NavigationStart>(); mockRouter.events = events;
      createComponent();
      const state = { asset_id: 'asset', group_revision: 1, revision: 0, input_token: 'old', source_path: samplePhoto.path,
        values: { star_rating: 3, is_favorite: 0, is_kept: 0, is_rejected: 0 },
        origins: { star_rating: 'file', is_favorite: 'file', is_kept: 'file', is_rejected: 'file' } };
      const pending = new Subject<any>(); mockApi.post.mockReturnValue(pending);
      component.photo.set({ ...samplePhoto, logical_review: state });
      const store = TestBed.inject(GalleryStore);
      const apply = vi.spyOn(store, 'applyLogicalReview');
      const writing = component.setRating(samplePhoto.path, 4);
      events.next(new NavigationStart(42, '/timeline'));
      pending.next({ ...state, revision: 1, input_token: 'new', values: { ...state.values, star_rating: 4 } });
      pending.complete();
      await writing;
      expect(mockApi.post).toHaveBeenCalledTimes(1);
      expect(apply).not.toHaveBeenCalled();
      expect(component.photo().star_rating).toBe(3);
    });

    it.each(['keep', 'reject'] as const)('advances a logical %s through the same captured review queue as a physical photo', async decision => {
      createComponent();
      const state = { asset_id: 'asset', group_revision: 1, revision: 0, input_token: 'old', source_path: samplePhoto.path,
        values: { star_rating: 3, is_favorite: 0, is_kept: 0, is_rejected: 0 },
        origins: { star_rating: 'file' as const, is_favorite: 'file' as const, is_kept: 'file' as const, is_rejected: 'file' as const } };
      const current = makePhoto({ path: samplePhoto.path, logical_review: state });
      const next = makePhoto({ path: '/next.jpg' });
      const store = TestBed.inject(GalleryStore);
      store.photos.set([current, next]);
      store.filters.update(f => ({ ...f, review_status: 'undecided' }));
      component.photo.set(current);
      mockApi.post.mockReturnValue(of({ ...state, revision: 1, input_token: 'updated', values: { ...state.values, is_kept: decision === 'keep' ? 1 : 0, is_rejected: decision === 'reject' ? 1 : 0 } }));
      const repair = vi.spyOn(store, 'refreshReviewResults').mockImplementation(async () => { store.photos.set([next]); });
      if (decision === 'keep') await component.reviewPhoto('kept');
      else await component.toggleRejected(current.path);
      expect(repair).toHaveBeenCalledWith(false, { whileParked: true });
      expect(component.photo().path).toBe('/next.jpg');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/photo'], expect.objectContaining({ queryParams: { path: '/next.jpg' }, replaceUrl: true }));
      expect(TestBed.inject(UserActivityJournal).since().items).toEqual([]);
    });

    it('lets a non-edition multi-user account update both representations without physical history', async () => {
      mockAuth.isEdition.set(false);
      mockAuth.status.set({ multi_user: true, authenticated: true });
      createComponent();
      const state = { asset_id: 'asset', group_revision: 1, revision: 0, input_token: 'old', source_path: samplePhoto.path,
        values: { star_rating: 3, is_favorite: 0, is_kept: 0, is_rejected: 0 },
        origins: { star_rating: 'file', is_favorite: 'file', is_kept: 'file', is_rejected: 'file' } };
      const result = { ...state, revision: 1, input_token: 'new', values: { ...state.values, star_rating: 4 } };
      const store = TestBed.inject(GalleryStore);
      store.photos.set([{ ...samplePhoto, logical_review: state }, { ...samplePhoto, path: '/raw.CR2', logical_review: state }] as any);
      component.photo.set({ ...samplePhoto, logical_review: state });
      mockApi.post.mockReturnValue(of(result));
      const record = vi.spyOn(TestBed.inject(UserActivityJournal), 'record');
      await component.setRating(samplePhoto.path, 4);
      expect(mockApi.post).toHaveBeenCalledExactlyOnceWith('/logical_assets/review', {
        asset_id: 'asset', group_revision: 1, revision: 0, input_token: 'old', patch: { star_rating: 4 },
      });
      expect(component.photo().star_rating).toBe(4);
      expect(store.photos().map(photo => photo.star_rating)).toEqual([4, 4]);
      expect(record).not.toHaveBeenCalled();
    });
  });

  describe('setRating', () => {
    it('should set a new rating via API', async () => {
      mockApi.post.mockReturnValue(of({}));
      createComponent();
      component.photo.set({ ...samplePhoto, star_rating: 0 });

      await component.setRating('/photos/test.jpg', 4);

      expect(mockApi.post).toHaveBeenCalledWith('/photo/set_rating', { photo_path: '/photos/test.jpg', rating: 4 });
      expect(component.photo().star_rating).toBe(4);
    });

    it('should toggle rating to 0 when clicking same star', async () => {
      mockApi.post.mockReturnValue(of({}));
      createComponent();
      component.photo.set({ ...samplePhoto, star_rating: 3 });

      await component.setRating('/photos/test.jpg', 3);

      expect(mockApi.post).toHaveBeenCalledWith('/photo/set_rating', { photo_path: '/photos/test.jpg', rating: 0 });
      expect(component.photo().star_rating).toBe(0);
    });

    it('should not call API when photo is null', async () => {
      createComponent();
      component.photo.set(null);

      await component.setRating('/photos/test.jpg', 3);

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('toggleFavorite', () => {
    it('should toggle favorite status via API', async () => {
      mockApi.post.mockReturnValue(of({ is_favorite: true, is_rejected: false }));
      createComponent();
      component.photo.set({ ...samplePhoto, is_favorite: false, is_rejected: false });

      await component.toggleFavorite('/photos/test.jpg');

      expect(mockApi.post).toHaveBeenCalledWith('/photo/toggle_favorite', { photo_path: '/photos/test.jpg' });
      expect(component.photo().is_favorite).toBe(true);
    });

    it('should update is_rejected when returned from API', async () => {
      mockApi.post.mockReturnValue(of({ is_favorite: true, is_rejected: false }));
      createComponent();
      component.photo.set({ ...samplePhoto, is_favorite: false, is_rejected: true });

      await component.toggleFavorite('/photos/test.jpg');

      expect(component.photo().is_rejected).toBe(false);
    });

    it('should not call API when photo is null', async () => {
      createComponent();
      component.photo.set(null);

      await component.toggleFavorite('/photos/test.jpg');

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('toggleRejected', () => {
    it('should toggle rejected status via API', async () => {
      mockApi.post.mockReturnValue(of({ is_rejected: true, is_favorite: null }));
      createComponent();
      component.photo.set({ ...samplePhoto, is_rejected: false, is_favorite: true });

      await component.toggleRejected('/photos/test.jpg');

      expect(mockApi.post).toHaveBeenCalledWith('/photo/toggle_rejected', { photo_path: '/photos/test.jpg' });
      expect(component.photo().is_rejected).toBe(true);
    });

    it('should update is_favorite when returned from API', async () => {
      mockApi.post.mockReturnValue(of({ is_rejected: true, is_favorite: false }));
      createComponent();
      component.photo.set({ ...samplePhoto, is_rejected: false, is_favorite: true });

      await component.toggleRejected('/photos/test.jpg');

      expect(component.photo().is_favorite).toBe(false);
    });

    it('clears the star rating when the response reports a reject', async () => {
      mockApi.post.mockReturnValue(of({ is_rejected: true, is_favorite: null, star_rating: 0 }));
      createComponent();
      component.photo.set({ ...samplePhoto, is_rejected: false, is_favorite: false, star_rating: 3 });

      await component.toggleRejected('/photos/test.jpg');

      expect(component.photo().star_rating).toBe(0);
    });

    it('keeps the prior star rating when un-rejecting (server sends null = unchanged)', async () => {
      mockApi.post.mockReturnValue(of({ is_rejected: false, is_favorite: null, star_rating: null }));
      createComponent();
      component.photo.set({ ...samplePhoto, is_rejected: true, is_favorite: false, star_rating: 4 });

      await component.toggleRejected('/photos/test.jpg');

      expect(component.photo().is_rejected).toBe(false);
      expect(component.photo().star_rating).toBe(4);
    });

    it('should not call API when photo is null', async () => {
      createComponent();
      component.photo.set(null);

      await component.toggleRejected('/photos/test.jpg');

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('rating keyboard shortcuts', () => {
    let setRating: MockInstance;
    let toggleFavorite: MockInstance;
    let toggleRejected: MockInstance;

    beforeEach(() => {
      createComponent();
      component.store.config.set({ features: { show_rating_controls: true } });
      component.photo.set({ ...samplePhoto });
      setRating = vi.spyOn(component, 'setRating').mockResolvedValue(undefined);
      toggleFavorite = vi.spyOn(component, 'toggleFavorite').mockResolvedValue(undefined);
      toggleRejected = vi.spyOn(component, 'toggleRejected').mockResolvedValue(undefined);
    });

    afterEach(() => {
      TestBed.inject(KeyboardMappingService).resetAll();
      localStorage.removeItem(KEYMAP_STORAGE_KEY);
    });

    function press(init: KeyboardEventInit, target?: HTMLElement): KeyboardEvent {
      const event = new KeyboardEvent('keydown', { cancelable: true, ...init });
      if (target) Object.defineProperty(event, 'target', { value: target });
      component.onRatingShortcut(event);
      return event;
    }

    function expectNothing(event: KeyboardEvent): void {
      expect(event.defaultPrevented).toBe(false);
      expect(setRating).not.toHaveBeenCalled();
      expect(toggleFavorite).not.toHaveBeenCalled();
      expect(toggleRejected).not.toHaveBeenCalled();
    }

    it('handles real document keyboard events for reject, rating and keep', () => {
      const view = TestBed.createComponent(PhotoDetailComponent);
      const page = view.componentInstance as any;
      vi.spyOn(page, 'ngOnInit').mockResolvedValue(undefined);
      page.photo.set({ ...samplePhoto });
      const reject = vi.spyOn(page, 'toggleRejected').mockResolvedValue(undefined);
      const rating = vi.spyOn(page, 'setRating').mockResolvedValue(undefined);
      const keep = vi.spyOn(page, 'reviewPhoto').mockResolvedValue(undefined);
      view.detectChanges();
      try {
        for (const key of ['x', '3', 'k']) document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
        expect(reject).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg');
        expect(rating).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg', 3);
        expect(keep).toHaveBeenCalledExactlyOnceWith('kept');
      } finally { view.destroy(); }
    });

    it.each([1, 2, 3, 4, 5])('%i rates the open photo', stars => {
      const event = press({ key: String(stars) });
      expect(event.defaultPrevented).toBe(true);
      expect(setRating).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg', stars);
    });

    it.each(['f', 'F'])('%s toggles the favourite', key => {
      expect(press({ key }).defaultPrevented).toBe(true);
      expect(toggleFavorite).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg');
    });

    it.each(['x', 'X', '0'])('%s toggles the reject', key => {
      expect(press({ key }).defaultPrevented).toBe(true);
      expect(toggleRejected).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg');
    });

    it('rejects with a remapped key and retires the default X', () => {
      const keymap = TestBed.inject(KeyboardMappingService);
      keymap.setKey('reject', 'r');
      try {
        expect(press({ key: 'r' }).defaultPrevented).toBe(true);
        expect(toggleRejected).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg');
        press({ key: 'x' });
        // Still exactly the one call from 'r': the retired default does nothing.
        expect(toggleRejected).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg');
      } finally {
        keymap.resetAll();
      }
    });

    it('toggles the favourite with a remapped key and retires the default F', () => {
      TestBed.inject(KeyboardMappingService).setKey('favourite', 'z');
      expect(press({ key: 'z' }).defaultPrevented).toBe(true);
      expect(toggleFavorite).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg');
      press({ key: 'f' });
      expect(toggleFavorite).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg');
    });

    describe('keep key', () => {
      let reviewPhoto: MockInstance;

      beforeEach(() => {
        reviewPhoto = vi.spyOn(component, 'reviewPhoto').mockResolvedValue(undefined);
      });

      function pressKeep(key: string): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { cancelable: true, key });
        component.onReviewKey(event);
        return event;
      }

      it('leaves Keep to an open settings or help dialog', () => {
        const panel = document.createElement('section');
        panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
        document.body.append(panel);
        try {
          expect(pressKeep('k').defaultPrevented).toBe(false);
          expect(reviewPhoto).not.toHaveBeenCalled();
        } finally { panel.remove(); }
      });

      it('keeps with the default k', () => {
        expect(pressKeep('k').defaultPrevented).toBe(true);
        expect(reviewPhoto).toHaveBeenCalledExactlyOnceWith('kept');
      });

      it('keeps with a remapped key and retires the default K', () => {
        TestBed.inject(KeyboardMappingService).setKey('keep', 'j');
        expect(pressKeep('j').defaultPrevented).toBe(true);
        expect(reviewPhoto).toHaveBeenCalledExactlyOnceWith('kept');
        expect(pressKeep('k').defaultPrevented).toBe(false);
        expect(reviewPhoto).toHaveBeenCalledExactlyOnceWith('kept');
      });
    });

    it.each(['6', '9', 'q', 'Enter'])('leaves %s alone', key => {
      expectNothing(press({ key }));
    });

    @Component({
      imports: [MatMenuModule, MatSelectModule],
      template: `
        <button [matMenuTriggerFor]="menu">Menu</button>
        <mat-menu #menu="matMenu">
          <button mat-menu-item>Favorite</button>
          <button mat-menu-item>X reject</button>
        </mat-menu>
        <mat-select aria-label="Keyboard rating selector">
          <mat-option value="f">Favorite</mat-option>
          <mat-option value="x">X reject</mat-option>
        </mat-select>
      `,
    })
    class RatingControlsHost {}

    it.each(['menu', 'select'])('does not rate the photo while a real Material %s owns the keys', async control => {
      const host = TestBed.createComponent(RatingControlsHost);
      host.detectChanges();
      document.body.appendChild(host.nativeElement);
      const trigger = host.debugElement.query(By.directive(MatMenuTrigger)).injector.get(MatMenuTrigger);
      const select = host.debugElement.query(By.directive(MatSelect)).componentInstance as MatSelect;
      try {
        if (control === 'menu') trigger.openMenu();
        else select.open();
        host.detectChanges();
        await host.whenStable();
        const target = control === 'menu'
          ? TestBed.inject(OverlayContainer).getContainerElement().querySelector('[role="menu"] button') as HTMLElement
          : select.panel.nativeElement as HTMLElement;
        target.focus();
        for (const key of ['1', '2', '3', '4', '5', 'f', 'F', 'x', 'X']) {
          const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
          target.dispatchEvent(event);
          component.onRatingShortcut(event);
        }
        expect(setRating).not.toHaveBeenCalled();
        expect(toggleFavorite).not.toHaveBeenCalled();
        expect(toggleRejected).not.toHaveBeenCalled();
        if (control === 'menu') trigger.closeMenu();
        else select.close();
        press({ key: 'f' });
        expect(toggleFavorite).toHaveBeenCalledExactlyOnceWith('/photos/test.jpg');
      } finally {
        host.destroy();
        host.nativeElement.remove();
      }
    });

    it('does nothing outside edition mode', () => {
      mockAuth.isEdition.set(false);
      expectNothing(press({ key: '3' }));
    });

    it('does nothing when the rating controls are turned off', () => {
      component.store.config.set({ features: { show_rating_controls: false } });
      expectNothing(press({ key: 'f' }));
    });

    it('does nothing before the photo has loaded', () => {
      component.photo.set(null);
      expectNothing(press({ key: '3' }));
    });

    it('does nothing while typing in a field', () => {
      expectNothing(press({ key: '3' }, document.createElement('input')));
    });

    it.each([['ctrlKey'], ['metaKey'], ['altKey']])('does nothing with %s held', mod => {
      expectNothing(press({ key: 'x', [mod]: true }));
    });

    it('does nothing while a dialog is open', () => {
      const dialog = document.createElement('mat-dialog-container');
      document.body.appendChild(dialog);
      try {
        expectNothing(press({ key: '3' }));
      } finally {
        dialog.remove();
      }
    });
  });

  describe('copy image', () => {
    const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    afterEach(() => {
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
      if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard);
      else Reflect.deleteProperty(navigator, 'clipboard');
    });

    it('copies a PNG rendition and reports success', async () => {
      createComponent();
      component.photo.set({ ...samplePhoto });
      const png = new Blob(['png'], { type: 'image/png' });
      const close = vi.fn();
      vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 4, height: 3, close })));
      vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() } as never);
      vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(png));
      vi.stubGlobal('ClipboardItem', class { constructor(public values: Record<string, Promise<Blob>>) {} });
      const write = vi.fn(async (items: { values: Record<string, Promise<Blob>> }[]) => {
        expect(await items[0].values['image/png']).toBe(png);
      });
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { write } });
      const notice = vi.spyOn(component.snackBar, 'open').mockReturnValue({} as never);
      await component.copyPhoto(samplePhoto.path);
      expect(mockApi.getRaw).toHaveBeenCalledWith(`/image?path=${encodeURIComponent(samplePhoto.path)}`);
      expect(write).toHaveBeenCalledOnce();
      expect(close).toHaveBeenCalledOnce();
      expect(notice).toHaveBeenCalledWith(I18N.photo_detail.copy_image_done, '', { duration: 3000 });
    });

    it.each(['photo', 'owner', 'token'] as const)('does not copy the image after the %s changes mid-fetch', async change => {
      Object.assign(mockAuth, { token: 'original-token' });
      createComponent();
      component.photo.set({ ...samplePhoto });
      const pending = new Subject<Blob>();
      mockApi.getRaw.mockReturnValue(pending);
      const close = vi.fn();
      const decode = vi.fn(async () => ({ width: 4, height: 3, close }));
      vi.stubGlobal('createImageBitmap', decode);
      const draw = vi.fn();
      vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: draw } as never);
      vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(new Blob(['png'], { type: 'image/png' })));
      vi.stubGlobal('ClipboardItem', class { constructor(public values: Record<string, Promise<Blob>>) {} });
      let outcome = 'unread';
      const write = vi.fn(async (items: { values: Record<string, Promise<Blob>> }[]) => {
        try { await items[0].values['image/png']; outcome = 'resolved'; } catch { outcome = 'rejected'; throw new Error('rejected'); }
      });
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { write } });
      const notice = vi.spyOn(component.snackBar, 'open').mockReturnValue({} as never);
      const copying = component.copyPhoto(samplePhoto.path);
      if (change === 'photo') component.photo.set({ ...samplePhoto, path: '/other.jpg' });
      else if (change === 'owner') mockAuth.status.set({ user_id: 'someone-else' });
      else Object.assign(mockAuth, { token: 'rotated-token' });
      pending.next(new Blob(['jpeg'], { type: 'image/jpeg' }));
      await copying;
      expect(outcome).toBe('rejected');
      expect(decode).not.toHaveBeenCalled();
      expect(draw).not.toHaveBeenCalled();
      expect(notice).not.toHaveBeenCalled();
      expect(component.copyingPhoto()).toBe(false);
    });

    it('reports an unavailable clipboard and offers the download path', async () => {
      createComponent();
      component.photo.set({ ...samplePhoto });
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
      const notice = vi.spyOn(component.snackBar, 'open').mockReturnValue({} as never);
      await component.copyPhoto(samplePhoto.path);
      expect(mockApi.getRaw).not.toHaveBeenCalled();
      expect(notice).toHaveBeenCalledWith(I18N.photo_detail.copy_image_failed, '', { duration: 4000 });
    });
  });

  describe('socialExportEnabled', () => {
    const withPreset = { features: { show_social_export: true }, social_export: { presets: [{ key: 'square', label_key: 'social.square' }] } };

    it('is true only when edition, feature flag, and presets all hold', () => {
      createComponent();
      component.store.config.set(withPreset);
      mockAuth.isEdition.set(true);
      expect(component.socialExportEnabled()).toBe(true);

      mockAuth.isEdition.set(false);
      expect(component.socialExportEnabled()).toBe(false);

      mockAuth.isEdition.set(true);
      component.store.config.set({ features: { show_social_export: false }, social_export: { presets: [{ key: 'square', label_key: 'social.square' }] } });
      expect(component.socialExportEnabled()).toBe(false);

      component.store.config.set({ features: { show_social_export: true }, social_export: { presets: [] } });
      expect(component.socialExportEnabled()).toBe(false);
    });
  });

  describe('social crop preview race guard', () => {
    it('ignores a stale preview response after navigating to another photo', async () => {
      const photoA = { ...samplePhoto, path: '/photos/a.jpg' };
      const photoB = { ...samplePhoto, path: '/photos/b.jpg' };
      const previewSubjects: Subject<{ source: string }>[] = [];
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/social_crop/preview') {
          const subject = new Subject<{ source: string }>();
          previewSubjects.push(subject);
          return subject.asObservable();
        }
        if (url === '/download/options') return of({ options: [{ type: 'original', label: 'original' }] });
        return of(samplePhoto);
      });

      createComponent();
      component.store.config.set({ features: { show_social_export: true }, social_export: { presets: [{ key: 'square', label_key: 'social.square' }] } });

      component.photo.set(photoA);
      TestBed.flushEffects();
      component.photo.set(photoB);
      TestBed.flushEffects();

      expect(previewSubjects.length).toBe(2);

      // Current photo (B) resolves first and wins.
      previewSubjects[1].next({ source: 'faces' });
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(component.socialCropSource()).toBe('faces');

      // Stale response for A arrives late and must NOT clobber B's source.
      previewSubjects[0].next({ source: 'saliency' });
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(component.socialCropSource()).toBe('faces');
    });
  });

  describe('social crop preview without dimensions', () => {
    it('does not request a preview for a photo without image dimensions, and does for one with them', () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/social_crop/preview') return of({ source: 'faces' });
        if (url === '/download/options') return of({ options: [{ type: 'original', label: 'original' }] });
        return of(samplePhoto);
      });
      createComponent();
      component.store.config.set({ features: { show_social_export: true }, social_export: { presets: [{ key: 'square', label_key: 'social.square' }] } });
      const previewCalls = () => mockApi.get.mock.calls.filter(call => call[0] === '/photo/social_crop/preview').length;
      component.photo.set({ ...samplePhoto, path: '/photos/nodims.jpg', image_width: null, image_height: null });
      TestBed.flushEffects();
      expect(previewCalls()).toBe(0);
      expect(component.socialCropSource()).toBeNull();
      component.photo.set({ ...samplePhoto, path: '/photos/dims.jpg', image_width: 6000, image_height: 4000 });
      TestBed.flushEffects();
      expect(previewCalls()).toBe(1);
    });
  });

  describe('clearCategoryOverride', () => {
    // D5: the endpoint's response already carries the recomputed category and
    // aggregate; the client used to ignore both, leaving the lightbox
    // showing the stale category/score until a full reload.
    it('posts to the clear_category_override endpoint and applies the returned category and aggregate', async () => {
      mockApi.post.mockReturnValue(of({
        success: true, path: '/photos/test.jpg', old_category: 'portrait', new_category: 'landscape', aggregate: 6.8,
      }));
      createComponent();
      component.photo.set(samplePhoto);

      await component.clearCategoryOverride(samplePhoto);

      expect(mockApi.post).toHaveBeenCalledWith('/comparison/clear_category_override', { path: '/photos/test.jpg' });
      expect(component.photo()?.category).toBe('landscape');
      expect(component.photo()?.aggregate).toBe(6.8);
    });

    it('does not throw when the API call fails', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
      createComponent();
      component.photo.set(samplePhoto);

      await expect(component.clearCategoryOverride(samplePhoto)).resolves.toBeUndefined();
    });
  });

  describe('arrow navigation', () => {
    const last = { ...samplePhoto, path: '/photos/a.jpg', filename: 'a.jpg' };
    const onNextPage = { ...samplePhoto, path: '/photos/b.jpg', filename: 'b.jpg' };

    function atEndOfLoadedPage(whileLoading: () => void = () => {}) {
      createComponent();
      component.store.photos.set([last]);
      component.store.hasMore.set(true);
      component.photo.set(last);
      mockRoute.snapshot.queryParamMap.get.mockReturnValue(last.path);
      vi.spyOn(component.store, 'nextPage').mockImplementation(async () => {
        component.store.photos.set([last, onNextPage]);
        whileLoading();
      });
    }

    it('fetches past the loaded page after real photo navigation parks the gallery', async () => {
      createComponent();
      component.store.photos.set([last]);
      component.store.hasMore.set(true);
      component.photo.set(last);
      mockRoute.snapshot.queryParamMap.get.mockReturnValue(last.path);
      enterPhotoFromGallery(last.path);
      mockApi.get.mockImplementation((url: string) => of(url === '/photos'
        ? { photos: [onNextPage], total: 2, has_more: false }
        : {}));
      await component.navigateAdjacentPhoto(1);
      expect(mockApi.get).toHaveBeenCalledWith('/photos', expect.objectContaining({ page: 2 }));
      expect(component.photo().path).toBe(onNextPage.path);
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/photo'], expect.objectContaining({ replaceUrl: true }));
    });

    it('stepping past the last loaded photo loads the next page and moves onto it', async () => {
      atEndOfLoadedPage();

      await component.navigateAdjacentPhoto(1);

      expect(component.photo().path).toBe(onNextPage.path);
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/photo'], expect.objectContaining({ replaceUrl: true }));
    });

    it('does not navigate if the page closed while the next page loaded', async () => {
      atEndOfLoadedPage(() => TestBed.resetTestingModule());

      await component.navigateAdjacentPhoto(1);

      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('does not navigate if Back moved to another photo while the page loaded', async () => {
      atEndOfLoadedPage(() => mockRoute.snapshot.queryParamMap.get.mockReturnValue(samplePhoto.path));

      await component.navigateAdjacentPhoto(1);

      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('does not navigate into another account after paging completes', async () => {
      atEndOfLoadedPage(() => mockAuth.status.update(status => ({ ...(status as object), user_id: 'another-account' })));

      await component.navigateAdjacentPhoto(1);

      expect(mockRouter.navigate).not.toHaveBeenCalled();
      expect(component.photo().path).toBe(last.path);
    });

    it('moves through the collection with the rendered navigation buttons', async () => {
      mockApi.get.mockImplementation((url: string, params?: { path?: string }) => of(url === '/photo'
        ? (params?.path === onNextPage.path ? onNextPage : last) : {}));
      const view = renderDetail();
      const detail = view.componentInstance as any;
      detail.store.photos.set([last, onNextPage]);
      detail.store.hasMore.set(false);
      detail.photo.set(last);
      mockRoute.snapshot.queryParamMap.get.mockReturnValue(last.path);
      view.detectChanges();
      await view.whenStable();

      expect(view.nativeElement.querySelector('[data-photo-previous]').disabled).toBe(true);
      view.nativeElement.querySelector('[data-photo-next]').click();
      await Promise.resolve();
      view.detectChanges();

      expect(detail.photo().path).toBe(onNextPage.path);
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/photo'], expect.objectContaining({
        queryParams: expect.objectContaining({ path: onNextPage.path }), replaceUrl: true,
      }));
      expect(view.nativeElement.querySelector('[data-photo-next]').disabled).toBe(true);
      expect(view.nativeElement.querySelector('[data-photo-previous]').disabled).toBe(false);

      detail.photo.set({ ...last, stack_id: 7 });
      view.detectChanges();
      expect(view.nativeElement.querySelector('[data-photo-next]')).not.toBeNull();
    });

    it('steps from where the photo sits in a list reloaded while the page loaded', async () => {
      atEndOfLoadedPage(() => component.store.photos.set([samplePhoto, onNextPage, last, { ...samplePhoto, path: '/photos/c.jpg' }]));

      await component.navigateAdjacentPhoto(1);

      expect(component.photo().path).toBe('/photos/c.jpg');
    });

    it('does not jump ahead if another photo was opened while the page loaded', async () => {
      atEndOfLoadedPage(() => component.photo.set(samplePhoto));

      await component.navigateAdjacentPhoto(1);

      expect(component.photo().path).toBe(samplePhoto.path);
    });
  });

  describe('gallery store write-back', () => {
    // The grid renders from GalleryStore.photos(), not from this component's
    // signal, so an edit that only reached the signal was shown back at its
    // pre-edit value the moment the lightbox closed. Every handler here has to
    // put the server-confirmed fields into the store as well (#132).
    const edited = { ...samplePhoto, path: '/photos/a.jpg', filename: 'a.jpg' };
    const neighbour = { ...samplePhoto, path: '/photos/b.jpg', filename: 'b.jpg' };

    /** Put the edited photo (with `overrides` applied) and one bystander in the grid. */
    function seedGrid(overrides: Record<string, unknown> = {}) {
      component.store.photos.set([{ ...edited, ...overrides }, neighbour]);
      component.photo.set({ ...edited, ...overrides });
    }

    const stored = (path = edited.path) =>
      component.store.photos().find((p: { path: string }) => p.path === path);

    it('setRating puts the new rating in the store, and only on that photo', async () => {
      mockApi.post.mockReturnValue(of({}));
      createComponent();
      seedGrid({ star_rating: 0 });

      await component.setRating(edited.path, 4);

      expect(stored().star_rating).toBe(4);
      expect(stored(neighbour.path).star_rating).toBe(samplePhoto.star_rating);
    });

    it('setRating puts the cleared rating in the store when the same star is clicked again', async () => {
      mockApi.post.mockReturnValue(of({}));
      createComponent();
      seedGrid({ star_rating: 3 });

      await component.setRating(edited.path, 3);

      expect(stored().star_rating).toBe(0);
    });

    it('toggleFavorite puts both confirmed flags in the store', async () => {
      mockApi.post.mockReturnValue(of({ is_favorite: true, is_rejected: false }));
      createComponent();
      seedGrid({ is_favorite: false, is_rejected: true });

      await component.toggleFavorite(edited.path);

      expect(stored().is_favorite).toBe(true);
      expect(stored().is_rejected).toBe(false);
    });

    // `is_rejected: null` is the un-favouriting branch and only that one: the
    // endpoint answers from a single expression keyed on the new value, so it
    // pairs the null with `is_favorite: false` and never with `true`. Seeding a
    // favourited photo and clearing it is the only way to reach the guard.
    it('toggleFavorite leaves the stored reject flag alone when the server sends null', async () => {
      mockApi.post.mockReturnValue(of({ is_favorite: false, is_rejected: null }));
      createComponent();
      seedGrid({ is_favorite: true, is_rejected: true });

      await component.toggleFavorite(edited.path);

      expect(stored().is_favorite).toBe(false);
      expect(stored().is_rejected).toBe(true);
    });

    // The coupled case, and the one most likely to regress: the server clears
    // the stars and the favorite flag as part of rejecting, so patching
    // is_rejected alone would leave the tile wearing a rating the photo no
    // longer has.
    it('a reject that clears the stars propagates the cleared rating to the store', async () => {
      mockApi.post.mockReturnValue(of({ is_rejected: true, is_favorite: false, star_rating: 0 }));
      createComponent();
      seedGrid({ is_rejected: false, is_favorite: true, star_rating: 3 });

      await component.toggleRejected(edited.path);

      expect(stored().is_rejected).toBe(true);
      expect(stored().is_favorite).toBe(false);
      expect(stored().star_rating).toBe(0);
    });

    it('un-rejecting keeps the stored rating the server did not touch', async () => {
      mockApi.post.mockReturnValue(of({ is_rejected: false, is_favorite: null, star_rating: null }));
      createComponent();
      seedGrid({ is_rejected: true, star_rating: 4 });

      await component.toggleRejected(edited.path);

      expect(stored().is_rejected).toBe(false);
      expect(stored().star_rating).toBe(4);
    });

    it.each([['a dated photo', '2024:01:01 00:00:00', { path: '/photos/a.jpg', date: '2024:01:01 00:00:00' }], ['an undated photo', null, null]])(
      'editCaptureDate passes %s as the dialog reference', async (_, date, reference) => {
        createComponent();
        seedGrid({ date_taken: date });
        mockDialog.open.mockReturnValue({ afterClosed: () => new Subject() });
        await import('./capture-date-dialog.component');
        component.editCaptureDate(component.photo());
        await new Promise<void>(resolve => setTimeout(resolve, 0));
        expect(mockDialog.open.mock.calls.at(-1)![1].data.reference).toEqual(reference);
      });

    it('refetches the open photo after an Organization history restore, unless a newer edit landed first', async () => {
      createComponent();
      seedGrid();
      mockApi.get.mockReturnValue(of({ ...edited, gps_latitude: 12 }));
      component.store.notifyOrganizationRestored();
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(mockApi.get).toHaveBeenCalledWith('/photo', { path: edited.path });
      expect(component.photo().gps_latitude).toBe(12);

      const delayed = new Subject();
      mockApi.get.mockReturnValue(delayed);
      component.store.notifyOrganizationRestored();
      component.photo.update((photo: typeof edited) => ({ ...photo, star_rating: 5 }));
      delayed.next({ ...edited, star_rating: 1 });
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(component.photo().star_rating).toBe(5);
    });

    it('capture date commits are available on immediate reopen and do not replace a newer photo', async () => {
      createComponent();
      seedGrid();
      const closed = new Subject();
      mockDialog.open.mockReturnValue({ afterClosed: () => closed });
      await import('./capture-date-dialog.component');
      component.editCaptureDate(component.photo());
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      closed.next({ date_taken: '2024:01:01 01:00:00', date_manually_set: 1 });
      component.editCaptureDate(component.photo());
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(mockDialog.open.mock.calls.at(-1)![1].data.manuallySet).toBe(true);
      expect(stored().date_manually_set).toBe(1);
      component.photo.set(neighbour);
      closed.next({ date_taken: null, date_manually_set: 0 });
      expect(component.photo().path).toBe(neighbour.path);
    });

    it('GPS results preserve concurrent metadata and do not resurrect a navigated photo', async () => {
      createComponent();
      seedGrid();
      const closed = new Subject();
      mockDialog.open.mockReturnValue({ afterClosed: () => closed });
      await import('./gps-edit-dialog.component');
      component.editGps(component.photo());
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      component.photo.update((photo: typeof edited) => ({ ...photo, star_rating: 5, is_favorite: true }));
      closed.next({ gps_latitude: 1, gps_longitude: 2 });
      expect(component.photo().star_rating).toBe(5);
      expect(component.photo().is_favorite).toBe(true);
      expect(component.photo().gps_latitude).toBe(1);
      component.photo.set(neighbour);
      closed.next({ gps_latitude: 3, gps_longitude: 4 });
      expect(component.photo().path).toBe(neighbour.path);
      expect(component.photo().gps_latitude).toBeUndefined();
    });

    describe('date detail launcher ownership', () => {
      for (const loss of ['identity', 'edition', 'navigation']) {
        function lose(events: Subject<NavigationStart>) {
          if (loss === 'identity') mockAuth.status.set({ user_id: 'bob' });
          if (loss === 'edition') mockAuth.isEdition.set(false);
          if (loss === 'navigation') { events.next(new NavigationStart(1, '/other')); events.next(new NavigationStart(2, '/')); }
        }
        it(`discards deferred date import after ${loss} and releases its listener`, async () => {
          const events = new Subject<NavigationStart>(); mockRouter.events = events;
          createComponent(); seedGrid();
          const listeners = events.observers.length;
          const module = await import('./capture-date-dialog.component');
          let finish!: (value: typeof module) => void;
          vi.spyOn(component, 'loadCaptureDateDialog').mockReturnValue(new Promise(resolve => { finish = resolve; }));
          component.editCaptureDate(component.photo());
          lose(events); finish(module);
          await new Promise<void>(resolve => setTimeout(resolve, 0));
          expect(mockDialog.open).not.toHaveBeenCalled();
          expect(events.observers).toHaveLength(listeners);
        });
        it(`ignores closed date results after ${loss}`, async () => {
          const events = new Subject<NavigationStart>(); mockRouter.events = events;
          createComponent(); seedGrid();
          const listeners = events.observers.length;
          const closed = new Subject();
          mockDialog.open.mockReturnValue({ afterClosed: () => closed });
          await import('./capture-date-dialog.component');
          component.editCaptureDate(component.photo());
          await new Promise<void>(resolve => setTimeout(resolve, 0));
          expect(mockDialog.open).toHaveBeenCalledOnce();
          const before = component.photo(); const row = stored();
          lose(events); closed.next({ date_taken: '2024:01:02 12:00:00', date_manually_set: 1 }); closed.complete();
          expect(component.photo()).toBe(before); expect(stored()).toBe(row);
          expect(events.observers).toHaveLength(listeners);
        });
      }
    });

    describe('gps detail launcher ownership', () => {
      for (const loss of ['identity', 'edition', 'navigation']) {
        function lose(events: Subject<NavigationStart>) {
          if (loss === 'identity') mockAuth.status.set({ user_id: 'bob' });
          if (loss === 'edition') mockAuth.isEdition.set(false);
          if (loss === 'navigation') { events.next(new NavigationStart(1, '/other')); events.next(new NavigationStart(2, '/')); }
        }
        it(`discards deferred gps import after ${loss} and releases its listener`, async () => {
          const events = new Subject<NavigationStart>(); mockRouter.events = events;
          createComponent(); seedGrid();
          const listeners = events.observers.length;
          const module = await import('./gps-edit-dialog.component');
          let finish!: (value: typeof module) => void;
          vi.spyOn(component, 'loadGpsDialog').mockReturnValue(new Promise(resolve => { finish = resolve; }));
          component.editGps(component.photo());
          lose(events); finish(module);
          await new Promise<void>(resolve => setTimeout(resolve, 0));
          expect(mockDialog.open).not.toHaveBeenCalled();
          expect(events.observers).toHaveLength(listeners);
        });
        it(`ignores closed gps results after ${loss}`, async () => {
          const events = new Subject<NavigationStart>(); mockRouter.events = events;
          createComponent(); seedGrid();
          const listeners = events.observers.length;
          const closed = new Subject();
          mockDialog.open.mockReturnValue({ afterClosed: () => closed });
          await import('./gps-edit-dialog.component');
          component.editGps(component.photo());
          await new Promise<void>(resolve => setTimeout(resolve, 0));
          expect(mockDialog.open).toHaveBeenCalledOnce();
          const before = component.photo(); const row = stored();
          lose(events); closed.next({ gps_latitude: 7, gps_longitude: 8 }); closed.complete();
          expect(component.photo()).toBe(before); expect(stored()).toBe(row);
          expect(events.observers).toHaveLength(listeners);
        });
      }
    });

    describe('date detail launcher ownership', () => {
      for (const loss of ['identity', 'edition', 'navigation']) {
        function lose(events: Subject<NavigationStart>) {
          if (loss === 'identity') mockAuth.status.set({ user_id: 'bob' });
          if (loss === 'edition') mockAuth.isEdition.set(false);
          if (loss === 'navigation') { events.next(new NavigationStart(1, '/other')); events.next(new NavigationStart(2, '/')); }
        }
        it(`discards deferred date import after ${loss} and releases its listener`, async () => {
          const events = new Subject<NavigationStart>(); mockRouter.events = events;
          createComponent(); seedGrid();
          const listeners = events.observers.length;
          const module = await import('./capture-date-dialog.component');
          let finish!: (value: typeof module) => void;
          vi.spyOn(component, 'loadCaptureDateDialog').mockReturnValue(new Promise(resolve => { finish = resolve; }));
          component.editCaptureDate(component.photo());
          lose(events); finish(module);
          await new Promise<void>(resolve => setTimeout(resolve, 0));
          expect(mockDialog.open).not.toHaveBeenCalled();
          expect(events.observers).toHaveLength(listeners);
        });
        it(`ignores closed date results after ${loss}`, async () => {
          const events = new Subject<NavigationStart>(); mockRouter.events = events;
          createComponent(); seedGrid();
          const listeners = events.observers.length;
          const closed = new Subject();
          mockDialog.open.mockReturnValue({ afterClosed: () => closed });
          await import('./capture-date-dialog.component');
          component.editCaptureDate(component.photo());
          await new Promise<void>(resolve => setTimeout(resolve, 0));
          expect(mockDialog.open).toHaveBeenCalledOnce();
          const before = component.photo(); const row = stored();
          lose(events); closed.next({ date_taken: '2024:01:02 12:00:00', date_manually_set: 1 }); closed.complete();
          expect(component.photo()).toBe(before); expect(stored()).toBe(row);
          expect(events.observers).toHaveLength(listeners);
        });
      }
    });

    it('the category override dialog result reaches the store', async () => {
      createComponent();
      seedGrid();
      mockDialog.open.mockReturnValue({ afterClosed: () => of({ category: 'sports', aggregate: 7.9 }) });
      // Warm the loader cache: openCategoryOverride is void and resolves its
      // dynamic import on its own, so the assertions need the module already
      // in hand for a single tick to be enough to see the result applied.
      await import('./category-override-dialog.component');

      component.openCategoryOverride({ ...edited });
      await new Promise<void>(resolve => setTimeout(resolve, 0));

      expect(stored().category).toBe('sports');
      expect(stored().aggregate).toBe(7.9);
    });

    it('the location dialog result reaches the store, including a cleared location', async () => {
      createComponent();
      seedGrid({ gps_latitude: 10, gps_longitude: 20 });
      mockDialog.open.mockReturnValue({ afterClosed: () => of({ gps_latitude: null, gps_longitude: null }) });
      await import('./gps-edit-dialog.component');

      component.editGps({ ...edited });
      await new Promise<void>(resolve => setTimeout(resolve, 0));

      expect(stored()).toMatchObject({ gps_latitude: null, gps_longitude: null });
    });

    it('two edits in flight on one photo both stick', async () => {
      createComponent();
      seedGrid({ star_rating: 0 });
      const ratingSaved = new Subject<unknown>();
      const favoriteSaved = new Subject<unknown>();
      mockApi.post.mockReturnValueOnce(ratingSaved).mockReturnValueOnce(favoriteSaved);

      const rating = component.setRating(edited.path, 5);
      const favorite = component.toggleFavorite(edited.path);
      ratingSaved.next({});
      await rating;
      favoriteSaved.next({ is_favorite: true, is_rejected: null });
      await favorite;

      expect(component.photo().star_rating).toBe(5);
    });

    it('clearCategoryOverride puts the recomputed category and aggregate in the store', async () => {
      mockApi.post.mockReturnValue(of({
        success: true, path: edited.path, old_category: 'portrait', new_category: 'landscape', aggregate: 6.8,
      }));
      createComponent();
      seedGrid();

      await component.clearCategoryOverride(component.photo());

      expect(stored().category).toBe('landscape');
      expect(stored().aggregate).toBe(6.8);
    });

    // Captions had the same split brain the flags did: both writers set only
    // this component's signal, so a caption edited in the lightbox was shown
    // back at its pre-edit value in the grid tooltip that carries it.
    it('generateCaption puts the generated caption in the store', async () => {
      mockApi.get.mockImplementation(() => of(samplePhoto));
      mockApi.post.mockImplementation((url: string) =>
        url === '/caption' ? of({ caption: 'a generated caption' }) : of({}));
      createComponent();
      seedGrid({ caption: 'stale' });

      await component.generateCaption(edited.path);

      expect(stored().caption).toBe('a generated caption');
      expect(stored(neighbour.path).caption).toBeUndefined();
    });

    // Generation is slow enough to outlive the photo that started it, and the
    // store write is what makes that reachable: applying it blind would put one
    // photo's caption on whichever tile the user had moved on to.
    it('generateCaption drops a response that arrives after the user moved on', async () => {
      const captions = new Subject<{ caption: string }>();
      mockApi.get.mockImplementation(() => of(samplePhoto));
      mockApi.post.mockImplementation((url: string) =>
        url === '/caption' ? captions.asObservable() : of({}));
      createComponent();
      seedGrid({ caption: 'stale' });

      const pending = component.generateCaption(edited.path);
      component.photo.set({ ...neighbour });
      captions.next({ caption: 'belongs to a.jpg' });
      captions.complete();
      await pending;

      expect(stored().caption).toBe('stale');
      expect(stored(neighbour.path).caption).toBeUndefined();
    });

    it('generateCaption refetches the config when generation fails', async () => {
      mockApi.post.mockImplementation((url: string) =>
        url === '/caption' ? throwError(() => new Error('503')) : of({}));
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/config') return of({ features: { show_captions: false } });
        return of(samplePhoto);
      });
      createComponent();
      TestBed.inject(GalleryStore).config.set({ features: { show_captions: true } } as never);

      await component.generateCaption(edited.path);

      expect(TestBed.inject(GalleryStore).config()?.features?.show_captions).toBe(false);
    });

    it('the caption edit dialog result reaches the store', async () => {
      createComponent();
      seedGrid({ caption: 'stale' });
      mockDialog.open.mockReturnValue({ afterClosed: () => of('an edited caption') });
      // Same loader warm-up the category override test needs: editCaption is
      // void and resolves its dynamic import on its own.
      await import('./caption-edit-dialog.component');

      component.editCaption({ ...edited });
      await new Promise<void>(resolve => setTimeout(resolve, 0));

      expect(stored().caption).toBe('an edited caption');
    });

    it('leaves the store untouched when the server refuses the change', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
      createComponent();
      seedGrid({ star_rating: 3 });

      await component.setRating(edited.path, 5);

      expect(stored().star_rating).toBe(3);
    });
  });

  describe('manual tags', () => {
    it('keeps cleared saved album criteria when refining from a photo', () => {
      history.replaceState({ photo: samplePhoto }, '', location.href);
      createComponent(store => {
        store.currentAlbum.set({ id: 7, name: 'Birds', is_smart: true,
          smart_filter_json: JSON.stringify({ camera: 'Canon', min_score: '7', blinks_only: true, sort_direction: 'ASC' }),
        } as NonNullable<ReturnType<typeof store.currentAlbum>>);
        store.filters.update(f => ({ ...f, album_id: '7', camera: '', min_score: '', blinks_only: false, sort_direction: 'DESC' }));
      });
      component.navigateTag('birds', 'collection');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], { info: GALLERY_REVISIT, queryParams: expect.objectContaining({
        album_id: '7', camera: '', min_score: '', blinks_only: 'false', sort_direction: 'DESC',
      }) });
    });

    it('refines the originating album and date constraints using a literal tag', () => {
      history.replaceState({ photo: samplePhoto }, '', location.href);
      createComponent(store => store.filters.update(f => ({ ...f, album_id: '7', date_from: '2026-10-01', tag_groups: '{"none":["private"]}' })));
      const store = TestBed.inject(GalleryStore);
      component.navigateTag('coast,ridge OR 夜景', 'collection');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], { info: GALLERY_REVISIT, queryParams: expect.objectContaining({
        album_id: '7', date_from: '2026-10-01', tag_groups: '{"all":["coast,ridge OR 夜景"],"none":["private"]}',
      }) });
      expect(store.filters().tag_groups).toBe('{"none":["private"]}');
    });

    it.each([null, { owner: 'other', refinable: true, params: { album_id: '7' } },
      { owner: '', refinable: true, params: [] }, { owner: '', refinable: true, params: { album_id: 7 } },
    ])('refuses a foreign or malformed saved tag origin: %j', origin => {
      const owned = origin && origin.owner === '' ? { ...origin, owner: mockAuth.identity() } : origin;
      history.replaceState({ photo: samplePhoto, photoTagOrigin: owned }, '', location.href);
      createComponent();
      expect(component.tagCollectionAvailable()).toBe(false);
      component.navigateTag('trip', 'collection');
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('starts a deliberate library tag query without inheriting the parked album', () => {
      createComponent();
      TestBed.inject(GalleryStore).filters.update(f => ({ ...f, album_id: '7', date_from: '2026-10-01' }));
      component.navigateTag('trip', 'library');
      expect(mockRouter.navigate).toHaveBeenCalledExactlyOnceWith(['/'], { info: GALLERY_REVISIT, queryParams: { tag_groups: '{"all":["trip"]}' } });
    });

    it('refuses a collection pivot from a direct link or a previous identity', () => {
      createComponent();
      component.navigateTag('trip', 'collection');
      mockAuth.status.set({ user_id: 'other' });
      component.navigateTag('trip', 'library');
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('does not offer a query refinement that would lose an explicit captured file list', () => {
      history.replaceState({ photo: samplePhoto }, '', location.href);
      createComponent(store => store.pinnedPaths.set([samplePhoto.path]));
      expect(component.tagCollectionAvailable()).toBe(false);
      component.navigateTag('trip', 'collection');
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('does not claim a tag can refine the separate Similar Photos ranking', () => {
      history.replaceState({ photo: samplePhoto }, '', location.href);
      createComponent(store => store.filters.update(f => ({ ...f, similar_to: '/source.jpg' })));
      expect(component.tagCollectionAvailable()).toBe(false);
      component.navigateTag('trip', 'collection');
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });
    const base = { ...samplePhoto, path: '/photos/a.jpg', filename: 'a.jpg', manual_tags: ['trip'] };
    const stored = () => component.store.photos().find((p: { path: string }) => p.path === base.path);

    function seed() {
      createComponent();
      component.store.photos.set([{ ...base }]);
      component.photo.set({ ...base });
    }

    it('fetchPhoto defaults manual_tags to [] when the payload omits it', async () => {
      mockApi.get.mockReturnValue(of({ ...samplePhoto, manual_tags: undefined }));
      createComponent();

      const photo = await component.fetchPhoto('/photos/test.jpg');

      expect(photo.manual_tags).toEqual([]);
    });

    it('addManualTag PUTs the tag and writes the sorted result to the signal and the store', async () => {
      mockApi.put.mockReturnValue(of({ success: true, tag: 'alpha', skipped_existing: false }));
      seed();

      await component.addManualTag(base, 'Alpha');

      expect(mockApi.put).toHaveBeenCalledWith('/photo/manual_tags', { path: base.path, tag: 'Alpha' });
      expect(component.photo().manual_tags).toEqual(['alpha', 'trip']);
      expect(stored().manual_tags).toEqual(['alpha', 'trip']);
    });

    it('addManualTag adds no chip when the server reports the tag already present as a manual tag', async () => {
      mockApi.put.mockReturnValue(of({ success: true, tag: 'trip', skipped_existing: true }));
      seed();
      const open = vi.spyOn(component.snackBar, 'open');

      await component.addManualTag(base, 'trip');

      expect(component.photo().manual_tags).toEqual(['trip']);
      expect(open).toHaveBeenCalledWith('manual_tags.already_present', '', { duration: 3000 });
    });

    it('addManualTag adds no phantom manual chip for a tag the photo already has as an AI tag', async () => {
      mockApi.put.mockReturnValue(of({ success: true, tag: 'sunset', skipped_existing: true }));
      seed();
      component.photo.set({ ...base, tags_list: ['sunset'] });
      const open = vi.spyOn(component.snackBar, 'open');

      await component.addManualTag(component.photo(), 'sunset');

      expect(component.photo().manual_tags).toEqual(['trip']);
      expect(stored().manual_tags).toEqual(['trip']);
      expect(open).toHaveBeenCalledTimes(1);
    });

    it('addManualTag shows the action-failed snackbar when the server refuses', async () => {
      mockApi.put.mockReturnValue(throwError(() => new Error('422')));
      seed();
      const open = vi.spyOn(component.snackBar, 'open');

      await component.addManualTag(base, 'bad');

      expect(open).toHaveBeenCalledWith('errors.action_failed', '', { duration: 3000 });
      expect(component.newTag()).toBe('');
    });

    it('removeManualTag shows the action-failed snackbar when the server refuses', async () => {
      mockApi.delete.mockReturnValue(throwError(() => new Error('boom')));
      seed();
      const open = vi.spyOn(component.snackBar, 'open');

      await component.removeManualTag(base, 'trip');

      expect(open).toHaveBeenCalledWith('errors.action_failed', '', { duration: 3000 });
    });

    it('two overlapping removes both land: the second applies to the current state, not a stale capture', async () => {
      const a = new Subject<unknown>();
      const b = new Subject<unknown>();
      mockApi.delete.mockReturnValueOnce(a).mockReturnValueOnce(b);
      createComponent();
      const two = { ...base, manual_tags: ['a', 'b'] };
      component.store.photos.set([{ ...two }]);
      component.photo.set({ ...two });

      const first = component.removeManualTag(two, 'a');
      const second = component.removeManualTag(two, 'b');
      a.next({}); a.complete();
      await first;
      b.next({}); b.complete();
      await second;

      expect(component.photo().manual_tags).toEqual([]);
      expect(stored().manual_tags).toEqual([]);
    });

    it('two overlapping adds both land', async () => {
      const a = new Subject<unknown>();
      const b = new Subject<unknown>();
      mockApi.put.mockReturnValueOnce(a).mockReturnValueOnce(b);
      seed();

      const first = component.addManualTag(base, 'x');
      const second = component.addManualTag(base, 'y');
      a.next({ success: true, tag: 'x', skipped_existing: false }); a.complete();
      await first;
      b.next({ success: true, tag: 'y', skipped_existing: false }); b.complete();
      await second;

      expect(component.photo().manual_tags).toEqual(['trip', 'x', 'y']);
    });

    it('addManualTag ignores a blank tag without calling the server', async () => {
      seed();

      await component.addManualTag(base, '   ');

      expect(mockApi.put).not.toHaveBeenCalled();
    });

    it('addManualTag leaves state untouched when the server refuses', async () => {
      mockApi.put.mockReturnValue(throwError(() => new Error('422')));
      seed();

      await component.addManualTag(base, 'bad');

      expect(component.photo().manual_tags).toEqual(['trip']);
      expect(stored().manual_tags).toEqual(['trip']);
    });

    it('removeManualTag DELETEs with a body and drops the tag from signal and store', async () => {
      mockApi.delete.mockReturnValue(of({ success: true, tag: 'trip', removed: true }));
      seed();

      await component.removeManualTag(base, 'trip');

      expect(mockApi.delete).toHaveBeenCalledWith('/photo/manual_tags', { path: base.path, tag: 'trip' });
      expect(component.photo().manual_tags).toEqual([]);
      expect(stored().manual_tags).toEqual([]);
    });

    it('removeManualTag leaves state untouched when the server refuses', async () => {
      mockApi.delete.mockReturnValue(throwError(() => new Error('boom')));
      seed();

      await component.removeManualTag(base, 'trip');

      expect(component.photo().manual_tags).toEqual(['trip']);
    });
  });

  describe('Tags section template', () => {
    let tagsView: ComponentFixture<InstanceType<typeof PhotoDetailComponent>>;
    async function settle() {
      tagsView.detectChanges(); TestBed.inject(ApplicationRef).tick(); await tagsView.whenStable();
    }
    async function render(photo: Record<string, unknown>, edition: boolean) {
      mockAuth.isEdition.set(edition);
      mockApi.get.mockReturnValue(of(photo));
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          { provide: AssistantChangesService, useValue: { batch$: changes$.asObservable() } },
        { provide: ApiService, useValue: mockApi },
          { provide: Router, useValue: mockRouter },
          { provide: Location, useValue: mockLocation },
          { provide: ActivatedRoute, useValue: mockRoute },
          { provide: AuthService, useValue: mockAuth },
          { provide: MatDialog, useValue: mockDialog },
          { provide: I18nService, useValue: { t: (k: string) => k, locale: () => 'en', translations: signal({}) } },
        ],
      });
      const fixture = TestBed.createComponent(PhotoDetailComponent);
      tagsView = fixture;
      fixture.componentInstance.photo.set(photo as never);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    const untagged = { ...samplePhoto, tags: null, tags_list: [], manual_tags: [] };

    it('offers + Tag to an edition user on a photo with no tags, revealing a focused input', async () => {
      const el = await render(untagged, true);
      document.body.appendChild(el);
      try {
        expect(el.querySelector('[data-testid="tags-section"]')).toBeNull();
        expect(el.querySelector('[data-testid="manual-tag-add"]')).toBeNull();
        el.querySelector<HTMLButtonElement>('[data-add-tag]')!.click();
        await settle();
        expect(el.querySelector('[data-testid="tags-section"]')).not.toBeNull();
        const input = el.querySelector<HTMLInputElement>('[data-testid="manual-tag-add"] input')!;
        expect(document.activeElement).toBe(input);
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await settle();
        expect(el.querySelector('[data-testid="manual-tag-add"]')).toBeNull();
        expect(document.activeElement).toBe(el.querySelector('[data-add-tag]'));
      } finally { el.remove(); }
    });

    it('ends the tag chips with + Tag once the photo has tags', async () => {
      const el = await render({ ...untagged, manual_tags: ['trip'] }, true);
      const section = el.querySelector<HTMLElement>('[data-testid="tags-section"]')!;
      expect(section.querySelector('[data-add-tag]')).not.toBeNull();
      expect(el.querySelector('[data-photo-add] [data-add-tag]')).toBeNull();
      expect(el.querySelector('[data-testid="manual-tag-add"]')).toBeNull();
    });

    it('is absent for a non-edition user on a photo with no tags', async () => {
      const el = await render(untagged, false);

      expect(el.querySelector('[data-testid="tags-section"]')).toBeNull();
    });

    it('shows manual tags read-only to a non-edition user', async () => {
      const el = await render({ ...untagged, manual_tags: ['trip'] }, false);

      expect(el.querySelector('[data-testid="manual-tag-chip"]')).not.toBeNull();
      expect(el.querySelector('[data-testid="manual-tag-remove"]')).toBeNull();
      expect(el.querySelector('[data-testid="manual-tag-add"]')).toBeNull();
    });

    it('gives manual chips a remove control and AI chips none', async () => {
      const el = await render({ ...samplePhoto, manual_tags: ['trip'] }, true);

      expect(el.querySelectorAll('[data-testid="ai-tag-chip"]').length).toBe(2);
      expect(el.querySelectorAll('[data-testid="manual-tag-remove"]').length).toBe(1);
      expect(el.querySelectorAll('[data-testid="ai-tag-chip"] [data-testid="manual-tag-remove"]').length).toBe(0);
    });

    it('opens the same explicit library action for AI and manual tags on a direct photo', async () => {
      const el = await render({ ...samplePhoto, tags_list: ['coast,ridge'], manual_tags: ['夜景'] }, false);
      const overlay = TestBed.inject(OverlayContainer).getContainerElement();
      for (const [selector, tag] of [['ai-tag-chip', 'coast,ridge'], ['manual-tag-chip', '夜景']]) {
        (el.querySelector(`[data-testid="${selector}"] button`) as HTMLButtonElement).click();
        await new Promise<void>(resolve => queueMicrotask(resolve));
        TestBed.flushEffects();
        const actions = overlay.querySelectorAll<HTMLButtonElement>('button[mat-menu-item]');
        expect(actions.length).toBe(1);
        expect(actions[0].textContent).toContain('photo_detail.tag_search_library');
        actions[0].click();
        expect(mockRouter.navigate).toHaveBeenLastCalledWith(['/'], { info: GALLERY_REVISIT, queryParams: { tag_groups: JSON.stringify({ all: [tag] }) } });
      }
    });
  });

  describe('category explainer popover', () => {
    it('lazily loads the category list', () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/config/category_priorities') {
          return of({ categories: [{ name: 'portrait' }, { name: 'sports' }] });
        }
        return of(samplePhoto);
      });
      createComponent();

      component.loadExplainerCategories();

      expect(mockApi.get).toHaveBeenCalledWith('/config/category_priorities');
    });

    it('reuses loaded categories on subsequent openings', async () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/config/category_priorities') return of({ categories: [{ name: 'portrait' }] });
        return of(samplePhoto);
      });
      createComponent();

      component.loadExplainerCategories();
      await Promise.resolve();
      mockApi.get.mockClear();
      component.loadExplainerCategories();

      expect(mockApi.get).not.toHaveBeenCalledWith('/config/category_priorities');
    });

    it('opens a category popover without inserting an inline panel', () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/config/category_priorities') return of({ categories: [{ name: 'portrait' }] });
        return of(samplePhoto);
      });
      const view = renderDetail();
      view.componentInstance.photo.set(makePhoto({ category: 'portrait' }));
      view.detectChanges();
      const el: HTMLElement = view.nativeElement;
      const toggle = el.querySelector<HTMLButtonElement>('app-control-popover button[aria-label="photo.category_override.explainer_toggle"]')!;
      expect(toggle.getAttribute('aria-label')).toBe('photo.category_override.explainer_toggle');
      expect(toggle.closest('span')!.textContent).toContain('Portrait');
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(toggle.textContent).toContain('help_outline');
      expect(el.querySelector('mat-select')).toBeNull();
      toggle.click();
      view.detectChanges();
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      expect(el.querySelector('mat-select')).toBeNull();
      expect(TestBed.inject(OverlayContainer).getContainerElement().querySelector('mat-select')).not.toBeNull();
    });

    it('keeps Download named accessibly and offers visible text when space permits', () => {
      const view = renderDetail();
      view.componentInstance.photo.set(makePhoto({ category: 'portrait' }));
      view.detectChanges();
      const download = view.nativeElement.querySelector('button[aria-label="photo_detail.download"]') as HTMLButtonElement;
      expect(download.querySelector('mat-icon')?.textContent?.trim()).toBe('download');
      expect(download.textContent).toContain('photo_detail.download');
      const tooltip = view.debugElement.query(By.css('button[aria-label="photo_detail.download"]')).injector.get(MatTooltip);
      expect(tooltip.message).toBe('photo_detail.download');
    });

    it('keeps the explainer toggle reachable for a photo with no category', () => {
      const view = renderDetail();
      view.componentInstance.photo.set(makePhoto({ category: null }));
      view.detectChanges();
      const toggle = view.nativeElement.querySelector('app-control-popover button[aria-label="photo.category_override.explainer_toggle"]') as HTMLButtonElement;
      expect(toggle).not.toBeNull();
      expect(toggle.textContent).toContain('help_outline');
      toggle.click();
      view.detectChanges();
      expect(toggle.isConnected).toBe(true);
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
    });

    it('hides the toggle outside edition mode', () => {
      mockAuth.isEdition.set(false);
      const view = renderDetail();
      view.componentInstance.photo.set(makePhoto({ category: 'portrait' }));
      view.detectChanges();
      expect(view.nativeElement.querySelector('app-control-popover button[aria-label="photo.category_override.explainer_toggle"]')).toBeNull();
    });
  });

  describe('photo set', () => {
    it('fetches the set for the photo and exposes it', async () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/set') {
          return of({ kind: 'bracket', group_id: 1, count: 3, ev_span: 2, members: [] });
        }
        if (url === '/download/options') return of({ options: [{ type: 'original', label: 'original' }] });
        return of(samplePhoto);
      });
      createComponent();

      component.photo.set(samplePhoto);
      TestBed.flushEffects();
      await new Promise<void>(resolve => setTimeout(resolve, 0));

      expect(component.photoSet()).toEqual({ kind: 'bracket', group_id: 1, count: 3, ev_span: 2, members: [] });
    });

    it('names the blink frames, which the gallery hides when the set is opened there', async () => {
      const burst = {
        kind: 'burst', group_id: 161, count: 4, ev_span: null, members: [
          { path: '/photos/a.jpg', ev_offset: null, is_lead: false, is_blink: true },
          { path: '/photos/b.jpg', ev_offset: null, is_lead: false, is_blink: false },
          { path: '/photos/test.jpg', ev_offset: null, is_lead: true, is_blink: false },
          { path: '/photos/test.CR2', ev_offset: null, is_lead: false, is_blink: false },
        ],
      };
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/set') return of(burst);
        if (url === '/download/options') return of({ options: [{ type: 'original', label: 'original' }] });
        return of(samplePhoto);
      });
      const view = renderDetail();
      view.componentInstance.photo.set(makePhoto({}));
      for (let i = 0; i < 3; i++) {
        view.detectChanges();
        await new Promise<void>(resolve => setTimeout(resolve, 0));
      }
      view.detectChanges();

      const text = view.nativeElement.textContent as string;
      const fileCount = view.nativeElement.querySelector('[data-set-file-count]') as HTMLElement;
      expect(fileCount.textContent).toContain('photo_detail.set.files_count_plural');
      expect(fileCount.textContent).not.toContain('capsules.photos_count');
      const countTooltip = view.debugElement.query(By.css('[data-set-file-count]')).injector.get(MatTooltip);
      expect(countTooltip.message).toBe('photo_detail.set.count_help');
      const members = view.nativeElement.querySelectorAll('button[aria-label^="photo_detail.set.member_position"]');
      expect(members).toHaveLength(4);
      expect(members[3].querySelector('img')).not.toBeNull();
      expect(text).toContain('gallery.hidden_banner.reason_blinks');
      expect(text.match(/ui\.badges\.blink/g)?.length).toBe(1);
    });

    it('orders the strip kept frames, then AI edits, then blinks, and labels the AI edit', async () => {
      const burst = {
        kind: 'burst', group_id: 161, count: 4, ev_span: null, members: [
          { path: '/photos/a.jpg', ev_offset: null, is_lead: false, is_blink: true },
          { path: '/photos/a_agy_1.jpg', ev_offset: null, is_lead: false, is_blink: false, ai_edit_of: '/photos/test.jpg' },
          { path: '/photos/b.jpg', ev_offset: null, is_lead: false, is_blink: false },
          { path: '/photos/test.jpg', ev_offset: null, is_lead: true, is_blink: false },
        ],
      };
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/set') return of(burst);
        if (url === '/download/options') return of({ options: [{ type: 'original', label: 'original' }] });
        return of(samplePhoto);
      });
      const view = renderDetail();
      view.componentInstance.photo.set(makePhoto({}));
      for (let i = 0; i < 3; i++) {
        view.detectChanges();
        await new Promise<void>(resolve => setTimeout(resolve, 0));
      }
      view.detectChanges();

      const thumbs = [...view.nativeElement.querySelectorAll('img[src*="size=96"]')] as HTMLImageElement[];
      const order = thumbs.map(img => img.getAttribute('src') ?? '')
        .map(src => ['b.jpg', 'test.jpg', 'a_agy_1.jpg', 'a.jpg'].find(name => src.includes(encodeURIComponent('/photos/' + name))))
        .filter(Boolean);
      expect(order).toEqual(['b.jpg', 'test.jpg', 'a_agy_1.jpg', 'a.jpg']);
      const labels = view.nativeElement.querySelectorAll('[data-ai-label]');
      expect(labels.length).toBe(1);
      expect(labels[0].textContent).toContain('photo_detail.ai_edit.badge_short');
      // The button's aria-label replaces its content, so it names the edit itself.
      const button = labels[0].closest('button') as HTMLButtonElement;
      expect(button.getAttribute('aria-label')).toContain('photo_detail.ai_edit.badge');
      const plain = thumbs.find(img => img.getAttribute('src')!.includes(encodeURIComponent('/photos/b.jpg')))!;
      expect(plain.closest('button')!.getAttribute('aria-label')).not.toContain('photo_detail.ai_edit');
    });

    it('labels a bracket\'s blink frame even though every bracket member has an EV offset', async () => {
      const bracket = {
        kind: 'bracket', group_id: 1, count: 3, ev_span: 4, members: [
          { path: '/photos/test.jpg', ev_offset: 0, is_lead: true, is_blink: false },
          { path: '/photos/under.jpg', ev_offset: -2, is_lead: false, is_blink: true },
          { path: '/photos/over.jpg', ev_offset: 2, is_lead: false, is_blink: false },
        ],
      };
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/set') return of(bracket);
        if (url === '/download/options') return of({ options: [{ type: 'original', label: 'original' }] });
        return of(samplePhoto);
      });
      const view = renderDetail();
      view.componentInstance.photo.set(makePhoto({}));
      for (let i = 0; i < 3; i++) {
        view.detectChanges();
        await new Promise<void>(resolve => setTimeout(resolve, 0));
      }
      view.detectChanges();

      const el = view.nativeElement as HTMLElement;
      expect(el.textContent!.match(/ui\.badges\.blink/g)?.length).toBe(1);
      const labels = Array.from(el.querySelectorAll('button[aria-label]')).map(b => b.getAttribute('aria-label')!);
      expect(labels.filter(l => l.includes('ui.badges.blink'))).toHaveLength(1);
    });

    it('ignores a stale set response after navigating to another photo', async () => {
      const photoA = { ...samplePhoto, path: '/photos/a.jpg' };
      const photoB = { ...samplePhoto, path: '/photos/b.jpg' };
      const setSubjects: Subject<{ kind: string; group_id: number; count: number; ev_span: number | null; members: unknown[] }>[] = [];
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/set') {
          const subject = new Subject<{ kind: string; group_id: number; count: number; ev_span: number | null; members: unknown[] }>();
          setSubjects.push(subject);
          return subject.asObservable();
        }
        if (url === '/download/options') return of({ options: [{ type: 'original', label: 'original' }] });
        return of(samplePhoto);
      });

      createComponent();
      component.photo.set(photoA);
      TestBed.flushEffects();
      component.photo.set(photoB);
      TestBed.flushEffects();

      expect(setSubjects.length).toBe(2);

      setSubjects[1].next({ kind: 'burst', group_id: 5, count: 2, ev_span: null, members: [] });
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(component.photoSet()?.kind).toBe('burst');

      setSubjects[0].next({ kind: 'duplicate', group_id: 9, count: 2, ev_span: null, members: [] });
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(component.photoSet()?.kind).toBe('burst');
    });
  });

  describe('arrow keys through a set and the collection', () => {
    type Fixture = ReturnType<typeof makePhoto>;
    const before = makePhoto({ path: '/before.jpg' });
    const lead = makePhoto({ path: '/burst/lead.jpg', burst_group_id: 7 });
    const after = makePhoto({ path: '/after.jpg' });
    const first = makePhoto({ path: '/burst/first.jpg', burst_group_id: 7 });
    const second = makePhoto({ path: '/burst/second.jpg', burst_group_id: 7 });
    const burst = { kind: 'burst', group_id: 7, count: 3, ev_span: null,
      members: [first, second, lead].map(m => ({ path: m.path, ev_offset: null, ai_edit_of: null, is_blink: false })) };
    const key = (value: string) => new KeyboardEvent('keydown', { key: value, cancelable: true });
    const opened = () => mockRouter.navigate.mock.calls.map(([, extras]) => (extras as { queryParams: { path: string } }).queryParams.path);
    function open(current: Fixture, setReply: Observable<unknown> = of(burst), rows: Fixture[] = [before, lead, after]) {
      mockApi.get.mockImplementation((url: string, params?: { path?: string }) => {
        if (url === '/photo/set') return setReply;
        if (url === '/photo') return of([first, second, lead].find(p => p.path === params?.path) ?? current);
        return of({});
      });
      createComponent(store => { store.photos.set(rows); store.collapseStacks.set(true); });
      component.photo.set(current);
      TestBed.tick();
    }
    /** Shows a photo and waits for its `/photo/set` reply, which lands a microtask later. */
    async function show(photo: Fixture) {
      component.photo.set(photo); TestBed.tick();
      await vi.waitFor(() => expect(component.photoSet()).not.toBeNull());
    }

    it('keeps a hidden sibling on its set\'s collection photo, so the sidebar and position stay', () => {
      open(first);
      expect(component.collectionEntry()?.path).toBe(lead.path);
      expect(component.collectionNavigation()).toMatchObject({ visible: true, position: 2 });
    });

    it('steps through the strip\'s members with Left/Right, then on into the collection', async () => {
      open(first); await show(first);
      component.nextPhoto(key('ArrowRight'));
      await vi.waitFor(() => expect(opened()).toEqual([second.path]));
      mockRouter.navigate.mockClear();
      await show(lead);
      component.nextPhoto(key('ArrowRight'));
      await vi.waitFor(() => expect(opened()).toEqual([after.path]));
      mockRouter.navigate.mockClear();
      await show(lead);
      component.prevPhoto(key('ArrowLeft'));
      await vi.waitFor(() => expect(opened()).toEqual([second.path]));
    });

    it('leaves the set for the previous collection photo from its first member', async () => {
      open(first); await show(first);
      component.prevPhoto(key('ArrowLeft'));
      await vi.waitFor(() => expect(opened()).toEqual([before.path]));
    });

    it('anchors a hidden sibling on the group /photo/set lists, not on a row sharing a lesser group', () => {
      const hidden = makePhoto({ path: '/burst/hidden.jpg', burst_group_id: 7, duplicate_group_id: 9 });
      const duplicate = makePhoto({ path: '/elsewhere/duplicate.jpg', duplicate_group_id: 9 });
      open(hidden, of(burst), [duplicate, lead, after]);
      expect(component.collectionEntry()?.path).toBe(lead.path);
    });

    it('leaves Left/Right to the collection once it lists several frames of the set', async () => {
      // Strip [first, second, lead]; collection [second, before, lead, after]: walking the strip
      // from lead would come back to second and cycle, never reaching after.
      open(lead, of(burst), [second, before, lead, after]); await show(lead);
      component.nextPhoto(key('ArrowRight'));
      await vi.waitFor(() => expect(opened()).toEqual([after.path]));
      mockRouter.navigate.mockClear();
      await show(second);
      component.nextPhoto(key('ArrowRight'));
      await vi.waitFor(() => expect(opened()).toEqual([before.path]));
    });

    it('lets a folded stack own Left/Right: past its ends they skip the set for the collection', async () => {
      const stacked = makePhoto({ path: '/burst/lead.jpg', burst_group_id: 7, stack_id: 'stack-3' });
      open(stacked, of(burst), [before, stacked, after]); await show(stacked);
      component.prevPhoto(key('ArrowLeft'));
      await vi.waitFor(() => expect(opened()).toEqual([before.path]));
    });

    it('falls through to the collection when the set cannot be read', async () => {
      open(first, throwError(() => new Error('offline')));
      await vi.waitFor(() => expect(component['photoSetPending']()).toBe(false));
      component.nextPhoto(key('ArrowRight'));
      await vi.waitFor(() => expect(opened()).toEqual([after.path]));
    });

    it('holds Left/Right while the set of a grouped photo is still loading', async () => {
      open(first, new Subject());
      await component.navigateAdjacentPhoto(1);
      await Promise.resolve();
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('moves along the collection with Up/Down on wide screens, leaving the inspector its own arrows', async () => {
      const media = vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList);
      open(first);
      const down = key('ArrowDown');
      component.nextCollectionPhoto(down);
      expect(down.defaultPrevented).toBe(true);
      await vi.waitFor(() => expect(opened()).toEqual([after.path]));
      mockRouter.navigate.mockClear();
      const aside = document.createElement('aside'); aside.setAttribute('data-photo-inspector', '');
      const inside = document.createElement('button'); aside.append(inside); document.body.append(aside);
      inside.addEventListener('keydown', event => component.previousCollectionPhoto(event));
      const up = new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true, cancelable: true });
      inside.dispatchEvent(up);
      expect(up.defaultPrevented).toBe(false);
      media.mockReturnValue({ matches: false } as MediaQueryList);
      const narrow = key('ArrowUp');
      component.previousCollectionPhoto(narrow);
      expect(narrow.defaultPrevented).toBe(false);
      await Promise.resolve();
      expect(mockRouter.navigate).not.toHaveBeenCalled();
      aside.remove();
    });

    it('leaves Up/Down to the inspector\'s scrolling after a click on its text, until a click elsewhere', async () => {
      vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList);
      open(first);
      const aside = document.createElement('aside'); aside.setAttribute('data-photo-inspector', '');
      const text = document.createElement('p'); aside.append(text); document.body.append(aside);
      const canvas = document.createElement('div'); document.body.append(canvas);
      try {
        component.notePointerTarget({ target: text } as unknown as Event);
        const scroll = key('ArrowDown');
        component.nextCollectionPhoto(scroll);
        expect(scroll.defaultPrevented).toBe(false);
        await Promise.resolve();
        expect(mockRouter.navigate).not.toHaveBeenCalled();
        component.notePointerTarget({ target: canvas } as unknown as Event);
        const move = key('ArrowDown');
        component.nextCollectionPhoto(move);
        expect(move.defaultPrevented).toBe(true);
        await vi.waitFor(() => expect(opened()).toEqual([after.path]));
      } finally { aside.remove(); canvas.remove(); }
    });
  });

  describe('openSetMember', () => {
    it('does not relabel a pending old-session photo as belonging to the new credentials', async () => {
      createComponent();
      component.photo.set(samplePhoto);
      const response = new Subject<typeof samplePhoto>();
      mockApi.get.mockReturnValue(response);
      const pending = component.openSetMember('/photos/sibling.jpg');
      resetPrivateImageSession();
      response.next({ ...samplePhoto, path: '/photos/sibling.jpg' });
      await pending;
      expect(mockRouter.navigate).not.toHaveBeenCalled();
      expect(component.photo()).toBe(samplePhoto);
    });

    it('does not open a member from a component owned by an older credential session', async () => {
      createComponent();
      component.photo.set(samplePhoto);
      resetPrivateImageSession();
      await component.openSetMember('/photos/sibling.jpg');
      expect(mockApi.get).not.toHaveBeenCalledWith('/photo', expect.anything());
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('does nothing when clicking the currently open photo', async () => {
      createComponent();
      component.photo.set(samplePhoto);

      await component.openSetMember(samplePhoto.path);

      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('loads and navigates to the sibling photo', async () => {
      const sibling = { ...samplePhoto, path: '/photos/sibling.jpg', tags: '', tags_list: undefined, persons: undefined };
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo') return of(sibling);
        if (url === '/download/options') return of({ options: [{ type: 'original', label: 'original' }] });
        return of({ kind: null, group_id: null, count: 0, ev_span: null, members: [] });
      });
      createComponent();
      component.photo.set(samplePhoto);

      await component.openSetMember('/photos/sibling.jpg');

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/photo'], {
        queryParams: { path: '/photos/sibling.jpg' },
        state: { photo: expect.objectContaining({ path: '/photos/sibling.jpg' }), photoSession: privateImageSessionKey(), photoBack: false },
        replaceUrl: true,
      });
      // Navigation, not openSetMember, swaps the photo: the route's activation reloads it,
      // so the component must leave photo() untouched until then (a mocked router never activates).
      expect(component.photo()).toBe(samplePhoto);
      expect(mockRouter.navigate).toHaveBeenCalledTimes(1);
    });
  });

  describe('openSetInGallery', () => {
    it('does nothing without an active set', () => {
      createComponent();

      component.openSetInGallery();

      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('scopes to the bracket set and clears only hide_brackets, carried via navigation state', () => {
      createComponent();
      component.photoSet.set({ kind: 'bracket', group_id: 3, count: 3, ev_span: 2, members: [] });
      mockRouter.navigate.mockResolvedValue(true);

      component.openSetInGallery();

      // Never the URL / a post-navigate updateFilters() call: the gallery
      // route re-initialises filters from config + localStorage + URL on
      // activation, which races a call made after navigate() resolves.
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        state: {
          setScope: {
            sequence_group_id: '3', sequence_kind: 'bracket', burst_group_id: '', duplicate_group_id: '',
            hide_brackets: false,
          },
        },
      });
    });

    it('scopes to the panorama set and clears only hide_panoramas', () => {
      createComponent();
      component.photoSet.set({ kind: 'panorama', group_id: 4, count: 5, ev_span: null, members: [] });
      mockRouter.navigate.mockResolvedValue(true);

      component.openSetInGallery();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        state: {
          setScope: {
            sequence_group_id: '4', sequence_kind: 'panorama', burst_group_id: '', duplicate_group_id: '',
            hide_panoramas: false,
          },
        },
      });
    });

    it('scopes to the burst set and clears only hide_bursts', () => {
      createComponent();
      component.photoSet.set({ kind: 'burst', group_id: 5, count: 2, ev_span: null, members: [] });
      mockRouter.navigate.mockResolvedValue(true);

      component.openSetInGallery();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        state: {
          setScope: {
            sequence_group_id: '', sequence_kind: '', burst_group_id: '5', duplicate_group_id: '',
            hide_bursts: false,
          },
        },
      });
    });

    it('scopes to the duplicate set and clears only hide_duplicates', () => {
      createComponent();
      component.photoSet.set({ kind: 'duplicate', group_id: 9, count: 2, ev_span: null, members: [] });
      mockRouter.navigate.mockResolvedValue(true);

      component.openSetInGallery();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        state: {
          setScope: {
            sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '9',
            hide_duplicates: false,
          },
        },
      });
    });
  });
});
