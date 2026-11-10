import { imageRetryUrl } from './image-retry-url';

describe('image rendition retries', () => {
  it('preserves exact capability and preview values while replacing an old retry', () => {
    const source = '/api/shared/album/7/media/image?asset_id=7.signed&token=a%2Bb%26c&preview=revision%26one&facet_retry=old#crop';
    const url = new URL(imageRetryUrl(source, 'session-2'));
    expect(url.pathname).toBe('/api/shared/album/7/media/image');
    expect(url.searchParams.get('token')).toBe('a+b&c');
    expect(url.searchParams.get('preview')).toBe('revision&one');
    expect(url.searchParams.getAll('facet_retry')).toEqual(['session-2']);
    expect(url.searchParams.get('ngsw-bypass')).toBe('1');
    expect(url.hash).toBe('#crop');
  });
});
