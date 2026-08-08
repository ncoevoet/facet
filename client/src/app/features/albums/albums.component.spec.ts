import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { provideRouter } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { AlbumService } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumsComponent } from './albums.component';

describe('AlbumsComponent', () => {
  let component: AlbumsComponent;
  let mockAlbumService: { list: Mock; delete: Mock };
  let mockAuth: { isEdition: Mock; hasFeature: Mock };
  let mockI18n: { t: Mock; translations: Mock };
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
    mockAuth = { isEdition: vi.fn(() => true), hasFeature: vi.fn(() => true) };
    mockI18n = { t: vi.fn((key: string) => key), translations: vi.fn(() => ({})) };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(true) })) };

    TestBed.configureTestingModule({
      providers: [
        AlbumsComponent,
        provideRouter([]),
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

  // Defect 4: the dialog must be opened with disableClose so ESC/backdrop dismissal
  // can't bypass its own close()/persisted-context logic and diverge from what the
  // server actually stored. This also pins that a context returned from the dialog
  // is applied to the in-memory album list.
  it('openScoringContext opens the dialog with disableClose and applies the returned context', async () => {
    await internals().loadAlbums(true);
    const album = internals().albums()[0];
    const event = { preventDefault: vi.fn(), stopPropagation: vi.fn() } as unknown as Event;
    mockDialog.open.mockReturnValueOnce({ afterClosed: () => of('party_event') });

    await internals().openScoringContext(event, album);

    expect(mockDialog.open).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ disableClose: true }),
    );
    expect(internals().albums().find((a: { id: number }) => a.id === album.id)?.scoring_context).toBe('party_event');
  });

  // DEFECT F7 regression: the scoring-context button was gated on `!album.is_smart`,
  // making it unreachable for every smart album (all 16 albums in the real library
  // are smart). Asserted against the RENDERED template, not `openScoringContext()`
  // called directly on the instance -- calling the method bypasses the template
  // gate entirely and would pass even with the bug present.
  it('renders the scoring-context button for a smart album', async () => {
    const fixture = TestBed.createComponent(AlbumsComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const smartCard = Array.from(fixture.nativeElement.querySelectorAll('a'))
      .find((a: any) => a.textContent.includes('Smart')) as HTMLElement;
    expect(smartCard).toBeTruthy();

    const icons = Array.from(smartCard.querySelectorAll('mat-icon')).map((i: any) => i.textContent.trim());
    expect(icons).toContain('tune');
  });
});
