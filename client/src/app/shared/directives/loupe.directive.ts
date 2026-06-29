import { Directive, ElementRef, effect, inject, input, OnDestroy } from '@angular/core';

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

  private static readonly SIZE = 220;
  private lens: HTMLDivElement | null = null;
  private readonly onMove = (e: MouseEvent): void => this.move(e);
  private readonly onLeave = (): void => this.hide();

  constructor() {
    const el = this.host.nativeElement;
    el.addEventListener('mousemove', this.onMove);
    el.addEventListener('mouseleave', this.onLeave);
    // Hide immediately when loupe mode is switched off, even if the cursor is
    // stationary (move() only reacts on the next mousemove/mouseleave).
    effect(() => {
      if (!this.loupeActive()) this.hide();
    });
  }

  private ensureLens(): HTMLDivElement {
    if (!this.lens) {
      const d = document.createElement('div');
      d.style.cssText = [
        'position:fixed', 'pointer-events:none', 'z-index:1000',
        'border-radius:9999px', 'border:2px solid rgba(255,255,255,0.8)',
        'box-shadow:0 6px 24px rgba(0,0,0,0.55)', 'background-repeat:no-repeat',
        'background-color:#000', 'display:none',
        `width:${LoupeDirective.SIZE}px`, `height:${LoupeDirective.SIZE}px`,
      ].join(';');
      document.body.appendChild(d);
      this.lens = d;
    }
    return this.lens;
  }

  private move(e: MouseEvent): void {
    if (!this.loupeActive()) { this.hide(); return; }
    const rect = this.host.nativeElement.getBoundingClientRect();
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
    this.lens?.remove();
    this.lens = null;
  }
}
