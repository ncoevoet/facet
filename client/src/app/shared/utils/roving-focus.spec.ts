import { rovingFocusKey } from './roving-focus';

describe('rovingFocusKey', () => {
  let items: HTMLButtonElement[];
  const press = (index: number, key: string, vertical = 0, options: KeyboardEventInit = {}) => {
    let move: ReturnType<typeof rovingFocusKey> = null;
    items[index].addEventListener('keydown', event => { move = rovingFocusKey(event, 'button', vertical); }, { once: true });
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...options });
    items[index].dispatchEvent(event);
    return { move, event };
  };
  beforeEach(() => {
    const row = document.createElement('div');
    items = Array.from({ length: 4 }, () => row.appendChild(document.createElement('button')));
    document.body.append(row);
  });
  afterEach(() => items[0].parentElement!.remove());

  it('steps, clamps and jumps, focusing the target and consuming the key', () => {
    const right = press(0, 'ArrowRight');
    expect(right.move).toEqual({ from: 0, to: 1 });
    expect(right.event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(items[1]);
    expect(press(0, 'ArrowLeft').move).toEqual({ from: 0, to: 0 });
    expect(press(1, 'End').move).toEqual({ from: 1, to: 3 });
    expect(press(3, 'Home').move).toEqual({ from: 3, to: 0 });
  });

  it('moves vertically only when given a row size', () => {
    expect(press(0, 'ArrowDown').move).toBeNull();
    expect(press(0, 'ArrowDown', 2).move).toEqual({ from: 0, to: 2 });
    expect(press(3, 'ArrowUp', 2).move).toEqual({ from: 3, to: 1 });
  });

  it('ignores modified, composing and unrelated keys', () => {
    for (const options of [{ ctrlKey: true }, { altKey: true }, { metaKey: true }, { isComposing: true }]) {
      const { move, event } = press(0, 'ArrowRight', 0, options);
      expect(move).toBeNull(); expect(event.defaultPrevented).toBe(false);
    }
    expect(press(0, 'a').move).toBeNull();
  });
});
