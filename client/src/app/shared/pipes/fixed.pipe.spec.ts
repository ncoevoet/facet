import { FixedPipe } from './fixed.pipe';

describe('FixedPipe', () => {
  let pipe: FixedPipe;

  beforeEach(() => {
    pipe = new FixedPipe();
  });

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('returns empty string for undefined', () => {
    expect(pipe.transform(undefined)).toBe('');
  });

  it('formats number with default 1 decimal digit', () => {
    expect(pipe.transform(7.567)).toBe('7.6');
  });

  it('formats number with specified digits', () => {
    expect(pipe.transform(7.567, 2)).toBe('7.57');
  });

  it('formats zero with digits', () => {
    expect(pipe.transform(0, 1)).toBe('0.0');
  });

  it('formats integer with no decimals', () => {
    expect(pipe.transform(10, 0)).toBe('10');
  });

  it('pads with trailing zeros', () => {
    expect(pipe.transform(5, 2)).toBe('5.00');
  });
});
