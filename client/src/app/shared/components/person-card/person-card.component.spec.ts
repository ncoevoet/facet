import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { PersonCardComponent, Person } from './person-card.component';

@Component({
  selector: 'test-host',
  standalone: true,
  imports: [PersonCardComponent],
  template: `<app-person-card [person]="person()" [isEditing]="isEditing()" />`,
})
class TestHostComponent {
  person = signal<Person>({ id: 1, name: 'Alice', face_count: 5, face_thumbnail: true });
  isEditing = signal(false);
}

describe('PersonCardComponent', () => {
  let fixture: ComponentFixture<TestHostComponent>;
  let host: TestHostComponent;
  const mockI18n = { t: jest.fn((key: string) => key), currentLang: jest.fn(() => 'en') };

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

  it('onSave emits empty string when no input element exists', () => {
    // isEditing is false so no input is rendered
    const card = getCard();
    const emitted: { id: number; name: string }[] = [];
    card.editSave.subscribe(v => emitted.push(v));

    card.onSave();
    expect(emitted).toEqual([{ id: 1, name: '' }]);
  });
});
