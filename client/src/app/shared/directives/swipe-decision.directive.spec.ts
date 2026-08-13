import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SwipeDecisionDirective, SWIPE_SETTLE_MS } from './swipe-decision.directive';

/**
 * The directive on its own, driven by real pointer events.
 *
 * What the component-level suite cannot show is the seam between the two things
 * the release does: the decision, which is state, and the fling-out, which is
 * animation. They used to share one timeout, so anything that ended the
 * animation early — a second swipe, most of all — ended the decision with it.
 */
@Component({
  selector: 'app-swipe-host',
  imports: [SwipeDecisionDirective],
  template: `
    <div [appSwipeDecision]="enabled()"
         (swipeKeep)="decisions.push('keep')"
         (swipeReject)="decisions.push('reject')"></div>
  `,
})
class SwipeHostComponent {
  readonly enabled = signal(true);
  readonly decisions: string[] = [];
}

describe('SwipeDecisionDirective', () => {
  let fixture: ComponentFixture<SwipeHostComponent>;
  let host: SwipeHostComponent;
  let surface: HTMLElement;

  /** jsdom measures every element at 0 wide, so the floor is what commits. */
  const OVER = 200;
  /** Past the 10px axis slop, short of the 48px floor — springs back. */
  const UNDER = 20;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [SwipeHostComponent] });
    fixture = TestBed.createComponent(SwipeHostComponent);
    host = fixture.componentInstance;
    fixture.detectChanges();
    surface = fixture.nativeElement.querySelector('div');
  });

  afterEach(() => fixture.destroy());

  let pointerId = 0;

  /** Drag by dx in two steps and lift the finger, as one whole gesture. */
  const swipe = (dx: number, dy = 0): void => {
    const id = ++pointerId;
    const send = (type: string, x: number, y: number) => surface.dispatchEvent(
      new PointerEvent(type, { pointerId: id, isPrimary: true, clientX: x, clientY: y, bubbles: true }),
    );
    send('pointerdown', 0, 0);
    send('pointermove', dx / 2, dy / 2);
    send('pointermove', dx, dy);
    send('pointerup', dx, dy);
  };

  const settle = () => new Promise(resolve => setTimeout(resolve, SWIPE_SETTLE_MS + 20));

  it('reports a committed swipe once the card has flown out, not before', async () => {
    swipe(OVER);
    expect(host.decisions).toEqual([]);

    await settle();

    expect(host.decisions).toEqual(['keep']);
  });

  it('reports nothing for a drag that springs back', async () => {
    swipe(UNDER);
    await settle();

    expect(host.decisions).toEqual([]);
  });

  // The regression: the settle window gates the animation alone. A thumb going
  // through a burst flicks faster than 180ms, and every one of those decisions
  // has to be recorded — the second gesture used to clear the first one's
  // timeout, and with it the keep or reject it had already committed to.
  it('lands both decisions when a second swipe starts inside the settle window', async () => {
    swipe(OVER);
    swipe(-OVER);

    await settle();

    expect(host.decisions).toEqual(['keep', 'reject']);
  });

  it('flushes the previous decision as the next gesture starts, before its own', () => {
    swipe(OVER);
    expect(host.decisions).toEqual([]);

    surface.dispatchEvent(new PointerEvent('pointerdown', { pointerId: 99, isPrimary: true, clientX: 0, clientY: 0, bubbles: true }));

    expect(host.decisions).toEqual(['keep']);
  });

  it('keeps three rapid swipes in the order they were made', async () => {
    swipe(OVER);
    swipe(-OVER);
    swipe(OVER);

    await settle();

    expect(host.decisions).toEqual(['keep', 'reject', 'keep']);
  });

  // A tap inside the window decides nothing of its own, but must still let the
  // swipe before it land — and put the card, flung off screen, back.
  it('a tap inside the settle window lands the previous decision and restores the card', async () => {
    swipe(OVER);
    swipe(0);

    await settle();

    expect(host.decisions).toEqual(['keep']);
    expect(surface.style.transform).toBe('');
    expect(surface.style.opacity).toBe('');
  });

  // Standing down is the one case that drops it: the frame the decision was
  // about is no longer the one the gesture was made on.
  it('drops a pending decision when the gesture mode is switched off', async () => {
    swipe(OVER);
    host.enabled.set(false);
    fixture.detectChanges();

    await settle();

    expect(host.decisions).toEqual([]);
  });

  it('reports nothing after the host is destroyed mid-flight', async () => {
    swipe(OVER);
    fixture.destroy();

    await settle();

    expect(host.decisions).toEqual([]);
  });
});
