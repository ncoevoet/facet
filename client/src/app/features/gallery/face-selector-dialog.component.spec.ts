import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { FaceSelectorDialogComponent } from './face-selector-dialog.component';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';

describe('FaceSelectorDialogComponent', () => {
  const mockDialogRef = { close: jest.fn() };
  const mockI18n = { t: (key: string) => key };
  let mockApi: { get: jest.Mock };

  const createComponent = () => {
    TestBed.configureTestingModule({
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: { photoPath: '/photos/test.jpg' } },
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
      ],
    });
    return TestBed.runInInjectionContext(() => new FaceSelectorDialogComponent());
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockApi = { get: jest.fn() };
  });

  it('starts in loading state', () => {
    mockApi.get.mockReturnValue(of({ faces: [] }));
    const component = createComponent();
    expect(component.loading()).toBe(true);
  });

  it('sets unassigned faces after successful load', async () => {
    const faces = [
      { id: 1, face_index: 0, person_id: null, person_name: null },
      { id: 2, face_index: 1, person_id: 5, person_name: 'Alice' },
      { id: 3, face_index: 2, person_id: null, person_name: null },
    ];
    mockApi.get.mockReturnValue(of({ faces }));
    const component = createComponent();
    await component.ngOnInit();
    expect(component.loading()).toBe(false);
    expect(component.unassignedFaces()).toHaveLength(2);
    expect(component.unassignedFaces().map(f => f.id)).toEqual([1, 3]);
  });

  it('filters out assigned faces (person_id set)', async () => {
    const faces = [
      { id: 1, face_index: 0, person_id: 3, person_name: 'Bob' },
    ];
    mockApi.get.mockReturnValue(of({ faces }));
    const component = createComponent();
    await component.ngOnInit();
    expect(component.unassignedFaces()).toHaveLength(0);
  });

  it('handles API error gracefully and sets loading to false', async () => {
    mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));
    const component = createComponent();
    await component.ngOnInit();
    expect(component.loading()).toBe(false);
    expect(component.unassignedFaces()).toHaveLength(0);
  });

  it('handles missing faces array in response', async () => {
    mockApi.get.mockReturnValue(of({ faces: null }));
    const component = createComponent();
    await component.ngOnInit();
    expect(component.unassignedFaces()).toHaveLength(0);
  });
});
