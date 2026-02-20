import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { PersonSelectorDialogComponent } from './person-selector-dialog.component';
import { I18nService } from '../../core/services/i18n.service';
import type { PersonOption } from './gallery.store';

const makePersons = (): PersonOption[] => [
  { id: 1, name: 'Alice', face_count: 10 },
  { id: 2, name: 'Bob', face_count: 5 },
  { id: 3, name: 'Charlie', face_count: 3 },
];

describe('PersonSelectorDialogComponent', () => {
  let component: PersonSelectorDialogComponent;
  const mockDialogRef = { close: jest.fn() };
  const mockI18n = { t: (key: string) => key };

  const createComponent = (persons: PersonOption[] = makePersons()) => {
    TestBed.configureTestingModule({
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: persons },
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: I18nService, useValue: mockI18n },
      ],
    });
    return TestBed.runInInjectionContext(() => new PersonSelectorDialogComponent());
  };

  beforeEach(() => {
    jest.clearAllMocks();
    component = createComponent();
  });

  it('initializes filtered list with all persons', () => {
    expect(component.filtered()).toHaveLength(3);
    expect(component.filtered()[0].name).toBe('Alice');
  });

  it('filter() narrows list by name (case-insensitive)', () => {
    component.searchQuery = 'ali';
    component.filter();
    expect(component.filtered()).toHaveLength(1);
    expect(component.filtered()[0].name).toBe('Alice');
  });

  it('filter() returns all persons when query is empty', () => {
    component.searchQuery = 'ali';
    component.filter();
    component.searchQuery = '';
    component.filter();
    expect(component.filtered()).toHaveLength(3);
  });

  it('filter() returns empty list when no match', () => {
    component.searchQuery = 'xyz';
    component.filter();
    expect(component.filtered()).toHaveLength(0);
  });

  it('filter() matches partial lowercase names', () => {
    component.searchQuery = 'ob';
    component.filter();
    expect(component.filtered()).toHaveLength(1);
    expect(component.filtered()[0].name).toBe('Bob');
  });

  it('filter() ignores persons with null name when searching', () => {
    const persons: PersonOption[] = [
      { id: 1, name: null, face_count: 5 },
      { id: 2, name: 'Alice', face_count: 3 },
    ];
    TestBed.resetTestingModule();
    const c = createComponent(persons);
    c.searchQuery = 'ali';
    c.filter();
    expect(c.filtered()).toHaveLength(1);
  });
});
