import { Pipe, PipeTransform } from '@angular/core';

/** Pixel dimensions as localized megapixels ("24.2 MP", "24,2 MP"); empty when either side is unknown. */
@Pipe({ name: 'megapixels' })
export class MegapixelsPipe implements PipeTransform {
  transform(width: number | null | undefined, height: number | null | undefined, locale = 'en'): string {
    if (!width || !height) return '';
    const value = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format((width * height) / 1_000_000);
    return `${value} MP`;
  }
}
