import { StarArrayPipe, IsStarFilledPipe } from './star-rating.pipe';

describe('StarArrayPipe', () => {
  let pipe: StarArrayPipe;

  beforeEach(() => {
    pipe = new StarArrayPipe();
  });

  it('returns array of 5 stars [1, 2, 3, 4, 5]', () => {
    expect(pipe.transform(null)).toEqual([1, 2, 3, 4, 5]);
  });

  it('returns the same reference every time (static array)', () => {
    expect(pipe.transform(undefined)).toBe(pipe.transform(undefined));
  });
});

describe('IsStarFilledPipe', () => {
  let pipe: IsStarFilledPipe;

  beforeEach(() => {
    pipe = new IsStarFilledPipe();
  });

  it('uses hover rating when provided', () => {
    expect(pipe.transform(3, 1, 4)).toBe(true);
    expect(pipe.transform(5, 1, 4)).toBe(false);
  });

  it('uses current rating when no hover rating', () => {
    expect(pipe.transform(3, 4, null)).toBe(true);
    expect(pipe.transform(5, 4, null)).toBe(false);
  });

  it('uses current rating when hover rating is undefined', () => {
    expect(pipe.transform(2, 3, undefined)).toBe(true);
    expect(pipe.transform(4, 3, undefined)).toBe(false);
  });

  it('returns false for all stars when no rating at all', () => {
    expect(pipe.transform(1, null, null)).toBe(false);
    expect(pipe.transform(5, null, undefined)).toBe(false);
  });

  it('hover rating takes precedence over current rating', () => {
    // hover=2, current=5 — only stars 1 and 2 filled
    expect(pipe.transform(2, 5, 2)).toBe(true);
    expect(pipe.transform(3, 5, 2)).toBe(false);
  });
});
