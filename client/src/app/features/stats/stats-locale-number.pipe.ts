import { Pipe, PipeTransform } from '@angular/core';

/** Locale-formatted number with a fixed number of fraction digits; a missing or non-finite value renders as an em dash. */
@Pipe({ name: 'statsNumber', standalone: true })
export class StatsNumberPipe implements PipeTransform {
  transform(value: number | null | undefined, locale: string, digits = 0): string {
    return value == null || !Number.isFinite(value) ? '—'
      : new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  }
}
