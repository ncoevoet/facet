import { Directive, ElementRef, OnDestroy, computed, effect, inject, input, output, signal } from '@angular/core';

/** Fraction of the host's width a horizontal drag must cover to commit. */
const COMMIT_FRACTION = 0.35;
/**
 * Floor under that distance. A host that has not been laid out yet measures 0
 * wide, and 35% of nothing would commit a decision on a tap.
 */
const MIN_COMMIT_PX = 48;
/** Travel before the gesture picks an axis; under it the touch is still a tap. */
const AXIS_SLOP_PX = 10;
/** Tilt at full commit distance — the card leans the way it is heading. */
const MAX_TILT_DEG = 8;
/** How long the fling-out and the spring-back run. Exported so a test can wait it out. */
export const SWIPE_SETTLE_MS = 180;

/**
 * Tinder-style horizontal decide gesture: drag the host right to accept, left
 * to reject.
 *
 * The host itself is what moves — the directive writes `transform` on it inside
 * a `requestAnimationFrame`, never through a signal, so a drag costs one style
 * write per frame instead of a change-detection pass per pointer event. What
 * the template *does* read is `keepProgress` / `rejectProgress`, one signal set
 * in that same frame, so the tint and the badges track the finger without the
 * transform going through Angular at all.
 *
 * Three things it deliberately does not do:
 *
 * - **It never calls `preventDefault`.** Every listener is passive; the axis
 *   contract is declared to the browser with `touch-action: pan-y` instead, so
 *   a vertical drag stays the page's and is never fought for.
 * - **It commits nothing while `enabled` is false.** The caller uses that to
 *   hand the pointer to whoever else wants it — a zoomed image being panned,
 *   a compare grid — rather than both handlers reading the same drag.
 * - **It releases a vertical drag the moment the axis is known.** Past the
 *   slop the gesture is either horizontal (and captured) or somebody else's
 *   (and dropped for the rest of that pointer's life).
 */
@Directive({
  selector: '[appSwipeDecision]',
  exportAs: 'appSwipeDecision',
  host: {
    '[style.touch-action]': 'enabled() ? "pan-y" : null',
  },
})
export class SwipeDecisionDirective implements OnDestroy {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** Whether the gesture is live. False hands every pointer straight through. */
  readonly enabled = input(false, { alias: 'appSwipeDecision' });

  /** Committed past the threshold to the right. */
  readonly swipeKeep = output<void>();
  /** Committed past the threshold to the left. */
  readonly swipeReject = output<void>();

  /** Signed drag progress, -1 (full reject) to 1 (full keep). */
  private readonly progress = signal(0);
  /** 0 → 1 as the drag approaches the keep threshold, for the green side. */
  readonly keepProgress = computed(() => Math.max(0, this.progress()));
  /** 0 → 1 as the drag approaches the reject threshold, for the red side. */
  readonly rejectProgress = computed(() => Math.max(0, -this.progress()));

  private pointerId: number | null = null;
  private startX = 0;
  private startY = 0;
  private dx = 0;
  private horizontal = false;
  private frameHandle = 0;
  private settleTimer: ReturnType<typeof setTimeout> | null = null;
  /**
   * The decision a released gesture already committed to, held only for as long
   * as the card takes to leave. It is flushed, never dropped: the settle window
   * gates the animation, so a second swipe starting inside it used to clear the
   * timeout and with it the first swipe's keep/reject.
   */
  private pendingCommit: boolean | null = null;

  private readonly onPointerDown = (e: PointerEvent): void => this.begin(e);
  private readonly onPointerMove = (e: PointerEvent): void => this.track(e);
  private readonly onPointerUp = (e: PointerEvent): void => this.release(e);
  private readonly onPointerCancel = (e: PointerEvent): void => this.abort(e);

  constructor() {
    const el = this.host.nativeElement;
    el.addEventListener('pointerdown', this.onPointerDown, { passive: true });
    el.addEventListener('pointermove', this.onPointerMove, { passive: true });
    el.addEventListener('pointerup', this.onPointerUp, { passive: true });
    el.addEventListener('pointercancel', this.onPointerCancel, { passive: true });
    // A gesture in flight when the caller switches the mode off (zoom, compare)
    // must not land: the frame it was about to decide is no longer the one on
    // screen the way the finger left it.
    effect(() => {
      if (!this.enabled()) this.cancelGesture();
    });
  }

  ngOnDestroy(): void {
    const el = this.host.nativeElement;
    el.removeEventListener('pointerdown', this.onPointerDown);
    el.removeEventListener('pointermove', this.onPointerMove);
    el.removeEventListener('pointerup', this.onPointerUp);
    el.removeEventListener('pointercancel', this.onPointerCancel);
    this.cancelGesture();
  }

  /** Distance that commits, never below the floor a zero-width host would give. */
  private commitDistance(): number {
    return Math.max(MIN_COMMIT_PX, this.host.nativeElement.getBoundingClientRect().width * COMMIT_FRACTION);
  }

