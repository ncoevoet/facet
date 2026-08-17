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
  standalone: true,
  imports: [PhotoCardComponent],
  template: `<app-photo-card [photo]="photo()" [config]="config()"
                             [burstFramesVisible]="burstFramesVisible()" />`,
})
class TestHostComponent {
  photo = signal<Photo>(makePhoto());
  config = signal<Record<string, unknown> | null>(null);
  burstFramesVisible = signal(false);
}

describe('PhotoCardComponent', () => {
  let fixture: ComponentFixture<TestHostComponent>;
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };

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

  describe('cycleStarRating', () => {
    it('emits next star value (0 → 1)', () => {
      const card = getCard();
      const spy = vi.fn();
      card.starClicked.subscribe(spy);
      card.cycleStarRating();
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ star: 1 }));
    });

    it('increments star rating (3 → 4)', () => {
      fixture.componentInstance.photo.set(makePhoto({ star_rating: 3 }));
      fixture.detectChanges();
      const card = getCard();
      const spy = vi.fn();
      card.starClicked.subscribe(spy);
      card.cycleStarRating();
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ star: 4 }));
    });

    it('wraps from 5 back to 0', () => {
      fixture.componentInstance.photo.set(makePhoto({ star_rating: 5 }));
      fixture.detectChanges();
      const card = getCard();
      const spy = vi.fn();
      card.starClicked.subscribe(spy);
      card.cycleStarRating();
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ star: 0 }));
    });

    it('treats null rating as 0', () => {
      fixture.componentInstance.photo.set(makePhoto({ star_rating: null }));
      fixture.detectChanges();
      const card = getCard();
      const spy = vi.fn();
      card.starClicked.subscribe(spy);
      card.cycleStarRating();
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ star: 1 }));
    });
  });

  describe('keeper hint badge', () => {
    function getTile(): HTMLElement {
      return fixture.nativeElement.querySelector('div[role="button"]') as HTMLElement;
    }

    function hasKeeperIcon(): boolean {
      const icons = Array.from(fixture.nativeElement.querySelectorAll('mat-icon')) as HTMLElement[];
      return icons.some(icon => icon.textContent?.trim() === 'arrow_circle_up');
    }

    it('renders the badge when keeper_hint.has_better is true', () => {
      fixture.componentInstance.photo.set(
        makePhoto({ keeper_hint: { has_better: true, best_path: '/other.jpg', keeper_prob: 0.2 } }),
      );
      fixture.detectChanges();

      expect(hasKeeperIcon()).toBe(true);
    });

    it('does not render the badge when keeper_hint.has_better is false', () => {
      fixture.componentInstance.photo.set(
        makePhoto({ keeper_hint: { has_better: false, best_path: null, keeper_prob: 0.1 } }),
      );
      fixture.detectChanges();

      expect(hasKeeperIcon()).toBe(false);
    });

    it('does not render the badge when keeper_hint is undefined', () => {
      fixture.componentInstance.photo.set(makePhoto());
      fixture.detectChanges();

      expect(hasKeeperIcon()).toBe(false);
    });

    it('includes the better-shot text in the tile aria-label when has_better is true', () => {
      fixture.componentInstance.photo.set(
        makePhoto({
          filename: 'shot.jpg',
          keeper_hint: { has_better: true, best_path: '/other.jpg', keeper_prob: 0.2 },
        }),
      );
      fixture.detectChanges();

      expect(getTile().getAttribute('aria-label')).toBe('shot.jpg, culling.reason.better_shot');
    });

    it('omits the better-shot text from the tile aria-label when has_better is false', () => {
      fixture.componentInstance.photo.set(
        makePhoto({
          filename: 'shot.jpg',
          keeper_hint: { has_better: false, best_path: null, keeper_prob: 0.1 },
        }),
      );
      fixture.detectChanges();

      expect(getTile().getAttribute('aria-label')).toBe('shot.jpg');
    });

    it('omits the better-shot text from the tile aria-label when keeper_hint is undefined', () => {
      fixture.componentInstance.photo.set(makePhoto({ filename: 'shot.jpg' }));
      fixture.detectChanges();

      expect(getTile().getAttribute('aria-label')).toBe('shot.jpg');
    });
  });

  describe('badge visibility config', () => {
    function iconNames(): string[] {
      return (Array.from(fixture.nativeElement.querySelectorAll('mat-icon')) as HTMLElement[])
        .map(icon => icon.textContent?.trim() ?? '');
    }

    it('draws every badge by default, so an install that configures nothing is unchanged', () => {
      fixture.componentInstance.photo.set(
        makePhoto({ keeper_hint: { has_better: true, best_path: '/o.jpg', keeper_prob: 0.2 } }),
      );
      fixture.detectChanges();

      expect(iconNames()).toContain('arrow_circle_up');
    });

    it('hides a badge the config turns off', () => {
      fixture.componentInstance.config.set({ badges: { keeper_hint: false } });
      fixture.componentInstance.photo.set(
        makePhoto({ keeper_hint: { has_better: true, best_path: '/o.jpg', keeper_prob: 0.2 } }),
      );
      fixture.detectChanges();

      expect(iconNames()).not.toContain('arrow_circle_up');
    });
  });

  describe('best-of-burst badge', () => {
    function hasBestBadge(): boolean {
      return Array.from(fixture.nativeElement.querySelectorAll('span'))
        .some(el => (el as HTMLElement).textContent?.trim() === 'ui.badges.best');
    }

    it('renders when the photo leads a burst whose other frames are on screen', () => {
      // The assertion this whole badge lacked: PRESENT for a truthy value.
      // Every earlier spec asserted a falsy one, which is why a badge keyed on
      // a field no backend ever sent passed for the life of the viewer.
      fixture.componentInstance.burstFramesVisible.set(true);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 'burst-1' }));
      fixture.detectChanges();

      expect(hasBestBadge()).toBe(true);
    });

    it('stays hidden while the burst is collapsed behind its lead', () => {
      fixture.componentInstance.burstFramesVisible.set(false);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 'burst-1' }));
      fixture.detectChanges();

      expect(hasBestBadge()).toBe(false);
    });

    it('stays hidden for a frame that does not lead its burst', () => {
      fixture.componentInstance.burstFramesVisible.set(true);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: false, burst_group_id: 'burst-1' }));
      fixture.detectChanges();

      expect(hasBestBadge()).toBe(false);
    });

    it('stays hidden for a standalone photo that is in no burst at all, even though is_burst_lead is also the sentinel for "not a hidden burst member"', () => {
      fixture.componentInstance.burstFramesVisible.set(true);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: null }));
      fixture.detectChanges();

      expect(hasBestBadge()).toBe(false);
    });

    it('can be turned off in the config', () => {
      fixture.componentInstance.config.set({ badges: { best_of_burst: false } });
      fixture.componentInstance.burstFramesVisible.set(true);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 'burst-1' }));
      fixture.detectChanges();

      expect(hasBestBadge()).toBe(false);
    });
  });

  describe('clipping badge', () => {
    function clipIcon(): string | null {
      const icons = Array.from(fixture.nativeElement.querySelectorAll('mat-icon')) as HTMLElement[];
      const found = icons.find(
        icon => icon.textContent?.trim() === 'flare' || icon.textContent?.trim() === 'brightness_low',
      );
      return found ? found.textContent!.trim() : null;
    }

    it('badges a photo whose highlights clip past the threshold', () => {
      fixture.componentInstance.photo.set(makePhoto({ channel_clip_highlight_pct: 41.7 }));
      fixture.detectChanges();

      expect(clipIcon()).toBe('flare');
    });

    it('leaves a photo below the threshold alone', () => {
      // 2.35% is the p90 of the sampled library — common, and not worth a badge.
      fixture.componentInstance.photo.set(makePhoto({ channel_clip_highlight_pct: 2.35 }));
      fixture.detectChanges();

      expect(clipIcon()).toBeNull();
    });

    it('says nothing about a photo that was never measured', () => {
      // null is unknown, not clean — and must not be compared as if it were 0.
      fixture.componentInstance.photo.set(
        makePhoto({ channel_clip_highlight_pct: null, channel_clip_shadow_pct: null }),
      );
      fixture.detectChanges();

      expect(clipIcon()).toBeNull();
    });

    it('ignores shadow clipping by default, because it is usually deliberate', () => {
      fixture.componentInstance.photo.set(makePhoto({ channel_clip_shadow_pct: 30.4 }));
      fixture.detectChanges();

      expect(clipIcon()).toBeNull();
    });

    it('badges shadows once they are opted in', () => {
      fixture.componentInstance.config.set({ badges: { clipping_shadow: true } });
      fixture.componentInstance.photo.set(makePhoto({ channel_clip_shadow_pct: 30.4 }));
      fixture.detectChanges();

      expect(clipIcon()).toBe('brightness_low');
    });

    it('prefers the highlight badge when both directions clip', () => {
      fixture.componentInstance.config.set({ badges: { clipping_shadow: true } });
      fixture.componentInstance.photo.set(
        makePhoto({ channel_clip_highlight_pct: 20, channel_clip_shadow_pct: 30 }),
      );
      fixture.detectChanges();

      expect(clipIcon()).toBe('flare');
    });

    it('honours a configured threshold', () => {
      fixture.componentInstance.config.set({ clipping: { badge_percent: 1 } });
      fixture.componentInstance.photo.set(makePhoto({ channel_clip_highlight_pct: 2.35 }));
      fixture.detectChanges();

      expect(clipIcon()).toBe('flare');
    });

    it('can be turned off entirely', () => {
      fixture.componentInstance.config.set({ badges: { clipping_highlight: false } });
      fixture.componentInstance.photo.set(makePhoto({ channel_clip_highlight_pct: 41.7 }));
      fixture.detectChanges();

      expect(clipIcon()).toBeNull();
    });
  });
});

