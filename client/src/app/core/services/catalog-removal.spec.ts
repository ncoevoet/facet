import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, Subject } from 'rxjs';
import { PhotoActionsService } from './photo-actions.service';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { I18nService } from './i18n.service';
import { GalleryStore } from '../../features/gallery/gallery.store';

describe('explicit catalog removal', () => {
  let token: string;
  let edition: boolean;
  let close: Subject<boolean>;
  let post: ReturnType<typeof vi.fn>;
  let remove: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    token = 'session-a'; edition = true; close = new Subject<boolean>();
    post = vi.fn(() => of({ removed_catalog: ['/private.jpg'] }));
    remove = vi.fn();
    TestBed.configureTestingModule({ providers: [
      provideRouter([]),
      { provide: ApiService, useValue: { post } },
      { provide: AuthService, useValue: {
        identity: signal('alice'), status: signal({ user_id: 1 }), isEdition: () => edition,
        get token() { return token; },
      } },
      { provide: GalleryStore, useValue: { removePhotos: remove } },
      { provide: MatDialog, useValue: { open: vi.fn(() => ({ afterClosed: () => close })) } },
      { provide: MatSnackBar, useValue: { open: vi.fn() } },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ] });
  });

  it('captures explicit paths before confirmation and repairs only returned removals', async () => {
    const paths = ['/private.jpg'];
    const pending = TestBed.inject(PhotoActionsService).removeFromCatalog(paths);
    await vi.waitFor(() => expect(TestBed.inject(MatDialog).open).toHaveBeenCalled());
    paths.push('/new-selection.jpg');
    expect(post).not.toHaveBeenCalled();
    close.next(true);
    expect(await pending).toEqual(['/private.jpg']);
    expect(post).toHaveBeenCalledWith('/photo/delete', {
      paths: ['/private.jpg'], catalog_only: true, dry_run: false,
    });
    expect(remove).toHaveBeenCalledExactlyOnceWith(['/private.jpg']);
  });

  it('rechecks the caller decision after confirmation before sending a catalog write', async () => {
    let rejected = true;
    const pending = TestBed.inject(PhotoActionsService).removeFromCatalog(['/private.jpg'], () => rejected);
    await vi.waitFor(() => expect(TestBed.inject(MatDialog).open).toHaveBeenCalled());
    rejected = false; close.next(true);
    expect(await pending).toEqual([]);
    expect(post).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });

  it('does not submit after token rotation while confirming', async () => {
    const pending = TestBed.inject(PhotoActionsService).removeFromCatalog(['/private.jpg']);
    await vi.waitFor(() => expect(TestBed.inject(MatDialog).open).toHaveBeenCalled());
    token = 'session-b'; close.next(true);
    expect(await pending).toEqual([]);
    expect(post).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });

  it('erases entries from already-open thumbnail Cache objects and retains their namespaces', async () => {
    const bytes = new Map([['/thumbnail?path=private', 'private bytes']]);
    const request = new Request('http://localhost/thumbnail?path=private');
    const deleteEntry = vi.fn(async () => bytes.delete('/thumbnail?path=private'));
    const deleteNamespace = vi.fn(async () => {
      expect(bytes.size).toBe(0);
      return true;
    });
    vi.stubGlobal('caches', {
      keys: async () => ['ngsw:db:thumbnails:cache', 'unrelated'],
      open: vi.fn(async () => ({ keys: async () => [request], delete: deleteEntry })),
      delete: deleteNamespace,
    });
    try {
      const pending = TestBed.inject(PhotoActionsService).removeFromCatalog(['/private.jpg']);
      await vi.waitFor(() => expect(TestBed.inject(MatDialog).open).toHaveBeenCalled());
      close.next(true);
      expect(await pending).toEqual(['/private.jpg']);
      expect(deleteEntry).toHaveBeenCalledWith(request);
      expect(deleteNamespace).not.toHaveBeenCalled();
      expect(bytes.size).toBe(0);
    } finally { vi.unstubAllGlobals(); }
  });

  it('does not launch for read-only users', async () => {
    edition = false;
    expect(await TestBed.inject(PhotoActionsService).removeFromCatalog(['/private.jpg'])).toEqual([]);
    expect(TestBed.inject(MatDialog).open).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});
