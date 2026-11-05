import { AuthService } from '../../core/services/auth.service';
import { provideRouter } from '@angular/router';
import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { ClientPicksDialogComponent, ClientPicksDialogData } from './client-picks-dialog.component';

describe('ClientPicksDialogComponent', () => {

  let component: any;
  let mockApi: { get: Mock };
  let mockI18n: { t: Mock; translations: Mock };
  let mockSnackBar: { open: Mock };

  const data: ClientPicksDialogData = { albumId: 7, albumName: 'Wedding' };

  function createComponent(getImpl?: () => unknown) {
    mockApi = {
      get: vi.fn(getImpl ?? (() => of({
        picks: [
          { path: '/photos/a/IMG_1.jpg', picked: true, comment: 'nice', client_name: 'Alice', updated_at: '2026-07-01 12:34:56' },
          { path: '/photos/b\\IMG_2.jpg', picked: false, comment: null, client_name: null, updated_at: '2026-07-01 12:35:00' },
          { path: '/photos/a/IMG_3.jpg', picked: true, comment: null, client_name: 'Alice', updated_at: '2026-07-01 12:36:00' },
        ],
        count: 3,
      }))),
    };
    mockI18n = { t: vi.fn((k: string) => k), translations: vi.fn(() => ({})) };
    mockSnackBar = { open: vi.fn() };

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]), { provide: AuthService, useValue: { identity: () => 'owner', isEdition: () => true } },
        ClientPicksDialogComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: MAT_DIALOG_DATA, useValue: data },
        { provide: MatDialogRef, useValue: { close: vi.fn() } },
      ],
    });
    component = TestBed.inject(ClientPicksDialogComponent);
  }

  it('loads picks and derives basenames from both path separators', async () => {
    createComponent();

    await component.ngOnInit();

    expect(mockApi.get).toHaveBeenCalledWith('/albums/7/picks');
    expect(component.picks().map((p: { filename: string }) => p.filename))
      .toEqual(['IMG_1.jpg', 'IMG_2.jpg', 'IMG_3.jpg']);
    expect(component.loading()).toBe(false);
  });

  it('pickedCount counts only picked entries', async () => {
    createComponent();

    await component.ngOnInit();

    expect(component.pickedCount()).toBe(2);
  });

  it('reports a failed load and retries successfully', async () => {
    createComponent(() => throwError(() => new Error('boom')));

    await component.ngOnInit();

    expect(component.loadFailed()).toBe(true);
    expect(component.loading()).toBe(false);
    mockApi.get.mockReturnValueOnce(of({ picks: [{ path: '/p.jpg', picked: true }], count: 1 }));
    await component.load();
    expect(component.loadFailed()).toBe(false);
    expect(component.picks()[0].filename).toBe('p.jpg');
  });

  it.each([true, false])('preserves intentional focus while retrying picks (move=%s)', async move => {
    createComponent(() => throwError(() => new Error('offline')));
    const fixture = TestBed.createComponent(ClientPicksDialogComponent);
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
    await vi.waitFor(() => { fixture.detectChanges(); expect(fixture.nativeElement.querySelector('[role=alert]')).not.toBeNull(); });
    const pending = new Subject<any>();
    mockApi.get.mockReturnValueOnce(pending);
    const retry = fixture.nativeElement.querySelector('[role=alert] button') as HTMLButtonElement;
    retry.focus(); retry.click(); fixture.detectChanges();
    const back = fixture.nativeElement.querySelector('mat-dialog-actions button:last-child') as HTMLButtonElement;
    if (move) back.focus();
    pending.next({ picks: [{ path: '/a.jpg', picked: true }], count: 1 });
    await fixture.whenStable(); fixture.detectChanges(); await fixture.whenStable();
    await vi.waitFor(() => expect(document.activeElement).toBe(move ? back : fixture.nativeElement.querySelector('h2')));
    fixture.destroy(); fixture.nativeElement.remove();
  });

  it('copyFilenames copies picked basenames newline-joined then shows a snackbar', async () => {
    createComponent();
    await component.ngOnInit();

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    component.copyFilenames();

    expect(writeText).toHaveBeenCalledWith('IMG_1.jpg\nIMG_3.jpg');

    await vi.waitFor(() => expect(mockSnackBar.open).toHaveBeenCalled());
  });
});
