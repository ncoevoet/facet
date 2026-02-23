import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { GalleryStore } from './gallery.store';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { I18nService } from '../../core/services/i18n.service';

describe('GalleryFilterSidebarComponent', () => {
  let component: GalleryFilterSidebarComponent;

  beforeEach(() => {
    const mockStore = {
      filters: signal({
        hide_details: true, hide_blinks: true, hide_bursts: true, hide_duplicates: true,
        hide_rejected: true, favorites_only: false, is_monochrome: false,
        camera: '', lens: '', tag: '', composition_pattern: '', person_id: '',
        min_score: '', max_score: '', min_aesthetic: '', max_aesthetic: '',
        min_face_quality: '', max_face_quality: '', min_composition: '', max_composition: '',
        min_sharpness: '', max_sharpness: '', min_exposure: '', max_exposure: '',
        min_color: '', max_color: '', min_contrast: '', max_contrast: '',
        min_noise: '', max_noise: '', min_dynamic_range: '', max_dynamic_range: '',
        min_face_count: '', max_face_count: '', min_eye_sharpness: '', max_eye_sharpness: '',
        min_face_sharpness: '', max_face_sharpness: '', min_face_ratio: '', max_face_ratio: '',
        min_face_confidence: '', max_face_confidence: '', min_quality_score: '', max_quality_score: '',
        min_topiq: '', max_topiq: '', min_power_point: '', max_power_point: '',
        min_leading_lines: '', max_leading_lines: '', min_isolation: '', max_isolation: '',
        min_saturation: '', max_saturation: '', min_luminance: '', max_luminance: '',
        min_histogram_spread: '', max_histogram_spread: '', min_star_rating: '', max_star_rating: '',
        min_iso: '', max_iso: '', min_aperture: '', max_aperture: '',
        min_focal_length: '', max_focal_length: '', date_from: '', date_to: '',
        search: '', type: '', sort: 'aggregate', sort_direction: 'DESC', page: 1, per_page: 64,
        similar_to: '', min_similarity: '70',
      }),
      filterDrawerOpen: signal(true),
      cameras: signal([]),
      lenses: signal([]),
      tags: signal([]),
      persons: signal([]),
      compositionPatterns: signal([]),
      updateFilter: jest.fn(),
      resetFilters: jest.fn(),
    };

    TestBed.configureTestingModule({
      providers: [
        GalleryFilterSidebarComponent,
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: { t: jest.fn((k: string) => k), currentLang: jest.fn(() => 'en') } },
      ],
    });
    component = TestBed.inject(GalleryFilterSidebarComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
