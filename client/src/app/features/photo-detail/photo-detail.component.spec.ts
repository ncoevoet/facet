import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { Location } from '@angular/common';
import { of } from 'rxjs';
import { signal } from '@angular/core';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PhotoDetailComponent } from './photo-detail.component';

describe('PhotoDetailComponent', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let component: any;
  let mockApi: { get: jest.Mock; post: jest.Mock; imageUrl: jest.Mock; downloadUrl: jest.Mock };
  let mockRouter: { navigate: jest.Mock };
  let mockLocation: { back: jest.Mock };
  let mockRoute: { snapshot: { queryParamMap: { get: jest.Mock } } };
  let mockAuth: { isEdition: ReturnType<typeof signal> };

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
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    component = TestBed.inject(PhotoDetailComponent);
  }

  beforeEach(() => {
    mockApi = {
      get: jest.fn(() => of(samplePhoto)),
      post: jest.fn(() => of({})),
      imageUrl: jest.fn((path: string) => `/image?path=${encodeURIComponent(path)}`),
      downloadUrl: jest.fn((path: string, type = 'original', profile?: string) => `/api/download?path=${encodeURIComponent(path)}&type=${type}${profile ? '&profile=' + profile : ''}`),
    };
    mockRouter = { navigate: jest.fn() };
    mockLocation = { back: jest.fn() };
    mockRoute = {
      snapshot: {
        queryParamMap: { get: jest.fn((key: string) => key === 'path' ? '/photos/test.jpg' : null) },
      },
    };
    mockAuth = { isEdition: signal(true) };
  });

  it('should create', () => {
    createComponent();
    expect(component).toBeTruthy();
  });

  describe('ngOnInit', () => {
    it('should load photo from history state when available', async () => {
      const originalState = history.state;
      Object.defineProperty(history, 'state', {
        value: { photo: samplePhoto },
        writable: true,
        configurable: true,
      });

      createComponent();
      await component.ngOnInit();

      expect(component.photo()).toEqual(samplePhoto);
      expect(mockApi.get).not.toHaveBeenCalled();

      Object.defineProperty(history, 'state', {
        value: originalState,
        writable: true,
        configurable: true,
      });
    });

    it('should load photo from API when no history state', async () => {
      const originalState = history.state;
      Object.defineProperty(history, 'state', {
        value: {},
        writable: true,
        configurable: true,
      });

      createComponent();
      await component.ngOnInit();

      expect(mockApi.get).toHaveBeenCalledWith('/photo', { path: '/photos/test.jpg' });
      expect(component.photo()).toBeTruthy();

      Object.defineProperty(history, 'state', {
        value: originalState,
        writable: true,
        configurable: true,
      });
    });

    it('should navigate to root when no path query param', async () => {
      const originalState = history.state;
      Object.defineProperty(history, 'state', {
        value: {},
        writable: true,
        configurable: true,
      });
      mockRoute.snapshot.queryParamMap.get = jest.fn(() => null);

      createComponent();
      await component.ngOnInit();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/']);

      Object.defineProperty(history, 'state', {
        value: originalState,
        writable: true,
        configurable: true,
      });
    });

    it('should populate tags_list from tags when missing', async () => {
      const originalState = history.state;
      Object.defineProperty(history, 'state', {
        value: {},
        writable: true,
        configurable: true,
      });
      mockApi.get.mockReturnValue(of({ ...samplePhoto, tags_list: undefined, tags: 'a, b', persons: undefined }));

      createComponent();
      await component.ngOnInit();

      const photo = component.photo();
      expect(photo.tags_list).toEqual(['a', 'b']);
      expect(photo.persons).toEqual([]);

      Object.defineProperty(history, 'state', {
        value: originalState,
        writable: true,
        configurable: true,
      });
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
    it('should create and click a download link', () => {
      createComponent();
      const appendSpy = jest.spyOn(document.body, 'appendChild').mockImplementation((el) => el);
      const removeSpy = jest.spyOn(document.body, 'removeChild').mockImplementation((el) => el);

      component.download('/photos/test.jpg');

      expect(appendSpy).toHaveBeenCalled();
      const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
      expect(anchor.href).toContain('/api/download?path=');
      expect(removeSpy).toHaveBeenCalled();

      appendSpy.mockRestore();
      removeSpy.mockRestore();
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
      mockApi.post.mockReturnValue(of({ is_favorite: true, is_rejected: null }));
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

    it('should not call API when photo is null', async () => {
      createComponent();
      component.photo.set(null);

      await component.toggleRejected('/photos/test.jpg');

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });
});
