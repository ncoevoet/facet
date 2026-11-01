import { sharedAlbumMediaUrl } from './shared-album-media';
import { ThumbnailUrlPipe } from '../pipes/thumbnail-url.pipe';

describe('shared album media URLs', () => {
  it('encodes the exact album capability and keeps every rendition off service-worker storage', () => {
    const scope = { albumId: 17, token: 'fixture+token&value' };
    for (const kind of ['thumbnail', 'image', 'download'] as const) {
      const url = new URL(sharedAlbumMediaUrl(scope, kind, '/Été/a & b.jpg', 160, 'revision&one'), 'http://facet.test');
      expect(url.pathname).toBe(`/api/shared/album/17/media/${kind}`);
      expect(url.searchParams.get('token')).toBe(scope.token);
      expect(url.searchParams.get('path')).toBe('/Été/a & b.jpg');
      expect(url.searchParams.get('preview')).toBe('revision&one');
      expect(url.searchParams.get('ngsw-bypass')).toBe('1');
      expect(url.searchParams.has('profile')).toBe(false);
    }
    expect(new ThumbnailUrlPipe().transform('/p.jpg', 160, 'v', scope))
      .toBe(sharedAlbumMediaUrl(scope, 'thumbnail', '/p.jpg', 160, 'v'));
  });

  it('refuses invalid grants instead of falling back to ordinary library URLs', () => {
    for (const albumId of [0, -1, NaN, 1.5]) {
      expect(() => sharedAlbumMediaUrl({ albumId, token: 'fixture' }, 'image', '/a.jpg')).toThrow();
    }
    expect(() => sharedAlbumMediaUrl({ albumId: 1, token: '' }, 'download', '/a.jpg')).toThrow();
  });
});
