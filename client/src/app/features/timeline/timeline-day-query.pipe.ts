import { Pipe, type PipeTransform } from '@angular/core';
import type { ViewFilterParams } from '../gallery/gallery.store';

/** Match the Timeline's visible-library denominator, not saved Gallery defaults. */
export function timelineGalleryQuery(visibility: ViewFilterParams): Record<string, string> {
  return { ...Object.fromEntries(Object.entries(visibility).map(([key, value]) => [key, String(value === '1')])),
    type: '', hide_rejected: 'false', favorites_only: 'false', is_monochrome: 'false',
    review_status: '', show_rejected: 'false', blinks_only: 'false', duplicates_only: 'false' };
}

export function timelineRangeQuery(
  from: string, to: string, visibility: ViewFilterParams, direction: 'ASC' | 'DESC',
): Record<string, string> {
  return { ...timelineGalleryQuery(visibility),
    date_from: from, date_to: to, sort: 'date_taken', sort_direction: direction };
}

export function timelineDayQuery(date: string, visibility: ViewFilterParams): Record<string, string> {
  return timelineRangeQuery(date, date, visibility, 'ASC');
}

@Pipe({ name: 'timelineDayQuery', standalone: true })
export class TimelineDayQueryPipe implements PipeTransform {
  transform(date: string, visibility: ViewFilterParams): Record<string, string> {
    return timelineDayQuery(date, visibility);
  }
}

@Pipe({ name: 'timelinePhotoLink', standalone: true })
export class TimelinePhotoLinkPipe implements PipeTransform {
  transform(path: string): string { return `/photo?path=${encodeURIComponent(path)}`; }
}
