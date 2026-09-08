import { signal } from '@angular/core';
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
  let exportSidecars: ReturnType<typeof vi.fn>;
  let exportSidecarsForView: ReturnType<typeof vi.fn>;
  let dialogClose: ReturnType<typeof vi.fn>;

  function build(data: ExportEditorDialogData = { albumId: 7 }) {
    exportAlbum = vi.fn(() => of({ ok: true, mode: 'copy', copied: 1, skipped: 0, errors: 0 }));
    exportSidecars = vi.fn(() => of({ ok: true, written: 0, skipped: 0, errors: 0, sidecars: [] }));
    exportSidecarsForView = vi.fn(() => of({ ok: true, written: 5, skipped: 0, errors: 0, sidecars: [] }));
    dialogClose = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: ExportService, useValue: { exportAlbum, exportSidecars, exportSidecarsForView } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        // `translations` is only read once the real template renders: the
        // translate pipe subscribes to the bundle even when `t` is stubbed.
        { provide: I18nService, useValue: { t: (k: string) => k, translations: signal({}) } },
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

  it('sends a view-scoped selection as filters, never as a path list', async () => {
    build({ filters: { type: 'aerial', hide_bursts: '1' }, exclude: ['a.jpg'], count: 129 });
    component.overwrite.set(true);
    await component.run();
    expect(exportSidecarsForView).toHaveBeenCalledWith({ type: 'aerial', hide_bursts: '1' }, ['a.jpg'], true);
    expect(exportSidecars).not.toHaveBeenCalled();
    expect(dialogClose).toHaveBeenCalled();
  });

  it('enables the sidecar run for a filters-only selection', () => {
    build({ filters: { type: 'aerial' } });
    expect(component.canRun()).toBe(true);
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

  // A view-scoped export sends a filter, so the dialog is the only place the
  // user can learn how many photos it is about to write sidecars for — the
  // cull dialog, which the same selection opens, has always said so.
  describe('how many photos the run will touch', () => {
    function render(data: ExportEditorDialogData): HTMLElement {
      build(data);
      const fixture = TestBed.createComponent(ExportEditorDialogComponent);
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    it('states the count a view-scoped selection stands for', () => {
      const el = render({ filters: { type: 'aerial' }, exclude: [], count: 129 });

      expect(el.textContent).toContain('129');
      expect(el.textContent).toContain('cull.selected');
    });

    it('falls back to the length of an explicit path selection', () => {
      const el = render({ paths: ['/a.jpg', '/b.jpg', '/c.jpg'] });

      expect(el.textContent).toContain('3');
      expect(el.textContent).toContain('cull.selected');
    });

    // An album export's rows are the album's, whatever they are: no count
    // reaches the client, so it states none rather than a wrong one.
    it('states nothing when neither a count nor a path list is given', () => {
      const el = render({ albumId: 7 });

      expect(el.textContent).not.toContain('cull.selected');
    });
  });
});
