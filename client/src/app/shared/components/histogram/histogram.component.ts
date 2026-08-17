import {
  ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, signal,
  untracked,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { catchError, of } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { HistogramPreferencesService, HistogramSurface } from '../../../core/services/histogram-preferences.service';
import { I18nService } from '../../../core/services/i18n.service';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { I18N_KEYS } from '../../../core/i18n/keys';
import {
  ClipChannel, ClipPercents, HistogramChannels, HistogramMode, clippedChannels,
  computeRgbHistogram, histogramLinePoints, histogramPolygonPoints, toInteriorChannels,
} from '../../utils/histogram';

/** One end-of-scale marker: a channel that ran out of range on this photo. */
interface ClipMarker {
  channel: ClipChannel;
  percent: number;
  colorClass: string;
}

/** A single colour channel, drawn filled like luma rather than a bare 1px
 *  stroke — a lone line in a large box reads poorly, and filling it keeps
 *  every mode visually consistent. */
type SingleChannel = 'r' | 'g' | 'b';

const VIEW_WIDTH = 128;
const SAMPLE_BINS = 256;
const DISPLAY_BINS = 64;
const SAMPLE_MAX_EDGE = 160;

const BUTTON_CLASS = 'px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider transition-colors cursor-pointer';
const BUTTON_ACTIVE_CLASS = 'bg-[var(--mat-sys-primary)] text-black';
const BUTTON_IDLE_CLASS = 'text-neutral-400 hover:text-neutral-200';

const MARKER_COLOR_CLASS: Record<ClipChannel, string> = {
  luma: 'bg-neutral-300', r: 'bg-red-500', g: 'bg-green-500', b: 'bg-blue-500',
};

/** Same channel labels as the mode buttons, so a marker's tooltip never names
 *  a channel differently than the button that selects it (e.g. French "V"
 *  for vert vs. a hardcoded "G"). */
const CHANNEL_LABEL_KEY: Record<ClipChannel, string> = {
  luma: I18N_KEYS.histogram.mode.luminance,
  r: I18N_KEYS.histogram.mode.red,
  g: I18N_KEYS.histogram.mode.green,
  b: I18N_KEYS.histogram.mode.blue,
};

const CHANNEL_FILL_CLASS: Record<SingleChannel, string> = {
  r: 'fill-red-500 opacity-70', g: 'fill-green-500 opacity-70', b: 'fill-blue-500 opacity-70',
};

/** Compact enough for a tooltip that follows the pointer around the gallery. */
export const HISTOGRAM_COMPACT_HEIGHT = 40;
/**
 * The pinned/docked tooltip's height: readable at a glance without the
 * scoring grid it sits beside losing its share of a bubble that also has to
 * fit on screen next to the cursor. Clearly larger than the 40px hover
 * default, clearly smaller than the detail panel's 160px — the tooltip is a
 * scan-many-photos surface, not a study-one-photo surface.
 */
export const HISTOGRAM_TOOLTIP_HEIGHT = 64;
/**
 * The detail panel's height. Tall enough that an ordinary tonal curve has real
 * vertical range to move in — at 40px the difference between a mid-tone hump
 * and a shadow hump is a couple of pixels — while still leaving the panel room
 * for everything below it.
 */
export const HISTOGRAM_PANEL_HEIGHT = 160;

/**
 * Compact histogram with five channel modes: luminance, RGB combined, or a
 * single R/G/B channel filled on its own.
 *
 * Prefers the bins the scan stored for the photo (`/api/photo/histogram`):
 * those are measured on the full-resolution image before any JPEG encoding.
 * Falls back to sampling the cached thumbnail in a canvas (same-origin, so it
 * stays untainted) for a photo whose row has no stored histogram — an
 * un-migrated scan, or a viewer DB exported before the column was kept. That
 * fallback reads a <=160px q80 JPEG with 4:2:0 chroma subsampling, so its R and
 * B curves are largely interpolated; the stored bins are not.
 *
 * The curve is drawn from the interior bins only. A clipped frame piles a large
 * share of its pixels onto bin 0 or bin 255, and normalizing against that spike
 * flattens the whole curve into a hairline at the baseline — useless for the
 * one thing a histogram is for. The extremes are shown as end markers instead,
 * which is also the only place they are legible.
 *
 * Markers come exclusively from the stored measurement. The sampled fallback
 * reads a re-encoded thumbnail whose extremes are an artifact of the JPEG
 * rather than of the exposure, so a photo on that path shows no markers at all
 * — unknown, rather than fabricated.
 */
@Component({
  selector: 'app-histogram',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatTooltipModule, TranslatePipe],
  template: `
    @if (curves(); as c) {
      <div class="relative">
        <svg [attr.viewBox]="viewBox()" preserveAspectRatio="none"
             [style.height.px]="height()" class="w-full block" aria-hidden="true">
          @if (effectiveMode() === 'luma') {
            <polygon [attr.points]="c.luma" class="fill-current opacity-60" />
          } @else if (effectiveMode() === 'rgb') {
            @if (c.r) {
              <polyline [attr.points]="c.r" fill="none" stroke-width="1" vector-effect="non-scaling-stroke" class="stroke-red-500 opacity-90" />
              <polyline [attr.points]="c.g" fill="none" stroke-width="1" vector-effect="non-scaling-stroke" class="stroke-green-500 opacity-90" />
              <polyline [attr.points]="c.b" fill="none" stroke-width="1" vector-effect="non-scaling-stroke" class="stroke-blue-500 opacity-90" />
            } @else {
              <polygon [attr.points]="c.luma" class="fill-current opacity-60" />
            }
          } @else if (singleChannelPoints()) {
            <!-- Single channel modes fill like luma rather than a bare 1px
                 stroke -- a lone line in a large box reads poorly -- coloured
                 with that channel's own colour. -->
            <polygon [attr.points]="singleChannelPoints()" [class]="singleChannelFillClass()" />
          } @else {
            <polygon [attr.points]="c.luma" class="fill-current opacity-60" />
          }
        </svg>

        <!-- Clipping markers, drawn as elements over the chart rather than
             inside it: preserveAspectRatio="none" stretches the viewBox
             unevenly, so a square drawn in SVG units would not render square.
             Kept per-channel in EVERY mode — a blown blue channel is lost data
             whichever curve is on screen, and merging them into one grey marker
             would hide exactly the single-channel case luma cannot show. This
             also means a single-channel mode still shows markers for the other
             two channels, which is deliberate: the point of a marker is "this
             data is gone", not "this is the channel you are currently looking at". -->
        @if (shadowMarkers().length) {
          <div class="absolute top-0 left-0 flex flex-col gap-px"
               [matTooltip]="I18N.histogram.clipping.shadow | translate:{ channels: shadowDetail() }"
               [attr.aria-label]="I18N.histogram.clipping.shadow | translate:{ channels: shadowDetail() }">
            @for (marker of shadowMarkers(); track marker.channel) {
              <span class="block w-1.5 h-1.5 rounded-[1px]" [class]="marker.colorClass"></span>
            }
          </div>
        }
        @if (highlightMarkers().length) {
          <div class="absolute top-0 right-0 flex flex-col gap-px"
               [matTooltip]="I18N.histogram.clipping.highlight | translate:{ channels: highlightDetail() }"
               [attr.aria-label]="I18N.histogram.clipping.highlight | translate:{ channels: highlightDetail() }">
            @for (marker of highlightMarkers(); track marker.channel) {
              <span class="block w-1.5 h-1.5 rounded-[1px]" [class]="marker.colorClass"></span>
            }
          </div>
        }
      </div>

      @if (showModeToggle() && !monochrome()) {
        <div class="flex items-center gap-1 mt-1 flex-wrap" role="group"
             [attr.aria-label]="I18N.histogram.mode.label | translate">
          <button type="button" [class]="lumaButtonClass()"
                  [attr.aria-pressed]="effectiveMode() === 'luma'"
                  (click)="selectMode('luma')">{{ I18N.histogram.mode.luminance | translate }}</button>
          <button type="button" [class]="rgbButtonClass()"
                  [attr.aria-pressed]="effectiveMode() === 'rgb'"
                  (click)="selectMode('rgb')">{{ I18N.histogram.mode.rgb | translate }}</button>
          <button type="button" [class]="rButtonClass()"
                  [attr.aria-pressed]="effectiveMode() === 'r'"
                  (click)="selectMode('r')">{{ I18N.histogram.mode.red | translate }}</button>
          <button type="button" [class]="gButtonClass()"
                  [attr.aria-pressed]="effectiveMode() === 'g'"
                  (click)="selectMode('g')">{{ I18N.histogram.mode.green | translate }}</button>
          <button type="button" [class]="bButtonClass()"
                  [attr.aria-pressed]="effectiveMode() === 'b'"
                  (click)="selectMode('b')">{{ I18N.histogram.mode.blue | translate }}</button>
        </div>
      }
    }
  `,
  host: { class: 'block text-neutral-400' },
})
export class HistogramComponent {
  /** Photo path — its stored bins are fetched and preferred when set. */
  readonly path = input<string>('');
  /** Thumbnail URL sampled in-browser when no stored histogram exists. */
  readonly src = input<string>('');
  /** B&W photo: the R/G/B curves would just triple-trace the luminance one. */
  readonly monochrome = input(false);
  /** Drawing height in CSS pixels. */
  readonly height = input(HISTOGRAM_COMPACT_HEIGHT);
  /** Whether to offer the channel-mode switch (the detail panel and a pinned tooltip do). */
  readonly showModeToggle = input(false);
  /** House default from `viewer.clipping.histogram_mode` (detail panel) or
   *  `viewer.clipping.tooltip_histogram_mode` (tooltip), until the user picks. */
  readonly defaultMode = input<HistogramMode>('rgb');
  /** Percent of clipped pixels a channel must exceed to earn a marker. */
  readonly indicatorPercent = input(1);
  /** Which surface's persisted mode choice this instance reads/writes — the
   *  detail panel and the tooltip remember their channel mode independently. */
  readonly surface = input<HistogramSurface>('detail');

