import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { ConfirmDialogComponent } from './confirm-dialog.component';

describe('ConfirmDialogComponent', () => {
  let component: ConfirmDialogComponent;
  let mockDialogRef: { close: jest.Mock };

  beforeEach(() => {
    mockDialogRef = { close: jest.fn() };
    TestBed.configureTestingModule({
      providers: [
        ConfirmDialogComponent,
        { provide: MAT_DIALOG_DATA, useValue: { title: 'Confirm', message: 'Are you sure?' } },
        { provide: MatDialogRef, useValue: mockDialogRef },
      ],
    });
    component = TestBed.inject(ConfirmDialogComponent);
  });

  it('should inject dialog data', () => {
    expect(component.data.title).toBe('Confirm');
    expect(component.data.message).toBe('Are you sure?');
  });

  it('should default optional labels to undefined', () => {
    expect(component.data.cancelLabel).toBeUndefined();
    expect(component.data.confirmLabel).toBeUndefined();
  });

  it('should have dialogRef', () => {
    expect(component.dialogRef).toBeDefined();
  });

  it('cancel closes dialog with false', () => {
    component.dialogRef.close(false);
    expect(mockDialogRef.close).toHaveBeenCalledWith(false);
  });

  it('confirm closes dialog with true', () => {
    component.dialogRef.close(true);
    expect(mockDialogRef.close).toHaveBeenCalledWith(true);
  });
});
