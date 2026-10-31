import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { Router, provideRouter } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { AlbumService } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AlbumsComponent } from './albums.component';
import { PageContextService } from '../../core/agent/page-context.service';
import { AlbumsFiltersService } from './albums-filters.service';

describe('AlbumsComponent', () => {
  let component: AlbumsComponent;
  let mockAlbumService: { list: Mock; delete: Mock };
  let mockAuth: { isEdition: Mock; hasFeature: Mock };
  let mockI18n: { t: Mock; translations: Mock };
  let mockDialog: { open: Mock };
  let journal: { record: Mock };

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
    journal = { record: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        AlbumsComponent,
        provideRouter([{ path: 'albums', children: [] }, { path: 'persons', children: [] }]),
        { provide: AlbumService, useValue: mockAlbumService },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatDialog, useValue: mockDialog },
        { provide: UserActivityJournal, useValue: journal },
      ],
    });
    component = TestBed.inject(AlbumsComponent);
  });

  const internals = () => component as any;

  it('registers the albums page and reads its filters live', () => {
    const context = TestBed.inject(PageContextService);
    expect(context.snapshot()).toEqual({ id: 'albums', search: '', sort: 'updated_at', type: '' });
    TestBed.inject(AlbumsFiltersService).typeFilter.set('smart');
    expect(context.snapshot()).toMatchObject({ type: 'smart' });
  });

  it('creates', () => {
    expect(component).toBeTruthy();
  });

  describe('a navigation made by the assistant', () => {
    const filters = () => TestBed.inject(AlbumsFiltersService);
    const go = (url: string) => TestBed.inject(Router).navigateByUrl(url);

    it('sets the search to the query and resets the other filters', async () => {
      filters().typeFilter.set('smart');
      filters().sort.set('name');
      await go('/albums?search=trip');
      expect(filters().search()).toBe('trip');
      expect(filters().typeFilter()).toBe('');
      expect(filters().sort()).toBe('updated_at');
    });

    it('clears a previous search when the query is empty', async () => {
      filters().search.set('old');
      await go('/albums?search=');
      expect(filters().search()).toBe('');
    });

    it('applies the same query again over the user\'s own edit (a same-URL reload)', async () => {
      await go('/albums?search=trip');
      filters().search.set('typed by the user');
      await TestBed.inject(Router).navigate(['/albums'], { queryParams: { search: 'trip' }, onSameUrlNavigation: 'reload' });
      expect(filters().search()).toBe('trip');
    });

    it('removes the query from the URL once applied, so Back or a reload cannot re-apply it over the user\'s edits', async () => {
      const router = TestBed.inject(Router);
      await go('/albums?search=trip');
      await vi.waitFor(() => expect(router.url).toBe('/albums'));
      filters().search.set('beach');
      filters().sort.set('name');
      await go('/albums');
      expect(filters().search()).toBe('beach');
      expect(filters().sort()).toBe('name');
    });

    it('leaves the filters alone when the navigation names no search or goes to another page', async () => {
      filters().search.set('kept');
      await go('/albums');
      await go('/persons?search=x');
      expect(filters().search()).toBe('kept');
    });
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

  it('deleteAlbum journals the deletion once, and nothing when cancelled or failed', async () => {
    await internals().loadAlbums(true);
    const album = internals().albums()[0];
    const event = { preventDefault: vi.fn(), stopPropagation: vi.fn() } as unknown as Event;
    mockDialog.open.mockReturnValueOnce({ afterClosed: () => of(false) });
    await internals().deleteAlbum(event, album);
    mockAlbumService.delete.mockReturnValueOnce(throwError(() => new Error('boom')));
    await expect(internals().deleteAlbum(event, album)).rejects.toThrow('boom');
    expect(journal.record).not.toHaveBeenCalled();
    await internals().deleteAlbum(event, album);
    expect(journal.record).toHaveBeenCalledTimes(1);
    expect(journal.record).toHaveBeenCalledWith('album', [], { album_id: 1, action: 'delete' });
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
      expect.objectContaining({ disableClose: true, restoreFocus: '#album-actions-1' }),
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
    const dialogOpen = vi.spyOn(fixture.debugElement.injector.get(MatDialog), 'open')
      .mockReturnValue({ afterClosed: () => of(undefined) } as any);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const smartCard = Array.from(fixture.nativeElement.querySelectorAll('a'))
      .find((a: any) => a.textContent.includes('Smart')) as HTMLElement;
    expect(smartCard).toBeTruthy();

    expect(smartCard.querySelector('button')).toBeNull();
    const article = smartCard.closest('article')!;
    article.querySelector('button')!.click();
    fixture.detectChanges();
    await fixture.whenStable();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    const icons = Array.from(overlay.querySelectorAll('mat-icon')).map((i: any) => i.textContent.trim());
    expect(icons).toContain('tune');

    const action = Array.from(overlay.querySelectorAll('button'))
      .find(button => button.textContent?.includes('albums.scoring_context.action'))!;
    action.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(dialogOpen).toHaveBeenCalled();
    expect(overlay.querySelector('[role="menu"]')).toBeNull();
  });
});
