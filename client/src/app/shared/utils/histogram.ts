/** Pure histogram math (kept canvas-free so it tests in jsdom). */

/**
 * Normalized bins in [0, 1]. `r`/`g`/`b` are null when only luminance is known —
 * a photo whose stored histogram predates the per-channel format.
 */
export interface HistogramChannels {
  luma: number[];
  r: number[] | null;
  g: number[] | null;
  b: number[] | null;
}

/**
 * Scale every channel by the single largest bin found across all of them.
 * Normalizing each channel by its own maximum would stretch a near-empty
 * channel to full height and draw a colour cast the photo does not have.
 */
export function normalizeChannels(channels: HistogramChannels): HistogramChannels {
  const series = [channels.luma, channels.r, channels.g, channels.b];
  let max = 0;
  for (const bins of series) {
    if (!bins) continue;
    for (const v of bins) if (v > max) max = v;
  }
  if (max <= 0) return channels;
  const scale = (bins: number[] | null) => bins && bins.map(v => v / max);
  return {
    luma: channels.luma.map(v => v / max),
    r: scale(channels.r),
    g: scale(channels.g),
    b: scale(channels.b),
  };
}

/**
 * Bin pixel data (RGBA byte stream) into luminance + R/G/B histograms.
 * Uses Rec. 601 luma weights. All four channels share one normalization.
 */
export function computeRgbHistogram(data: Uint8ClampedArray, bins = 64): HistogramChannels {
  const luma = new Array<number>(bins).fill(0);
  const r = new Array<number>(bins).fill(0);
  const g = new Array<number>(bins).fill(0);
  const b = new Array<number>(bins).fill(0);
  if (!data.length) return { luma, r, g, b };
  const scale = bins / 256;
  const last = bins - 1;
  for (let i = 0; i < data.length; i += 4) {
    const red = data[i];
    const green = data[i + 1];
    const blue = data[i + 2];
    luma[Math.min(last, Math.floor((0.299 * red + 0.587 * green + 0.114 * blue) * scale))]++;
    r[Math.min(last, Math.floor(red * scale))]++;
    g[Math.min(last, Math.floor(green * scale))]++;
    b[Math.min(last, Math.floor(blue * scale))]++;
  }
  return normalizeChannels({ luma, r, g, b });
}

/** SVG point list for a normalized histogram, in a 0..width / 0..height box. */
export function histogramLinePoints(values: number[], width: number, height: number): string {
  if (!values.length) return '';
  const step = width / (values.length - 1 || 1);
  return values
    .map((v, i) => `${(i * step).toFixed(1)},${(height - v * height).toFixed(1)}`)
    .join(' ');
}

/** The same curve closed down to the baseline, for a filled `<polygon>`. */
export function histogramPolygonPoints(values: number[], width: number, height: number): string {
  const line = histogramLinePoints(values, width, height);
  return line ? `0,${height} ${line} ${width},${height}` : '';
}

/** Draw the filled luminance curve, the three colour channels together, or one alone. */
export type HistogramMode = 'luma' | 'rgb' | 'r' | 'g' | 'b';

export const HISTOGRAM_MODES: readonly HistogramMode[] = ['luma', 'rgb', 'r', 'g', 'b'];

/** Narrows a stored/configured value, so a stale localStorage entry or an
 *  unrecognised config string degrades to the caller's fallback rather than
 *  rendering nothing. */
export function isHistogramMode(value: unknown): value is HistogramMode {
  return typeof value === 'string' && (HISTOGRAM_MODES as readonly string[]).includes(value);
}

/** The channels a clipping percentage is reported for. */
export type ClipChannel = 'luma' | 'r' | 'g' | 'b';

/**
 * Percentage of pixels sitting exactly on bin 0 / bin 255, per channel, as
 * measured by the scan. `null` from the API means the photo was never measured
 * — its histogram predates the per-channel format — which is NOT the same as
 * zero and must never be drawn as "clean".
 */
export interface ClipPercents {
  shadow: Record<ClipChannel, number>;
  highlight: Record<ClipChannel, number>;
}

/** Channels whose clipping exceeds `threshold` percent, worst-first order R/G/B. */
export function clippedChannels(
  clipped: ClipPercents | null | undefined,
  direction: 'shadow' | 'highlight',
  threshold: number,
  monochrome: boolean,
): ClipChannel[] {
  if (!clipped) return [];
  // A monochrome frame has three identical channels, so three coloured markers
  // would be one fact drawn three times; it gets a single neutral one instead.
  const channels: ClipChannel[] = monochrome ? ['luma'] : ['r', 'g', 'b'];
  return channels.filter(c => (clipped[direction]?.[c] ?? 0) > threshold);
}

/** Sum adjacent bins down to `bins` buckets. `bins` must divide the input length. */
export function downsampleBins(values: number[], bins: number): number[] {
  if (bins >= values.length) return [...values];
  const group = values.length / bins;
  const out = new Array<number>(bins).fill(0);
  for (let i = 0; i < values.length; i++) out[Math.min(bins - 1, Math.floor(i / group))] += values[i];
  return out;
}

/**
 * Fold full-resolution channels down to `bins` for drawing, with both clipping
 * bins excluded.
 *
 * A clipped frame puts a large share of its pixels in one extreme bin, and that
 * spike becomes the global maximum — normalizing against it flattens the entire
 * tonal curve into a hairline at the baseline, destroying the only thing the
 * curve is for. The extremes are reported as clipping markers instead. The
 * single shared maximum across channels is kept: per-channel maxima would
 * stretch a near-empty channel to full height and invent a colour cast.
 */
export function toInteriorChannels(channels: HistogramChannels, bins: number): HistogramChannels {
  const interior = (values: number[] | null): number[] | null => {
    if (!values?.length) return values;
    const trimmed = [...values];
    trimmed[0] = 0;
    trimmed[trimmed.length - 1] = 0;
    return downsampleBins(trimmed, bins);
  };
  return normalizeChannels({
    luma: interior(channels.luma) ?? [],
    r: interior(channels.r),
    g: interior(channels.g),
    b: interior(channels.b),
  });
}
