import { signal } from '@angular/core';
import { Router, NavigationStart } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { GalleryStore } from '../gallery/gallery.store';
import { CaptureDateDialogComponent, CaptureDateDialogData } from './capture-date-dialog.component';

const preview = { changed: 1, skipped: 0, samples: [{ path: '/a', old_date: '2024:01:01 00:00:00', new_date: '2024:01:01 01:00:00' }], preview_token: 'token' };
describe('CaptureDateDialogComponent', () => {
  const api = { post: vi.fn(), delete: vi.fn() };
  const store = { refreshPaths: vi.fn(), patchPhoto: vi.fn() };
  const closed = new Subject<void>();
  const events = new Subject<NavigationStart>();
  const status = signal({ user_id: 'alice', edition_authenticated: true });
  const router = { url: '/', events };
  const dialog = { close: vi.fn(), disableClose: false, beforeClosed: () => closed };
  function create(data: CaptureDateDialogData = { paths: ['/a'], count: 1, manuallySet: true, reference: { path: '/a', date: '2024:01:01 00:00:00' } }) {
    vi.clearAllMocks();
    status.set({ user_id: 'alice', edition_authenticated: true });
    router.url = '/';
    TestBed.configureTestingModule({ providers: [CaptureDateDialogComponent,
      { provide: AuthService, useValue: { status, isEdition: () => status().edition_authenticated } },
      { provide: Router, useValue: router },
      { provide: ApiService, useValue: api }, { provide: GalleryStore, useValue: store },
      { provide: MatDialogRef, useValue: dialog }, { provide: MAT_DIALOG_DATA, useValue: data }] });
    api.post.mockReturnValue(of(preview));
    return TestBed.inject(CaptureDateDialogComponent);
  }
  it('requires a preview and invalidates it when offset changes', async () => {
    const c = create();
    await c.apply();
    expect(api.post).not.toHaveBeenCalled();
    await c.preview();
    expect(c.result()).toEqual(preview);
    c.setOffset(10);
    expect(c.result()).toBeNull();
    await c.apply();
    expect(api.post).toHaveBeenCalledTimes(1);
  });
  it('applies the exact preview and refreshes without replacing current pins or selection', async () => {
    const c = create();
    await c.preview();
    await c.apply();
    expect(api.post).toHaveBeenLastCalledWith('/photos/capture_date/apply', { photo_paths: ['/a'], exclude: [], offset_seconds: 3600, preview_token: 'token' });
    expect(store.refreshPaths).toHaveBeenCalledWith(null);
    expect(dialog.close).toHaveBeenCalled();
  });
  it('does not keep a stale preview after a conflict', async () => {
    const c = create();
    await c.preview();
    api.post.mockReturnValue(throwError(() => ({ status: 409 })));
    await c.apply();
    expect(c.result()).toBeNull();
    expect(c.failed()).toBe(true);
    expect(dialog.close).not.toHaveBeenCalled();
  });
  it('discards a preview resolving after offset changed', async () => {
    const c = create();
    const pending = new Subject<typeof preview>();
    api.post.mockReturnValue(pending);
    const task = c.preview();
    c.setOffset(60);
    pending.next(preview);
    await task;
    expect(c.result()).toBeNull();
  });
  it('reset patches the original photo and refreshes the current gallery', async () => {
    const c = create();
    api.delete.mockReturnValue(of({ date_taken: null, date_manually_set: 0 }));
    await c.useFileDate();
    expect(api.delete).toHaveBeenCalledWith('/photo/capture_date?path=%2Fa');
    expect(store.patchPhoto).toHaveBeenCalledWith('/a', { date_taken: null, date_manually_set: 0 });
    expect(store.refreshPaths).toHaveBeenCalledWith(null);
  });
  it('opens in Exact mode for one undated photo and posts set_date, never offset_seconds', async () => {
    const c = create({ paths: ['/a'], count: 1, reference: null });
    expect(c.mode()).toBe('exact');
    expect(c.valid()).toBe(false);
    await c.preview();
    expect(api.post).not.toHaveBeenCalled();
    c.setExact('2024-05-06T07:08');
    expect(c.valid()).toBe(true);
    api.post.mockReturnValue(of({ ...preview, samples: [{ path: '/a', old_date: null, new_date: '2024:05:06 07:08:00' }] }));
    await c.preview();
    expect(api.post).toHaveBeenLastCalledWith('/photos/capture_date/preview', { photo_paths: ['/a'], exclude: [], set_date: '2024-05-06T07:08:00' });
    await c.apply();
    expect(api.post).toHaveBeenLastCalledWith('/photos/capture_date/apply', { photo_paths: ['/a'], exclude: [], set_date: '2024-05-06T07:08:00', preview_token: 'token' });
    expect(store.patchPhoto).toHaveBeenCalledWith('/a', { date_taken: '2024:05:06 07:08:00', date_manually_set: 1 });
  });
  it('rejects an impossible absolute date', () => {
    const c = create({ paths: ['/a'], count: 1, reference: null });
    c.setExact('2024-04-31T07:08');
    expect(c.valid()).toBe(false);
  });
  it('opens in Shift for several photos without a reference, and Exact there is an absolute set', async () => {
    const c = create({ paths: ['/a', '/b'], count: 2, reference: null });
    expect(c.mode()).toBe('shift');
    c.setMode('exact');
    c.setExact('2024-05-06T07:08:09');
    await c.preview();
    expect(api.post).toHaveBeenLastCalledWith('/photos/capture_date/preview', { photo_paths: ['/a', '/b'], exclude: [], set_date: '2024-05-06T07:08:09' });
    c.setMode('shift');
    expect(c.valid()).toBe(true);
  });
  it('keeps Exact as an offset when a dated reference exists', async () => {
    const c = create();
    expect(c.mode()).toBe('shift');
    c.setMode('exact');
    c.setExact('2024-01-01T00:00:30');
    await c.preview();
    expect(api.post).toHaveBeenLastCalledWith('/photos/capture_date/preview', { photo_paths: ['/a'], exclude: [], offset_seconds: 30 });
  });
  it('rejects more than 1000 targets instead of chunking an atomic edit', async () => {
    const c = create({ paths: ['/a'], count: 1001, manuallySet: false });
    await c.preview();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('invalidates an already visible preview when ownership is lost', async () => {
    const c = create(); await c.preview();
    status.set({ user_id: 'bob', edition_authenticated: true });
    TestBed.tick();
    expect(c.result()).toBeNull(); expect(dialog.close).toHaveBeenCalled();
    api.post.mockClear(); await c.apply(); await c.preview(); await c.useFileDate();
    expect(api.post).not.toHaveBeenCalled(); expect(api.delete).not.toHaveBeenCalled();
  });
  for (const loss of ['identity', 'edition', 'dismissal', 'navigation', 'destroy']) {
    function invalidate() {
      if (loss === 'identity') status.set({ user_id: 'bob', edition_authenticated: true });
      if (loss === 'edition') status.set({ user_id: 'alice', edition_authenticated: false });
      if (loss === 'dismissal') closed.next();
      if (loss === 'navigation') { events.next(new NavigationStart(1, '/other')); events.next(new NavigationStart(2, '/')); }
      if (loss === 'destroy') TestBed.resetTestingModule();
    }
    it(`discards late preview and blocks further commands after ${loss}`, async () => {
      const c = create();
      const pending = new Subject<typeof preview>();
      api.post.mockReturnValue(pending);
      const task = c.preview();
      invalidate();
      pending.next(preview);
      await task;
      expect(c.result()).toBeNull();
      api.post.mockClear();
      await c.preview(); await c.apply(); await c.useFileDate();
      expect(api.post).not.toHaveBeenCalled();
      expect(api.delete).not.toHaveBeenCalled();
    });
    it.each(['apply', 'useFileDate'] as const)(`suppresses late %s publication after ${loss}`, async method => {
      const c = create();
      await c.preview();
      const pending = new Subject<unknown>();
      api.post.mockReturnValue(pending); api.delete.mockReturnValue(pending);
      const task = c[method]();
      invalidate();
      dialog.close.mockClear();
      pending.next({ date_taken: null, date_manually_set: 0 });
      await task;
      expect(store.patchPhoto).not.toHaveBeenCalled();
      expect(store.refreshPaths).not.toHaveBeenCalled();
      expect(dialog.close).not.toHaveBeenCalled();
    });
  }

});
