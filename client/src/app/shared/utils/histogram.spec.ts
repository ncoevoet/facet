import { computeLuminanceHistogram, histogramPolygonPoints } from './histogram';

function rgba(pixels: number[][]): Uint8ClampedArray {
  const data = new Uint8ClampedArray(pixels.length * 4);
  pixels.forEach(([r, g, b], i) => {
    data[i * 4] = r; data[i * 4 + 1] = g; data[i * 4 + 2] = b; data[i * 4 + 3] = 255;
  });
  return data;
}

describe('computeLuminanceHistogram', () => {
  it('all-black image spikes in the first bin', () => {
    const hist = computeLuminanceHistogram(rgba(Array(50).fill([0, 0, 0])), 8);
    expect(hist[0]).toBe(1);
    expect(hist.slice(1).every(v => v === 0)).toBe(true);
  });

  it('all-white image spikes in the last bin', () => {
    const hist = computeLuminanceHistogram(rgba(Array(50).fill([255, 255, 255])), 8);
    expect(hist[7]).toBe(1);
    expect(hist.slice(0, 7).every(v => v === 0)).toBe(true);
  });

  it('uniform gray ramp fills bins roughly evenly', () => {
    const pixels = Array.from({ length: 256 }, (_, v) => [v, v, v]);
    const hist = computeLuminanceHistogram(rgba(pixels), 8);
    expect(hist.every(v => v > 0.9)).toBe(true);
  });

  it('empty data yields all-zero bins', () => {
    expect(computeLuminanceHistogram(new Uint8ClampedArray(0), 4)).toEqual([0, 0, 0, 0]);
  });
});

describe('histogramPolygonPoints', () => {
  it('starts and ends at the baseline', () => {
    const points = histogramPolygonPoints([0.5, 1, 0.25], 128, 40);
    expect(points.startsWith('0,40 ')).toBe(true);
    expect(points.endsWith(' 128,40')).toBe(true);
  });

  it('maps values to inverted y coordinates', () => {
    const points = histogramPolygonPoints([1], 100, 40);
    expect(points).toContain('0.0,0.0');
  });

  it('empty values yield empty string', () => {
    expect(histogramPolygonPoints([], 100, 40)).toBe('');
  });
});
