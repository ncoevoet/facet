import { TestBed } from '@angular/core/testing';
import { CompareFiltersService } from './compare-filters.service';

describe('CompareFiltersService', () => {
  let service: CompareFiltersService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [CompareFiltersService],
    });
    service = TestBed.inject(CompareFiltersService);
  });

  it('should have empty selectedCategory by default', () => {
    expect(service.selectedCategory()).toBe('');
  });

  it('should update selectedCategory signal', () => {
    service.selectedCategory.set('portrait');
    expect(service.selectedCategory()).toBe('portrait');
  });

  it('should overwrite a previously selected category', () => {
    service.selectedCategory.set('landscape');
    expect(service.selectedCategory()).toBe('landscape');

    service.selectedCategory.set('street');
    expect(service.selectedCategory()).toBe('street');
  });

  it('should reset selectedCategory back to empty', () => {
    service.selectedCategory.set('macro');
    expect(service.selectedCategory()).toBe('macro');

    service.selectedCategory.set('');
    expect(service.selectedCategory()).toBe('');
  });
});
