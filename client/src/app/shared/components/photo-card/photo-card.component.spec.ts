import { Component, signal, ChangeDetectionStrategy } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { OverlayContainer } from '@angular/cdk/overlay';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatTooltip } from '@angular/material/tooltip';
import { MatMenuTrigger } from '@angular/material/menu';
import { I18nService } from '../../../core/services/i18n.service';
import { KeyboardMappingService, KEYMAP_STORAGE_KEY } from '../../../core/services/keyboard-mapping.service';
import { PhotoCardComponent } from './photo-card.component';
import { CardActionsConfig } from './card-actions';
import type { Photo } from '../../models/photo.model';
import { makePhoto } from '../../../../testing/photo.fixture';

/* eslint-disable @angular-eslint/component-selector */
@Component({
  selector: 'test-host',
  standalone: true,
  imports: [PhotoCardComponent],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `<app-photo-card [photo]="photo()" [config]="config()"
                             [burstFramesVisible]="burstFramesVisible()"
                             [collapsedSetKinds]="collapsedSetKinds()"
                             [isEditionMode]="isEditionMode()"
                             [metricRanges]="metricRanges()"
                             [currentSort]="currentSort()"
                             (selectionChange)="selected.push($event.photo.path)"
                             (doubleClicked)="opened.push($event.path)" />`,
})
class TestHostComponent {
  photo = signal<Photo>(makePhoto());
  config = signal<Record<string, unknown> | null>(null);
  burstFramesVisible = signal(false);
  collapsedSetKinds = signal<readonly string[]>([]);
  isEditionMode = signal(false);
  metricRanges = signal<Record<string, { min: number; max: number; buckets: number[] }>>({});
  currentSort = signal('aggregate');
  selected: string[] = [];
  opened: string[] = [];
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

  describe('score badge library placement', () => {
    const badgeTooltips = () => fixture.debugElement.queryAll(By.directive(MatTooltip))
      .map(el => el.injector.get(MatTooltip).message)
      .filter(message => message.startsWith('gallery.aggregate_score'));

    it('keeps the plain tooltip when no distribution was loaded', () => {
      fixture.componentInstance.photo.set(makePhoto({ aggregate: 7.5 }));
      fixture.detectChanges();
      expect(badgeTooltips()).toEqual(['gallery.aggregate_score']);
    });

    it('says where the score sits in the library when its distribution is known', () => {
      fixture.componentInstance.photo.set(makePhoto({ aggregate: 7.5 }));
      fixture.componentInstance.metricRanges.set({ aggregate: { min: 0, max: 10, buckets: [1, 1] } });
      fixture.detectChanges();
      expect(badgeTooltips()).toEqual(['gallery.aggregate_score · photo_detail.distribution.top']);
      expect(mockI18n.t).toHaveBeenCalledWith('photo_detail.distribution.top', { pct: 25 });
    });

    describe('under another sort', () => {
      const sortTooltips = () => fixture.debugElement.queryAll(By.directive(MatTooltip))
        .map(el => el.injector.get(MatTooltip).message)
        .filter(message => message.startsWith('gallery.sort_score'));
      const even = { min: 0, max: 10, buckets: [1, 1] };

      beforeEach(() => mockI18n.t.mockClear());

      it('ranks the sorted column, not the aggregate', () => {
        fixture.componentInstance.photo.set(makePhoto({ aggregate: 7.5, aesthetic: 2.5 }));
        fixture.componentInstance.metricRanges.set({ aggregate: even, aesthetic: even });
        fixture.componentInstance.currentSort.set('aesthetic');
        fixture.detectChanges();
        expect(sortTooltips()).toEqual(['gallery.sort_score (aesthetic) · photo_detail.distribution.top']);
        expect(mockI18n.t).toHaveBeenCalledWith('photo_detail.distribution.top', { pct: 75 });
      });

      it('ranks the aggregate the badge falls back to for a non-numeric sort', () => {
        fixture.componentInstance.photo.set(makePhoto({ aggregate: 7.5 }));
        fixture.componentInstance.metricRanges.set({ aggregate: even });
        fixture.componentInstance.currentSort.set('date_taken');
        fixture.detectChanges();
        expect(mockI18n.t).toHaveBeenCalledWith('photo_detail.distribution.top', { pct: 25 });
      });

      it('keeps the plain tooltip for a sorted column without a distribution', () => {
        fixture.componentInstance.photo.set(makePhoto({ aggregate: 7.5, star_rating: 4 }));
        fixture.componentInstance.metricRanges.set({ aggregate: even });
        fixture.componentInstance.currentSort.set('star_rating');
        fixture.detectChanges();
        expect(sortTooltips()).toEqual(['gallery.sort_score (star_rating)']);
      });
    });
  });

  it('should create with required photo input', () => {
    const card = getCard();
    expect(card).toBeTruthy();
    expect(card.photo().filename).toBe('test.jpg');
  });

