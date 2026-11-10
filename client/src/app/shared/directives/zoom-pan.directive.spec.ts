import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ZoomPanDirective } from './zoom-pan.directive';

@Component({
  selector: 'app-zoom-host',
  imports: [ZoomPanDirective],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div [appZoomPan]="key()" #zoom="zoomPan">
      <img alt="" [style.transform]="zoom.transform()" />
    </div>
  `,
})
class ZoomHostComponent {
  readonly key = signal('a');
}

describe('ZoomPanDirective', () => {
  let fixture: ComponentFixture<ZoomHostComponent>;
  let panel: HTMLElement;
  let img: HTMLImageElement;

  const wheel = (deltaY: number) => {
    const event = new WheelEvent('wheel', { deltaY, cancelable: true });
    panel.dispatchEvent(event);
    fixture.detectChanges();
    return event;
  };

  const pointer = (type: string, clientX: number, clientY: number, pointerId = 1) => {
    panel.dispatchEvent(new PointerEvent(type, { clientX, clientY, pointerId, bubbles: true }));
    fixture.detectChanges();
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [ZoomHostComponent] });
    fixture = TestBed.createComponent(ZoomHostComponent);
    fixture.detectChanges();
    panel = fixture.nativeElement.querySelector('div');
    img = fixture.nativeElement.querySelector('img');
  });

  afterEach(() => TestBed.resetTestingModule());

  it('zooms with the wheel within 0.5x and 5x and keeps the page from scrolling', () => {
    const event = wheel(-1);
    expect(event.defaultPrevented).toBe(true);
    expect(img.style.transform).toBe('scale(1.15) translate(0px, 0px)');
    for (let i = 0; i < 40; i++) wheel(-1);
    expect(img.style.transform).toBe('scale(5) translate(0px, 0px)');
    for (let i = 0; i < 80; i++) wheel(1);
    expect(img.style.transform).toBe('scale(0.5) translate(0px, 0px)');
  });

  it('pans only while zoomed in, clamped to the panel', () => {
    Object.defineProperty(panel, 'clientWidth', { value: 400 });
    Object.defineProperty(panel, 'clientHeight', { value: 300 });
    pointer('pointerdown', 0, 0);
    pointer('pointermove', 50, 0);
    pointer('pointerup', 50, 0);
    expect(img.style.transform).toBe('');
    let scale = 1;
    for (let i = 0; i < 7; i++) { wheel(-1); scale += 0.15; }
    pointer('pointerdown', 0, 0);
    expect(panel.classList).toContain('cursor-grabbing');
    pointer('pointermove', 10000, 0);
    pointer('pointerup', 10000, 0);
    expect(panel.classList).not.toContain('cursor-grabbing');
    expect(img.style.transform).toBe(`scale(${scale}) translate(${400 * (scale - 1) / (2 * scale)}px, 0px)`);
  });

  it('provides bounded explicit zoom steps and centers an image below Fit', () => {
    const zoom = fixture.debugElement.children[0].injector.get(ZoomPanDirective);
    Object.defineProperty(panel, 'clientWidth', { value: 400 });
    Object.defineProperty(panel, 'clientHeight', { value: 300 });
    zoom.zoomStep(1); fixture.detectChanges();
    expect(img.style.transform).toBe('scale(1.25) translate(0px, 0px)');
    pointer('pointerdown', 0, 0); pointer('pointermove', 40, 20); pointer('pointerup', 40, 20);
    expect(zoom.panX()).not.toBe(0);
    zoom.zoomStep(-4); fixture.detectChanges();
    expect(img.style.transform).toBe('scale(0.5) translate(0px, 0px)');
    zoom.zoomStep(40); fixture.detectChanges();
    expect(img.style.transform).toBe('scale(5) translate(0px, 0px)');
    zoom.reset(); fixture.detectChanges(); expect(img.style.transform).toBe('');
  });

  it('zooms, pans in all directions within bounds, and fits from the focused canvas', () => {
    Object.defineProperty(panel, 'clientWidth', { value: 400 });
    Object.defineProperty(panel, 'clientHeight', { value: 300 });
    const key = (value: string) => {
      const event = new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true });
      panel.dispatchEvent(event); fixture.detectChanges(); return event;
    };
    expect(key('ArrowRight').defaultPrevented).toBe(false);
    expect(key('+').defaultPrevented).toBe(true);
    expect(key('ArrowRight').defaultPrevented).toBe(true);
    expect(img.style.transform).toBe('scale(1.25) translate(-32px, 0px)');
    key('ArrowLeft'); key('ArrowUp');
    expect(img.style.transform).toBe('scale(1.25) translate(0px, 30px)');
    key('ArrowDown'); key('Home'); key('+');
    for (let i = 0; i < 20; i++) key('ArrowRight');
    expect(img.style.transform).toBe('scale(1.25) translate(-40px, 0px)');
    expect(key('Tab').defaultPrevented).toBe(false);
    key('Home'); expect(img.style.transform).toBe('');
    key('-'); expect(img.style.transform).toBe('scale(0.75) translate(0px, 0px)');
  });

  it('keeps zooming out with the minus key below Fit instead of jumping back to Fit', () => {
    const zoom = fixture.debugElement.children[0].injector.get(ZoomPanDirective);
    wheel(1); wheel(1);
    const below = zoom.scale();
    expect(below).toBeLessThan(1);
    panel.dispatchEvent(new KeyboardEvent('keydown', { key: '-', bubbles: true, cancelable: true }));
    expect(zoom.scale()).toBeLessThan(below);
    expect(zoom.scale()).toBeGreaterThanOrEqual(0.5);
  });

  it('suspends panning while two pointers are down and re-anchors on the one left', () => {
    const zoom = fixture.debugElement.children[0].injector.get(ZoomPanDirective);
    Object.defineProperty(panel, 'clientWidth', { value: 400 });
    Object.defineProperty(panel, 'clientHeight', { value: 300 });
    zoom.zoomStep(4); fixture.detectChanges();
    expect(zoom.scale()).toBe(2);
    pointer('pointerdown', 0, 0, 1);
    pointer('pointerdown', 200, 0, 2);
    expect(panel.classList).not.toContain('cursor-grabbing');
    pointer('pointermove', 10, 0, 1); pointer('pointermove', 210, 0, 2); pointer('pointermove', 20, 0, 1);
    expect(zoom.panX()).toBe(0);
    pointer('pointerup', 210, 0, 2);
    expect(panel.classList).toContain('cursor-grabbing');
    pointer('pointermove', 40, 0, 1);
    expect(zoom.panX()).toBe(10);
    pointer('pointerup', 40, 0, 1);
    expect(panel.classList).not.toContain('cursor-grabbing');
  });

  it('leaves nested controls, modified shortcuts and IME input alone', () => {
    wheel(-1);
    const button = document.createElement('button'); panel.append(button);
    const nested = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
    button.dispatchEvent(nested);
    expect(nested.defaultPrevented).toBe(false);
    for (const modifiers of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { isComposing: true }]) {
      const event = new KeyboardEvent('keydown', { key: '+', cancelable: true, ...modifiers });
      panel.dispatchEvent(event); expect(event.defaultPrevented).toBe(false);
    }
    fixture.detectChanges();
    expect(img.style.transform).toBe('scale(1.15) translate(0px, 0px)');
  });

  it('reaches every zoomed edge using the fitted aspect ratio and reclamps on zoom-out', () => {
    const zoom = fixture.debugElement.children[0].injector.get(ZoomPanDirective);
    Object.defineProperty(panel, 'clientWidth', { value: 400 });
    Object.defineProperty(panel, 'clientHeight', { value: 300 });
    Object.defineProperties(img, { naturalWidth: { value: 800 }, naturalHeight: { value: 400 } });
    zoom.zoomStep(16); fixture.detectChanges();
    expect(panel.classList).toContain('touch-none');
    pointer('pointerdown', 0, 0); pointer('pointermove', -10000, -10000); pointer('pointerup', -10000, -10000);
    expect(zoom.panX()).toBe(-160); expect(zoom.panY()).toBe(-70);
    zoom.zoomStep(-15); fixture.detectChanges();
    expect(zoom.scale()).toBe(1.25);
    expect(zoom.panX()).toBe(-40); expect(zoom.panY()).toBe(0);
    zoom.reset(); fixture.detectChanges();
    expect(panel.classList).not.toContain('touch-none');
  });

  it('ends the previous drag when the displayed photo changes', () => {
    wheel(-1); pointer('pointerdown', 0, 0);
    expect(panel.classList).toContain('cursor-grabbing');
    fixture.componentInstance.key.set('next-photo'); fixture.detectChanges();
    pointer('pointermove', 200, 100);
    expect(panel.classList).not.toContain('cursor-grabbing');
    expect(img.style.transform).toBe('');
  });

  it('resets on double-click and when the bound value changes', () => {
    wheel(-1);
    panel.dispatchEvent(new MouseEvent('dblclick'));
    fixture.detectChanges();
    expect(img.style.transform).toBe('');
    wheel(-1);
    fixture.componentInstance.key.set('b');
    fixture.detectChanges();
    expect(img.style.transform).toBe('');
  });
});
