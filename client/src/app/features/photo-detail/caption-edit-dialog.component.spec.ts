import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of, throwError, Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { GalleryStore } from '../gallery/gallery.store';
import { I18nService } from '../../core/services/i18n.service';
import { CaptionEditDialogComponent } from './caption-edit-dialog.component';

describe('CaptionEditDialogComponent', () => {
  let component: CaptionEditDialogComponent;
  let mockDialogRef: { close: Mock };
  let mockStore: { patchPhoto: Mock };
  let mockApi: { put: Mock };

  const dialogData = {
    path: '/photo.jpg',
    filename: 'photo.jpg',
    caption: 'A sunset over the mountains',
  };

  beforeEach(() => {
    mockDialogRef = { close: vi.fn() };
    mockStore = { patchPhoto: vi.fn() };
    mockApi = { put: vi.fn(() => of({})) };

    TestBed.configureTestingModule({
      providers: [
        CaptionEditDialogComponent,
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: dialogData },
        { provide: ApiService, useValue: mockApi },
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
    component = TestBed.inject(CaptionEditDialogComponent);
  });

  it('Cancel closes without a result, so the caller keeps the caption', () => {
    const fixture = TestBed.createComponent(CaptionEditDialogComponent);
    fixture.detectChanges();

    (fixture.nativeElement.querySelector('mat-dialog-actions button') as HTMLButtonElement).click();

    expect(mockDialogRef.close).toHaveBeenCalledWith(undefined);
  });

  it('should initialize with data from dialog', () => {
    expect(component.data.path).toBe('/photo.jpg');
    expect(component.data.filename).toBe('photo.jpg');
    expect(component.captionText).toBe('A sunset over the mountains');
  });

  it('should start with saving false', () => {
    expect(component.saving()).toBe(false);
  });

  it('should call API and close dialog on save', async () => {
    component.captionText = 'Updated caption';

    await component.save();

    expect(mockApi.put).toHaveBeenCalledWith('/caption', {
      path: '/photo.jpg',
      caption: 'Updated caption',
    });
    expect(mockDialogRef.close).toHaveBeenCalledWith('Updated caption');
    expect(component.saving()).toBe(false);
  });

  it('save writes the caption to the gallery copy even if Back already closed the dialog', async () => {
    component.captionText = '';
    await component.save();

    expect(mockStore.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { caption: null, caption_translated: undefined });
  });

  it('should not close dialog on save error', async () => {
    mockApi.put.mockReturnValue(throwError(() => new Error('Server error')));

    await component.save();

    expect(mockDialogRef.close).not.toHaveBeenCalled();
    expect(component.saving()).toBe(false);
  });

  it('should set saving true during request', async () => {
    let savingDuringRequest = false;
    mockApi.put.mockImplementation(() => {
      savingDuringRequest = component.saving();
      return of({});
    });

    await component.save();

    expect(savingDuringRequest).toBe(true);
  });
  it.each([false, true])('keeps the submitted caption while inputs change (destroyed: %s)', async destroyed => {
    const pending = new Subject<unknown>();
    mockApi.put.mockReturnValue(pending);
    component.captionText = 'Submitted';
    const saving = component.save();
    component.captionText = 'Unsaved edit';
    const duplicate = component.save();
    if (destroyed) TestBed.resetTestingModule();
    pending.next({});
    await Promise.all([saving, duplicate]);
    expect(mockStore.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { caption: 'Submitted', caption_translated: undefined });
    expect(mockApi.put).toHaveBeenCalledExactlyOnceWith('/caption', { path: '/photo.jpg', caption: 'Submitted' });
    if (destroyed) expect(mockDialogRef.close).not.toHaveBeenCalled();
    else expect(mockDialogRef.close).toHaveBeenCalledWith('Submitted');
  });

  it('a failed save sets saveFailed, renders the alert and keeps the dialog open; a later success clears it', async () => {
    const fixture = TestBed.createComponent(CaptionEditDialogComponent);
    fixture.detectChanges();
    const cmp = fixture.componentInstance;
    mockApi.put.mockReturnValue(throwError(() => new Error('boom')));

    await cmp.save();
    fixture.detectChanges();

    expect(cmp.saveFailed()).toBe(true);
    expect(fixture.nativeElement.querySelector('[role="alert"]')).not.toBeNull();
    expect(mockDialogRef.close).not.toHaveBeenCalled();

    mockApi.put.mockReturnValue(of({}));
    await cmp.save();
    fixture.detectChanges();

    expect(cmp.saveFailed()).toBe(false);
    expect(fixture.nativeElement.querySelector('[role="alert"]')).toBeNull();
  });

  it('a failure arriving after the component is destroyed does not throw', async () => {
    const pending = new Subject<unknown>();
    mockApi.put.mockReturnValue(pending);
    const fixture = TestBed.createComponent(CaptionEditDialogComponent);
    fixture.detectChanges();
    const saving = fixture.componentInstance.save();
    fixture.destroy();
    pending.error(new Error('late'));
    await expect(saving).resolves.toBeUndefined();
  });

});
