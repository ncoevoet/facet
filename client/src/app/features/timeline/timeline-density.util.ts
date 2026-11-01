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

export function densityBuckets(response: DensityResponse, year: string, month: string): DensityBucket[] {
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

export function densityRange(first: DensityBucket, last: DensityBucket): { from: string; to: string } {
  return first.from <= last.from ? { from: first.from, to: last.to } : { from: last.from, to: first.to };
}
