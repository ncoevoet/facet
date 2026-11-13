import { Pipe, PipeTransform } from '@angular/core';

const UNITS = ['byte', 'kilobyte', 'megabyte', 'gigabyte'] as const;

/** Bytes as a localized SI size ("1.5 MB", 1 kB = 1000 bytes). The locale is an argument so a language switch re-renders. */
@Pipe({ name: 'fileSize' })
export class FileSizePipe implements PipeTransform {
  transform(bytes: number | null | undefined, locale = 'en'): string {
    if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '';
    let value = bytes;
    let unit = 0;
    // Compare the value as shown: 999,950 bytes rounds to 1000 kB and must read "1 MB".
    const shown = (unit: number) => unit === 0 ? Math.round(value) : Math.round(value * 10) / 10;
    while (shown(unit) >= 1000 && unit < UNITS.length - 1) { value /= 1000; unit++; }
    return new Intl.NumberFormat(locale, { style: 'unit', unit: UNITS[unit], unitDisplay: 'short', maximumFractionDigits: unit === 0 ? 0 : 1 }).format(value);
  }
}
