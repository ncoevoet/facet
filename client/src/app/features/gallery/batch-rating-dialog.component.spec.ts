import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { I18nService } from '../../core/services/i18n.service';
import { BatchRatingDialogComponent, type BatchRatingPreview } from './batch-rating-dialog.component';

describe('BatchRatingDialogComponent', () => {
  afterEach(() => TestBed.resetTestingModule());

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
  it.each([false, true])('shows the exact set-rating plan and scope (whole view: %s)', wholeView => {
    const close = vi.fn();
    const data: BatchRatingPreview = { paths: ['/a', '/b', '/c'], rating: 2, loaded: 1, wholeView,
      observed: [{ rating: 3, count: 1 }] };
    TestBed.configureTestingModule({ imports: [BatchRatingDialogComponent], providers: [
      { provide: MAT_DIALOG_DATA, useValue: data }, { provide: MatDialogRef, useValue: { close } },
      { provide: I18nService, useValue: { t: (key: string, values?: object) => key + JSON.stringify(values ?? {}), translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(BatchRatingDialogComponent); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.textContent).toContain(wholeView ? 'rating_preview.whole_scope' : 'rating_preview.scope');
    expect(root.querySelector('summary')!.textContent).toContain('"loaded":1,"total":3');
    expect(root.querySelector('[data-rating-plan]')!.textContent).toContain('set_plan{"count":3,"rating":2}');
    root.querySelector<HTMLButtonElement>('[data-apply-rating]')!.click();
    expect(close).toHaveBeenCalledExactlyOnceWith(2);
  });

  it('Cancel closes without returning a rating or applying the draft', () => {
    const close = vi.fn();
    TestBed.configureTestingModule({ imports: [BatchRatingDialogComponent], providers: [
      { provide: MAT_DIALOG_DATA, useValue: { paths: ['/a'], rating: 5, loaded: 1, wholeView: false, observed: [] } },
      { provide: MatDialogRef, useValue: { close } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(BatchRatingDialogComponent); fixture.detectChanges();
    fixture.nativeElement.querySelector('button[mat-dialog-close]').click();
    expect(close).toHaveBeenCalledExactlyOnceWith('');
  });

});
