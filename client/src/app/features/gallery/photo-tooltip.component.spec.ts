import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Component, signal, ChangeDetectionStrategy } from '@angular/core';
import { Router } from '@angular/router';
import { of, Subject } from 'rxjs';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { CategoryLabelPipe } from '../../shared/pipes/category-label.pipe';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import type { Photo, PhotoSet } from '../../shared/models/photo.model';
import { GalleryStore } from './gallery.store';
import { MetricsTabState } from '../../core/services/metrics-tab-state.service';
import { makePhoto, makePhotoFull } from '../../../testing/photo.fixture';
import { OverlayContainer } from '@angular/cdk/overlay';

/* eslint-disable @angular-eslint/component-selector */
@Component({
  selector: 'test-host',
  imports: [PhotoTooltipComponent],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `<app-photo-tooltip [photo]="photo()" [x]="x()" [y]="y()" [flipped]="flipped()"
                                 [pinned]="pinned()" [docked]="docked()" [personLinks]="personLinks()"
                                 [explainable]="explainable()" (explain)="explained = explained + 1" />`,
})
class TestHostComponent {
  photo = signal<Photo | null>(null);
  x = signal(0);
  y = signal(0);
  flipped = signal(false);
  pinned = signal(false);
  docked = signal(false);
  personLinks = signal(true);
  explainable = signal(false);
  explained = 0;
}

