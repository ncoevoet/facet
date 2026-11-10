import { Pipe, PipeTransform } from '@angular/core';
import { privateImageCacheKey } from '../utils/private-image-session';
import { SharedAlbumMediaScope, sharedAlbumMediaUrl } from '../utils/shared-album-media';

/** Largest `size` served from the stored thumbnail. Mirrors the server's render
 *  THRESHOLD (`_STORED_THUMBNAIL_SIZE` in api/routers/thumbnails.py), not the
 *  configurable edge the thumbnails are stored at. */
export const STORED_THUMBNAIL_EDGE = 640;
/** Edge of the single render the server produces above the threshold (mirrors
 *  `_RENDERED_SIZE`). */
export const RENDERED_THUMBNAIL_EDGE = 1920;
/** Bump all library URLs past old public browser entries. Bypass even an older
 *  active service worker, whose thumbnail data cache ignores Cache-Control. */
export const PRIVATE_IMAGE_URL_VERSION = '3';

/** Version of the face and person crop URLs, bumped apart from library images. */
const PRIVATE_CROP_URL_VERSION = '2';

/** The query tail of every private image URL: its version, the service-worker
 *  bypass and the account's image key. */
function privateImageQuery(params: URLSearchParams, version = PRIVATE_IMAGE_URL_VERSION): string {
  params.set('v', version);
  params.set('ngsw-bypass', '1');
  params.set('session', privateImageCacheKey());
  return params.toString();
}

/** Impure pipes track the image-key signal even when their inputs are unchanged.
 *  Rebuild only when an input or the key changed, so ordinary change detection
 *  does not rebuild URLs. */
class UrlMemo<A extends unknown[]> {
  private readonly build: (...args: A) => string;
  private inputs?: unknown[];
  private url = '';

  constructor(build: (...args: A) => string) {
    this.build = build;
  }

  get(...args: A): string {
    const inputs = [...args, privateImageCacheKey()];
    if (!this.inputs || inputs.some((value, index) => value !== this.inputs?.[index])) {
      this.inputs = inputs;
      this.url = this.build(...args);
    }
    return this.url;
  }
}

export function thumbnailUrl(path: string, size?: number, revision?: string | null, scope?: SharedAlbumMediaScope | null): string {
  if (scope) return sharedAlbumMediaUrl(scope, 'thumbnail', path, size, revision);
  const params = new URLSearchParams({ path });
  if (size) params.set('size', String(size));
  if (revision) params.set('preview', revision);
  return `/thumbnail?${privateImageQuery(params)}`;
}

@Pipe({ name: 'thumbnailUrl', standalone: true, pure: false })
export class ThumbnailUrlPipe implements PipeTransform {
  private readonly memo = new UrlMemo(thumbnailUrl);

  transform(path: string, size?: number, revision?: string | null, scope?: SharedAlbumMediaScope | null): string {
    return this.memo.get(path, size, revision, scope);
  }
}

export function imageUrl(path: string, fallbackThumbnail = false, revision?: string | null, scope?: SharedAlbumMediaScope | null): string {
  if (scope) return sharedAlbumMediaUrl(scope, 'image', path, undefined, revision);
  const params = new URLSearchParams({ path });
  if (fallbackThumbnail) params.set('fallback', 'thumbnail');
  if (revision) params.set('preview', revision);
  return `/image?${privateImageQuery(params)}`;
}

@Pipe({ name: 'imageUrl', standalone: true, pure: false })
export class ImageUrlPipe implements PipeTransform {
  private readonly memo = new UrlMemo(imageUrl);

  transform(path: string, fallbackThumbnail = false, revision?: string | null, scope?: SharedAlbumMediaScope | null): string {
    return this.memo.get(path, fallbackThumbnail, revision, scope);
  }
}

/** Bypass old public browser/SW entries; these crops require an auth check on every reuse. */
export function faceThumbnailUrl(faceId: number): string {
  return `/face_thumbnail/${faceId}?${privateImageQuery(new URLSearchParams(), PRIVATE_CROP_URL_VERSION)}`;
}

export function personThumbnailUrl(personId: number): string {
  return `/person_thumbnail/${personId}?${privateImageQuery(new URLSearchParams(), PRIVATE_CROP_URL_VERSION)}`;
}

@Pipe({ name: 'faceThumbnailUrl', standalone: true, pure: false })
export class FaceThumbnailUrlPipe implements PipeTransform {
  private readonly memo = new UrlMemo(faceThumbnailUrl);

  transform(faceId: number): string {
    return this.memo.get(faceId);
  }
}

@Pipe({ name: 'personThumbnailUrl', standalone: true, pure: false })
export class PersonThumbnailUrlPipe implements PipeTransform {
  private readonly memo = new UrlMemo(personThumbnailUrl);

  transform(personId: number): string {
    return this.memo.get(personId);
  }
}
