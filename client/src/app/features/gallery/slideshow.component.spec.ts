import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { SlideshowComponent } from './slideshow.component';
import { GalleryStore } from './gallery.store';
import { I18nService } from '../../core/services/i18n.service';
import type { Photo } from '../../shared/models/photo.model';
import { makePhoto } from '../../../testing/photo.fixture';

/** Landscape photo (width > height) -- always its own single-photo slide. */
const landscape = (path: string): Photo => makePhoto({ path, filename: path, image_width: 1920, image_height: 1080 });
/** Portrait photo (height > width) -- eligible for multi-photo slide grouping. */
const portrait = (path: string): Photo => makePhoto({ path, filename: path, image_width: 1080, image_height: 1920 });

describe('SlideshowComponent', () => {
  let fixture: ComponentFixture<SlideshowComponent>;
  let component: SlideshowComponent;
  let mockStore: { slideshowActive: ReturnType<typeof signal<boolean>>; nextPage: Mock };
  const mockI18n = {
    t: (key: string) => key,
    currentLang: vi.fn(() => 'en'),
    locale: vi.fn(() => 'en'),
    translations: vi.fn(() => ({})),
  };

  /** jsdom never fetches an <img>, so onload would never fire on its own --
   *  resolve every preload synchronously, matching the house pattern in
   *  histogram.component.spec.ts. */
  class MockImage {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    private _src = '';
    get src(): string { return this._src; }
    set src(value: string) {
      this._src = value;
      this.onload?.();
    }
  }

  /** Give the preload Promise.all().then() chain enough microtask hops to run. */
  async function flushMicrotasks(times = 10): Promise<void> {
    for (let i = 0; i < times; i++) {
      await Promise.resolve();
    }
  }

  /** Flushes the two nested requestAnimationFrame calls crossfadeTo() makes
   *  (stubbed below as 0ms timers) that flip the front layer and seed the
   *  standby slide, plus the default 300ms crossfade transition itself. */
  async function advanceCrossfadeFrame(): Promise<void> {
    await vi.advanceTimersByTimeAsync(300);
    await flushMicrotasks();
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('Image', MockImage);
    // requestAnimationFrame as a 0ms timer keeps it composable with the fake
    // clock instead of racing real animation frames.
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) =>
      setTimeout(() => cb(performance.now()), 0) as unknown as number);
    vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));

    // Deterministic maxPortraitsPerSlide: ar=1600/900=1.778, /(2/3)=2.667,
    // round=3, clamped to [1,3] => 3. Set before construction so the
    // viewportWidth/Height signal field initializers pick it up.
    Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
    Object.defineProperty(window, 'innerHeight', { value: 900, configurable: true, writable: true });

    mockStore = {
      slideshowActive: signal(true),
      nextPage: vi.fn(() => Promise.resolve()),
    };

    TestBed.configureTestingModule({
      imports: [SlideshowComponent],
      providers: [
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: mockI18n },
      ],
    });

    fixture = TestBed.createComponent(SlideshowComponent);
    component = fixture.componentInstance;
  });

  afterEach(() => {
    component.ngOnDestroy();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  /** Mount with the given photos and let afterNextRender + constructor
   *  effects run (initial slide seeding, listeners, auto-advance timer). */
  function mount(photos: Photo[] = []): void {
    if (photos.length > 0) {
      fixture.componentRef.setInput('photos', photos);
    }
    fixture.detectChanges();
    TestBed.tick();
  }

  describe('initial state', () => {
    it('starts at slide index 0', () => {
      mount();
      expect(component.currentSlideIndex()).toBe(0);
    });

    it('starts playing', () => {
      mount();
      expect(component.isPlaying()).toBe(true);
    });

    it('starts with duration 4s', () => {
      mount();
      expect(component.duration()).toBe(4);
    });

    it('starts with progress 0', () => {
      mount();
      expect(component.progress()).toBe(0);
    });

    it('starts with controls visible', () => {
      mount();
      expect(component.controlsVisible()).toBe(true);
    });

    it('starts not in fullscreen', () => {
      mount();
      expect(component.isFullscreen()).toBe(false);
    });
  });

  describe('currentSlide()', () => {
    it('returns null when no photos', () => {
      mount();
      expect(component.currentSlide()).toBeNull();
    });
  });

  describe('slides()', () => {
    it('returns empty array when no photos', () => {
      mount();
      expect(component.slides()).toEqual([]);
    });

    it('gives every landscape photo its own single-photo slide', () => {
      mount([landscape('/a.jpg'), landscape('/b.jpg'), landscape('/c.jpg')]);
      const slides = component.slides();
      expect(slides).toHaveLength(3);
      expect(slides.map(s => s.photos.map(p => p.path))).toEqual([['/a.jpg'], ['/b.jpg'], ['/c.jpg']]);
    });

    it('packs exactly maxPortraitsPerSlide (3) portraits into a single slide', () => {
      mount([portrait('/p1.jpg'), portrait('/p2.jpg'), portrait('/p3.jpg')]);
      const slides = component.slides();
      expect(slides).toHaveLength(1);
      expect(slides[0].photos.map(p => p.path)).toEqual(['/p1.jpg', '/p2.jpg', '/p3.jpg']);
    });

    it('splits a trailing single leftover portrait into its own slide, not merged', () => {
      mount([portrait('/p1.jpg'), portrait('/p2.jpg'), portrait('/p3.jpg'), portrait('/p4.jpg')]);
      const slides = component.slides();
      expect(slides).toHaveLength(2);
      expect(slides[0].photos.map(p => p.path)).toEqual(['/p1.jpg', '/p2.jpg', '/p3.jpg']);
      expect(slides[1].photos.map(p => p.path)).toEqual(['/p4.jpg']);
    });

    it('merges a trailing leftover group of 2+ portraits into one slide', () => {
      mount([
        portrait('/p1.jpg'), portrait('/p2.jpg'), portrait('/p3.jpg'),
        portrait('/p4.jpg'), portrait('/p5.jpg'),
      ]);
      const slides = component.slides();
      expect(slides).toHaveLength(2);
      expect(slides[0].photos.map(p => p.path)).toEqual(['/p1.jpg', '/p2.jpg', '/p3.jpg']);
      expect(slides[1].photos.map(p => p.path)).toEqual(['/p4.jpg', '/p5.jpg']);
    });

    it('keeps a completed portrait group in order between two single landscape slides', () => {
      mount([
        landscape('/l1.jpg'),
        portrait('/p1.jpg'), portrait('/p2.jpg'), portrait('/p3.jpg'),
        landscape('/l2.jpg'),
      ]);
      const slides = component.slides();
      expect(slides.map(s => s.photos.map(p => p.path))).toEqual([
        ['/l1.jpg'],
        ['/p1.jpg', '/p2.jpg', '/p3.jpg'],
        ['/l2.jpg'],
      ]);
    });

    it('flushes an incomplete buffered portrait group before an interleaved landscape, preserving input order', () => {
      mount([
        portrait('/p1.jpg'),
        landscape('/l1.jpg'),
        portrait('/p2.jpg'), portrait('/p3.jpg'),
      ]);
      const slides = component.slides();
      expect(slides.map(s => s.photos.map(p => p.path))).toEqual([
        ['/p1.jpg'],
        ['/l1.jpg'],
        ['/p2.jpg', '/p3.jpg'],
      ]);
    });
  });

  describe('photoCounter()', () => {
    it('returns correct range with no slides', () => {
      mount();
      const counter = component.photoCounter();
      expect(counter).toEqual({ start: 1, end: 0, total: 0 });
    });

    it('tracks true input order across an advance, not slide-grouping order', async () => {
      // slides(): [{p1}, {l1}, {p2, p3}] -- see the slides() ordering test above.
      mount([
        portrait('/p1.jpg'),
        landscape('/l1.jpg'),
        portrait('/p2.jpg'), portrait('/p3.jpg'),
      ]);
      expect(component.photoCounter()).toEqual({ start: 1, end: 1, total: 4 });

      component.next();
      await flushMicrotasks();
      expect(component.currentSlideIndex()).toBe(1);
      expect(component.photoCounter()).toEqual({ start: 2, end: 2, total: 4 });

      component.next();
      await flushMicrotasks();
      expect(component.currentSlideIndex()).toBe(2);
      expect(component.photoCounter()).toEqual({ start: 3, end: 4, total: 4 });
    });
  });

  describe('slideDuration()', () => {
    it('falls back to a single-photo count when there is no current slide', () => {
      mount();
      expect(component.slideDuration()).toBe(4);
    });

    it('multiplies the base duration by the photo count of a multi-photo slide', () => {
      mount([portrait('/p1.jpg'), portrait('/p2.jpg'), portrait('/p3.jpg')]);
      expect(component.currentSlide()?.photos.length).toBe(3);
      expect(component.duration()).toBe(4);
      expect(component.slideDuration()).toBe(12);
    });
  });

  describe('crossfade layers', () => {
    it('starts with layer A as front', () => {
      mount();
      expect(component.frontLayer()).toBe('a');
    });

    it('starts with layer A opacity 1, layer B opacity 0', () => {
      mount();
      expect(component.layerAOpacity()).toBe(1);
      expect(component.layerBOpacity()).toBe(0);
    });

    it('layer A and B slides stay null when there are no photos to seed with', () => {
      mount();
      expect(component.layerASlide()).toBeNull();
      expect(component.layerBSlide()).toBeNull();
    });

    it('seeds layer A once photos arrive after the initial (empty) render', () => {
      mount(); // renders with no photos; afterNextRender finds nothing to seed
      expect(component.layerASlide()).toBeNull();

      fixture.componentRef.setInput('photos', [landscape('/a.jpg'), landscape('/b.jpg')]);
      fixture.detectChanges();
      TestBed.tick();

      expect(component.layerASlide()).not.toBeNull();
      expect(component.layerASlide()?.photos.map(p => p.path)).toEqual(['/a.jpg']);
      expect(component.currentSlideIndex()).toBe(0);
      expect(component.frontLayer()).toBe('a');
    });

    it('seeds layer B and swaps the front layer across an advance', async () => {
      mount([landscape('/a.jpg'), landscape('/b.jpg'), landscape('/c.jpg')]);
      const slides = component.slides();
      expect(component.layerASlide()?.photos[0].path).toBe('/a.jpg');
      expect(component.layerBSlide()).toBeNull();
      expect(component.frontLayer()).toBe('a');

      component['onKeyDown'](new KeyboardEvent('keydown', { key: 'ArrowRight' }));
      await flushMicrotasks();
      await advanceCrossfadeFrame();

      expect(component.frontLayer()).toBe('b');
      expect(component.layerBSlide()).toBe(slides[1]);
      expect(component.layerBSlide()?.photos[0].path).toBe('/b.jpg');
      // The old layer keeps its slide data (just faded out), never cleared.
      expect(component.layerASlide()?.photos[0].path).toBe('/a.jpg');
    });
  });

  describe('togglePlay()', () => {
    it('pauses when playing', () => {
      mount();
      expect(component.isPlaying()).toBe(true);
      component.togglePlay();
      expect(component.isPlaying()).toBe(false);
    });

    it('resumes when paused', () => {
      mount();
      component.togglePlay(); // pause
      component.togglePlay(); // resume
      expect(component.isPlaying()).toBe(true);
    });
  });

  describe('close()', () => {
    it('sets slideshowActive to false on the store', () => {
      mount();
      component.close();
      expect(mockStore.slideshowActive()).toBe(false);
    });
  });

  describe('onDurationChange()', () => {
    it('updates duration signal', () => {
      mount();
      component.onDurationChange(8);
      expect(component.duration()).toBe(8);
    });

    it('resets progress to 0', () => {
      mount();
      component['progress'].set(50);
      component.onDurationChange(6);
      expect(component.progress()).toBe(0);
    });
  });

  describe('timer progress', () => {
    it('progress advances each 100ms tick', () => {
      mount();
      component['clearTimerInterval']();
      component.progress.set(0);
      component['startInterval']();
      vi.advanceTimersByTime(100); // one tick with default 4s slideDuration: +2.5%
      expect(component.progress()).toBeCloseTo(2.5, 1);
    });

    it('resets progress and stays at index 0 after full duration (no photos)', () => {
      mount();
      component['clearTimerInterval']();
      component.progress.set(0);
      component.duration.set(1);
      component['startInterval']();
      vi.advanceTimersByTime(1000); // 10 ticks of 100ms
      expect(component.currentSlideIndex()).toBe(0); // no photos → stays at 0
      expect(component.progress()).toBe(0);
    });

    it('auto-advances the slide index once the progress bar completes', async () => {
      mount([landscape('/a.jpg'), landscape('/b.jpg')]);
      expect(component.currentSlideIndex()).toBe(0);

      component['clearTimerInterval']();
      component.progress.set(0);
      component.duration.set(1); // 1s slideDuration for a single-photo slide
      component['startInterval']();

      await vi.advanceTimersByTimeAsync(1000); // 10 ticks of 100ms -> reaches 100%
      await flushMicrotasks();

      expect(component.currentSlideIndex()).toBe(1);
    });
  });

  describe('next() and prev()', () => {
    it('next() resets progress', () => {
      mount();
      component['progress'].set(50);
      component.next();
      expect(component.progress()).toBe(0);
    });

    it('prev() resets progress', () => {
      mount();
      component['progress'].set(50);
      component.prev();
      expect(component.progress()).toBe(0);
    });

    it('prev() stays at 0 when there are no slides to wrap to', () => {
      mount();
      component.prev();
      expect(component.currentSlideIndex()).toBe(0);
    });

    it('prev() wraps from slide 0 to the last slide index', async () => {
      mount([landscape('/a.jpg'), landscape('/b.jpg'), landscape('/c.jpg')]);
      expect(component.currentSlideIndex()).toBe(0);

      component.prev();
      await flushMicrotasks();

      expect(component.currentSlideIndex()).toBe(2);
    });
  });

  describe('controls visibility', () => {
    it('showControls() makes controls visible', () => {
      mount();
      component.controlsVisible.set(false);
      component.showControls();
      expect(component.controlsVisible()).toBe(true);
    });

    it('controls auto-hide after 2 seconds', () => {
      mount();
      component.showControls();
      expect(component.controlsVisible()).toBe(true);
      vi.advanceTimersByTime(2000);
      expect(component.controlsVisible()).toBe(false);
    });

    it('showControls() resets the hide timer', () => {
      mount();
      component.showControls();
      vi.advanceTimersByTime(1500); // 1.5s, not yet hidden
      expect(component.controlsVisible()).toBe(true);
      component.showControls(); // reset timer
      vi.advanceTimersByTime(1500); // 1.5s from reset, still visible
      expect(component.controlsVisible()).toBe(true);
      vi.advanceTimersByTime(500); // 2s from reset, now hidden
      expect(component.controlsVisible()).toBe(false);
    });
  });

  describe('fullscreen', () => {
    it('toggleFullscreen() calls requestFullscreen when not fullscreen', () => {
      mount();
      const mockEl = { requestFullscreen: vi.fn().mockResolvedValue(undefined) };
      Object.defineProperty(component, 'container', { value: () => ({ nativeElement: mockEl }), writable: true, configurable: true });
      Object.defineProperty(document, 'fullscreenElement', { value: null, writable: true, configurable: true });
      component.toggleFullscreen();
      expect(mockEl.requestFullscreen).toHaveBeenCalled();
    });

    it('toggleFullscreen() calls exitFullscreen when in fullscreen', () => {
      mount();
      document.exitFullscreen = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(document, 'fullscreenElement', { value: document.body, writable: true, configurable: true });
      component.toggleFullscreen();
      expect(document.exitFullscreen).toHaveBeenCalled();
      Object.defineProperty(document, 'fullscreenElement', { value: null, writable: true, configurable: true });
    });
  });

  describe('keyboard handler', () => {
    it('Space key toggles play/pause', () => {
      mount();
      const handler = component['onKeyDown'].bind(component);
      expect(component.isPlaying()).toBe(true);
      handler(new KeyboardEvent('keydown', { key: ' ' }));
      expect(component.isPlaying()).toBe(false);
    });

    it('Escape key closes the slideshow', () => {
      mount();
      const handler = component['onKeyDown'].bind(component);
      handler(new KeyboardEvent('keydown', { key: 'Escape' }));
      expect(mockStore.slideshowActive()).toBe(false);
    });

    it('ArrowRight advances forward through slides, wrapping from the last slide to the first', async () => {
      mount([landscape('/a.jpg'), landscape('/b.jpg'), landscape('/c.jpg')]);
      const handler = component['onKeyDown'].bind(component);
      expect(component.currentSlideIndex()).toBe(0);

      handler(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
      await flushMicrotasks();
      expect(component.currentSlideIndex()).toBe(1);

      handler(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
      await flushMicrotasks();
      expect(component.currentSlideIndex()).toBe(2);

      handler(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
      await flushMicrotasks();
      expect(component.currentSlideIndex()).toBe(0); // wraps
    });

    it('ArrowLeft goes backward through slides, wrapping from the first slide to the last', async () => {
      mount([landscape('/a.jpg'), landscape('/b.jpg'), landscape('/c.jpg')]);
      const handler = component['onKeyDown'].bind(component);
      expect(component.currentSlideIndex()).toBe(0);

      handler(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
      await flushMicrotasks();
      expect(component.currentSlideIndex()).toBe(2); // wraps

      handler(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
      await flushMicrotasks();
      expect(component.currentSlideIndex()).toBe(1);

      handler(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
      await flushMicrotasks();
      expect(component.currentSlideIndex()).toBe(0);
    });

    it('F key toggles fullscreen', () => {
      mount();
      const handler = component['onKeyDown'].bind(component);
      const toggleSpy = vi.spyOn(component, 'toggleFullscreen').mockImplementation(() => {});
      handler(new KeyboardEvent('keydown', { key: 'f' }));
      expect(toggleSpy).toHaveBeenCalledTimes(1);
      handler(new KeyboardEvent('keydown', { key: 'F' }));
      expect(toggleSpy).toHaveBeenCalledTimes(2);
      toggleSpy.mockRestore();
    });
  });

  describe('ngOnDestroy()', () => {
    it('clears the interval', () => {
      mount();
      component['startInterval']();
      const clearSpy = vi.spyOn(window, 'clearInterval');
      component.ngOnDestroy();
      expect(clearSpy).toHaveBeenCalled();
    });

    it('clears the hide controls timer', () => {
      mount();
      const clearSpy = vi.spyOn(window, 'clearTimeout');
      component.showControls(); // starts hide timer
      component.ngOnDestroy();
      expect(clearSpy).toHaveBeenCalled();
    });

    it('removes fullscreenchange listener', () => {
      mount();
      const removeSpy = vi.spyOn(document, 'removeEventListener');
      component.ngOnDestroy();
      expect(removeSpy).toHaveBeenCalledWith('fullscreenchange', component['boundFullscreenHandler']);
    });
  });

  describe('focus management', () => {
    /** The shared `component`/`fixture` from the outer beforeEach are already
     *  constructed by the time a test body runs, which is too late to control
     *  document.activeElement before the field initializer captures it. Each
     *  test here creates its own instance instead, under the same TestBed
     *  configuration (fake timers, mocked Image/rAF already stubbed above). */
    function mountFresh(trigger: HTMLElement): ComponentFixture<SlideshowComponent> {
      // Focus must happen before createComponent(): the previously-focused
      // element is captured by a field initializer, which runs synchronously
      // during component construction.
      trigger.focus();
      const freshFixture = TestBed.createComponent(SlideshowComponent);
      freshFixture.componentRef.setInput('photos', [landscape('/a.jpg')]);
      freshFixture.detectChanges();
      TestBed.tick();
      return freshFixture;
    }

    let trigger: HTMLButtonElement;

    beforeEach(() => {
      trigger = document.createElement('button');
      document.body.appendChild(trigger);
    });

    afterEach(() => {
      trigger.remove();
    });

    it('moves focus into the dialog container on open', () => {
      const freshFixture = mountFresh(trigger);
      const container = freshFixture.nativeElement.querySelector('[role="dialog"]');

      expect(document.activeElement).toBe(container);

      freshFixture.componentInstance.ngOnDestroy();
    });

    it('restores focus to the previously focused element on close', () => {
      const freshFixture = mountFresh(trigger);
      expect(document.activeElement).not.toBe(trigger);

      freshFixture.componentInstance.ngOnDestroy();

      expect(document.activeElement).toBe(trigger);
    });
  });
});
