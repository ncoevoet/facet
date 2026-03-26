/** Convert a Date to an ISO date string (YYYY-MM-DD), or empty string if null. */
export function toIsoDateString(d: Date | null): string {
  if (!d) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
