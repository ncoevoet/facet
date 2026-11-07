import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router, provideRouter } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { I18nService } from '../../core/services/i18n.service';
import { CreateAlbumDialogComponent } from './create-album-dialog.component';
import { EditAlbumDialogComponent } from './edit-album-dialog.component';
import { AlbumsComponent } from './albums.component';
import { AlbumsFiltersService } from './albums-filters.service';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';
import { ClientPicksDialogComponent } from './client-picks-dialog.component';

@Component({ template: '' }) class Page {}

describe('album dialogs and cancelled navigation', () => {
  let router: Router;
  let http: HttpTestingController;
  let decision: Subject<boolean>;
  let close: ReturnType<typeof vi.fn>;
  const owner = signal('owner');
  let enterGuard: () => Subject<boolean>;
  let closed: Subject<unknown>;

  beforeEach(async () => {
    decision = new Subject<boolean>();
    closed = new Subject<unknown>();
    close = vi.fn(value => { closed.next(value); closed.complete(); });
    owner.set('owner');
    enterGuard = vi.fn(() => decision);
    TestBed.configureTestingModule({ providers: [
      provideRouter([{ path: 'albums', component: Page }, { path: 'away', component: Page, canActivate: [() => enterGuard()] }]),
      provideHttpClient(), provideHttpClientTesting(),
      { provide: AuthService, useValue: { identity: owner, isEdition: () => true, hasFeature: () => true } },
      { provide: UserActivityJournal, useValue: { record: vi.fn() } },
      { provide: MatDialogRef, useValue: { close } },
      { provide: MatDialog, useValue: { open: () => ({ afterClosed: () => closed }) } },
      { provide: MAT_DIALOG_DATA, useValue: { albumId: 1, albumName: 'Trip', album: { id: 1, name: 'Trip', description: '' } } },
      { provide: MatSnackBar, useValue: { open: vi.fn() } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      CreateAlbumDialogComponent, EditAlbumDialogComponent, ClientPicksDialogComponent, AlbumsComponent,
    ] });
    router = TestBed.inject(Router);
    http = TestBed.inject(HttpTestingController);
    await router.navigateByUrl('/albums');
  });
  afterEach(() => http.verify());

  it('keeps an in-flight create locked until cancellation, then handles its success once', async () => {
    const dialog = TestBed.inject(CreateAlbumDialogComponent);
    dialog.name = 'Trip';
    const save = dialog.save();
    const req = http.expectOne('/api/albums');
    const navigation = router.navigateByUrl('/away');
    await vi.waitFor(() => expect(enterGuard).toHaveBeenCalled());
    req.flush({ id: 7, name: 'Trip' });
    await Promise.resolve();
    await dialog.save();
    http.expectNone('/api/albums');
    expect(close).not.toHaveBeenCalled();
    decision.next(false);
    await navigation;
    await save;
    expect(close).toHaveBeenCalledTimes(1);
    expect(close).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
  });

  it('allows retry after a failed edit completes during cancelled navigation', async () => {
    const dialog = TestBed.inject(EditAlbumDialogComponent) as any;
    dialog.name = 'New';
    const save = dialog.save();
    const req = http.expectOne('/api/albums/1');
    const navigation = router.navigateByUrl('/away');
    await vi.waitFor(() => expect(enterGuard).toHaveBeenCalled());
    req.flush('failed', { status: 500, statusText: 'Failed' });
    decision.next(false);
    await navigation;
    await save;
    expect(dialog.saveFailed()).toBe(true);
    const retry = dialog.save();
    http.expectOne('/api/albums/1').flush({ id: 1, name: 'New', description: '' });
    await retry;
    expect(close).toHaveBeenCalledTimes(1);
  });

  it('refreshes the enclosing list once when create succeeds through a cancelled navigation', async () => {
    const albums = TestBed.inject(AlbumsComponent) as any;
    TestBed.tick();
    const initialList = http.expectOne(req => req.url === '/api/albums' && req.method === 'GET');
    expect(initialList.request.context.get(HANDLE_SERVER_ERROR_LOCALLY)).toBe(true);
    initialList.flush({ albums: [], total: 0 });
    const opening = albums.openCreateDialog();
    const dialog = TestBed.inject(CreateAlbumDialogComponent);
    dialog.name = 'Trip';
    const saving = dialog.save();
    const request = http.expectOne(req => req.url === '/api/albums' && req.method === 'POST');
    const navigation = router.navigateByUrl('/away');
    await vi.waitFor(() => expect(enterGuard).toHaveBeenCalled());
    request.flush({ id: 7, name: 'Trip' });
    decision.next(false);
    await navigation;
    await saving;
    await opening;
    const refresh = http.expectOne(req => req.url === '/api/albums' && req.method === 'GET');
    refresh.flush({ albums: [{ id: 7, name: 'Trip' }], total: 1 });
    await vi.waitFor(() => expect(albums.albums()[0]?.name).toBe('Trip'));
    http.expectNone(req => req.url === '/api/albums');
  });

  it('updates the enclosing card when edit succeeds through cancelled navigation', async () => {
    const albums = TestBed.inject(AlbumsComponent) as any;
    TestBed.tick();
    http.expectOne(req => req.url === '/api/albums' && req.method === 'GET')
      .flush({ albums: [{ id: 1, name: 'Trip' }], total: 1 });
    await vi.waitFor(() => expect(albums.albums().length).toBe(1));
    const opening = albums.editAlbum(albums.albums()[0]);
    const dialog = TestBed.inject(EditAlbumDialogComponent) as any;
    dialog.name = 'New name';
    const saving = dialog.save();
    const request = http.expectOne('/api/albums/1');
    const navigation = router.navigateByUrl('/away');
    await vi.waitFor(() => expect(enterGuard).toHaveBeenCalled());
    request.flush({ id: 1, name: 'New name', description: '' });
    decision.next(false);
    await navigation;
    await saving;
    await opening;
    expect(albums.albums()[0].name).toBe('New name');
    http.expectNone(req => req.url === '/api/albums');
  });

  it('removes the deleted card and updates the count after cancelled navigation', async () => {
    const albums = TestBed.inject(AlbumsComponent) as any;
    TestBed.tick();
    http.expectOne(req => req.url === '/api/albums' && req.method === 'GET')
      .flush({ albums: [{ id: 1, name: 'Trip' }, { id: 2, name: 'Family' }], total: 2 });
    await vi.waitFor(() => expect(albums.albums().length).toBe(2));
    const deleting = albums.deleteAlbum(albums.albums()[0]);
    closed.next(true);
    closed.complete();
    let request: ReturnType<HttpTestingController['expectOne']>;
    await vi.waitFor(() => { request = http.expectOne(req => req.url === '/api/albums/1' && req.method === 'DELETE'); });
    const navigation = router.navigateByUrl('/away');
    await vi.waitFor(() => expect(enterGuard).toHaveBeenCalled());
    request!.flush({ ok: true });
    decision.next(false);
    await navigation;
    await deleting;
    expect(albums.albums().map((album: { id: number }) => album.id)).toEqual([2]);
    expect(albums.total()).toBe(1);
    expect(TestBed.inject(UserActivityJournal).record).toHaveBeenCalledOnce();
    http.expectNone(req => req.url === '/api/albums/1');
  });

  it('refreshes current filters and ignores a stale list after a delayed delete', async () => {
    const albums = TestBed.inject(AlbumsComponent) as any;
    TestBed.tick();
    http.expectOne(req => req.url === '/api/albums' && req.method === 'GET')
      .flush({ albums: [{ id: 1, name: 'Trip' }], total: 1 });
    await vi.waitFor(() => expect(albums.albums().length).toBe(1));
    const deleting = albums.deleteAlbum(albums.albums()[0]);
    closed.next(true);
    closed.complete();
    let deleteRequest: ReturnType<HttpTestingController['expectOne']>;
    await vi.waitFor(() => { deleteRequest = http.expectOne(req => req.url === '/api/albums/1' && req.method === 'DELETE'); });
    TestBed.inject(AlbumsFiltersService).search.set('Family');
    TestBed.tick();
    const staleList = http.expectOne(req => req.url === '/api/albums' && req.method === 'GET' && req.params.get('search') === 'Family');
    deleteRequest!.flush({ ok: true });
    await deleting;
    const currentList = http.expectOne(req => req.url === '/api/albums' && req.method === 'GET' && req.params.get('search') === 'Family');
    currentList.flush({ albums: [{ id: 2, name: 'Family' }], total: 1 });
    staleList.flush({ albums: [{ id: 1, name: 'Trip' }], total: 2 });
    await vi.waitFor(() => expect(albums.albums().map((a: { id: number }) => a.id)).toEqual([2]));
    expect(albums.total()).toBe(1);
  });

  it('loads client picks after a cancellation and ignores a different owner', async () => {
    const dialog = TestBed.inject(ClientPicksDialogComponent) as any;
    const load = dialog.ngOnInit();
    const req = http.expectOne('/api/albums/1/picks');
    const navigation = router.navigateByUrl('/away');
    await vi.waitFor(() => expect(enterGuard).toHaveBeenCalled());
    req.flush({ picks: [{ path: '/a.jpg', picked: true }], count: 1 });
    decision.next(false);
    await navigation;
    await load;
    expect(dialog.picks()[0].filename).toBe('a.jpg');
    const second = dialog.load();
    const secondRequest = http.expectOne('/api/albums/1/picks');
    owner.set('other');
    TestBed.tick();
    expect(dialog.picks()).toEqual([]);
    expect(dialog.pickedCount()).toBe(0);
    owner.set('owner');
    TestBed.tick();
    secondRequest.flush({ picks: [{ path: '/private.jpg', picked: true }], count: 1 });
    await second;
    expect(dialog.picks()).toEqual([]);
    expect(close).toHaveBeenCalled();
  });
});
