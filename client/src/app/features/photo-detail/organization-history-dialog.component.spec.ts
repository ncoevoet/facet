import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { NavigationStart, Router } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { GalleryStore } from '../gallery/gallery.store';
import { OrganizationHistoryDialogComponent } from './organization-history-dialog.component';

const entry = { id: 1, kind: 'gps' as const, created_at: '2026-10-24', part: 1, parts: 2, reverted: false, changes: [{ path: '/a', before: [1, 2, 0], after: [3, 4, 1], revision: 4 }] };
describe('Organization history', () => {
  const api = { get: vi.fn(), post: vi.fn() };
  const store = { refreshPaths: vi.fn() };
  const closing = new Subject<void>();
  const dialog = { close: vi.fn(), beforeClosed: () => closing };
  const auth = { status: signal({ user_id: 'alice' }), isEdition: signal(true) };
  const router = { url: '/gallery', events: new Subject<NavigationStart>() };
  function create() {
    vi.clearAllMocks(); auth.status.set({ user_id: 'alice' }); auth.isEdition.set(true); router.url = '/gallery';
    api.get.mockReturnValue(of({ entries: [entry] }));
    api.post.mockReturnValue(of({ changed: 1 }));
    TestBed.configureTestingModule({ providers: [OrganizationHistoryDialogComponent,
      { provide: ApiService, useValue: api }, { provide: GalleryStore, useValue: store },
      { provide: AuthService, useValue: auth }, { provide: Router, useValue: router },
      { provide: MatDialogRef, useValue: dialog }] });
    return TestBed.inject(OrganizationHistoryDialogComponent);
  }
  it('only restores an explicitly chosen entry and refreshes the current view in place', async () => {
    const c = create(); await c.load();
    expect(api.post).not.toHaveBeenCalled();
    await c.revert(entry);
    expect(api.post).toHaveBeenCalledWith('/organization_history/1/revert', {});
    expect(store.refreshPaths).toHaveBeenCalledWith(null);
    expect(c.changed()).toBe(1);
  });
  it('does not publish a late private list after changing principal', async () => {
    const c = create(); const response = new Subject<{ entries: typeof entry[] }>();
    api.get.mockReturnValue(response); const pending = c.load();
    auth.status.set({ user_id: 'bob' }); response.next({ entries: [entry] }); await pending;
    expect(c.entries()).toEqual([]);
  });
  it('does not refresh or publish a late revert across auth or navigation', async () => {
    const c = create(); const response = new Subject<{ changed: number }>();
    api.post.mockReturnValue(response); const pending = c.revert(entry);
    router.url = '/albums'; response.next({ changed: 1 }); await pending;
    expect(store.refreshPaths).not.toHaveBeenCalled(); expect(c.changed()).toBeNull();
  });
  it('discards a revert after navigation away and back to the same URL', async () => {
    const c = create(); const response = new Subject<{ changed: number }>();
    api.post.mockReturnValue(response); const pending = c.revert(entry);
    router.events.next(new NavigationStart(1, '/albums'));
    router.events.next(new NavigationStart(2, '/gallery'));
    response.next({ changed: 1 }); await pending;
    expect(store.refreshPaths).not.toHaveBeenCalled(); expect(c.changed()).toBeNull();
  });
  it('discards a late revert after the principal changes', async () => {
    const c = create(); const response = new Subject<{ changed: number }>();
    api.post.mockReturnValue(response); const pending = c.revert(entry);
    auth.status.set({ user_id: 'bob' }); response.next({ changed: 1 }); await pending;
    expect(store.refreshPaths).not.toHaveBeenCalled(); expect(c.changed()).toBeNull();
  });
  it('discards a restore completing after dismissal starts while still alive', async () => {
    const c = create(); const response = new Subject<{ changed: number }>();
    api.post.mockReturnValue(response); const pending = c.revert(entry);
    closing.next();
    response.next({ changed: 1 }); await pending;
    expect(store.refreshPaths).not.toHaveBeenCalled();
    expect(c.wasRestored()).toBe(false);
    expect(c.changed()).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });
  it('discards a list completing after dismissal starts while still alive', async () => {
    const c = create(); const response = new Subject<{ entries: typeof entry[] }>();
    api.get.mockReturnValue(response); const pending = c.load();
    closing.next();
    response.next({ entries: [entry] }); await pending;
    expect(c.entries()).toEqual([]);
  });
  it('discards an error arriving after dismissal starts while still alive', async () => {
    const c = create(); const response = new Subject<{ changed: number }>();
    api.post.mockReturnValue(response); const pending = c.revert(entry);
    closing.next();
    response.error({ status: 409 }); await pending;
    expect(c.error()).toBeNull();
    expect(c.wasRestored()).toBe(false);
  });
  it('reports a conflict without pretending any photos were restored', async () => {
    const c = create(); api.post.mockReturnValue(throwError(() => ({ status: 409 })));
    await c.revert(entry); expect(c.error()).toBe('conflict');
    expect(store.refreshPaths).not.toHaveBeenCalled(); expect(c.changed()).toBeNull();
  });
});
