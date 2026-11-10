import { DestroyRef, Directive, ElementRef, effect, inject, input } from '@angular/core';

export const TOOLBAR_POSITION_EVENT = 'toolbarpositionchange';
/** Below this width the bar is a full-width mobile strip: no offset is applied or saved. */
const MIN_MOVABLE_WIDTH = 768;
const STORAGE_PREFIX = 'facet_selection_bar:';
interface Position { x: number; up: number }
interface Drag { id: number; owner: string; x: number; y: number; offset: Position; before: Position }

/** Moves only through an explicit handle; action buttons retain their normal behavior. */
@Directive({
  selector: '[appMovableToolbar]',
  host: {
    '(pointerdown)': 'start($event)', '(pointermove)': 'move($event)',
    '(pointerup)': 'end($event)', '(pointercancel)': 'cancel($event)',
    '(lostpointercapture)': 'cancel($event)', '(keydown)': 'key($event)', '(window:resize)': 'schedule()',
  },
})
export class MovableToolbarDirective {
  readonly toolbarBoundary = input<HTMLElement | null>(null);
  readonly toolbarRightInset = input(8);
  readonly toolbarOwner = input('');
  private readonly element = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  private position: Position = { x: 0, up: 0 };
  private offset: Position = { x: 0, up: 0 };
  private drag: Drag | null = null;
  private owner: string | null = null;
  private frame: number | null = null;

  constructor() {
    effect(cleanup => {
      const owner = this.toolbarOwner();
      const boundary = this.toolbarBoundary();
      this.toolbarRightInset();
      if (owner !== this.owner) {
        this.finish(false);
        this.owner = owner;
        this.position = this.load(owner);
      }
      this.schedule();
      if (typeof ResizeObserver !== 'undefined') {
        const observer = new ResizeObserver(() => this.schedule());
        observer.observe(this.element);
        if (boundary) observer.observe(boundary);
        cleanup(() => observer.disconnect());
      }
    });
    inject(DestroyRef).onDestroy(() => {
      this.finish(false);
      if (this.frame !== null) cancelAnimationFrame(this.frame);
    });
  }

  private load(owner: string): Position {
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_PREFIX + owner) ?? 'null');
      if (saved && typeof saved === 'object' && 'x' in saved && 'up' in saved
        && typeof saved.x === 'number' && typeof saved.up === 'number'
        && Number.isFinite(saved.x) && Number.isFinite(saved.up)
        && saved.x >= 0 && saved.x <= 1 && saved.up >= 0 && saved.up <= 1) return { x: saved.x, up: saved.up };
    } catch { /* Disabled or invalid browser storage keeps the default position. */ }
    return { x: 0, up: 0 };
  }

  private limits(): Position {
    const boundary = this.toolbarBoundary() ?? this.element.parentElement;
    if (!boundary) return { x: 0, up: 0 };
    const area = boundary.getBoundingClientRect();
    const bar = this.element.getBoundingClientRect();
    return {
      x: Math.max(0, area.right - this.toolbarRightInset() - (bar.right - this.offset.x)),
      up: Math.max(0, bar.top + this.offset.up - area.top - 8),
    };
  }

  private movable(): boolean {
    return window.innerWidth >= MIN_MOVABLE_WIDTH;
  }

  schedule(): void {
    if (this.frame !== null) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      const limits = this.limits();
      this.offset = this.movable() ? { x: this.position.x * limits.x, up: this.position.up * limits.up } : { x: 0, up: 0 };
      this.element.style.transform = `translate3d(${this.offset.x}px, ${-this.offset.up}px, 0)`;
      this.placePanels();
      this.element.dispatchEvent(new Event(TOOLBAR_POSITION_EVENT));
    });
  }

  /** Disclosures open into the larger available space, outside the bar itself. */
  private placePanels(): void {
    const boundary = this.toolbarBoundary() ?? this.element.parentElement;
    if (!boundary) return;
    const area = boundary.getBoundingClientRect();
    const bar = this.element.getBoundingClientRect();
    const above = Math.max(0, bar.top - area.top - 20);
    const below = Math.max(0, area.bottom - bar.bottom - 20);
    const down = below > above;
    this.element.dataset['toolbarDown'] = String(down);
    for (const panel of this.element.querySelectorAll<HTMLElement>('[data-toolbar-panel]')) {
      panel.style.maxHeight = `${down ? below : above}px`;
    }
  }

  private place(x: number, up: number): void {
    const limits = this.limits();
    this.position = { x: limits.x ? Math.max(0, Math.min(1, x / limits.x)) : 0,
      up: limits.up ? Math.max(0, Math.min(1, up / limits.up)) : 0 };
    this.schedule();
  }

  private handle(event: Event): HTMLElement | null {
    const handle = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-toolbar-drag-handle]') : null;
    return handle && this.element.contains(handle) ? handle : null;
  }

  start(event: PointerEvent): void {
    const handle = this.handle(event);
    if (!handle || !this.movable() || this.drag || event.button !== 0 || !event.isPrimary) return;
    handle.focus({ preventScroll: true });
    event.preventDefault(); event.stopPropagation();
    const limits = this.limits();
    this.drag = { id: event.pointerId, owner: this.toolbarOwner(), x: event.clientX, y: event.clientY,
      offset: { x: this.position.x * limits.x, up: this.position.up * limits.up }, before: { ...this.position } };
    try { this.element.setPointerCapture(event.pointerId); } catch { /* Synthetic pointers have no capture target. */ }
  }

  move(event: PointerEvent): void {
    if (!this.drag || event.pointerId !== this.drag.id) return;
    event.preventDefault(); event.stopPropagation();
    this.place(this.drag.offset.x + event.clientX - this.drag.x, this.drag.offset.up - event.clientY + this.drag.y);
  }

  end(event: PointerEvent): void {
    if (this.drag?.id === event.pointerId) this.finish(true);
  }

  cancel(event: PointerEvent): void {
    if (this.drag?.id === event.pointerId) this.finish(false);
  }

  private finish(save: boolean): void {
    const drag = this.drag;
    if (!drag) return;
    this.drag = null;
    if (!save) { this.position = drag.before; this.schedule(); }
    else if (drag.owner === this.toolbarOwner()) this.persist();
    try { this.element.releasePointerCapture(drag.id); } catch { /* Already released by the browser. */ }
  }

  private persist(): void {
    try { localStorage.setItem(STORAGE_PREFIX + this.toolbarOwner(), JSON.stringify(this.position)); } catch { /* Optional preference. */ }
  }

  key(event: KeyboardEvent): void {
    if (!this.handle(event) || !this.movable()) return;
    if (event.key === 'Escape' && this.drag) {
      event.preventDefault(); event.stopPropagation(); this.finish(false); return;
    }
    const step = event.shiftKey ? 48 : 16;
    const directions: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    if (event.key !== 'Home' && !directions[event.key]) return;
    event.preventDefault(); event.stopPropagation();
    if (this.drag) this.finish(false);
    if (event.key === 'Home') this.position = { x: 0, up: 0 };
    else {
      const [x, up] = directions[event.key];
      const limits = this.limits();
      this.place(this.position.x * limits.x + x, this.position.up * limits.up + up);
    }
    this.schedule(); this.persist();
  }
}
