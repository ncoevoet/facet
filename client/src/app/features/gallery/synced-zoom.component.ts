import { ChangeDetectionStrategy, Component, afterRenderEffect, DestroyRef, ElementRef, computed, effect, inject, input, output, signal, untracked, viewChild } from '@angular/core';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { normalizedInspectionBox } from './comparison-inspection.util';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

export interface ZoomState {
  scale: number;
  tx: number;
  ty: number;
}

export interface DisplayedRendition {
  kind: 'thumbnail' | 'preview' | 'source';
  phase: 'loading' | 'ready' | 'failed';
  width?: number;
  height?: number;
}

export const FIT_ZOOM: ZoomState = { scale: 1, tx: 0, ty: 0 };

/** Largest side-by-side grid the panes stay readable in. Lives here rather than
 *  in the compare dialog so a caller can enforce the bound without eagerly
 *  importing that lazily-loaded dialog. */

/** How long a frame must stay current before its sharp render is requested, so
 *  a held arrow key does not queue one render per frame it passes. */
export const SHARP_PRELOAD_DEBOUNCE_MS = 150;

/** Sources already fetched into the browser cache, bounded so a long session
 *  does not grow it without limit. A pane consults it to skip the debounce for
 *  a render that may still be cached. The preloader verifies it before promotion. */
export class LoadedSources {
  static readonly MAX = 64;
  private readonly urls = new Set<string>();

  has(url: string): boolean {
    return this.urls.has(url);
  }

  add(url: string): void {
    this.urls.delete(url);
    this.urls.add(url);
    if (this.urls.size > LoadedSources.MAX) {
      const oldest = this.urls.values().next().value;
      if (oldest !== undefined) this.urls.delete(oldest);
    }
  }
}

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
 *
 * Progressive load: with `placeholderSrc` set the pane shows that (cheap, usually
 * already cached) source first and swaps to `src` only once a preloader `Image`
 * has fetched it, so the sharp render never paints in progressively over the
 * stretched thumbnail. With `frameKey` set the pane stays `opacity-0` until the
 * image of the CURRENT frame has loaded, so a slow load shows the pane
 * background rather than the previous frame. Both are opt-in: left null, the
 * pane shows `src` as soon as the browser paints it.
 */
