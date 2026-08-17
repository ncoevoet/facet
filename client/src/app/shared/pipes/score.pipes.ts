import { Pipe, PipeTransform } from '@angular/core';
import { Photo } from '../models/photo.model';

@Pipe({ name: 'scoreClass', standalone: true, pure: true })
export class ScoreClassPipe implements PipeTransform {
  transform(score: number | null, config: { quality_thresholds?: { excellent: number; great: number; good: number } } | null): string {
    // An unscored photo has no bucket. Comparing null against a positive
    // threshold has always been false, so it has always landed in the lowest
    // bucket; -Infinity keeps that exact outcome now the type admits null.
    const value = score ?? Number.NEGATIVE_INFINITY;
    const thresholds = config?.quality_thresholds;
    if (thresholds) {
      if (value >= thresholds.excellent) return 'bg-green-600 text-white';
      if (value >= thresholds.great) return 'bg-yellow-600 text-white';
      if (value >= thresholds.good) return 'bg-orange-600 text-white';
      return 'bg-red-600 text-white';
    }
    if (value >= 8) return 'bg-green-600 text-white';
    if (value >= 6) return 'bg-yellow-600 text-white';
    if (value >= 4) return 'bg-orange-600 text-white';
    return 'bg-red-600 text-white';
  }
}

/** Return the score value for the current sort column (falls back to aggregate). */
@Pipe({ name: 'sortScore', standalone: true, pure: true })
export class SortScorePipe implements PipeTransform {
  transform(photo: Photo, sort: string): number | null {
    const val = (photo as unknown as Record<string, unknown>)[sort];
    return typeof val === 'number' ? val : photo.aggregate;
  }
}
