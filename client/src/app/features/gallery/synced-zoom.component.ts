import { ChangeDetectionStrategy, Component, ElementRef, computed, inject, input, output, viewChild } from '@angular/core';

export interface ZoomState {
  scale: number;
  tx: number;
  ty: number;
}

export const FIT_ZOOM: ZoomState = { scale: 1, tx: 0, ty: 0 };

/** Largest side-by-side grid the panes stay readable in. Lives here rather than
 *  in the compare dialog so a caller can enforce the bound without eagerly
 *  importing that lazily-loaded dialog. */
export const MAX_COMPARE_PANES = 4;

/**
 * One pane of a synced compare view. It is presentational: the pan/zoom
 * transform lives in a parent signal shared by every pane, so a gesture on any
 * pane updates them all in lockstep (the whole point of side-by-side pixel
 * peeking). Past the fit scale a pane lazily swaps to a full-resolution source
 * so 1:1 inspection is crisp.
 *
 * Zooming in lands on `focusPoint` — the frame's key subject — rather than on
 * its geometric centre, so a 1:1 peek starts on the face or subject that
 * matters. The pane owns that math because `ZoomState.tx/ty` are pixels and
 * only the pane knows its own rect and its image's natural size.
 */
@Component({
  selector: 'app-synced-zoom',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'block relative overflow-hidden bg-black',
    '(wheel)': 'onWheel($event)',
    '(pointerdown)': 'onPointerDown($event)',
    '(pointermove)': 'onPointerMove($event)',
    '(pointerup)': 'onPointerUp()',
    '(pointercancel)': 'onPointerUp()',
    '(dblclick)': 'onDoubleClick()',
  },
  template: `
    <img #frame [src]="effectiveSrc()" [alt]="alt()"
         class="absolute inset-0 w-full h-full object-contain origin-center will-change-transform select-none"
         [style.transform]="transform()" draggable="false" />
  `,
})
export class SyncedZoomComponent {
  readonly src = input.required<string>();
  readonly fullResSrc = input<string | null>(null);
  readonly zoom = input.required<ZoomState>();
  readonly alt = input('');
  /** Normalized [cx, cy] of what this frame is about, to centre on when zooming
   *  in past fit; null keeps the frame's own centre. */
  readonly focusPoint = input<[number, number] | null>(null);
  readonly zoomChange = output<ZoomState>();

  static readonly MIN_SCALE = 1;
  static readonly MAX_SCALE = 8;
  /** The scale a double-click (or the darkroom's Z key) lands on. */
  static readonly TOGGLE_SCALE = 2;

  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly frame = viewChild<ElementRef<HTMLImageElement>>('frame');

  private dragging = false;
  private lastX = 0;
  private lastY = 0;

  /** The source the user has already framed by hand. While it matches the
   *  current frame the focus point stands down: a suggested centre must never
   *  re-frame a crop the user chose themselves. Latched on the first manual
   *  pan or zoom step, and implicitly released when the frame changes, so the
   *  next photo still gets its own suggestion. */
  private manuallyFramedSrc: string | null = null;

  protected readonly transform = computed(() => {
    const z = this.zoom();
    return `translate(${z.tx}px, ${z.ty}px) scale(${z.scale})`;
  });

  protected readonly effectiveSrc = computed(() => {
    const full = this.fullResSrc();
    // Past the fit scale the 1920px thumbnail is too soft to judge sharpness;
    // swap to the full-res source for the actual pixel peek.
    return this.zoom().scale > SyncedZoomComponent.MIN_SCALE && full ? full : this.src();
  });

  private clampScale(scale: number): number {
    return Math.max(SyncedZoomComponent.MIN_SCALE, Math.min(SyncedZoomComponent.MAX_SCALE, scale));
  }

  private markManuallyFramed(): void {
    this.manuallyFramedSrc = this.src();
  }

  /**
   * Pixel translate that lands the focus point on the pane centre at `scale`.
   *
   * The image fills the host, is `object-contain` and has `origin-center`, so
   * the transform origin IS the pane centre and a point at normalized (cx, cy)
   * sits `(cx - 0.5) * w * fit` px from it, where `fit` is the contain scale.
   * The transform then multiplies that offset by `scale`, hence the sign and
   * the factor below.
   *
   * Falls back to a centred zoom — the behaviour before focus points existed —
   * whenever the answer cannot be trusted: no focus point, a frame the user has
   * already framed by hand, an image that has not loaded (`naturalWidth === 0`,
   * which is also every frame in a browser-less test), or a pane with no size.
   * Measured here, inside the handler, rather than in an effect: the pane swaps
   * to its full-resolution source the moment the zoom lands.
   */
  private translateForFocus(scale: number): { tx: number; ty: number } {
    const focus = this.focusPoint();
    const img = this.frame()?.nativeElement;
    if (!focus || !img || this.manuallyFramedSrc === this.src()) return { tx: 0, ty: 0 };
    const { naturalWidth, naturalHeight } = img;
    const { width, height } = this.host.nativeElement.getBoundingClientRect();
    if (!naturalWidth || !naturalHeight || !width || !height) return { tx: 0, ty: 0 };
    const fit = Math.min(width / naturalWidth, height / naturalHeight);
    return {
      tx: -scale * (focus[0] - 0.5) * naturalWidth * fit,
      ty: -scale * (focus[1] - 0.5) * naturalHeight * fit,
    };
  }

  protected onWheel(event: WheelEvent): void {
    event.preventDefault();
    const z = this.zoom();
    const scale = this.clampScale(z.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15));
    if (scale === SyncedZoomComponent.MIN_SCALE) {
      this.zoomChange.emit({ ...FIT_ZOOM });
      return;
    }
    // Only the fit -> zoomed step re-frames. A step taken while already zoomed
    // is the user driving, so it keeps panning from the crop they are on.
    if (z.scale === SyncedZoomComponent.MIN_SCALE) {
      this.zoomChange.emit({ scale, ...this.translateForFocus(scale) });
      return;
    }
    this.markManuallyFramed();
    this.zoomChange.emit({ ...z, scale });
  }

  protected onPointerDown(event: PointerEvent): void {
    if (this.zoom().scale <= SyncedZoomComponent.MIN_SCALE) return;
    this.dragging = true;
    this.lastX = event.clientX;
    this.lastY = event.clientY;
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  protected onPointerMove(event: PointerEvent): void {
    if (!this.dragging) return;
    this.markManuallyFramed();
    const z = this.zoom();
    this.zoomChange.emit({ scale: z.scale, tx: z.tx + (event.clientX - this.lastX), ty: z.ty + (event.clientY - this.lastY) });
    this.lastX = event.clientX;
    this.lastY = event.clientY;
  }

  protected onPointerUp(): void {
    this.dragging = false;
  }

  /** Toggle fit <-> TOGGLE_SCALE, zooming in on the focus point. Public so the
   *  darkroom's Z key runs this very math instead of duplicating it. */
  toggleZoom(): void {
    const scale = SyncedZoomComponent.TOGGLE_SCALE;
    this.zoomChange.emit(this.zoom().scale > SyncedZoomComponent.MIN_SCALE
      ? { ...FIT_ZOOM }
      : { scale, ...this.translateForFocus(scale) });
  }

  protected onDoubleClick(): void {
    this.toggleZoom();
  }
}
