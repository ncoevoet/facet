import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Component, signal } from '@angular/core';
import { PhotoTooltipComponent, CategoryLabelPipe } from './photo-tooltip.component';
import { I18nService } from '../../core/services/i18n.service';
import type { Photo } from '../../shared/models/photo.model';

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
  aesthetic_iaa: null,
  face_quality_iqa: null,
  liqe_score: null,
  subject_sharpness: null,
  subject_prominence: null,
  subject_placement: null,
  bg_separation: null,
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

  it('renders face_ratio as percentage (value * 100)', () => {
    // API returns face_ratio as 0-1 fraction; template multiplies by 100 for display
    fixture.componentInstance.photo.set(makePhoto({ face_count: 1, face_quality: 8.5, face_ratio: 0.35 }));
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('35%');
  });

  it('renders face_confidence as percentage (value * 100)', () => {
    fixture.componentInstance.photo.set(makePhoto({ face_count: 1, face_quality: 8.5, face_confidence: 0.92 }));
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('92%');
  });

  it('renders mean_saturation as percentage (value * 100)', () => {
    fixture.componentInstance.photo.set(makePhoto({ mean_saturation: 0.47 }));
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('47%');
  });

  it('renders mean_luminance as percentage (value * 100)', () => {
    fixture.componentInstance.photo.set(makePhoto({ mean_luminance: 0.62 }));
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('62%');
  });

  describe('Extended Quality metrics', () => {
    it('renders aesthetic_iaa when present', () => {
      fixture.componentInstance.photo.set(makePhoto({ aesthetic_iaa: 7.3 }));
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('7.3');
    });

    it('renders face_quality_iqa when present', () => {
      fixture.componentInstance.photo.set(makePhoto({ face_quality_iqa: 6.8 }));
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('6.8');
    });

    it('renders liqe_score when present', () => {
      fixture.componentInstance.photo.set(makePhoto({ liqe_score: 8.1 }));
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('8.1');
    });

    it('does not render aesthetic_iaa row when null', () => {
      fixture.componentInstance.photo.set(makePhoto({ aesthetic_iaa: null }));
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).not.toContain('tooltip.aesthetic_iaa');
    });
  });

  describe('Subject Saliency section', () => {
    it('renders saliency section when at least one metric is present', () => {
      fixture.componentInstance.photo.set(makePhoto({ subject_sharpness: 7.5 }));
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('tooltip.saliency_section');
      expect(fixture.nativeElement.textContent).toContain('7.5');
    });

    it('hides saliency section when all saliency fields are null', () => {
      fixture.componentInstance.photo.set(makePhoto({
        subject_sharpness: null, subject_prominence: null,
        subject_placement: null, bg_separation: null,
      }));
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).not.toContain('tooltip.saliency_section');
    });

    it('renders subject_prominence when present', () => {
      fixture.componentInstance.photo.set(makePhoto({ subject_prominence: 5.2 }));
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('5.2');
    });

    it('renders bg_separation when present', () => {
      fixture.componentInstance.photo.set(makePhoto({ bg_separation: 8.0 }));
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('8.0');
    });
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
