import { Pipe, type PipeTransform } from '@angular/core';
import { formatCaptureDate } from '../../shared/utils/date-format';
import type { DensityBucket } from './timeline-density.util';

/** How a density bucket names its period: a week by its first and last day, anything else by its key.
 *  The language is an argument, so a language switched in place re-formats the week labels of
 *  buckets whose data has not changed. */
@Pipe({ name: 'densityPeriod', standalone: true })
export class DensityPeriodPipe implements PipeTransform {
  transform(bucket: DensityBucket, unit: 'auto' | 'week', language: string): string {
    return unit === 'week' ? `${formatCaptureDate(bucket.from, language)} – ${formatCaptureDate(bucket.to, language)}` : bucket.key;
  }
}
