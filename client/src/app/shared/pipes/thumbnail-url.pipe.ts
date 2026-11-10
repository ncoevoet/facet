import { Pipe, PipeTransform } from '@angular/core';
import { privateImageSessionKey } from '../utils/private-image-session';

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

export function thumbnailUrl(path: string, size?: number, revision?: string | null): string {
  const params = new URLSearchParams({ path });
  if (size) params.set('size', String(size));
  if (revision) params.set('preview', revision);
  params.set('v', PRIVATE_IMAGE_URL_VERSION);
  params.set('ngsw-bypass', '1');
  params.set('session', privateImageSessionKey());
  return `/thumbnail?${params}`;
}

// Impure pipes track the session signal even when their image input is unchanged.
// Cache each result so ordinary change detection does not rebuild URLs.
@Pipe({ name: 'thumbnailUrl', standalone: true, pure: false })
export class ThumbnailUrlPipe implements PipeTransform {
  private cached?: { path: string; size?: number; revision?: string | null; session: string; url: string };

  transform(path: string, size?: number, revision?: string | null): string {
    const session = privateImageSessionKey();
    if (!this.cached || this.cached.path !== path || this.cached.size !== size ||
        this.cached.revision !== revision || this.cached.session !== session) {
      this.cached = { path, size, revision, session, url: thumbnailUrl(path, size, revision) };
    }
    return this.cached.url;
  }
}

export function imageUrl(path: string, fallbackThumbnail = false, revision?: string | null): string {
  const params = new URLSearchParams({ path });
  if (fallbackThumbnail) params.set('fallback', 'thumbnail');
  if (revision) params.set('preview', revision);
  params.set('v', PRIVATE_IMAGE_URL_VERSION);
  params.set('ngsw-bypass', '1');
  params.set('session', privateImageSessionKey());
  return `/image?${params}`;
}

@Pipe({ name: 'imageUrl', standalone: true, pure: false })
export class ImageUrlPipe implements PipeTransform {
  private cached?: { path: string; fallback: boolean; revision?: string | null; session: string; url: string };

  transform(path: string, fallbackThumbnail = false, revision?: string | null): string {
    const session = privateImageSessionKey();
    if (!this.cached || this.cached.path !== path || this.cached.fallback !== fallbackThumbnail ||
        this.cached.revision !== revision || this.cached.session !== session) {
      this.cached = { path, fallback: fallbackThumbnail, revision, session, url: imageUrl(path, fallbackThumbnail, revision) };
    }
    return this.cached.url;
  }
}

/** Bypass old public browser/SW entries; these crops require an auth check on every reuse. */
export function faceThumbnailUrl(faceId: number): string {
  return `/face_thumbnail/${faceId}?v=2&ngsw-bypass=1&session=${privateImageSessionKey()}`;
}

export function personThumbnailUrl(personId: number): string {
  return `/person_thumbnail/${personId}?v=2&ngsw-bypass=1&session=${privateImageSessionKey()}`;
}

@Pipe({ name: 'faceThumbnailUrl', standalone: true, pure: false })
export class FaceThumbnailUrlPipe implements PipeTransform {
  private cached?: { id: number; session: string; url: string };

  transform(faceId: number): string {
    const session = privateImageSessionKey();
    if (!this.cached || this.cached.id !== faceId || this.cached.session !== session) {
      this.cached = { id: faceId, session, url: faceThumbnailUrl(faceId) };
    }
    return this.cached.url;
  }
}

@Pipe({ name: 'personThumbnailUrl', standalone: true, pure: false })
export class PersonThumbnailUrlPipe implements PipeTransform {
  private cached?: { id: number; session: string; url: string };

  transform(personId: number): string {
    const session = privateImageSessionKey();
    if (!this.cached || this.cached.id !== personId || this.cached.session !== session) {
      this.cached = { id: personId, session, url: personThumbnailUrl(personId) };
    }
    return this.cached.url;
  }
}
