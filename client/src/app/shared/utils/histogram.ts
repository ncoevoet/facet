/** Pure luminance-histogram math (kept canvas-free so it tests in jsdom). */

/**
 * Bin pixel data (RGBA byte stream) into a luminance histogram.
 * Uses Rec. 601 luma weights. Returns counts normalized to [0, 1].
 */
export function computeLuminanceHistogram(data: Uint8ClampedArray, bins = 64): number[] {
  const counts = new Array<number>(bins).fill(0);
  if (!data.length) return counts;
  const scale = bins / 256;
  for (let i = 0; i < data.length; i += 4) {
    const luma = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    counts[Math.min(bins - 1, Math.floor(luma * scale))]++;
  }
  let max = 0;
  for (const c of counts) if (c > max) max = c;
  return max > 0 ? counts.map(c => c / max) : counts;
}

/** SVG polygon points string for a normalized histogram, in a 0..width / 0..height box. */
export function histogramPolygonPoints(values: number[], width: number, height: number): string {
  if (!values.length) return '';
  const step = width / (values.length - 1 || 1);
  const points = values.map((v, i) =>
    `${(i * step).toFixed(1)},${(height - v * height).toFixed(1)}`);
  return `0,${height} ${points.join(' ')} ${width},${height}`;
}
