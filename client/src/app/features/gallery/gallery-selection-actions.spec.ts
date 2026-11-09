import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of } from 'rxjs';
import { signal } from '@angular/core';
import { AlbumService } from '../../core/services/album.service';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { SequenceOverrideService } from '../../core/services/sequence-override.service';
import { UndoService } from '../../core/services/undo.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { GalleryStore } from './gallery.store';
import { ExportEditorDialogComponent } from './export-editor-dialog.component';
import { GallerySelectionActions } from './gallery-selection-actions';

describe('GallerySelectionActions', () => {
  const selected = signal(new Set<string>());
  const dialog = { open: vi.fn() };
  const snackBar = { open: vi.fn() };
  let albumId: string | null;
  let actions: GallerySelectionActions;

  beforeEach(() => {
    selected.set(new Set());
    dialog.open.mockReset();
    snackBar.open.mockReset();
    albumId = null;
    const store = {
      selectedPaths: selected,
      excludedPaths: signal(new Set<string>()),
      viewScopeSelected: signal(false),
      selectionCount: () => selected().size,
      photos: () => [],
      filters: () => ({}),
      filterPayload: () => ({}),
      pinnedPaths: () => null,
      currentAlbum: () => null,
      refreshPaths: vi.fn(async () => undefined),
    };
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: GalleryStore, useValue: store },
        { provide: AuthService, useValue: { isEdition: () => true, identity: () => 'u', status: () => 's', token: 't' } },
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => albumId } } } },
        { provide: ApiService, useValue: {} },
        { provide: AlbumService, useValue: {} },
        { provide: MatDialog, useValue: dialog },
        { provide: MatSnackBar, useValue: snackBar },
        { provide: I18nService, useValue: { t: (key: string, params?: Record<string, unknown>) => `${key}|${JSON.stringify(params ?? {})}` } },
        { provide: UserActivityJournal, useValue: { record: vi.fn() } },
        { provide: PhotoActionsService, useValue: {} },
        { provide: UndoService, useValue: {} },
        { provide: SequenceOverrideService, useValue: {} },
      ],
    });
    actions = TestBed.runInInjectionContext(() => new GallerySelectionActions({ isActive: () => true, clearSelection: vi.fn(), albumAdded: vi.fn() }));
  });

  describe('openExportDialog on an album route', () => {
    it('exports the whole album when nothing is selected', () => {
      albumId = '7';
      actions.openExportDialog();
      expect(dialog.open).toHaveBeenCalledWith(ExportEditorDialogComponent, { width: '420px', data: { albumId: 7 } });
    });

    it('exports the selection, not the album, when photos are selected', () => {
      albumId = '7';
      selected.set(new Set(['/a.jpg']));
      actions.openExportDialog();
      expect(dialog.open).toHaveBeenCalledWith(ExportEditorDialogComponent, { width: '420px', data: { paths: ['/a.jpg'] } });
    });
  });

  describe('openManualTagsDialog', () => {
    const run = async (confirmedCount: number, uncertain = false) => {
      selected.set(new Set(['/a.jpg']));
      dialog.open.mockReturnValue({ afterClosed: () => of({ confirmedCount, tag: 't', action: 'add', incomplete: false, uncertain }) });
      await actions.openManualTagsDialog();
    };

    it('toasts the singular count after an apply, without an Undo action', async () => {
      await run(1);
      expect(snackBar.open).toHaveBeenCalledTimes(1);
      expect(snackBar.open.mock.calls[0][0]).toContain('manual_tags.batch.applied|');
      expect(snackBar.open.mock.calls[0][0]).not.toContain('applied_plural');
      expect(snackBar.open.mock.calls[0][1]).toBe('');
    });

    it('picks the plural key when more than one photo changed', async () => {
      await run(3);
      expect(snackBar.open.mock.calls[0][0]).toContain('manual_tags.batch.applied_plural');
    });

    it('stays silent when nothing was confirmed', async () => {
      await run(0);
      expect(snackBar.open).not.toHaveBeenCalled();
    });

    it('claims no applied count when the write is uncertain and confirmed nothing', async () => {
      await run(0, true);
      expect(snackBar.open).not.toHaveBeenCalled();
    });
  });
});
