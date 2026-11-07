import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationStart, Router, type Event } from '@angular/router';
import { Subject } from 'rxjs';
import { trackPendingNavigation } from './navigation-settled';

@Component({ template: '' })
class Owner {
  readonly started = vi.fn();
  readonly settled = vi.fn();
  readonly pending = trackPendingNavigation({
    blocks: event => !event.url.startsWith('/?'), started: this.started, settled: this.settled,
  });
}

describe('pending navigation ownership', () => {
  function create() {
    const events = new Subject<Event>();
    TestBed.configureTestingModule({ providers: [{ provide: Router, useValue: { events, currentNavigation: () => null } }] });
    const fixture = TestBed.createComponent(Owner);
    return { events, fixture, owner: fixture.componentInstance };
  }
  it('keeps a newer request locked through older completions and redirect cancellation', () => {
    const { events, owner } = create();
    events.next(new NavigationStart(2, '/albums')); events.next(new NavigationStart(3, '/persons'));
    events.next(new NavigationEnd(2, '/albums', '/albums'));
    expect(owner.pending()).toBe(true); expect(owner.settled).not.toHaveBeenCalled();
    events.next(new NavigationCancel(3, '/persons', 'redirect', NavigationCancellationCode.Redirect));
    expect(owner.pending()).toBe(true);
    events.next(new NavigationStart(4, '/login')); events.next(new NavigationEnd(4, '/login', '/login'));
    expect(owner.pending()).toBe(false); expect(owner.settled).toHaveBeenCalledTimes(1);
  });
  it('permits query-only work while retaining navigation ordering and lifetime cleanup', () => {
    const { events, fixture, owner } = create();
    events.next(new NavigationStart(5, '/?keyword_branch=trip'));
    expect(owner.pending()).toBe(false); expect(owner.started).toHaveBeenCalledTimes(1);
    events.next(new NavigationStart(4, '/albums'));
    expect(owner.pending()).toBe(false); expect(owner.started).toHaveBeenCalledTimes(1);
    events.next(new NavigationStart(6, '/persons'));
    expect(owner.pending()).toBe(true);
    events.next(new NavigationCancel(6, '/persons', 'guard refused', NavigationCancellationCode.GuardRejected));
    expect(owner.pending()).toBe(false);
    fixture.destroy(); events.next(new NavigationStart(7, '/albums'));
    expect(owner.started).toHaveBeenCalledTimes(2); expect(owner.pending()).toBe(false);
  });
});
