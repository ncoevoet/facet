import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal } from '@angular/core';
import { MatDialog, MatDialogState } from '@angular/material/dialog';
import { I18nService } from '../../../core/services/i18n.service';
import { I18N } from '../../../core/i18n/keys';
import { DEFAULT_KEYMAP, KeyboardMappingService, KEYMAP_STORAGE_KEY } from '../../../core/services/keyboard-mapping.service';
import { KeyboardMappingDialogComponent } from './keyboard-mapping-dialog.component';

describe('KeyboardMappingDialogComponent', () => {
  let fixture: ComponentFixture<KeyboardMappingDialogComponent>;

  /** The stub translates a key to itself, so assertions use the I18N constants. */
  function render(): HTMLElement {
    // The builder shares one jsdom window across spec files: never inherit a
    // mapping a previous file left behind.
    localStorage.removeItem(KEYMAP_STORAGE_KEY);
    TestBed.configureTestingModule({
      imports: [KeyboardMappingDialogComponent],
      providers: [
        { provide: I18nService, useValue: {
          translations: signal({}),
          t: (key: string) => key,
        } },
      ],
    });
    fixture = TestBed.createComponent(KeyboardMappingDialogComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  /** One clickable row per remappable action; OK is flat, Reset raised. */
  const actionButtons = (root: HTMLElement): HTMLButtonElement[] =>
    Array.from(root.querySelectorAll<HTMLButtonElement>('button[data-keymap-row]'));

  const press = (key: string, init: KeyboardEventInit = {}): void => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key, ...init }));
    fixture.detectChanges();
  };

  afterEach(() => localStorage.removeItem(KEYMAP_STORAGE_KEY));

  it('lists every remappable action with its current key', () => {
    const root = render();
    const buttons = actionButtons(root);
    expect(buttons.length).toBe(7);
    // Each row reads label + key cap together.
    expect(buttons[0].textContent!.trim().endsWith(DEFAULT_KEYMAP.favourite.toUpperCase())).toBe(true);
    expect(buttons[2].textContent!.trim().endsWith(DEFAULT_KEYMAP.keep.toUpperCase())).toBe(true);
    expect(buttons[3].textContent!.trim().endsWith('/')).toBe(true);
  });

  it('shows Stack unassigned and captures a free binding without replacing the older S action', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    service.keymap.set({ ...DEFAULT_KEYMAP, stack: '', focusSearch: 's' });
    fixture.detectChanges();
    const button = actionButtons(root).find(row => row.querySelector('span')?.textContent?.trim() === I18N.shortcuts.stack)!;
    expect(button.querySelector('kbd')!.textContent!.trim()).toBe(I18N.shortcuts.unassigned);
    expect(button.querySelector('span')!.textContent).toContain(I18N.shortcuts.stack);
    button.click(); press('g');
    expect(button.querySelector('kbd')!.textContent!.trim()).toBe('G');
    expect(service.keymap().focusSearch).toBe('s');
  });

  it('captures a pressed key into the clicked action and persists it', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    fixture.detectChanges();
    expect(actionButtons(root)[0].textContent).toContain(I18N.shortcuts.press_key);
    press('z');
    expect(actionButtons(root)[0].textContent!.trim().endsWith('Z')).toBe(true);
    expect(service.keymap().favourite).toBe('z');
    expect(JSON.parse(localStorage.getItem(KEYMAP_STORAGE_KEY)!).favourite).toBe('z');
  });

  it('stores an uppercase keystroke lowercased', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[1].click();
    press('R');
    expect(service.keymap().reject).toBe('r');
  });

  it('backs out of capture on Escape and keeps the old binding', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    press('Escape');
    expect(actionButtons(root)[0].textContent!.trim().endsWith(DEFAULT_KEYMAP.favourite.toUpperCase())).toBe(true);
    expect(service.keymap().favourite).toBe(DEFAULT_KEYMAP.favourite);
  });

  it('stays armed through keys it cannot use, such as arrows and modifiers', () => {
    const root = render();
    actionButtons(root)[0].click();
    press('ArrowLeft');
    press('c', { ctrlKey: true });
    expect(actionButtons(root)[0].textContent).toContain(I18N.shortcuts.press_key);
    press('g');
    expect(actionButtons(root)[0].textContent!.trim().endsWith('G')).toBe(true);
  });

  it.each(['3', '0', '9', ' ', '?'])('refuses the reserved key %j with an announced message and keeps the old binding', key => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    press(key);
    expect(root.querySelector('[role="status"]')!.textContent).toContain(I18N.shortcuts.key_reserved);
    expect(service.keymap().favourite).toBe(DEFAULT_KEYMAP.favourite);
  });

  it('lets Tab move focus on, cancelling capture without remapping', () => {
    const root = render();
    actionButtons(root)[0].click();
    fixture.detectChanges();
    const tab = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true });
    document.dispatchEvent(tab);
    fixture.detectChanges();
    expect(tab.defaultPrevented).toBe(false);
    expect(actionButtons(root)[0].textContent!.trim().endsWith(DEFAULT_KEYMAP.favourite.toUpperCase())).toBe(true);
  });

  it('names each row by its action and its current key', () => {
    const root = render();
    // The row reads label + key cap together, so its accessible name holds both.
    const name = actionButtons(root)[1].textContent!.trim();
    expect(name).toContain(I18N.shortcuts.reject);
    expect(name.endsWith(DEFAULT_KEYMAP.reject.toUpperCase())).toBe(true);
  });

  it('refuses a key another action already holds and keeps the old binding', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    press('x');
    expect(root.textContent).toContain(I18N.shortcuts.key_in_use);
    expect(service.keymap().favourite).toBe(DEFAULT_KEYMAP.favourite);
    expect(service.keymap().reject).toBe(DEFAULT_KEYMAP.reject);
  });

  it('enforces clashes against the live map, and frees a key when its holder moves', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    // favourite <- q: no default holds q, allowed.
    actionButtons(root)[0].click();
    press('q');
    expect(service.keymap().favourite).toBe('q');
    // reject <- q: favourite now holds q, refused.
    actionButtons(root)[1].click();
    press('q');
    expect(root.textContent).toContain(I18N.shortcuts.key_in_use);
    expect(service.keymap().reject).toBe(DEFAULT_KEYMAP.reject);
    // favourite <- w releases q; swap layout then takes q.
    actionButtons(root)[0].click();
    press('w');
    expect(service.keymap().favourite).toBe('w');
    actionButtons(root)[5].click();
    press('q');
    expect(service.keymap().swapLayout).toBe('q');
  });

  it('reset all restores every default', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    press('z');
    root.querySelector<HTMLButtonElement>('button[mat-button]')!.click();
    fixture.detectChanges();
    expect(service.keymap()).toEqual(DEFAULT_KEYMAP);
    expect(actionButtons(root)[0].textContent!.trim().endsWith(DEFAULT_KEYMAP.favourite.toUpperCase())).toBe(true);
  });

  it('stops listening for keys once closed', () => {
    render();
    const remove = vi.spyOn(document, 'removeEventListener');
    fixture.destroy();
    expect(remove).toHaveBeenCalledWith('keydown', expect.any(Function), true);
    remove.mockRestore();
  });

  describe('inside a real dialog', () => {
    it('backs out of capture on Escape without closing the dialog', () => {
      localStorage.removeItem(KEYMAP_STORAGE_KEY);
      TestBed.configureTestingModule({
        providers: [{ provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } }],
      });
      const ref = TestBed.inject(MatDialog).open(KeyboardMappingDialogComponent);
      const root = document.querySelector<HTMLElement>('app-keyboard-mapping-dialog')!;
      TestBed.tick();
      actionButtons(root)[0].click();
      TestBed.tick();
      // A page shortcut, such as the photo page's Escape-goes-back, listens on document.
      const pageListener = vi.fn();
      document.addEventListener('keydown', pageListener);
      // The overlay closes on Escape from body, keyCode included, exactly as a browser sends it.
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true, cancelable: true }));
      TestBed.tick();
      document.removeEventListener('keydown', pageListener);
      expect(ref.getState()).toBe(MatDialogState.OPEN);
      expect(pageListener).not.toHaveBeenCalled();
      expect(actionButtons(root)[0].textContent!.trim().endsWith(DEFAULT_KEYMAP.favourite.toUpperCase())).toBe(true);
      ref.close();
    });
  });
});
