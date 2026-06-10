import {
  ChangeDetectionStrategy, Component, effect, input, signal, untracked,
} from '@angular/core';
import { computeLuminanceHistogram, histogramPolygonPoints } from '../../utils/histogram';

/**
 * Compact luminance histogram computed client-side from an already-cached
 * thumbnail (same-origin, so the canvas stays untainted). Pass `bins` to
 * bypass the canvas path with precomputed values (future backend feed).
 */
@Component({
  selector: 'app-histogram',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (points()) {
      <svg viewBox="0 0 128 40" preserveAspectRatio="none" class="w-full h-10 block" aria-hidden="true">
        <polygon [attr.points]="points()" class="fill-current opacity-60" />
      </svg>
    }
  `,
  host: { class: 'block text-neutral-400' },
})
export class HistogramComponent {
  /** Thumbnail URL to sample (ignored when bins are provided). */
  readonly src = input<string>('');
  /** Optional precomputed normalized bins (skips the canvas path). */
  readonly bins = input<number[] | null>(null);

  protected readonly points = signal('');

  constructor() {
    effect(() => {
      const precomputed = this.bins();
      if (precomputed?.length) {
        this.points.set(histogramPolygonPoints(precomputed, 128, 40));
        return;
      }
      const url = this.src();
      untracked(() => this.points.set(''));
      if (!url) return;
      this.sample(url);
    });
  }

  private sample(url: string): void {
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => {
      try {
        const scale = Math.min(1, 160 / (img.naturalWidth || 160));
        const w = Math.max(1, Math.round((img.naturalWidth || 160) * scale));
        const h = Math.max(1, Math.round((img.naturalHeight || 120) * scale));
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        if (!ctx) return;
        ctx.drawImage(img, 0, 0, w, h);
        const values = computeLuminanceHistogram(ctx.getImageData(0, 0, w, h).data);
        if (this.src() === url) {
          this.points.set(histogramPolygonPoints(values, 128, 40));
        }
      } catch { /* canvas unavailable - histogram stays hidden */ }
    };
    img.src = url;
  }
}
