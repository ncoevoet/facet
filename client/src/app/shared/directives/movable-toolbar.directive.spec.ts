import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MovableToolbarDirective } from './movable-toolbar.directive';

@Component({
  imports: [MovableToolbarDirective],
  template: `<section #area><div appMovableToolbar [toolbarBoundary]="area" [toolbarOwner]="owner()" [toolbarRightInset]="inset()">
    <button data-toolbar-drag-handle>Move</button><button class="action">Rate</button>
  </div></section>`,
})
class HostComponent { readonly owner = signal('alice'); readonly inset = signal(8); }

describe('MovableToolbarDirective', () => {
  let frame: FrameRequestCallback | undefined;
  let resized: () => void;
  const flush = () => { const callback = frame; frame = undefined; callback?.(0); };
  const setup = () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    const area: HTMLElement = fixture.nativeElement.querySelector('section');
    const bar: HTMLElement = area.querySelector('div')!;
    const handle: HTMLElement = bar.querySelector('button')!;
    vi.spyOn(area, 'getBoundingClientRect').mockReturnValue({ top: 0, right: 800, bottom: 600 } as DOMRect);
    vi.spyOn(bar, 'getBoundingClientRect').mockImplementation(() => {
      const values = /translate3d\(([-.\d]+)px, ([-.\d]+)px/.exec(bar.style.transform);
      return { top: 500 + Number(values?.[2] ?? 0), bottom: 550 + Number(values?.[2] ?? 0), right: 300 + Number(values?.[1] ?? 0) } as DOMRect;
    });
    flush();
    const key = (key: string) => handle.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
    const pointer = (target: HTMLElement, type: string, x: number, y: number, id = 1) => target.dispatchEvent(
      new PointerEvent(type, { pointerId: id, isPrimary: true, button: 0, clientX: x, clientY: y, bubbles: true }),
    );
    return { fixture, area, bar, handle, key, pointer };
  };

  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resized = callback; }
      observe() { /* Controlled geometry below. */ }
      disconnect() { /* No native observer in this test. */ }
    });
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { frame = callback; return 1; });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => { frame = undefined; });
    TestBed.configureTestingModule({ imports: [HostComponent] });
  });
  afterEach(() => { TestBed.resetTestingModule(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('accumulates repeated keyboard steps before the next paint', () => {
    const { bar, key } = setup();
    key('ArrowRight'); key('ArrowRight'); key('ArrowUp'); flush();
    expect(bar.style.transform).toBe('translate3d(32px, -16px, 0)');
  });

  it('moves only from its handle and restores cancelled drags', () => {
    const { bar, handle, pointer } = setup();
    pointer(bar.querySelector('.action')!, 'pointerdown', 0, 0);
    pointer(bar, 'pointermove', 100, -100); flush();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    pointer(handle, 'pointerdown', 0, 0);
    pointer(bar, 'pointermove', 100, -100); flush();
    expect(bar.style.transform).toBe('translate3d(100px, -100px, 0)');
    pointer(bar, 'pointercancel', 100, -100); flush();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    expect(localStorage.getItem('facet_selection_bar:alice')).toBeNull();
  });

  it('remembers completed movement per account and resets with Home', () => {
    const { fixture, bar, handle, pointer, key } = setup();
    pointer(handle, 'pointerdown', 0, 0);
    pointer(bar, 'pointermove', 100, -100);
    pointer(bar, 'pointerup', 100, -100); flush();
    expect(localStorage.getItem('facet_selection_bar:alice')).not.toBeNull();
    fixture.componentInstance.owner.set('bob'); fixture.detectChanges(); flush();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    fixture.componentInstance.owner.set('alice'); fixture.detectChanges(); flush();
    expect(bar.style.transform).toBe('translate3d(100px, -100px, 0)');
    key('Home'); flush();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
  });
  it('clamps a drag to reachable bounds and ignores another pointer', () => {
    const { bar, handle, pointer } = setup();
    pointer(handle, 'pointerdown', 0, 0);
    pointer(bar, 'pointermove', 9999, -9999, 2); flush();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    pointer(bar, 'pointermove', 9999, -9999); flush();
    expect(bar.style.transform).toBe('translate3d(492px, -492px, 0)');
  });

  it('rejects corrupt saved positions', () => {
    localStorage.setItem('facet_selection_bar:alice', '{"x":99,"up":0.5}');
    const { bar } = setup();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
  });

  it('cancels a drag on identity change without saving it to either account', () => {
    const { fixture, bar, handle, pointer } = setup();
    pointer(handle, 'pointerdown', 0, 0);
    pointer(bar, 'pointermove', 100, -100); flush();
    fixture.componentInstance.owner.set('bob'); fixture.detectChanges(); flush();
    pointer(bar, 'pointerup', 100, -100); flush();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    expect(localStorage.getItem('facet_selection_bar:alice')).toBeNull();
    expect(localStorage.getItem('facet_selection_bar:bob')).toBeNull();
  });

  it('keeps the saved relative position reachable after resize and drawer changes', () => {
    const { fixture, area, bar, handle, pointer } = setup();
    pointer(handle, 'pointerdown', 0, 0);
    pointer(bar, 'pointermove', 492, -492);
    pointer(bar, 'pointerup', 492, -492); flush();
    vi.mocked(area.getBoundingClientRect).mockReturnValue({ top: 200, right: 500 } as DOMRect);
    resized(); flush();
    expect(bar.style.transform).toBe('translate3d(192px, -292px, 0)');
    fixture.componentInstance.inset.set(108); fixture.detectChanges(); flush();
    expect(bar.style.transform).toBe('translate3d(92px, -292px, 0)');
    vi.mocked(area.getBoundingClientRect).mockReturnValue({ top: 500, right: 300 } as DOMRect);
    resized(); flush();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    vi.mocked(area.getBoundingClientRect).mockReturnValue({ top: 0, right: 800, bottom: 600 } as DOMRect);
    fixture.componentInstance.inset.set(8); fixture.detectChanges(); flush();
    expect(bar.style.transform).toBe('translate3d(492px, -492px, 0)');
  });

  it('cancels queued painting when destroyed', () => {
    const { fixture, key } = setup();
    key('ArrowUp');
    expect(frame).toBeDefined();
    fixture.destroy();
    expect(frame).toBeUndefined();
  });
});
