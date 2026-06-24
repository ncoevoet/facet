import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

export interface ZoomState {
  scale: number;
  tx: number;
  ty: number;
}

export const FIT_ZOOM: ZoomState = { scale: 1, tx: 0, ty: 0 };

/**
 * One pane of a synced compare view. It is presentational: the pan/zoom
 * transform lives in a parent signal shared by every pane, so a gesture on any
 * pane updates them all in lockstep (the whole point of side-by-side pixel
 * peeking). Past the fit scale a pane lazily swaps to a full-resolution source
 * so 1:1 inspection is crisp.
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
    <img [src]="effectiveSrc()" [alt]="alt()"
         class="absolute inset-0 w-full h-full object-contain origin-center will-change-transform select-none"
         [style.transform]="transform()" draggable="false" />
  `,
})
export class SyncedZoomComponent {
  readonly src = input.required<string>();
  readonly fullResSrc = input<string | null>(null);
  readonly zoom = input.required<ZoomState>();
  readonly alt = input('');
  readonly zoomChange = output<ZoomState>();

  static readonly MIN_SCALE = 1;
  static readonly MAX_SCALE = 8;

  private dragging = false;
  private lastX = 0;
  private lastY = 0;

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

  protected onWheel(event: WheelEvent): void {
    event.preventDefault();
    const z = this.zoom();
    const scale = this.clampScale(z.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15));
    this.zoomChange.emit(scale === SyncedZoomComponent.MIN_SCALE ? { ...FIT_ZOOM } : { ...z, scale });
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
    const z = this.zoom();
    this.zoomChange.emit({ scale: z.scale, tx: z.tx + (event.clientX - this.lastX), ty: z.ty + (event.clientY - this.lastY) });
    this.lastX = event.clientX;
    this.lastY = event.clientY;
  }

  protected onPointerUp(): void {
    this.dragging = false;
  }

  protected onDoubleClick(): void {
    this.zoomChange.emit(this.zoom().scale > SyncedZoomComponent.MIN_SCALE ? { ...FIT_ZOOM } : { scale: 2, tx: 0, ty: 0 });
  }
}
