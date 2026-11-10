import { PRIVATE_IMAGE_SESSION_STORAGE_KEY } from './private-image-session';

describe('private image session', () => {
  const load = async () => {
    vi.resetModules();
    return import('./private-image-session');
  };

  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('reuses the stored key after a reload, so the browser can revalidate its images', async () => {
    const first = await load();
    first.confirmPrivateImageOwner('1|alice');
    const key = first.privateImageCacheKey();
    const reloaded = await load();
    expect(reloaded.privateImageCacheKey()).toBe(key);
    reloaded.confirmPrivateImageOwner('1|alice');
    expect(reloaded.privateImageCacheKey()).toBe(key);
  });

  it('replaces a stored key that served another identity', async () => {
    const first = await load();
    first.confirmPrivateImageOwner('1|alice');
    const aliceKey = first.privateImageCacheKey();
    const reloaded = await load();
    reloaded.confirmPrivateImageOwner('1|bob');
    expect(reloaded.privateImageCacheKey()).not.toBe(aliceKey);
    expect(JSON.parse(localStorage.getItem(PRIVATE_IMAGE_SESSION_STORAGE_KEY)!)).toEqual({ owner: '1|bob', key: reloaded.privateImageCacheKey() });
  });

  it('gives each document its own history key while reusing the image URL key', async () => {
    const first = await load();
    first.confirmPrivateImageOwner('1|alice');
    const reloaded = await load();
    expect(reloaded.privateImageCacheKey()).toBe(first.privateImageCacheKey());
    expect(reloaded.privateImageSessionKey()).not.toBe(first.privateImageSessionKey());
  });

  it('changes the history key exactly when the image URL key changes', async () => {
    const loaded = await load();
    loaded.confirmPrivateImageOwner('1|alice');
    const session = loaded.privateImageSessionKey();
    loaded.confirmPrivateImageOwner('1|alice');
    expect(loaded.privateImageSessionKey()).toBe(session);
    loaded.resetPrivateImageSession();
    expect(loaded.privateImageSessionKey()).not.toBe(session);
  });

  it('starts a new key when the stored entry is unreadable', async () => {
    localStorage.setItem(PRIVATE_IMAGE_SESSION_STORAGE_KEY, '{"owner":null,"key":"not-hex"}');
    const loaded = await load();
    expect(loaded.privateImageCacheKey()).toMatch(/^[a-f0-9]{32}$/);
  });
});
