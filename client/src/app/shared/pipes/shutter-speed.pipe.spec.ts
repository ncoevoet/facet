import { ShutterSpeedPipe } from './shutter-speed.pipe';

describe('ShutterSpeedPipe', () => {
  let pipe: ShutterSpeedPipe;

  beforeEach(() => {
    pipe = new ShutterSpeedPipe();
  });

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('returns empty string for undefined', () => {
    expect(pipe.transform(undefined)).toBe('');
  });

  it('returns empty string for 0', () => {
    expect(pipe.transform(0)).toBe('');
  });

  it('returns empty string for negative value', () => {
    expect(pipe.transform(-1)).toBe('');
  });

  it('returns empty string for NaN string', () => {
    expect(pipe.transform('abc')).toBe('');
  });

  it('formats shutter speed >= 1s as decimal seconds', () => {
    expect(pipe.transform(1)).toBe('1.0s');
    expect(pipe.transform(2)).toBe('2.0s');
    expect(pipe.transform(30)).toBe('30.0s');
  });

  it('formats fast shutter as fraction', () => {
    expect(pipe.transform(0.001)).toBe('1/1000');
    expect(pipe.transform(0.01)).toBe('1/100');
    expect(pipe.transform(0.5)).toBe('1/2');
  });

  it('handles string numeric input', () => {
    expect(pipe.transform('0.001')).toBe('1/1000');
    expect(pipe.transform('2')).toBe('2.0s');
  });
});
