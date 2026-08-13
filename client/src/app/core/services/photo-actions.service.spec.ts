import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { I18nService } from './i18n.service';
import { GalleryStore } from '../../features/gallery/gallery.store';
import { PhotoActionsService } from './photo-actions.service';

const mockPhoto: any = { path: '/photos/test.jpg' };

describe('PhotoActionsService', () => {
  let service: PhotoActionsService;
  let mockDialog: { open: Mock };
  let mockSnackBar: { open: Mock };
  let mockI18n: { t: Mock };
  let mockStore: { config: Mock; persons: Mock; assignFace: Mock; createPerson: Mock };

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
      open: vi.fn(() => ({ afterClosed: () => of(null) })),
    };
    mockSnackBar = { open: vi.fn() };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockStore = {
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
        PhotoActionsService,
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: GalleryStore, useValue: mockStore },
      ],
    });
    service = TestBed.inject(PhotoActionsService);
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

    it('should filter out unnamed persons for the selector', async () => {
      const selectedFace = { id: 10 };
      mockDialog.open
        .mockReturnValueOnce({ afterClosed: () => of(selectedFace) })
        .mockReturnValueOnce({ afterClosed: () => of(null) });

      service.openAddPerson(mockPhoto);
      await vi.waitFor(() => expect(mockDialog.open).toHaveBeenCalledTimes(2), { timeout: 5000 });

      // PersonSelector receives only named persons
      const personSelectorCall = mockDialog.open.mock.calls[1];
      const personsData = personSelectorCall[1].data;
      expect(personsData.every((p: any) => p.name !== null)).toBe(true);
      expect(personsData).toHaveLength(1); // only Alice (name: 'Alice'), not the unnamed one
    });
  });
});
