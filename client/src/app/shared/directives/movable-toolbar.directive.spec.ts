import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MovableToolbarDirective } from './movable-toolbar.directive';

@Component({
  imports: [MovableToolbarDirective],
  template: `<section #area><div appMovableToolbar [toolbarBoundary]="area" [toolbarOwner]="owner()" [toolbarRightInset]="inset()">
    <button data-toolbar-drag-handle>Move</button><button class="action">Rate</button><div data-toolbar-panel></div>
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

  it('opens disclosure panels into available space and bounds their height', () => {
    const { bar, handle, pointer } = setup();
    const panel = bar.querySelector<HTMLElement>('[data-toolbar-panel]')!;
    expect(bar.dataset['toolbarDown']).toBe('false');
    expect(panel.style.maxHeight).toBe('480px');
    pointer(handle, 'pointerdown', 0, 0);
    pointer(bar, 'pointermove', 0, -492); flush();
    expect(bar.dataset['toolbarDown']).toBe('true');
    expect(panel.style.maxHeight).toBe('522px');
  });

  it.each(['null', '[]', '{}', 'bad json', '{"x":"0.5","up":0}', '{"x":0}',
    '{"x":-0.1,"up":0}', '{"x":0,"up":-0.1}', '{"x":0,"up":1.1}', '{"x":1e999,"up":0}'])('ignores invalid saved position %s', saved => {
      localStorage.setItem('facet_selection_bar:alice', saved);
      expect(setup().bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    });

  it('loads valid boundary values and treats unavailable storage as optional', () => {
    localStorage.setItem('facet_selection_bar:alice', '{"x":1,"up":0.5}');
    const first = setup();
    expect(first.bar.style.transform).toBe('translate3d(492px, -246px, 0)');
    first.fixture.destroy();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('disabled'); });
    const second = setup();
    expect(second.bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('disabled'); });
    expect(() => second.key('ArrowRight')).not.toThrow();
    flush(); expect(second.bar.style.transform).toBe('translate3d(16px, 0px, 0)');
  });

  it('supports reverse and accelerated keyboard movement, and lets unrelated keys bubble', () => {
    const { bar, handle, key } = setup();
    handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', shiftKey: true, bubbles: true }));
    key('ArrowUp'); key('ArrowLeft'); key('ArrowDown'); flush();
    expect(bar.style.transform).toBe('translate3d(32px, 0px, 0)');
    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    handle.dispatchEvent(event); flush();
    expect(event.defaultPrevented).toBe(false);
    expect(bar.style.transform).toBe('translate3d(32px, 0px, 0)');
    const actionKey = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
    bar.querySelector('.action')!.dispatchEvent(actionKey); flush();
    expect(actionKey.defaultPrevented).toBe(false);
    expect(bar.style.transform).toBe('translate3d(32px, 0px, 0)');
  });

  it('rejects secondary/nonprimary pointers and ignores mismatched completion', () => {
    const { bar, handle, pointer } = setup();
    for (const init of [{ button: 2, isPrimary: true }, { button: 0, isPrimary: false }]) {
      handle.dispatchEvent(new PointerEvent('pointerdown', { ...init, pointerId: 1, bubbles: true }));
      pointer(bar, 'pointermove', 100, -100); flush();
      expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    }
    pointer(handle, 'pointerdown', 0, 0);
    pointer(handle, 'pointerdown', 50, -50, 2);
    pointer(bar, 'pointermove', 100, -100); flush();
    pointer(bar, 'pointerup', 100, -100, 2);
    pointer(bar, 'pointercancel', 100, -100, 2);
    expect(localStorage.getItem('facet_selection_bar:alice')).toBeNull();
    pointer(bar, 'pointerup', 100, -100);
    expect(JSON.parse(localStorage.getItem('facet_selection_bar:alice')!)).toEqual({ x: 100 / 492, up: 100 / 492 });
  });

  it.each(['Escape', 'Home', 'ArrowRight'])('cancels a drag before the %s command', command => {
    const { bar, handle, pointer, key } = setup();
    key('ArrowRight'); flush();
    pointer(handle, 'pointerdown', 0, 0);
    pointer(bar, 'pointermove', 100, -100); flush();
    key(command); flush();
    expect(bar.style.transform).toBe(command === 'Home' ? 'translate3d(0px, 0px, 0)'
      : command === 'Escape' ? 'translate3d(16px, 0px, 0)' : 'translate3d(32px, 0px, 0)');
    pointer(bar, 'pointerup', 100, -100); flush();
    expect(bar.style.transform).not.toBe('translate3d(116px, -100px, 0)');
  });

  it('restores a drag on lost pointer capture', () => {
    const { bar, handle, pointer } = setup();
    pointer(handle, 'pointerdown', 0, 0); pointer(bar, 'pointermove', 100, -100); flush();
    pointer(bar, 'lostpointercapture', 100, -100); flush();
    expect(bar.style.transform).toBe('translate3d(0px, 0px, 0)');
    expect(localStorage.getItem('facet_selection_bar:alice')).toBeNull();
  });

});
