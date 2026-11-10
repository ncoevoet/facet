import { TestBed } from '@angular/core/testing';
import { PhotoMetricSectionComponent } from './photo-metric-section.component';
import { I18nService } from '../../../core/services/i18n.service';
import { makePhoto } from '../../../../testing/photo.fixture';

describe('composition metric icons', () => {
  it('distinguishes composition, subject and form metrics while retaining their labels', () => {
    TestBed.configureTestingModule({ providers: [
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(PhotoMetricSectionComponent);
    fixture.componentRef.setInput('kind', 'composition');
    fixture.componentRef.setInput('histogramHeight', 80);
    fixture.componentRef.setInput('photo', makePhoto({ comp_score: 7, power_point_score: 7,
      leading_lines_score: 7, isolation_bonus: 7, subject_sharpness: 7, subject_prominence: 7,
      subject_placement: 7, bg_separation: 7, form_symmetry: 7, form_balance: 7,
      form_edge_entropy: 7, form_fractal: 7, color_harmony: 7 }));
    fixture.detectChanges();
    const rows = [...(fixture.nativeElement as HTMLElement).querySelectorAll('app-metric-score-row')];
    const icons = rows.map(row => row.querySelector('mat-icon')!.textContent!.trim());
    expect(icons).toHaveLength(13); expect(new Set(icons).size).toBe(13);
    expect(icons).not.toContain('analytics');
    expect(rows[0].textContent).toContain('tooltip.composition');
    expect(rows.at(-1)!.textContent).toContain('tooltip.color_harmony');
    expect(rows.every(row => row.querySelector('mat-icon')!.getAttribute('aria-hidden') === 'true')).toBe(true);
    fixture.destroy();
  });
});