  private begin(e: PointerEvent): void {
    if (!this.enabled() || this.pointerId !== null || !e.isPrimary) return;
    // Whatever the settle window still owes lands here, in order, before this
    // gesture takes the card over.
    this.settleNow();
    this.pointerId = e.pointerId;
    this.startX = e.clientX;
    this.startY = e.clientY;
    this.dx = 0;
    this.horizontal = false;
  }

  private track(e: PointerEvent): void {
    if (this.pointerId !== e.pointerId) return;
    const dx = e.clientX - this.startX;
    const dy = e.clientY - this.startY;
    if (!this.horizontal) {
      if (Math.abs(dx) < AXIS_SLOP_PX && Math.abs(dy) < AXIS_SLOP_PX) return;
      if (Math.abs(dy) >= Math.abs(dx)) {
        // Vertical: not ours. Drop the pointer so the rest of the drag, and the
        // pointerup that ends it, pass through untouched.
        this.pointerId = null;
        return;
      }
      this.horizontal = true;
      this.host.nativeElement.setPointerCapture?.(e.pointerId);
    }
    this.dx = dx;
    this.schedule();
  }

  private release(e: PointerEvent): void {
    if (this.pointerId !== e.pointerId) return;
    const dx = this.dx;
    const wasHorizontal = this.horizontal;
    this.host.nativeElement.releasePointerCapture?.(e.pointerId);
    this.pointerId = null;
    this.horizontal = false;
    if (!wasHorizontal) return;
    if (Math.abs(dx) >= this.commitDistance()) this.fling(dx > 0);
    else this.springBack();
  }

  private abort(e: PointerEvent): void {
    if (this.pointerId !== e.pointerId) return;
    this.cancelGesture();
  }

  private schedule(): void {
    if (this.frameHandle) return;
    this.frameHandle = requestAnimationFrame(() => {
      this.frameHandle = 0;
      const ratio = Math.max(-1, Math.min(1, this.dx / this.commitDistance()));
      const el = this.host.nativeElement;
      el.style.transition = '';
      el.style.transform = `translateX(${this.dx}px) rotate(${(ratio * MAX_TILT_DEG).toFixed(2)}deg)`;
      this.progress.set(ratio);
    });
  }

  /** Throw the card off the side it was heading for, then report the decision. */
  private fling(keep: boolean): void {
    this.cancelFrame();
    const el = this.host.nativeElement;
    const width = el.getBoundingClientRect().width || window.innerWidth;
    const sign = keep ? 1 : -1;
    el.style.transition = `transform ${SWIPE_SETTLE_MS}ms ease-out, opacity ${SWIPE_SETTLE_MS}ms ease-out`;
    el.style.transform = `translateX(${sign * (width + MIN_COMMIT_PX)}px) rotate(${sign * MAX_TILT_DEG}deg)`;
    el.style.opacity = '0';
    // The decision is taken here, at release, and only *reported* once the card
    // is gone: the frame under it swaps to the next photo, and doing that
    // mid-flight would fling the *new* photo off screen.
    this.pendingCommit = keep;
    this.settleTimer = setTimeout(() => {
      this.settleTimer = null;
      this.resetStyles();
      this.progress.set(0);
      this.flushCommit();
    }, SWIPE_SETTLE_MS);
  }

  /** Report the decision the last release committed to, at most once. */
  private flushCommit(): void {
    const keep = this.pendingCommit;
    if (keep === null) return;
    this.pendingCommit = null;
    if (keep) this.swipeKeep.emit();
    else this.swipeReject.emit();
  }

  /** End the settle window early: the card back where a gesture starts from, and
   *  the decision it still owed. */
  private settleNow(): void {
    if (this.settleTimer === null) return;
    this.clearSettle();
    this.resetStyles();
    this.progress.set(0);
    this.flushCommit();
  }

  private springBack(): void {
    this.cancelFrame();
    const el = this.host.nativeElement;
    el.style.transition = `transform ${SWIPE_SETTLE_MS}ms ease-out`;
    el.style.transform = '';
    this.progress.set(0);
    this.settleTimer = setTimeout(() => {
      this.settleTimer = null;
      this.resetStyles();
    }, SWIPE_SETTLE_MS);
  }

  /** Stand down completely. The pending commit is dropped rather than flushed:
   *  this runs when the mode is switched off or the host goes away, where the
   *  frame the decision was about is no longer the one on screen. */
  private cancelGesture(): void {
    this.pointerId = null;
    this.horizontal = false;
    this.dx = 0;
    this.pendingCommit = null;
    this.cancelFrame();
    this.clearSettle();
    this.resetStyles();
    this.progress.set(0);
  }

  private cancelFrame(): void {
    if (this.frameHandle) {
      cancelAnimationFrame(this.frameHandle);
      this.frameHandle = 0;
    }
  }

  private clearSettle(): void {
    if (this.settleTimer) {
      clearTimeout(this.settleTimer);
      this.settleTimer = null;
    }
  }

  private resetStyles(): void {
    const el = this.host.nativeElement;
    el.style.transition = '';
    el.style.transform = '';
    el.style.opacity = '';
  }
}
