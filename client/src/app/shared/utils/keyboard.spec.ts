import { isTypingContext } from './keyboard';

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

  it('is false for a plain element', () => {
    expect(isTypingContext(eventFrom({ tagName: 'DIV', isContentEditable: false } as HTMLElement))).toBe(false);
  });

  it('is false when there is no target', () => {
    expect(isTypingContext(eventFrom(null))).toBe(false);
  });
});
