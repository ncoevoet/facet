import { closeDetailsOnEscape, closeOverlayDirectives } from './overlays';

describe('closeOverlayDirectives', () => {
  it('hides tooltips immediately, closes menus and closes selects', () => {
    const tooltip = { hide: vi.fn() };
    const menu = { closeMenu: vi.fn() };
    const select = { close: vi.fn() };
    closeOverlayDirectives([tooltip], [menu], [select]);
    expect(tooltip.hide).toHaveBeenCalledWith(0);
    expect(menu.closeMenu).toHaveBeenCalledTimes(1);
    expect(select.close).toHaveBeenCalledTimes(1);
  });

  it('accepts tooltips alone', () => {
    const tooltip = { hide: vi.fn() };
    closeOverlayDirectives([tooltip]);
    expect(tooltip.hide).toHaveBeenCalledWith(0);
  });
});


describe('closeDetailsOnEscape', () => {
  it('closes only an open disclosure and returns focus without leaking Escape', () => {
    const details = document.createElement('details');
    details.innerHTML = '<summary>Tools</summary>';
    document.body.appendChild(details);
    const summary = details.querySelector('summary')!;
    const escaped = vi.fn(); details.parentElement!.addEventListener('keydown', escaped);
    try {
      summary.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      expect(escaped).toHaveBeenCalledOnce();
      const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
      details.open = true;
      details.addEventListener('keydown', event => closeDetailsOnEscape(event, details, summary));
      summary.dispatchEvent(event);
      expect(details.open).toBe(false); expect(document.activeElement).toBe(summary);
      expect(event.defaultPrevented).toBe(true); expect(escaped).toHaveBeenCalledOnce();
      const closed = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
      summary.dispatchEvent(closed);
      expect(closed.defaultPrevented).toBe(false); expect(escaped).toHaveBeenCalledTimes(2);
    } finally { details.parentElement!.removeEventListener('keydown', escaped); details.remove(); }
  });
});
