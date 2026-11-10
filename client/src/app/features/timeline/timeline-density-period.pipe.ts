import { Pipe, type PipeTransform } from '@angular/core';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import type { DensityBucket } from './timeline-density.util';

const CAPTURE_DATE = new CaptureDatePipe();

/** How a density bucket names its period: a week by its first and last day, anything else by its key. */
@Pipe({ name: 'densityPeriod', standalone: true })
export class DensityPeriodPipe implements PipeTransform {
  transform(bucket: DensityBucket, unit: 'auto' | 'week'): string {
    return unit === 'week' ? `${CAPTURE_DATE.transform(bucket.from)} – ${CAPTURE_DATE.transform(bucket.to)}` : bucket.key;
  }
}
