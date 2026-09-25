import { Directive, ElementRef, effect, inject, input, OnDestroy } from '@angular/core';

/** How the host's box relates to the actual displayed image content, mirroring
 *  CSS `object-fit`. `'fill'` is the original behaviour: the host rect IS the
 *  content rect (grid tiles / scenes / junk-sweep, which stretch to their box
 *  anyway). `'contain'` letterboxes/pillarboxes (the darkroom's single/compare
 *  panes). `'cover'` crops to fill the box (the face-strip thumbnails, whose
 *  longest side is capped but which render in a square `object-cover` box). */
export type LoupeFit = 'fill' | 'contain' | 'cover';

/**
 * Photo-Mechanic-style hover loupe for contact-sheet tiles. While active, a
 * circular magnifier follows the cursor over the host element and shows the
 * region under it sourced from the full-resolution image — so a culler can
 * pixel-peek for sharpness/closed eyes without leaving the grid. The lens
 * background is the full-res source, scaled by the host's displayed size, so
 * the magnification shows real detail (not an upscaled thumbnail).
 */
@Directive({ selector: '[appLoupe]' })
export class LoupeDirective implements OnDestroy {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** Full-resolution image URL to magnify. */
  readonly loupeSrc = input.required<string>({ alias: 'appLoupe' });
  /** Whether loupe mode is on (toggled by the view, e.g. the Z key). */
  readonly loupeActive = input(false);
  /** Magnification factor relative to the tile's displayed size. */
  readonly loupeZoom = input(3);
  /** How the host's box relates to the rendered image content — see
   *  `LoupeFit`. Grid tiles / scenes / junk-sweep leave this at the default
   *  `'fill'` and keep the original host-rect-is-the-image behaviour. */
  readonly loupeFit = input<LoupeFit>('fill');

  private static readonly SIZE = 300;
  private lens: HTMLDivElement | null = null;
  private lensParent: Element | null = null;
  private lastEvent: MouseEvent | null = null;
  private readonly onMove = (e: MouseEvent): void => this.move(e);
  private readonly onLeave = (): void => {
    this.lastEvent = null;
    this.hide();
  };
  private readonly onLoad = (): void => this.refresh();

  constructor() {
    const el = this.host.nativeElement;
    el.addEventListener('mousemove', this.onMove);
    el.addEventListener('mouseleave', this.onLeave);
    el.addEventListener('load', this.onLoad);
    // Hide immediately when loupe mode is switched off, even if the cursor is
    // stationary (move() only reacts on the next mousemove/mouseleave).
    effect(() => {
      if (!this.loupeActive()) this.hide();
    });
    // The darkroom's <img>/directive survive a frame step without a remount
    // (the @if's `as` binding just swaps context), so the lens must refresh
    // on a source change even without a mousemove — otherwise it shows the
    // previous frame's pixels under the cursor.
    effect(() => {
      this.loupeSrc();
      this.refresh();
    });
  }

  private ensureLens(): HTMLDivElement {
    const parent = document.fullscreenElement ?? document.body;
    if (!this.lens) {
      const d = document.createElement('div');
      d.style.cssText = [
        'position:fixed', 'pointer-events:none', 'z-index:1000',
        'border-radius:9999px', 'border:2px solid rgba(255,255,255,0.8)',
        'box-shadow:0 6px 24px rgba(0,0,0,0.55)', 'background-repeat:no-repeat',
        'background-color:#000', 'display:none',
        `width:${LoupeDirective.SIZE}px`, `height:${LoupeDirective.SIZE}px`,
      ].join(';');
      this.lens = d;
    }
    if (this.lensParent !== parent) {
      parent.appendChild(this.lens);
      this.lensParent = parent;
    }
    return this.lens;
  }

  /**
   * The rect the lens should map against: the host's own box for `'fill'`,
   * or — for `'contain'`/`'cover'` — the actual rendered image content box
   * within that host, computed with the matching `object-fit` formula:
   * `'contain'` scale = min(rectW/naturalW, rectH/naturalH) (image fits
   * inside, centred, may letterbox); `'cover'` scale = max(...) (image fills
   * the box, centred, may overflow/crop). Falls back to the host rect if the
   * image has not loaded yet (naturalWidth/Height still 0).
   */
  private contentRect(): DOMRect {
    const rect = this.host.nativeElement.getBoundingClientRect();
    const fit = this.loupeFit();
    if (fit === 'fill') return rect;
    const img = this.host.nativeElement as HTMLImageElement;
    const naturalW = img.naturalWidth;
    const naturalH = img.naturalHeight;
    if (!naturalW || !naturalH) return rect;
    const scale = fit === 'cover'
      ? Math.max(rect.width / naturalW, rect.height / naturalH)
      : Math.min(rect.width / naturalW, rect.height / naturalH);
    const w = naturalW * scale;
    const h = naturalH * scale;
    const left = rect.left + (rect.width - w) / 2;
    const top = rect.top + (rect.height - h) / 2;
    return new DOMRect(left, top, w, h);
  }

  private move(e: MouseEvent): void {
    this.lastEvent = e;
    this.render(e);
  }

  /** Re-renders the lens against the last known cursor position, for changes
   *  that are not themselves a mousemove: a new `loupeSrc`, or the image's
   *  `load` event settling the natural size the fit modes depend on. */
  private refresh(): void {
    if (this.lastEvent) this.render(this.lastEvent);
  }

  private render(e: MouseEvent): void {
    if (!this.loupeActive()) { this.hide(); return; }
    const rect = this.contentRect();
    const size = LoupeDirective.SIZE;
    const ratio = this.loupeZoom();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const lens = this.ensureLens();
    lens.style.display = 'block';
    lens.style.left = `${e.clientX - size / 2}px`;
    lens.style.top = `${e.clientY - size / 2}px`;
    lens.style.backgroundImage = `url("${this.loupeSrc()}")`;
    lens.style.backgroundSize = `${rect.width * ratio}px ${rect.height * ratio}px`;
    lens.style.backgroundPosition = `${-(x * ratio - size / 2)}px ${-(y * ratio - size / 2)}px`;
  }

  private hide(): void {
    if (this.lens) this.lens.style.display = 'none';
  }

  ngOnDestroy(): void {
    const el = this.host.nativeElement;
    el.removeEventListener('mousemove', this.onMove);
    el.removeEventListener('mouseleave', this.onLeave);
    el.removeEventListener('load', this.onLoad);
    this.lens?.remove();
    this.lens = null;
    this.lensParent = null;
  }
}
