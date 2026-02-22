import { Pipe, PipeTransform } from '@angular/core';

/** Pipe to compute chart container height from item count. */
@Pipe({ name: 'chartHeight', standalone: true })
export class ChartHeightPipe implements PipeTransform {
  transform(items: unknown[], rowHeight = 28): number {
    return Math.max(200, items.length * rowHeight);
  }
}
