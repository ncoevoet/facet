import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MAT_SNACK_BAR_DATA } from '@angular/material/snack-bar';
import { I18nService } from '../../../core/services/i18n.service';
import { DownloadProgressSnackComponent } from './download-progress-snack.component';

describe('DownloadProgressSnackComponent', () => {
  const done = signal(0);
  const failed = signal(0);
  const cancel = vi.fn();

  beforeEach(() => {
    done.set(0); failed.set(0); cancel.mockClear();
    TestBed.configureTestingModule({
      imports: [DownloadProgressSnackComponent],
      providers: [
        { provide: MAT_SNACK_BAR_DATA, useValue: { done, failed, total: 4, cancel } },
        { provide: I18nService, useValue: { translations: () => ({}), t: (key: string, vars?: Record<string, unknown>) => `${key} ${JSON.stringify(vars ?? {})}` } },
      ],
    });
  });

  function render() {
    const fixture = TestBed.createComponent(DownloadProgressSnackComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('names the file in flight and fills the bar with the finished ones', () => {
    done.set(1);
    const el = render();
    expect(el.textContent).toContain('gallery.selection.download_progress {"done":2,"total":4}');
    expect(el.textContent).not.toContain('download_progress_failed');
    expect(el.querySelector('mat-progress-bar')?.getAttribute('aria-valuenow')).toBe('25');
  });

  it('follows the batch as it runs, holding at the total on the last file', () => {
    const fixture = TestBed.createComponent(DownloadProgressSnackComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('gallery.selection.download_progress {"done":1,"total":4}');
    expect(el.querySelector('mat-progress-bar')?.getAttribute('aria-valuenow')).toBe('0');
    done.set(4); failed.set(1);
    fixture.detectChanges();
    expect(el.textContent).toContain('gallery.selection.download_progress {"done":4,"total":4}');
    expect(el.textContent).toContain('gallery.selection.download_progress_failed {"failed":1}');
    expect(el.querySelector('mat-progress-bar')?.getAttribute('aria-valuenow')).toBe('100');
  });

  it('mentions failures once there are some', () => {
    done.set(2); failed.set(1);
    expect(render().textContent).toContain('gallery.selection.download_progress_failed {"failed":1}');
  });

  it('cancels from its action button', () => {
    (render().querySelector('button') as HTMLButtonElement).click();
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});
