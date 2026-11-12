import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { privateImageCacheKey, resetPrivateImageSession } from '../utils/private-image-session';
import { ThumbnailUrlPipe, ImageUrlPipe, FaceThumbnailUrlPipe, PersonThumbnailUrlPipe,
  thumbnailUrl, thumbnailSrcset, imageUrl, faceThumbnailUrl, personThumbnailUrl } from './thumbnail-url.pipe';

@Component({
  imports: [ThumbnailUrlPipe, ImageUrlPipe, FaceThumbnailUrlPipe, PersonThumbnailUrlPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <img alt="Thumbnail" [src]="path | thumbnailUrl:160" />
    <img alt="Original" [src]="path | imageUrl" />
    <img alt="Face" [src]="42 | faceThumbnailUrl" />
    <img alt="Person" [src]="7 | personThumbnailUrl" />
  `,
})
class PrivateImagesHost {
  readonly path = '/photos/shared.jpg';
}

describe('private image sessions', () => {
  it('keeps all helper URLs stable until the opaque session nonce rotates', () => {
    const urls = () => [thumbnailUrl('/photos/shared.jpg', 160), imageUrl('/photos/shared.jpg'),
      faceThumbnailUrl(42), personThumbnailUrl(7)];
    const before = urls();
    const firstKey = privateImageCacheKey();
    expect(firstKey).toMatch(/^[a-f0-9]{32}$/);
    expect(urls()).toEqual(before);
    for (const url of before) {
      expect(new URL(url, 'http://facet.test').searchParams.get('session')).toBe(firstKey);
    }
    resetPrivateImageSession();
    expect(privateImageCacheKey()).not.toBe(firstKey);
    expect(privateImageCacheKey()).toMatch(/^[a-f0-9]{32}$/);
    for (const [index, url] of urls().entries()) {
      expect(url).not.toBe(before[index]);
      expect(new URL(url, 'http://facet.test').searchParams.get('session')).toBe(privateImageCacheKey());
    }
    const after = urls();
    expect(urls()).toEqual(after);
  });

  it('updates already-mounted OnPush images when only the session changes', async () => {
    const fixture = TestBed.createComponent(PrivateImagesHost);
    fixture.autoDetectChanges();
    await fixture.whenStable();
    const images = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('img'));
    const before = images.map(image => image.getAttribute('src'));
    expect(images).toHaveLength(4);
    expect(before.every(src => src !== null)).toBe(true);
    resetPrivateImageSession();
    // No new path input, manual detectChanges, or component reconstruction.
    await fixture.whenStable();
    for (const [index, image] of images.entries()) {
      expect(image.getAttribute('src')).not.toBe(before[index]);
      const url = new URL(image.src);
      expect(url.searchParams.get('session')).toBe(privateImageCacheKey());
      expect(url.searchParams.get('ngsw-bypass')).toBe('1');
    }
  });

  it('generates fresh opaque keys without putting the stored credential in URLs', () => {
    const previous = localStorage.getItem('facet_token');
    const credential = 'private-account-secret-token';
    try {
      localStorage.setItem('facet_token', credential);
      resetPrivateImageSession();
      const first = privateImageCacheKey();
      resetPrivateImageSession();
      expect(privateImageCacheKey()).not.toBe(first);
      expect(privateImageCacheKey()).toMatch(/^[a-f0-9]{32}$/);
      for (const url of [thumbnailUrl('/p.jpg'), imageUrl('/p.jpg'), faceThumbnailUrl(42), personThumbnailUrl(7)]) {
        expect(url).not.toContain(credential);
        expect(new URL(url, 'http://facet.test').searchParams.get('session')).toBe(privateImageCacheKey());
      }
    } finally {
      if (previous === null) localStorage.removeItem('facet_token');
      else localStorage.setItem('facet_token', previous);
    }
  });
});

describe('ThumbnailUrlPipe', () => {
  let pipe: ThumbnailUrlPipe;

  beforeEach(() => {
    pipe = new ThumbnailUrlPipe();
  });

  it('returns URL with path param', () => {
    const url = pipe.transform('/photos/test.jpg');
    expect(url).toContain('path=%2Fphotos%2Ftest.jpg');
    expect(url.startsWith('/thumbnail?')).toBe(true);
  });

  it('includes size param when provided', () => {
    const url = pipe.transform('/photos/test.jpg', 640);
    expect(url).toContain('size=640');
  });

  it('versions all private image URLs and bypasses existing service-worker caches', () => {
    for (const size of [undefined, 48, 160, 640, 641, 1920]) {
      const params = new URL(pipe.transform('/photos/test.jpg', size), 'http://x').searchParams;
      expect(params.get('v')).toBe('3');
      expect(params.has('ngsw-bypass')).toBe(true);
    }
  });

  it('omits size param when not provided', () => {
    const url = pipe.transform('/photos/test.jpg');
    expect(url).not.toContain('size=');
  });

  it('handles paths with special characters', () => {
    const url = pipe.transform('/photos/my photo.jpg');
    expect(url).toContain('path=');
    expect(url).not.toContain(' ');
  });
});

describe('explicit thumbnail preview revisions', () => {
  it('encodes revisions while keeping every representation behind authorization', () => {
    const pipe = new ThumbnailUrlPipe();
    const path = '/photos/a b.jpg';
    const revised = new URL(pipe.transform(path, 160, 'load+1&2'), 'http://facet.test');
    expect(revised.searchParams.get('path')).toBe(path);
    expect(revised.searchParams.get('preview')).toBe('load+1&2');
    expect(revised.searchParams.get('ngsw-bypass')).toBe('1');
    const sharp = new URL(pipe.transform(path, 1920, 'load+1&2'), 'http://facet.test');
    expect(sharp.searchParams.get('preview')).toBe('load+1&2');
    expect(sharp.searchParams.get('v')).toBe('3');
    expect(sharp.searchParams.get('ngsw-bypass')).toBe('1');
    expect(pipe.transform(path, 160, null)).toBe(pipe.transform(path, 160));
    expect(pipe.transform(path, 160)).toContain('ngsw-bypass');
  });
});

describe('thumbnailSrcset', () => {
  it('offers the 320 px resize and the stored thumbnail, each a parseable candidate', () => {
    // A comma or space left raw in a URL would split the srcset into bogus candidates.
    const candidates = thumbnailSrcset('/photos/a, b.jpg', 'r1').split(', ').map((c) => c.split(' '));
    expect(candidates.map(([, w]) => w)).toEqual(['320w', '640w']);
    for (const [url, w] of candidates) {
      const parsed = new URL(url, 'http://facet.test');
      expect(parsed.searchParams.get('path')).toBe('/photos/a, b.jpg');
      expect(parsed.searchParams.get('size')).toBe(w.slice(0, -1));
      expect(parsed.searchParams.get('preview')).toBe('r1');
    }
  });
});

describe('ImageUrlPipe', () => {
  let pipe: ImageUrlPipe;

  beforeEach(() => {
    pipe = new ImageUrlPipe();
  });

  it('returns full-size image URL with path param', () => {
    const url = pipe.transform('/photos/test.jpg');
    expect(url.startsWith('/image?')).toBe(true);
    expect(url).toContain('path=%2Fphotos%2Ftest.jpg');
    const params = new URL(url, 'http://facet.test').searchParams;
    expect(params.get('v')).toBe('3');
    expect(params.get('ngsw-bypass')).toBe('1');
  });

  it('does not include a size param', () => {
    const url = pipe.transform('/photos/test.jpg');
    expect(url).not.toContain('size=');
  });
});

describe('FaceThumbnailUrlPipe', () => {
  let pipe: FaceThumbnailUrlPipe;

  beforeEach(() => {
    pipe = new FaceThumbnailUrlPipe();
  });

  it('returns face thumbnail URL with face id', () => {
    const url = new URL(pipe.transform(42), 'http://facet.test');
    expect(url.pathname).toBe('/face_thumbnail/42');
    expect(url.searchParams.get('v')).toBe('2');
    expect(url.searchParams.get('ngsw-bypass')).toBe('1');
  });

  it('handles id 0', () => {
    expect(new URL(pipe.transform(0), 'http://facet.test').pathname).toBe('/face_thumbnail/0');
  });
});

describe('PersonThumbnailUrlPipe', () => {
  let pipe: PersonThumbnailUrlPipe;

  beforeEach(() => {
    pipe = new PersonThumbnailUrlPipe();
  });

  it('returns person thumbnail URL with person id', () => {
    const url = new URL(pipe.transform(7), 'http://facet.test');
    expect(url.pathname).toBe('/person_thumbnail/7');
    expect(url.searchParams.get('v')).toBe('2');
    expect(url.searchParams.get('ngsw-bypass')).toBe('1');
  });

  it('handles large ids', () => {
    expect(new URL(pipe.transform(9999), 'http://facet.test').pathname).toBe('/person_thumbnail/9999');
  });
});


describe('per-photo preview revisions', () => {
  it('keeps stored thumbnail revisions distinct without service-worker caching', () => {
    const pipe = new ThumbnailUrlPipe();
    const first = pipe.transform('/photo a.jpg', 160, 'one&value');
    const second = pipe.transform('/photo a.jpg', 160, 'second');
    expect(first).not.toEqual(second);
    expect(new URL(first, 'http://localhost').searchParams.get('preview')).toBe('one&value');
    expect(first).toContain('ngsw-bypass');
    expect(pipe.transform('/a.jpg', 1920, 'second')).toContain('ngsw-bypass=1');
  });

  it('also versions full-image URLs', () => {
    expect(new ImageUrlPipe().transform('/a.jpg', false, 'new')).toContain('preview=new');
  });
});
