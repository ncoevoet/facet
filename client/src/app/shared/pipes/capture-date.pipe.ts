import { Pipe, PipeTransform } from '@angular/core';
import { formatCaptureDate } from '../utils/date-format';

/** `date_taken | captureDate: locale()`: a capture timestamp as the viewer's language writes it
 *  (see `formatCaptureDate`). The language is an argument so the pipe stays pure and re-formats
 *  exactly when the value or the language changes. */
@Pipe({ name: 'captureDate', standalone: true })
export class CaptureDatePipe implements PipeTransform {
  transform(value: string | null | undefined, language: string): string {
    return formatCaptureDate(value, language);
  }
}