  it('opens a stack from its matching/permitted count badge without selecting the representative', () => {
    fixture.componentInstance.photo.set(makePhoto({ stack_id: 'stack', stack_count: 2, stack_total_count: 4 }));
    fixture.detectChanges();
    const opened = vi.fn(); getCard().openStackClicked.subscribe(opened);
    const button = fixture.nativeElement.querySelector('[data-stack-badge]') as HTMLButtonElement;
    // The bubble shows the matching count; the permitted total lives in the
    // tooltip/aria-label, which a 14px bubble has no room for.
    expect(button.textContent?.replace('layers', '').trim()).toBe('2');
    expect(button.getAttribute('aria-label')).toBe('stacks.badge_filtered');
    button.click();
    expect(opened).toHaveBeenCalledWith(fixture.componentInstance.photo());
    expect(fixture.componentInstance.selected).toEqual([]);
    expect(fixture.nativeElement.querySelector('img').src).toContain('/thumbnail?');
  });

  it('offers the stack as a configurable hover action only on a stacked photo', () => {
    fixture.componentInstance.photo.set(makePhoto({ stack_id: 'stack', stack_count: 3, stack_total_count: 3 }));
    fixture.detectChanges();
    const opened = vi.fn(); getCard().openStackClicked.subscribe(opened);
    const action = fixture.nativeElement.querySelector('button[aria-label="photoCard.stack_set"]') as HTMLButtonElement;
    action.click();
    expect(opened).toHaveBeenCalledWith(fixture.componentInstance.photo());
    fixture.componentInstance.photo.set(makePhoto({}));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('button[aria-label="photoCard.stack_set"]')).toBeNull();
    expect(fixture.nativeElement.querySelector('[data-stack-badge]')).toBeNull();
  });

  it('hides the stack badge but keeps the hover action when badges.stack is off', () => {
    fixture.componentInstance.config.set({ badges: { stack: false } });
    fixture.componentInstance.photo.set(makePhoto({ stack_id: 'stack', stack_count: 3, stack_total_count: 3 }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-stack-badge]')).toBeNull();
    expect(fixture.nativeElement.querySelector('button[aria-label="photoCard.stack_set"]')).not.toBeNull();
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

  it('fills a mosaic tile at every width, without relying on the md: variants', () => {
    const cardFixture = TestBed.createComponent(PhotoCardComponent);
    cardFixture.componentRef.setInput('photo', makePhoto());
    cardFixture.componentRef.setInput('hideDetails', true);
    cardFixture.componentRef.setInput('mosaicMode', true);
    cardFixture.detectChanges();
    const el = cardFixture.nativeElement as HTMLElement;
    const img = el.querySelector('img')!;
    expect(img.classList.contains('h-full')).toBe(true);
    expect(img.classList.contains('object-cover')).toBe(true);
    expect(img.parentElement!.classList.contains('h-full')).toBe(true);
  });

  it('fills the tile below md too when details are hidden (no dead strip)', () => {
    const cardFixture = TestBed.createComponent(PhotoCardComponent);
    cardFixture.componentRef.setInput('photo', makePhoto());
    cardFixture.componentRef.setInput('hideDetails', true);
    cardFixture.detectChanges();
    const img = (cardFixture.nativeElement as HTMLElement).querySelector('img')!;
    expect(img.classList.contains('h-full')).toBe(true);
    expect(img.classList.contains('object-cover')).toBe(true);
  });

  it('never asks for a thumbnail above the stored 640 px', () => {
    const cardFixture = TestBed.createComponent(PhotoCardComponent);
    cardFixture.componentRef.setInput('photo', makePhoto());
    cardFixture.componentRef.setInput('thumbSize', 900);
    cardFixture.detectChanges();

    expect(cardFixture.componentInstance.thumbSize()).toBe(640);
    const img: HTMLImageElement = cardFixture.nativeElement.querySelector('img[src*="/thumbnail"]');
    expect(img.getAttribute('src')).toContain('size=640');
  });

  it('should reflect updated photo input', () => {
    fixture.componentInstance.photo.set(makePhoto({ filename: 'updated.jpg', aggregate: 9.0 }));
    fixture.detectChanges();
    const card = getCard();
    expect(card.photo().filename).toBe('updated.jpg');
    expect(card.photo().aggregate).toBe(9.0);
  });

  it('accepts a null aggregate (an unscored row): blank badge, lowest-bucket class, no throw', () => {
    // The wire type: a row the scoring pass hasn't reached yet sends
    // `aggregate: null`, not a number -- see photo.model.ts. Sorting by
    // 'aggregate' (the default) routes it through SortScorePipe ->
    // ScoreClassPipe -> FixedPipe; null must render as BLANK, never "0.0" --
    // that would turn "not scored yet" into "scored zero".
    fixture.componentInstance.photo.set(makePhoto({ aggregate: null }));
    fixture.detectChanges();
    const card = getCard();
    expect(card.photo().aggregate).toBeNull();
    const badge = fixture.nativeElement.querySelector('span.text-xs.font-bold') as HTMLElement;
    expect(badge.textContent?.trim()).toBe('');
    expect(badge.className).toContain('bg-red-600');
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

  describe('persistent kept badge', () => {
    it.each([
      [false, false, false, false],
      [false, true, false, false],
      [true, false, false, false],
      [true, true, false, true],
      [true, true, true, false],
    ])('edition=%s kept=%s rejected=%s renders badge=%s', (edition, kept, rejected, shown) => {
      fixture.componentInstance.isEditionMode.set(edition);
      fixture.componentInstance.photo.set(makePhoto({ is_kept: kept, is_rejected: rejected }));
      fixture.detectChanges();
      const badge = (fixture.nativeElement as HTMLElement).querySelector('[aria-label="review.kept"]');
      expect(badge !== null).toBe(shown);
      if (badge) expect(badge.querySelector('mat-icon')?.textContent?.trim()).toBe('check');
    });

    it('removes an existing badge when edition access ends', () => {
      fixture.componentInstance.isEditionMode.set(true);
      fixture.componentInstance.photo.set(makePhoto({ is_kept: true }));
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('[aria-label="review.kept"]')).not.toBeNull();
      fixture.componentInstance.isEditionMode.set(false);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('[aria-label="review.kept"]')).toBeNull();
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
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 1 }));
      fixture.detectChanges();

      expect(hasBestBadge()).toBe(true);
    });

    it('renders for the first burst group, whose id is the falsy 0', () => {
      // `burst_group_id` counts from 0 (processing/scorer.py), so the library's
      // first burst group is a valid id that a truthiness test discards. Only
      // null means "in no burst" -- the case asserted false below.
      fixture.componentInstance.burstFramesVisible.set(true);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 0 }));
      fixture.detectChanges();

      expect(hasBestBadge()).toBe(true);
    });

    it('stays hidden while the burst is collapsed behind its lead', () => {
      fixture.componentInstance.burstFramesVisible.set(false);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 1 }));
      fixture.detectChanges();

      expect(hasBestBadge()).toBe(false);
    });

    it('stays hidden for a frame that does not lead its burst', () => {
      fixture.componentInstance.burstFramesVisible.set(true);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: false, burst_group_id: 1 }));
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
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 1 }));
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

  describe('set kind badge', () => {
    function setIcon(): string | null {
      const icons = Array.from(fixture.nativeElement.querySelectorAll('mat-icon')) as HTMLElement[];
      const found = icons.find(icon => ['hdr_on', 'panorama_photosphere', 'vrpano', 'burst_mode', 'content_copy']
        .includes(icon.textContent?.trim() ?? ''));
      return found ? found.textContent!.trim() : null;
    }

    it('badges a collapsed bracket by sequence_kind', () => {
      fixture.componentInstance.collapsedSetKinds.set(['bracket']);
      fixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket' }));
      fixture.detectChanges();

      expect(setIcon()).toBe('hdr_on');
    });

    it('badges a collapsed panorama by sequence_kind', () => {
      fixture.componentInstance.collapsedSetKinds.set(['panorama', 'hdr_panorama']);
      fixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'panorama' }));
      fixture.detectChanges();

      expect(setIcon()).toBe('panorama_photosphere');
    });

    it('badges a burst lead when bursts are collapsed', () => {
      fixture.componentInstance.collapsedSetKinds.set(['burst']);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 1 }));
      fixture.detectChanges();

      expect(setIcon()).toBe('burst_mode');
    });

    it('badges a burst lead whose group id is the falsy 0', () => {
      fixture.componentInstance.collapsedSetKinds.set(['burst']);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: 0 }));
      fixture.detectChanges();

      expect(setIcon()).toBe('burst_mode');
    });

    it('stays hidden for a burst lead when burst_group_id is null', () => {
      fixture.componentInstance.collapsedSetKinds.set(['burst']);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: true, burst_group_id: null }));
      fixture.detectChanges();

      expect(setIcon()).toBeNull();
    });

    it('stays hidden for a burst photo that does not lead its group', () => {
      fixture.componentInstance.collapsedSetKinds.set(['burst']);
      fixture.componentInstance.photo.set(makePhoto({ is_burst_lead: false, burst_group_id: 1 }));
      fixture.detectChanges();

      expect(setIcon()).toBeNull();
    });

    it('badges a duplicate lead when duplicates are collapsed', () => {
      fixture.componentInstance.collapsedSetKinds.set(['duplicate']);
      fixture.componentInstance.photo.set(makePhoto({ is_duplicate_lead: true, duplicate_group_id: 1 }));
      fixture.detectChanges();

      expect(setIcon()).toBe('content_copy');
    });

    it('stays hidden when the kind is not in collapsedSetKinds', () => {
      fixture.componentInstance.collapsedSetKinds.set(['panorama', 'hdr_panorama']);
      fixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket' }));
      fixture.detectChanges();

      expect(setIcon()).toBeNull();
    });

    it('prefers sequence_kind over a burst lead when both are collapsed', () => {
      fixture.componentInstance.collapsedSetKinds.set(['bracket', 'burst']);
      fixture.componentInstance.photo.set(
        makePhoto({ sequence_kind: 'bracket', is_burst_lead: true, burst_group_id: 1 }),
      );
      fixture.detectChanges();

      expect(setIcon()).toBe('hdr_on');
    });

    it('uses the best_of_* key, not the plain set-kind label, for tooltip and aria-label', () => {
      fixture.componentInstance.collapsedSetKinds.set(['bracket']);
      fixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket' }));
      fixture.detectChanges();

      const icon = Array.from(fixture.nativeElement.querySelectorAll('mat-icon') as HTMLElement[])
        .find(el => el.textContent?.trim() === 'hdr_on');
      const badge = icon!.parentElement as HTMLElement;
      expect(badge.getAttribute('aria-label')).toBe('ui.badges.best_of_bracket');
    });

    function badgeElement(): HTMLElement {
      const icon = Array.from(fixture.nativeElement.querySelectorAll('mat-icon') as HTMLElement[])
        .find(el => ['hdr_on', 'panorama_photosphere', 'vrpano', 'burst_mode', 'content_copy']
          .includes(el.textContent?.trim() ?? ''));
      return icon!.parentElement as HTMLElement;
    }

    it('packs the badge flush right when neither favorite nor rejected shows', () => {
      fixture.componentInstance.isEditionMode.set(true);
      fixture.componentInstance.collapsedSetKinds.set(['bracket']);
      fixture.componentInstance.photo.set(
        makePhoto({ sequence_kind: 'bracket', is_favorite: false, is_rejected: false }),
      );
      fixture.detectChanges();

      expect(badgeElement().className).toContain('right-1.5');
      expect(badgeElement().className).not.toContain('right-9');
    });

    it('packs the badge into the rejected slot when only favorite shows', () => {
      fixture.componentInstance.isEditionMode.set(true);
      fixture.componentInstance.collapsedSetKinds.set(['bracket']);
      fixture.componentInstance.photo.set(
        makePhoto({ sequence_kind: 'bracket', is_favorite: true, is_rejected: false }),
      );
      fixture.detectChanges();

      expect(badgeElement().className).toContain('right-9');
    });

    it('packs the badge clear of both slots when rejected shows', () => {
      fixture.componentInstance.isEditionMode.set(true);
      fixture.componentInstance.collapsedSetKinds.set(['bracket']);
      fixture.componentInstance.photo.set(
        makePhoto({ sequence_kind: 'bracket', is_favorite: false, is_rejected: true }),
      );
      fixture.detectChanges();

      expect(badgeElement().className).toContain('right-[4.125rem]');
    });

    it('packs the badge clear of both slots when favorite and rejected both show', () => {
      fixture.componentInstance.isEditionMode.set(true);
      fixture.componentInstance.collapsedSetKinds.set(['bracket']);
      fixture.componentInstance.photo.set(
        makePhoto({ sequence_kind: 'bracket', is_favorite: true, is_rejected: true }),
      );
      fixture.detectChanges();

      expect(badgeElement().className).toContain('right-[4.125rem]');
    });

    it('adds the hover-clear class in edition mode', () => {
      fixture.componentInstance.isEditionMode.set(true);
      fixture.componentInstance.collapsedSetKinds.set(['bracket']);
      fixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket' }));
      fixture.detectChanges();

      expect(badgeElement().className).toContain('md:group-hover/img:right-[4.125rem]');
    });

    it('omits the hover-clear class outside edition mode', () => {
      fixture.componentInstance.isEditionMode.set(false);
      fixture.componentInstance.collapsedSetKinds.set(['bracket']);
      fixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket' }));
      fixture.detectChanges();

      expect(badgeElement().className).not.toContain('md:group-hover/img:right-[4.125rem]');
    });
  });
  describe('persistent badges and hover bar', () => {
    it('keeps the badges at bottom-1 and the hover bar flush with the bottom edge, with no strip', () => {
      fixture.componentInstance.isEditionMode.set(true);
      fixture.componentInstance.config.set({ features: { show_rating_controls: true } });
      fixture.componentInstance.photo.set(makePhoto({ star_rating: 3, is_favorite: true, is_rejected: true }));
      fixture.detectChanges();
      const badges = [...fixture.nativeElement.querySelectorAll('div.absolute.w-7.h-7')] as HTMLElement[];
      expect(badges.length).toBeGreaterThanOrEqual(3);
      for (const b of badges) expect(b.className).toMatch(/(^| )bottom-1( |$)/);
      const overlay = fixture.nativeElement.querySelector('div.z-10.inset-x-0') as HTMLElement;
      expect(overlay.className).toContain('bottom-0');
      expect(fixture.nativeElement.querySelector('button.inset-x-0.bottom-0')).toBeNull();
      expect(fixture.nativeElement.querySelector('img').className).not.toContain('brightness-50');
    });
  });
});

