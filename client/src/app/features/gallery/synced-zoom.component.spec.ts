import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SyncedZoomComponent, ZoomState, DisplayedRendition, FIT_ZOOM, LoadedSources, SHARP_PRELOAD_DEBOUNCE_MS } from './synced-zoom.component';
import { signal } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';

describe('SyncedZoomComponent', () => {
  beforeEach(() => TestBed.configureTestingModule({ providers: [
    { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
  ] }));
  function make(zoom: ZoomState = FIT_ZOOM): ComponentFixture<SyncedZoomComponent> {
    const fixture = TestBed.createComponent(SyncedZoomComponent);
    fixture.componentRef.setInput('src', '/thumb.jpg');
    fixture.componentRef.setInput('fullResSrc', '/full.jpg');
    fixture.componentRef.setInput('zoom', zoom);
    fixture.detectChanges();
    return fixture;
  }

  function emitted(fixture: ComponentFixture<SyncedZoomComponent>, fn: () => void): ZoomState {
    let captured: ZoomState | undefined;
    fixture.componentInstance.zoomChange.subscribe(z => (captured = z));
    fn();
    return captured!;
  }

  function api(fixture: ComponentFixture<SyncedZoomComponent>) {
    return fixture.componentInstance as unknown as {
      transform(): string;
      effectiveSrc(): string;
      onWheel(e: Partial<WheelEvent>): void;
      onDoubleClick(): void;
      onPointerDown(e: Partial<PointerEvent>): void;
      onPointerMove(e: Partial<PointerEvent>): void;
    };
  }

  // The browser-less test env reports a zero-size host and an unloaded image, so
  // the focus math is untestable until both are stubbed — and that zero size is
  // exactly what the production fallback guards against.
  const PANE = { width: 800, height: 600 };
  const NATURAL = { width: 4000, height: 3000 };

  function measure(
    fixture: ComponentFixture<SyncedZoomComponent>,
    natural: { width: number; height: number } = NATURAL,
  ): void {
    const host: HTMLElement = fixture.nativeElement;
    host.getBoundingClientRect = () => ({ ...PANE, x: 0, y: 0, top: 0, left: 0,
      right: PANE.width, bottom: PANE.height, toJSON: () => ({}) }) as DOMRect;
    const img = host.querySelector('img')!;
    Object.defineProperty(img, 'naturalWidth', { value: natural.width, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: natural.height, configurable: true });
  }

  /** Re-feed an emitted transform as the shared zoom input, the way the parent does. */
  function apply(fixture: ComponentFixture<SyncedZoomComponent>, zoom: ZoomState): void {
    fixture.componentRef.setInput('zoom', zoom);
    fixture.detectChanges();
  }

  it('constructs and retries on HTTP LAN without randomUUID', () => {
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) });
    try {
      const fixture = make();
      fixture.componentInstance.retry(); fixture.detectChanges();
      expect(new URL(api(fixture).effectiveSrc()).searchParams.get('facet_retry')).toMatch(/^[0-9a-f-]{36}-1$/);
    } finally { vi.unstubAllGlobals(); }
  });

  it('shows the visible image region while zooming and panning, and hides it at Fit', () => {
    const f = make(); measure(f); f.componentInstance.measurePane(); f.detectChanges();
    const root = f.nativeElement as HTMLElement;
    const region = () => root.querySelector<HTMLElement>('[data-zoom-viewport]');
    expect(root.querySelector('[data-zoom-overview]')).toBeNull();
    apply(f, { scale: 2, tx: 0, ty: 0 });
    expect(region()!.style.left).toBe('25%'); expect(region()!.style.top).toBe('25%');
    expect(region()!.style.width).toBe('50%'); expect(region()!.style.height).toBe('50%');
    apply(f, { scale: 2, tx: 200, ty: -150 });
    expect(region()!.style.left).toBe('12.5%'); expect(region()!.style.top).toBe('37.5%');
    apply(f, FIT_ZOOM);
    expect(root.querySelector('[data-zoom-overview]')).toBeNull();
  });

  it.each([
    [{ width: 4000, height: 2000 }, ['25%', '12.5%', '50%', '75%']],
    [{ width: 2000, height: 4000 }, ['0%', '25%', '100%', '50%']],
  ])('accounts for contained-image letterboxing in its overview (%o)', (natural, expected) => {
    const f = make({ scale: 2, tx: 0, ty: 0 }); measure(f, natural);
    f.componentInstance.measurePane(); f.detectChanges();
    const region = (f.nativeElement as HTMLElement).querySelector<HTMLElement>('[data-zoom-viewport]')!;
    expect([region.style.left, region.style.top, region.style.width, region.style.height]).toEqual(expected);
    apply(f, { scale: 2, tx: 2000, ty: 0 });
    expect(region.style.width).toBe('0%');
  });

  it('builds a translate+scale transform from the shared zoom', () => {
    const f = make({ scale: 2, tx: 10, ty: -5 });
    expect(api(f).transform()).toBe('translate(10px, -5px) scale(2)');
  });

  it('frames a valid normalized crop within scale bounds and refuses mismatched source geometry', () => {
    const f = make(); measure(f); f.componentInstance.measurePane();
    const box = [0.5, 0.25, 0.75, 0.5];
    const frame = f.componentInstance.zoomForRegion(box, 4 / 3)!;
    expect(frame.scale).toBeCloseTo(8 / 3);
    expect(frame.tx + frame.scale * 100).toBeCloseTo(0);
    expect(frame.ty - frame.scale * 75).toBeCloseTo(0);
    expect(f.componentInstance.zoomForRegion(box, 1)).toBeNull();
    expect(f.componentInstance.zoomForRegion([0.8, 0.2, 0.1, 0.5])).toBeNull();
    expect(f.componentInstance.zoomForRegion([0, 0, Number.NaN, 1])).toBeNull();
    expect(f.componentInstance.zoomForRegion([0.1, 0.1, 0.11, 0.11])?.scale).toBe(8);
  });

  it('opts into keyboard pan/zoom and delegates Fit without stealing other surfaces’ shortcuts', () => {
    const f = make({ scale: 2, tx: 0, ty: 0 });
    const host = f.nativeElement as HTMLElement;
    const zooms: ZoomState[] = []; let fits = 0;
    f.componentInstance.zoomChange.subscribe(z => zooms.push(z));
    f.componentInstance.fitRequested.subscribe(() => fits++);
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(zooms).toEqual([]);
    f.componentRef.setInput('keyboardInspection', true); f.detectChanges();
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', shiftKey: true, bubbles: true }));
    expect(zooms.at(-1)).toEqual({ scale: 2, tx: -64, ty: 0 });
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    expect(fits).toBe(1);
    expect(host.tabIndex).toBe(0);
    expect(host.classList.contains('touch-none')).toBe(true);
  });

  it('centres a panned image when keyboard or wheel zoom returns to fit', () => {
    const f = make({ scale: 1.1, tx: 80, ty: -40 });
    f.componentRef.setInput('keyboardInspection', true); f.detectChanges();
    const zooms: ZoomState[] = [];
    f.componentInstance.zoomChange.subscribe(z => zooms.push(z));
    const host = f.nativeElement as HTMLElement;
    host.dispatchEvent(new KeyboardEvent('keydown', { key: '-', bubbles: true, cancelable: true }));
    expect(zooms.at(-1)).toEqual(FIT_ZOOM);
    host.dispatchEvent(new WheelEvent('wheel', { deltaY: 1, bubbles: true, cancelable: true }));
    expect(zooms.at(-1)).toEqual(FIT_ZOOM);
  });

  it('bounds comparison framing to fitted image pixels without changing culling framing', () => {
    const f = make(); measure(f); f.componentInstance.measurePane();
    const state = { scale: 1.5, tx: -1464, ty: 1000 };
    expect(f.componentInstance.boundInspectionZoom(state)).toEqual(state);
    f.componentRef.setInput('keyboardInspection', true); f.detectChanges();
    expect(f.componentInstance.boundInspectionZoom(state)).toEqual({ scale: 1.5, tx: -200, ty: 150 });
    measure(f, { width: 3000, height: 4000 }); f.componentInstance.measurePane();
    expect(f.componentInstance.boundInspectionZoom(state)).toEqual({ scale: 1.5, tx: 0, ty: 150 });
    expect(f.componentInstance.boundInspectionZoom({ ...state, scale: 1 })).toEqual(FIT_ZOOM);
  });

  it('ends a captured drag at Fit, lost capture, and frame replacement', () => {
    const f = make({ scale: 2, tx: 0, ty: 0 });
    const host = f.nativeElement as HTMLElement;
    const updates: ZoomState[] = []; f.componentInstance.zoomChange.subscribe(state => updates.push(state));
    const start = () => host.dispatchEvent(new PointerEvent('pointerdown', { button: 0, pointerId: 1, clientX: 0, clientY: 0 }));
    const move = () => host.dispatchEvent(new PointerEvent('pointermove', { pointerId: 1, clientX: 20, clientY: 10 }));
    start(); move(); expect(updates).toHaveLength(1);
    apply(f, FIT_ZOOM); move(); expect(updates).toHaveLength(1);
    apply(f, { scale: 2, tx: 0, ty: 0 }); start();
    host.dispatchEvent(new Event('lostpointercapture')); move(); expect(updates).toHaveLength(1);
    start(); f.componentRef.setInput('frameKey', 'next'); f.detectChanges(); move(); expect(updates).toHaveLength(1);
  });

  it('uses the thumbnail at fit scale and the full-res past it', () => {
    expect(api(make(FIT_ZOOM)).effectiveSrc()).toBe('/thumb.jpg');
    expect(api(make({ scale: 1.5, tx: 0, ty: 0 })).effectiveSrc()).toBe('/full.jpg');
  });

  it('tracks displayed source settlement and ignores a stale preview load while zoomed', () => {
    const fixture = make();
    const states: DisplayedRendition[] = [];
    fixture.componentInstance.renditionChange.subscribe(state => states.push(state));
    const img = (fixture.nativeElement as HTMLElement).querySelector('img')!;
    let current = new URL('/thumb.jpg', document.baseURI).href;
    Object.defineProperties(img, {
      complete: { configurable: true, value: true },
      currentSrc: { configurable: true, get: () => current },
      naturalWidth: { configurable: true, value: 4000 },
      naturalHeight: { configurable: true, value: 3000 },
    });
    apply(fixture, { scale: 2, tx: 10, ty: 20 });
    expect(states.at(-1)).toEqual({ kind: 'source', phase: 'loading' });
    img.dispatchEvent(new Event('load'));
    expect(states.at(-1)?.phase).toBe('loading');
    current = new URL('/full.jpg', document.baseURI).href;
    img.dispatchEvent(new Event('load'));
    expect(states.at(-1)).toEqual({ kind: 'source', phase: 'ready', width: 4000, height: 3000 });
    img.dispatchEvent(new Event('error'));
    expect(states.at(-1)).toEqual({ kind: 'source', phase: 'failed' });
    fixture.componentInstance.retry(); fixture.detectChanges();
    expect(new URL(api(fixture).effectiveSrc()).searchParams.get('facet_retry')).toMatch(/-1$/);
    expect(fixture.componentInstance.zoom()).toEqual({ scale: 2, tx: 10, ty: 20 });
    expect(states.at(-1)).toEqual({ kind: 'source', phase: 'loading' });
    img.dispatchEvent(new Event('load'));
    expect(states.at(-1)?.phase).toBe('loading');
  });

  it('scopes retry cache bypass to the captured frame and preview source', () => {
    const fixture = make();
    fixture.componentRef.setInput('frameKey', 'a');
    fixture.detectChanges();
    fixture.componentInstance.retry();
    fixture.detectChanges();
    const retried = api(fixture).effectiveSrc();
    expect(new URL(retried).searchParams.has('ngsw-bypass')).toBe(true);

    fixture.componentRef.setInput('frameKey', 'b');
    fixture.detectChanges();
    expect(api(fixture).effectiveSrc()).toBe('/thumb.jpg');
    fixture.componentRef.setInput('frameKey', 'a');
    fixture.detectChanges();
    expect(api(fixture).effectiveSrc()).toBe(retried);
    fixture.componentRef.setInput('src', '/new-preview.jpg');
    fixture.detectChanges();
    expect(api(fixture).effectiveSrc()).toBe('/new-preview.jpg');
    fixture.componentInstance.retry();
    fixture.detectChanges();
    expect(new URL(api(fixture).effectiveSrc()).searchParams.get('facet_retry')).toMatch(/-2$/);
  });

  it('zooms in on wheel up and clamps to the max', () => {
    const f = make({ scale: 7.5, tx: 0, ty: 0 });
    const z = emitted(f, () => api(f).onWheel({ deltaY: -1, preventDefault: () => {} }));
    expect(z.scale).toBe(SyncedZoomComponent.MAX_SCALE);
  });

  it('snaps back to fit when wheeling out to scale 1', () => {
    const f = make({ scale: 1.1, tx: 40, ty: 40 });
    const z = emitted(f, () => api(f).onWheel({ deltaY: 1, preventDefault: () => {} }));
    expect(z).toEqual(FIT_ZOOM);
  });

  it('double-click toggles fit <-> 2x', () => {
    const fitted = make(FIT_ZOOM);
    expect(emitted(fitted, () => api(fitted).onDoubleClick()).scale).toBe(2);
    const zoomed = make({ scale: 3, tx: 5, ty: 5 });
    expect(emitted(zoomed, () => api(zoomed).onDoubleClick())).toEqual(FIT_ZOOM);
  });

  it('pans only when zoomed past fit', () => {
    const fitted = make(FIT_ZOOM);
    let fired = false;
    fitted.componentInstance.zoomChange.subscribe(() => (fired = true));
    const a = api(fitted);
    a.onPointerDown({ button: 0, clientX: 0, clientY: 0, pointerId: 1, target: document.createElement('div') });
    a.onPointerMove({ pointerId: 1, clientX: 20, clientY: 20 });
    expect(fired).toBe(false);

    const zoomed = make({ scale: 2, tx: 0, ty: 0 });
    const b = api(zoomed);
    b.onPointerDown({ button: 0, clientX: 0, clientY: 0, pointerId: 1, target: document.createElement('div') });
    const z = emitted(zoomed, () => b.onPointerMove({ pointerId: 1, clientX: 15, clientY: -10 }));
    expect(z).toEqual({ scale: 2, tx: 15, ty: -10 });
  });

  // The formula, on a 800x600 pane showing a 4000x3000 frame (object-contain fit
  // scale 0.2, so the image renders 800x600 and fills the pane):
  //   tx = -scale * (cx - 0.5) * naturalWidth  * fit
  //   ty = -scale * (cy - 0.5) * naturalHeight * fit
  describe('focus point (zoom onto the key subject)', () => {
    const FOCUS: [number, number] = [0.75, 0.25];

    function focused(zoom: ZoomState = FIT_ZOOM, focus: [number, number] | null = FOCUS) {
      const fixture = make(zoom);
      fixture.componentRef.setInput('focusPoint', focus);
      fixture.detectChanges();
      measure(fixture);
      return fixture;
    }

    it('double-click lands the focus point on the pane centre', () => {
      const f = focused();

      const z = emitted(f, () => api(f).onDoubleClick());

      expect(z).toEqual({ scale: 2, tx: -400, ty: 300 });
      apply(f, z);
      expect(api(f).transform()).toBe('translate(-400px, 300px) scale(2)');
    });

    it('the Z key runs the same math as a double-click', () => {
      const f = focused();

      const z = emitted(f, () => f.componentInstance.toggleZoom());

      expect(z).toEqual({ scale: 2, tx: -400, ty: 300 });
    });

    it('stays centred without a focus point, and zooming back out still resets to fit', () => {
      const f = focused(FIT_ZOOM, null);

      expect(emitted(f, () => api(f).onDoubleClick())).toEqual({ scale: 2, tx: 0, ty: 0 });

      apply(f, { scale: 2, tx: 0, ty: 0 });
      expect(emitted(f, () => api(f).onDoubleClick())).toEqual(FIT_ZOOM);
    });

    it('stays centred while the image has not loaded', () => {
      const f = focused();
      measure(f, { width: 0, height: 0 });

      expect(emitted(f, () => api(f).onDoubleClick())).toEqual({ scale: 2, tx: 0, ty: 0 });
    });

    it('wheeling off fit re-frames, but a further step keeps the user crop', () => {
      const f = focused();

      const first = emitted(f, () => api(f).onWheel({ deltaY: -1, preventDefault: () => {} }));
      expect(first.scale).toBeCloseTo(1.15, 5);
      expect(first.tx).toBeCloseTo(-230, 5);
      expect(first.ty).toBeCloseTo(172.5, 5);

      apply(f, { scale: 2, tx: 5, ty: 5 });
      const second = emitted(f, () => api(f).onWheel({ deltaY: -1, preventDefault: () => {} }));
      expect(second.tx).toBe(5);
      expect(second.ty).toBe(5);
    });

    // The latch: a suggestion must never re-frame a crop the user chose by hand.
    it('stops re-framing once the user has panned the frame', () => {
      const f = focused({ scale: 2, tx: 0, ty: 0 });
      const a = api(f);
      a.onPointerDown({ button: 0, clientX: 0, clientY: 0, pointerId: 1, target: document.createElement('div') });
      a.onPointerMove({ pointerId: 1, clientX: 40, clientY: 0 });

      apply(f, FIT_ZOOM);

      expect(emitted(f, () => a.onDoubleClick())).toEqual({ scale: 2, tx: 0, ty: 0 });
    });

    it('stops re-framing once the user has wheeled the frame past fit', () => {
      const f = focused({ scale: 2, tx: 0, ty: 0 });
      api(f).onWheel({ deltaY: -1, preventDefault: () => {} });

      apply(f, FIT_ZOOM);

      expect(emitted(f, () => api(f).onDoubleClick())).toEqual({ scale: 2, tx: 0, ty: 0 });
    });

    it('releases the latch when the pane moves to another frame', () => {
      const f = focused({ scale: 2, tx: 0, ty: 0 });
      const a = api(f);
      a.onPointerDown({ button: 0, clientX: 0, clientY: 0, pointerId: 1, target: document.createElement('div') });
      a.onPointerMove({ pointerId: 1, clientX: 40, clientY: 0 });

      f.componentRef.setInput('src', '/next.jpg');
      apply(f, FIT_ZOOM);
      measure(f);

      expect(emitted(f, () => a.onDoubleClick())).toEqual({ scale: 2, tx: -400, ty: 300 });
    });
  });

  // What the darkroom's per-frame chrome hangs off: where the photo actually is
  // inside a pane that letterboxes it.
  describe('letterbox insets', () => {
    /** Load the frame the way the browser does, after stubbing the two sizes. */
    function loaded(
      zoom: ZoomState = FIT_ZOOM,
      natural: { width: number; height: number } = NATURAL,
    ): ComponentFixture<SyncedZoomComponent> {
      const fixture = make(zoom);
      measure(fixture, natural);
      fixture.nativeElement.querySelector('img')!.dispatchEvent(new Event('load'));
      fixture.detectChanges();
      return fixture;
    }

    it('reports no inset until the pane and the frame have both been measured', () => {
      const f = make();
      expect(f.componentInstance.fitInsetX()).toBe(0);
      expect(f.componentInstance.fitInsetY()).toBe(0);
    });

    // 800x600 pane, 4000x3000 frame: the contain fit is 0.2 and the image fills
    // the pane exactly, so there is no letterbox to inset by.
    it('reports no inset when the frame fills the pane', () => {
      const f = loaded();
      expect(f.componentInstance.fitInsetX()).toBe(0);
      expect(f.componentInstance.fitInsetY()).toBe(0);
    });

    // 800x600 pane, 4000x1000 frame: fit 0.2, so the image renders 800x200 and
    // the bars above and below are (600 - 200) / 2 each.
    it('halves the leftover height for a frame wider than its pane', () => {
      const f = loaded(FIT_ZOOM, { width: 4000, height: 1000 });
      expect(f.componentInstance.fitInsetX()).toBe(0);
      expect(f.componentInstance.fitInsetY()).toBe(200);
    });

    // 800x600 pane, 1000x4000 frame: fit 0.15, image 150x600, bars of 325 aside.
    it('halves the leftover width for a frame taller than its pane', () => {
      const f = loaded(FIT_ZOOM, { width: 1000, height: 4000 });
      expect(f.componentInstance.fitInsetX()).toBe(325);
      expect(f.componentInstance.fitInsetY()).toBe(0);
    });

    // Past fit the image outgrows its box, so chrome traced to it belongs at the
    // pane's own corner -- which is where a zero inset puts it.
    it('shrinks the inset as the shared zoom grows, and never past zero', () => {
      const f = loaded({ scale: 2, tx: 0, ty: 0 }, { width: 4000, height: 1000 });
      expect(f.componentInstance.fitInsetY()).toBe(100);

      apply(f, { scale: 8, tx: 0, ty: 0 });
      expect(f.componentInstance.fitInsetY()).toBe(0);
    });

    it('publishes the insets as custom properties on the pane', () => {
      const host: HTMLElement = loaded(FIT_ZOOM, { width: 4000, height: 1000 }).nativeElement;
      expect(host.style.getPropertyValue('--fit-inset-y')).toBe('200px');
      expect(host.style.getPropertyValue('--fit-inset-x')).toBe('0px');
    });
  });
  describe('progressive load', () => {
    class FakeImage {
      static instances: FakeImage[] = [];
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      src = '';
      constructor() { FakeImage.instances.push(this); }
    }

    beforeEach(() => {
      FakeImage.instances = [];
      vi.useFakeTimers();
      vi.stubGlobal('Image', FakeImage);
    });
    afterEach(() => {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    });

    function makeProgressive(inputs: Record<string, unknown> = {}): ComponentFixture<SyncedZoomComponent> {
      const fixture = TestBed.createComponent(SyncedZoomComponent);
      const all: Record<string, unknown> = {
        src: '/render-a.jpg', placeholderSrc: '/thumb-a.jpg', frameKey: 'a', zoom: FIT_ZOOM, ...inputs };
      for (const [k, v] of Object.entries(all)) fixture.componentRef.setInput(k, v);
      fixture.detectChanges();
      return fixture;
    }

    function setInputs(f: ComponentFixture<SyncedZoomComponent>, inputs: Record<string, unknown>): void {
      for (const [k, v] of Object.entries(inputs)) f.componentRef.setInput(k, v);
      f.detectChanges();
    }

    function startPreload(f: ComponentFixture<SyncedZoomComponent>): FakeImage {
      vi.advanceTimersByTime(SHARP_PRELOAD_DEBOUNCE_MS);
      f.detectChanges();
      return FakeImage.instances[FakeImage.instances.length - 1];
    }

    function imgEl(f: ComponentFixture<SyncedZoomComponent>): HTMLImageElement {
      return f.nativeElement.querySelector('img');
    }

    /** Pretend the browser finished loading `url` into the pane's <img>. */
    function browserLoaded(f: ComponentFixture<SyncedZoomComponent>, url: string): void {
      const img = imgEl(f);
      Object.defineProperty(img, 'complete', { value: true, configurable: true });
      Object.defineProperty(img, 'naturalWidth', { value: 640, configurable: true });
      Object.defineProperty(img, 'naturalHeight', { value: 480, configurable: true });
      Object.defineProperty(img, 'currentSrc', { value: new URL(url, document.baseURI).href, configurable: true });
      img.dispatchEvent(new Event('load'));
      f.detectChanges();
    }

    it('shows the placeholder first, then the render once the preloader has loaded it', () => {
      const f = makeProgressive();
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-a.jpg');
      const emitted: string[] = [];
      f.componentInstance.sharpLoaded.subscribe(s => emitted.push(s));
      const pre = startPreload(f);
      expect(pre.src).toBe('/render-a.jpg');
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-a.jpg');
      pre.onload!();
      f.detectChanges();
      expect(imgEl(f).getAttribute('src')).toBe('/render-a.jpg');
      expect(emitted).toEqual(['/render-a.jpg']);
    });

    it('does not request the render before the debounce has elapsed', () => {
      makeProgressive();
      vi.advanceTimersByTime(SHARP_PRELOAD_DEBOUNCE_MS - 1);
      expect(FakeImage.instances).toHaveLength(0);
    });

    it('never shows the previous frame render for the next frame, and a late onload promotes nothing', () => {
      const f = makeProgressive();
      const pre = startPreload(f);
      const lateOnload = pre.onload!;
      const emitted: string[] = [];
      f.componentInstance.sharpLoaded.subscribe(s => emitted.push(s));
      setInputs(f, { src: '/render-b.jpg', placeholderSrc: '/thumb-b.jpg', frameKey: 'b' });
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-b.jpg');
      // The superseded preloader is aborted, then its handler fires anyway.
      expect(pre.onload).toBeNull();
      expect(pre.onerror).toBeNull();
      expect(pre.src).toBe('');
      lateOnload();
      f.detectChanges();
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-b.jpg');
      expect(emitted).toEqual([]);
    });

    it('skips the debounce for a render already known to be loaded', () => {
      const loaded = new LoadedSources();
      loaded.add('/render-a.jpg');
      // The effect runs on the first change detection, so subscribe before it.
      const f = TestBed.createComponent(SyncedZoomComponent);
      const inputs: Record<string, unknown> = {
        src: '/render-a.jpg', placeholderSrc: '/thumb-a.jpg', frameKey: 'a', zoom: FIT_ZOOM, loadedSources: loaded };
      for (const [k, v] of Object.entries(inputs)) f.componentRef.setInput(k, v);
      const emitted: string[] = [];
      f.componentInstance.sharpLoaded.subscribe(s => emitted.push(s));
      f.detectChanges();
      expect(FakeImage.instances).toHaveLength(1);
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-a.jpg');
      expect(emitted).toEqual([]);
      FakeImage.instances[0].onload!();
      f.detectChanges();
      expect(imgEl(f).getAttribute('src')).toBe('/render-a.jpg');
      expect(emitted).toEqual(['/render-a.jpg']);
    });

    it('keeps the current thumbnail on render failure and reports settlement without sharp success', () => {
      const f = makeProgressive();
      const failed: string[] = [];
      const sharp: string[] = [];
      f.componentInstance.sharpFailed.subscribe(s => failed.push(s));
      f.componentInstance.sharpLoaded.subscribe(s => sharp.push(s));
      startPreload(f).onerror!();
      f.detectChanges();
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-a.jpg');
      expect(failed).toEqual(['/render-a.jpg']);
      expect(sharp).toEqual([]);
    });

    it('ignores a canceled failure even after returning to the same source', () => {
      const f = makeProgressive();
      const lateFailure = startPreload(f).onerror!;
      const failed: string[] = [];
      f.componentInstance.sharpFailed.subscribe(s => failed.push(s));
      setInputs(f, { src: '/render-b.jpg', frameKey: 'b' });
      setInputs(f, { src: '/render-a.jpg', frameKey: 'a' });
      lateFailure();
      expect(failed).toEqual([]);
    });

    it('revalidates a previously displayed render after revisiting its frame', () => {
      const f = makeProgressive();
      startPreload(f).onload!();
      f.detectChanges();
      setInputs(f, { src: '/render-b.jpg', placeholderSrc: '/thumb-b.jpg', frameKey: 'b' });
      setInputs(f, { src: '/render-a.jpg', placeholderSrc: '/thumb-a.jpg', frameKey: 'a' });
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-a.jpg');
    });

    it('promotes a genuinely warm browser image without waiting for another load event', () => {
      class WarmImage extends FakeImage {
        complete = true;
        naturalWidth = 640;
      }
      vi.stubGlobal('Image', WarmImage);
      const loaded = new LoadedSources();
      loaded.add('/render-a.jpg');
      const f = makeProgressive({ loadedSources: loaded });
      expect(imgEl(f).getAttribute('src')).toBe('/render-a.jpg');
    });

    it('stays on the thumbnail when a warm-looking image has zero natural width', () => {
      class BrokenWarmImage extends FakeImage {
        complete = true;
        naturalWidth = 0;
      }
      vi.stubGlobal('Image', BrokenWarmImage);
      const loaded = new LoadedSources();
      loaded.add('/render-a.jpg');
      const f = makeProgressive({ loadedSources: loaded });
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-a.jpg');
    });

    it('keeps the thumbnail and reports failure when a LoadedSources-hinted preload errors', () => {
      const loaded = new LoadedSources();
      loaded.add('/render-a.jpg');
      const f = TestBed.createComponent(SyncedZoomComponent);
      const inputs: Record<string, unknown> = {
        src: '/render-a.jpg', placeholderSrc: '/thumb-a.jpg', frameKey: 'a', zoom: FIT_ZOOM, loadedSources: loaded };
      for (const [k, v] of Object.entries(inputs)) f.componentRef.setInput(k, v);
      const failed: string[] = [];
      f.componentInstance.sharpFailed.subscribe(s => failed.push(s));
      f.detectChanges();
      FakeImage.instances[0].onerror!();
      f.detectChanges();
      expect(imgEl(f).getAttribute('src')).toBe('/thumb-a.jpg');
      expect(failed).toEqual(['/render-a.jpg']);
    });

    it('records a fetched render so a later pane can skip the debounce', () => {
      const loaded = new LoadedSources();
      const f = makeProgressive({ loadedSources: loaded });
      startPreload(f).onload!();
      expect(loaded.has('/render-a.jpg')).toBe(true);
    });

    it('past the fit scale still uses the full-resolution source', () => {
      const f = makeProgressive({ fullResSrc: '/full-a.jpg', zoom: { scale: 2, tx: 0, ty: 0 } });
      expect(imgEl(f).getAttribute('src')).toBe('/full-a.jpg');
    });

    it('builds no preloader and behaves as before without a placeholder', () => {
      const f = makeProgressive({ placeholderSrc: null, frameKey: null });
      vi.advanceTimersByTime(SHARP_PRELOAD_DEBOUNCE_MS * 2);
      expect(FakeImage.instances).toHaveLength(0);
      expect(imgEl(f).getAttribute('src')).toBe('/render-a.jpg');
      expect(imgEl(f).classList.contains('opacity-0')).toBe(false);
    });

    it('hides the pane until the image of the current frame has loaded', () => {
      const f = makeProgressive();
      expect(imgEl(f).classList.contains('opacity-0')).toBe(true);
      browserLoaded(f, '/thumb-a.jpg');
      expect(imgEl(f).classList.contains('opacity-0')).toBe(false);
      setInputs(f, { src: '/render-b.jpg', placeholderSrc: '/thumb-b.jpg', frameKey: 'b' });
      expect(imgEl(f).classList.contains('opacity-0')).toBe(true);
    });

    /** Make the <img> report what the browser would for an image it already holds. */
    function stubImage(f: ComponentFixture<SyncedZoomComponent>, state: { complete: boolean; naturalWidth: number; currentSrc: string }): void {
      const img = imgEl(f);
      Object.defineProperty(img, 'complete', { value: state.complete, configurable: true });
      Object.defineProperty(img, 'naturalWidth', { value: state.naturalWidth, configurable: true });
      Object.defineProperty(img, 'currentSrc', {
        get: () => (state.currentSrc === 'follow-src'
          ? new URL(img.getAttribute('src')!, document.baseURI).href
          : new URL(state.currentSrc, document.baseURI).href),
        configurable: true,
      });
    }

    it('does not hide the pane on a step onto an image the browser already holds', () => {
      const f = makeProgressive();
      browserLoaded(f, '/thumb-a.jpg');
      // Cached: complete and decoded; currentSrc tracks the element's own src attribute, so only a
      // read made after [src] was applied can match the new frame's URL.
      stubImage(f, { complete: true, naturalWidth: 640, currentSrc: 'follow-src' });
      setInputs(f, { src: '/render-b.jpg', placeholderSrc: '/thumb-b.jpg', frameKey: 'b' });
      TestBed.tick();
      expect(imgEl(f).classList.contains('opacity-0')).toBe(false);
    });

    it('still hides the pane on a step onto an image that is not loaded yet, until it loads', () => {
      const f = makeProgressive();
      browserLoaded(f, '/thumb-a.jpg');
      // Mid-download: dimensions known, but not complete.
      stubImage(f, { complete: false, naturalWidth: 640, currentSrc: '/thumb-b.jpg' });
      setInputs(f, { src: '/render-b.jpg', placeholderSrc: '/thumb-b.jpg', frameKey: 'b' });
      TestBed.tick();
      expect(imgEl(f).classList.contains('opacity-0')).toBe(true);
      browserLoaded(f, '/thumb-b.jpg');
      expect(imgEl(f).classList.contains('opacity-0')).toBe(false);
    });

    it('never shows the previous frame pixels under the new key, even when the old image is complete', () => {
      const f = makeProgressive();
      browserLoaded(f, '/thumb-a.jpg');
      // The element still reports frame A as complete and decoded.
      stubImage(f, { complete: true, naturalWidth: 640, currentSrc: '/thumb-a.jpg' });
      setInputs(f, { src: '/render-b.jpg', placeholderSrc: '/thumb-b.jpg', frameKey: 'b' });
      TestBed.tick();
      expect(imgEl(f).classList.contains('opacity-0')).toBe(true);
    });

    it('does not hide the pane again for a source change inside one frame', () => {
      const f = makeProgressive();
      browserLoaded(f, '/thumb-a.jpg');
      startPreload(f).onload!();
      f.detectChanges();
      expect(imgEl(f).getAttribute('src')).toBe('/render-a.jpg');
      expect(imgEl(f).classList.contains('opacity-0')).toBe(false);
    });

    it('ignores a load for a URL the pane has moved on from', () => {
      const f = makeProgressive();
      setInputs(f, { src: '/render-b.jpg', placeholderSrc: '/thumb-b.jpg', frameKey: 'b' });
      browserLoaded(f, '/thumb-a.jpg');
      expect(imgEl(f).classList.contains('opacity-0')).toBe(true);
      browserLoaded(f, '/thumb-b.jpg');
      expect(imgEl(f).classList.contains('opacity-0')).toBe(false);
    });

    it('shows a broken image of the current frame rather than staying hidden', () => {
      const f = makeProgressive();
      imgEl(f).dispatchEvent(new Event('error'));
      f.detectChanges();
      expect(imgEl(f).classList.contains('opacity-0')).toBe(false);
    });

    it('caps the loaded-sources set', () => {
      const loaded = new LoadedSources();
      for (let i = 0; i < LoadedSources.MAX + 5; i++) loaded.add(`/r${i}.jpg`);
      expect(loaded.has('/r0.jpg')).toBe(false);
      expect(loaded.has(`/r${LoadedSources.MAX + 4}.jpg`)).toBe(true);
    });
  });
});
