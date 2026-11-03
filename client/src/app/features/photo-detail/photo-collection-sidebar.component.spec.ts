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
  afterEach(() => { TestBed.resetTestingModule(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
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
    expect(root.style.width).toBe('40px'); expect(root.querySelector('[role="separator"]')).toBeNull();
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