  protected readonly I18N = I18N_KEYS;

  // Two independent sources, never mixed within a single rendered curve (the
  // widget only ever draws one mode at a time, so there is no view where
  // they would need to agree on scale):
  //  - storedChannels: from /photo/histogram. Its luma is the more accurate
  //    measurement (full resolution, pre-JPEG) and is preferred for luma
  //    mode whenever present, including a legacy row that has it alone.
  //  - sampledChannels: canvas-sampled from the thumbnail, computed lazily
  //    (see the second effect below) only once a channel mode is actually
  //    selected AND the stored measurement turned out to lack per-channel
  //    data. Deferred rather than eager: it is real CPU cost (image decode +
  //    canvas draw + getImageData) that would otherwise run on every render
  //    across a library that, measured, is 100% legacy 1024-byte histograms.
  //    All four of its channels come from the one canvas pass, so RGB/single-
  //    channel modes stay internally consistent with each other.
  private readonly storedChannels = signal<HistogramChannels | null>(null);
  private readonly sampledChannels = signal<HistogramChannels | null>(null);
  protected readonly clipped = signal<ClipPercents | null>(null);

  /** A monochrome photo has no colour channels to separate, so it never leaves luma. */
  protected readonly effectiveMode = computed<HistogramMode>(
    () => this.monochrome() ? 'luma' : (this.preferences.mode(this.surface()) ?? this.defaultMode()));

