import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { ClientPicksDialogComponent, ClientPicksDialogData } from './client-picks-dialog.component';

describe('ClientPicksDialogComponent', () => {

  let component: any;
  let mockApi: { get: Mock };
  let mockI18n: { t: Mock };
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
    mockI18n = { t: vi.fn((k: string) => k) };
    mockSnackBar = { open: vi.fn() };

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        ClientPicksDialogComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: MAT_DIALOG_DATA, useValue: data },
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

  it('empties picks and stops loading when the API fails', async () => {
    createComponent(() => throwError(() => new Error('boom')));

    await component.ngOnInit();

    expect(component.picks()).toEqual([]);
    expect(component.loading()).toBe(false);
  });

  it('copyFilenames copies picked basenames newline-joined then shows a snackbar', async () => {
    createComponent();
    await component.ngOnInit();

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    component.copyFilenames();

    expect(writeText).toHaveBeenCalledWith('IMG_1.jpg\nIMG_3.jpg');

    await Promise.resolve();
    expect(mockSnackBar.open).toHaveBeenCalled();
  });
});
