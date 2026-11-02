import { clearThumbnailCaches } from './thumbnail-cache';

describe('clearThumbnailCaches', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('clears retained entries and can reach later refills without touching unrelated caches', async () => {
    const request = new Request('http://localhost/thumbnail?path=fixture');
    const bytes = new Map([[request, 'private']]);
    const cache = {
      keys: async () => [...bytes.keys()],
      delete: vi.fn(async (key: Request) => bytes.delete(key)),
    };
    const open = vi.fn<(name: string) => Promise<typeof cache>>(async () => cache);
    const deleteNamespace = vi.fn();
    vi.stubGlobal('caches', {
      keys: async () => ['ngsw:/:1:thumbnails:cache', 'ngsw:/:1:thumbnails:age', 'unrelated'],
      open, delete: deleteNamespace,
    });
    await clearThumbnailCaches();
    expect(bytes.size).toBe(0);
    expect(open.mock.calls.map(call => call[0])).toEqual([
      'ngsw:/:1:thumbnails:cache', 'ngsw:/:1:thumbnails:age',
    ]);
    expect(deleteNamespace).not.toHaveBeenCalled();
    bytes.set(request, 'later worker refill');
    await clearThumbnailCaches();
    expect(bytes.size).toBe(0);
  });

  it('continues cleanup when one cache or entry is unavailable', async () => {
    const first = new Request('http://localhost/thumbnail?path=first');
    const second = new Request('http://localhost/thumbnail?path=second');
    const remove = vi.fn(async (request: Request) => {
      if (request === first) throw new Error('storage failure');
      return true;
    });
    vi.stubGlobal('caches', {
      keys: async () => ['ngsw:thumbnails:unavailable', 'ngsw:thumbnails:cache'],
      open: async (name: string) => {
        if (name.endsWith('unavailable')) throw new Error('storage disabled');
        return { keys: async () => [first, second], delete: remove };
      },
    });
    await expect(clearThumbnailCaches()).resolves.toBeUndefined();
    expect(remove).toHaveBeenCalledWith(second);
  });

  it('tolerates unavailable cache storage', async () => {
    vi.stubGlobal('caches', { keys: async () => { throw new Error('disabled'); } });
    await expect(clearThumbnailCaches()).resolves.toBeUndefined();
  });
});
