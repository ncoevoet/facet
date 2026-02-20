import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Component, signal } from '@angular/core';
import { PhotoTooltipComponent, CategoryLabelPipe } from './photo-tooltip.component';
import { I18nService } from '../../core/services/i18n.service';
import type { Photo } from './gallery.store';

const makePhoto = (overrides: Partial<Photo> = {}): Photo => ({
  path: '/photos/test.jpg',
  filename: 'test.jpg',
  aggregate: 7.5,
  aesthetic: 8.0,
  face_quality: null,
  comp_score: null,
  tech_sharpness: null,
  color_score: null,
  exposure_score: null,
  quality_score: null,
  top_picks_score: null,
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
  imports: [PhotoTooltipComponent],
  template: `<app-photo-tooltip [photo]="photo()" [x]="0" [y]="0" />`,
})
class TestHostComponent {
  photo = signal<Photo | null>(null);
}

describe('PhotoTooltipComponent', () => {
  let fixture: ComponentFixture<TestHostComponent>;
  const mockI18n = { t: (key: string) => key };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TestHostComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    }).compileComponents();
    fixture = TestBed.createComponent(TestHostComponent);
  });

  it('creates the host', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('isLandscape is true for landscape photo', () => {
    fixture.componentInstance.photo.set(makePhoto({ image_width: 1920, image_height: 1080 }));
    fixture.detectChanges();
    const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
    expect(tooltip.isLandscape()).toBe(true);
  });

  it('isLandscape is false for portrait photo', () => {
    fixture.componentInstance.photo.set(makePhoto({ image_width: 1080, image_height: 1920 }));
    fixture.detectChanges();
    const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
    expect(tooltip.isLandscape()).toBe(false);
  });

  it('isLandscape is false when no photo', () => {
    fixture.detectChanges();
    const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
    expect(tooltip.isLandscape()).toBe(false);
  });
});

describe('CategoryLabelPipe', () => {
  let pipe: CategoryLabelPipe;

  beforeEach(() => {
    pipe = new CategoryLabelPipe();
  });

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('converts underscored category to Title Case', () => {
    expect(pipe.transform('rule_of_thirds')).toBe('Rule Of Thirds');
  });

  it('handles single word category', () => {
    expect(pipe.transform('portrait')).toBe('Portrait');
  });

  it('handles multi-word with underscores', () => {
    expect(pipe.transform('golden_ratio')).toBe('Golden Ratio');
  });
});
