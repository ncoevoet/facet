import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../core/services/i18n.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { PhotoCollectionSidebarComponent } from './photo-collection-sidebar.component';

describe('PhotoCollectionSidebarComponent', () => {
  let frame: FrameRequestCallback | undefined;
  let resized: () => void;
  const flush = () => { const callback = frame; frame = undefined; callback?.(0); };
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resized = callback; }
      observe() { /* Geometry controlled by tests. */ }
      disconnect() { /* No native observer. */ }
    });
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { frame = callback; return 1; });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => { frame = undefined; });
    TestBed.configureTestingModule({ imports: [PhotoCollectionSidebarComponent], providers: [
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
  });
  afterEach(() => { TestBed.resetTestingModule(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.removeItem('facet_collection_sidebar_width'); });
  function render() {
    const fixture = TestBed.createComponent(PhotoCollectionSidebarComponent);
    fixture.componentRef.setInput('photos', [makePhoto({ path: '/a.jpg', filename: 'a.jpg' }), makePhoto({ path: '/b.jpg', filename: 'b.jpg' })]);
    fixture.componentRef.setInput('currentPath', '/b.jpg');
    fixture.componentRef.setInput('hasMore', true);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const divider = () => root.querySelector<HTMLElement>('[role="separator"]')!;
    return { fixture, root, divider };
  }
  it('marks the current photo and emits explicit choices and paging without changing its inputs', () => {
    const { fixture, root } = render();
    const choose = vi.fn(); const more = vi.fn();
    fixture.componentInstance.choose.subscribe(choose); fixture.componentInstance.more.subscribe(more);
    expect(root.querySelector('[aria-current="true"]')?.getAttribute('aria-label')).toBe('b.jpg');
    root.querySelector<HTMLButtonElement>('button[aria-label="a.jpg"]')!.click();
    root.querySelector<HTMLButtonElement>('button[aria-label="a.jpg"]')!.click();
    root.querySelector<HTMLButtonElement>('div[tabindex] > button')!.click();
    expect(choose).toHaveBeenCalledWith('/a.jpg'); expect(more).toHaveBeenCalledOnce();
    expect(fixture.componentInstance.currentPath()).toBe('/b.jpg');
  });
  it('uses one thumbnail Tab stop and opens the photo reached by an arrow key', () => {
    const { fixture, root } = render();
    const buttons = [...root.querySelectorAll<HTMLButtonElement>('.grid button')];
    expect(buttons.map(button => button.tabIndex)).toEqual([-1, 0]);
    const choose = vi.fn(); fixture.componentInstance.choose.subscribe(choose);
    buttons[1].focus();
    const event = new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true });
    buttons[1].dispatchEvent(event); fixture.detectChanges();
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(buttons[0]);
    expect(buttons.map(button => button.tabIndex)).toEqual([0, -1]);
    expect(choose).toHaveBeenCalledExactlyOnceWith('/a.jpg');
    buttons[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true }));
    expect(choose).toHaveBeenCalledTimes(1);
  });
  it('opens photos with vertical and section-edge keys while preserving modified-key behavior', () => {
    const { fixture, root } = render();
    const photos = Array.from({ length: 4 }, (_, index) => makePhoto({ path: `/p${index}.jpg` }));
    fixture.componentRef.setInput('photos', photos);
    fixture.detectChanges();
    const buttons = [...root.querySelectorAll<HTMLButtonElement>('.grid button')];
    const choose = vi.fn(); fixture.componentInstance.choose.subscribe(choose);
    const key = (index: number, value: string, options: KeyboardEventInit = {}) => {
      const event = new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true, ...options });
      buttons[index].dispatchEvent(event); fixture.detectChanges(); return event;
    };
    key(0, 'ArrowDown'); expect(choose).toHaveBeenLastCalledWith('/p1.jpg');
    key(1, 'End'); expect(choose).toHaveBeenLastCalledWith('/p3.jpg');
    key(3, 'Home'); expect(choose).toHaveBeenLastCalledWith('/p0.jpg');
    key(1, 'ArrowUp'); expect(choose).toHaveBeenLastCalledWith('/p0.jpg');
    const count = choose.mock.calls.length;
    expect(key(0, 'ArrowRight', { ctrlKey: true }).defaultPrevented).toBe(false);
    expect(key(0, 'ArrowRight', { altKey: true }).defaultPrevented).toBe(false);
    expect(key(0, 'ArrowRight', { metaKey: true }).defaultPrevented).toBe(false);
    expect(key(0, 'ArrowRight', { isComposing: true }).defaultPrevented).toBe(false);
    expect(choose).toHaveBeenCalledTimes(count);
  });
  it('moves by two rows per vertical key once the sidebar is wide enough for two columns', () => {
    const { fixture, root, divider } = render();
    fixture.componentRef.setInput('photos', Array.from({ length: 4 }, (_, index) => makePhoto({ path: `/p${index}.jpg` })));
    divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }));
    fixture.detectChanges();
    expect(root.querySelector<HTMLElement>('.grid')!.style.gridTemplateColumns).toContain('repeat(2,');
    const buttons = [...root.querySelectorAll<HTMLButtonElement>('.grid button')];
    const choose = vi.fn(); fixture.componentInstance.choose.subscribe(choose);
    buttons[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    expect(choose).toHaveBeenLastCalledWith('/p2.jpg');
    buttons[3].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true, cancelable: true }));
    expect(choose).toHaveBeenLastCalledWith('/p1.jpg');
  });
  it('bounds the rendered list while keeping later and earlier loaded photos accessible', () => {
    const { fixture, root } = render();
    const photos = Array.from({ length: 500 }, (_, index) => makePhoto({ path: `/p${index}.jpg`, filename: `p${index}.jpg` }));
    fixture.componentRef.setInput('photos', photos); fixture.componentRef.setInput('currentPath', '/p350.jpg'); fixture.detectChanges();
    expect(root.querySelectorAll('.grid button')).toHaveLength(200);
    expect(root.querySelector('[aria-current="true"]')?.getAttribute('aria-label')).toBe('p350.jpg');
    expect(root.querySelector('[data-collection-previous-window]')).not.toBeNull();
    root.querySelector<HTMLButtonElement>('[data-collection-next-window]')!.click(); fixture.detectChanges();
    expect(root.querySelectorAll('.grid button').length).toBeLessThanOrEqual(200);
    expect(root.querySelector('[aria-label="p499.jpg"]')).not.toBeNull();
    fixture.componentRef.setInput('photos', photos.map(photo => ({ ...photo, is_favorite: true }))); fixture.detectChanges();
    expect(root.querySelector('[aria-label="p499.jpg"]')).not.toBeNull();
    root.querySelector<HTMLButtonElement>('[data-collection-previous-window]')!.click(); fixture.detectChanges();
    expect(root.querySelector('[aria-label="p350.jpg"]')).not.toBeNull();
    fixture.componentRef.setInput('currentPath', '/p0.jpg'); fixture.detectChanges();
    expect(root.querySelector('[aria-current="true"]')?.getAttribute('aria-label')).toBe('p0.jpg');
  });
  it('resizes by keyboard within bounds without leaking photo navigation keys', () => {
    const { fixture, root, divider } = render();
    const key = (value: string) => { const event = new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true }); divider().dispatchEvent(event); fixture.detectChanges(); return event; };
    expect(key('End').defaultPrevented).toBe(true);
    expect(root.style.width).toBe('384px');
    expect(root.querySelector('.grid')?.getAttribute('style')).toContain('repeat(2');
    key('ArrowRight'); expect(root.style.width).toBe('384px');
    key('Home'); expect(root.style.width).toBe('144px');
    key('ArrowLeft'); expect(root.style.width).toBe('144px');
    expect(key('Escape').defaultPrevented).toBe(false);
  });
  it('cancels pointer resizing and ignores a second pointer', () => {
    const { fixture, root, divider } = render();
    const pointer = (type: string, x: number, id = 1) => { divider().dispatchEvent(new PointerEvent(type, { clientX: x, pointerId: id, isPrimary: true, bubbles: true })); fixture.detectChanges(); };
    flush();
    pointer('pointerdown', 100); pointer('pointermove', 200, 2); expect(root.style.width).toBe('192px');
    pointer('pointermove', 200); flush(); fixture.detectChanges(); expect(root.style.width).toBe('292px');
    pointer('pointercancel', 200); expect(root.style.width).toBe('192px');
  });
  it('commits the latest pending pointer width on release', () => {
    const { fixture, root, divider } = render();
    const pointer = (type: string, x: number) => { divider().dispatchEvent(new PointerEvent(type, { clientX: x, pointerId: 1, isPrimary: true, bubbles: true })); fixture.detectChanges(); };
    flush(); pointer('pointerdown', 100); pointer('pointermove', 150); pointer('pointermove', 170);
    expect(root.style.width).toBe('192px');
    pointer('pointerup', 170); expect(root.style.width).toBe('262px');
    flush(); fixture.detectChanges(); expect(root.style.width).toBe('262px');
  });

  it.each(['lostpointercapture', 'Escape'])('restores the starting width after %s during a drag', kind => {
    const { fixture, root, divider } = render(); flush();
    divider().dispatchEvent(new PointerEvent('pointerdown', { clientX: 100, pointerId: 1, isPrimary: true, bubbles: true }));
    divider().dispatchEvent(new PointerEvent('pointermove', { clientX: 180, pointerId: 1, isPrimary: true, bubbles: true }));
    flush(); fixture.detectChanges(); expect(root.style.width).toBe('272px');
    if (kind === 'Escape') divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    else divider().dispatchEvent(new PointerEvent(kind, { pointerId: 1, bubbles: true }));
    fixture.detectChanges(); expect(root.style.width).toBe('192px');
    flush(); fixture.detectChanges(); expect(root.style.width).toBe('192px');
  });

  describe('remembered width', () => {
    const KEY = 'facet_collection_sidebar_width';
    it('restores the stored width, clamped, and ignores garbage', () => {
      localStorage.setItem(KEY, '300');
      expect(render().root.style.width).toBe('300px');
      TestBed.resetTestingModule();
      localStorage.setItem(KEY, '9999');
      TestBed.configureTestingModule({ imports: [PhotoCollectionSidebarComponent], providers: [
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      ] });
      expect(render().root.style.width).toBe('384px');
      TestBed.resetTestingModule();
      localStorage.setItem(KEY, 'wide');
      TestBed.configureTestingModule({ imports: [PhotoCollectionSidebarComponent], providers: [
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      ] });
      expect(render().root.style.width).toBe('192px');
    });
    it('saves a committed keyboard or pointer resize but not a cancelled drag', () => {
      const { fixture, divider } = render(); flush();
      divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
      fixture.detectChanges();
      expect(localStorage.getItem(KEY)).toBe('208');
      const pointer = (type: string, x: number) => { divider().dispatchEvent(new PointerEvent(type, { clientX: x, pointerId: 1, isPrimary: true, bubbles: true })); fixture.detectChanges(); };
      pointer('pointerdown', 100); pointer('pointermove', 150); flush(); pointer('pointercancel', 150);
      expect(localStorage.getItem(KEY)).toBe('208');
      pointer('pointerdown', 100); pointer('pointermove', 140); pointer('pointerup', 140);
      expect(localStorage.getItem(KEY)).toBe('248');
    });
  });

  it('disables loading more while a page is pending', () => {
    const { fixture, root } = render(); const more = vi.fn(); fixture.componentInstance.more.subscribe(more);
    fixture.componentRef.setInput('loading', true); fixture.detectChanges();
    const button = root.querySelector<HTMLButtonElement>('div[tabindex] > button')!;
    expect(button.disabled).toBe(true); button.click(); expect(more).not.toHaveBeenCalled();
  });
  it('scrolls only its own collection viewport to reveal the current photo', () => {
    const { root } = render();
    const viewport = root.querySelector<HTMLElement>('div[tabindex]')!;
    const active = root.querySelector<HTMLElement>('[data-collection-current]')!;
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ top: 10, bottom: 110 } as DOMRect);
    vi.spyOn(active, 'getBoundingClientRect').mockReturnValue({ top: 130, bottom: 180 } as DOMRect);
    flush(); expect(viewport.scrollTop).toBe(70);
  });
  it('collapses without losing the current-photo input and releases scheduled work on destroy', () => {
    const { fixture, root } = render();
    root.querySelector<HTMLButtonElement>('button')!.click(); fixture.detectChanges();
    expect(root.style.width).toBe('52px'); expect(root.querySelector('[role="separator"]')).toBeNull();
    expect(fixture.componentInstance.currentPath()).toBe('/b.jpg');
    fixture.destroy(); expect(frame).toBeUndefined();
  });
  it('reveals the unchanged current photo after column reflow and hidden-to-visible resize', () => {
    const { fixture, root, divider } = render();
    const viewport = root.querySelector<HTMLElement>('div[tabindex]')!;
    const active = root.querySelector<HTMLElement>('[data-collection-current]')!;
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ top: 10, bottom: 110 } as DOMRect);
    vi.spyOn(active, 'getBoundingClientRect').mockReturnValue({ top: 130, bottom: 180 } as DOMRect);
    flush(); expect(viewport.scrollTop).toBe(70);
    vi.mocked(active.getBoundingClientRect).mockReturnValue({ top: -50, bottom: 0 } as DOMRect);
    divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    fixture.detectChanges(); flush(); expect(viewport.scrollTop).toBe(10);
    vi.mocked(active.getBoundingClientRect).mockReturnValue({ top: 130, bottom: 180 } as DOMRect);
    resized(); flush(); expect(viewport.scrollTop).toBe(80);
  });

});
