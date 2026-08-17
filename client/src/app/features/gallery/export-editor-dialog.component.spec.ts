import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ExportService } from '../../core/services/export.service';
import { I18nService } from '../../core/services/i18n.service';
import { ExportEditorDialogComponent, ExportEditorDialogData } from './export-editor-dialog.component';

describe('ExportEditorDialogComponent', () => {
  let component: ExportEditorDialogComponent;
  let exportAlbum: ReturnType<typeof vi.fn>;
  let dialogClose: ReturnType<typeof vi.fn>;

  function build(data: ExportEditorDialogData = { albumId: 7 }) {
    exportAlbum = vi.fn(() => of({ ok: true, mode: 'copy', copied: 1, skipped: 0, errors: 0 }));
    dialogClose = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: ExportService, useValue: { exportAlbum, exportSidecars: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    component = TestBed.runInInjectionContext(() => new ExportEditorDialogComponent());
  }

  it('clears errorDetail and closes on success', async () => {
    build();
    component.mode.set('copy');
    component.targetDir.set('/dest');
    await component.run();
    expect(dialogClose).toHaveBeenCalled();
    expect(component.errorDetail()).toBeNull();
  });

  it('surfaces the server-supplied reason instead of swallowing it', async () => {
    build();
    component.mode.set('copy');
    component.targetDir.set('/dest');
    exportAlbum.mockReturnValueOnce(throwError(() => ({
      error: { detail: 'target_dir is not an allowed export location. Configure viewer.export.allowed_target_dirs' },
    })));
    await component.run();
    expect(dialogClose).not.toHaveBeenCalled();
    expect(component.errorDetail()).toBe(
      'target_dir is not an allowed export location. Configure viewer.export.allowed_target_dirs',
    );
  });

  it('falls back to null errorDetail when the error has no detail', async () => {
    build();
    component.mode.set('copy');
    component.targetDir.set('/dest');
    exportAlbum.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.run();
    expect(component.errorDetail()).toBeNull();
  });

  it('does not crash on a non-string detail (FastAPI validation error list)', async () => {
    build();
    component.mode.set('copy');
    component.targetDir.set('/dest');
    exportAlbum.mockReturnValueOnce(throwError(() => ({
      error: { detail: [{ loc: ['body', 'target_dir'], msg: 'field required' }] },
    })));
    await component.run();
    expect(component.errorDetail()).toBeNull();
  });
});