  protected readonly viewBox = computed(() => `0 0 ${VIEW_WIDTH} ${this.height()}`);

  protected readonly curves = computed(() => {
    const mode = this.effectiveMode();
    const stored = this.storedChannels();
    const sampled = this.sampledChannels();
    // luma mode: prefer the more accurate stored measurement. Every other
    // mode needs per-channel data: prefer the self-consistent sampled set,
    // falling back to the (channel-less) stored one only until sampling
    // resolves -- the template already degrades that to a luma polygon.
    const source = mode === 'luma' ? (stored ?? sampled) : (sampled ?? stored);
    if (!source) return null;
    const height = this.height();
    const rgb = this.monochrome() ? null : source;
    const line = (values: number[] | null | undefined) =>
      values?.length ? histogramLinePoints(values, VIEW_WIDTH, height) : '';
    const fill = (values: number[] | null | undefined) =>
      values?.length ? histogramPolygonPoints(values, VIEW_WIDTH, height) : '';
    return {
      luma: histogramPolygonPoints(source.luma, VIEW_WIDTH, height),
      r: line(rgb?.r),
      g: line(rgb?.g),
      b: line(rgb?.b),
      rFill: fill(rgb?.r),
      gFill: fill(rgb?.g),
      bFill: fill(rgb?.b),
    };
  });

  /** Filled polygon points for the active single-channel mode, or '' outside one. */
  protected readonly singleChannelPoints = computed(() => {
    const c = this.curves();
    const mode = this.effectiveMode();
    if (!c || (mode !== 'r' && mode !== 'g' && mode !== 'b')) return '';
    return mode === 'r' ? c.rFill : mode === 'g' ? c.gFill : c.bFill;
  });

  protected readonly singleChannelFillClass = computed(() => {
    const mode = this.effectiveMode();
    return mode === 'r' || mode === 'g' || mode === 'b' ? CHANNEL_FILL_CLASS[mode] : '';
  });

  protected readonly shadowMarkers = computed(() => this.markersFor('shadow'));
  protected readonly highlightMarkers = computed(() => this.markersFor('highlight'));
  protected readonly shadowDetail = computed(() => this.describeMarkers(this.shadowMarkers()));
  protected readonly highlightDetail = computed(() => this.describeMarkers(this.highlightMarkers()));

