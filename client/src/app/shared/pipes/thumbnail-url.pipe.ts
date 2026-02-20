import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'thumbnailUrl', standalone: true, pure: true })
export class ThumbnailUrlPipe implements PipeTransform {
  transform(path: string, size?: number): string {
    const params = new URLSearchParams({ path });
    if (size) params.set('size', String(size));
    return `/thumbnail?${params}`;
  }
}

@Pipe({ name: 'imageUrl', standalone: true, pure: true })
export class ImageUrlPipe implements PipeTransform {
  transform(path: string): string {
    return `/image?${new URLSearchParams({ path })}`;
  }
}

@Pipe({ name: 'faceThumbnailUrl', standalone: true, pure: true })
export class FaceThumbnailUrlPipe implements PipeTransform {
  transform(faceId: number): string {
    return `/face_thumbnail/${faceId}`;
  }
}

@Pipe({ name: 'personThumbnailUrl', standalone: true, pure: true })
export class PersonThumbnailUrlPipe implements PipeTransform {
  transform(personId: number): string {
    return `/person_thumbnail/${personId}`;
  }
}
