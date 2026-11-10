import { randomUuid } from './random-uuid';

describe('randomUuid', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses the native generator when available', () => {
    const native = vi.fn(() => 'native-uuid');
    vi.stubGlobal('crypto', { randomUUID: native });
    expect(randomUuid()).toBe('native-uuid');
    expect(native).toHaveBeenCalledOnce();
  });

  it('preserves random bytes while setting UUID v4 version and variant on HTTP LAN', () => {
    const fill = vi.fn((bytes: Uint8Array) => {
      bytes.fill(255);
      bytes[0] = 1;
      return bytes;
    });
    vi.stubGlobal('crypto', { getRandomValues: fill });
    expect(randomUuid()).toBe('01ffffff-ffff-4fff-bfff-ffffffffffff');
    expect(fill).toHaveBeenCalledOnce();
    expect(fill.mock.calls[0][0]).toHaveLength(16);
  });
});
