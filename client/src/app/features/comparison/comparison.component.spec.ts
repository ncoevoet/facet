import type { Mock } from 'vitest';
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
import { PageContextService } from '../../core/agent/page-context.service';

describe('ComparisonComponent', () => {
   
  let component: any;
  let mockApi: { get: Mock; post: Mock; delete: Mock };
  let mockSnackBar: { open: Mock };
  let mockI18n: { t: Mock };
  let mockAuth: { isEdition: Mock };
  let mockStore: { types: ReturnType<typeof signal<{ id: string; count: number }[]>>; loadTypeCounts: Mock };
  let compareFilters: { selectedCategory: ReturnType<typeof signal<string>>; strategy: ReturnType<typeof signal<string>>; activeTab: ReturnType<typeof signal<number>> };

  beforeEach(() => {
    mockApi = {
      get: vi.fn(() => of({})),
      post: vi.fn(() => of({})),
      delete: vi.fn(() => of({})),
    };
    mockSnackBar = { open: vi.fn() };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockAuth = { isEdition: vi.fn(() => true) };
    mockStore = {
      types: signal([]),
      loadTypeCounts: vi.fn(() => Promise.resolve()),
    };
    compareFilters = { selectedCategory: signal(''), strategy: signal('uncertainty'), activeTab: signal(0) };

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

  describe('page context', () => {
    it('registers the compare page, with no tab until a category is chosen', () => {
      const context = TestBed.inject(PageContextService);
      expect(context.snapshot()).toEqual({
        id: 'compare', tab: null, category: '', strategy: 'uncertainty', pair_a: null, pair_b: null, pair_loading: false,
      });
      compareFilters.selectedCategory.set('portrait');
      compareFilters.activeTab.set(1);
      expect(context.snapshot()).toMatchObject({ tab: 'ab', category: 'portrait' });
    });
  });

  describe('page context pair and tab names', () => {
    const mountAbTab = (): void => {
      Object.defineProperty(component, 'abTab', {
        value: () => ({ pairA: () => '/a.jpg', pairB: () => '/b.jpg', pairLoading: () => true }),
      });
      compareFilters.selectedCategory.set('portrait');
    };

    it('reports the pair only while the A/B tab is the active one', () => {
      const context = TestBed.inject(PageContextService);
      mountAbTab();
      compareFilters.activeTab.set(0);
      expect(context.snapshot()).toMatchObject({ tab: 'snapshots', pair_a: null, pair_b: null, pair_loading: false });
      compareFilters.activeTab.set(1);
      expect(context.snapshot()).toMatchObject({ tab: 'ab', pair_a: '/a.jpg', pair_b: '/b.jpg', pair_loading: true });
    });

    it.each([[2, 'suggestions'], [3, 'weights'], [4, 'context'], [5, 'panorama']])('names tab %i %s', (index, name) => {
      compareFilters.selectedCategory.set('portrait');
      compareFilters.activeTab.set(index);
      expect(TestBed.inject(PageContextService).snapshot()).toMatchObject({ tab: name });
    });
  });

  describe('leaving the page', () => {
    it('resets the strategy to the server-configured default (empty) the root service kept from this visit', () => {
      compareFilters.strategy.set('boundary');
      TestBed.resetTestingModule();
      expect(compareFilters.strategy()).toBe('');
    });
  });

  describe('category pick', () => {
    const types = [{ id: 'portrait', count: 10 }, { id: 'landscape', count: 5 }];

    it('asks the store for types on construction when it has none', () => {
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });

    it('does not ask again when types are already loaded', () => {
      TestBed.resetTestingModule();
      mockStore.types.set(types);
      mockStore.loadTypeCounts.mockClear();
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
      TestBed.inject(ComparisonComponent);
      TestBed.tick();
      expect(mockStore.loadTypeCounts).not.toHaveBeenCalled();
      expect(compareFilters.selectedCategory()).toBe('portrait');
    });

    it('picks the first type when the list arrives after construction', () => {
      TestBed.tick();
      expect(compareFilters.selectedCategory()).toBe('');
      mockStore.types.set(types);
      TestBed.tick();
      expect(compareFilters.selectedCategory()).toBe('portrait');
    });

    it('keeps a category the user already chose', () => {
      compareFilters.selectedCategory.set('landscape');
      mockStore.types.set(types);
      TestBed.tick();
      expect(compareFilters.selectedCategory()).toBe('landscape');
    });
  });
});
