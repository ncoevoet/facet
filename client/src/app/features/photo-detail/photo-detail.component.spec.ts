import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { Location } from '@angular/common';
import { MatDialog } from '@angular/material/dialog';
import { of, Subject, throwError } from 'rxjs';
import { signal } from '@angular/core';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';

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
  let mockApi: { get: Mock; post: Mock; imageUrl: Mock; downloadUrl: Mock; getRaw: Mock };
  let mockRouter: { navigate: Mock };
  let mockLocation: { back: Mock };
  let mockRoute: { snapshot: { queryParamMap: { get: Mock } } };
  let mockAuth: { isEdition: ReturnType<typeof signal>; downloadProfiles: ReturnType<typeof signal> };
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
        { provide: ApiService, useValue: mockApi },
        { provide: Router, useValue: mockRouter },
        { provide: Location, useValue: mockLocation },
        { provide: ActivatedRoute, useValue: mockRoute },
        { provide: AuthService, useValue: mockAuth },
        { provide: MatDialog, useValue: mockDialog },
        { provide: I18nService, useValue: { t: (k: string) => k, locale: () => 'en' } },
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
    mockApi = {
      get: vi.fn(() => of(samplePhoto)),
      post: vi.fn(() => of({})),
      imageUrl: vi.fn((path: string) => `/image?path=${encodeURIComponent(path)}`),
      downloadUrl: vi.fn((path: string, type = 'original', profile?: string) => `/api/download?path=${encodeURIComponent(path)}&type=${type}${profile ? '&profile=' + profile : ''}`),
      getRaw: vi.fn(() => of(new Blob(['test'], { type: 'image/jpeg' }))),
    };
    mockRouter = { navigate: vi.fn() };
    mockLocation = { back: vi.fn() };
    mockRoute = {
      snapshot: {
        queryParamMap: { get: vi.fn((key: string) => key === 'path' ? '/photos/test.jpg' : null) },
      },
    };
    mockAuth = { isEdition: signal(true), downloadProfiles: signal([]) };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(undefined) })) };
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

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/']);
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
