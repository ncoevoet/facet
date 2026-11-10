import { isPageShortcutBlocked, isTypingContext } from './keyboard';

function eventFrom(el: Partial<HTMLElement> | null): Event {
  return { target: el } as unknown as Event;
}

describe('isTypingContext', () => {
  it('is true for INPUT / TEXTAREA / SELECT', () => {
    expect(isTypingContext(eventFrom({ tagName: 'INPUT' } as HTMLElement))).toBe(true);
    expect(isTypingContext(eventFrom({ tagName: 'TEXTAREA' } as HTMLElement))).toBe(true);
    expect(isTypingContext(eventFrom({ tagName: 'SELECT' } as HTMLElement))).toBe(true);
  });

  it('is true for contenteditable', () => {
    expect(isTypingContext(eventFrom({ tagName: 'DIV', isContentEditable: true } as HTMLElement))).toBe(true);
  });

  it.each(['combobox', 'listbox', 'option', 'menu', 'menubar', 'menuitem', 'menuitemcheckbox', 'menuitemradio'])('recognizes a nested target in an ARIA %s', role => {
    const control = document.createElement('div');
    control.setAttribute('role', role);
    const label = document.createElement('span');
    control.appendChild(label);
    expect(isTypingContext(eventFrom(label))).toBe(true);
  });

  it('is false for a plain element', () => {
    expect(isTypingContext(eventFrom({ tagName: 'DIV', isContentEditable: false } as HTMLElement))).toBe(false);
  });

  it('is false when there is no target', () => {
    expect(isTypingContext(eventFrom(null))).toBe(false);
  });
});

describe('isPageShortcutBlocked', () => {
  function key(init: KeyboardEventInit = {}, target: Element = document.body): KeyboardEvent {
    const event = new KeyboardEvent('keydown', { key: 'b', bubbles: true, ...init });
    target.dispatchEvent(event);
    return event;
  }
  afterEach(() => document.body.replaceChildren());

  it('is false for a plain key on the page', () => {
    expect(isPageShortcutBlocked(key())).toBe(false);
  });

  it('is true in a typing context', () => {
    const input = document.createElement('input');
    document.body.append(input);
    expect(isPageShortcutBlocked(key({}, input))).toBe(true);
  });

  it.each([{ ctrlKey: true }, { metaKey: true }, { altKey: true }])('is true with a modifier held (%o)', init => {
    expect(isPageShortcutBlocked(key(init))).toBe(true);
  });

  it('blocks photo actions while a settings or help popover is open', () => {
    const panel = document.createElement('section');
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    document.body.append(panel);
    expect(isPageShortcutBlocked(key({ key: 'x' }))).toBe(true);
    panel.remove();
    expect(isPageShortcutBlocked(key({ key: 'x' }))).toBe(false);
  });

  it.each(['mat-dialog-container', 'mat-bottom-sheet-container'])('is true while a %s is open', tag => {
    document.body.append(document.createElement(tag));
    expect(isPageShortcutBlocked(key())).toBe(true);
  });
});
