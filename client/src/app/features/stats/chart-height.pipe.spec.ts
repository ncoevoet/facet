import { ChartHeightPipe } from './chart-height.pipe';

describe('ChartHeightPipe', () => {
  const pipe = new ChartHeightPipe();

  it('returns the 200px minimum for an empty array', () => {
    expect(pipe.transform([])).toBe(200);
  });

  it('returns the 200px minimum when count * default rowHeight is below 200', () => {
    // 7 * 28 = 196 < 200
    expect(pipe.transform(new Array(7).fill(0))).toBe(200);
  });

  it('returns the boundary 200 when count * rowHeight exactly equals 200', () => {
    expect(pipe.transform(new Array(8).fill(0), 25)).toBe(200);
  });

  it('scales by the default row height of 28 above the minimum', () => {
    // 10 * 28 = 280 > 200
    expect(pipe.transform(new Array(10).fill(0))).toBe(280);
  });

  it('uses a custom row height when provided', () => {
    expect(pipe.transform(new Array(10).fill(0), 40)).toBe(400);
  });

  it('returns minimum when custom row height keeps total below 200', () => {
    expect(pipe.transform(new Array(5).fill(0), 10)).toBe(200);
  });

  it('handles a single item (still clamps to minimum)', () => {
    expect(pipe.transform([1])).toBe(200);
  });

  it('handles large item counts', () => {
    expect(pipe.transform(new Array(1000).fill(0), 28)).toBe(28000);
  });
});
