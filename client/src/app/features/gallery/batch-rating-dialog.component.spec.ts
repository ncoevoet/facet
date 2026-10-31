import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { I18nService } from '../../core/services/i18n.service';
import { BatchRatingDialogComponent } from './batch-rating-dialog.component';

describe('BatchRatingDialogComponent', () => {
  it('captures mixed observations and only returns Clear after explicit Apply', () => {
    const close = vi.fn();
    const data = { paths: ['/a', '/b', '/offscreen'], rating: 4, loaded: 2, wholeView: false, observed: [{ rating: 0, count: 1 }, { rating: 3, count: 1 }] };
    TestBed.configureTestingModule({ imports: [BatchRatingDialogComponent], providers: [
      { provide: MAT_DIALOG_DATA, useValue: data }, { provide: MatDialogRef, useValue: { close } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(BatchRatingDialogComponent); fixture.detectChanges();
    data.paths.push('/later');
    expect(fixture.componentInstance.data.paths).toEqual(['/a', '/b', '/offscreen']);
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('select');
    expect(select.value).toBe('4');
    select.value = '0'; select.dispatchEvent(new Event('change')); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-rating-plan]').textContent).toContain('clear_plan');
    expect(close).not.toHaveBeenCalled();
    fixture.nativeElement.querySelector('[data-apply-rating]').click();
    expect(close).toHaveBeenCalledExactlyOnceWith(0);
  });
});
