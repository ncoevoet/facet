import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Subject } from 'rxjs';
import { UndoService } from './undo.service';
import { I18nService } from './i18n.service';

interface FakeSnackRef {
  onAction: Subject<void>;
  afterDismissed: Subject<void>;
}

describe('UndoService', () => {
  let service: UndoService;
  let refs: FakeSnackRef[];
  let snackOpen: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    refs = [];
    snackOpen = vi.fn(() => {
      const ref: FakeSnackRef = { onAction: new Subject(), afterDismissed: new Subject() };
      refs.push(ref);
      return {
        onAction: () => ref.onAction.asObservable(),
        afterDismissed: () => ref.afterDismissed.asObservable(),
        // MatSnackBar emits afterDismissed only once its exit animation ends, so a
        // second Ctrl+Z can land while the bar is still on screen; tests fire it by hand.
        dismissWithAction: () => ref.onAction.next(),
      };
    });
    TestBed.configureTestingModule({
      providers: [
        UndoService,
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    service = TestBed.inject(UndoService);
  });

  it('invert command: undo action runs undo()', async () => {
    const undo = vi.fn(() => Promise.resolve());
    service.register({ labelKey: 'x', undo });
    refs[0].onAction.next();
    await Promise.resolve();
    expect(undo).toHaveBeenCalled();
  });

  it('deferred command: commit fires on dismissal timeout', async () => {
    const commit = vi.fn(() => Promise.resolve());
    const undo = vi.fn(() => Promise.resolve());
    service.register({ labelKey: 'x', commit, undo });
    refs[0].afterDismissed.next();
    await Promise.resolve();
    expect(commit).toHaveBeenCalled();
    expect(undo).not.toHaveBeenCalled();
  });

  it('deferred command: undo cancels the commit', async () => {
    const commit = vi.fn(() => Promise.resolve());
    const undo = vi.fn(() => Promise.resolve());
    service.register({ labelKey: 'x', commit, undo });
    refs[0].onAction.next();
    refs[0].afterDismissed.next();
    await Promise.resolve();
    expect(undo).toHaveBeenCalled();
    expect(commit).not.toHaveBeenCalled();
  });

  it('registering a second command commits a pending deferred one first', async () => {
    const firstCommit = vi.fn(() => Promise.resolve());
    service.register({ labelKey: 'a', commit: firstCommit, undo: () => Promise.resolve() });
    service.register({ labelKey: 'b', undo: () => Promise.resolve() });
    await Promise.resolve();
    expect(firstCommit).toHaveBeenCalled();
  });

  it('flushPending commits and clears the pending command', async () => {
    const commit = vi.fn(() => Promise.resolve());
    service.register({ labelKey: 'x', commit, undo: () => Promise.resolve() });
    await service.flushPending();
    expect(commit).toHaveBeenCalledTimes(1);
    // Dismissal after flush must not double-commit
    refs[0].afterDismissed.next();
    await Promise.resolve();
    expect(commit).toHaveBeenCalledTimes(1);
  });

  describe('Ctrl/Cmd+Z', () => {
    const press = (init: KeyboardEventInit, target: EventTarget = document.body): KeyboardEvent => {
      const event = new KeyboardEvent('keydown', { key: 'z', bubbles: true, cancelable: true, ...init });
      target.dispatchEvent(event);
      return event;
    };

    it('presses Undo on the showing snackbar and cancels a deferred commit', async () => {
      const commit = vi.fn(() => Promise.resolve());
      const undo = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'x', commit, undo });
      const event = press({ ctrlKey: true });
      await Promise.resolve();
      expect(event.defaultPrevented).toBe(true);
      expect(undo).toHaveBeenCalledTimes(1);
      expect(commit).not.toHaveBeenCalled();
    });

    it('accepts Cmd+Z and a Caps-Lock Z', async () => {
      const undo = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'x', undo });
      press({ key: 'Z', metaKey: true });
      await Promise.resolve();
      expect(undo).toHaveBeenCalledTimes(1);
    });

    it('does nothing, and leaves the key alone, once the snackbar is gone', async () => {
      const undo = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'x', undo });
      refs[0].afterDismissed.next();
      const event = press({ ctrlKey: true });
      await Promise.resolve();
      expect(undo).not.toHaveBeenCalled();
      expect(event.defaultPrevented).toBe(false);
    });

    it('undoes only the newest command, once', async () => {
      const first = vi.fn(() => Promise.resolve());
      const second = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'a', undo: first });
      refs[0].afterDismissed.next(); // MatSnackBar dismisses the old bar when a new one opens
      service.register({ labelKey: 'b', undo: second });
      press({ ctrlKey: true });
      press({ ctrlKey: true });
      await Promise.resolve();
      expect(first).not.toHaveBeenCalled();
      expect(second).toHaveBeenCalledTimes(1);
    });

    it.each([
      ['Ctrl+Shift+Z (redo, a later PR)', { ctrlKey: true, shiftKey: true }],
      ['Ctrl+Alt+Z (AltGr layouts)', { ctrlKey: true, altKey: true }],
      ['Ctrl+Cmd+Z', { ctrlKey: true, metaKey: true }],
      ['a bare Z (darkroom zoom)', {}],
      ['auto-repeat', { ctrlKey: true, repeat: true }],
      ['an IME composition', { ctrlKey: true, isComposing: true }],
    ])('ignores %s', async (_name, init) => {
      const undo = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'x', undo });
      const event = press(init);
      await Promise.resolve();
      expect(undo).not.toHaveBeenCalled();
      expect(event.defaultPrevented).toBe(false);
    });

    it('leaves Ctrl+Z to a text field', async () => {
      const undo = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'x', undo });
      const input = document.body.appendChild(document.createElement('input'));
      const event = press({ ctrlKey: true }, input);
      input.remove();
      await Promise.resolve();
      expect(undo).not.toHaveBeenCalled();
      expect(event.defaultPrevented).toBe(false);
    });

    it.each(['mat-dialog-container', 'mat-bottom-sheet-container'])('leaves Ctrl+Z to an open %s', async tag => {
      const undo = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'x', undo });
      const host = document.body.appendChild(document.createElement(tag));
      const event = press({ ctrlKey: true });
      host.remove();
      await Promise.resolve();
      expect(undo).not.toHaveBeenCalled();
      expect(event.defaultPrevented).toBe(false);
    });

    it('presses Undo while the culling darkroom is open, but not under a dialog opened over it', async () => {
      const undo = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'x', undo });
      const darkroom = document.body.appendChild(document.createElement('div'));
      darkroom.setAttribute('role', 'dialog');
      darkroom.setAttribute('aria-modal', 'true');
      darkroom.setAttribute('data-undo-surface', '');
      const dialog = darkroom.appendChild(document.createElement('div'));
      dialog.setAttribute('role', 'dialog');
      dialog.setAttribute('aria-modal', 'true');
      press({ ctrlKey: true }, dialog);
      await Promise.resolve();
      expect(undo).not.toHaveBeenCalled();
      dialog.remove();
      press({ ctrlKey: true }, darkroom);
      darkroom.remove();
      await Promise.resolve();
      expect(undo).toHaveBeenCalledTimes(1);
    });

    it('reaches the service even when the page stops the key from bubbling', async () => {
      const undo = vi.fn(() => Promise.resolve());
      service.register({ labelKey: 'x', undo });
      const shield = document.body.appendChild(document.createElement('div'));
      shield.addEventListener('keydown', e => e.stopPropagation());
      press({ ctrlKey: true }, shield);
      shield.remove();
      await Promise.resolve();
      expect(undo).toHaveBeenCalledTimes(1);
    });
  });

  it('shows confirmation snackbar after successful undo', async () => {
    service.register({ labelKey: 'x', undo: () => Promise.resolve() });
    refs[0].onAction.next();
    await Promise.resolve();
    await Promise.resolve();
    expect(snackOpen).toHaveBeenCalledWith('undo.restored', '', expect.anything());
  });

  it('preempting a pending command surfaces its failed commit', async () => {
    const failing = vi.fn(() => Promise.reject(new Error('boom')));
    const undo = vi.fn(() => Promise.resolve());
    // First command defers its commit: the bar is still on screen (its 7s
    // window has not closed), so the commit is pending, not yet fired.
    service.register({ labelKey: 'x', undo, commit: failing });
    await Promise.resolve();
    expect(failing).not.toHaveBeenCalled();
    // A second registration preempts the still-showing bar: the pending
    // commit runs now and fails visibly, once the new bar has closed.
    service.register({ labelKey: 'y', undo });
    await Promise.resolve();
    await Promise.resolve();
    expect(failing).toHaveBeenCalled();
    refs[1].afterDismissed.next();
    expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', { duration: 3000 });
  });

  it('a preempted commit\'s failure waits for the new Undo bar instead of replacing it', async () => {
    // MatSnackBar keeps one bar at a time: opening a bar dismisses the one on
    // screen, whose afterDismissed fires once its exit animation ends.
    snackOpen.mockImplementation(() => {
      const previous = refs.at(-1);
      const ref: FakeSnackRef = { onAction: new Subject(), afterDismissed: new Subject() };
      refs.push(ref);
      if (previous) queueMicrotask(() => previous.afterDismissed.next());
      return {
        onAction: () => ref.onAction.asObservable(),
        afterDismissed: () => ref.afterDismissed.asObservable(),
        dismissWithAction: () => ref.onAction.next(),
      };
    });
    const failing = vi.fn(() => Promise.reject(new Error('boom')));
    const second = vi.fn(() => Promise.resolve());
    service.register({ labelKey: 'x', undo: vi.fn(() => Promise.resolve()), commit: failing });
    service.register({ labelKey: 'y', undo: vi.fn(() => Promise.resolve()), commit: second });
    for (let i = 0; i < 5; i++) await Promise.resolve();
    expect(failing).toHaveBeenCalled();
    // The second command's bar is still the live one: its deferred commit has
    // not been forced, and the error has not been opened over it.
    expect(refs).toHaveLength(2);
    expect(second).not.toHaveBeenCalled();
    expect(snackOpen).not.toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
    // Once that bar closes on its own, its commit runs and the error shows.
    refs[1].afterDismissed.next();
    await Promise.resolve();
    expect(second).toHaveBeenCalled();
    expect(snackOpen).toHaveBeenCalledWith('errors.action_failed', '', { duration: 3000 });
  });

  it('the pagehide flush stays silent on failure', async () => {
    const failing = vi.fn(() => Promise.reject(new Error('boom')));
    service.register({ labelKey: 'x', undo: vi.fn(() => Promise.resolve()), commit: failing });
    const openCalls = snackOpen.mock.calls.length;
    await service.flushPending();
    expect(failing).toHaveBeenCalledTimes(1);
    expect(snackOpen.mock.calls.length).toBe(openCalls);
    expect(snackOpen).not.toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
    refs[0].afterDismissed.next();
    await Promise.resolve();
    expect(failing).toHaveBeenCalledTimes(1);
    expect(snackOpen.mock.calls.length).toBe(openCalls);
    expect(snackOpen).not.toHaveBeenCalledWith('errors.action_failed', '', expect.anything());
  });
});
