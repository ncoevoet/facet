import { Pipe, PipeTransform } from '@angular/core';
import { SharedAlbumMediaScope, sharedAlbumMediaUrl } from '../utils/shared-album-media';

/** Largest `size` served from the stored thumbnail. Mirrors the server's render
 *  THRESHOLD (`_STORED_THUMBNAIL_SIZE` in api/routers/thumbnails.py), not the
 *  configurable edge the thumbnails are stored at. */
export const STORED_THUMBNAIL_EDGE = 640;
/** Edge of the single render the server produces above the threshold (mirrors
 *  `_RENDERED_SIZE`). */
export const RENDERED_THUMBNAIL_EDGE = 1920;
/** Cache-buster for render URLs: bump it to skip every soft frame browsers cached
 *  under the previous URL. */
export const RENDER_URL_VERSION = '2';

/** Above the stored edge the server renders the original. `v` skips the soft
 *  frame browsers cached under the old URL; `ngsw-bypass` because the service
 *  worker ignores Cache-Control. */
export function thumbnailUrl(path: string, size?: number, revision?: string | null, scope?: SharedAlbumMediaScope | null): string {
  if (scope) return sharedAlbumMediaUrl(scope, 'thumbnail', path, size, revision);
  const params = new URLSearchParams({ path });
  if (size) params.set('size', String(size));
  if (revision) params.set('preview', revision);
  if (size && size > STORED_THUMBNAIL_EDGE) {
    params.set('v', RENDER_URL_VERSION);
    params.set('ngsw-bypass', '1');
  }
  return `/thumbnail?${params}`;
}

@Pipe({ name: 'thumbnailUrl', standalone: true, pure: true })
export class ThumbnailUrlPipe implements PipeTransform {
  transform(path: string, size?: number, revision?: string | null, scope?: SharedAlbumMediaScope | null): string {
    return thumbnailUrl(path, size, revision, scope);
  }
}

export function imageUrl(path: string, fallbackThumbnail = false, revision?: string | null, scope?: SharedAlbumMediaScope | null): string {
  if (scope) return sharedAlbumMediaUrl(scope, 'image', path, undefined, revision);
  const params = new URLSearchParams({ path });
  if (fallbackThumbnail) params.set('fallback', 'thumbnail');
  if (revision) params.set('preview', revision);
  return `/image?${params}`;
}

@Pipe({ name: 'imageUrl', standalone: true, pure: true })
export class ImageUrlPipe implements PipeTransform {
  transform(path: string, fallbackThumbnail = false, revision?: string | null, scope?: SharedAlbumMediaScope | null): string {
    return imageUrl(path, fallbackThumbnail, revision, scope);
  }
}

/** Bypass old public browser/SW entries; these crops require an auth check on every reuse. */
export function faceThumbnailUrl(faceId: number): string {
  return `/face_thumbnail/${faceId}?v=2&ngsw-bypass=1`;
}

export function personThumbnailUrl(personId: number): string {
  return `/person_thumbnail/${personId}?v=2&ngsw-bypass=1`;
}

@Pipe({ name: 'faceThumbnailUrl', standalone: true, pure: true })
export class FaceThumbnailUrlPipe implements PipeTransform {
  transform(faceId: number): string {
    return faceThumbnailUrl(faceId);
  }
}

@Pipe({ name: 'personThumbnailUrl', standalone: true, pure: true })
export class PersonThumbnailUrlPipe implements PipeTransform {
  transform(personId: number): string {
    return personThumbnailUrl(personId);
  }
}
