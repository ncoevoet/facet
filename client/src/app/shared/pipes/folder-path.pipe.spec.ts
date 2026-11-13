import { FolderPathPipe } from './folder-path.pipe';

describe('FolderPathPipe', () => {
  const pipe = new FolderPathPipe();

  it('returns the directory of a POSIX path', () => {
    expect(pipe.transform('/photos/2024/IMG_1.jpg')).toBe('/photos/2024');
  });

  it('returns the directory of a Windows path', () => {
    expect(pipe.transform('C:\\photos\\2024\\IMG_1.jpg')).toBe('C:\\photos\\2024');
  });

  it('keeps the root for a file directly under it', () => {
    expect(pipe.transform('/IMG_1.jpg')).toBe('/');
  });

  it('returns an empty string for a bare name, null or undefined', () => {
    expect(pipe.transform('IMG_1.jpg')).toBe('');
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
  });
});
