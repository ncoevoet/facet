import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';
import { Chart } from 'chart.js';
import { ThemeService } from '../../core/services/theme.service';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { StatsFiltersService } from './stats-filters.service';
import { StatsCorrelationsTabComponent } from './stats-correlations-tab.component';
import { buildCorrelationCsvRecords } from './stats-correlations-csv';

describe('StatsCorrelationsTabComponent', () => {
  let component: StatsCorrelationsTabComponent;
  let api: { get: Mock };
  let csvTexts: string[];
  let originalBlob: typeof Blob;
  let originalCreateUrl: typeof URL.createObjectURL;
  let originalRevokeUrl: typeof URL.revokeObjectURL;
  const filters = () => TestBed.inject(StatsFiltersService);
  const response = {
    labels: ['2024'],
    groups: { canon: { '2024': { aggregate: 7.5, aesthetic: 6.5 } } },
    x_axis: 'date_year', group_by: 'camera_model',
  };

  beforeEach(() => {
    api = { get: vi.fn(() => of(response)) };
    csvTexts = [];
    originalBlob = globalThis.Blob;
    originalCreateUrl = URL.createObjectURL;
    originalRevokeUrl = URL.revokeObjectURL;
    globalThis.Blob = function (parts: BlobPart[], options?: BlobPropertyBag) {
      csvTexts.push(String(parts[0]).replace(/^\uFEFF/, ''));
      return new originalBlob(parts, options);
    } as unknown as typeof Blob;
    URL.createObjectURL = vi.fn(() => 'blob:correlation-test');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    TestBed.configureTestingModule({
      providers: [
        StatsCorrelationsTabComponent,
        { provide: ApiService, useValue: api },
        { provide: I18nService, useValue: { t: vi.fn((k: string) => k), currentLang: vi.fn(() => 'en'), translations: signal({}) } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    component = TestBed.inject(StatsCorrelationsTabComponent);
  });

  afterEach(() => {
    globalThis.Blob = originalBlob;
    URL.createObjectURL = originalCreateUrl;
    URL.revokeObjectURL = originalRevokeUrl;
    vi.restoreAllMocks();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it.each(['metric', 'x axis', 'group', 'category', 'date from', 'date to'])(
    'invalidates the loaded chart and CSV when the draft %s changes', async control => {
      component.corrGroupBy.set('camera_model');
      component.corrYMetrics.set(['aggregate']);
      await component.loadCorrelation();
      expect(component.corrData()).toEqual(response);
      component.exportCsv();
      expect(csvTexts).toEqual(['date_year,group,aggregate\r\n2024,canon,7.5']);
      csvTexts.length = 0;
      if (control === 'metric') component.corrYMetrics.set(['aesthetic']);
      if (control === 'x axis') component.corrXAxis.set('iso');
      if (control === 'group') component.corrGroupBy.set('lens_model');
      if (control === 'category') filters().filterCategory.set('portrait');
      if (control === 'date from') filters().dateFrom.set('2025-01-01');
      if (control === 'date to') filters().dateTo.set('2025-12-31');
      // Even before Angular runs effects, an export cannot relabel the previous response.
      component.exportCsv();
      expect(csvTexts).toEqual([]);
      expect(component.corrData()).toBeNull();
      TestBed.tick();
      await component.loadCorrelation();
      expect(component.corrData()).toEqual(response);
      component.exportCsv();
      expect(csvTexts).toHaveLength(1);
    },
  );

  it.each(['success', 'failure'])('ignores a queued obsolete %s after loading a new query', async outcome => {
    await component.loadCorrelation();
    const old = new Subject<typeof response>();
    const latest = new Subject<typeof response>();
    api.get.mockReturnValueOnce(old).mockReturnValueOnce(latest);
    component.corrYMetrics.set(['aggregate']);
    const oldDone = component.loadCorrelation();
    if (outcome === 'success') old.next(response);
    else old.error(new Error('obsolete query'));
    component.corrYMetrics.set(['aesthetic']);
    const latestDone = component.loadCorrelation();
    await oldDone;
    expect(component.correlationLoading()).toBe(true);
    expect(component.corrData()).toBeNull();
    latest.next(response);
    latest.complete();
    await latestDone;
    expect(component.correlationLoading()).toBe(false);
    expect((component as any).correlationError()).toBe(false);
    component.exportCsv();
    expect(csvTexts).toEqual(['date_year,group,aesthetic\r\n2024,canon,6.5']);
  });

  it('cancels a pending request when controls change without a reload', async () => {
    const pending = new Subject<typeof response>();
    api.get.mockReturnValueOnce(pending);
    const done = component.loadCorrelation();
    expect(pending.observed).toBe(true);
    component.corrXAxis.set('iso');
    TestBed.tick();
    expect(pending.observed).toBe(false);
    await done;
    expect(component.correlationLoading()).toBe(false);
    expect(component.corrData()).toBeNull();
  });

  it('reports failures without stale data and succeeds on retry', async () => {
    await component.loadCorrelation();
    api.get.mockReturnValueOnce(throwError(() => new Error('failure')));
    await component.loadCorrelation();
    expect(component.corrData()).toBeNull();
    expect((component as any).correlationError()).toBe(true);
    await component.loadCorrelation();
    expect((component as any).correlationError()).toBe(false);
    expect(component.corrData()).toEqual(response);
  });

  it('cancels the pending request on destroy', async () => {
    const pending = new Subject<typeof response>();
    api.get.mockReturnValueOnce(pending);
    const done = component.loadCorrelation();
    expect(pending.observed).toBe(true);
    TestBed.resetTestingModule();
    expect(pending.observed).toBe(false);
    await done;
    expect(component.corrData()).toBeNull();
  });

  it('renders loaded group metrics, rebuilds presentation changes, and removes a stale chart', async () => {
    // Keep the real Chart constructor, config and destruction lifecycle. jsdom
    // has no canvas renderer/layout: isolate those steps without mocking the
    // module (Angular bundles shared imports differently in the full suite).
    vi.spyOn(Chart.prototype as any, '_initialize').mockImplementation(function (this: Chart) { return this; });
    vi.spyOn(Chart.prototype, 'update').mockImplementation(() => {});
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (this: HTMLCanvasElement) {
      return { canvas: this, save() {}, resetTransform() {}, clearRect() {}, restore() {} } as unknown as CanvasRenderingContext2D;
    });
    const fixture = TestBed.createComponent(StatsCorrelationsTabComponent);
    component = fixture.componentInstance;
    component.corrGroupBy.set('camera_model');
    component.corrYMetrics.set(['aggregate']);
    fixture.detectChanges();
    await component.loadCorrelation();
    fixture.detectChanges();
    const chart = () => Chart.getChart(fixture.nativeElement.querySelector('canvas') as HTMLCanvasElement)!;
    const chartConfig = () => chart().config as any;
    expect(chart()).toBeInstanceOf(Chart);
    expect(chart().ctx).not.toBeNull();
    expect(chartConfig().data.datasets[0].data).toEqual([7.5]);
    component.corrChartType.set('bar');
    TestBed.inject(ThemeService).setTheme('theme-green');
    fixture.detectChanges();
    expect(chartConfig().type).toBe('bar');
    expect(chartConfig().data.datasets[0].borderColor).toBe('#22c55e');
    expect(chartConfig().data.datasets[0].data).toEqual([7.5]);
    const previousChart = chart();
    const previousCanvas = previousChart.canvas;
    component.corrYMetrics.set(['aesthetic']);
    fixture.detectChanges();
    expect(previousChart.ctx).toBeNull();
    expect(Chart.getChart(previousCanvas)).toBeUndefined();
    expect(fixture.nativeElement.querySelector('canvas')).toBeNull();
    expect(fixture.nativeElement.querySelector('button[mat-icon-button]').disabled).toBe(true);
    await component.loadCorrelation();
    fixture.detectChanges();
    expect(chartConfig().data.datasets[0].data).toEqual([6.5]);
    expect(fixture.nativeElement.querySelector('button[mat-icon-button]').disabled).toBe(false);
    fixture.destroy();
  });
});

describe('buildCorrelationCsvRecords', () => {
  it('returns empty when no correlation data is loaded', () => {
    expect(buildCorrelationCsvRecords(null, ['aggregate'])).toEqual([]);
  });

  it('builds one row per label from the metrics branch', () => {
    const records = buildCorrelationCsvRecords(
      {
        labels: ['2023', '2024'],
        metrics: { aggregate: [7.1, 7.8], aesthetic: [6.0, 6.5] },
        x_axis: 'date_year',
        group_by: '',
      },
      ['aggregate', 'aesthetic'],
    );
    expect(records).toEqual([
      { date_year: '2023', aggregate: 7.1, aesthetic: 6.0 },
      { date_year: '2024', aggregate: 7.8, aesthetic: 6.5 },
    ]);
  });

  it('builds one row per group+label from the groups branch', () => {
    const records = buildCorrelationCsvRecords(
      {
        labels: ['2023', '2024'],
        groups: {
          canon: { '2023': { aggregate: 7.0 }, '2024': { aggregate: 7.5 } },
          nikon: { '2023': { aggregate: 6.8 }, '2024': { aggregate: 7.2 } },
        },
        x_axis: 'date_year',
        group_by: 'camera_model',
      },
      ['aggregate'],
    );
    expect(records).toEqual([
      { date_year: '2023', group: 'canon', aggregate: 7.0 },
      { date_year: '2024', group: 'canon', aggregate: 7.5 },
      { date_year: '2023', group: 'nikon', aggregate: 6.8 },
      { date_year: '2024', group: 'nikon', aggregate: 7.2 },
    ]);
  });
});
