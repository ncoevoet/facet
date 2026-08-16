import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Component, signal } from '@angular/core';
import { Router } from '@angular/router';
import { of } from 'rxjs';
import { PhotoTooltipComponent, CategoryLabelPipe } from './photo-tooltip.component';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import type { Photo, PhotoSet } from '../../shared/models/photo.model';

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
  is_burst_lead: null,
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

/* eslint-disable @angular-eslint/component-selector */
@Component({
  selector: 'test-host',
  imports: [PhotoTooltipComponent],
  template: `<app-photo-tooltip [photo]="photo()" [x]="0" [y]="0" [flipped]="flipped()"
                                 [pinned]="pinned()" [docked]="docked()" />`,
})
class TestHostComponent {
  photo = signal<Photo | null>(null);
  flipped = signal(false);
  pinned = signal(false);
  docked = signal(false);
}

describe('PhotoTooltipComponent', () => {
  let fixture: ComponentFixture<TestHostComponent>;
  const mockI18n = { t: (key: string) => key, locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };
  const mockRouter = { navigate: vi.fn(() => Promise.resolve(true)) };

  beforeEach(async () => {
    mockRouter.navigate.mockClear();
    await TestBed.configureTestingModule({
      imports: [TestHostComponent],
      providers: [
        { provide: I18nService, useValue: mockI18n },
        { provide: Router, useValue: mockRouter },
      ],
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

  describe('flipped input', () => {
    it('defaults to false', () => {
      fixture.componentInstance.photo.set(makePhoto({ image_width: 1080, image_height: 1920 }));
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.flipped()).toBe(false);
    });

    it('reflects host value when set to true', () => {
      fixture.componentInstance.photo.set(makePhoto({ image_width: 1080, image_height: 1920 }));
      fixture.componentInstance.flipped.set(true);
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.flipped()).toBe(true);
    });
  });

  describe('hasExif computed', () => {
    it('returns false when no EXIF fields', () => {
      fixture.componentInstance.photo.set(makePhoto());
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.hasExif()).toBe(false);
    });

    it('returns true when camera_model is present', () => {
      fixture.componentInstance.photo.set(makePhoto({ camera_model: 'Canon EOS R5' }));
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.hasExif()).toBe(true);
    });

    it('returns true when lens_model is present', () => {
      fixture.componentInstance.photo.set(makePhoto({ lens_model: 'RF 50mm f/1.2' }));
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.hasExif()).toBe(true);
    });

    it('returns true when iso is present', () => {
      fixture.componentInstance.photo.set(makePhoto({ iso: 400 }));
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.hasExif()).toBe(true);
    });

    it('returns true when focal_length is present', () => {
      fixture.componentInstance.photo.set(makePhoto({ focal_length: 85 }));
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.hasExif()).toBe(true);
    });

    it('returns true when f_stop is present', () => {
      fixture.componentInstance.photo.set(makePhoto({ f_stop: 2.8 }));
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.hasExif()).toBe(true);
    });

    it('returns true when shutter_speed is present', () => {
      fixture.componentInstance.photo.set(makePhoto({ shutter_speed: 0.004 }));
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.hasExif()).toBe(true);
    });

    it('returns false when no photo', () => {
      fixture.detectChanges();
      const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      expect(tooltip.hasExif()).toBe(false);
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

  describe('Person avatars', () => {
    it('renders person avatar images when persons are present', () => {
      fixture.componentInstance.photo.set(makePhoto({
        persons: [
          { id: 1, name: 'Alice' },
          { id: 2, name: 'Bob' },
        ],
      }));
      fixture.detectChanges();
      const avatars = fixture.nativeElement.querySelectorAll('img[class*="rounded-full"]');
      expect(avatars.length).toBe(2);
      expect(avatars[0].src).toContain('/person_thumbnail/1');
      expect(avatars[0].alt).toBe('Alice');
      expect(avatars[1].src).toContain('/person_thumbnail/2');
      expect(avatars[1].alt).toBe('Bob');
    });

    it('does not render any avatar when persons array is empty', () => {
      fixture.componentInstance.photo.set(makePhoto({ persons: [] }));
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('img[class*="rounded-full"]').length).toBe(0);
    });

    it('renders a plain, non-interactive image (no button) in the floating hover tooltip', () => {
      // showInteractiveControls() is false here: neither docked nor pinned
      // was set on the host, so the avatar must not look clickable when it
      // is not -- a hover bubble dismisses before a click could land.
      fixture.componentInstance.photo.set(makePhoto({
        persons: [{ id: 1, name: 'Alice' }],
      }));
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('button')).toBeNull();
      const avatar = fixture.nativeElement.querySelector('img[class*="rounded-full"]');
      expect(avatar).not.toBeNull();
      expect(avatar.className).toContain('w-6');
    });

    it('handles person with empty name', () => {
      fixture.componentInstance.photo.set(makePhoto({
        persons: [{ id: 3, name: '' }],
      }));
      fixture.detectChanges();
      const avatars = fixture.nativeElement.querySelectorAll('img[class*="rounded-full"]');
      expect(avatars.length).toBe(1);
      expect(avatars[0].src).toContain('/person_thumbnail/3');
      expect(avatars[0].alt).toBe('');
    });
  });

  describe('Set section', () => {
    let mockApi: { get: Mock };
    let setFixture: ComponentFixture<TestHostComponent>;

    beforeEach(async () => {
      // Discriminates by URL: the histogram widget shares this same mocked
      // ApiService and needs its own valid response to render anything at all.
      mockApi = {
        get: vi.fn((url: string) => {
          if (url === '/photo/set') {
            return of({ kind: 'bracket', group_id: 1, count: 3, ev_span: 4, members: [] });
          }
          if (url === '/photo/histogram') {
            return of({ bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null });
          }
          return of(null);
        }),
      };
      mockRouter.navigate.mockClear();
      TestBed.resetTestingModule();
      await TestBed.configureTestingModule({
        imports: [TestHostComponent],
        providers: [
          { provide: I18nService, useValue: mockI18n },
          { provide: ApiService, useValue: mockApi },
          { provide: Router, useValue: mockRouter },
        ],
      }).compileComponents();
      setFixture = TestBed.createComponent(TestHostComponent);
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('shows nothing for a photo that belongs to no set', () => {
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.textContent).not.toContain('tooltip.set_section');
      expect(mockApi.get).not.toHaveBeenCalledWith('/photo/set', expect.anything());
    });

    it('shows the kind and this frame\'s own EV offset immediately, with zero set requests', () => {
      setFixture.componentInstance.photo.set(makePhoto({
        sequence_kind: 'bracket', sequence_ev_offset: 1.5,
      }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.textContent).toContain('tooltip.set_section');
      expect(setFixture.nativeElement.textContent).toContain('culling.bracket.label');
      expect(setFixture.nativeElement.textContent).toContain('+1.5 EV');
      expect(mockApi.get).not.toHaveBeenCalledWith('/photo/set', expect.anything());
    });

    it('fills in the frame count and EV span once the dwell-delayed fetch resolves', () => {
      setFixture.componentInstance.photo.set(makePhoto({
        sequence_kind: 'bracket', sequence_ev_offset: 0,
      }));
      setFixture.detectChanges();
      expect(setFixture.nativeElement.textContent).not.toContain('capsules.photos_count');

      vi.advanceTimersByTime(300);
      setFixture.detectChanges();

      expect(mockApi.get).toHaveBeenCalledWith('/photo/set', { path: '/photos/test.jpg' });
      expect(setFixture.nativeElement.textContent).toContain('capsules.photos_count');
      expect(setFixture.nativeElement.textContent).toContain('±4.0 EV');
    });

    it('never fires the request at all when the pointer only passes through', () => {
      setFixture.componentInstance.photo.set(makePhoto({
        path: '/photos/a.jpg', sequence_kind: 'bracket', sequence_ev_offset: 0,
      }));
      setFixture.detectChanges();
      vi.advanceTimersByTime(150); // half the dwell delay

      setFixture.componentInstance.photo.set(makePhoto({
        path: '/photos/b.jpg', sequence_kind: 'bracket', sequence_ev_offset: 0,
      }));
      setFixture.detectChanges();
      vi.advanceTimersByTime(150); // the first photo's timer never reaches 300ms

      expect(mockApi.get).not.toHaveBeenCalledWith('/photo/set', expect.anything());
    });

    it('hides the histogram mode toggle in plain hover mode (neither pinned nor docked)', () => {
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.querySelectorAll('button').length).toBe(0);
    });

    it('shows the histogram mode toggle when pinned', () => {
      setFixture.componentInstance.pinned.set(true);
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.querySelectorAll('button').length).toBeGreaterThan(0);
    });

    it('shows the histogram mode toggle when docked', () => {
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.querySelectorAll('button').length).toBeGreaterThan(0);
    });

    // --- full-width histogram when the photo belongs to no set ---------------

    function histogramContainer(): HTMLElement | null {
      return setFixture.nativeElement.querySelector('app-histogram')?.parentElement ?? null;
    }

    it('the histogram is its own full-width block, not a grid column, when the photo belongs to no set', () => {
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.textContent).not.toContain('tooltip.set_section');
      const container = histogramContainer();
      expect(container).not.toBeNull();
      expect(container!.parentElement?.classList.contains('grid')).toBe(false);
    });

    it('the layout is already full-width on the very first render, before the debounced fetch resolves -- no reflow once it does', () => {
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();

      // Presence of the set block is decided by the synchronous
      // p.sequence_kind, never by GET /api/photo/set -- assert the layout is
      // already correct before advancing the fake timer past the dwell delay.
      const beforeFetch = histogramContainer()!.parentElement?.classList.contains('grid');

      vi.advanceTimersByTime(300);
      setFixture.detectChanges();

      const afterFetch = histogramContainer()!.parentElement?.classList.contains('grid');
      expect(beforeFetch).toBe(false);
      expect(afterFetch).toBe(false);
    });

    it('keeps the set block and the histogram as two stacked full-width blocks when the photo IS in a set', () => {
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket', sequence_ev_offset: 0 }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.textContent).toContain('tooltip.set_section');
      const container = histogramContainer();
      expect(container!.parentElement?.classList.contains('grid')).toBe(false);
    });

    // --- docked-only sibling thumbnails ---------------------------------------

    const MEMBERS: PhotoSet['members'] = [
      { path: '/photos/a.jpg', ev_offset: -2, is_lead: false },
      { path: '/photos/test.jpg', ev_offset: 0, is_lead: true },
      { path: '/photos/c.jpg', ev_offset: 2, is_lead: false },
    ];

    function mockSetWithMembers(): void {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/set') {
          return of({ kind: 'bracket', group_id: 1, count: 3, ev_span: 2, members: MEMBERS });
        }
        if (url === '/photo/histogram') {
          return of({ bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null });
        }
        return of(null);
      });
    }

    it('shows sibling thumbnails with an EV badge in the docked panel once the fetch resolves', () => {
      mockSetWithMembers();
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket', sequence_ev_offset: 0 }));
      setFixture.detectChanges();
      vi.advanceTimersByTime(300);
      setFixture.detectChanges();

      // size=96 scopes to the sibling strip's thumbnails specifically -- the
      // main preview image reuses the same "test.jpg" filename at size=640.
      const thumbs = setFixture.nativeElement.querySelectorAll(
        'img[src*="size=96"][src*="a.jpg"], img[src*="size=96"][src*="test.jpg"], img[src*="size=96"][src*="c.jpg"]',
      );
      expect(thumbs.length).toBe(3);
      expect(setFixture.nativeElement.textContent).toContain('+2');
      expect(setFixture.nativeElement.textContent).toContain('−2');
    });

    it('labels each sibling button with its position in the set and EV offset, not the filesystem path', () => {
      mockSetWithMembers();
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket', sequence_ev_offset: 0 }));
      setFixture.detectChanges();
      vi.advanceTimersByTime(300);
      setFixture.detectChanges();

      const img = setFixture.nativeElement.querySelector('img[src*="a.jpg"]') as HTMLElement;
      const button = img.closest('button') as HTMLButtonElement;
      // mockI18n.t() returns the raw key (no interpolation), so the position
      // clause below is the untranslated key -- only the EV suffix comes from
      // the real (unmocked) evOffset pipe.
      expect(button.getAttribute('aria-label')).toBe('photo_detail.set.member_position, −2 EV');
      expect(img.getAttribute('alt')).toBe('');
    });

    it('does not show sibling thumbnails in the floating (non-docked, non-pinned) tooltip', () => {
      mockSetWithMembers();
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket', sequence_ev_offset: 0 }));
      setFixture.detectChanges();
      vi.advanceTimersByTime(300);
      setFixture.detectChanges();

      expect(setFixture.nativeElement.querySelector('img[src*="a.jpg"]')).toBeNull();
    });

    it('clicking a sibling thumbnail opens that frame\'s own detail page', () => {
      mockSetWithMembers();
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket', sequence_ev_offset: 0 }));
      setFixture.detectChanges();
      vi.advanceTimersByTime(300);
      setFixture.detectChanges();

      const img = setFixture.nativeElement.querySelector('img[src*="a.jpg"]') as HTMLElement;
      (img.closest('button') as HTMLButtonElement).click();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/photo'], { queryParams: { path: '/photos/a.jpg' } });
    });

    it('rings the current frame among its siblings', () => {
      mockSetWithMembers();
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket', sequence_ev_offset: 0 }));
      setFixture.detectChanges();
      vi.advanceTimersByTime(300);
      setFixture.detectChanges();

      const currentImg = setFixture.nativeElement.querySelector('img[src*="size=96"][src*="test.jpg"]') as HTMLElement;
      const otherImg = setFixture.nativeElement.querySelector('img[src*="a.jpg"]') as HTMLElement;
      expect(currentImg.closest('button')!.className).toContain('ring-2');
      expect(otherImg.closest('button')!.className).not.toContain('ring-2');
    });

    // --- clickable, per-surface-sized person avatars --------------------------

    function personButton(): HTMLButtonElement | null {
      return setFixture.nativeElement.querySelector('button[aria-label]');
    }

    it('renders person avatars as clickable 44px buttons in the docked panel', () => {
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({
        sequence_kind: null, persons: [{ id: 1, name: 'Alice' }],
      }));
      setFixture.detectChanges();

      const button = personButton();
      expect(button).not.toBeNull();
      expect(button!.className).toContain('w-11');
      expect(button!.className).toContain('cursor-pointer');
      expect(button!.getAttribute('aria-label')).toBe('tooltip.filter_by_person');
      expect(button!.getAttribute('title')).toBe('Alice');
    });

    it('keeps person avatars small (24px) in a click-pinned floating tooltip, though still clickable', () => {
      setFixture.componentInstance.pinned.set(true); // not docked
      setFixture.componentInstance.photo.set(makePhoto({
        sequence_kind: null, persons: [{ id: 1, name: 'Alice' }],
      }));
      setFixture.detectChanges();

      const button = personButton();
      expect(button).not.toBeNull();
      expect(button!.className).toContain('w-6');
      expect(button!.className).not.toContain('w-11');
    });

    it('renders a plain, non-clickable image in plain hover mode (neither docked nor pinned)', () => {
      setFixture.componentInstance.photo.set(makePhoto({
        sequence_kind: null, persons: [{ id: 1, name: 'Alice' }],
      }));
      setFixture.detectChanges();

      expect(personButton()).toBeNull();
      const img = setFixture.nativeElement.querySelector('img[alt="Alice"]');
      expect(img).not.toBeNull();
      expect(img.className).toContain('w-6');
    });

    it('clicking a person avatar emits its id as a plain string -- a bare number would silently match nothing or the wrong set', () => {
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({
        sequence_kind: null, persons: [{ id: 42, name: 'Alice' }],
      }));
      setFixture.detectChanges();

      const tooltip = setFixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
      const emitted: string[] = [];
      tooltip.personSelected.subscribe((id: string) => emitted.push(id));

      personButton()!.click();

      expect(emitted).toEqual(['42']);
      expect(typeof emitted[0]).toBe('string');
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
