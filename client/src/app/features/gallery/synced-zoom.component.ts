import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, inject, input, output, signal, viewChild } from '@angular/core';

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
 *
 * The same two measurements answer a second question the parent cannot: where
 * the photo actually is inside the pane. `object-contain` letterboxes it, so a
 * badge pinned to the pane's corner can land far off the image — published here
 * as `fitInsetX` / `fitInsetY` and as the `--fit-inset-x` / `--fit-inset-y`
 * custom properties, so chrome can trace the rendered image instead.
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
    '[style.--fit-inset-x.px]': 'fitInsetX()',
    '[style.--fit-inset-y.px]': 'fitInsetY()',
  },
  template: `
    <img #frame [src]="effectiveSrc()" [alt]="alt()"
         class="absolute inset-0 w-full h-full object-contain origin-center will-change-transform select-none"
         [style.transform]="transform()" draggable="false" (load)="onFrameLoad()" />
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
  private readonly destroyRef = inject(DestroyRef);

  private dragging = false;
  private lastX = 0;
  private lastY = 0;

  /** The pane's own box and the frame's natural size — the two halves of the
   *  letterbox math, as signals because the insets below are read on every
   *  change detection by whatever chrome traces the image. */
  private readonly paneSize = signal<{ w: number; h: number }>({ w: 0, h: 0 });
  private readonly naturalSize = signal<{ w: number; h: number }>({ w: 0, h: 0 });

  constructor() {
    // No ResizeObserver in a browser-less test env; the zero fallback below is
    // what a pane that has never been measured reports anyway.
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => this.measurePane());
    observer.observe(this.host.nativeElement);
    this.destroyRef.onDestroy(() => observer.disconnect());
  }

  /** Re-read the pane's rendered box. Driven by the ResizeObserver above, and
   *  public so a test can measure a pane the observer never fires for. */
  measurePane(): void {
    const { width, height } = this.host.nativeElement.getBoundingClientRect();
    this.paneSize.set({ w: width, h: height });
  }

  protected onFrameLoad(): void {
    const img = this.frame()?.nativeElement;
    if (!img) return;
    this.naturalSize.set({ w: img.naturalWidth, h: img.naturalHeight });
    this.measurePane();
  }

  /**
   * Half the letterbox bar on each axis, in CSS pixels: where the rendered
   * photo starts inside the pane.
   *
   * `object-contain` centres the frame, so the leftover space is split evenly.
   * The shared zoom scale is folded in and the result floored at 0, so a pane
   * whose image has grown past its own box reports no inset and chrome anchored
   * to it sits at the pane corner — which is where the image edge then is.
   * Panning is deliberately ignored: at fit there is none, and past fit the
   * inset is already 0.
   */
  private readonly fitInset = computed(() => {
    const { w: paneW, h: paneH } = this.paneSize();
    const { w: naturalW, h: naturalH } = this.naturalSize();
    if (!paneW || !paneH || !naturalW || !naturalH) return { x: 0, y: 0 };
    const rendered = Math.min(paneW / naturalW, paneH / naturalH) * this.zoom().scale;
    return {
      x: Math.max(0, (paneW - naturalW * rendered) / 2),
      y: Math.max(0, (paneH - naturalH * rendered) / 2),
    };
  });

  readonly fitInsetX = computed(() => this.fitInset().x);
  readonly fitInsetY = computed(() => this.fitInset().y);

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
