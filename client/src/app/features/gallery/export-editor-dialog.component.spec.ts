import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { ExportService } from '../../core/services/export.service';
import { I18nService } from '../../core/services/i18n.service';
import { ExportEditorDialogComponent, ExportEditorDialogData } from './export-editor-dialog.component';

describe('ExportEditorDialogComponent', () => {
  let component: ExportEditorDialogComponent;
  let exportAlbum: ReturnType<typeof vi.fn>;
  let exportSidecars: ReturnType<typeof vi.fn>;
  let exportSidecarsForView: ReturnType<typeof vi.fn>;
  let dialogClose: ReturnType<typeof vi.fn>;
  let apiPost: ReturnType<typeof vi.fn>;
  let snackBarOpen: ReturnType<typeof vi.fn>;

  function build(data: ExportEditorDialogData = { albumId: 7 }) {
    exportAlbum = vi.fn(() => of({ ok: true, mode: 'copy', copied: 1, skipped: 0, errors: 0 }));
    exportSidecars = vi.fn(() => of({ ok: true, written: 0, skipped: 0, errors: 0, sidecars: [] }));
    exportSidecarsForView = vi.fn(() => of({ ok: true, written: 5, skipped: 0, errors: 0, sidecars: [] }));
    dialogClose = vi.fn();
    apiPost = vi.fn(() => of({}));
    snackBarOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: ExportService, useValue: { exportAlbum, exportSidecars, exportSidecarsForView } },
        { provide: ApiService, useValue: { post: apiPost } },
        { provide: MatSnackBar, useValue: { open: snackBarOpen } },
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

  describe('Lightroom manifest download', () => {
    let createObjectURLSpy: ReturnType<typeof vi.spyOn>;
    let clickSpy: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
      vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
      clickSpy = vi.fn();
      const realCreateElement = document.createElement.bind(document);
      vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
        const el = realCreateElement(tag);
        if (tag === 'a') (el as HTMLAnchorElement).click = clickSpy as unknown as () => void;
        return el;
      });
      vi.spyOn(document.body, 'appendChild').mockImplementation(((n: Node) => n) as typeof document.body.appendChild);
      vi.spyOn(document.body, 'removeChild').mockImplementation(((n: Node) => n) as typeof document.body.removeChild);
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('posts the dialog scope (explicit paths) and saves the manifest as a file', async () => {
      build({ paths: ['/a.jpg', '/b.jpg'] });
      apiPost.mockReturnValueOnce(of({ version: 2, generated_at: 'x', photos: [], pending_corrections: 0 }));

      await component.downloadManifest();

      expect(apiPost).toHaveBeenCalledWith('/lightroom/manifest', { paths: ['/a.jpg', '/b.jpg'] });
      expect(createObjectURLSpy).toHaveBeenCalled();
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(snackBarOpen).not.toHaveBeenCalled();
    });

    it('posts a view-scoped filter selection', async () => {
      build({ filters: { type: 'aerial' }, exclude: ['a.jpg'] });
      apiPost.mockReturnValueOnce(of({ version: 2, generated_at: 'x', photos: [], pending_corrections: 0 }));

      await component.downloadManifest();

      expect(apiPost).toHaveBeenCalledWith('/lightroom/manifest', {
        filters: { type: 'aerial' }, exclude: ['a.jpg'],
      });
    });

    it('maps an album-only scope onto the gallery album_id filter key', async () => {
      build({ albumId: 7 });
      apiPost.mockReturnValueOnce(of({ version: 2, generated_at: 'x', photos: [], pending_corrections: 0 }));

      expect(component.canDownloadManifest()).toBe(true);
      await component.downloadManifest();

      expect(apiPost).toHaveBeenCalledWith('/lightroom/manifest', { filters: { album_id: '7' } });
    });

    it('warns when pending_corrections is greater than zero', async () => {
      build({ paths: ['/a.jpg'] });
      apiPost.mockReturnValueOnce(of({ version: 2, generated_at: 'x', photos: [], pending_corrections: 3 }));

      await component.downloadManifest();

      expect(snackBarOpen).toHaveBeenCalledWith(
        expect.stringContaining('export.lightroom.pending_corrections'), '', expect.anything(),
      );
    });

    it('shows no pending-corrections warning when the count is zero', async () => {
      build({ paths: ['/a.jpg'] });
      apiPost.mockReturnValueOnce(of({ version: 2, generated_at: 'x', photos: [], pending_corrections: 0 }));

      await component.downloadManifest();

      expect(snackBarOpen).not.toHaveBeenCalled();
    });
  });

  describe('Lightroom state import', () => {
    function fileEvent(text: string): Event {
      const file = new File([text], 'facet_manifest.json', { type: 'application/json' });
      const input = document.createElement('input');
      Object.defineProperty(input, 'files', { value: [file] });
      return { target: input } as unknown as Event;
    }

    it('parses the file and POSTs the parsed body', async () => {
      build();
      apiPost.mockReturnValueOnce(of({ matched: 3, unmatched: 1, changed: 2 }));

      await component.onImportFileSelected(fileEvent('{"format":"facet-lightroom-state","version":1,"photos":[]}'));

      expect(apiPost).toHaveBeenCalledWith('/lightroom/import', {
        format: 'facet-lightroom-state', version: 1, photos: [],
      });
      expect(snackBarOpen).toHaveBeenCalledWith(
        expect.stringContaining('export.lightroom.imported'), '', expect.anything(),
      );
    });

    it('shows an error and makes no request for invalid JSON', async () => {
      build();

      await component.onImportFileSelected(fileEvent('not json'));

      expect(apiPost).not.toHaveBeenCalled();
      expect(snackBarOpen).toHaveBeenCalledWith('export.lightroom.invalid_json', '', expect.anything());
    });

    it('surfaces the server detail on a 400/413 error', async () => {
      build();
      apiPost.mockReturnValueOnce(throwError(() => ({ error: { detail: 'Lightroom state file is too large' } })));

      await component.onImportFileSelected(fileEvent('{"format":"facet-lightroom-state","version":1,"photos":[]}'));

      expect(component.lightroomErrorDetail()).toBe('Lightroom state file is too large');
      expect(snackBarOpen).toHaveBeenCalledWith('export.lightroom.import_failed', '', expect.anything());
    });
  });
});
