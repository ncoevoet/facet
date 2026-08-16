import {
  ClipPercents, clippedChannels, computeRgbHistogram, downsampleBins, histogramLinePoints,
  histogramPolygonPoints, normalizeChannels, toInteriorChannels,
} from './histogram';

function rgba(pixels: number[][]): Uint8ClampedArray {
  const data = new Uint8ClampedArray(pixels.length * 4);
  pixels.forEach(([r, g, b], i) => {
    data[i * 4] = r; data[i * 4 + 1] = g; data[i * 4 + 2] = b; data[i * 4 + 3] = 255;
  });
  return data;
}

describe('computeRgbHistogram', () => {
  it('all-black image spikes in the first bin', () => {
    const hist = computeRgbHistogram(rgba(Array(50).fill([0, 0, 0])), 8);
    expect(hist.luma[0]).toBe(1);
    expect(hist.luma.slice(1).every(v => v === 0)).toBe(true);
  });

  it('all-white image spikes in the last bin', () => {
    const hist = computeRgbHistogram(rgba(Array(50).fill([255, 255, 255])), 8);
    expect(hist.luma[7]).toBe(1);
    expect(hist.luma.slice(0, 7).every(v => v === 0)).toBe(true);
  });

  it('uniform gray ramp fills bins roughly evenly', () => {
    const pixels = Array.from({ length: 256 }, (_, v) => [v, v, v]);
    const hist = computeRgbHistogram(rgba(pixels), 8);
    expect(hist.luma.every(v => v > 0.9)).toBe(true);
  });

  it('empty data yields all-zero bins on every channel', () => {
    const hist = computeRgbHistogram(new Uint8ClampedArray(0), 4);
    expect(hist.luma).toEqual([0, 0, 0, 0]);
    expect(hist.r).toEqual([0, 0, 0, 0]);
    expect(hist.g).toEqual([0, 0, 0, 0]);
    expect(hist.b).toEqual([0, 0, 0, 0]);
  });

  it('separates the channels of a pure-red frame', () => {
    const hist = computeRgbHistogram(rgba(Array(50).fill([255, 0, 0])), 8);
    expect(hist.r![7]).toBe(1);
    expect(hist.g![0]).toBe(1);
    expect(hist.b![0]).toBe(1);
    // Rec. 601 luma of pure red is 76 -> bin 2 of 8.
    expect(hist.luma[2]).toBe(1);
  });

  it('normalizes every channel by one global max, never per channel', () => {
    // 30 red + 10 green pixels. Blue is zero for all 40, so its single bin is
    // the tallest anywhere and sets the global max; no other channel may be
    // stretched up to 1 by its own peak.
    const pixels = [...Array(30).fill([255, 0, 0]), ...Array(10).fill([0, 255, 0])];
    const hist = computeRgbHistogram(rgba(pixels), 8);
    expect(hist.b![0]).toBeCloseTo(1, 5);
    expect(hist.r![7]).toBeCloseTo(0.75, 5);
    expect(hist.g![7]).toBeCloseTo(0.25, 5);
    expect(Math.max(...hist.r!)).toBeLessThan(1);
    expect(Math.max(...hist.g!)).toBeLessThan(1);
    expect(Math.max(...hist.luma)).toBeLessThan(1);
  });
});

