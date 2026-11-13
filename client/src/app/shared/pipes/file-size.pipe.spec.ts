import { FileSizePipe } from './file-size.pipe';

describe('FileSizePipe', () => {
  const pipe = new FileSizePipe();

  it('returns an empty string for null, undefined and negative values', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
    expect(pipe.transform(-1)).toBe('');
  });

  it('keeps small sizes in bytes and zero meaningful', () => {
    expect(pipe.transform(0, 'en')).toContain('0');
    expect(pipe.transform(512, 'en')).toContain('512');
  });

  it('scales by 1000 to the SI kB, MB and GB its labels name', () => {
    expect(pipe.transform(1500, 'en')).toMatch(/^1\.5\s?kB$/i);
    expect(pipe.transform(5_000_000, 'en')).toMatch(/^5\s?MB$/);
    expect(pipe.transform(3_000_000_000, 'en')).toMatch(/^3\s?GB$/);
    expect(pipe.transform(999, 'en')).toMatch(/^999\s?byte/);
  });

  it('formats with the given locale', () => {
    expect(pipe.transform(1536, 'de')).toContain('1,5');
  });
});
