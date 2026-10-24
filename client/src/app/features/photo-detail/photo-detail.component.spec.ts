import { GalleryStore } from '../gallery/gallery.store';
import { makePhoto } from '../../../testing/photo.fixture';
import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, ParamMap, Router, NavigationStart, convertToParamMap } from '@angular/router';
import { Location } from '@angular/common';
import { MatDialog } from '@angular/material/dialog';
import { BehaviorSubject, NEVER, Observable, of, Subject, throwError } from 'rxjs';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { signal } from '@angular/core';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AssistantChangesService, AssistantChangeBatch } from '../../core/agent/assistant-changes.service';

// Mock Leaflet via vi.doMock + dynamic import: the component pulls in shared/leaflet
// (which runs L.Icon.Default.mergeOptions at module load). Without this mock, importing
// the real component caches the real shared/leaflet in the shared module registry and
// poisons map.component.spec's leaflet mock (createLeafletMap keeps the real L) — a
// flaky CI failure. The shared singleton keeps the real Leaflet out of the registry and
// makes every leaflet-using spec's binding identical regardless of load order.
import { leafletMock } from '../../../testing/leaflet-mock';

vi.doMock('leaflet', () => leafletMock);

let PhotoDetailComponent: typeof import('./photo-detail.component').PhotoDetailComponent;

describe('PhotoDetailComponent', () => {
   
  let component: any;
  let changes$: Subject<AssistantChangeBatch>;
  let mockApi: { get: Mock; post: Mock; put: Mock; delete: Mock; imageUrl: Mock; downloadUrl: Mock; getRaw: Mock };
  let mockRouter: { navigate: Mock; events: Observable<unknown> };
  let mockLocation: { back: Mock };
  let mockRoute: { snapshot: { queryParamMap: { get: Mock } }; queryParamMap: BehaviorSubject<ParamMap> };
  let mockAuth: { status: ReturnType<typeof signal>; identity: () => string; isEdition: ReturnType<typeof signal>; downloadProfiles: ReturnType<typeof signal> };
  let mockDialog: { open: Mock };

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

  function createComponent() {
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
    component = TestBed.inject(PhotoDetailComponent);
  }

  // Explicit hook timeout above the default 10s: under full-suite load, many
  // workers resolving dynamic import() chunks concurrently can contend for
  // longer than that, and this hook flaking looks like a broken suite rather
  // than the load-dependent timing issue it actually is.
  beforeAll(async () => {
    ({ PhotoDetailComponent } = await import('./photo-detail.component'));
  }, 20000);

  beforeEach(() => {
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
    mockRouter = { navigate: vi.fn(), events: NEVER };
    mockLocation = { back: vi.fn() };
    mockRoute = {
      snapshot: {
        queryParamMap: { get: vi.fn((key: string) => key === 'path' ? '/photos/test.jpg' : null) },
      },
      queryParamMap: new BehaviorSubject(convertToParamMap({ path: '/photos/test.jpg' })),
    };
    const status = signal({ user_id: 'test' });
    mockAuth = { status, identity: () => status().user_id, isEdition: signal(true), downloadProfiles: signal([]) };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(undefined) })) };
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

    await committed();

    expect(store.photos().map(p => p.path)).toEqual(['/remaining.jpg']);
    expect(store.total()).toBe(1);
    expect(store.filters()).toMatchObject({ person_id: '5', camera: 'Canon' });
    expect(mockApi.get).toHaveBeenCalledWith('/photos', expect.objectContaining({ person_id: '5', camera: 'Canon' }));
    expect(component.photo()).toEqual(other);
    expect(mockRouter.navigate).not.toHaveBeenCalled();
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

  it('renders NULL and zero extended metrics in the actual detail template', () => {
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
    TestBed.inject(GalleryStore).config.set({ populated_scores: ['aesthetic_v25', 'qrealign_score', 'deqa_score'] } as never);
    view.componentInstance.photo.set(makePhoto({ aesthetic_v25: null, qrealign_score: 0, deqa_score: null }));
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
    view.componentInstance.photo.set(makePhoto());
    view.detectChanges();
    expect(view.nativeElement.querySelectorAll('app-extended-quality [data-testid$="-row"]').length).toBe(0);
  });

  it('should create', () => {
    createComponent();
    expect(component).toBeTruthy();
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

    it('should load photo from history state when available', async () => {
      history.replaceState({ photo: samplePhoto }, '', location.href);

      createComponent();
      await component.ngOnInit();

      expect(component.photo()).toEqual(samplePhoto);
      expect(mockApi.get).not.toHaveBeenCalled();
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
      history.replaceState({ photo: samplePhoto }, '', location.href);
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

    it('the not-found page has a way back', () => {
      createComponent();
      const view = TestBed.createComponent(PhotoDetailComponent);
      vi.spyOn(view.componentInstance, 'ngOnInit').mockResolvedValue(undefined);
      (view.componentInstance as unknown as { photoMissing: { set(v: boolean): void } }).photoMissing.set(true);
      view.detectChanges();

      (view.nativeElement.querySelector('button') as HTMLButtonElement).click();

      expect(mockLocation.back).toHaveBeenCalled();
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
    it('should set fullImageLoaded to true', () => {
      createComponent();
      expect(component.fullImageLoaded()).toBe(false);

      component.onFullImageLoad();

      expect(component.fullImageLoaded()).toBe(true);
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
      expect(mockLocation.back).toHaveBeenCalled();
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
    it('should call location.back()', () => {
      createComponent();
      component.goBack();
      expect(mockLocation.back).toHaveBeenCalled();
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
      mockApi.get.mockImplementation((url: string) =>
        url === '/caption' ? of({ caption: 'a generated caption' }) : of(samplePhoto));
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
      mockApi.get.mockImplementation((url: string) =>
        url === '/caption' ? captions.asObservable() : of(samplePhoto));
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
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/caption') return throwError(() => new Error('503'));
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
      fixture.componentInstance.photo.set(photo as never);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    const untagged = { ...samplePhoto, tags: null, tags_list: [], manual_tags: [] };

    it('renders for an edition user on a photo with no tags at all', async () => {
      const el = await render(untagged, true);

      expect(el.querySelector('[data-testid="tags-section"]')).not.toBeNull();
      expect(el.querySelector('[data-testid="manual-tag-add"]')).not.toBeNull();
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
  });

  describe('toggleExplainer', () => {
    it('opens the panel and lazily loads the category list once', () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/config/category_priorities') {
          return of({ categories: [{ name: 'portrait' }, { name: 'sports' }] });
        }
        return of(samplePhoto);
      });
      createComponent();

      component.toggleExplainer();

      expect(component.explainerOpen()).toBe(true);
      expect(mockApi.get).toHaveBeenCalledWith('/config/category_priorities');
    });

    it('closes without refetching categories', () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/config/category_priorities') return of({ categories: [{ name: 'portrait' }] });
        return of(samplePhoto);
      });
      createComponent();

      component.toggleExplainer();
      mockApi.get.mockClear();
      component.toggleExplainer();

      expect(component.explainerOpen()).toBe(false);
      expect(mockApi.get).not.toHaveBeenCalledWith('/config/category_priorities');
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

  describe('openSetMember', () => {
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
        state: { photo: expect.objectContaining({ path: '/photos/sibling.jpg' }) },
        replaceUrl: true,
      });
      expect(component.photo()?.path).toBe('/photos/sibling.jpg');
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
