import { basename, copyLines } from './clipboard';

describe('basename', () => {
  it('extracts the filename from a unix-style path', () => {
    expect(basename('/a/b/photo.jpg')).toBe('photo.jpg');
  });

  it('extracts the filename from a windows-style path', () => {
    expect(basename('C:\\Users\\alice\\photo.jpg')).toBe('photo.jpg');
  });

  it('extracts the filename from a mixed-separator path', () => {
    expect(basename('C:\\Users\\alice/photos/photo.jpg')).toBe('photo.jpg');
  });

  it('returns the input unchanged when there is no path separator', () => {
    expect(basename('photo.jpg')).toBe('photo.jpg');
  });

  it('returns an empty string for a path with a trailing separator', () => {
    expect(basename('/a/b/')).toBe('');
  });
});

describe('copyLines', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('joins the lines with newlines and writes them to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    await copyLines(['a.jpg', 'b.jpg', 'c.jpg']);

    expect(writeText).toHaveBeenCalledWith('a.jpg\nb.jpg\nc.jpg');
  });

  it('resolves when the clipboard write succeeds', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    await expect(copyLines(['a.jpg'])).resolves.toBeUndefined();
  });

  it('propagates the rejection when the clipboard write fails (no internal fallback)', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    Object.assign(navigator, { clipboard: { writeText } });

    await expect(copyLines(['a.jpg'])).rejects.toThrow('denied');
  });
});