describe('PhotoCardComponent unassigned faces action', () => {
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };

  function createCard(photo: Photo, isEditionMode: boolean): ComponentFixture<PhotoCardComponent> {
    TestBed.configureTestingModule({
      imports: [PhotoCardComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    });
    const fixture = TestBed.createComponent(PhotoCardComponent);
    fixture.componentRef.setInput('photo', photo);
    fixture.componentRef.setInput('isEditionMode', isEditionMode);
    fixture.detectChanges();
    return fixture;
  }

  function hasAssignFaceAction(fixture: ComponentFixture<PhotoCardComponent>): boolean {
    return Array.from(fixture.nativeElement.querySelectorAll('mat-icon'))
      .some(icon => (icon as HTMLElement).textContent?.trim() === 'person_add');
  }

  afterEach(() => TestBed.resetTestingModule());

  it('renders the assign-face action in edition mode when faces are unassigned', () => {
    const fixture = createCard(makePhoto({ unassigned_faces: 3 }), true);
    expect(hasAssignFaceAction(fixture)).toBe(true);
  });

  it('hides the assign-face action outside edition mode even with unassigned faces', () => {
    const fixture = createCard(makePhoto({ unassigned_faces: 3 }), false);
    expect(hasAssignFaceAction(fixture)).toBe(false);
  });

  it('hides the assign-face action in edition mode when there are no unassigned faces', () => {
    const fixture = createCard(makePhoto({ unassigned_faces: 0 }), true);
    expect(hasAssignFaceAction(fixture)).toBe(false);
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

describe('PhotoCardComponent current-photo marker', () => {
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };

  interface MarkerInputs { isActive?: boolean; gridHasActiveCard?: boolean; isSelected?: boolean }

  function createCard(inputs: MarkerInputs = {}): ComponentFixture<PhotoCardComponent> {
    TestBed.configureTestingModule({
      imports: [PhotoCardComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    });
    const fixture = TestBed.createComponent(PhotoCardComponent);
    fixture.componentRef.setInput('photo', makePhoto());
    for (const [name, value] of Object.entries(inputs)) fixture.componentRef.setInput(name, value);
    fixture.detectChanges();
    return fixture;
  }

  /** The marker is asserted on the HOST, not on the tile inside it. The host
   *  carries `content-visibility: auto`, whose paint containment clips whatever
   *  a descendant draws outside the card -- so only the host's own outline
   *  reaches the gutter. */
  function host(fixture: ComponentFixture<PhotoCardComponent>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function tile(fixture: ComponentFixture<PhotoCardComponent>): HTMLElement {
    return fixture.nativeElement.querySelector('div[role="button"]') as HTMLElement;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('shows the focused-card shortcut hint only while rating controls are enabled', () => {
    const fixture = createCard({ isActive: true, gridHasActiveCard: true });
    fixture.componentRef.setInput('isEditionMode', true);
    fixture.componentRef.setInput('config', { features: { show_rating_controls: true } });
    fixture.detectChanges();
    const hint = () => [...host(fixture).querySelectorAll('div[aria-hidden="true"]')]
      .find(node => node.textContent?.trim() === 'photoCard.key_hint');
    expect(hint()).toBeDefined();
    fixture.componentRef.setInput('config', { features: { show_rating_controls: false } });
    fixture.detectChanges();
    expect(hint()).toBeUndefined();
    fixture.componentRef.setInput('config', { features: { show_rating_controls: true } });
    fixture.detectChanges();
    expect(hint()).toBeDefined();
    fixture.componentRef.setInput('isEditionMode', false);
    fixture.detectChanges();
    expect(hint()).toBeUndefined();
  });

  it('names the favourite and reject keys the user mapped in the focused-card hint', () => {
    localStorage.removeItem(KEYMAP_STORAGE_KEY);
    const fixture = createCard({ isActive: true, gridHasActiveCard: true });
    const mapping = TestBed.inject(KeyboardMappingService);
    mapping.setKey('favourite', 'z');
    fixture.componentRef.setInput('isEditionMode', true);
    fixture.componentRef.setInput('config', { features: { show_rating_controls: true } });
    fixture.detectChanges();
    expect(TestBed.inject(I18nService).t).toHaveBeenCalledWith('photoCard.key_hint', { favourite: 'Z', reject: 'X' });
    mapping.resetAll();
    localStorage.removeItem(KEYMAP_STORAGE_KEY);
  });

  it.each([
    ['not the active card', { isActive: false, gridHasActiveCard: true, mosaicMode: false }],
    ['no card active in the grid', { isActive: true, gridHasActiveCard: false, mosaicMode: false }],
    ['mosaic layout', { isActive: true, gridHasActiveCard: true, mosaicMode: true }],
  ])('hides the focused-card shortcut hint for %s even with edition and rating controls on', (_name, inputs) => {
    const fixture = createCard(inputs);
    fixture.componentRef.setInput('isEditionMode', true);
    fixture.componentRef.setInput('config', { features: { show_rating_controls: true } });
    fixture.detectChanges();
    expect([...host(fixture).querySelectorAll('div[aria-hidden="true"]')]
      .find(node => node.textContent?.trim() === 'photoCard.key_hint')).toBeUndefined();
  });

  it('is neither current nor dimmed by default', () => {
    const fixture = createCard();
    expect(fixture.componentInstance.isActive()).toBe(false);
    expect(fixture.componentInstance.gridHasActiveCard()).toBe(false);
    expect(host(fixture).classList.contains('outline-4')).toBe(false);
    expect(host(fixture).classList.contains('opacity-50')).toBe(false);
  });

  it('frames the current card with an outline offset off the photo', () => {
    const classes = host(createCard({ isActive: true, gridHasActiveCard: true })).classList;
    expect(classes.contains('outline-4')).toBe(true);
    expect(classes.contains('outline-[var(--mat-sys-tertiary)]')).toBe(true);
    expect(classes.contains('outline-offset-2')).toBe(true);
    expect(classes.contains('z-10')).toBe(true);
  });

  it('leaves the current card at full strength', () => {
    expect(host(createCard({ isActive: true, gridHasActiveCard: true })).classList.contains('opacity-50'))
      .toBe(false);
  });

  it('dims a card that is not the current one', () => {
    const fixture = createCard({ isActive: false, gridHasActiveCard: true });
    expect(host(fixture).classList.contains('opacity-50')).toBe(true);
    expect(host(fixture).classList.contains('outline-4')).toBe(false);
  });

  it('dims nothing while the grid has no current photo at all', () => {
    // The gallery's cursor is -1 until it first lands somewhere. Dimming on
    // that state would fade every tile of a gallery nobody has navigated yet,
    // which is the whole grid on first load.
    expect(host(createCard({ isActive: false, gridHasActiveCard: false })).classList.contains('opacity-50'))
      .toBe(false);
  });

  it('keeps the selection ring and the current-photo frame telling different stories', () => {
    // A card can be both at once: selection is the set the batch actions act
    // on, current is the one photo the next rating keystroke lands on.
    const fixture = createCard({ isActive: true, gridHasActiveCard: true, isSelected: true });
    expect(tile(fixture).classList.contains('ring-2')).toBe(true);
    expect(tile(fixture).classList.contains('ring-[var(--mat-sys-primary)]')).toBe(true);
    expect(host(fixture).classList.contains('outline-[var(--mat-sys-tertiary)]')).toBe(true);
  });

  it('does not dim a card that is merely unselected', () => {
    expect(host(createCard({ isSelected: false })).classList.contains('opacity-50')).toBe(false);
  });

  it('reports the current card to assistive technology', () => {
    expect(tile(createCard({ isActive: true })).getAttribute('aria-current')).toBe('true');
  });

  it('says nothing about a card that is not the current one', () => {
    expect(tile(createCard()).getAttribute('aria-current')).toBeNull();
  });

  it('keeps the focus-visible outline, which still means genuine keyboard focus', () => {
    expect(tile(createCard({ isActive: true })).className).toContain('focus-visible:outline-2');
  });

  it('reserves room for the frame and for the bar the grid scrolls it under', () => {
    // The grid moves its cursor with scrollIntoView({ block: 'nearest' }),
    // which stops at the scrollport's edge and knows nothing of the action bar
    // fixed across the bottom of it.
    const classes = host(createCard()).classList;
    expect(classes.contains('scroll-mb-48')).toBe(true);
    expect(classes.contains('scroll-mt-2')).toBe(true);
  });

  it('reserves it whether or not it is the current card', () => {
    // Deliberately unconditional: scroll-margin does nothing until something
    // calls scrollIntoView on the card, and the one caller runs inside the
    // keydown handler, ahead of the change detection a conditional class would
    // be waiting on.
    const classes = host(createCard({ isActive: true, gridHasActiveCard: true })).classList;
    expect(classes.contains('scroll-mb-48')).toBe(true);
    expect(classes.contains('scroll-mt-2')).toBe(true);
  });

  it('carries the class that cancels the dimming under "reduce transparency"', () => {
    // jsdom cannot evaluate `prefers-reduced-transparency`, so this only proves
    // the class is BOUND to the host, not that the media query wins the
    // cascade at runtime -- that is proven separately against the built
    // production stylesheet, where `.reduce-transparency\:opacity-100` (inside
    // the `@media (prefers-reduced-transparency: reduce)` block) must appear
    // AFTER the plain `.opacity-50` rule, since both are single-class
    // selectors and source order, not specificity, decides which wins.
    const classes = host(createCard({ isActive: false, gridHasActiveCard: true })).classList;
    expect(classes.contains('reduce-transparency:opacity-100')).toBe(true);
  });

});

describe('PhotoCardComponent filter links', () => {
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };
  function create(inputs: Record<string, unknown>): HTMLElement {
    TestBed.configureTestingModule({
      imports: [PhotoCardComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    });
    const fixture = TestBed.createComponent(PhotoCardComponent);
    fixture.componentRef.setInput('photo', makePhoto({ tags_list: ['sunset'] }));
    fixture.componentRef.setInput('config', { features: { show_similar_button: true } });
    for (const [name, value] of Object.entries(inputs)) fixture.componentRef.setInput(name, value);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  const chip = (el: HTMLElement) =>
    Array.from(el.querySelectorAll('span')).find(s => s.textContent?.trim() === 'sunset') as HTMLElement;
  const similar = (el: HTMLElement) => el.querySelector('button[aria-label="similar.find_similar"]');

  afterEach(() => TestBed.resetTestingModule());

  it('keeps tag chips clickable and Find similar available by default', () => {
    const el = create({});
    expect(chip(el).getAttribute('role')).toBe('button');
    expect(chip(el).getAttribute('tabindex')).toBe('0');
    expect(similar(el)).not.toBeNull();
  });

  it('renders tag chips as plain text and drops Find similar when filterLinks is false', () => {
    const el = create({ filterLinks: false });
    const c = chip(el);
    expect(c).toBeTruthy();
    expect(c.hasAttribute('role')).toBe(false);
    expect(c.hasAttribute('tabindex')).toBe(false);
    expect(c.className).not.toContain('cursor-pointer');
    expect(c.className).not.toContain('hover:');
    expect(similar(el)).toBeNull();
  });

  it('closes an open Find similar menu when closeOverlays is called', () => {
    TestBed.configureTestingModule({
      imports: [PhotoCardComponent],
      providers: [
        { provide: I18nService, useValue: mockI18n },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      ],
    });
    const fixture = TestBed.createComponent(PhotoCardComponent);
    fixture.componentRef.setInput('photo', makePhoto({ tags_list: ['sunset'] }));
    fixture.componentRef.setInput('config', { features: { show_similar_button: true } });
    fixture.detectChanges();
    const trigger = fixture.debugElement.query(By.directive(MatMenuTrigger)).injector.get(MatMenuTrigger);
    trigger.openMenu();
    fixture.detectChanges();
    expect(trigger.menuOpen).toBe(true);
    fixture.componentInstance.closeOverlays();
    expect(trigger.menuOpen).toBe(false);
  });

  it('does not emit tagClicked from a plain chip', () => {
    TestBed.configureTestingModule({
      imports: [PhotoCardComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    });
    const fixture = TestBed.createComponent(PhotoCardComponent);
    fixture.componentRef.setInput('photo', makePhoto({ tags_list: ['sunset'] }));
    fixture.componentRef.setInput('filterLinks', false);
    const emitted: string[] = [];
    fixture.componentInstance.tagClicked.subscribe(t => emitted.push(t));
    fixture.detectChanges();
    chip(fixture.nativeElement as HTMLElement).click();
    expect(emitted).toEqual([]);
  });
});

describe('PhotoCardComponent hideTooltips', () => {
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };
  let fixture: ComponentFixture<TestHostComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TestHostComponent],
      providers: [
        { provide: I18nService, useValue: mockI18n },
        // Without this the hide waits for an animationend jsdom never fires.
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(TestHostComponent);
    fixture.detectChanges();
  });

  afterEach(() => fixture.destroy());

  const settle = () => new Promise(resolve => setTimeout(resolve, 30));

  it('takes a showing tooltip off the page and lets Escape through', async () => {
    const tooltip = fixture.debugElement.queryAll(By.directive(MatTooltip))[0].injector.get(MatTooltip);
    tooltip.show(0);
    await settle();
    const container = TestBed.inject(OverlayContainer).getContainerElement();
    expect(tooltip._isTooltipVisible()).toBe(true);
    expect(container.querySelector('.mat-mdc-tooltip')).not.toBeNull();
    const card = fixture.debugElement.children[0].componentInstance as PhotoCardComponent;
    card.hideTooltips();
    await settle();
    expect(container.querySelector('.mat-mdc-tooltip')).toBeNull();
    expect(tooltip._isTooltipVisible()).toBe(false);
    const seen = vi.fn();
    document.addEventListener('keydown', seen);
    try {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true }));
    } finally {
      document.removeEventListener('keydown', seen);
    }
    expect(seen).toHaveBeenCalledOnce();
  });
});

describe('PhotoCardComponent configured hover actions', () => {
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };

  function makeCard(photoOverrides: Partial<Photo> = {}, cardActions: CardActionsConfig | null = null) {
    const f = TestBed.createComponent(PhotoCardComponent);
    f.componentRef.setInput('photo', makePhoto(photoOverrides));
    if (cardActions) f.componentRef.setInput('cardActions', cardActions);
    f.detectChanges();
    return f;
  }

  function topRowIcons(f: ComponentFixture<PhotoCardComponent>): string[] {
    const row = f.nativeElement.querySelector('.absolute.inset-x-0.top-0 > div');
    return [...row.querySelectorAll('button mat-icon')].map(i => i.textContent!.trim());
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PhotoCardComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    }).compileComponents();
  });

  it('shows the duplicate-group button by default only on photos that belong to one', () => {
    expect(topRowIcons(makeCard({ duplicate_group_id: 7 }))).toContain('photo_library');
    expect(topRowIcons(makeCard({ duplicate_group_id: null }))).not.toContain('photo_library');
  });

  it('keeps a null config on the historical default row, gating untouched', () => {
    // unassigned_faces>0 alone must not surface assign_face outside edition mode
    const icons = topRowIcons(makeCard({ unassigned_faces: 2, duplicate_group_id: null }));
    expect(icons).not.toContain('person_add');
    expect(icons).not.toContain('photo_library');
  });

  it('honours hidden and order from the config', () => {
    const cfg: CardActionsConfig = {
      order: ['duplicate_set', 'critique'],
      hidden: ['critique'],
    };
    const icons = topRowIcons(makeCard({ duplicate_group_id: 7 }, cfg));
    expect(icons).toEqual(['photo_library']);
  });

  it('shows burst and sequence buttons only when the photo belongs to such a set', () => {
    const cfg: CardActionsConfig = {
      order: ['burst_set', 'sequence_set'],
      hidden: [],
    };
    expect(topRowIcons(makeCard({ burst_group_id: 3 }, cfg))).toEqual(['burst_mode']);
    expect(topRowIcons(makeCard({ sequence_kind: 'bracket', sequence_group_id: 5 }, cfg)))
      .toEqual(['auto_awesome_motion']);
    expect(topRowIcons(makeCard({ sequence_kind: 'bracket' }, cfg))).toEqual([]);
  });

  it('emits openSetClicked with the photo and kind', () => {
    const cfg: CardActionsConfig = { order: ['duplicate_set'], hidden: [] };
    const f = makeCard({ duplicate_group_id: 7 }, cfg);
    const card = f.debugElement.children[0].componentInstance as PhotoCardComponent;
    const emitted: { photo: Photo; kind: string }[] = [];
    card.openSetClicked.subscribe(e => emitted.push(e));
    (f.nativeElement.querySelector('button mat-icon')!.closest('button') as HTMLButtonElement).click();
    expect(emitted).toEqual([{ photo: makePhoto({ duplicate_group_id: 7 }), kind: 'duplicate' }]);
  });
});

