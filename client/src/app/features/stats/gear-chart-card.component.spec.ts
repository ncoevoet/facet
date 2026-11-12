import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Pipe, PipeTransform, signal } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';
import { axisLabelIndexAt, GearChartCardComponent, GearItem, truncateLegendLabel } from './gear-chart-card.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Pipe({
  name: 'translate',
  standalone: true
})
class MockTranslatePipe implements PipeTransform {
  transform(value: string): string {
    return `trans_${value}`;
  }
}

describe('GearChartCardComponent', () => {
  let component: GearChartCardComponent;
  let fixture: ComponentFixture<GearChartCardComponent>;

  const mockItems: GearItem[] = [
    {
      name: 'Lens A',
      count: 10,
      avg_score: 5.5,
      avg_aesthetic: 5.5,
      avg_sharpness: 5.5,
      avg_composition: 5.5,
      avg_exposure: 5.5,
      avg_color: 5.5,
      avg_iso: 100,
      avg_f_stop: 2.8,
      avg_focal_length: 50,
      avg_face_count: 1,
      avg_monochrome: 0.5,
      avg_dynamic_range: 10.5,
      history: [{ date: '2024-01-01', count: 5 }]
    },
    {
      name: 'Lens B',
      count: 20,
      avg_score: 8.5,
      avg_aesthetic: 8.5,
      avg_sharpness: 8.5,
      avg_composition: 8.5,
      avg_exposure: 8.5,
      avg_color: 8.5,
      avg_iso: 200,
      avg_f_stop: 4.0,
      avg_focal_length: 85,
      avg_face_count: 2,
      avg_monochrome: 0.1,
      avg_dynamic_range: 12.0,
      history: [{ date: '2024-02-01', count: 10 }]
    }
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [GearChartCardComponent, NoopAnimationsModule],
      providers: [{ provide: I18nService, useValue: { locale: signal('en') } }],
    })
    .overrideComponent(GearChartCardComponent, {
      remove: { imports: [TranslatePipe] },
      add: { imports: [MockTranslatePipe] }
    })
    .compileComponents();

    fixture = TestBed.createComponent(GearChartCardComponent);
    component = fixture.componentInstance;

    // Mock localStorage
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key: string) => {
      if (key === 'gear_metric_stats.test_title') return 'avg_score';
      return null;
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});

    // Set required inputs
    fixture.componentRef.setInput('titleKey', 'stats.test_title');
    fixture.componentRef.setInput('items', mockItems);
    fixture.componentRef.setInput('loading', false);
    fixture.componentRef.setInput('color', '#ff0000');
  });

  it('should create the component and restore metric from localStorage', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
    expect((component as any).selectedMetric()).toBe('avg_score');
  });

  it('provides the plotted gear values in a readable data table', () => {
    fixture.detectChanges();
    const table = fixture.nativeElement.querySelector('details table') as HTMLTableElement;
    expect(table.textContent).toContain('Lens A');
    expect(table.textContent).toContain('5.5');
    expect(table.textContent).toContain('Lens B');
    expect(table.textContent).toContain('8.5');
  });

  it('names the data table and its columns, and rounds averages like the other tables', () => {
    (component as any).selectedMetric.set('avg_score');
    fixture.componentRef.setInput('items', [{ ...mockItems[0], avg_score: 7.123457 }]);
    fixture.detectChanges();
    const table = fixture.nativeElement.querySelector('details table') as HTMLTableElement;
    expect(table.querySelector('caption')?.textContent).toContain('trans_');
    expect(Array.from(table.querySelectorAll('thead th')).map(th => th.textContent)).toEqual(['trans_stats.model', 'trans_stats.gear_metrics.avg_score']);
    expect(table.querySelector('tbody td')?.textContent?.trim()).toBe('7.1');
  });

  it('shows an empty state rather than an empty chart', () => {
    fixture.componentRef.setInput('items', []);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('trans_stats.no_data');
    expect(fixture.nativeElement.querySelector('canvas')).toBeNull();
  });

  it('should sort items correctly by count (default)', () => {
    fixture.detectChanges();
    const sorted = (component as any).sortedItems();
    expect(sorted.length).toBe(2);
    expect(sorted[0].name).toBe('Lens B'); // count 20 > count 10
  });

  it('should re-sort when metric changes to avg_score', () => {
    fixture.detectChanges();
    (component as any).selectedMetric.set('avg_score');
    fixture.detectChanges();

    const sorted = (component as any).sortedItems();
    expect(sorted[0].name).toBe('Lens B'); // avg_score 8.5 > 5.5
  });

  it('should sort correctly for usage_timeline metric', () => {
    fixture.detectChanges();
    (component as any).selectedMetric.set('usage_timeline');
    fixture.detectChanges();

    // Usage timeline defaults to sorting by count to show top N
    const sorted = (component as any).sortedItems();
    expect(sorted[0].name).toBe('Lens B');
  });

  it('names the metric select for assistive tech, since it carries no visible label', () => {
    fixture.detectChanges();
    const select = (fixture.nativeElement as HTMLElement).querySelector('mat-select') as HTMLElement;
    expect(select.getAttribute('aria-label')).toBe('trans_stats.gear_metric_label');
    expect((fixture.nativeElement as HTMLElement).querySelector('mat-label')).toBeNull();
  });

  it('shows the gallery sort icon of the selected metric in the select trigger', async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const icon = () => (fixture.nativeElement as HTMLElement).querySelector('.mat-mdc-select-value mat-icon') as HTMLElement;
    expect(icon().textContent!.trim()).toBe('leaderboard');
    (component as any).selectedMetric.set('avg_aesthetic');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(icon().textContent!.trim()).toBe('✦');
  });

  it('gives every option its icon', async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    ((fixture.nativeElement as HTMLElement).querySelector('.mat-mdc-select-trigger') as HTMLElement).click();
    fixture.detectChanges();
    await fixture.whenStable();
    const icons = Array.from(document.querySelectorAll('mat-option mat-icon')).map(el => el.textContent!.trim());
    expect(icons).toEqual(['numbers', 'leaderboard', '✦', 'deblur', 'iso', 'camera', 'zoom_in', 'show_chart']);
  });
});

