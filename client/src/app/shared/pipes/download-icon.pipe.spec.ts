import { DownloadIconPipe } from './download-icon.pipe';

describe('DownloadIconPipe', () => {
  const pipe = new DownloadIconPipe();

  it('returns photo_filter for darktable', () => {
    expect(pipe.transform('darktable')).toBe('photo_filter');
  });

  it('returns raw_on for raw', () => {
    expect(pipe.transform('raw')).toBe('raw_on');
  });

  it('returns image for original', () => {
    expect(pipe.transform('original')).toBe('image');
  });

  it('returns image for unknown types', () => {
    expect(pipe.transform('unknown')).toBe('image');
    expect(pipe.transform('')).toBe('image');
  });
});
