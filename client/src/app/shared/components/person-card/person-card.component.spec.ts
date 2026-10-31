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

  it('emits split output when the split button is clicked', () => {
    host.canEdit.set(true);
    fixture.detectChanges();

    const card = getCard();
    const split: number[] = [];
    card.split.subscribe(v => split.push(v));

    clickActionButton('call_split');
    expect(split).toEqual([1]);
  });

  it('emits hidden output when the hide button is clicked', () => {
    host.canEdit.set(true);
    fixture.detectChanges();

    const card = getCard();
    const hidden: number[] = [];
    card.hidden.subscribe(v => hidden.push(v));

    clickActionButton('visibility_off');
    expect(hidden).toEqual([1]);
  });

  it('emits unhidden output when the unhide button is clicked for a hidden person', () => {
    host.canEdit.set(true);
    host.person.set({ id: 7, name: 'Bob', face_count: 2, face_thumbnail: false, is_hidden: true });
    fixture.detectChanges();

    const card = getCard();
    const unhidden: number[] = [];
    card.unhidden.subscribe(v => unhidden.push(v));

    clickActionButton('visibility');
    expect(unhidden).toEqual([7]);
  });

  it('renders the hidden indicator icon when the person is hidden', () => {
    host.canEdit.set(true);
    host.person.set({ id: 7, name: 'Bob', face_count: 2, face_thumbnail: false, is_hidden: true });
    fixture.detectChanges();

    // The hidden state now shows a visibility_off icon in the name overlay (the
    // unhide action button uses the 'visibility' icon, so this is unambiguous).
    expect(fixture.nativeElement.textContent).toContain('visibility_off');
  });

  it('restoreOnly keeps view photos, restore and delete, and drops rename, split and find more', () => {
    host.canEdit.set(true);
    host.person.set({ id: 7, name: 'Bob', face_count: 2, face_thumbnail: false, is_hidden: true });
    host.restoreOnly.set(true);
    fixture.detectChanges();
    const icons = [...fixture.nativeElement.querySelectorAll('mat-card-content button mat-icon')]
      .map((i) => (i as HTMLElement).textContent!.trim());
    expect(icons).toEqual(['photo_library', 'visibility', 'delete']);
  });

  it('shows every action by default', () => {
    host.canEdit.set(true);
    fixture.detectChanges();
    const icons = [...fixture.nativeElement.querySelectorAll('mat-card-content button mat-icon')]
      .map((i) => (i as HTMLElement).textContent!.trim());
    expect(icons).toEqual(['edit', 'photo_library', 'call_split', 'person_search', 'visibility_off', 'delete']);
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
