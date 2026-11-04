import { bucketIndexOf, normalizeBars, percentileOf, topPercentOf } from './metric-distribution';

const range = { min: 0, max: 10, buckets: [10, 0, 0, 0, 0, 0, 0, 0, 0, 10] };

describe('metric-distribution', () => {
  it('normalizes bars to the tallest bucket', () => {
    expect(normalizeBars([1, 2, 4])).toEqual([25, 50, 100]);
    expect(normalizeBars([0, 0])).toEqual([0, 0]);
  });

  it('places a value in the bucket the server counted it in', () => {
    expect(bucketIndexOf(range, 0)).toBe(0);
    expect(bucketIndexOf(range, 0.99)).toBe(0);
    expect(bucketIndexOf(range, 1)).toBe(1);
    expect(bucketIndexOf(range, 10)).toBe(9);
    expect(bucketIndexOf(range, -5)).toBe(0);
    expect(bucketIndexOf(range, 50)).toBe(9);
  });

  it('interpolates the share of the library below a value', () => {
    expect(percentileOf(range, 0)).toBe(0);
    expect(percentileOf(range, 5)).toBe(50);
    expect(percentileOf(range, 9.5)).toBe(75);
    expect(percentileOf(range, 10)).toBe(100);
  });

  it('ranks a value as the share of the library at or above it, floored at 1', () => {
    expect(topPercentOf(range, 5)).toBe(50);
    expect(topPercentOf(range, 9.5)).toBe(25);
    expect(topPercentOf(range, 10)).toBe(1);
    expect(topPercentOf(range, 0)).toBe(100);
    expect(topPercentOf(range, null)).toBeNull();
  });

  it('ranks a lower-is-better field from the bottom', () => {
    const noise = { ...range, column: 'noise_sigma' };
    expect(topPercentOf(noise, 0)).toBe(1);
    expect(topPercentOf(noise, 9.5)).toBe(75);
    expect(topPercentOf(noise, 10)).toBe(100);
  });

  it('does not rank a field with no better end', () => {
    expect(topPercentOf({ ...range, column: 'mean_luminance' }, 10)).toBeNull();
    expect(topPercentOf({ ...range, column: 'f_stop' }, 10)).toBeNull();
  });

  it('has no percentile without a value or a spread to place it in', () => {
    expect(percentileOf(range, null)).toBeNull();
    expect(percentileOf({ min: 3, max: 3, buckets: [5] }, 3)).toBeNull();
    expect(percentileOf({ min: 0, max: 1, buckets: [0, 0] }, 0.5)).toBeNull();
  });
});


it('places finite extreme scores without overflowing the marker or rank', () => {
  const range = {min: -1e308, max: 1e308, buckets: Array(32).fill(1)};
  expect(bucketIndexOf(range, 0)).toBe(16);
  expect(percentileOf(range, 0)).toBe(50);
  expect(bucketIndexOf({min: 0, max: 1e308, buckets: Array(32).fill(1)}, 1e307)).toBe(3);
});
