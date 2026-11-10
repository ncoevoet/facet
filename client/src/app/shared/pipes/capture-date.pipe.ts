import { Pipe, PipeTransform } from '@angular/core';

/** Capture timestamps are camera-local values: format their recorded calendar
 * fields without shifting them through the browser's timezone. */
@Pipe({ name: 'captureDate', standalone: true, pure: true })
export class CaptureDatePipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value) return '';
    const match = /^(\d{4})[:-](\d{2})[:-](\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/.exec(value);
    if (!match) return value;
    const [, year, month, day, hour, minute] = match;
    const date = new Date(0);
    date.setUTCFullYear(Number(year), Number(month) - 1, Number(day));
    if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() !== Number(month) - 1
      || date.getUTCDate() !== Number(day) || Number(hour ?? 0) > 23 || Number(minute ?? 0) > 59) return value;
    return `${day}/${month}/${year}${hour === undefined ? '' : ` ${hour}:${minute}`}`;
  }
}
