import { DestroyRef, Directive, ElementRef, computed, effect, inject, input, signal, untracked } from '@angular/core';

const MIN_SCALE = 0.5;
const MAX_SCALE = 5;
const WHEEL_STEP = 0.15;

/**
 * Wheel / pinch zoom and drag-to-pan for an image panel; double-click resets.
 * The host is the panel, and the images inside bind `[style.transform]` to
 * `transform()` through the `zoomPan` export. A change of the optional
 * `appZoomPan` value resets the view, for a panel whose image is swapped
 * in place.
 */
@Directive({
  selector: '[appZoomPan]',
  exportAs: 'zoomPan',
  host: {
    '[class.cursor-grabbing]': 'isPanning()',
    '(dblclick)': 'reset()',
    '(keydown)': 'onKeydown($event)',
    '(pointerdown)': 'onPanStart($event)',
    '(pointermove)': 'onPanMove($event)',
    '(pointerup)': 'onPanEnd($event)',
    '(pointercancel)': 'onPanEnd($event)',
    '(touchstart)': 'onTouchStart($event)',
    '(touchend)': 'onTouchEnd()',
  },
})
export class ZoomPanDirective {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly resetKey = input<unknown>(undefined, { alias: 'appZoomPan' });

  readonly maximumScale = MAX_SCALE;
  readonly scale = signal(1);
  readonly panX = signal(0);
  readonly panY = signal(0);
  readonly isPanning = signal(false);
  readonly transform = computed(() => {
    const s = this.scale();
    const x = this.panX();
    const y = this.panY();
    return s === 1 && x === 0 && y === 0 ? '' : `scale(${s}) translate(${x}px, ${y}px)`;
  });
  private panStartX = 0;
  private panStartY = 0;
  private panOriginX = 0;
  private panOriginY = 0;
  private lastPinchDist = 0;

  constructor() {
    // Non-passive, so preventDefault() keeps the page from scrolling or zooming.
    const el = this.host.nativeElement;
    const wheelHandler = (e: WheelEvent) => this.onWheel(e);
    const touchMoveHandler = (e: TouchEvent) => this.onTouchMove(e);
    el.addEventListener('wheel', wheelHandler, { passive: false });
    el.addEventListener('touchmove', touchMoveHandler, { passive: false });
    inject(DestroyRef).onDestroy(() => {
      el.removeEventListener('wheel', wheelHandler);
      el.removeEventListener('touchmove', touchMoveHandler);
    });
    effect(() => {
      this.resetKey();
      untracked(() => this.reset());
    });
  }

  zoomStep(direction: number): void {
    this.applyZoom(this.scale() + direction * 0.25);
  }

  reset(): void {
    this.isPanning.set(false);
    this.lastPinchDist = 0;
    this.scale.set(1);
    this.panX.set(0);
    this.panY.set(0);
  }

  private applyZoom(raw: number): void {
    const clamped = Math.min(MAX_SCALE, Math.max(MIN_SCALE, raw));
    if (clamped <= 1) { this.panX.set(0); this.panY.set(0); }
    this.scale.set(clamped);
  }

  private onWheel(e: WheelEvent): void {
    e.preventDefault();
    this.applyZoom(this.scale() + (e.deltaY > 0 ? -WHEEL_STEP : WHEEL_STEP));
  }

  /** Only the focused canvas owns these keys; nested navigation buttons keep theirs. */
  protected onKeydown(event: KeyboardEvent): void {
    if (event.target !== this.host.nativeElement || event.defaultPrevented
      || event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
    if (event.key === 'Home') {
      this.reset();
    } else if (event.key === '+' || event.key === '=' || event.key === '-') {
      this.applyZoom(Math.max(1, this.scale() + (event.key === '-' ? -0.25 : 0.25)));
    } else {
      if (this.scale() <= 1) return;
      const step = 40 / this.scale();
      const directions: Record<string, [number, number]> = {
        ArrowLeft: [step, 0], ArrowRight: [-step, 0],
        ArrowUp: [0, step], ArrowDown: [0, -step],
      };
      const delta = directions[event.key];
      if (!delta) return;
      this.applyPan(this.panX() + delta[0], this.panY() + delta[1]);
    }
    event.preventDefault();
    event.stopPropagation();
  }

  private applyPan(x: number, y: number): void {
    const el = this.host.nativeElement;
    const limit = Math.max(el.clientWidth, el.clientHeight) / (2 * this.scale());
    this.panX.set(Math.max(-limit, Math.min(limit, x)));
    this.panY.set(Math.max(-limit, Math.min(limit, y)));
  }

  protected onPanStart(e: PointerEvent): void {
    if (this.scale() <= 1) return;
    this.isPanning.set(true);
    this.panStartX = e.clientX;
    this.panStartY = e.clientY;
    this.panOriginX = this.panX();
    this.panOriginY = this.panY();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }

  protected onPanMove(e: PointerEvent): void {
    if (!this.isPanning()) return;
    const scale = this.scale();
    const rawX = this.panOriginX + (e.clientX - this.panStartX) / scale;
    const rawY = this.panOriginY + (e.clientY - this.panStartY) / scale;
    // Pointer and keyboard panning share the same bounds.
    this.applyPan(rawX, rawY);
  }

  protected onPanEnd(e: PointerEvent): void {
    if (!this.isPanning()) return;
    this.isPanning.set(false);
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
  }

  protected onTouchStart(e: TouchEvent): void {
    if (e.touches.length === 2) {
      this.lastPinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
    }
  }

  private onTouchMove(e: TouchEvent): void {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
      if (this.lastPinchDist > 0) {
        this.applyZoom(this.scale() * (dist / this.lastPinchDist));
      }
      this.lastPinchDist = dist;
    }
  }

  protected onTouchEnd(): void {
    this.lastPinchDist = 0;
  }
}
