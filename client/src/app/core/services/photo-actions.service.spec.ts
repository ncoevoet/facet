import { provideRouter, Router } from '@angular/router';
import { TestBed } from '@angular/core/testing';
import { of, Subject } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { I18nService } from './i18n.service';
import { ApiService } from './api.service';
import { GalleryStore } from '../../features/gallery/gallery.store';
import { PhotoActionsService } from './photo-actions.service';
import { AuthService } from './auth.service';
import type { Mock } from 'vitest';

const mockPhoto: any = { path: '/photos/test.jpg' };

describe('PhotoActionsService', () => {
  let service: PhotoActionsService;
  let mockDialog: { open: Mock; openDialogs: unknown[] };
  let mockSnackBar: { open: Mock };
  let mockI18n: { t: Mock };
  let mockStore: { removePhotos?: Mock; config: Mock; persons: Mock; assignFace: Mock; createPerson: Mock; refreshPaths: Mock };

  // Every entry point here reaches its dialog through a dynamic `import()`, so the
  // first test to touch one pays for loading that lazy chunk inside its own
  // `waitFor` budget -- which is what makes these time out when the worker is busy.
  // Resolving them once up front leaves each test waiting only on its own promise.
  beforeAll(async () => {
    await Promise.all([
      import('../../features/gallery/photo-critique-dialog.component'),
      import('../../features/gallery/face-selector-dialog.component'),
      import('../../features/gallery/person-selector-dialog.component'),
    ]);
  });

  beforeEach(() => {
    mockDialog = {
      openDialogs: [],
      open: vi.fn(() => ({ afterClosed: () => of(null) })),
    };
    mockSnackBar = { open: vi.fn() };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockStore = {
      refreshPaths: vi.fn().mockResolvedValue(undefined),
      config: vi.fn(() => ({ features: { show_vlm_critique: false } })),
      persons: vi.fn(() => [
        { id: 1, name: 'Alice', face_count: 5 },
        { id: 2, name: null, face_count: 1 },
      ]),
      assignFace: vi.fn().mockResolvedValue(true),
      createPerson: vi.fn().mockResolvedValue({ id: 99, name: 'New Person', face_count: 1 }),
    };

    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: { identity: () => '1|test', isEdition: () => true, status: () => 'status', token: 't' } },
        PhotoActionsService,
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: GalleryStore, useValue: mockStore },
      ],
    });
    service = TestBed.inject(PhotoActionsService);
  });

  describe('removeFromCatalog count wording', () => {
    const run = async (paths: string[]) => {
      mockStore.removePhotos = vi.fn();
      mockDialog.open.mockReturnValue({ afterClosed: () => of(true) });
      vi.spyOn(TestBed.inject(ApiService), 'post').mockReturnValue(of({ removed_catalog: paths }) as never);
      await service.removeFromCatalog(paths);
      return { confirm: mockI18n.t.mock.calls.find(call => String(call[0]).includes('remove_catalog.confirm'))?.[0],
        result: mockI18n.t.mock.calls.find(call => String(call[0]).includes('remove_catalog.result'))?.[0] };
    };

    it('uses the singular keys for one photo', async () => {
      expect(await run(['/a.jpg'])).toEqual({ confirm: 'photo_detail.remove_catalog.confirm', result: 'photo_detail.remove_catalog.result' });
    });

    it('uses the plural keys for several photos', async () => {
      expect(await run(['/a.jpg', '/b.jpg'])).toEqual({ confirm: 'photo_detail.remove_catalog.confirm_plural', result: 'photo_detail.remove_catalog.result_plural' });
    });

    it('uses the plural result key when nothing was removed', async () => {
      mockStore.removePhotos = vi.fn();
      mockDialog.open.mockReturnValue({ afterClosed: () => of(true) });
      vi.spyOn(TestBed.inject(ApiService), 'post').mockReturnValue(of({ removed_catalog: [] }) as never);
      await service.removeFromCatalog(['/a.jpg']);
      expect(mockI18n.t.mock.calls.some(call => call[0] === 'photo_detail.remove_catalog.result_plural')).toBe(true);
    });
  });

  describe('refreshPhotos', () => {
    it('suppresses a lazy launch after real router navigation', async () => {
      const loaded = await import('../../features/photo-detail/photo-refresh-dialog.component');
      let finish!: (module: typeof loaded) => void;
      vi.spyOn(service as unknown as { loadRefreshDialog(): Promise<typeof loaded> }, 'loadRefreshDialog')
        .mockImplementation(() => new Promise(resolve => { finish = resolve; }));
      const pending = service.refreshPhotos(['/a.jpg']);
      await TestBed.inject(Router).navigateByUrl('/?other=1');
      finish(loaded);
      expect(await pending).toEqual([]);
      expect(mockDialog.open).not.toHaveBeenCalled();
    });

    it('refreshes only returned paths and refuses duplicate launches', async () => {
      const done = new Subject<string[]>();
      mockDialog.open.mockReturnValue({ afterClosed: () => done, componentInstance: { completed: () => [] } });
      const pending = service.refreshPhotos(['/a.jpg', '/b.jpg']);
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalledTimes(1));
      expect(await service.refreshPhotos(['/c.jpg'])).toEqual([]);
      done.next(['/a.jpg']); done.complete();
      expect(await pending).toEqual(['/a.jpg']);
      expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(['/a.jpg']);
    });
  });

  describe('openCritique', () => {
    it('should open PhotoCritiqueDialogComponent with photo path and vlmAvailable', async () => {
      service.openCritique(mockPhoto);
      // The dialog component is lazy-loaded via dynamic import; wait for it to resolve.
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalled(), { timeout: 5000 });

      expect(mockDialog.open).toHaveBeenCalledWith(
        expect.any(Function),
        expect.objectContaining({
          data: { photoPath: '/photos/test.jpg', vlmAvailable: false },
          width: '95vw',
          maxWidth: '600px',
        }),
      );
    });

    it('should pass vlmAvailable=true when show_vlm_critique is true', async () => {
      mockStore.config.mockReturnValue({ features: { show_vlm_critique: true } });
      service.openCritique(mockPhoto);
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalled(), { timeout: 5000 });

      const call = mockDialog.open.mock.calls[0][1];
      expect(call.data.vlmAvailable).toBe(true);
    });
  });

  describe('openAddPerson', () => {
    it('does not submit a selection captured before switching accounts', async () => {
      const selected = new Subject<unknown>();
      mockDialog.open
        .mockReturnValueOnce({ afterClosed: () => of({ id: 10 }) })
        .mockReturnValueOnce({ afterClosed: () => selected });
      service.openAddPerson(mockPhoto);
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalledTimes(2));
      vi.spyOn(TestBed.inject(AuthService), 'identity').mockReturnValue('1|other');
      selected.next({ kind: 'select', person: { id: 1, name: 'Alice' } });
      selected.complete();
      expect(mockStore.assignFace).not.toHaveBeenCalled();
      expect(mockStore.createPerson).not.toHaveBeenCalled();
    });

    it('should open FaceSelectorDialogComponent first', async () => {
      service.openAddPerson(mockPhoto);
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalled(), { timeout: 5000 });

      expect(mockDialog.open).toHaveBeenCalledWith(
        expect.any(Function),
        expect.objectContaining({ data: { photoPath: '/photos/test.jpg' } }),
      );
    });

    it('should call onAssigned callback after successful face assignment', async () => {
      const selectedFace = { id: 10 };
      const selectedResult = { kind: 'select', person: { id: 1, name: 'Alice' } };
      const onAssigned = vi.fn();

      // Dialog 1 (face selector) returns a face
      // Dialog 2 (person selector) returns a person-select result
      mockDialog.open
        .mockReturnValueOnce({ afterClosed: () => of(selectedFace) })
        .mockReturnValueOnce({ afterClosed: () => of(selectedResult) });

      service.openAddPerson(mockPhoto, onAssigned);
      await vi.waitFor(() => expect(mockStore.assignFace).toHaveBeenCalled(), { timeout: 5000 });

      expect(mockStore.assignFace).toHaveBeenCalledWith(10, 1, '/photos/test.jpg', 'Alice');
      expect(onAssigned).toHaveBeenCalled();
    });

    it('should NOT call onAssigned or show a success toast when assignFace fails', async () => {
      mockStore.assignFace.mockResolvedValue(false);
      const selectedFace = { id: 10 };
      const selectedResult = { kind: 'select', person: { id: 1, name: 'Alice' } };
      const onAssigned = vi.fn();

      mockDialog.open
        .mockReturnValueOnce({ afterClosed: () => of(selectedFace) })
        .mockReturnValueOnce({ afterClosed: () => of(selectedResult) });

      service.openAddPerson(mockPhoto, onAssigned);
      await vi.waitFor(() => expect(mockStore.assignFace).toHaveBeenCalled(), { timeout: 5000 });
      await vi.waitFor(() => expect(mockSnackBar.open).toHaveBeenCalled(), { timeout: 5000 });

      expect(onAssigned).not.toHaveBeenCalled();
      expect(mockSnackBar.open).toHaveBeenCalledWith('errors.action_failed', '', { duration: 3000 });
    });

    it('should create a new person when dialog returns kind="create"', async () => {
      const selectedFace = { id: 10 };
      const createResult = { kind: 'create', name: 'NewPerson' };
      const onAssigned = vi.fn();

      mockDialog.open
        .mockReturnValueOnce({ afterClosed: () => of(selectedFace) })
        .mockReturnValueOnce({ afterClosed: () => of(createResult) });

      service.openAddPerson(mockPhoto, onAssigned);
      await vi.waitFor(() => expect(mockStore.createPerson).toHaveBeenCalled(), { timeout: 5000 });

      expect(mockStore.createPerson).toHaveBeenCalledWith('NewPerson', [10], '/photos/test.jpg');
      expect(mockStore.assignFace).not.toHaveBeenCalled();
      expect(onAssigned).toHaveBeenCalled();
    });

    it('should not open person selector when face dialog is cancelled', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of(null) });

      service.openAddPerson(mockPhoto);
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalled(), { timeout: 5000 });

      // Only the face selector should have been opened
      expect(mockDialog.open).toHaveBeenCalledTimes(1);
      expect(mockStore.assignFace).not.toHaveBeenCalled();
    });

    it('opens the shared server-backed selector without a gallery dropdown snapshot', async () => {
      const selectedFace = { id: 10 };
      mockDialog.open
        .mockReturnValueOnce({ afterClosed: () => of(selectedFace) })
        .mockReturnValueOnce({ afterClosed: () => of(null) });

      service.openAddPerson(mockPhoto);
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalledTimes(2), { timeout: 5000 });

      expect(mockDialog.open.mock.calls[1][1]).not.toHaveProperty('data');
    });
  });
});


