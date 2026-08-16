import { Injectable, signal } from '@angular/core';
import { HistogramMode, isHistogramMode } from '../../shared/utils/histogram';

/** The two independent surfaces the histogram widget renders on. Each has its
 *  own persisted user choice and its own config-derived default — see
 *  `HistogramPreferencesService`. */
export type HistogramSurface = 'detail' | 'tooltip';

export const HISTOGRAM_MODE_KEYS: Record<HistogramSurface, string> = {
  detail: 'facet_histogram_mode',
  tooltip: 'facet_histogram_mode_tooltip',
};

/**
 * The user's channel-mode choice for the histogram widget, kept separately
 * per surface.
 *
 * A service rather than component state so that every widget on the same
 * surface agrees and the choice outlives the photo — following
 * `ThemeService`, which persists its own preference the same way: a signal
 * seeded from `localStorage`, with the config-derived default applying only
 * while nothing is stored.
 *
 * The detail panel and the hover/pinned tooltip are deliberately independent:
 * the panel is for studying one photo (RGB detail earns its space), the
 * tooltip is for scanning many quickly (a plain luminance curve usually reads
 * faster). A user's choice on one surface must not silently retune the other,
 * and an admin sets each surface's default separately in `viewer.clipping`.
 */
@Injectable({ providedIn: 'root' })
export class HistogramPreferencesService {
  /** null until the user picks on that surface, so its config default still applies. */
  private readonly detailMode = signal<HistogramMode | null>(this.loadSaved('detail'));
  private readonly tooltipMode = signal<HistogramMode | null>(this.loadSaved('tooltip'));

  mode(surface: HistogramSurface): HistogramMode | null {
    return surface === 'tooltip' ? this.tooltipMode() : this.detailMode();
  }

  setMode(surface: HistogramSurface, mode: HistogramMode): void {
    const target = surface === 'tooltip' ? this.tooltipMode : this.detailMode;
    target.set(mode);
    try {
      localStorage.setItem(HISTOGRAM_MODE_KEYS[surface], mode);
    } catch { /* private browsing — the choice just does not outlive the tab */ }
  }

  private loadSaved(surface: HistogramSurface): HistogramMode | null {
    try {
      const raw = localStorage.getItem(HISTOGRAM_MODE_KEYS[surface]);
      return isHistogramMode(raw) ? raw : null;
    } catch {
      return null;
    }
  }
}