describe('PhotoTooltipComponent', () => {
  it('keeps hover tags noninteractive and offers the same literal scope actions when docked', async () => {
    fixture.componentInstance.photo.set(makePhoto({ tags_list: ['coast,ridge'], manual_tags: ['夜景'] }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="tooltip-tag"]')).toBeNull();
    fixture.componentInstance.docked.set(true);
    fixture.detectChanges();
    const tooltip = fixture.debugElement.children[0].componentInstance as PhotoTooltipComponent;
    const emitted: unknown[] = [];
    tooltip.tagSelected.subscribe(event => emitted.push(event));
    const buttons = fixture.nativeElement.querySelectorAll('[data-testid="tooltip-tag"]');
    expect(buttons.length).toBe(2);
    buttons[1].click(); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    const library = [...overlay.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes('photo_detail.tag_search_library'))!;
    library.click();
    expect(emitted).toEqual([{ tag: '夜景', scope: 'library' }]);
    buttons[0].click(); fixture.detectChanges(); await fixture.whenStable();
    expect(overlay.querySelector('[role="menu"]')).not.toBeNull();
    fixture.componentInstance.photo.set(makePhoto({ path: '/new.jpg', tags_list: [] }));
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    expect(overlay.querySelector('[role="menu"]')).toBeNull();
  });
  // The open metric tab is remembered across tests otherwise.
  afterEach(() => localStorage.removeItem('facet_photo_detail_tab'));

  let fixture: ComponentFixture<TestHostComponent>;
  const mockI18n = { t: (key: string) => key, locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };
  const mockStore = {
    config: signal<{ populated_scores?: string[] } | null>(null),
    metricRangesByColumn: signal({}),
  };
  const mockRouter = { events: new Subject(), navigate: vi.fn(() => Promise.resolve(true)) };

  beforeEach(async () => {
    mockStore.config.set(null);
    mockRouter.navigate.mockClear();
    await TestBed.configureTestingModule({
      imports: [TestHostComponent],
      providers: [
        { provide: I18nService, useValue: mockI18n },
        { provide: Router, useValue: mockRouter },
        { provide: GalleryStore, useValue: mockStore },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(TestHostComponent);
  });

  /** The full metric sheet lives in the side panel's tabs now that the floating
   *  bubble keeps four key scores: render docked with one tab open. */
  function renderDocked(photo: Photo, tab: 'quality' | 'composition' | 'technical'): string {
    TestBed.inject(MetricsTabState).tab.set(tab);
    fixture.componentInstance.docked.set(true);
    fixture.componentInstance.photo.set(photo);
    fixture.detectChanges();
    return fixture.nativeElement.textContent as string;
  }

  it('keeps present NULL extended metrics visible in the side panel', () => {
    mockStore.config.set({ populated_scores: ['aesthetic_v25', 'qrealign_score', 'deqa_score'] });
    renderDocked(makePhotoFull({ aesthetic_v25: null, qrealign_score: null, deqa_score: 0 }), 'quality');
    for (const key of ['aesthetic_v25', 'qrealign_score']) {
      expect(fixture.nativeElement.querySelector(`[data-testid="${key}-score"]`).textContent).toContain('tooltip.not_computed');
    }
    expect(fixture.nativeElement.querySelector('[data-testid="deqa_score-score"]').textContent.trim()).toBe('0.0');
  });

  it('hides NULL extended metrics when the library never ran those models, and omitted keys render no rows', () => {
    mockStore.config.set({ populated_scores: [] });
    fixture.componentInstance.photo.set(makePhotoFull({ aesthetic_v25: null, qrealign_score: null, deqa_score: null }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('app-extended-quality [data-testid$="-row"]').length).toBe(0);
    fixture.componentInstance.photo.set(makePhoto());
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('app-extended-quality [data-testid$="-row"]').length).toBe(0);
  });

  it('lets a docked portrait preview take the rail width, capping only very tall photos', () => {
    const photo = makePhotoFull({ image_width: 2000, image_height: 3000 });
    renderDocked(photo, 'quality');
    const preview = fixture.nativeElement.querySelector(`img[alt="${photo.filename}"]`) as HTMLImageElement;
    expect([...preview.classList]).toEqual(expect.arrayContaining(['w-full', 'h-auto', 'object-contain', 'max-h-[75dvh]']));
    expect([...preview.classList]).not.toContain('w-auto');
    expect([...preview.classList]).not.toContain('max-h-[32dvh]');
    fixture.componentInstance.docked.set(false);
    fixture.detectChanges();
    expect([...(fixture.nativeElement.querySelector(`img[alt="${photo.filename}"]`) as HTMLImageElement).classList])
      .toEqual(expect.arrayContaining(['w-auto', 'max-h-[40vh]']));
  });

  it('formats camera-local dates and keeps a single labeled assessment in the docked inspector', () => {
    renderDocked(makePhotoFull({ date_taken: '2026:10:29 10:12:00', aggregate: 0 }), 'quality');
    expect(fixture.nativeElement.querySelector('[data-capture-date]').textContent).toBe('29/10/2026 10:12');
    expect(fixture.nativeElement.querySelectorAll('app-photo-assessment')).toHaveLength(1);
    expect(fixture.nativeElement.querySelector('app-photo-assessment').textContent).toContain('photo_detail.assessment.score');
    expect(fixture.nativeElement.querySelector('app-photo-assessment').textContent).toContain('0.0');
  });

  it('puts the opt-in explain button on the docked assessment and re-emits its click', () => {
    renderDocked(makePhotoFull({ aggregate: 6 }), 'quality');
    expect(fixture.nativeElement.querySelector('[data-explain-score]')).toBeNull();
    fixture.componentInstance.explainable.set(true);
    fixture.detectChanges();
    fixture.nativeElement.querySelector('app-photo-assessment [data-explain-score]').click();
    expect(fixture.componentInstance.explained).toBe(1);
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
    const text = renderDocked(makePhoto({ face_count: 1, face_quality: 8.5, face_ratio: 0.35 }), 'quality');
    expect(text).toContain('35%');
  });

  it('renders face_confidence as percentage (value * 100)', () => {
    const text = renderDocked(makePhoto({ face_count: 1, face_quality: 8.5, face_confidence: 0.92 }), 'quality');
    expect(text).toContain('92%');
  });

  it('renders mean_saturation as percentage (value * 100)', () => {
    const text = renderDocked(makePhoto({ mean_saturation: 0.47 }), 'technical');
    expect(text).toContain('47%');
  });

  it('renders mean_luminance as percentage (value * 100)', () => {
    const text = renderDocked(makePhoto({ mean_luminance: 0.62 }), 'technical');
    expect(text).toContain('62%');
  });

  describe('Extended Quality metrics', () => {
    it('renders aesthetic_iaa when present', () => {
      const text = renderDocked(makePhoto({ aesthetic_iaa: 7.3 }), 'quality');
      expect(text).toContain('7.3');
    });

    it('renders face_quality_iqa when present', () => {
      const text = renderDocked(makePhoto({ face_quality_iqa: 6.8 }), 'quality');
      expect(text).toContain('6.8');
    });

    it('renders liqe_score when present', () => {
      const text = renderDocked(makePhoto({ liqe_score: 8.1 }), 'quality');
      expect(text).toContain('8.1');
    });

    it('does not render aesthetic_iaa row when null', () => {
      const text = renderDocked(makePhoto({ aesthetic_iaa: null }), 'quality');
      expect(text).not.toContain('tooltip.aesthetic_iaa');
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
      fixture.componentInstance.photo.set(makePhoto({ shutter_speed: '0.004' }));
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
      const text = renderDocked(makePhoto({ subject_sharpness: 7.5 }), 'composition');
      expect(text).toContain('photo_detail.saliency');
      expect(text).toContain('7.5');
    });

    it('hides saliency section when all saliency fields are null', () => {
      const text = renderDocked(makePhoto({
        subject_sharpness: null, subject_prominence: null,
        subject_placement: null, bg_separation: null,
      }), 'composition');
      expect(text).not.toContain('photo_detail.saliency');
    });

    it('renders subject_prominence when present', () => {
      const text = renderDocked(makePhoto({ subject_prominence: 5.2 }), 'composition');
      expect(text).toContain('5.2');
    });

    it('renders bg_separation when present', () => {
      const text = renderDocked(makePhoto({ bg_separation: 8.0 }), 'composition');
      expect(text).toContain('8.0');
    });

    it('renders subject_placement when present', () => {
      const text = renderDocked(makePhoto({ subject_placement: 6.7 }), 'composition');
      expect(text).toContain('tooltip.subject_placement');
      expect(text).toContain('6.7');
    });
  });

  describe('Quality section extra metrics', () => {
    it('renders quality_score when present', () => {
      const text = renderDocked(makePhoto({ quality_score: 8.2 }), 'quality');
      expect(text).toContain('tooltip.quality_score');
      expect(text).toContain('8.2');
    });

    it('renders topiq_score when present', () => {
      const text = renderDocked(makePhoto({ topiq_score: 7.6 }), 'quality');
      expect(text).toContain('tooltip.topiq_score');
      expect(text).toContain('7.6');
    });
  });

  describe('Face section sharpness metrics', () => {
    it('renders face_sharpness when a scored face is present', () => {
      const text = renderDocked(makePhoto({ face_count: 1, face_quality: 8.4, face_sharpness: 8.1 }), 'quality');
      expect(text).toContain('tooltip.face_sharpness');
      expect(text).toContain('8.1');
    });

    it('renders eye_sharpness when a scored face is present', () => {
      const text = renderDocked(makePhoto({ face_count: 1, face_quality: 8.4, eye_sharpness: 8.9 }), 'quality');
      expect(text).toContain('tooltip.eye_sharpness');
      expect(text).toContain('8.9');
    });
  });

  describe('Composition section extra metrics', () => {
    it('renders power_point_score when present', () => {
      const text = renderDocked(makePhoto({ power_point_score: 6.1 }), 'composition');
      expect(text).toContain('tooltip.power_points');
      expect(text).toContain('6.1');
    });

    it('renders leading_lines_score when present', () => {
      const text = renderDocked(makePhoto({ leading_lines_score: 5.4 }), 'composition');
      expect(text).toContain('tooltip.leading_lines');
      expect(text).toContain('5.4');
    });
  });

  describe('Technical section extra metrics', () => {
    it('renders contrast_score when present', () => {
      const text = renderDocked(makePhoto({ contrast_score: 6.8 }), 'technical');
      expect(text).toContain('tooltip.contrast');
      expect(text).toContain('6.8');
    });

    it('renders dynamic_range_stops when present', () => {
      const text = renderDocked(makePhoto({ dynamic_range_stops: 9.5 }), 'technical');
      expect(text).toContain('tooltip.dynamic_range');
      expect(text).toContain('9.5');
    });

    it('renders noise_sigma when present', () => {
      const text = renderDocked(makePhoto({ noise_sigma: 2.4 }), 'technical');
      expect(text).toContain('tooltip.noise');
      expect(text).toContain('2.4');
    });

    it('renders histogram_spread when present', () => {
      const text = renderDocked(makePhoto({ histogram_spread: 5.3 }), 'technical');
      expect(text).toContain('tooltip.histogram_spread');
      expect(text).toContain('5.3');
    });
  });

  it('renders every gated metric row from the full fixture in the side panel', () => {
    const rows = {
      quality: ['quality_score', 'topiq_score', 'face_sharpness', 'eye_sharpness'],
      composition: ['power_points', 'leading_lines', 'subject_placement'],
      technical: ['contrast', 'dynamic_range', 'noise', 'histogram_spread'],
    } as const;
    for (const [tab, keys] of Object.entries(rows) as [keyof typeof rows, readonly string[]][]) {
      fixture = TestBed.createComponent(TestHostComponent);
      const text = renderDocked(makePhotoFull(), tab);
      for (const key of keys) expect(text).toContain(`tooltip.${key}`);
    }
  });

  describe('floating key scores', () => {
    it('shows the four key scores and one EXIF line', () => {
      fixture.componentInstance.photo.set(makePhoto({
        aesthetic: 9.9, comp_score: 7.3, tech_sharpness: null, exposure_score: 6.1,
        camera_model: 'Canon EOS R6', focal_length: 24, f_stop: 8, iso: 640,
      }));
      fixture.detectChanges();
      const text = fixture.nativeElement.textContent as string;
      for (const key of ['tooltip.aesthetic', 'tooltip.composition', 'tooltip.exposure']) expect(text).toContain(key);
      expect(fixture.nativeElement.querySelector('[data-floating-key-scores]').textContent).not.toContain('tooltip.tech_sharpness');
      expect(text).toContain('Canon EOS R6');
      expect(text).toContain('ISO 640');
      expect(fixture.nativeElement.querySelector('app-histogram')).toBeNull();
      expect(text).not.toContain('tooltip.contrast');
    });
  });

  describe('Person avatars', () => {
    it('renders docked avatars as filter buttons by default', () => {
      fixture.componentInstance.docked.set(true);
      fixture.componentInstance.photo.set(makePhoto({ persons: [{ id: 1, name: 'Alice' }] }));
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('button img[alt="Alice"]').length).toBe(1);
    });

    it('renders docked avatars as plain images when personLinks is false', () => {
      fixture.componentInstance.docked.set(true);
      fixture.componentInstance.personLinks.set(false);
      fixture.componentInstance.photo.set(makePhoto({ persons: [{ id: 1, name: 'Alice' }] }));
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('button img[alt="Alice"]').length).toBe(0);
      expect(fixture.nativeElement.querySelectorAll('img[alt="Alice"]').length).toBe(1);
    });

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
      expect(fixture.nativeElement.querySelector('img[src*="person"]')?.closest('button')).toBeNull();
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

  describe('pointer-events on the tooltip container', () => {
    function container(): HTMLElement {
      return fixture.nativeElement.querySelector('div[class*="pointer-events-none"]');
    }

    it('stays pointer-events: none in plain hover mode (neither pinned nor docked)', () => {
      fixture.componentInstance.photo.set(makePhoto());
      fixture.detectChanges();
      expect(container().style.pointerEvents).not.toBe('auto');
    });

    it('accepts pointer events when click-pinned, so the person and histogram buttons are reachable', () => {
      fixture.componentInstance.pinned.set(true);
      fixture.componentInstance.photo.set(makePhoto());
      fixture.detectChanges();
      expect(container().style.pointerEvents).toBe('auto');
    });

    it('accepts pointer events when docked', () => {
      fixture.componentInstance.docked.set(true);
      fixture.componentInstance.photo.set(makePhoto());
      fixture.detectChanges();
      expect(container().style.pointerEvents).toBe('auto');
    });
  });

  describe('viewport clamping', () => {
    let observers: { cb: ResizeObserverCallback; target: Element | null; disconnected: boolean }[];
    let size: { width: number; height: number };
    let rectSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      observers = [];
      size = { width: 300, height: 900 };
      vi.stubGlobal('ResizeObserver', class {
        private rec: { cb: ResizeObserverCallback; target: Element | null; disconnected: boolean };
        constructor(cb: ResizeObserverCallback) {
          this.rec = { cb, target: null, disconnected: false };
          observers.push(this.rec);
        }
        observe(t: Element) { this.rec.target = t; }
        unobserve() { /* unused */ }
        disconnect() { this.rec.disconnected = true; }
      });
      rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
        () => ({ width: size.width, height: size.height, top: 0, left: 0, right: size.width, bottom: size.height, x: 0, y: 0, toJSON: () => ({}) }),
      );
      vi.stubGlobal('innerHeight', 1000);
      vi.stubGlobal('innerWidth', 1200);
    });

    afterEach(() => {
      rectSpy.mockRestore();
      vi.unstubAllGlobals();
    });

    const root = () => fixture.nativeElement.querySelector('app-photo-tooltip > div') as HTMLElement;
    const grow = (height: number) => {
      size.height = height;
      for (const o of observers) if (!o.disconnected) o.cb([], {} as ResizeObserver);
      fixture.detectChanges();
    };

    it('keeps the box inside the viewport bottom, including after late growth', () => {
      fixture.componentInstance.photo.set(makePhoto());
      fixture.componentInstance.x.set(100);
      fixture.componentInstance.y.set(900);
      fixture.detectChanges();
      TestBed.tick();
      fixture.detectChanges();
      expect(parseFloat(root().style.top) + size.height).toBeLessThanOrEqual(1000 - 16);
      grow(850);
      expect(parseFloat(root().style.top) + 850).toBeLessThanOrEqual(1000 - 16);
      expect(parseFloat(root().style.top)).toBeGreaterThanOrEqual(16);
    });

    it('never lets the top go above 16px for a box taller than the viewport', () => {
      size.height = 2000;
      fixture.componentInstance.photo.set(makePhoto());
      fixture.componentInstance.y.set(500);
      fixture.detectChanges();
      TestBed.tick();
      fixture.detectChanges();
      expect(root().style.top).toBe('16px');
      expect(root().className).toContain('overflow-y-auto');
    });

    it('clamps the right edge inside the viewport', () => {
      fixture.componentInstance.photo.set(makePhoto());
      fixture.componentInstance.x.set(1150);
      fixture.componentInstance.y.set(100);
      fixture.detectChanges();
      TestBed.tick();
      fixture.detectChanges();
      expect(parseFloat(root().style.left) + size.width).toBeLessThanOrEqual(1200 - 16);
    });

    it('re-clamps on window resize', () => {
      size.height = 500;
      fixture.componentInstance.photo.set(makePhoto());
      fixture.componentInstance.y.set(300);
      fixture.detectChanges();
      TestBed.tick();
      fixture.detectChanges();
      expect(root().style.top).toBe('300px');
      vi.stubGlobal('innerHeight', 600);
      window.dispatchEvent(new Event('resize'));
      fixture.detectChanges();
      expect(parseFloat(root().style.top) + size.height).toBeLessThanOrEqual(600 - 16);
    });

    it('does not observe or clamp when docked, and disconnects when the photo clears', () => {
      fixture.componentInstance.docked.set(true);
      fixture.componentInstance.photo.set(makePhoto());
      fixture.componentInstance.y.set(900);
      fixture.detectChanges();
      TestBed.tick();
      fixture.detectChanges();
      expect(root().style.top).toBe('');
      expect(observers.some(o => o.target === root())).toBe(false);
      fixture.componentInstance.docked.set(false);
      fixture.detectChanges();
      TestBed.tick();
      // Only the box's own observer: the docked metric tabs' header keeps
      // Material's shared, never-disconnected one.
      const box = root();
      expect(observers.some(o => o.target === box && !o.disconnected)).toBe(true);
      fixture.componentInstance.photo.set(null);
      fixture.detectChanges();
      TestBed.tick();
      expect(observers.filter(o => o.target === box).every(o => o.disconnected)).toBe(true);
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
          { provide: GalleryStore, useValue: mockStore },
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

      expect(setFixture.nativeElement.querySelector('[data-testid="tooltip-set"]')).toBeNull();
      expect(mockApi.get).not.toHaveBeenCalledWith('/photo/set', expect.anything());
    });

    it('shows the Set section for a burst frame even though sequence_kind is null', () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/set') {
          return of({ kind: 'burst', group_id: 5, count: 4, ev_span: null, members: [] });
        }
        if (url === '/photo/histogram') {
          return of({ bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null });
        }
        return of(null);
      });
      setFixture.componentInstance.photo.set(
        makePhoto({ path: '/photos/test.jpg', sequence_kind: null, burst_group_id: 1 }),
      );
      setFixture.detectChanges();

      expect(setFixture.nativeElement.querySelector('[data-testid="tooltip-set"]')).not.toBeNull();
      expect(setFixture.nativeElement.textContent).toContain('culling.type_burst');
      vi.advanceTimersByTime(300);
      setFixture.detectChanges();
      expect(mockApi.get).toHaveBeenCalledWith('/photo/set', { path: '/photos/test.jpg' });
    });

    it('shows the Set section for a duplicate frame even though sequence_kind is null', () => {
      mockApi.get.mockImplementation((url: string) => {
        if (url === '/photo/set') {
          return of({ kind: 'duplicate', group_id: 9, count: 2, ev_span: null, members: [] });
        }
        if (url === '/photo/histogram') {
          return of({ bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null });
        }
        return of(null);
      });
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null, duplicate_group_id: 1 }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.querySelector('[data-testid="tooltip-set"]')).not.toBeNull();
      expect(setFixture.nativeElement.textContent).toContain('photo_detail.set.kind_duplicate');
    });

    it('shows the kind and this frame\'s own EV offset immediately, with zero set requests', () => {
      setFixture.componentInstance.photo.set(makePhoto({
        sequence_kind: 'bracket', sequence_ev_offset: 1.5,
      }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.querySelector('[data-testid="tooltip-set"]')).not.toBeNull();
      expect(setFixture.nativeElement.textContent).toContain('culling.bracket.label');
      expect(setFixture.nativeElement.textContent).toContain('+1.5 EV');
      expect(mockApi.get).not.toHaveBeenCalledWith('/photo/set', expect.anything());
    });

    it('fills in the frame count and EV span once the dwell-delayed fetch resolves', () => {
      setFixture.componentInstance.photo.set(makePhoto({
        path: '/photos/test.jpg', sequence_kind: 'bracket', sequence_ev_offset: 0,
      }));
      setFixture.detectChanges();
      expect(setFixture.nativeElement.textContent).not.toContain('capsules.photos_count');

      vi.advanceTimersByTime(300);
      setFixture.detectChanges();

      expect(mockApi.get).toHaveBeenCalledWith('/photo/set', { path: '/photos/test.jpg' });
      expect(setFixture.nativeElement.textContent).toContain('capsules.photos_count');
      expect(setFixture.nativeElement.textContent).toContain('4.0 EV');
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

    it('has no histogram in the floating tooltip, pinned or not', () => {
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();
      expect(setFixture.nativeElement.querySelector('app-histogram')).toBeNull();
      setFixture.componentInstance.pinned.set(true);
      setFixture.detectChanges();
      expect(setFixture.nativeElement.querySelector('app-histogram')).toBeNull();
    });

    it('shows the histogram mode toggle when docked', () => {
      localStorage.setItem('facet_photo_detail_tab', 'histogram');
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();

      expect(setFixture.nativeElement.querySelectorAll('app-histogram button').length).toBeGreaterThan(0);
    });

    it('shows the metric tabs instead of the score sections when docked', () => {
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();
      expect(setFixture.nativeElement.querySelector('app-photo-metrics-tabs')).not.toBeNull();
      setFixture.componentInstance.docked.set(false);
      setFixture.detectChanges();
      expect(setFixture.nativeElement.querySelector('app-photo-metrics-tabs')).toBeNull();
    });

    it('shows the set block for a photo in a set and none otherwise', () => {
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: null }));
      setFixture.detectChanges();
      expect(setFixture.nativeElement.querySelector('[data-testid="tooltip-set"]')).toBeNull();
      setFixture.componentInstance.photo.set(makePhoto({ sequence_kind: 'bracket', sequence_ev_offset: 0 }));
      setFixture.detectChanges();
      expect(setFixture.nativeElement.querySelector('[data-testid="tooltip-set"]')).not.toBeNull();
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

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/photo'], { queryParams: { path: '/photos/a.jpg' }, state: { photoOrigin: 'in-app' } });
    });

    it('rings the current frame among its siblings', () => {
      mockSetWithMembers();
      setFixture.componentInstance.docked.set(true);
      setFixture.componentInstance.photo.set(
        makePhoto({ path: '/photos/test.jpg', sequence_kind: 'bracket', sequence_ev_offset: 0 }),
      );
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
      return setFixture.nativeElement.querySelector('img[src*="person"]')?.closest('button') ?? null;
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
