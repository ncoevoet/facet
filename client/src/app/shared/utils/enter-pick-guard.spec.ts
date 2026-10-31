import { describe, expect, it } from 'vitest';
import { EnterPickGuard } from './enter-pick-guard';

describe('EnterPickGuard', () => {
  const pick = { panelOpen: true, activeOption: {} } as never;

  it('submits when no panel is open', () => {
    const guard = new EnterPickGuard();
    guard.down({ panelOpen: false, activeOption: null } as never);
    expect(guard.up()).toBe(true);
  });

  it('submits when there is no trigger', () => {
    const guard = new EnterPickGuard();
    guard.down(undefined);
    expect(guard.up()).toBe(true);
  });

  it('submits when the panel is open with no highlighted option', () => {
    const guard = new EnterPickGuard();
    guard.down({ panelOpen: true, activeOption: null } as never);
    expect(guard.up()).toBe(true);
  });

  it('does not submit the keyup of an Enter that picked an option, then submits the next', () => {
    const guard = new EnterPickGuard();
    guard.down(pick);
    expect(guard.up()).toBe(false);
    guard.down({ panelOpen: false, activeOption: null } as never);
    expect(guard.up()).toBe(true);
  });
});
