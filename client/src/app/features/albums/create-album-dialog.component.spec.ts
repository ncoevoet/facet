import { AuthService } from '../../core/services/auth.service';
import { provideRouter } from '@angular/router';
import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { AlbumService } from '../../core/services/album.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { CreateAlbumDialogComponent } from './create-album-dialog.component';

describe('CreateAlbumDialogComponent', () => {
  let component: CreateAlbumDialogComponent;
  let albumService: { create: Mock };
  let dialogRef: { close: Mock };
  let journal: { record: Mock };

  beforeEach(() => {
    albumService = { create: vi.fn(() => of({ id: 7, name: 'Trip' })) };
    dialogRef = { close: vi.fn() };
    journal = { record: vi.fn() };
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]), { provide: AuthService, useValue: { identity: () => 'owner', isEdition: () => true } },
        CreateAlbumDialogComponent,
        { provide: AlbumService, useValue: albumService },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: UserActivityJournal, useValue: journal },
      ],
    });
    component = TestBed.inject(CreateAlbumDialogComponent);
  });

  it('journals one create with the id and name once the album exists', async () => {
    component.name = ' Trip ';
    await component.save();
    expect(albumService.create).toHaveBeenCalledWith('Trip', '');
    expect(journal.record).toHaveBeenCalledTimes(1);
    expect(journal.record).toHaveBeenCalledWith('album', [], { album_id: 7, action: 'create', name: 'Trip' });
  });

  it('journals nothing when the request fails or the name is empty', async () => {
    component.name = '  ';
    await component.save();
    component.name = 'Trip';
    albumService.create.mockReturnValue(throwError(() => new Error('boom')));
    await component.save();
    expect(journal.record).not.toHaveBeenCalled();
    expect(component.saveFailed()).toBe(true);
    expect(component.saving()).toBe(false);
  });
});
