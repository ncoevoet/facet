import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { CompareFiltersService } from './compare-filters.service';
import { ComparisonComponent } from './comparison.component';

describe('ComparisonComponent', () => {
  let component: ComparisonComponent;
  let mockApi: { get: jest.Mock; post: jest.Mock; delete: jest.Mock };
  let mockSnackBar: { open: jest.Mock };
  let mockI18n: { t: jest.Mock };
  let mockAuth: { isEdition: jest.Mock };
  let mockStore: { types: ReturnType<typeof signal<{ id: string; count: number }[]>>; loadTypeCounts: jest.Mock };
  let compareFilters: { selectedCategory: ReturnType<typeof signal<string>> };

  beforeEach(() => {
    mockApi = {
      get: jest.fn(() => of({})),
      post: jest.fn(() => of({})),
      delete: jest.fn(() => of({})),
    };
    mockSnackBar = { open: jest.fn() };
    mockI18n = { t: jest.fn((key: string) => key) };
    mockAuth = { isEdition: jest.fn(() => true) };
    mockStore = {
      types: signal([]),
      loadTypeCounts: jest.fn(() => Promise.resolve()),
    };
    compareFilters = { selectedCategory: signal('') };

    TestBed.configureTestingModule({
      providers: [
        ComparisonComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
        { provide: AuthService, useValue: mockAuth },
        { provide: GalleryStore, useValue: mockStore },
        { provide: CompareFiltersService, useValue: compareFilters },
      ],
    });
    component = TestBed.inject(ComparisonComponent);
  });

  describe('loadCategories', () => {
    it('should call store.loadTypeCounts when types are empty', async () => {
      mockStore.types.set([]);
      await component.loadCategories();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });

    it('should not call loadTypeCounts when types are already populated', async () => {
      mockStore.types.set([{ id: 'portrait', count: 10 }]);
      mockStore.loadTypeCounts.mockClear();
      await component.loadCategories();
      expect(mockStore.loadTypeCounts).not.toHaveBeenCalled();
    });

    it('should set selectedCategory to first type when none selected', async () => {
      mockStore.types.set([{ id: 'portrait', count: 10 }, { id: 'landscape', count: 5 }]);
      compareFilters.selectedCategory.set('');
      await component.loadCategories();
      expect(compareFilters.selectedCategory()).toBe('portrait');
    });

    it('should not overwrite an already-selected category', async () => {
      mockStore.types.set([{ id: 'portrait', count: 10 }, { id: 'landscape', count: 5 }]);
      compareFilters.selectedCategory.set('landscape');
      await component.loadCategories();
      expect(compareFilters.selectedCategory()).toBe('landscape');
    });

    it('should not set category when types are empty', async () => {
      mockStore.types.set([]);
      compareFilters.selectedCategory.set('');
      await component.loadCategories();
      expect(compareFilters.selectedCategory()).toBe('');
    });
  });

  describe('constructor', () => {
    it('should call loadCategories on construction, triggering store.loadTypeCounts when types are empty', () => {
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });
  });
});