@Component({
  selector: 'app-synced-zoom',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LoupeDirective, TranslatePipe],
  host: {
    class: 'block relative overflow-hidden bg-black focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-white',
    '[class.touch-none]': 'keyboardInspection()',
    '[attr.tabindex]': 'keyboardInspection() ? 0 : null',
    role: 'group',
    '[attr.aria-label]': 'alt()',
    '(keydown)': 'onKeydown($event)',
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
         [class.opacity-0]="hidden()"
         [style.transform]="transform()" draggable="false" (load)="onFrameLoad()" (error)="onFrameError()"
         [appLoupe]="loupeSrc() ?? effectiveSrc()" [loupeActive]="loupeActive()"
         [loupeZoom]="loupeZoom()" loupeFit="contain" />
    @if (overview(); as area) {
      <div data-zoom-overview role="img" [attr.aria-label]="I18N.gallery.compare.zoom_overview | translate"
           class="pointer-events-none absolute bottom-3 right-3 overflow-hidden rounded border border-white/70 bg-black/70 shadow-lg"
           [style.width.px]="area.width" [style.height.px]="area.height">
        <img [src]="effectiveSrc()" alt="" class="h-full w-full object-fill" draggable="false" />
        <div data-zoom-viewport class="absolute border-2 border-red-500 bg-red-500/10 ring-1 ring-black/60"
             [style.left.%]="area.left" [style.top.%]="area.top"
             [style.width.%]="area.visibleWidth" [style.height.%]="area.visibleHeight"></div>
      </div>
    }
  `,
})
export class SyncedZoomComponent {
  protected readonly I18N = I18N;
  readonly src = input.required<string>();
  readonly fullResSrc = input<string | null>(null);
  readonly zoom = input.required<ZoomState>();
  readonly alt = input('');
  /** Normalized [cx, cy] of what this frame is about, to centre on when zooming
   *  in past fit; null keeps the frame's own centre. */
  readonly focusPoint = input<[number, number] | null>(null);
  readonly zoomChange = output<ZoomState>();
  readonly keyboardInspection = input(false);
  readonly fitRequested = output<void>();

  /** Shown until `src` has been fetched by a preloader; null disables the
   *  progressive load entirely (no `Image` is ever constructed). */
  readonly placeholderSrc = input<string | null>(null);
  /** Identity of the frame (its photo path). While set, the pane is hidden until
   *  the image of the current frame has loaded. A source change inside one frame
   *  (placeholder to render, render to full-res) never hides it again. */
  readonly frameKey = input<string | null>(null);
  /** Sources known to be in the browser cache already; skips the debounce. */
  readonly loadedSources = input<LoadedSources | null>(null);
  /** Emits `src` once the preloader has fetched it and the pane swapped to it. */
  readonly sharpLoaded = output<string>();
  /** Starts each progressive attempt, including revisits of the same URL. */
  readonly sharpPending = output<string>();
  /** The render failed; the pane keeps its stored thumbnail. */
  readonly sharpFailed = output<string>();
  /** Actual displayed image state, independent of the background preview preload. */
  readonly renditionChange = output<DisplayedRendition>();

  /** Hover loupe over this pane. `loupeSrc` defaults to the pane's own
   *  effective source (so a caller need not track full-res separately);
   *  the darkroom passes the full-resolution URL explicitly per the spec —
   *  magnify from full-res even while the pane itself is still showing the
   *  thumbnail. `loupeActive` is the caller's combined "toggle on AND not
   *  zoomed past fit" boolean — this component has no opinion on either. */
  readonly loupeSrc = input<string | null>(null);
  readonly loupeActive = input(false);
  readonly loupeZoom = input(3);

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

  protected readonly overview = computed(() => {
    const z = this.zoom();
    const { w, h } = this.paneSize();
    const { w: iw, h: ih } = this.naturalSize();
    if (this.hidden() || z.scale <= 1 || !w || !h || !iw || !ih || ![z.scale, z.tx, z.ty].every(Number.isFinite)) return null;
    const fit = this.containFitScale(w, h, iw, ih);
    const width = iw * fit * z.scale;
    const height = ih * fit * z.scale;
    const x = (w - width) / 2 + z.tx;
    const y = (h - height) / 2 + z.ty;
    const percent = (value: number) => Math.max(0, Math.min(100, value * 100));
    const left = percent(-x / width);
    const top = percent(-y / height);
    const miniature = Math.min(112 / iw, 80 / ih, w / 4 / iw, h / 4 / ih);
    return { width: iw * miniature, height: ih * miniature, left, top,
      visibleWidth: percent((w - x) / width) - left,
      visibleHeight: percent((h - y) / height) - top };
  });

  /** The `src` whose preload has finished; the pane shows the placeholder until
   *  it equals the current `src`. */
  private readonly readySrc = signal<string | null>(null);
  private readonly retryState = signal<{ frameKey: string | null; src: string; attempt: number } | null>(null);
  private readonly retrySession = crypto.randomUUID();
  private readonly requestedPreview = computed(() => this.retryUrl(this.src()));
  /** The frame whose own image last finished loading in this pane. */
  private readonly paintedKey = signal<string | null>(null);

  protected readonly hidden = computed(() => {
    const key = this.frameKey();
    return key !== null && this.paintedKey() !== key;
  });

  constructor() {
    effect(onCleanup => {
      const src = this.requestedPreview();
      // Read for its dependency only: re-run the preload on a frame change even when src is unchanged.
      this.frameKey();
      if (!this.placeholderSrc()) return;
      untracked(() => {
        const loaded = this.loadedSources();
        this.sharpPending.emit(src);
        this.readySrc.set(null);
        let active = true;
        let img: HTMLImageElement | null = null;
        const preload = () => {
          const preloader = new Image();
          img = preloader;
          let settled = false;
          // A cache hint skips the debounce, never the browser's load check.
          preloader.onload = () => {
            if (!active || settled || this.requestedPreview() !== src) return;
            settled = true;
            loaded?.add(src);
            this.readySrc.set(src);
            this.sharpLoaded.emit(src);
          };
          preloader.onerror = () => {
            if (!active || settled || this.requestedPreview() !== src) return;
            settled = true;
            this.sharpFailed.emit(src);
          };
          preloader.src = src;
          if (preloader.complete && preloader.naturalWidth > 0) preloader.onload(new Event('load'));
        };
        const timer = loaded?.has(src) ? null : setTimeout(preload, SHARP_PRELOAD_DEBOUNCE_MS);
        if (timer === null) preload();
        onCleanup(() => {
          active = false;
          if (timer !== null) clearTimeout(timer);
          if (img) {
            img.onload = null;
            img.onerror = null;
            img.src = '';
          }
        });
      });
    });
    effect(() => {
      this.effectiveSrc();
      this.frameKey();
      this.renditionChange.emit({ kind: this.displayedKind(), phase: 'loading' });
    });
    // A step onto an image the browser already holds (memory cache) has it
    // complete as soon as the new `src` is applied, but its `load` event only
    // fires later, which would keep the pane `opacity-0` for a frame or two.
    // After the render that applied `src`, read the element: when it is
    // complete, decoded and resolved to the CURRENT effective URL, those pixels
    // are the new frame's, so mark it painted now. The URL match is what keeps
    // the previous frame's pixels from ever showing under the new key.
    afterRenderEffect(() => {
      const key = this.frameKey();
      const src = this.effectiveSrc();
      const img = this.frame()?.nativeElement;
      if (key === null || !img) return;
      untracked(() => {
        if (img.complete && img.naturalWidth > 0 && img.currentSrc === new URL(src, document.baseURI).href) {
          this.paintedKey.set(key);
          this.renditionChange.emit({ kind: this.displayedKind(), phase: 'ready', width: img.naturalWidth, height: img.naturalHeight });
        }
      });
    });
    // No ResizeObserver in a browser-less test env; the zero fallback below is
    // what a pane that has never been measured reports anyway.
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => this.measurePane());
    observer.observe(this.host.nativeElement);
    this.destroyRef.onDestroy(() => observer.disconnect());
  }

  /** Re-read both halves of the letterbox geometry: the pane's rendered box
   *  and the frame's natural size. Driven by the ResizeObserver above and the
   *  frame's own `load` event below, and public so a caller that needs a
   *  guaranteed-fresh reading — a zoom handler mid-gesture, or a test the
   *  observer never fires for — can trigger it directly. */
  measurePane(): void {
    const { width, height } = this.host.nativeElement.getBoundingClientRect();
    this.paneSize.set({ w: width, h: height });
    const img = this.frame()?.nativeElement;
    if (img) this.naturalSize.set({ w: img.naturalWidth, h: img.naturalHeight });
  }

  protected onFrameLoad(): void {
    this.measurePane();
    const img = this.frame()?.nativeElement;
    // A `load` for a URL the pane has already moved on from must not mark the
    // new frame painted.
    if (img?.complete && img.naturalWidth > 0 && img.currentSrc === new URL(this.effectiveSrc(), document.baseURI).href) {
      this.paintedKey.set(this.frameKey());
      this.renditionChange.emit({ kind: this.displayedKind(), phase: 'ready', width: img.naturalWidth, height: img.naturalHeight });
    }
  }

  /** A broken image of the right frame is shown as such rather than leaving the
   *  pane hidden forever. */
  protected onFrameError(): void {
    const img = this.frame()?.nativeElement;
    if (!img || (img.currentSrc || img.src) !== new URL(this.effectiveSrc(), document.baseURI).href) return;
    this.paintedKey.set(this.frameKey());
    this.renditionChange.emit({ kind: this.displayedKind(), phase: 'failed' });
  }

  /** The `object-contain` fit scale: how much `content` (natural image size)
   *  is shrunk to fit inside `box` (the rendered pane), the single ratio both
   *  the letterbox inset math and the focus-point translate build on. */
  private containFitScale(boxW: number, boxH: number, contentW: number, contentH: number): number {
    return Math.min(boxW / contentW, boxH / contentH);
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
    const rendered = this.containFitScale(paneW, paneH, naturalW, naturalH) * this.zoom().scale;
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
    // Past the fit scale the render is too soft to judge sharpness; swap to
    // the full-res source for the actual pixel peek.
    if (this.zoom().scale > SyncedZoomComponent.MIN_SCALE && full) return this.retryUrl(full);
    const placeholder = this.placeholderSrc();
    return placeholder && this.readySrc() !== this.requestedPreview() ? this.retryUrl(placeholder) : this.requestedPreview();
  });

  private readonly displayedKind = computed<DisplayedRendition['kind']>(() => {
    if (this.zoom().scale > SyncedZoomComponent.MIN_SCALE && this.fullResSrc()) return 'source';
    return this.placeholderSrc() && this.readySrc() !== this.requestedPreview() ? 'thumbnail' : 'preview';
  });

  private retryUrl(src: string): string {
    const retry = this.retryState();
    if (!retry || retry.frameKey !== this.frameKey() || retry.src !== this.src()) return src;
    const url = new URL(src, document.baseURI);
    url.searchParams.set('facet_retry', `${this.retrySession}-${retry.attempt}`);
    url.searchParams.set('ngsw-bypass', '1');
    return url.href;
  }

  /** Repeat this pane's reads only; framing and the selected photo stay intact. */
  retry(): void {
    this.retryState.update(previous => ({
      frameKey: this.frameKey(), src: this.src(), attempt: (previous?.attempt ?? 0) + 1,
    }));
  }

  /** Compute every pane's proposed crop before the parent commits any of them. */
  zoomForRegion(value: unknown, expectedAspect?: number): ZoomState | null {
    const box = normalizedInspectionBox(value);
    if (!box) return null;
    this.measurePane();
    const { w, h } = this.paneSize();
    const { w: iw, h: ih } = this.naturalSize();
    if (!w || !h || !iw || !ih || expectedAspect !== undefined && (!Number.isFinite(expectedAspect) || expectedAspect <= 0 || Math.abs(iw / ih / expectedAspect - 1) > 0.03)) return null;
    const fit = this.containFitScale(w, h, iw, ih);
    const [x1, y1, x2, y2] = box;
    const scale = this.clampScale(Math.min(w / ((x2 - x1) * iw * fit * 1.5), h / ((y2 - y1) * ih * fit * 1.5)));
    if (scale === SyncedZoomComponent.MIN_SCALE) return { ...FIT_ZOOM };
    return { scale, tx: -scale * ((x1 + x2) / 2 - 0.5) * iw * fit, ty: -scale * ((y1 + y2) / 2 - 0.5) * ih * fit };
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (!this.keyboardInspection() || event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
    if (event.key === 'Home' || event.key.toLowerCase() === 'f') {
      event.preventDefault(); event.stopPropagation(); this.fitRequested.emit(); return;
    }
    const z = this.zoom();
    let next: ZoomState | null = null;
    const step = event.shiftKey ? 64 : 24;
    if (event.key === '+' || event.key === '=') next = { ...z, scale: this.clampScale(z.scale * 1.5) };
    else if (event.key === '-') next = { ...z, scale: this.clampScale(z.scale / 1.5) };
    else if (z.scale > 1) {
      const delta: Record<string, [number, number]> = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
      const pan = delta[event.key];
      if (pan) next = { scale: z.scale, tx: z.tx + pan[0], ty: z.ty + pan[1] };
    }
    if (!next) return;
    event.preventDefault(); event.stopPropagation();
    this.markManuallyFramed();
    this.zoomChange.emit(next);
  }

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
   * Calls measurePane() for a guaranteed-fresh reading of the same
   * paneSize()/naturalSize() signals fitInset() uses, rather than duplicating
   * its own DOM query: the pane swaps to its full-resolution source the
   * moment the zoom lands, so a box cached from an earlier resize or load
   * would misplace the very frame that's about to render.
   */
  private translateForFocus(scale: number): { tx: number; ty: number } {
    const focus = this.focusPoint();
    if (!focus || this.manuallyFramedSrc === this.src()) return { tx: 0, ty: 0 };
    this.measurePane();
    const { w: naturalWidth, h: naturalHeight } = this.naturalSize();
    const { w: width, h: height } = this.paneSize();
    if (!naturalWidth || !naturalHeight || !width || !height) return { tx: 0, ty: 0 };
    const fit = this.containFitScale(width, height, naturalWidth, naturalHeight);
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
      this.zoomChange.emit(this.keyboardInspection() ? { ...z, scale } : { ...FIT_ZOOM });
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
    if (this.keyboardInspection() && this.zoom().scale > 1) this.fitRequested.emit();
    else this.toggleZoom();
  }
}
