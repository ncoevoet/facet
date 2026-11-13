import { MegapixelsPipe } from './megapixels.pipe';

describe('MegapixelsPipe', () => {
  const pipe = new MegapixelsPipe();

  it('formats width x height as megapixels with one decimal', () => {
    expect(pipe.transform(6000, 4000)).toBe('24.0 MP');
    expect(pipe.transform(6048, 4024)).toBe('24.3 MP');
    expect(pipe.transform(6048, 4024, 'fr')).toBe('24,3 MP');
  });

  it('returns an empty string when a side is missing or zero', () => {
    expect(pipe.transform(null, 4000)).toBe('');
    expect(pipe.transform(6000, undefined)).toBe('');
    expect(pipe.transform(0, 4000)).toBe('');
  });
});
