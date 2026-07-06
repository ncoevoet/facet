import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { JunkSweepComponent } from './junk-sweep.component';

describe('JunkSweepComponent', () => {

  let component: any;
  let mockApi: { get: Mock; post: Mock };
  let mockI18n: { t: Mock };
  let mockSnackBar: { open: Mock };
  let mockDialog: { open: Mock };
  let photosCall: number;

  const initialPhotos = [
    { path: '/p/meme.jpg', filename: 'meme.jpg', junk_kind: 'meme', aggregate: 2.1 },
    { path: '/p/s1.jpg', filename: 's1.jpg', junk_kind: 'screenshot', aggregate: 1.0 },
    { path: '/p/s2.jpg', filename: 's2.jpg', junk_kind: 'screenshot', aggregate: 1.1 },
    { path: '/p/s3.jpg', filename: 's3.jpg', junk_kind: 'screenshot', aggregate: 1.2 },
  ];

  function createComponent() {
    photosCall = 0;
    mockApi = {
      get: vi.fn((url: string) => {
        if (url.includes('junk_kinds')) {
          return of({ junk_kinds: [['meme', 1], ['screenshot', 3]] });
        }
        photosCall += 1;
        if (photosCall === 1) {
          return of({ photos: initialPhotos, total: 4, total_pages: 1, page: 1, has_more: false });
        }
        return of({ photos: [], total: 0, total_pages: 1, page: 1, has_more: false });
      }),
      post: vi.fn(() => of({})),
    };
    mockI18n = { t: vi.fn((k: string) => k) };
    mockSnackBar = { open: vi.fn() };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(true) })) };

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        JunkSweepComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: MatDialog, useValue: mockDialog },
      ],
    });
    component = TestBed.inject(JunkSweepComponent);
  }

  it('reads the total candidate count from the API `total` field, not `total_count`', async () => {
    createComponent();

    await component.ngOnInit();

    expect(component.total()).toBe(4);
  });

  it('keeps the counter a finite number after rejecting a photo (no NaN)', async () => {
    createComponent();
    await component.ngOnInit();

    await component.reject(initialPhotos[1]);

    expect(component.total()).toBe(3);
    expect(Number.isNaN(component.total())).toBe(false);
  });

  it('rejectAllShown refreshes per-kind chip counts instead of leaving them stale', async () => {
    createComponent();
    await component.ngOnInit();
    expect(component.kinds()).toEqual([['meme', 1], ['screenshot', 3]]);

    await component.rejectAllShown();

    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_reject', {
      photo_paths: initialPhotos.map(p => p.path),
    });
    const counts = new Map(component.kinds() as [string, number][]);
    expect(counts.get('meme')).toBe(0);
    expect(counts.get('screenshot')).toBe(0);
  });
});
