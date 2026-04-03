import { IsLensNamePipe } from './is-lens-name.pipe';

describe('IsLensNamePipe', () => {
  const pipe = new IsLensNamePipe();

  it('returns true for lens names containing "mm"', () => {
    expect(pipe.transform('EF 50mm f/1.4')).toBe(true);
    expect(pipe.transform('RF135mm F1.8L')).toBe(true);
  });

  it('returns true for lens names containing "f/"', () => {
    expect(pipe.transform('Sigma Art f/1.4')).toBe(true);
  });

  it('returns false for camera body names', () => {
    expect(pipe.transform('Canon EOS R6')).toBe(false);
    expect(pipe.transform('Nikon Z8')).toBe(false);
  });

  it('returns false for null/empty', () => {
    expect(pipe.transform(null)).toBe(false);
    expect(pipe.transform('')).toBe(false);
  });
});
