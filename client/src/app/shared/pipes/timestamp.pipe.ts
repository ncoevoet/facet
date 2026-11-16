import { Pipe, PipeTransform } from '@angular/core';
import { formatDisplayDate } from '../utils/date-format';

const pad = (n: number): string => String(n).padStart(2, '0');

/**
 * `created_at | timestamp: locale()`: an instant (ISO string, epoch milliseconds or Date) as the
 * viewer's language writes the day, then a 24-hour `HH:mm` — the same shape as `captureDate`, so
 * the two read alike side by side. Read in the browser's timezone unless `timeZone` is `'UTC'`;
 * `'date'` drops the time. A missing or unreadable value renders empty.
 */
@Pipe({ name: 'timestamp', standalone: true })
export class TimestampPipe implements PipeTransform {
  transform(value: string | number | Date | null | undefined, language: string,
    mode: 'datetime' | 'date' = 'datetime', timeZone?: 'UTC'): string {
    if (value === null || value === undefined || value === '') return '';
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const day = formatDisplayDate(date, language, timeZone);
    if (mode === 'date') return day;
    const utc = timeZone === 'UTC';
    return `${day} ${pad(utc ? date.getUTCHours() : date.getHours())}:${pad(utc ? date.getUTCMinutes() : date.getMinutes())}`;
  }
}
