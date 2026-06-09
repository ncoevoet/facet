import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { AlbumService } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumsComponent } from './albums.component';

describe('AlbumsComponent', () => {
  let component: AlbumsComponent;
  let mockAlbumService: { list: Mock; delete: Mock };
  let mockAuth: { isEdition: Mock };
  let mockI18n: { t: Mock };
  let mockDialog: { open: Mock };

  const mockAlbumsResponse = {
    albums: [
      { id: 1, name: 'Trip', is_smart: false, is_shared: false },
      { id: 2, name: 'Smart', is_smart: true, is_shared: false },
    ],
    total: 5,
  };

  beforeEach(() => {
    mockAlbumService = {
      list: vi.fn(() => of(mockAlbumsResponse)),
      delete: vi.fn(() => of({})),
    };
    mockAuth = { isEdition: vi.fn(() => true) };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(true) })) };

    TestBed.configureTestingModule({
      providers: [
        AlbumsComponent,
        { provide: AlbumService, useValue: mockAlbumService },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatDialog, useValue: mockDialog },
      ],
    });
    component = TestBed.inject(AlbumsComponent);
  });

  const internals = () => component as any;

  it('creates', () => {
    expect(component).toBeTruthy();
  });

  it('loads albums from the service and reports hasMore when more remain', async () => {
    await internals().loadAlbums(true);
    expect(mockAlbumService.list).toHaveBeenCalled();
    expect(internals().albums().length).toBe(2);
    expect(internals().total()).toBe(5);
    expect(internals().hasMore()).toBe(true); // 2 loaded < 5 total
  });

  it('deleteAlbum removes the album after confirmation', async () => {
    await internals().loadAlbums(true);
    const album = internals().albums()[0];
    const event = { preventDefault: vi.fn(), stopPropagation: vi.fn() } as unknown as Event;

    await internals().deleteAlbum(event, album);

    expect(mockDialog.open).toHaveBeenCalled();
    expect(mockAlbumService.delete).toHaveBeenCalledWith(1);
    expect(internals().albums().some((a: { id: number }) => a.id === 1)).toBe(false);
    expect(internals().total()).toBe(4);
  });
});
