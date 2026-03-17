import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { I18nService } from './i18n.service';
import { GalleryStore } from '../../features/gallery/gallery.store';
import { PhotoActionsService } from './photo-actions.service';

// Mock lazy-loaded dialog components so dynamic imports resolve synchronously
jest.mock('../../features/gallery/photo-critique-dialog.component', () => ({
  PhotoCritiqueDialogComponent: class MockCritiqueDialog {},
}));
jest.mock('../../features/gallery/face-selector-dialog.component', () => ({
  FaceSelectorDialogComponent: class MockFaceSelector {},
}));
jest.mock('../../features/gallery/person-selector-dialog.component', () => ({
  PersonSelectorDialogComponent: class MockPersonSelector {},
}));

const mockPhoto: any = { path: '/photos/test.jpg' };

describe('PhotoActionsService', () => {
  let service: PhotoActionsService;
  let mockDialog: { open: jest.Mock };
  let mockSnackBar: { open: jest.Mock };
  let mockI18n: { t: jest.Mock };
  let mockStore: { config: jest.Mock; persons: jest.Mock; assignFace: jest.Mock };

  beforeEach(() => {
    mockDialog = {
      open: jest.fn(() => ({ afterClosed: () => of(null) })),
    };
    mockSnackBar = { open: jest.fn() };
    mockI18n = { t: jest.fn((key: string) => key) };
    mockStore = {
      config: jest.fn(() => ({ features: { show_vlm_critique: false } })),
      persons: jest.fn(() => [
        { id: 1, name: 'Alice', face_count: 5 },
        { id: 2, name: null, face_count: 1 },
      ]),
      assignFace: jest.fn().mockResolvedValue(undefined),
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
      await Promise.resolve(); // flush dynamic import

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
      await Promise.resolve();

      const call = mockDialog.open.mock.calls[0][1];
      expect(call.data.vlmAvailable).toBe(true);
    });
  });

  describe('openAddPerson', () => {
    it('should open FaceSelectorDialogComponent first', async () => {
      service.openAddPerson(mockPhoto);
      await Promise.resolve();

      expect(mockDialog.open).toHaveBeenCalledWith(
        expect.any(Function),
        expect.objectContaining({ data: { photoPath: '/photos/test.jpg' } }),
      );
    });

    it('should call onAssigned callback after successful face assignment', async () => {
      const selectedFace = { id: 10 };
      const selectedPerson = { id: 1, name: 'Alice' };
      const onAssigned = jest.fn();

      // Dialog 1 (face selector) returns a face
      // Dialog 2 (person selector) returns a person
      mockDialog.open
        .mockReturnValueOnce({ afterClosed: () => of(selectedFace) })
        .mockReturnValueOnce({ afterClosed: () => of(selectedPerson) });

      service.openAddPerson(mockPhoto, onAssigned);
      await Promise.resolve(); // flush face-selector import
      await Promise.resolve(); // flush person-selector import
      await Promise.resolve(); // flush afterClosed chain

      expect(mockStore.assignFace).toHaveBeenCalledWith(10, 1, '/photos/test.jpg', 'Alice');
      expect(onAssigned).toHaveBeenCalled();
    });

    it('should not open person selector when face dialog is cancelled', async () => {
      mockDialog.open.mockReturnValue({ afterClosed: () => of(null) });

      service.openAddPerson(mockPhoto);
      await Promise.resolve();

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
      await Promise.resolve();
      await Promise.resolve();

      // PersonSelector receives only named persons
      const personSelectorCall = mockDialog.open.mock.calls[1];
      const personsData = personSelectorCall[1].data;
      expect(personsData.every((p: any) => p.name !== null)).toBe(true);
      expect(personsData).toHaveLength(1); // only Alice (name: 'Alice'), not the unnamed one
    });
  });
});
