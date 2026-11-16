import { Pipe, PipeTransform } from '@angular/core';

let activeLocale: () => string = () => 'en';

/** The i18n service registers its live locale reader at bootstrap: module-scope
 *  constructions of this pipe (organization-history-diff shares one instance)
 *  have no injector to ask, but still need the viewer's locale. */
export function setCaptureDateLocaleReader(read: () => string): void {
  activeLocale = read;
}

/** Capture timestamps are camera-local values: format their recorded calendar
 * fields without shifting them through the browser's timezone. The field order
 * and separators follow the viewer's locale (zh: 2026年10月31日, en: Oct 31,
 * 2026) instead of an ambiguous all-numeric slash form. */
@Pipe({ name: 'captureDate', standalone: true, pure: false })
export class CaptureDatePipe implements PipeTransform {
  private readonly cache = new Map<string, string>();

  transform(value: string | null | undefined): string {
    if (!value) return '';
    const locale = activeLocale();
    const cached = this.cache.get(`${locale}\u0000${value}`);
    if (cached !== undefined) return cached;
    const match = /^(\d{4})[:-](\d{2})[:-](\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/.exec(value);
    if (!match) return value;
    const [, year, month, day, hour, minute] = match;
    const date = new Date(0);
    date.setUTCFullYear(Number(year), Number(month) - 1, Number(day));
    date.setUTCHours(Number(hour ?? 0), Number(minute ?? 0));
    if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() !== Number(month) - 1
      || date.getUTCDate() !== Number(day) || Number(hour ?? 0) > 23 || Number(minute ?? 0) > 59) return value;
    // `timeZone: UTC` keeps the recorded calendar fields untouched; Intl
    // renders them the way the locale writes dates. The recorded HH:mm is
    // appended verbatim (24-hour), so the time never goes through a locale
    // hour cycle either.
    const formatted = new Intl.DateTimeFormat(locale, {
      timeZone: 'UTC',
      year: 'numeric', month: 'short', day: 'numeric',
    }).format(date);
    const result = hour === undefined ? formatted : `${formatted} ${hour}:${minute}`;
    this.cache.set(`${locale}\u0000${value}`, result);
    return result;
  }
}
