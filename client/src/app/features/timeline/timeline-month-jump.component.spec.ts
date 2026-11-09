import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { provideNativeDateAdapter, MAT_DATE_FORMATS } from '@angular/material/core';
import { MatDatepicker } from '@angular/material/datepicker';
import { TimelineMonthJumpComponent } from './timeline-month-jump.component';
import { I18nService } from '../../core/services/i18n.service';

describe('TimelineMonthJumpComponent', () => {
  function setup(year = '', month = '') {
    const navigate = vi.fn().mockResolvedValue(true);
    TestBed.configureTestingModule({ imports: [TimelineMonthJumpComponent], providers: [
      provideNativeDateAdapter(),
      { provide: Router, useValue: { navigate } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(TimelineMonthJumpComponent);
    fixture.componentRef.setInput('year', year); fixture.componentRef.setInput('month', month);
    fixture.detectChanges();
    const picker = fixture.debugElement.query(By.directive(MatDatepicker)).componentInstance as MatDatepicker<Date>;
    const input = (fixture.nativeElement as HTMLElement).querySelector('input')!;
    return { fixture, navigate, picker, input };
  }

  it('labels the field and opens on the multi-year view', () => {
    const v = setup();
    expect((v.fixture.nativeElement as HTMLElement).querySelector('mat-label')?.textContent).toContain('timeline.jump_month');
    expect(v.picker.startView).toBe('multi-year');
    expect(v.input.value).toBe('');
  });

  it('shows the route month, formatted as month and year, and nothing at the years level', () => {
    const v = setup('2026', '2');
    expect(v.input.value).toMatch(/February/); expect(v.input.value).toContain('2026');
    v.fixture.componentRef.setInput('month', ''); v.fixture.componentRef.setInput('year', ''); v.fixture.detectChanges();
    expect(v.input.value).toBe('');
  });

  it('navigates to the chosen month and closes the picker', () => {
    const v = setup(); const close = vi.spyOn(v.picker, 'close');
    v.picker.monthSelected.emit(new Date(2026, 1, 1));
    expect(v.navigate).toHaveBeenCalledExactlyOnceWith(['/timeline', '2026', '2']);
    expect(close).toHaveBeenCalled();
  });

  it('does not navigate while the route is inactive, but still closes', () => {
    const v = setup(); v.fixture.componentRef.setInput('disabled', true); const close = vi.spyOn(v.picker, 'close');
    v.picker.monthSelected.emit(new Date(2026, 1, 1));
    expect(v.navigate).not.toHaveBeenCalled(); expect(close).toHaveBeenCalled();
  });

  it('scopes its month-only display format to this component', () => {
    const v = setup();
    expect(v.fixture.debugElement.injector.get(MAT_DATE_FORMATS).display.dateInput).toEqual({ year: 'numeric', month: 'long' });
    expect(TestBed.inject(MAT_DATE_FORMATS).display.dateInput).not.toEqual({ year: 'numeric', month: 'long' });
  });
});
