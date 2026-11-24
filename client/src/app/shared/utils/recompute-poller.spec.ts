import { DestroyRef, EnvironmentInjector, createEnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { RecomputePoller } from './recompute-poller';

interface Status { running: boolean; exit_code: number | null; }

describe('RecomputePoller', () => {
  const running: Status = { running: true, exit_code: null };
  const done: Status = { running: false, exit_code: 0 };
  const failedRead = () => throwError(() => new Error('status read failed'));
  let injector: EnvironmentInjector;
  const get = vi.fn();
  const onStatus = vi.fn();
  const onGiveUp = vi.fn();
  const make = (captureCurrent?: () => () => boolean) => new RecomputePoller<Status>(
    { get }, injector.get(DestroyRef), { intervalMs: 1000, maxFailures: 3, captureCurrent, onStatus, onGiveUp },
  );
  const advance = (ms = 1000) => vi.advanceTimersByTimeAsync(ms);

  beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers();
    injector = createEnvironmentInjector([], TestBed.inject(EnvironmentInjector));
  });

  afterEach(() => {
    if (!injector.destroyed) injector.destroy();
    vi.useRealTimers();
  });

  it('counts consecutive failures and stops only after the configured limit', async () => {
    get.mockReturnValueOnce(failedRead()).mockReturnValueOnce(failedRead()).mockReturnValueOnce(of(running))
      .mockReturnValue(failedRead());
    make().start();
    await advance(4000);
    expect(get).toHaveBeenCalledTimes(5);
    expect(onStatus).toHaveBeenCalledExactlyOnceWith(running);
    expect(onGiveUp).not.toHaveBeenCalled();
    await advance(5000);
    expect(onGiveUp).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledTimes(6);
  });

  it('rejects a late result from the previous scope but keeps polling after a cancelled visit', async () => {
    let epoch = 0;
    let navigating = false;
    const first = new Subject<Status>();
    get.mockReturnValueOnce(first).mockReturnValue(of(done));
    make(() => {
      const captured = epoch;
      return () => !navigating && epoch === captured;
    }).start();

    navigating = true; epoch++;
    first.next(done);
    await advance(2000);
    expect(get).toHaveBeenCalledExactlyOnceWith('/scan/recompute_status');
    expect(onStatus).not.toHaveBeenCalled();
    expect(onGiveUp).not.toHaveBeenCalled();

    navigating = false;
    await advance(5000);
    expect(get).toHaveBeenCalledTimes(2);
    expect(onStatus).toHaveBeenCalledExactlyOnceWith(done);
  });

  it('cancels a stopped read and does not let its cancellation disturb a restarted cycle', async () => {
    const old = new Subject<Status>();
    const replacement = new Subject<Status>();
    get.mockReturnValueOnce(old).mockReturnValueOnce(replacement);
    const poller = make();
    poller.start();
    expect(old.observed).toBe(true);

    poller.start();
    expect(old.observed).toBe(false);
    expect(replacement.observed).toBe(true);
    await advance(3000);
    expect(get).toHaveBeenCalledTimes(2);
    expect(onGiveUp).not.toHaveBeenCalled();
    replacement.next(done);
    await advance(3000);
    expect(get).toHaveBeenCalledTimes(2);
    expect(onStatus).toHaveBeenCalledExactlyOnceWith(done);
  });

  it('unsubscribes a pending read on destruction and cannot restart', async () => {
    const pending = new Subject<Status>();
    get.mockReturnValue(pending);
    const poller = make();
    poller.start();
    expect(pending.observed).toBe(true);
    injector.destroy();
    expect(pending.observed).toBe(false);
    poller.start();
    await advance(16_000);
    expect(get).toHaveBeenCalledExactlyOnceWith('/scan/recompute_status');
    expect(onStatus).not.toHaveBeenCalled();
    expect(onGiveUp).not.toHaveBeenCalled();
  });
});
