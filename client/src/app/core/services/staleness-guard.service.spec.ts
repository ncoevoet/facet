import { DestroyRef, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NavigationEnd, NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AuthService } from './auth.service';
import { StalenessGuardFactory } from './staleness-guard.service';

describe('StalenessGuardFactory', () => {
  const status = signal<{ user_id: string }>({ user_id: 'alice' });
  const edition = signal(true);
  let events: Subject<unknown>;
  let router: { url: string; events: Subject<unknown> };
  let destroyed: boolean;
  let onDestroy: (() => void)[];
  let destroyRef: DestroyRef;
  let factory: StalenessGuardFactory;

  beforeEach(() => {
    status.set({ user_id: 'alice' }); edition.set(true); destroyed = false; onDestroy = [];
    events = new Subject<unknown>();
    router = { url: '/a', events };
    destroyRef = {
      get destroyed() { return destroyed; },
      onDestroy: (cb: () => void) => { onDestroy.push(cb); return () => undefined; },
    } as DestroyRef;
    TestBed.configureTestingModule({ providers: [
      { provide: AuthService, useValue: { status, identity: () => status().user_id, isEdition: () => edition() } },
      { provide: Router, useValue: router },
    ] });
    factory = TestBed.inject(StalenessGuardFactory);
  });

  it('is current until the identity changes', () => {
    const guard = factory.create(destroyRef);
    expect(guard.current()).toBe(true);
    status.set({ user_id: 'alice' });
    expect(guard.current()).toBe(true);
    status.set({ user_id: 'bob' });
    expect(guard.current()).toBe(false);
    expect(guard.session()).toBe(false);
  });

  it('tracks the whole status object when asked, so a revalidation counts as a change', () => {
    const guard = factory.create(destroyRef, { track: 'status' });
    status.set({ user_id: 'alice' });
    expect(guard.current()).toBe(false);
  });

  it('is stale once edition access is lost', () => {
    const guard = factory.create(destroyRef);
    edition.set(false);
    expect(guard.current()).toBe(false);
  });

  it('permits read-only commands while retaining identity and navigation guards', () => {
    edition.set(false);
    const guard = factory.create(destroyRef, { requireEdition: false });
    expect(guard.current()).toBe(true);
    status.set({ user_id: 'bob' });
    expect(guard.current()).toBe(false);
    const next = factory.create(destroyRef, { requireEdition: false });
    events.next(new NavigationStart(1, '/b'));
    expect(next.current()).toBe(false);
  });

  it('is stale after a url change', () => {
    const guard = factory.create(destroyRef);
    router.url = '/b';
    expect(guard.current()).toBe(false);
  });

  it('stays stale after a navigation even when the url returns, and reports each navigation to onNavigate', () => {
    const onNavigate = vi.fn();
    const guard = factory.create(destroyRef, { onNavigate });
    events.next(new NavigationStart(1, '/b'));
    events.next(new NavigationStart(2, '/a'));
    expect(guard.current()).toBe(false);
    expect(onNavigate).toHaveBeenCalledTimes(2);
  });

  it('keeps the session valid after the owner is destroyed but not current()', () => {
    const guard = factory.create(destroyRef);
    destroyed = true;
    expect(guard.current()).toBe(false);
    expect(guard.session()).toBe(true);
  });

  it('honours the extra condition', () => {
    let path = '/one';
    const guard = factory.create(destroyRef, { valid: () => path === '/one' });
    expect(guard.current()).toBe(true);
    path = '/two';
    expect(guard.current()).toBe(false);
  });

  it('ignores router events other than NavigationStart', () => {
    const onNavigate = vi.fn();
    const guard = factory.create(destroyRef, { onNavigate });
    events.next(new NavigationEnd(1, '/a', '/a'));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(guard.current()).toBe(true);
  });

  it('stops watching navigation once the owner is destroyed', () => {
    const onNavigate = vi.fn();
    factory.create(destroyRef, { onNavigate });
    destroyed = true;
    onDestroy.forEach(cb => cb());
    events.next(new NavigationStart(1, '/b'));
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it('stops watching navigation once disposed', () => {
    const onNavigate = vi.fn();
    const guard = factory.create(destroyRef, { onNavigate });
    guard.dispose();
    events.next(new NavigationStart(1, '/b'));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(guard.current()).toBe(true);
  });
});
