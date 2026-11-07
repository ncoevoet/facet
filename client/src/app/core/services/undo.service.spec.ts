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
        dismissWithAction: () => { ref.onAction.next(); ref.afterDismissed.next(); },
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
});
