import { TestBed } from '@angular/core/testing';
import { StatsFiltersService } from './stats-filters.service';

describe('StatsFiltersService', () => {
  let service: StatsFiltersService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(StatsFiltersService);
  });

  it('should initialize filterCategory to empty string', () => {
    expect(service.filterCategory()).toBe('');
  });

  it('should initialize dateFrom to empty string', () => {
    expect(service.dateFrom()).toBe('');
  });

  it('should initialize dateTo to empty string', () => {
    expect(service.dateTo()).toBe('');
  });

  it('should update filterCategory', () => {
    service.filterCategory.set('portrait');
    expect(service.filterCategory()).toBe('portrait');
  });

  it('should update dateFrom', () => {
    service.dateFrom.set('2025-01-01');
    expect(service.dateFrom()).toBe('2025-01-01');
  });

  it('should update dateTo', () => {
    service.dateTo.set('2025-12-31');
    expect(service.dateTo()).toBe('2025-12-31');
  });
});
