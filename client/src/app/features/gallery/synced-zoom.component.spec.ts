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
});