describe('PhotoCardComponent tooltip emission', () => {
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };

  /** Drive the card directly: this is about which gesture emits, not markup. */
  function card(mode: 'hover' | 'click' | 'off' | 'panel', panelActivation?: 'hover' | 'click' | 'both') {
    TestBed.configureTestingModule({
      imports: [PhotoCardComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    });
    const fixture = TestBed.createComponent(PhotoCardComponent);
    fixture.componentRef.setInput('photo', makePhoto());
    fixture.componentRef.setInput('tooltipMode', mode);
    if (panelActivation) fixture.componentRef.setInput('panelActivation', panelActivation);
    fixture.detectChanges();
    const shown: string[] = [];
    let hidden = 0;
    fixture.componentInstance.tooltipShow.subscribe(e => shown.push(e.photo.path));
    fixture.componentInstance.tooltipHide.subscribe(() => { hidden++; });
    return { c: fixture.componentInstance, shown, hidden: () => hidden };
  }

  const clickEvent = {} as MouseEvent;

  afterEach(() => TestBed.resetTestingModule());

  it('hover mode reports hover but not clicks', () => {
    const { c, shown } = card('hover');
    c.onMouseEnter(clickEvent);
    expect(shown).toEqual(['/test.jpg']);
    c.onSelect(clickEvent);
    expect(shown).toEqual(['/test.jpg']);
  });

  it('click mode reports clicks but not hover', () => {
    const { c, shown } = card('click');
    c.onMouseEnter(clickEvent);
    expect(shown).toEqual([]);
    c.onSelect(clickEvent);
    expect(shown).toEqual(['/test.jpg']);
  });

  it('panel mode reports BOTH, since the rail is parked rather than chasing the cursor', () => {
    const { c, shown } = card('panel');
    c.onMouseEnter(clickEvent);
    c.onSelect(clickEvent);
    expect(shown).toEqual(['/test.jpg', '/test.jpg']);
  });

  it('panel mode still reports mouse-out, which the gallery ignores while the rail shows', () => {
    const { c, hidden } = card('panel');
    c.onMouseLeave();
    expect(hidden()).toBe(1);
  });

  // --- panelActivation: which gesture(s) retarget panel mode ----------------

  it('activation "both" (the default) retargets on hover AND click', () => {
    const { c, shown } = card('panel', 'both');
    c.onMouseEnter(clickEvent);
    c.onSelect(clickEvent);
    expect(shown).toEqual(['/test.jpg', '/test.jpg']);
  });

  it('activation "hover" retargets on hover but does NOT retarget on click', () => {
    const { c, shown } = card('panel', 'hover');
    c.onMouseEnter(clickEvent);
    expect(shown).toEqual(['/test.jpg']);
    c.onSelect(clickEvent);
    // A test that only checked the 'both' default would pass even if 'hover'
    // also retargeted on click -- assert the click contributed nothing.
    expect(shown).toEqual(['/test.jpg']);
  });

  it('activation "click" retargets on click but does NOT retarget on hover', () => {
    const { c, shown } = card('panel', 'click');
    c.onMouseEnter(clickEvent);
    // A test that only checked the 'both' default would pass even if 'click'
    // also retargeted on hover -- assert the hover contributed nothing.
    expect(shown).toEqual([]);
    c.onSelect(clickEvent);
    expect(shown).toEqual(['/test.jpg']);
  });

  it('activation "click" does not clear the panel on mouse-out -- it was deliberately pinned there', () => {
    const { c, hidden } = card('panel', 'click');
    c.onMouseLeave();
    expect(hidden()).toBe(0);
  });

  it('activation "hover" still clears the panel on mouse-out', () => {
    const { c, hidden } = card('panel', 'hover');
    c.onMouseLeave();
    expect(hidden()).toBe(1);
  });

  it('Space retargets the panel regardless of activation -- a keyboard user has no hover to fall back on', () => {
    const keyEvent = { preventDefault: () => {} } as unknown as Event;
    for (const activation of ['hover', 'click', 'both'] as const) {
      const { c, shown } = card('panel', activation);
      c.onKeySelect(keyEvent);
      expect(shown).toEqual(['/test.jpg']);
      TestBed.resetTestingModule();
    }
  });

  it('off mode reports nothing at all', () => {
    const { c, shown, hidden } = card('off');
    c.onMouseEnter(clickEvent);
    c.onSelect(clickEvent);
    c.onMouseLeave();
    expect(shown).toEqual([]);
    expect(hidden()).toBe(0);
  });

  it('selecting still emits selectionChange in every mode', () => {
    for (const mode of ['hover', 'click', 'off', 'panel'] as const) {
      const { c } = card(mode);
      const selected: string[] = [];
      c.selectionChange.subscribe(e => selected.push(e.photo.path));
      c.onSelect(clickEvent);
      expect(selected).toEqual(['/test.jpg']);
      TestBed.resetTestingModule();
    }
  });

  // Space is the keyboard's click. Reporting the selection but not the photo
  // left a keyboard user selecting cards while the panel stayed on whatever the
  // mouse last touched — the one gesture that can reach it on a touch screen.
  it('Space reports the photo in the modes a click would', () => {
    const keyEvent = { preventDefault: () => {} } as unknown as Event;
    for (const mode of ['click', 'panel'] as const) {
      const { c, shown } = card(mode);
      c.onKeySelect(keyEvent);
      expect(shown).toEqual(['/test.jpg']);
      TestBed.resetTestingModule();
    }
  });

  it('Space reports nothing in the modes a click would not', () => {
    const keyEvent = { preventDefault: () => {} } as unknown as Event;
    for (const mode of ['hover', 'off'] as const) {
      const { c, shown } = card(mode);
      c.onKeySelect(keyEvent);
      expect(shown).toEqual([]);
      TestBed.resetTestingModule();
    }
  });

  it('Space still selects, whatever the tooltip mode', () => {
    const keyEvent = { preventDefault: () => {} } as unknown as Event;
    for (const mode of ['hover', 'click', 'off', 'panel'] as const) {
      const { c } = card(mode);
      const selected: string[] = [];
      c.selectionChange.subscribe(e => selected.push(e.photo.path));
      c.onKeySelect(keyEvent);
      expect(selected).toEqual(['/test.jpg']);
      TestBed.resetTestingModule();
    }
  });

});
