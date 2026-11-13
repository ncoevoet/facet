import { ExposureCompensationPipe } from './exposure-compensation.pipe';

describe('ExposureCompensationPipe', () => {
  const pipe = new ExposureCompensationPipe();

  it('signs positive and negative values', () => {
    expect(pipe.transform(0.7)).toBe('+0.7 EV');
    expect(pipe.transform(-1)).toBe('\u22121 EV');
    expect(pipe.transform(2)).toBe('+2 EV');
  });

  it('renders zero, and values that round to zero, as 0 EV', () => {
    expect(pipe.transform(0)).toBe('0 EV');
    expect(pipe.transform(-0.04)).toBe('0 EV');
  });

  it('rounds the 1/3 stop steps to one decimal', () => {
    expect(pipe.transform(0.333)).toBe('+0.3 EV');
    expect(pipe.transform(-0.667)).toBe('\u22120.7 EV');
    expect(pipe.transform(-0.667, 'de')).toBe('\u22120,7 EV');
  });

  it('returns an empty string for null or undefined', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
  });
});
