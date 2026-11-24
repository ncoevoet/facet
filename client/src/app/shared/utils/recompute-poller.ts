import { DestroyRef } from '@angular/core';
import { firstValueFrom, timeout } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { LatestRequest } from './latest-request';

const STATUS_TIMEOUT_MS = 15_000;

interface PollOptions<Status> {
  intervalMs: number;
  maxFailures: number;
  immediate?: boolean;
  /** Capture a fresh route/session guard before each read, then check it again on reply. */
  captureCurrent?: () => () => boolean;
  onStatus: (status: Status) => void;
  onGiveUp: () => void;
}

interface PollCycle {
  timer: ReturnType<typeof setInterval>;
  inFlight: boolean;
  failures: number;
}

/** Polls job status only. The caller still owns starting and interpreting the server job. */
export class RecomputePoller<Status extends { running: boolean }> {
  private cycle: PollCycle | null = null;
  private readonly requests: LatestRequest;

  constructor(
    private readonly api: Pick<ApiService, 'get'>,
    private readonly destroyRef: DestroyRef,
    private readonly options: PollOptions<Status>,
  ) {
    this.requests = new LatestRequest(destroyRef);
    destroyRef.onDestroy(() => this.stop());
  }

  start(): void {
    this.stop();
    if (this.destroyRef.destroyed) return;
    const cycle: PollCycle = {
      timer: setInterval(() => void this.poll(cycle), this.options.intervalMs),
      inFlight: false,
      failures: 0,
    };
    this.cycle = cycle;
    if (this.options.immediate !== false) void this.poll(cycle);
  }

  stop(): void {
    if (this.cycle === null) return;
    clearInterval(this.cycle.timer);
    this.cycle = null;
    this.requests.cancel();
  }

  private async poll(cycle: PollCycle): Promise<void> {
    if (this.cycle !== cycle || cycle.inFlight || this.destroyRef.destroyed) return;
    const currentScope = this.options.captureCurrent?.();
    if (currentScope && !currentScope()) return;

    cycle.inFlight = true;
    const request = this.requests.begin();
    const current = () => request.isCurrent() && (currentScope?.() ?? true);
    let status: Status;
    let done: boolean;
    try {
      // LatestRequest.bind cancels on stop/restart and on view destruction.
      status = await firstValueFrom(request.bind(this.api.get<Status>('/scan/recompute_status')
        .pipe(timeout({ first: STATUS_TIMEOUT_MS }))));
      done = !status.running;
    } catch {
      if (current() && ++cycle.failures >= this.options.maxFailures) {
        this.stop();
        this.options.onGiveUp();
      }
      return;
    } finally {
      cycle.inFlight = false;
    }
    if (!current()) return;

    cycle.failures = 0;
    if (done) this.stop();
    this.options.onStatus(status);
  }
}