describe('PhotoCardComponent action button dispatch', () => {
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };

  function makeCard(photoOverrides: Partial<Photo>, cardActions: CardActionsConfig, edition = false, features: Record<string, boolean> = {}) {
    const f = TestBed.createComponent(PhotoCardComponent);
    f.componentRef.setInput('photo', makePhoto(photoOverrides));
    f.componentRef.setInput('cardActions', cardActions);
    f.componentRef.setInput('isEditionMode', edition);
    f.componentRef.setInput('config', { features } as never);
    f.detectChanges();
    return f;
  }

  function topRowIcons(f: ComponentFixture<PhotoCardComponent>): string[] {
    const row = f.nativeElement.querySelector('.absolute.inset-x-0.top-0 > div');
    return [...row.querySelectorAll('button mat-icon')].map(i => i.textContent!.trim());
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PhotoCardComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    }).compileComponents();
  });

  it('emits openDetailClicked with the photo from the open_detail button', () => {
    const f = makeCard({}, { order: ['open_detail'], hidden: [] });
    const card = f.debugElement.children[0].componentInstance as PhotoCardComponent;
    const emitted: Photo[] = [];
    card.openDetailClicked.subscribe(p => emitted.push(p));
    (f.nativeElement.querySelector('.absolute.inset-x-0.top-0 > div:first-child button') as HTMLButtonElement).click();
    expect(emitted).toEqual([makePhoto({})]);
  });

  it('shows the embed button only in edition mode with the feature on', () => {
    const cfg: CardActionsConfig = { order: ['embed'], hidden: [] };
    expect(topRowIcons(makeCard({}, cfg, true, { show_embed_metadata: true }))).toEqual(['save']);
    expect(topRowIcons(makeCard({}, cfg, false, { show_embed_metadata: true }))).toEqual([]);
    expect(topRowIcons(makeCard({}, cfg, true, {}))).toEqual([]);
  });

  it('emits embedMetadataClicked and openAddPersonClicked from their buttons', () => {
    const cfg: CardActionsConfig = { order: ['embed', 'assign_face'], hidden: [] };
    const f = makeCard({ unassigned_faces: 2 }, cfg, true, { show_embed_metadata: true });
    const card = f.debugElement.children[0].componentInstance as PhotoCardComponent;
    const embed: Photo[] = [];
    const assign: Photo[] = [];
    card.embedMetadataClicked.subscribe(p => embed.push(p));
    card.openAddPersonClicked.subscribe(p => assign.push(p));
    const buttons = f.nativeElement.querySelectorAll('.absolute.inset-x-0.top-0 > div:first-child button') as NodeListOf<HTMLButtonElement>;
    expect(buttons).toHaveLength(2);
    buttons[0].click();
    expect(embed).toEqual([card.photo()]);
    expect(assign).toEqual([]);
    buttons[1].click();
    expect(embed).toHaveLength(1);
    expect(assign).toEqual([card.photo()]);
  });

  it('shows assign_face in edition mode on a photo with unassigned faces, never outside it', () => {
    const cfg: CardActionsConfig = { order: ['assign_face'], hidden: [] };
    expect(topRowIcons(makeCard({ unassigned_faces: 1 }, cfg, true))).toEqual(['person_add']);
    expect(topRowIcons(makeCard({ unassigned_faces: 1 }, cfg, false))).toEqual([]);
    expect(topRowIcons(makeCard({ unassigned_faces: 0 }, cfg, true))).toEqual([]);
  });

  it('emits critique and the burst and sequence set kinds', () => {
    const cfg: CardActionsConfig = { order: ['critique', 'burst_set', 'sequence_set'], hidden: [] };
    const f = makeCard({ burst_group_id: 3, sequence_kind: 'bracket', sequence_group_id: 5 }, cfg, false, { show_critique: true });
    const card = f.debugElement.children[0].componentInstance as PhotoCardComponent;
    const critique: Photo[] = [];
    const sets: string[] = [];
    card.openCritiqueClicked.subscribe(p => critique.push(p));
    card.openSetClicked.subscribe(e => sets.push(e.kind));
    const buttons = f.nativeElement.querySelectorAll('.absolute.inset-x-0.top-0 > div:first-child button') as NodeListOf<HTMLButtonElement>;
    buttons[0].click();
    expect(critique).toEqual([card.photo()]);
    expect(sets).toEqual([]);
    buttons[1].click();
    buttons[2].click();
    expect(critique).toHaveLength(1);
    expect(sets).toEqual(['burst', 'sequence']);
  });
});
