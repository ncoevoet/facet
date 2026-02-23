import { Pipe, PipeTransform } from '@angular/core';
import { Photo } from '../models/photo.model';

@Pipe({ name: 'scoreClass', standalone: true, pure: true })
export class ScoreClassPipe implements PipeTransform {
  transform(score: number, config: { quality_thresholds?: { excellent: number; great: number; good: number } } | null): string {
    const thresholds = config?.quality_thresholds;
    if (thresholds) {
      if (score >= thresholds.excellent) return 'bg-green-600 text-white';
      if (score >= thresholds.great) return 'bg-yellow-600 text-white';
      if (score >= thresholds.good) return 'bg-orange-600 text-white';
      return 'bg-red-600 text-white';
    }
    if (score >= 8) return 'bg-green-600 text-white';
    if (score >= 6) return 'bg-yellow-600 text-white';
    if (score >= 4) return 'bg-orange-600 text-white';
    return 'bg-red-600 text-white';
  }
}

/** Return the score value for the current sort column (falls back to aggregate). */
@Pipe({ name: 'sortScore', standalone: true, pure: true })
export class SortScorePipe implements PipeTransform {
  transform(photo: Photo, sort: string): number {
    const val = (photo as unknown as Record<string, unknown>)[sort];
    return typeof val === 'number' ? val : photo.aggregate;
  }
}
