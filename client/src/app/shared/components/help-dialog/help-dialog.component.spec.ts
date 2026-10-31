import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA } from '@angular/material/dialog';
import { I18nService } from '../../../core/services/i18n.service';
import { I18N } from '../../../core/i18n/keys';
import { DEFAULT_KEYMAP } from '../../../core/services/keyboard-mapping.service';
import { galleryShortcutSection } from '../../../features/gallery/gallery-shortcuts';
import { HelpDialogComponent } from './help-dialog.component';

describe('HelpDialogComponent', () => {
  /** The stub translates a key to itself, or to `key:count` when given params. */
  function render(data: object): HTMLElement {
    TestBed.configureTestingModule({
      imports: [HelpDialogComponent],
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: data },
        { provide: I18nService, useValue: {
          translations: signal({}),
          t: (key: string, params?: { count?: number }) => params?.count === undefined ? key : `${key}:${params.count}`,
        } },
      ],
    });
    const fixture = TestBed.createComponent(HelpDialogComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('titles the dialog with the Help label so it has an accessible name', () => {
    const title = render({ key: null }).querySelector('h2[mat-dialog-title]');
    // The decorative icon lives inside the title but is aria-hidden, so the
    // accessible name stays the Help label alone; textContent still shows both.
    expect(title?.textContent?.trim()).toContain(I18N.nav.help);
    expect(title?.querySelector('mat-icon')?.getAttribute('aria-hidden')).toBe('true');
  });

  it('falls back to the no-help text when the page set none', () => {
    expect(render({ key: null }).textContent).toContain(I18N.gallery.help_none);
  });

  it('shows the page note with its params under the description', () => {
    const root = render({ key: I18N.culling.help_text, note: { key: I18N.culling.my_taste_learning, params: { count: 12 } } });
    expect(root.querySelector('li')?.textContent?.trim()).toBe(I18N.culling.help_text);
    expect(root.textContent).toContain(`${I18N.culling.my_taste_learning}:12`);
  });

  it('renders the actual Stack mapping or its unassigned status in gallery Help', () => {
    const section = galleryShortcutSection({ ...DEFAULT_KEYMAP, stack: '' });
    const root = render({ key: I18N.gallery.help, shortcutSections: [section] });
    const label = Array.from(root.querySelectorAll('span')).find(node => node.textContent?.trim() === I18N.shortcuts.stack)!;
    expect(label.parentElement!.textContent).toContain(I18N.shortcuts.unassigned);
    expect(label.parentElement!.querySelector('kbd')).toBeNull();
  });

  it('renders the keyboard sections the opener passed', () => {
    const section = galleryShortcutSection(DEFAULT_KEYMAP);
    const root = render({ key: I18N.gallery.help, shortcutSections: [section] });
    expect(root.textContent).toContain(I18N.shortcuts.section_gallery);
    expect(root.querySelectorAll('kbd').length).toBe(section.rows.flatMap(r => r.keys).length);
  });
});
