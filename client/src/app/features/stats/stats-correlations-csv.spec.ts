import { buildCorrelationCsvRecords, CorrelationApiResponse } from './stats-correlations-csv';

describe('buildCorrelationCsvRecords', () => {
  it('returns an empty array for null data', () => {
    expect(buildCorrelationCsvRecords(null, ['aesthetic'])).toEqual([]);
  });

  it('returns an empty array when labels are missing', () => {
    const data = { x_axis: 'iso', group_by: '' } as unknown as CorrelationApiResponse;
    expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([]);
  });

  it('returns an empty array when labels is an empty array', () => {
    const data: CorrelationApiResponse = {
      labels: [],
      metrics: { aesthetic: [] },
      x_axis: 'iso',
      group_by: '',
    };
    expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([]);
  });

  describe('metrics mode (no groups)', () => {
    it('builds one record per label with the x_axis column and each metric value', () => {
      const data: CorrelationApiResponse = {
        labels: ['100', '200', '400'],
        metrics: {
          aesthetic: [5.1, 6.2, 7.3],
          comp_score: [4.0, 4.5, 5.0],
        },
        x_axis: 'iso',
        group_by: '',
      };
      expect(buildCorrelationCsvRecords(data, ['aesthetic', 'comp_score'])).toEqual([
        { iso: '100', aesthetic: 5.1, comp_score: 4.0 },
        { iso: '200', aesthetic: 6.2, comp_score: 4.5 },
        { iso: '400', aesthetic: 7.3, comp_score: 5.0 },
      ]);
    });

    it('iterates ALL metric keys present in data.metrics, ignoring the yMetrics argument', () => {
      const data: CorrelationApiResponse = {
        labels: ['a'],
        metrics: { aesthetic: [1], comp_score: [2] },
        x_axis: 'cat',
        group_by: '',
      };
      // yMetrics is empty, but metrics-mode keys off Object.keys(data.metrics)
      expect(buildCorrelationCsvRecords(data, [])).toEqual([
        { cat: 'a', aesthetic: 1, comp_score: 2 },
      ]);
    });

    it('uses null for a missing metric index', () => {
      const data: CorrelationApiResponse = {
        labels: ['a', 'b'],
        metrics: { aesthetic: [5] }, // only index 0 present
        x_axis: 'iso',
        group_by: '',
      };
      expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([
        { iso: 'a', aesthetic: 5 },
        { iso: 'b', aesthetic: null },
      ]);
    });

    it('preserves explicit null cell values', () => {
      const data: CorrelationApiResponse = {
        labels: ['a'],
        metrics: { aesthetic: [null] },
        x_axis: 'iso',
        group_by: '',
      };
      expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([
        { iso: 'a', aesthetic: null },
      ]);
    });

    it("defaults the x column header to 'x' when x_axis is empty", () => {
      const data: CorrelationApiResponse = {
        labels: ['a'],
        metrics: { aesthetic: [1] },
        x_axis: '',
        group_by: '',
      };
      expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([
        { x: 'a', aesthetic: 1 },
      ]);
    });
  });

  describe('groups mode', () => {
    it('builds one record per group x label with a group column', () => {
      const data: CorrelationApiResponse = {
        labels: ['100', '200'],
        groups: {
          Canon: {
            '100': { aesthetic: 5.0 },
            '200': { aesthetic: 6.0 },
          },
          Nikon: {
            '100': { aesthetic: 4.0 },
            '200': { aesthetic: 4.5 },
          },
        },
        x_axis: 'iso',
        group_by: 'camera_model',
      };
      expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([
        { iso: '100', group: 'Canon', aesthetic: 5.0 },
        { iso: '200', group: 'Canon', aesthetic: 6.0 },
        { iso: '100', group: 'Nikon', aesthetic: 4.0 },
        { iso: '200', group: 'Nikon', aesthetic: 4.5 },
      ]);
    });

    it('uses null when a group has no cell for a label', () => {
      const data: CorrelationApiResponse = {
        labels: ['100', '200'],
        groups: {
          Canon: { '100': { aesthetic: 5.0 } }, // no '200' entry
        },
        x_axis: 'iso',
        group_by: 'camera_model',
      };
      expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([
        { iso: '100', group: 'Canon', aesthetic: 5.0 },
        { iso: '200', group: 'Canon', aesthetic: null },
      ]);
    });

    it('uses null when a metric is absent from an existing cell', () => {
      const data: CorrelationApiResponse = {
        labels: ['100'],
        groups: {
          Canon: { '100': { aesthetic: 5.0 } },
        },
        x_axis: 'iso',
        group_by: 'camera_model',
      };
      expect(buildCorrelationCsvRecords(data, ['aesthetic', 'comp_score'])).toEqual([
        { iso: '100', group: 'Canon', aesthetic: 5.0, comp_score: null },
      ]);
    });

    it('falls back to metrics mode when groups is an empty object', () => {
      const data: CorrelationApiResponse = {
        labels: ['100'],
        groups: {},
        metrics: { aesthetic: [9] },
        x_axis: 'iso',
        group_by: '',
      };
      expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([
        { iso: '100', aesthetic: 9 },
      ]);
    });
  });

  it('returns an empty record list when neither groups nor metrics are present', () => {
    const data: CorrelationApiResponse = {
      labels: ['a'],
      x_axis: 'iso',
      group_by: '',
    };
    expect(buildCorrelationCsvRecords(data, ['aesthetic'])).toEqual([]);
  });
});
