/** A scalar value maps cleanly to a single CSV cell. */
export type CsvValue = string | number | boolean | null | undefined;

/** Escape one CSV field per RFC 4180 — quote when it contains a comma, quote, or newline. */
function escapeCsvField(value: CsvValue): string {
  if (value === null || value === undefined) return '';
  const str = String(value);
  if (/[",\r\n]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function isScalar(value: unknown): value is CsvValue {
  return value === null || value === undefined
    || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
}

/** Build the CSV text and trigger a browser download. */
function triggerCsvDownload(filename: string, headers: string[], rows: CsvValue[][]): void {
  const lines = [headers, ...rows].map((row) => row.map(escapeCsvField).join(','));
  // UTF-8 BOM so spreadsheet apps detect the encoding; CRLF for Excel.
  const csv = String.fromCharCode(0xfeff) + lines.join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Export an array of flat records as a downloaded CSV file.
 *
 * Column headers are derived from the keys of the first row; non-scalar fields
 * (nested arrays/objects) are skipped so any stats dataset can be exported
 * without hand-listing its columns. No-op for an empty array.
 */
export function downloadCsv<T extends object>(filename: string, rows: readonly T[]): void {
  if (rows.length === 0) return;
  const records = rows as readonly Record<string, unknown>[];
  const keys = Object.keys(records[0]).filter((k) => isScalar(records[0][k]));
  const data = records.map((row) => keys.map((k) => (isScalar(row[k]) ? (row[k] as CsvValue) : '')));
  triggerCsvDownload(filename, keys, data);
}
