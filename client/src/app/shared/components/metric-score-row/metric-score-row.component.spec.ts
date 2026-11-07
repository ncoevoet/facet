import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { MetricDistribution } from '../../utils/metric-distribution';
import { MetricScoreRowComponent } from './metric-score-row.component';

@Component({
  imports: [MetricScoreRowComponent],
  template: `<app-metric-score-row label="Aesthetic" [range]="range()" [value]="value()">{{ value() }}</app-metric-score-row>`,
})
class HostComponent {
  readonly value = signal<number | null>(7.2);
  readonly range = signal<MetricDistribution | undefined>({ min: 0, max: 10, buckets: [1, 1] });
}

describe('MetricScoreRowComponent', () => {
  function render(range: MetricDistribution | undefined): HTMLElement {
    TestBed.configureTestingModule({
      imports: [HostComponent],
      providers: [{ provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } }],
    });
    const fixture = TestBed.createComponent(HostComponent);
    fixture.componentInstance.range.set(range);
    fixture.detectChanges();
    return fixture.nativeElement.querySelector('app-metric-score-row');
  }

  it('keeps the name, value and on-demand distribution in one compact row', () => {
    const row = render({ min: 0, max: 10, buckets: [1, 1] });
    expect(row.textContent).toContain('Aesthetic');
    expect(row.querySelector('.font-semibold')?.textContent?.trim()).toBe('7.2');
    expect(row.querySelector('app-metric-rank')).not.toBeNull();
    expect(row.querySelector('app-metric-sparkline')).toBeNull();
  });

  it('keeps the value and name without a distribution', () => {
    const row = render(undefined);
    expect(row.querySelector('app-metric-rank')).toBeNull();
    expect(row.textContent).toContain('7.2');
    expect(row.textContent).toContain('Aesthetic');
  });

  it('replaces a missing score with explicit unavailable and hides its distribution', () => {
    render({ min: 0, max: 10, buckets: [1, 1] });
    const fixture = TestBed.createComponent(HostComponent);
    fixture.componentInstance.value.set(null);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('photo_detail.assessment.unavailable');
    expect(fixture.nativeElement.querySelector('app-metric-rank')).toBeNull();
  });
});
