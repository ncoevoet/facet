/** Convert a Date to an ISO date string (YYYY-MM-DD), or empty string if null. */
export function toIsoDateString(d: Date | null): string {
  if (!d) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * A scope date as a plain `YYYY-MM-DD` when it is the EXIF form of a whole-day edge (`from` at 00:00:00, `to` at
 * 23:59:59), which is what the server's normaliser makes of a date-only value and reads back identically; any
 * other value (a scene's real times) is returned unchanged, since a plain date would widen it.
 */
export function plainScopeDate(value: string | null | undefined, edge: 'from' | 'to'): string | null {
  if (!value) return null;
  const m = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}:\d{2}:\d{2})$/.exec(value);
  if (!m || m[4] !== (edge === 'from' ? '00:00:00' : '23:59:59')) return value;
  return `${m[1]}-${m[2]}-${m[3]}`;
}

/** The viewer's language as an Intl locale. Bare `en` is en-US, which puts the month first;
 *  Facet's English reads day-first, so it formats as en-GB. */
export function displayLocale(language: string): string {
  return language === 'en' ? 'en-GB' : language;
}

const dateFormatters = new Map<string, Intl.DateTimeFormat>();

/**
 * A date's calendar day as the viewer's language writes it (en `31 Oct 2026`, zh `2026年10月31日`),
 * read in `timeZone` (the browser's own when omitted).
 */
export function formatDisplayDate(date: Date, language: string, timeZone?: string): string {
  const locale = displayLocale(language);
  const key = `${locale}\u0000${timeZone ?? ''}`;
  let formatter = dateFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, { timeZone, year: 'numeric', month: 'short', day: 'numeric' });
    dateFormatters.set(key, formatter);
  }
  return formatter.format(date);
}

/**
 * A capture timestamp (EXIF `YYYY:MM:DD HH:mm:ss` or ISO) as the viewer's language writes the day,
 * with the recorded `HH:mm` appended verbatim. Capture timestamps are camera-local values, so the
 * recorded calendar fields are rendered without shifting them through the browser's timezone.
 * An unreadable or impossible value is returned unchanged.
 */
export function formatCaptureDate(value: string | null | undefined, language: string): string {
  if (!value) return '';
  const match = /^(\d{4})[:-](\d{2})[:-](\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/.exec(value);
  if (!match) return value;
  const [, year, month, day, hour, minute] = match;
  const date = new Date(0);
  date.setUTCFullYear(Number(year), Number(month) - 1, Number(day));
  if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() !== Number(month) - 1
    || date.getUTCDate() !== Number(day) || Number(hour ?? 0) > 23 || Number(minute ?? 0) > 59) return value;
  const formatted = formatDisplayDate(date, language, 'UTC');
  return hour === undefined ? formatted : `${formatted} ${hour}:${minute}`;
}
