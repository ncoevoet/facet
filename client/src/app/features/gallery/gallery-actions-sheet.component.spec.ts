import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { MAT_BOTTOM_SHEET_DATA, MatBottomSheetRef } from '@angular/material/bottom-sheet';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { GalleryActionsSheetComponent, GalleryActionsSheetData } from './gallery-actions-sheet.component';

describe('GalleryActionsSheetComponent', () => {
  let dismiss: Mock;

  function render(over: Partial<GalleryActionsSheetData> = {}): HTMLElement {
    dismiss = vi.fn();
    const data: GalleryActionsSheetData = {
      count: 3, isEdition: true, showAlbums: false, albums: [], downloadProfiles: [],
      canCompare: false, trashAvailable: false, ...over,
    };
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        { provide: MAT_BOTTOM_SHEET_DATA, useValue: data },
        { provide: MatBottomSheetRef, useValue: { dismiss } },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: signal({}) } },
      ],
    });
    const fixture = TestBed.createComponent(GalleryActionsSheetComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  const entry = (el: HTMLElement): HTMLButtonElement | undefined =>
    (Array.from(el.querySelectorAll('button')) as HTMLButtonElement[])
      .find(b => b.textContent?.includes(I18N.gallery.selection.edit_tags));

  it('offers Stack only for an explicit bounded selection and discloses folded scope', () => {
    const find = (el: HTMLElement) => Array.from(el.querySelectorAll('button')).find(button => button.textContent?.includes(I18N.stacks.create));
    expect(find(render({ canStack: false, viewScoped: true }))?.disabled).toBe(true);
    const el = render({ canStack: true });
    find(el)!.click(); expect(dismiss).toHaveBeenCalledWith({ kind: 'stack' });
    expect(find(render({ isEdition: false }))).toBeUndefined();
    expect(render({ viewScoped: true }).textContent).toContain(I18N.stacks.folded_scope);
  });

  it('offers the edit-tags entry to an edition user', () => {
    expect(entry(render({ isEdition: true }))).toBeDefined();
  });

  it('hides the edit-tags entry without edition', () => {
    expect(entry(render({ isEdition: false }))).toBeUndefined();
  });

  it('dismisses with the tags action when picked', () => {
    entry(render())!.click();

    expect(dismiss).toHaveBeenCalledWith({ kind: 'tags' });
  });

  for (const [label, decision] of [[I18N.review.keep, 'kept'], [I18N.review.reset, 'undecided']] as const) {
    it(`dismisses with the ${decision} review action after a real click`, () => {
      const button = Array.from(render().querySelectorAll('button'))
        .find(el => el.textContent?.includes(label));
      expect(button).toBeDefined();
      button!.click();
      expect(dismiss.mock.calls).toEqual([[{ kind: 'review', decision }]]);
    });

    it(`does not offer ${decision} review without edition access`, () => {
      const el = render({ isEdition: false });
      expect(Array.from(el.querySelectorAll('button')).some(button => button.textContent?.includes(label))).toBe(false);
      expect(dismiss).not.toHaveBeenCalled();
    });
  }

  it('offers capture date correction only with edition access', () => {
    const find = (el: HTMLElement) => Array.from(el.querySelectorAll('button')).find(b => b.textContent?.includes(I18N.capture_date.title));
    expect(find(render({ isEdition: false }))).toBeUndefined();
    const button = find(render());
    expect(button).toBeDefined();
    button!.click();
    expect(dismiss).toHaveBeenCalledWith({ kind: 'capture-date' });
  });

  it('offers batch location assignment and emits the gps action', () => {
    const button = Array.from(render().querySelectorAll('button')).find(b => b.textContent?.includes(I18N.photo_detail.gps.batch_title));
    expect(button).toBeDefined();
    button!.click();
    expect(dismiss).toHaveBeenCalledWith({ kind: 'gps' });
  });

  /** A button's accessible name: its aria-label, else its text without the icon ligature. */
  const label = (button: HTMLButtonElement): string => button.getAttribute('aria-label')
    ?? [...button.childNodes].filter(node => !(node instanceof Element && node.tagName === 'MAT-ICON'))
      .map(node => node.textContent).join('').trim();
  const actions = (el: HTMLElement) => [...el.querySelectorAll<HTMLButtonElement>('button:not([data-sheet-close])')].map(label);
  const headings = (el: HTMLElement) => [...el.querySelectorAll<HTMLElement>('[role="group"]')].map(group => {
    const heading = group.querySelector('h2');
    expect(heading, 'every section is labelled by its heading').not.toBeNull();
    expect(group.getAttribute('aria-labelledby')).toBe(heading!.id);
    return heading!.textContent!.trim();
  });
  const button = (el: HTMLElement, name: string) =>
    [...el.querySelectorAll<HTMLButtonElement>('button')].find(candidate => label(candidate) === name);
  const reason = (el: HTMLElement, target: HTMLButtonElement) => {
    const id = target.getAttribute('aria-describedby');
    return id ? el.querySelector(`#${id}`)?.textContent?.trim() : undefined;
  };
  const S = I18N.gallery.selection;

  it('groups the edition actions as the desktop Actions menu does, its submenus as labelled sections', () => {
    const el = render({
      showAlbums: true, albums: [{ id: 7, name: 'Trip' } as never], downloadProfiles: ['web'],
      canCompare: true, canSelectAll: true, canStack: true, trashAvailable: true,
    });
    expect(headings(el)).toEqual([
      I18N.gallery.sidebar.tabs.review, I18N.albums.add_photos, S.mark_sequence, S.edit_metadata, S.download,
    ]);
    expect(actions(el)).toEqual([
      S.compare, S.select_all, S.invert,
      I18N.review.keep, S.reject, S.favorite, I18N.review.reset,
      ...[1, 2, 3, 4, 5].map(star => `${S.rate} ${star}`), S.clear_rating,
      'Trip', I18N.albums.create,
      S.mark_panorama, S.mark_hdr_panorama, S.mark_bracket,
      I18N.capture_date.title, I18N.photo_detail.gps.batch_title, S.edit_tags,
      I18N.download.type_original, 'web', I18N.download.type_raw,
      I18N.stacks.create, S.copy_filenames, I18N.export.action, I18N.cull.action, I18N.photo_refresh.title,
      I18N.photo_detail.remove_catalog.action, I18N.cull.delete_action,
    ]);
  });

  it('gives a read-only viewer selection, download and copy only, in the menu order', () => {
    const plain = render({ isEdition: false, canSelectAll: true });
    expect(headings(plain)).toEqual([]);
    expect(actions(plain)).toEqual([S.select_all, S.invert, S.download, S.copy_filenames]);
    button(plain, S.download)!.click();
    expect(dismiss).toHaveBeenCalledWith({ kind: 'download', type: 'original' });
    const profiles = render({ isEdition: false, canSelectAll: false, downloadProfiles: ['web'] });
    expect(headings(profiles)).toEqual([S.download]);
    expect(actions(profiles)).toEqual([S.invert, I18N.download.type_original, 'web', I18N.download.type_raw, S.copy_filenames]);
  });

  it('omits the album section when albums are off and the delete entry without a trash', () => {
    const el = render({ showAlbums: false, trashAvailable: false });
    expect(headings(el)).not.toContain(I18N.albums.add_photos);
    expect(actions(el)).not.toContain(I18N.albums.create);
    expect(actions(el)).not.toContain(I18N.cull.delete_action);
    expect(actions(el)).toContain(I18N.photo_detail.remove_catalog.action);
  });

  it('dismisses with Select all, Remove from catalog and Clear rating', () => {
    const el = render({ canSelectAll: true });
    button(el, S.select_all)!.click();
    button(el, I18N.photo_detail.remove_catalog.action)!.click();
    button(el, S.clear_rating)!.click();
    expect(dismiss.mock.calls).toEqual([[{ kind: 'select-all' }], [{ kind: 'remove-catalog' }], [{ kind: 'rate', rating: 0 }]]);
  });

  it('disables the commands a whole-view selection cannot drive and says why', () => {
    const el = render({ viewScoped: true, canStack: false, trashAvailable: true });
    const expected: [string, string][] = [
      [I18N.stacks.create, I18N.stacks.explicit_only],
      [I18N.photo_refresh.title, S.explicit_required],
      [I18N.photo_detail.remove_catalog.action, S.explicit_required],
      [I18N.cull.delete_action, I18N.cull.delete_disabled_view_scope_tooltip],
    ];
    for (const [name, why] of expected) {
      const target = button(el, name)!;
      expect(target.disabled, name).toBe(true);
      expect(reason(el, target), name).toBe(why);
      target.click();
    }
    expect(dismiss).not.toHaveBeenCalled();
    const enabled = button(render({ canStack: true, trashAvailable: true }), I18N.cull.delete_action)!;
    expect(enabled.disabled).toBe(false);
    expect(enabled.getAttribute('aria-describedby')).toBeNull();
  });

  it('states the refresh limit when the selection is too large', () => {
    const el = render({ count: 101 });
    const refresh = button(el, I18N.photo_refresh.title)!;
    expect(refresh.disabled).toBe(true);
    expect(reason(el, refresh)).toBe(I18N.photo_refresh.limit);
  });

  it('keeps every action at a 44 px touch target', () => {
    const el = render({ showAlbums: true, albums: [{ id: 7, name: 'Trip' } as never], canCompare: true, canSelectAll: true, trashAvailable: true });
    for (const target of el.querySelectorAll<HTMLButtonElement>('button:not([data-sheet-close])')) {
      expect(target.classList.contains('min-h-11'), label(target)).toBe(true);
    }
  });

  it('closes without an action from the header close button', () => {
    const close = render().querySelector<HTMLButtonElement>('[data-sheet-close]');
    expect(close?.getAttribute('aria-label')).toBe(I18N.dialog.close);

    close!.click();

    expect(dismiss).toHaveBeenCalledWith();
  });
});
