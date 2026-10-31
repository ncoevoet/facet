import type { Mock } from 'vitest';
import { Component, signal } from '@angular/core';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { PersonFilterChipComponent } from './person-filter-chip.component';
import { SameNameMergeDialogComponent } from '../persons/same-name-merge.service';

const OPTIONS = {
  persons: [
    [163, 'Jirjet Salem', 257],
    [144, 'Peter Salem', 298],
    [95, null, 25],
  ],
};

@Component({
  imports: [PersonFilterChipComponent],
  template: `
    @for (id of ids(); track id) {
      <app-person-filter-chip [personId]="id" [canEdit]="canEdit()" (remove)="removed.push(id)" />
    }
  `,
})
class HostComponent {
  readonly ids = signal<number[]>([95]);
  readonly canEdit = signal(true);
  readonly removed: number[] = [];
}

describe('PersonFilterChipComponent', () => {
  let fixture: ComponentFixture<HostComponent>;
  let mockApi: { get: Mock; post: Mock };
  let mockDialog: { open: Mock };
  let mockSnack: { open: Mock };
  let mockStore: {
    reloadPersonOptions: Mock; updateFilters: Mock; reloadPhotos: Mock;
    filters: ReturnType<typeof signal<{ person_id: string }>>;
  };

  async function settle() {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function render(ids: number[] = [95], canEdit = true) {
    fixture = TestBed.createComponent(HostComponent);
    fixture.componentInstance.ids.set(ids);
    fixture.componentInstance.canEdit.set(canEdit);
    await settle();
  }

  /** The chip of ``id``, and a query inside it. */
  function chip(id = 95): HTMLElement {
    return fixture.nativeElement.querySelector(`[data-person-chip][data-person-id="${id}"]`) as HTMLElement;
  }
  function inChip<T extends Element = HTMLElement>(sel: string, id = 95): T | null {
    return chip(id).querySelector(sel) as T | null;
  }

  async function edit(id = 95) {
    inChip<HTMLButtonElement>('[data-person-name-edit]', id)!.click();
    await settle();
  }

  async function type(name: string, id = 95) {
    const input = inChip<HTMLInputElement>('[data-person-name-input]', id)!;
    input.value = name;
    input.dispatchEvent(new Event('input'));
    await settle();
  }

  function menuItems(): string[] {
    return ([...document.querySelectorAll('.mat-mdc-menu-panel [mat-menu-item]')] as HTMLElement[])
      .map((b) => b.textContent!.replace(/\s+/g, ' ').trim());
  }

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of(OPTIONS)), post: vi.fn(() => of({ success: true, name: '', face_count: 25, same_name_persons: [] })) };
    mockSnack = { open: vi.fn() };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(null) })) };
    mockStore = {
      reloadPersonOptions: vi.fn(async () => undefined), updateFilters: vi.fn(async () => undefined),
      reloadPhotos: vi.fn(async () => undefined), filters: signal({ person_id: '95' }),
    };
    TestBed.configureTestingModule({
      imports: [HostComponent],
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: mockSnack },
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
  });

  it('read-only users get only the remove button', async () => {
    await render([95], false);
    expect(inChip('[data-person-remove]')).not.toBeNull();
    expect(inChip('[data-person-name-edit]')).toBeNull();
    expect(inChip('[data-person-more]')).toBeNull();
    inChip<HTMLButtonElement>('[data-person-remove]')!.click();
    expect(fixture.componentInstance.removed).toEqual([95]);
  });

  it('keeps the 32 px avatar, and nudges an unnamed person with a dashed outline', async () => {
    await render([95, 163]);
    expect(inChip('[data-person-chip-avatar]')!.className).toBe('w-8 h-8 rounded-full object-cover shrink-0');
    expect(chip(95).classList).toContain('border-dashed');
    expect(chip(95).textContent).toContain('persons.unnamed');
    expect(chip(163).classList).toContain('border-solid');
    expect(chip(163).textContent).toContain('Jirjet Salem');
  });

  it('the pencil and ⋮ are labelled, focusable buttons before the ×, and remove nothing', async () => {
    await render();
    const buttons = [...chip().querySelectorAll('button')] as HTMLButtonElement[];
    expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual(['persons.rename', 'nav.more', 'gallery.person_chip.remove']);
    for (const b of buttons) expect(b.tabIndex).toBe(0);
    buttons[1].click();
    await settle();
    expect(fixture.componentInstance.removed).toEqual([]);
  });

  it('edit opens the focused name field with the suggestions, styled to show focus', async () => {
    await render([163]);
    await edit(163);
    const input = inChip<HTMLInputElement>('[data-person-name-input]', 163)!;
    expect(document.activeElement).toBe(input);
    expect(input.classList).toContain('!outline-none');
    expect(input.classList).toContain('focus-visible:!outline-none');
    expect(input.classList).toContain('focus:border-[var(--mat-sys-primary)]');
    const options = [...document.querySelectorAll('mat-option')] as HTMLElement[];
    expect(options.map((o) => o.textContent)).toEqual([expect.stringContaining('Peter Salem')]);
    expect(inChip('[data-person-remove]', 163)).toBeNull();
  });

  it('edit then save renames, and the chip comes back', async () => {
    await render();
    await edit();
    await type('Aunt May');
    inChip<HTMLButtonElement>('[data-person-name-save]')!.click();
    await settle();
    expect(mockApi.post).toHaveBeenCalledWith('/persons/95/rename', { name: 'Aunt May' });
    expect(mockStore.reloadPersonOptions).toHaveBeenCalled();
    expect(inChip('[data-person-name-input]')).toBeNull();
    expect(inChip('[data-person-name-edit]')).not.toBeNull();
  });

  it('cancel restores the chip without an API call', async () => {
    await render();
    await edit();
    await type('Aunt May');
    inChip<HTMLButtonElement>('[data-person-name-cancel]')!.click();
    await settle();
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(inChip('[data-person-name-input]')).toBeNull();
    expect(fixture.componentInstance.removed).toEqual([]);
  });

  it('Escape behaves like cancel', async () => {
    await render();
    await edit();
    await type('Aunt May');
    inChip('[data-person-name-input]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(inChip('[data-person-name-input]')).toBeNull();
  });

  it('a merge into another person points the filter at it, keeping the other chips', async () => {
    mockStore.filters.set({ person_id: '95,144' });
    mockApi.post.mockImplementation((url: string) =>
      of(url.endsWith('/rename')
        ? { success: true, name: 'x', face_count: 25, same_name_persons: [{ id: 163, name: 'Jirjet Salem', face_count: 257 }] }
        : { success: true }));
    mockDialog.open.mockReturnValue({ afterClosed: () => of([95, 163]) });
    await render([95, 144]);
    await edit();
    await type('Jirjet Salem');
    inChip<HTMLButtonElement>('[data-person-name-save]')!.click();
    await settle();
    await settle();
    expect(mockDialog.open).toHaveBeenCalledWith(SameNameMergeDialogComponent, expect.anything());
    expect(mockStore.updateFilters).toHaveBeenCalledWith({ person_id: '163,144' });
  });

  it('⋮ opens the person-only menu', async () => {
    await render();
    inChip<HTMLButtonElement>('[data-person-more]')!.click();
    await settle();
    const items = menuItems();
    expect(items.some((t) => t.includes('photo_faces.find_more'))).toBe(true);
    expect(items.some((t) => t.includes('persons.hide'))).toBe(true);
    expect(items.some((t) => t.includes('photo_faces.not_person'))).toBe(false);
  });

  it('several person chips each work on their own', async () => {
    mockStore.filters.set({ person_id: '95,163' });
    await render([95, 163]);
    await edit(163);
    expect(inChip('[data-person-name-input]', 163)).not.toBeNull();
    expect(inChip('[data-person-name-input]', 95)).toBeNull();
    expect(inChip('[data-person-name-edit]', 95)).not.toBeNull();
    await type('Jirjet S', 163);
    inChip<HTMLButtonElement>('[data-person-name-save]', 163)!.click();
    await settle();
    expect(mockApi.post).toHaveBeenCalledWith('/persons/163/rename', { name: 'Jirjet S' });
    expect(mockApi.post).not.toHaveBeenCalledWith('/persons/95/rename', expect.anything());
    inChip<HTMLButtonElement>('[data-person-remove]', 95)!.click();
    expect(fixture.componentInstance.removed).toEqual([95]);
  });

  /** A rename of chip 95 that reports namesakes 163 (``faces`` faces) and 144 (298), merged as the dialog picks. */
  async function renameWithNamesake(picked: number[], faces: number) {
    mockStore.filters.set({ person_id: '95,144' });
    mockApi.post.mockImplementation((url: string) =>
      of(url.endsWith('/rename')
        ? { success: true, name: 'x', face_count: 25, same_name_persons: [{ id: 163, name: 'Jirjet Salem', face_count: faces }, { id: 144, name: 'Jirjet Salem', face_count: 298 }] }
        : { success: true }));
    mockDialog.open.mockReturnValue({ afterClosed: () => of(picked) });
    await render([95, 144]);
    await edit();
    await type('Jirjet Salem');
    inChip<HTMLButtonElement>('[data-person-name-save]')!.click();
    await settle();
    await settle();
  }

  it('a merge that left this person out keeps the filter and reloads the chip', async () => {
    await renameWithNamesake([163, 144], 257);
    expect(mockApi.post).toHaveBeenCalledWith('/persons/merge_batch', { merges: [{ source_id: 163, target_id: 144 }] });
    expect(mockStore.updateFilters).not.toHaveBeenCalled();
    expect(mockApi.get.mock.calls.filter(([, p]) => p?.ids === '95').length).toBeGreaterThan(1);
  });

  it('a merge that keeps this person leaves the filter alone', async () => {
    await renameWithNamesake([95, 163], 3);
    expect(mockApi.post).toHaveBeenCalledWith('/persons/merge_batch', { merges: [{ source_id: 163, target_id: 95 }] });
    expect(mockStore.updateFilters).not.toHaveBeenCalled();
  });

  it('a failed rename shows the error and lets the user save again', async () => {
    mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
    await render();
    await edit();
    await type('Aunt May');
    inChip<HTMLButtonElement>('[data-person-name-save]')!.click();
    await settle();
    expect(mockSnack.open).toHaveBeenCalledWith('gallery.person_chip.error', '', { duration: 3000 });
    expect(inChip<HTMLButtonElement>('[data-person-name-save]')!.disabled).toBe(false);
    expect(mockStore.reloadPersonOptions).not.toHaveBeenCalled();
  });

  it('retyping the current name posts nothing', async () => {
    await render([163]);
    await edit(163);
    await type('jirjet salem', 163);
    inChip<HTMLButtonElement>('[data-person-name-save]', 163)!.click();
    await settle();
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(inChip('[data-person-name-input]', 163)).toBeNull();
  });
});
