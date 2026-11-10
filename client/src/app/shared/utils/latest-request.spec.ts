import { DestroyRef } from '@angular/core';
import { Observable } from 'rxjs';
import { LatestRequest } from './latest-request';

function makeDestroyRef() {
  const callbacks: (() => void)[] = [];
  const ref = {
    destroyed: false,
    onDestroy(cb: () => void) {
      callbacks.push(cb);
      return () => undefined;
    },
  };
  return {
    ref: ref as unknown as DestroyRef,
    destroy: () => {
      ref.destroyed = true;
      callbacks.forEach(cb => cb());
    },
  };
}

function probe() {
  const state = { subscribed: 0, unsubscribed: 0 };
  const source = new Observable<number>(() => {
    state.subscribed++;
    return () => { state.unsubscribed++; };
  });
  return { state, source };
}

describe('LatestRequest', () => {
  it('keeps a handle current until it is superseded', () => {
    const latest = new LatestRequest(makeDestroyRef().ref);
    const first = latest.begin();
    expect(first.isCurrent()).toBe(true);
    expect(first.isCurrent()).toBe(true);
  });

  it('supersedes the first handle and unsubscribes its source on a second begin()', () => {
    const latest = new LatestRequest(makeDestroyRef().ref);
    const first = latest.begin();
    const { state, source } = probe();
    const sub = first.bind(source).subscribe();
    expect(state.subscribed).toBe(1);
    const second = latest.begin();
    expect(first.isCurrent()).toBe(false);
    expect(second.isCurrent()).toBe(true);
    expect(state.unsubscribed).toBe(1);
    sub.unsubscribe();
  });

  it('cancel() supersedes the current handle without starting a new one', () => {
    const latest = new LatestRequest(makeDestroyRef().ref);
    const first = latest.begin();
    const { state, source } = probe();
    first.bind(source).subscribe();
    latest.cancel();
    expect(first.isCurrent()).toBe(false);
    expect(state.unsubscribed).toBe(1);
  });

  it('makes the handle not current and unsubscribes on destroy', () => {
    const destroy = makeDestroyRef();
    const latest = new LatestRequest(destroy.ref);
    const handle = latest.begin();
    const { state, source } = probe();
    handle.bind(source).subscribe();
    destroy.destroy();
    expect(handle.isCurrent()).toBe(false);
    expect(state.unsubscribed).toBe(1);
  });
});
