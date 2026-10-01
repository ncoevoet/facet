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
});
