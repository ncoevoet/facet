export interface DensityBucket {
  key: string;
  label: string;
  from: string;
  to: string;
  count: number;
}

export interface DensityResponse {
  years?: { year: string; count: number }[];
  months?: { month: string; count: number }[];
  dates?: { date: string; count: number }[];
}

/** Intersect a route period with the optional typed capture-date range. */
export function timelineWindow(year: string, month: string, from: string, to: string): { from: string; to: string } {
  if (!/^\d{4}$/.test(year)) return { from, to };
  const validMonth = /^(?:[1-9]|0[1-9]|1[0-2])$/.test(month);
  const start = `${year}-${validMonth ? month.padStart(2, '0') : '01'}-01`;
  const end = validMonth ? `${year}-${month.padStart(2, '0')}-${new Date(+year, +month, 0).getDate()}` : `${year}-12-31`;
  return { from: from > start ? from : start, to: to && to < end ? to : end };
}

export function densityBuckets(response: DensityResponse, year: string, month: string,
  options: { unit?: 'auto' | 'week'; from?: string; to?: string } = {}): DensityBucket[] {
  if (options.unit === 'week' && year) return weekBuckets(response, year, month, options.from ?? '', options.to ?? '');
  if (!year) return (response.years ?? []).map(row => ({ key: row.year, label: row.year,
    from: `${row.year}-01-01`, to: `${row.year}-12-31`, count: row.count })).sort((a, b) => a.key.localeCompare(b.key));
  if (!month) {
    const counts = new Map((response.months ?? []).map(row => [row.month, row.count]));
    return Array.from({ length: 12 }, (_, index) => {
      const key = `${year}-${String(index + 1).padStart(2, '0')}`;
      const days = new Date(+year, index + 1, 0).getDate();
      return { key, label: String(index + 1).padStart(2, '0'), from: `${key}-01`, to: `${key}-${days}`, count: counts.get(key) ?? 0 };
    });
  }
  const counts = new Map((response.dates ?? []).map(row => [row.date, row.count]));
  const days = new Date(+year, +month, 0).getDate();
  return Array.from({ length: days }, (_, index) => {
    const key = `${year}-${month.padStart(2, '0')}-${String(index + 1).padStart(2, '0')}`;
    return { key, label: String(index + 1), from: key, to: key, count: counts.get(key) ?? 0 };
  });
}

/** ISO Monday–Sunday groups, clipped to the actual calendar/query window.
 * Work from at most366 day counts, never loading photos or inferring dates. */
function weekBuckets(response: DensityResponse, year: string, month: string, from: string, to: string): DensityBucket[] {
  const window = timelineWindow(year, month, from, to);
  const counts = new Map((response.dates ?? []).map(row => [row.date, row.count]));
  const start = new Date(Date.UTC(+year, month ? +month - 1 : 0, 1));
  const end = new Date(Date.UTC(+year, month ? +month : 12, 0));
  const weeks = new Map<string, DensityBucket>();
  for (const date = start; date <= end; date.setUTCDate(date.getUTCDate() + 1)) {
    const day = date.toISOString().slice(0, 10);
    if (day < window.from || day > window.to) continue;
    const thursday = new Date(date);
    thursday.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7));
    const isoYear = thursday.getUTCFullYear();
    const number = Math.ceil(((thursday.getTime() - Date.UTC(isoYear, 0, 1)) / 86_400_000 + 1) / 7);
    const key = `${isoYear}-W${String(number).padStart(2, '0')}`;
    const previous = weeks.get(key);
    if (previous) { previous.to = day; previous.count += counts.get(day) ?? 0; }
    else weeks.set(key, { key, label: key, from: day, to: day, count: counts.get(day) ?? 0 });
  }
  return [...weeks.values()];
}

export function densityRange(first: DensityBucket, last: DensityBucket): { from: string; to: string } {
  return first.from <= last.from ? { from: first.from, to: last.to } : { from: last.from, to: first.to };
}
