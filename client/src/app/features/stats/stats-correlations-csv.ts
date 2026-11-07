import { CsvValue } from '../../shared/utils/csv';

export interface CorrelationApiResponse {
  labels: string[];
  metrics?: Record<string, (number | null)[]>;
  groups?: Record<string, Record<string, Record<string, number>>>;
  counts?: number[];
  x_axis: string;
  group_by: string;
}

/** Key of the bucket column: the X dimension, renamed when a Y metric of the same name would overwrite it. */
export function correlationBucketColumn(data: CorrelationApiResponse, yMetrics: string[]): string {
  const xCol = data.x_axis || 'x';
  const metrics = new Set([...yMetrics, ...Object.keys(data.metrics ?? {})]);
  return metrics.has(xCol) ? `${xCol}_bucket` : xCol;
}

/** Build the CSV export rows (one per bucket, or per bucket+group). */
export function buildCorrelationCsvRecords(
  data: CorrelationApiResponse | null,
  yMetrics: string[],
): Record<string, CsvValue>[] {
  if (!data || !data.labels?.length) return [];
  const xCol = correlationBucketColumn(data, yMetrics);
  const records: Record<string, CsvValue>[] = [];
  if (data.groups && Object.keys(data.groups).length > 0) {
    for (const [group, byLabel] of Object.entries(data.groups)) {
      for (const label of data.labels) {
        const cell = byLabel[label] ?? {};
        const rec: Record<string, CsvValue> = { [xCol]: label, group };
        for (const m of yMetrics) rec[m] = cell[m] ?? null;
        records.push(rec);
      }
    }
  } else if (data.metrics) {
    const metricsData = data.metrics;
    const metrics = Object.keys(metricsData);
    data.labels.forEach((label, i) => {
      const rec: Record<string, CsvValue> = { [xCol]: label };
      for (const m of metrics) rec[m] = metricsData[m]?.[i] ?? null;
      records.push(rec);
    });
  }
  return records;
}
