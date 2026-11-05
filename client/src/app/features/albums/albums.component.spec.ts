import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { of, Subject, throwError } from 'rxjs';
import { Router, provideRouter } from '@angular/router';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { AlbumService } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AlbumsComponent } from './albums.component';
import { PageContextService } from '../../core/agent/page-context.service';
import { AlbumsFiltersService } from './albums-filters.service';

@Component({ imports: [MatDialogModule], template: '<button mat-dialog-close data-cancel-dialog>Cancel</button>' })
class CancelOnlyDialog {}

describe('AlbumsComponent', () => {
  let component: AlbumsComponent;
  let mockAlbumService: { list: Mock; delete: Mock };
  let mockAuth: { isEdition: Mock; hasFeature: Mock; identity: Mock };
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
    mockAuth = { identity: vi.fn(() => 'owner'), isEdition: vi.fn(() => true), hasFeature: vi.fn(() => true) };
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

  it('ignores an older filter response that arrives after the newer response', async () => {
    const oldResponse = new Subject<any>();
    const newResponse = new Subject<any>();
    mockAlbumService.list.mockReturnValueOnce(oldResponse).mockReturnValueOnce(newResponse);
    const oldLoad = internals().loadAlbums(true);
    const newLoad = internals().loadAlbums(true);
    newResponse.next({ albums: [{ id: 9, name: 'New' }], total: 1 });
    await newLoad;
    oldResponse.next({ albums: [{ id: 8, name: 'Old' }], total: 1 });
    await oldLoad;
    expect(internals().albums().map((a: { id: number }) => a.id)).toEqual([9]);
  });

  it('retries the failed page instead of skipping it', async () => {
    await internals().loadAlbums(true);
    mockAlbumService.list.mockReturnValueOnce(throwError(() => new Error('offline')));
    await internals().loadAlbums(false);
    expect(internals().loadFailed()).toBe(true);
    mockAlbumService.list.mockReturnValueOnce(of({ albums: [{ id: 3 }], total: 5 }));
    internals().retryLoad();
    await vi.waitFor(() => expect(internals().loadFailed()).toBe(false));
    expect(mockAlbumService.list.mock.calls.slice(-2).map(call => call[0].page)).toEqual([2, 2]);
    expect(internals().albums().map((a: { id: number }) => a.id)).toEqual([1, 2, 3]);
  });

  it('deleteAlbum removes the album after confirmation', async () => {
    await internals().loadAlbums(true);
    const album = internals().albums()[0];

    await internals().deleteAlbum(album);

    expect(mockDialog.open).toHaveBeenCalled();
    expect(mockAlbumService.delete).toHaveBeenCalledWith(1);
    expect(internals().albums().some((a: { id: number }) => a.id === 1)).toBe(false);
    expect(internals().total()).toBe(4);
  });

  it('renders a retry instead of an empty-albums message after a failed load', async () => {
    mockAlbumService.list.mockReturnValue(throwError(() => new Error('offline')));
    const fixture = TestBed.createComponent(AlbumsComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-albums-retry]')).not.toBeNull();
    expect(fixture.nativeElement.textContent).not.toContain('albums.empty');
    fixture.destroy();
  });

  it('places later-page retry after the cards and focuses the new card after retry', async () => {
    const fixture = TestBed.createComponent(AlbumsComponent);
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const page = fixture.componentInstance as any;
    mockAlbumService.list.mockReturnValueOnce(throwError(() => new Error('offline')));
    await page.loadAlbums(false);
    fixture.detectChanges();
    const retry = fixture.nativeElement.querySelector('[data-albums-retry]') as HTMLButtonElement;
    const cards = fixture.nativeElement.querySelectorAll('article');
    expect(cards.length).toBe(2);
    expect(cards[1].compareDocumentPosition(retry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(fixture.nativeElement.querySelector('#album-link-2 .sr-only')?.textContent).toContain('albums.smart_tooltip');
    mockAlbumService.list.mockReturnValueOnce(of({ albums: [{ id: 3, name: 'New' }], total: 3 }));
    retry.focus(); retry.click();
    await fixture.whenStable(); fixture.detectChanges(); await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('#album-link-3')).not.toBeNull();
    await vi.waitFor(() => expect(document.activeElement?.id).toBe('album-link-3'));
    fixture.destroy(); fixture.nativeElement.remove();
  });

  it('does not move focus after the user leaves Retry while a page is loading', async () => {
    const fixture = TestBed.createComponent(AlbumsComponent);
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const page = fixture.componentInstance as any;
    mockAlbumService.list.mockReturnValueOnce(throwError(() => new Error('offline')));
    await page.loadAlbums(false); fixture.detectChanges();
    const pending = new Subject<any>();
    mockAlbumService.list.mockReturnValueOnce(pending);
    const retry = fixture.nativeElement.querySelector('[data-albums-retry]') as HTMLButtonElement;
    retry.focus(); retry.click(); fixture.detectChanges();
    const other = fixture.nativeElement.querySelector('#album-link-1') as HTMLElement;
    other.focus();
    pending.next({ albums: [{ id: 3, name: 'New' }], total: 3 });
    await fixture.whenStable(); fixture.detectChanges(); await fixture.whenStable();
    expect(document.activeElement).toBe(other);
    fixture.destroy(); fixture.nativeElement.remove();
  });

  it('keeps focus on Retry when navigation is cancelled during a retry', async () => {
    const router = TestBed.inject(Router);
    router.resetConfig([{ path: 'blocked', canActivate: [() => false], children: [] }]);
    const fixture = TestBed.createComponent(AlbumsComponent);
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const page = fixture.componentInstance as any;
    mockAlbumService.list.mockReturnValueOnce(throwError(() => new Error('offline')));
    await page.loadAlbums(false); fixture.detectChanges();
    const pending = new Subject<any>();
    mockAlbumService.list.mockReturnValueOnce(pending);
    const retry = fixture.nativeElement.querySelector('[data-albums-retry]') as HTMLButtonElement;
    retry.focus(); retry.click(); fixture.detectChanges();
    expect(await router.navigateByUrl('/blocked')).toBe(false);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-albums-retry]')).toBe(retry);
    expect(document.activeElement).toBe(retry);
    pending.next({ albums: [], total: 0 });
    fixture.destroy(); fixture.nativeElement.remove();
  });

  it('does not delete after the account changes while confirmation is open', async () => {
    const confirmed = new Subject<boolean>();
    mockDialog.open.mockReturnValueOnce({ afterClosed: () => confirmed });
    const pending = internals().deleteAlbum({ id: 1, name: 'Trip' });
    mockAuth.identity.mockReturnValue('other-owner');
    confirmed.next(true);
    await pending;
    expect(mockAlbumService.delete).not.toHaveBeenCalled();
    expect(journal.record).not.toHaveBeenCalled();
  });

  it('deleteAlbum journals the deletion once, and nothing when cancelled or failed', async () => {
    await internals().loadAlbums(true);
    const album = internals().albums()[0];
    mockDialog.open.mockReturnValueOnce({ afterClosed: () => of(false) });
    await internals().deleteAlbum(album);
    mockAlbumService.delete.mockReturnValueOnce(throwError(() => new Error('boom')));
    await internals().deleteAlbum(album);
    expect(journal.record).not.toHaveBeenCalled();
    await internals().deleteAlbum(album);
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
    mockDialog.open.mockReturnValueOnce({ afterClosed: () => of('party_event') });

    await internals().openScoringContext(album);

    expect(mockDialog.open).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ disableClose: true, restoreFocus: '#album-actions-1' }),
    );
    expect(internals().albums().find((a: { id: number }) => a.id === album.id)?.scoring_context).toBe('party_event');
  });

  it.each(['albums.edit', 'albums.delete', 'albums.scoring_context.action', 'albums.portfolio', 'proofing.client_picks', 'albums.share'])(
    'restores real dialog focus to the album menu trigger after %s closes', async label => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({ imports: [AlbumsComponent, CancelOnlyDialog], providers: [
        provideRouter([]), { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        { provide: AlbumService, useValue: mockAlbumService }, { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n }, { provide: UserActivityJournal, useValue: journal },
      ] });
      const fixture = TestBed.createComponent(AlbumsComponent);
      document.body.appendChild(fixture.nativeElement);
      const dialog = fixture.debugElement.injector.get(MatDialog), open = dialog.open.bind(dialog);
      // Keep Material's real close/focus lifecycle while isolating each feature's dialog contents.
      const spy = vi.spyOn(dialog, 'open').mockImplementation((_component, config) => open(CancelOnlyDialog, config) as any);
      fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      const trigger = fixture.nativeElement.querySelector('#album-actions-1') as HTMLButtonElement;
      trigger.focus(); trigger.click(); fixture.detectChanges(); await fixture.whenStable();
      const overlay = TestBed.inject(OverlayContainer).getContainerElement();
      const action = overlay.querySelector<HTMLButtonElement>(`[role=menu] button[aria-label="${label}"]`);
      expect(action).not.toBeNull(); action!.click();
      fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      expect(spy).toHaveBeenCalledExactlyOnceWith(expect.anything(), expect.objectContaining({ restoreFocus: '#album-actions-1' }));
      const cancel = overlay.querySelector<HTMLButtonElement>('[data-cancel-dialog]')!;
      expect(cancel).not.toBeNull();
      expect(document.activeElement?.closest('mat-dialog-container')).toBe(cancel.closest('mat-dialog-container'));
      expect(document.activeElement).not.toBe(trigger); cancel.click();
      fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      expect(dialog.openDialogs).toHaveLength(0); expect(document.activeElement).toBe(trigger);
      expect(mockAlbumService.delete).not.toHaveBeenCalled();
      fixture.destroy(); fixture.nativeElement.remove();
    },
  );

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
    article.querySelector<HTMLButtonElement>('#album-actions-2')!.click();
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
