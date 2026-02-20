import { IncludesPipe, IndexOfPipe } from './array.pipe';

describe('IncludesPipe', () => {
  let pipe: IncludesPipe;

  beforeEach(() => {
    pipe = new IncludesPipe();
  });

  it('returns true when item is in array', () => {
    expect(pipe.transform(['a', 'b', 'c'], 'b')).toBe(true);
  });

  it('returns false when item is not in array', () => {
    expect(pipe.transform(['a', 'b', 'c'], 'd')).toBe(false);
  });

  it('works with empty array', () => {
    expect(pipe.transform([], 'a')).toBe(false);
  });

  it('works with numbers', () => {
    expect(pipe.transform([1, 2, 3], 2)).toBe(true);
    expect(pipe.transform([1, 2, 3], 4)).toBe(false);
  });

  it('uses strict equality', () => {
    expect(pipe.transform([1, 2], '1')).toBe(false);
  });
});

describe('IndexOfPipe', () => {
  let pipe: IndexOfPipe;

  beforeEach(() => {
    pipe = new IndexOfPipe();
  });

  it('returns index of item in array', () => {
    expect(pipe.transform(['a', 'b', 'c'], 'b')).toBe(1);
  });

  it('returns -1 when item is not in array', () => {
    expect(pipe.transform(['a', 'b', 'c'], 'd')).toBe(-1);
  });

  it('returns first index when duplicates exist', () => {
    expect(pipe.transform(['a', 'b', 'a'], 'a')).toBe(0);
  });

  it('works with empty array', () => {
    expect(pipe.transform([], 'a')).toBe(-1);
  });
});
