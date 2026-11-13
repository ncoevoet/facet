import { Pipe, PipeTransform } from '@angular/core';

/** Exposure compensation in EV with an explicit sign ("+0.7 EV", "−1 EV", "0 EV"), localized decimals. */
@Pipe({ name: 'exposureCompensation' })
export class ExposureCompensationPipe implements PipeTransform {
  transform(value: number | null | undefined, locale = 'en'): string {
    if (value == null || !Number.isFinite(value)) return '';
    const rounded = Math.round(value * 10) / 10;
    if (rounded === 0) return '0 EV';
    const magnitude = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(Math.abs(rounded));
    return `${rounded > 0 ? '+' : '−'}${magnitude} EV`;
  }
}
