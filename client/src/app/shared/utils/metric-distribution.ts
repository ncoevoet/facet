/** A metric's library-wide distribution, as served by /filter_options/metric_ranges. */
export interface MetricDistribution {
  min: number;
  max: number;
  buckets: number[];
  /** The photo field the range describes; decides which end of it ranks best. */
  column?: string;
}

/** Fields where a lower value is the better photo, so their rank counts from the bottom. */
const LOWER_IS_BETTER = new Set(['noise_sigma', 'channel_clip_shadow_pct', 'channel_clip_highlight_pct']);

/** Fields with no better end (the brightest frame or f/22 is not the best photo): range only, no rank. */
const UNRANKED = new Set(['face_count', 'face_ratio', 'mean_luminance', 'mean_saturation', 'iso', 'f_stop', 'focal_length']);

/** Bucket heights as a percentage of the tallest bucket, for a sparkline. */
export function normalizeBars(buckets: number[]): number[] {
  const max = Math.max(1, ...buckets);
  return buckets.map(b => Math.round((b / max) * 100));
}

function relativePosition(range: MetricDistribution, value: number): number {
  const scale = Math.max(Math.abs(range.min), Math.abs(range.max), 1);
  return (value / scale - range.min / scale) / (range.max / scale - range.min / scale);
}

/** The bucket a value falls in, by the same formula the server buckets with (`_metric_buckets`). */
export function bucketIndexOf(range: MetricDistribution, value: number): number {
  const bins = range.buckets.length;
  if (bins <= 1 || range.max <= range.min) return 0;
  const raw = Math.trunc(relativePosition(range, value) * bins);
  return Math.max(0, Math.min(bins - 1, raw));
}

/**
 * Share of the library (0-100) whose value is below this one, interpolated
 * linearly inside the value's bucket — so it is approximate to one bucket.
 * Null when there is no value, no photo counted, or no spread to place it in.
 */
export function percentileOf(range: MetricDistribution, value: number | null | undefined): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  const bins = range.buckets.length;
  const total = range.buckets.reduce((sum, b) => sum + b, 0);
  if (bins <= 1 || total === 0 || range.max <= range.min) return null;
  const index = bucketIndexOf(range, value);
  const within = Math.max(0, Math.min(1, relativePosition(range, value) * bins - index));
  const below = range.buckets.slice(0, index).reduce((sum, b) => sum + b, 0) + within * range.buckets[index];
  return Math.round((below / total) * 100);
}

/**
 * "Top X%": the share of the library at least as good as a value — at or above it,
 * or at or below it for a lower-is-better field — never below 1 so the best reads "top 1%".
 * Null for a field with no better end.
 */
export function topPercentOf(range: MetricDistribution, value: number | null | undefined): number | null {
  if (UNRANKED.has(range.column ?? '')) return null;
  const below = percentileOf(range, value);
  if (below === null) return null;
  return Math.max(1, LOWER_IS_BETTER.has(range.column ?? '') ? below : 100 - below);
}