describe('photo refresh dismissal with a real Material dialog', () => {
  it.each(['not started', 'partial'])(
    'returns completed paths after Escape when %s and the component is disposed', async mode => {
      const { provideHttpClient } = await import('@angular/common/http');
      const { provideHttpClientTesting, HttpTestingController } = await import('@angular/common/http/testing');
      const { MatDialogState } = await import('@angular/material/dialog');
      TestBed.configureTestingModule({ providers: [
        provideRouter([]), provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: { identity: () => 'alice', isEdition: () => true } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: GalleryStore, useValue: { refreshPaths: vi.fn().mockResolvedValue(undefined) } },
      ] });
      const service = TestBed.inject(PhotoActionsService);
      const dialog = TestBed.inject(MatDialog);
      const http = TestBed.inject(HttpTestingController);
      const pending = service.refreshPhotos(['/a.jpg', '/b.jpg']);
      await vi.waitFor(() => expect(dialog.openDialogs).toHaveLength(1));
      const ref = dialog.openDialogs[0];
      await vi.waitFor(() => expect(ref.getState()).toBe(MatDialogState.OPEN));
      if (mode === 'partial') {
        const run = ref.componentInstance.run();
        http.expectOne('/api/photos/refresh').flush({ refreshed: ['/a.jpg'], failed: [{ path: '/b.jpg', reason: 'failed' }] });
        await run;
        // A refreshed photo may have gained or lost GPS, so the Map link is re-checked.
        http.expectOne('/api/photos/map/count').flush({ count: 0 });
      }
      document.querySelector('mat-dialog-container h2')!.dispatchEvent(new KeyboardEvent('keydown',
        { key: 'Escape', keyCode: 27, bubbles: true, cancelable: true }));
      expect(await pending).toEqual(mode === 'partial' ? ['/a.jpg'] : []);
      expect(ref.componentInstance).toBeNull();
      expect(TestBed.inject(GalleryStore).refreshPaths).toHaveBeenCalledTimes(mode === 'partial' ? 1 : 0);
      http.verify();
    },
  );
});
