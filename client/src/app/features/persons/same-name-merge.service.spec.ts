import type { Mock } from 'vitest';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { SameNameMergeDialogComponent, SameNameMergeService } from './same-name-merge.service';

const NAMESAKES = [
  { id: 5, name: 'Peter Salem', face_count: 77 },
  { id: 6, name: 'PETER SALEM', face_count: 4 },
];

describe('SameNameMergeDialogComponent', () => {
  let fixture: ComponentFixture<SameNameMergeDialogComponent>;
  let dialogRef: { close: Mock };

  beforeEach(() => {
    dialogRef = { close: vi.fn() };
    TestBed.configureTestingModule({
      imports: [SameNameMergeDialogComponent],
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: {
          name: 'peter salem', current: { id: 1, name: 'peter salem', face_count: 10 }, persons: NAMESAKES,
        } },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
    fixture = TestBed.createComponent(SameNameMergeDialogComponent);
    fixture.detectChanges();
  });

  const tiles = () => [...fixture.nativeElement.querySelectorAll('button[aria-pressed]')] as HTMLButtonElement[];
  const mergeButton = () => [...fixture.nativeElement.querySelectorAll('button')]
    .find((b) => (b as HTMLElement).textContent?.includes('persons.same_name_merge')) as HTMLButtonElement;

  it('shows a tile per person, the named cluster first, with thumbnail, name and faces, all selected', () => {
    expect(tiles().length).toBe(3);
    expect(tiles().map((t) => t.getAttribute('aria-pressed'))).toEqual(['true', 'true', 'true']);
    expect(tiles()[0].textContent).toContain('persons.same_name_this_group');
    expect(tiles()[1].textContent).toContain('Peter Salem');
    expect(tiles()[1].textContent).toContain('person_selector.face_count');
    expect(tiles()[1].querySelector('img')?.getAttribute('src')).toContain('5');
    expect(tiles().every((t) => t.querySelector('mat-icon')?.textContent?.trim() === 'check')).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('persons.same_name_message');
  });

  it('marks the largest selected person as kept, and moves the mark when it is deselected', () => {
    const kept = () => tiles().filter((t) => t.textContent?.includes('persons.same_name_kept'));
    expect(kept()).toEqual([tiles()[1]]);
    tiles()[1].click();
    fixture.detectChanges();
    expect(tiles()[1].getAttribute('aria-pressed')).toBe('false');
    expect(tiles()[1].querySelector('mat-icon')).toBeNull();
    expect(kept()).toEqual([tiles()[0]]);
  });

  it('closes with only the persons left selected', () => {
    tiles()[1].click();
    fixture.detectChanges();
    mergeButton().click();
    expect(dialogRef.close).toHaveBeenCalledWith([1, 6]);
  });

  it('cannot merge fewer than two persons', () => {
    tiles()[1].click();
    tiles()[2].click();
    fixture.detectChanges();
    expect(mergeButton().disabled).toBe(true);
  });
});

describe('SameNameMergeService', () => {
  let service: SameNameMergeService;
  let mockApi: { post: Mock };
  let mockDialog: { open: Mock };
  let snackBar: { open: Mock };

  beforeEach(() => {
    mockApi = { post: vi.fn(() => of({ success: true })) };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of([1, 5, 6]) })) };
    snackBar = { open: vi.fn() };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: snackBar },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    service = TestBed.inject(SameNameMergeService);
  });

  it('folds the renamed person and the ticked namesakes into the largest', async () => {
    const result = await service.offer({ id: 1, face_count: 10 }, 'peter salem', NAMESAKES);
    expect(mockApi.post).toHaveBeenCalledWith('/persons/merge_batch', {
      merges: [{ source_id: 1, target_id: 5 }, { source_id: 6, target_id: 5 }],
    });
    expect(result).toEqual({ status: 'merged', targetId: 5, merges: expect.any(Array) });
  });

  it('merges nothing when cancelled', async () => {
    mockDialog.open.mockReturnValue({ afterClosed: () => of(null) });
    expect(await service.offer({ id: 1, face_count: 10 }, 'x', NAMESAKES)).toEqual({ status: 'declined' });
    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it('reports a failed merge', async () => {
    mockApi.post.mockReturnValue(throwError(() => new Error('down')));
    expect(await service.offer({ id: 1, face_count: 10 }, 'x', NAMESAKES)).toEqual({ status: 'failed' });
    expect(snackBar.open).toHaveBeenCalledWith('persons.merge_error', '', { duration: 3000 });
  });
});
