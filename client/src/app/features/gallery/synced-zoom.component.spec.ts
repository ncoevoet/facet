import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SyncedZoomComponent, ZoomState, FIT_ZOOM } from './synced-zoom.component';

describe('SyncedZoomComponent', () => {
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

  it('builds a translate+scale transform from the shared zoom', () => {
    const f = make({ scale: 2, tx: 10, ty: -5 });
    expect(api(f).transform()).toBe('translate(10px, -5px) scale(2)');
  });

  it('uses the thumbnail at fit scale and the full-res past it', () => {
    expect(api(make(FIT_ZOOM)).effectiveSrc()).toBe('/thumb.jpg');
    expect(api(make({ scale: 1.5, tx: 0, ty: 0 })).effectiveSrc()).toBe('/full.jpg');
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
    a.onPointerDown({ clientX: 0, clientY: 0, pointerId: 1, target: document.createElement('div') });
    a.onPointerMove({ clientX: 20, clientY: 20 });
    expect(fired).toBe(false);

    const zoomed = make({ scale: 2, tx: 0, ty: 0 });
    const b = api(zoomed);
    b.onPointerDown({ clientX: 0, clientY: 0, pointerId: 1, target: document.createElement('div') });
    const z = emitted(zoomed, () => b.onPointerMove({ clientX: 15, clientY: -10 }));
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
      a.onPointerDown({ clientX: 0, clientY: 0, pointerId: 1, target: document.createElement('div') });
      a.onPointerMove({ clientX: 40, clientY: 0 });

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
      a.onPointerDown({ clientX: 0, clientY: 0, pointerId: 1, target: document.createElement('div') });
      a.onPointerMove({ clientX: 40, clientY: 0 });

      f.componentRef.setInput('src', '/next.jpg');
      apply(f, FIT_ZOOM);
      measure(f);

      expect(emitted(f, () => a.onDoubleClick())).toEqual({ scale: 2, tx: -400, ty: 300 });
    });
  });
});
