import { TestBed } from '@angular/core/testing';
import { PersonsFiltersService } from './persons-filters.service';

describe('PersonsFiltersService', () => {
  let service: PersonsFiltersService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [PersonsFiltersService],
    });
    service = TestBed.inject(PersonsFiltersService);
  });

  it('should have count as default sort', () => {
    expect(service.sort()).toBe('count');
  });

  it('should have desc as default sortDirection', () => {
    expect(service.sortDirection()).toBe('desc');
  });

  it('should have empty search by default', () => {
    expect(service.search()).toBe('');
  });

  it('should update sort signal', () => {
    service.sort.set('name');
    expect(service.sort()).toBe('name');
  });

  it('should toggle sortDirection between desc and asc', () => {
    service.sortDirection.set('asc');
    expect(service.sortDirection()).toBe('asc');

    service.sortDirection.set('desc');
    expect(service.sortDirection()).toBe('desc');
  });

  it('should update search signal', () => {
    service.search.set('alice');
    expect(service.search()).toBe('alice');
  });

  it('should clear search back to empty', () => {
    service.search.set('bob');
    expect(service.search()).toBe('bob');

    service.search.set('');
    expect(service.search()).toBe('');
  });

  it('should track sort, sortDirection and search independently', () => {
    service.sort.set('name');
    service.sortDirection.set('asc');
    service.search.set('carol');

    expect(service.sort()).toBe('name');
    expect(service.sortDirection()).toBe('asc');
    expect(service.search()).toBe('carol');
  });
});
