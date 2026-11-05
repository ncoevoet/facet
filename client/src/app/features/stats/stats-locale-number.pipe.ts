import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'statsLocaleNumber', standalone: true })
export class StatsLocaleNumberPipe implements PipeTransform {
  transform(value: number, locale: string): string {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(value);
  }
}
