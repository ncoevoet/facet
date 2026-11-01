import { Pipe, type PipeTransform } from '@angular/core';
import type { ViewFilterParams } from '../gallery/gallery.store';

/** Match the Timeline's visible-library denominator, not saved Gallery defaults. */
export function timelineGalleryQuery(visibility: ViewFilterParams): Record<string, string> {
  return { ...Object.fromEntries(Object.entries(visibility).map(([key, value]) => [key, String(value === '1')])),
    type: '', hide_rejected: 'false', favorites_only: 'false', is_monochrome: 'false',
    review_status: '', show_rejected: 'false', blinks_only: 'false', duplicates_only: 'false' };
}

@Pipe({ name: 'timelineDayQuery', standalone: true })
export class TimelineDayQueryPipe implements PipeTransform {
  transform(date: string, visibility: ViewFilterParams): Record<string, string> {
    return { ...timelineGalleryQuery(visibility),
      date_from: date, date_to: date, sort: 'date_taken', sort_direction: 'ASC' };
  }
}

@Pipe({ name: 'timelinePhotoLink', standalone: true })
export class TimelinePhotoLinkPipe implements PipeTransform {
  transform(path: string): string { return `/photo?path=${encodeURIComponent(path)}`; }
}