  protected readonly lumaButtonClass = computed(() => this.buttonClass('luma'));
  protected readonly rgbButtonClass = computed(() => this.buttonClass('rgb'));
  protected readonly rButtonClass = computed(() => this.buttonClass('r'));
  protected readonly gButtonClass = computed(() => this.buttonClass('g'));
  protected readonly bButtonClass = computed(() => this.buttonClass('b'));

  private readonly api = inject(ApiService);
  private readonly preferences = inject(HistogramPreferencesService);
  private readonly i18n = inject(I18nService);
  private readonly destroyRef = inject(DestroyRef);
  private destroyed = false;
  // Bumped on every input change so a slow response can't overwrite the curves
  // of the photo the user has already moved on to.
  private generation = 0;

  constructor() {
    this.destroyRef.onDestroy(() => { this.destroyed = true; });
    effect(onCleanup => {
      const path = this.path();
      const url = this.src();
      const token = ++this.generation;
      untracked(() => {
        this.storedChannels.set(null);
        this.sampledChannels.set(null);
        this.clipped.set(null);
      });
      if (path) {
        // Unsubscribing aborts the request, so scrubbing the gallery cancels
        // the tooltips the pointer already left instead of queueing them.
        onCleanup(this.loadStored(path, url, token));
      } else if (url) {
        this.sample(url, token);
      }
    });

    // Lazy channel sampling: a legacy row's stored measurement has luma but
    // no r/g/b. Re-runs whenever the resolved mode changes (the user picking
    // a channel mode) or a fresh storedChannels arrives (in case the mode
    // already needed channels the moment it loaded) -- either way, sample
    // exactly once per photo, only if something actually needs it.
    effect(() => {
      const mode = this.effectiveMode();
      const stored = this.storedChannels();
      const url = this.src();
      if (mode === 'luma' || !stored || stored.r?.length || this.sampledChannels() || !url) return;
      this.sample(url, this.generation);
    });
  }

  protected selectMode(mode: HistogramMode): void {
    this.preferences.setMode(this.surface(), mode);
  }

  private buttonClass(mode: HistogramMode): string {
    const state = this.effectiveMode() === mode ? BUTTON_ACTIVE_CLASS : BUTTON_IDLE_CLASS;
    return `${BUTTON_CLASS} ${state}`;
  }

  private markersFor(direction: 'shadow' | 'highlight'): ClipMarker[] {
    const clipped = this.clipped();
    if (!clipped) return [];
    return clippedChannels(clipped, direction, this.indicatorPercent(), this.monochrome())
      .map(channel => ({
        channel,
        percent: clipped[direction][channel],
        colorClass: MARKER_COLOR_CLASS[channel],
      }));
  }

  /** "R 21.0% · B 41.7%" for a marker tooltip, using the same translated
   *  channel labels as the mode buttons so the two never disagree. */
  private describeMarkers(markers: ClipMarker[]): string {
    return markers
      .map(m => `${this.i18n.t(CHANNEL_LABEL_KEY[m.channel])} ${m.percent.toFixed(1)}%`)
      .join(' · ');
  }

  private loadStored(path: string, url: string, token: number): () => void {
    const subscription = this.api
      .get<HistogramChannels & { clipped?: ClipPercents | null }>(
        '/photo/histogram', { path, bins: DISPLAY_BINS })
      .pipe(catchError(() => of(null)))
      .subscribe(stored => {
        if (this.destroyed || token !== this.generation) return;
        if (stored?.luma?.length) {
          // Markers come exclusively from this stored measurement -- a legacy
          // row genuinely was never measured for clipping, and that must stay
          // "unknown", never get filled in from the (also legacy) fallback.
          this.clipped.set(stored.clipped ?? null);
          this.storedChannels.set(stored);
        } else if (url) {
          this.sample(url, token);
        }
      });
    return () => subscription.unsubscribe();
  }

  private sample(url: string, token: number): void {
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => {
      if (this.destroyed || token !== this.generation) return;
      try {
        const naturalWidth = img.naturalWidth || SAMPLE_MAX_EDGE;
        const scale = Math.min(1, SAMPLE_MAX_EDGE / naturalWidth);
        const w = Math.max(1, Math.round(naturalWidth * scale));
        const h = Math.max(1, Math.round((img.naturalHeight || 120) * scale));
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        if (!ctx) return;
        ctx.drawImage(img, 0, 0, w, h);
        const data = ctx.getImageData(0, 0, w, h).data;
        // Sampled at full resolution first, so the bins dropped as clipping are
        // exactly the values 0 and 255 rather than a four-value bucket around them.
        this.sampledChannels.set(toInteriorChannels(computeRgbHistogram(data, SAMPLE_BINS), DISPLAY_BINS));
      } catch { /* canvas unavailable - histogram stays hidden */ }
    };
    img.src = url;
  }
}