describe('normalizeChannels', () => {
  it('leaves null channels null', () => {
    const out = normalizeChannels({ luma: [1, 3], r: null, g: null, b: null });
    expect(out.luma).toEqual([1 / 3, 1]);
    expect(out.r).toBeNull();
  });

  it('scales luminance by the RGB peak when a channel is taller', () => {
    const out = normalizeChannels({ luma: [2, 0], r: [4, 0], g: [0, 0], b: [0, 0] });
    expect(out.luma).toEqual([0.5, 0]);
    expect(out.r).toEqual([1, 0]);
  });

  it('all-zero input is returned untouched', () => {
    const zero = { luma: [0, 0], r: [0, 0], g: [0, 0], b: [0, 0] };
    expect(normalizeChannels(zero)).toEqual(zero);
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

describe('histogramLinePoints', () => {
  it('omits the baseline points the polygon adds', () => {
    const line = histogramLinePoints([0.5, 1, 0.25], 128, 40);
    expect(line.startsWith('0,40')).toBe(false);
    expect(histogramPolygonPoints([0.5, 1, 0.25], 128, 40)).toBe(`0,40 ${line} 128,40`);
  });

  it('empty values yield empty string', () => {
    expect(histogramLinePoints([], 100, 40)).toBe('');
  });
});

describe('downsampleBins', () => {
  it('sums adjacent bins', () => {
    expect(downsampleBins([1, 2, 3, 4, 5, 6, 7, 8], 4)).toEqual([3, 7, 11, 15]);
  });

  it('is a passthrough at full resolution', () => {
    expect(downsampleBins([1, 2, 3], 3)).toEqual([1, 2, 3]);
  });
});

describe('toInteriorChannels', () => {
  /** A readable curve at bin 100, dwarfed by a clipping spike at bin 255. */
  function clippedCurve(): number[] {
    const bins = new Array<number>(256).fill(0);
    bins[255] = 10000;
    bins[100] = 300;
    bins[101] = 150;
    return bins;
  }

  it('keeps the curve readable when the clip spike dominates', () => {
    const bins = clippedCurve();
    const out = toInteriorChannels({ luma: bins, r: null, g: null, b: null }, 256);
    // Normalized against the spike this was 0.03 of full height — a hairline.
    expect(out.luma[100]).toBeCloseTo(1, 5);
    expect(out.luma[101]).toBeCloseTo(0.5, 5);
  });

  it('drops both clipping bins from the drawn curve', () => {
    const out = toInteriorChannels(
      { luma: clippedCurve(), r: null, g: null, b: null }, 256);
    expect(out.luma[255]).toBe(0);
    expect(out.luma[0]).toBe(0);
  });

  it('still scales every channel by one shared maximum', () => {
    const spike = (at: number, height: number) => {
      const bins = new Array<number>(256).fill(0);
      bins[at] = height;
      return bins;
    };
    const out = toInteriorChannels(
      { luma: spike(90, 100), r: spike(90, 400), g: spike(90, 200), b: spike(90, 50) }, 256);
    expect(Math.max(...out.r!)).toBeCloseTo(1, 5);
    expect(Math.max(...out.g!)).toBeCloseTo(0.5, 5);
    expect(Math.max(...out.b!)).toBeCloseTo(0.125, 5);
    expect(Math.max(...out.luma)).toBeCloseTo(0.25, 5);
  });

  it('does not divide by zero when every pixel is clipped', () => {
    const bins = new Array<number>(256).fill(0);
    bins[255] = 5000;
    const out = toInteriorChannels({ luma: bins, r: null, g: null, b: null }, 64);
    expect(out.luma.every(v => v === 0)).toBe(true);
  });
});

describe('clippedChannels', () => {
  const clipped: ClipPercents = {
    shadow: { luma: 1.73, r: 9.58, g: 2.94, b: 1.63 },
    highlight: { luma: 0, r: 0.0035, g: 0, b: 0 },
  };

  it('returns only the channels above the threshold', () => {
    expect(clippedChannels(clipped, 'shadow', 2, false)).toEqual(['r', 'g']);
  });

  it('finds a single-channel clip luminance would miss entirely', () => {
    expect(clippedChannels(clipped, 'highlight', 0.001, false)).toEqual(['r']);
    expect(clipped.highlight.luma).toBe(0);
  });

  it('returns nothing when no channel reaches the threshold', () => {
    expect(clippedChannels(clipped, 'highlight', 1, false)).toEqual([]);
  });

  it('reports luminance alone for a monochrome photo', () => {
    expect(clippedChannels(clipped, 'shadow', 1, true)).toEqual(['luma']);
  });

  it('treats an unmeasured photo as unknown, never as clean', () => {
    // Threshold 0 would match every channel if null were read as zero.
    expect(clippedChannels(null, 'highlight', 0, false)).toEqual([]);
    expect(clippedChannels(undefined, 'shadow', 0, false)).toEqual([]);
  });
});