describe('truncateLegendLabel', () => {
  it('leaves a short label untouched', () => {
    expect(truncateLegendLabel('Canon EOS R5')).toBe('Canon EOS R5');
  });

  it('shortens a long label to the limit with an ellipsis', () => {
    const out = truncateLegendLabel('KODAK EASYSHARE ZD710 ZOOM DIGITAL CAMERA');
    expect(out.length).toBeLessThanOrEqual(24);
    expect(out.endsWith('…')).toBe(true);
  });

  it('keeps a label of exactly the limit', () => {
    const exact = 'x'.repeat(24);
    expect(truncateLegendLabel(exact)).toBe(exact);
  });
});

describe('axisLabelIndexAt', () => {
  // A 3-row horizontal bar chart whose plot area starts 100 px in; each row is 50 px tall.
  const chart = {
    chartArea: { left: 100, top: 10, right: 300, bottom: 160 },
    scales: { y: { getValueForPixel: (y: number) => (y - 10) / 50 - 0.5 } },
    data: { labels: ['Canon EOS R5 Mark II', 'Nikon Z8', 'Sony A7 IV'] },
  } as unknown as Parameters<typeof axisLabelIndexAt>[0];

  it('maps a point on a label to that row', () => {
    expect(axisLabelIndexAt(chart, 40, 30)).toBe(0);
    expect(axisLabelIndexAt(chart, 40, 85)).toBe(1);
    expect(axisLabelIndexAt(chart, 99, 150)).toBe(2);
  });

  it('ignores the plot area, where Chart.js shows the tooltip itself, and points beside the rows', () => {
    expect(axisLabelIndexAt(chart, 100, 30)).toBeNull();
    expect(axisLabelIndexAt(chart, 40, 5)).toBeNull();
    expect(axisLabelIndexAt(chart, 40, 170)).toBeNull();
  });
});
