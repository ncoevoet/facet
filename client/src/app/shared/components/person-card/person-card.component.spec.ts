import { Component, signal, ChangeDetectionStrategy } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { PersonCardComponent, Person } from './person-card.component';

/* eslint-disable @angular-eslint/component-selector */
@Component({
  selector: 'test-host',
  standalone: true,
  imports: [PersonCardComponent],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `<app-person-card [person]="person()" [isEditing]="isEditing()" [canEdit]="canEdit()" [restoreOnly]="restoreOnly()" [nameOptions]="nameOptions()" />`,
})
class TestHostComponent {
  person = signal<Person>({ id: 1, name: 'Alice', face_count: 5, face_thumbnail: true });
  isEditing = signal(false);
  canEdit = signal(false);
  restoreOnly = signal(false);
  nameOptions = signal([
    { id: 7, name: 'Anna', count: 12 },
    { id: 8, name: 'Peter Salem', count: 1 },
  ]);
}

describe('PersonCardComponent', () => {
  let fixture: ComponentFixture<TestHostComponent>;
  let host: TestHostComponent;
  const mockI18n = { t: vi.fn((key: string) => key), currentLang: vi.fn(() => 'en'), locale: vi.fn(() => 'en'), translations: vi.fn(() => ({})) };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TestHostComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    }).compileComponents();
    fixture = TestBed.createComponent(TestHostComponent);
    host = fixture.componentInstance;
    fixture.detectChanges();
  });

  function getCard(): PersonCardComponent {
    return fixture.debugElement.children[0].componentInstance as PersonCardComponent;
  }

  it('double-clicking the card opens the person photos', () => {
    const emitted: number[] = [];
    getCard().viewPhotos.subscribe((id) => emitted.push(id));
    fixture.nativeElement.querySelector('mat-card').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    expect(emitted).toEqual([1]);
  });

  it('double-clicking inside the name line does not open the photos', () => {
    host.isEditing.set(true);
    host.canEdit.set(true);
    fixture.detectChanges();
    const emitted: number[] = [];
    getCard().viewPhotos.subscribe((id) => emitted.push(id));
    fixture.nativeElement.querySelector('input').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    expect(emitted).toEqual([]);
  });

  it('double-clicking an avatar button does not also open the photos', () => {
    host.isEditing.set(true);
    host.canEdit.set(true);
    fixture.detectChanges();
    const emitted: number[] = [];
    getCard().viewPhotos.subscribe((id) => emitted.push(id));
    const findMore = [...fixture.nativeElement.querySelectorAll('button')]
      .find((b) => (b as HTMLElement).textContent?.includes('person_search')) as HTMLElement;
    findMore.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    expect(emitted).toEqual([]);
  });

  describe('the name line', () => {
    beforeEach(() => {
      host.isEditing.set(true);
      host.canEdit.set(true);
      fixture.detectChanges();
    });

    const input = () => fixture.nativeElement.querySelector('input:not([type="checkbox"])') as HTMLInputElement;

    async function typeName(value: string): Promise<HTMLElement[]> {
      input().focus();
      input().value = value;
      input().dispatchEvent(new Event('input'));
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      return [...document.querySelectorAll('mat-option')] as HTMLElement[];
    }

    it('suggests names with the person face and photo count, filtered as the user types', async () => {
      const options = await typeName('pet');
      expect(options.length).toBe(1);
      expect(options[0].textContent).toContain('Peter Salem');
      expect(options[0].textContent).toContain('persons.name_suggestion_photos');
      expect(options[0].querySelector('img')?.getAttribute('src')).toContain('8');
    });

    it('choosing a suggestion fills the name; Enter then saves it', async () => {
      const emitted: { id: number; name: string }[] = [];
      getCard().editSave.subscribe((v) => emitted.push(v));
      const options = await typeName('an');
      options[0].click();
      fixture.detectChanges();
      expect(input().value).toBe('Anna');
      expect(emitted).toEqual([]);
      input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
      input().dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter' }));
      expect(emitted).toEqual([{ id: 1, name: 'Anna' }]);
    });

    it('hides the selection checkbox while the name line is open, and styles the input focus', () => {
      expect(fixture.nativeElement.querySelector('mat-checkbox')).toBeNull();
      expect(input().classList).toContain('focus:border-[var(--mat-sys-primary)]');
      expect(input().classList).toContain('!outline-none');
    });

    it('centres the save and cancel glyphs in their 28 px buttons', () => {
      const buttons = [...fixture.nativeElement.querySelectorAll('button')] as HTMLElement[];
      const save = buttons.find((b) => b.querySelector('mat-icon')?.textContent?.trim() === 'check') as HTMLElement;
      expect(save.classList).toContain('!p-0');
      expect(save.classList).toContain('justify-center');
    });
  });

  it('should create with required person input', () => {
    const card = getCard();
    expect(card).toBeTruthy();
    expect(card.person().name).toBe('Alice');
    expect(card.person().face_count).toBe(5);
  });

  it('should default isSelected to false', () => {
    expect(getCard().isSelected()).toBe(false);
  });

  it('should default isEditing to false', () => {
    expect(getCard().isEditing()).toBe(false);
  });

  it('should default canEdit to false', () => {
    expect(getCard().canEdit()).toBe(false);
  });

  it('onSave emits editSave with id and name from input', () => {
    host.isEditing.set(true);
    fixture.detectChanges();

    const card = getCard();
    const emitted: { id: number; name: string }[] = [];
    card.editSave.subscribe(v => emitted.push(v));

    // Set the native input value
    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    expect(input).toBeTruthy();
    input.value = 'Bob';

    card.onSave();
    expect(emitted).toEqual([{ id: 1, name: 'Bob' }]);
  });

  it('keeps the rename input usable in a narrow tile by wrapping its buttons', () => {
    host.isEditing.set(true);
    fixture.detectChanges();
    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    expect(input.classList.contains('min-w-24')).toBe(true);
    expect(input.parentElement!.classList.contains('flex-wrap')).toBe(true);
    // The global unlayered *:focus-visible outline beats layered utilities unless they are !important.
    expect(input.classList).toContain('!outline-none');
    expect(input.classList).toContain('focus-visible:!outline-none');
    expect(input.classList).toContain('focus:border-[var(--mat-sys-primary)]');
  });

  it('onSave emits empty string when no input element exists', () => {
    // isEditing is false so no input is rendered
    const card = getCard();
    const emitted: { id: number; name: string }[] = [];
    card.editSave.subscribe(v => emitted.push(v));

    card.onSave();
    expect(emitted).toEqual([{ id: 1, name: '' }]);
  });

  // Click the action button whose mat-icon ligature matches `icon`. This drives
  // the real (click)->emit template wiring rather than calling .emit() directly.
  function clickActionButton(icon: string): void {
    const buttons = Array.from(
      fixture.nativeElement.querySelectorAll('button'),
    ) as HTMLButtonElement[];
    const btn = buttons.find(
      b => b.querySelector('mat-icon')?.textContent?.trim() === icon,
    );
    expect(btn).toBeTruthy();
    btn!.click();
  }

  // Open the card's overflow menu and click the item with `label` (its i18n key,
  // which the mock translates to itself). Items render lazily, only once open.
  function clickMenuItem(label: string): void {
    clickActionButton('more_vert');
    fixture.detectChanges();
    const items = Array.from(document.querySelectorAll('.mat-mdc-menu-panel button[mat-menu-item]')) as HTMLButtonElement[];
    const item = items.find(i => i.textContent!.includes(label));
    expect(item, `menu item ${label}`).toBeTruthy();
    item!.click();
  }

  function menuLabels(): string[] {
    clickActionButton('more_vert');
    fixture.detectChanges();
    return Array.from(document.querySelectorAll('.mat-mdc-menu-panel button[mat-menu-item]'))
      .map(i => `${i.querySelector('mat-icon')!.textContent!.trim()} ${i.querySelector('span')!.textContent!.trim()}`);
  }

  it('emits split output when the split menu item is clicked', () => {
    host.canEdit.set(true);
    fixture.detectChanges();
    const split: number[] = [];
    getCard().split.subscribe(v => split.push(v));
    clickMenuItem('persons.split');
    expect(split).toEqual([1]);
  });

  it('emits rename and find more from the menu', () => {
    host.canEdit.set(true);
    fixture.detectChanges();
    const edit: number[] = [];
    const more: number[] = [];
    getCard().editStart.subscribe(v => edit.push(v));
    getCard().findMore.subscribe(v => more.push(v));
    clickMenuItem('persons.rename');
    expect(edit).toEqual([1]);
    clickMenuItem('persons.find_more');
    expect(more).toEqual([1]);
  });

  it('emits hidden output when the ignore menu item is clicked', () => {
    host.canEdit.set(true);
    fixture.detectChanges();
    const hidden: number[] = [];
    getCard().hidden.subscribe(v => hidden.push(v));
    clickMenuItem('persons.hide');
    expect(hidden).toEqual([1]);
  });

  it('emits deleted output when the delete menu item is clicked', () => {
    host.canEdit.set(true);
    fixture.detectChanges();
    const deleted: number[] = [];
    getCard().deleted.subscribe(v => deleted.push(v));
    clickMenuItem('persons.delete');
    expect(deleted).toEqual([1]);
  });

  it('emits unhidden output when the restore menu item is clicked for a hidden person', () => {
    host.canEdit.set(true);
    host.person.set({ id: 7, name: 'Bob', face_count: 2, face_thumbnail: false, is_hidden: true });
    fixture.detectChanges();
    const unhidden: number[] = [];
    getCard().unhidden.subscribe(v => unhidden.push(v));
    clickMenuItem('persons.unhide');
    expect(unhidden).toEqual([7]);
  });

  it('a click on the menu trigger does not select the card', () => {
    host.canEdit.set(true);
    fixture.detectChanges();
    const selected: number[] = [];
    getCard().selected.subscribe(v => selected.push(v));
    clickActionButton('more_vert');
    expect(selected).toEqual([]);
  });

  it('renders the hidden indicator icon when the person is hidden', () => {
    host.canEdit.set(true);
    host.person.set({ id: 7, name: 'Bob', face_count: 2, face_thumbnail: false, is_hidden: true });
    fixture.detectChanges();

    // The hidden state now shows a visibility_off icon in the name overlay (the
    // unhide action button uses the 'visibility' icon, so this is unambiguous).
    expect(fixture.nativeElement.textContent).toContain('visibility_off');
  });

  it('restoreOnly keeps the same row and offers only restore and delete in the menu', () => {
    host.canEdit.set(true);
    host.person.set({ id: 7, name: 'Bob', face_count: 2, face_thumbnail: false, is_hidden: true });
    host.restoreOnly.set(true);
    fixture.detectChanges();
    const icons = [...fixture.nativeElement.querySelectorAll('mat-card-content button mat-icon')]
      .map((i) => (i as HTMLElement).textContent!.trim());
    expect(icons).toEqual(['photo_library', 'more_vert']);
    expect(menuLabels()).toEqual(['visibility persons.unhide', 'delete persons.delete']);
  });

  it('shows at most three controls in the row and every other action in the menu', () => {
    host.canEdit.set(true);
    fixture.detectChanges();
    const icons = [...fixture.nativeElement.querySelectorAll('mat-card-content button mat-icon')]
      .map((i) => (i as HTMLElement).textContent!.trim());
    expect(icons).toEqual(['photo_library', 'more_vert']);
    expect(fixture.nativeElement.querySelectorAll('mat-card-content mat-checkbox').length).toBe(1);
    expect(menuLabels()).toEqual([
      'edit persons.rename',
      'person_search persons.find_more',
      'call_split persons.split',
      'visibility_off persons.hide',
      'delete persons.delete',
    ]);
  });

  it('the menu trigger is labelled and the card no longer clips its content', () => {
    host.canEdit.set(true);
    fixture.detectChanges();
    const trigger = Array.from(fixture.nativeElement.querySelectorAll('button')).find(
      (b) => (b as HTMLElement).querySelector('mat-icon')?.textContent?.trim() === 'more_vert') as HTMLElement;
    expect(trigger.getAttribute('aria-label')).toBe('nav.more');
    expect(fixture.nativeElement.querySelector('mat-card').className).not.toContain('overflow-hidden');
  });

  it('keystrokes in the avatar action row do not reach the card', () => {
    host.canEdit.set(true);
    host.isEditing.set(true);
    fixture.detectChanges();
    const card = fixture.nativeElement.querySelector('mat-card') as HTMLElement;
    const seen: string[] = [];
    card.addEventListener('keydown', () => seen.push('card'));
    const row = fixture.nativeElement.querySelector('mat-card .absolute.bottom-1\\.5') as HTMLElement;
    row.querySelector('button')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(seen).toEqual([]);
  });
});
