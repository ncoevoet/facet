import { TestBed } from '@angular/core/testing';
import { Component, inject } from '@angular/core';
import { DensityPeriodPipe } from './timeline-density-period.pipe';
import { I18nService } from '../../core/services/i18n.service';

@Component({
  standalone: true,
  imports: [DensityPeriodPipe],
  template: `<span data-week>{{ bucket | densityPeriod: 'week': locale() }}</span>`,
})
class WeekHostComponent {
  // A bucket whose data never changes across the test: the label must still
  // follow the language, which reaches the pure pipe as its argument.
  readonly locale = inject(I18nService).locale;
  readonly bucket = { key: '2026-W45', label: '2026-W45', from: '2026-11-02', to: '2026-11-08', count: 3 };
}

describe('DensityPeriodPipe', () => {
  it('formats a week with its first and last day', () => {
    TestBed.configureTestingModule({ imports: [WeekHostComponent], providers: [I18nService] });
    TestBed.inject(I18nService).locale.set('en');
    const fixture = TestBed.createComponent(WeekHostComponent);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-week]')!.textContent!.trim())
      .toBe('2 Nov 2026 – 8 Nov 2026');
  });

  it('re-formats the labels of unchanged buckets when the language changes in place', () => {
    TestBed.configureTestingModule({ imports: [WeekHostComponent], providers: [I18nService] });
    const i18n = TestBed.inject(I18nService);
    i18n.locale.set('en');
    const fixture = TestBed.createComponent(WeekHostComponent);
    fixture.detectChanges();
    const el = (fixture.nativeElement as HTMLElement).querySelector('[data-week]') as HTMLElement;
    expect(el.textContent).toContain('2 Nov 2026');

    i18n.locale.set('zh');
    fixture.detectChanges();
    expect(el.textContent).toContain('2026年11月2日');
    expect(el.textContent).toContain('2026年11月8日');

    i18n.locale.set('en');
  });
});
