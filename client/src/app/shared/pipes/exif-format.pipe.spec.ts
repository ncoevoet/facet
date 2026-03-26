import {
  ApertureFormatPipe,
  FocalLengthFormatPipe,
  IsoFormatPipe,
  LuminanceFormatPipe,
  FaceRatioFormatPipe,
} from './exif-format.pipe';

describe('ApertureFormatPipe', () => {
  const pipe = new ApertureFormatPipe();

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('returns empty string for undefined', () => {
    expect(pipe.transform(undefined)).toBe('');
  });

  it('formats integer aperture without decimal', () => {
    expect(pipe.transform(2)).toBe('f/2');
    expect(pipe.transform(8)).toBe('f/8');
  });

  it('formats fractional aperture with one decimal', () => {
    expect(pipe.transform(1.4)).toBe('f/1.4');
    expect(pipe.transform(2.8)).toBe('f/2.8');
    expect(pipe.transform(5.6)).toBe('f/5.6');
  });
});

describe('FocalLengthFormatPipe', () => {
  const pipe = new FocalLengthFormatPipe();

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('formats with mm suffix', () => {
    expect(pipe.transform(50)).toBe('50mm');
    expect(pipe.transform(200)).toBe('200mm');
  });

  it('rounds fractional values', () => {
    expect(pipe.transform(85.5)).toBe('86mm');
  });
});

describe('IsoFormatPipe', () => {
  const pipe = new IsoFormatPipe();

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('formats with ISO prefix', () => {
    expect(pipe.transform(100)).toBe('ISO 100');
  });

  it('formats large values with locale separator', () => {
    expect(pipe.transform(6400)).toBe('ISO 6,400');
  });
});

describe('LuminanceFormatPipe', () => {
  const pipe = new LuminanceFormatPipe();

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('formats as percentage', () => {
    expect(pipe.transform(0.15)).toBe('15%');
    expect(pipe.transform(1.0)).toBe('100%');
  });
});

describe('FaceRatioFormatPipe', () => {
  const pipe = new FaceRatioFormatPipe();

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('formats as percentage', () => {
    expect(pipe.transform(0.05)).toBe('5%');
    expect(pipe.transform(0.8)).toBe('80%');
  });
});
