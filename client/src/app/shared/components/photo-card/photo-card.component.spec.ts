import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { PhotoCardComponent } from './photo-card.component';
import type { Photo } from '../../models/photo.model';

const makePhoto = (overrides: Partial<Photo> = {}): Photo => ({
  path: '/test.jpg',
  filename: 'test.jpg',
  aggregate: 7.5,
  aesthetic: 8.0,
  face_quality: null,
  comp_score: null,
  tech_sharpness: null,
  color_score: null,
  exposure_score: null,
  quality_score: null,
  topiq_score: null,
  top_picks_score: null,
  isolation_bonus: null,
  face_count: 0,
  face_ratio: 0,
  eye_sharpness: null,
  face_sharpness: null,
  face_confidence: null,
  is_blink: null,
  camera_model: null,
  lens_model: null,
  iso: null,
  f_stop: null,
  shutter_speed: null,
  focal_length: null,
  noise_sigma: null,
  contrast_score: null,
  dynamic_range_stops: null,
  mean_saturation: null,
  mean_luminance: null,
  histogram_spread: null,
  composition_pattern: null,
  power_point_score: null,
  leading_lines_score: null,
  category: null,
  tags: null,
  tags_list: [],
  is_monochrome: null,
  is_silhouette: null,
  date_taken: null,
  image_width: 1920,
  image_height: 1080,
  is_best_of_burst: null,
  burst_group_id: null,
  duplicate_group_id: null,
  is_duplicate_lead: null,
  persons: [],
  unassigned_faces: 0,
  star_rating: null,
  is_favorite: null,
  is_rejected: null,
  ...overrides,
});

@Component({
  selector: 'test-host',
  standalone: true,
  imports: [PhotoCardComponent],
  template: `<app-photo-card [photo]="photo()" />`,
})
class TestHostComponent {
  photo = signal<Photo>(makePhoto());
}

describe('PhotoCardComponent', () => {
  let fixture: ComponentFixture<TestHostComponent>;
  const mockI18n = { t: jest.fn((key: string) => key), currentLang: jest.fn(() => 'en') };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TestHostComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    }).compileComponents();
    fixture = TestBed.createComponent(TestHostComponent);
    fixture.detectChanges();
  });

  function getCard(): PhotoCardComponent {
    return fixture.debugElement.children[0].componentInstance as PhotoCardComponent;
  }

  it('should create with required photo input', () => {
    const card = getCard();
    expect(card).toBeTruthy();
    expect(card.photo().filename).toBe('test.jpg');
  });

  it('should have default input values', () => {
    const card = getCard();
    expect(card.isSelected()).toBe(false);
    expect(card.hideDetails()).toBe(false);
    expect(card.currentSort()).toBe('aggregate');
    expect(card.thumbSize()).toBe(240);
    expect(card.isEditionMode()).toBe(false);
    expect(card.hoverStar()).toBeNull();
    expect(card.personFilterId()).toBe('');
    expect(card.config()).toBeNull();
  });

  it('should reflect updated photo input', () => {
    fixture.componentInstance.photo.set(makePhoto({ filename: 'updated.jpg', aggregate: 9.0 }));
    fixture.detectChanges();
    const card = getCard();
    expect(card.photo().filename).toBe('updated.jpg');
    expect(card.photo().aggregate).toBe(9.0);
  });
});
