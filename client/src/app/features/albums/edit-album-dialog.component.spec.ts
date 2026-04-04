import { TestBed } from '@angular/core/testing';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of } from 'rxjs';
import { AlbumService } from '../../core/services/album.service';
import { EditAlbumDialogComponent, EditAlbumDialogData } from './edit-album-dialog.component';

describe('EditAlbumDialogComponent', () => {
   
  let component: any;
  let mockAlbumService: { update: jest.Mock };
  let mockDialogRef: { close: jest.Mock };

  const albumData: EditAlbumDialogData = {
    album: {
      id: 42,
      name: 'My Album',
      description: 'A nice album',
      cover_photo_path: null,
      first_photo_path: null,
      photo_count: 10,
      is_smart: false,
      smart_filter_json: null,
      is_shared: false,
    } as any,
  };

  beforeEach(() => {
    mockAlbumService = {
      update: jest.fn(() => of({ ...albumData.album, name: 'Updated' })),
    };
    mockDialogRef = { close: jest.fn() };

    TestBed.configureTestingModule({
      providers: [
        EditAlbumDialogComponent,
        { provide: AlbumService, useValue: mockAlbumService },
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: albumData },
      ],
    });
    component = TestBed.inject(EditAlbumDialogComponent);
  });

  describe('initialization', () => {
    it('should populate name from dialog data', () => {
      expect(component.name).toBe('My Album');
    });

    it('should populate description from dialog data', () => {
      expect(component.description).toBe('A nice album');
    });

    it('should default description to empty string when null', () => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          EditAlbumDialogComponent,
          { provide: AlbumService, useValue: mockAlbumService },
          { provide: MatDialogRef, useValue: mockDialogRef },
          { provide: MAT_DIALOG_DATA, useValue: { album: { ...albumData.album, description: null } } },
        ],
      });
      const comp = TestBed.inject(EditAlbumDialogComponent);
      expect((comp as any).description).toBe('');
    });
  });

  describe('save', () => {
    it('should call albumService.update with trimmed values', async () => {
      component.name = '  Updated Name  ';
      component.description = '  Updated Description  ';

      await component.save();

      expect(mockAlbumService.update).toHaveBeenCalledWith(42, {
        name: 'Updated Name',
        description: 'Updated Description',
      });
    });

    it('should close dialog with the updated album', async () => {
      const updatedAlbum = { ...albumData.album, name: 'Updated' };
      mockAlbumService.update.mockReturnValue(of(updatedAlbum));

      await component.save();

      expect(mockDialogRef.close).toHaveBeenCalledWith(updatedAlbum);
    });

    it('should not save when name is empty', async () => {
      component.name = '   ';

      await component.save();

      expect(mockAlbumService.update).not.toHaveBeenCalled();
      expect(mockDialogRef.close).not.toHaveBeenCalled();
    });

    it('should not save when name is whitespace only', async () => {
      component.name = '\t\n  ';

      await component.save();

      expect(mockAlbumService.update).not.toHaveBeenCalled();
    });
  });
});
