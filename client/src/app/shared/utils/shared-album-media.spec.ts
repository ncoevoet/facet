import { sharedAlbumMediaUrl, sharedAssetPhoto } from './shared-album-media';
import { ThumbnailUrlPipe } from '../pipes/thumbnail-url.pipe';

describe('shared album media URLs', () => {
  it('encodes the exact album capability and keeps every rendition off service-worker storage', () => {
    const asset = '17.' + 'a'.repeat(64);
    const scope = { albumId: 17, token: 'fixture+token&value' };
    for (const kind of ['thumbnail', 'image', 'download'] as const) {
      const url = new URL(sharedAlbumMediaUrl(scope, kind, asset, 160, 'revision&one'), 'http://facet.test');
      expect(url.pathname).toBe(`/api/shared/album/17/media/${kind}`);
      expect(url.searchParams.get('token')).toBe(scope.token);
      expect(url.searchParams.get('asset_id')).toBe(asset);
      expect(url.searchParams.get('preview')).toBe('revision&one');
      expect(url.searchParams.get('ngsw-bypass')).toBe('1');
      expect(url.searchParams.has('profile')).toBe(false);
    }
    expect(new ThumbnailUrlPipe().transform('/p.jpg', 160, 'v', scope))
      .toBe(sharedAlbumMediaUrl(scope, 'thumbnail', '/p.jpg', 160, 'v'));
  });

  it('rejects a legacy path payload instead of using a native library path', () => {
    expect(() => sharedAssetPhoto({ path: '/private/a.jpg' } as never)).toThrow();
  });

  it('accepts signed asset identities and rejects malformed handles', () => {
    const valid = '17.' + 'a'.repeat(64);
    expect(sharedAssetPhoto({ asset_id: valid, filename: 'public.jpg' } as never).path).toBe(valid);
    for (const asset_id of ['', '01.' + 'a'.repeat(64), '17.' + 'A'.repeat(64), '17.' + 'a'.repeat(63), valid + '/private']) {
      expect(() => sharedAssetPhoto({ asset_id } as never)).toThrow();
    }
    const url = new URL(sharedAlbumMediaUrl({ albumId: 17, token: 'grant' }, 'image', valid), 'http://facet.test');
    expect(url.searchParams.has('size')).toBe(false);
    expect(url.searchParams.has('preview')).toBe(false);
  });

  it('refuses invalid grants instead of falling back to ordinary library URLs', () => {
    for (const albumId of [0, -1, NaN, 1.5]) {
      expect(() => sharedAlbumMediaUrl({ albumId, token: 'fixture' }, 'image', '/a.jpg')).toThrow();
    }
    expect(() => sharedAlbumMediaUrl({ albumId: 1, token: '' }, 'download', '/a.jpg')).toThrow();
  });
});
