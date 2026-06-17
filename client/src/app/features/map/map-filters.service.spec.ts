import { TestBed } from '@angular/core/testing';
import { MapFiltersService } from './map-filters.service';

describe('MapFiltersService', () => {
  let service: MapFiltersService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [MapFiltersService],
    });
    service = TestBed.inject(MapFiltersService);
  });

  it('should have empty dateFrom by default', () => {
    expect(service.dateFrom()).toBe('');
  });

  it('should have empty dateTo by default', () => {
    expect(service.dateTo()).toBe('');
  });

  it('should update dateFrom signal', () => {
    service.dateFrom.set('2025-01-01');
    expect(service.dateFrom()).toBe('2025-01-01');
  });

  it('should update dateTo signal', () => {
    service.dateTo.set('2025-12-31');
    expect(service.dateTo()).toBe('2025-12-31');
  });

  it('should track dateFrom and dateTo independently', () => {
    service.dateFrom.set('2024-06-01');
    expect(service.dateFrom()).toBe('2024-06-01');
    expect(service.dateTo()).toBe('');

    service.dateTo.set('2024-06-30');
    expect(service.dateFrom()).toBe('2024-06-01');
    expect(service.dateTo()).toBe('2024-06-30');
  });

  it('should clear a date filter back to empty', () => {
    service.dateFrom.set('2025-03-15');
    expect(service.dateFrom()).toBe('2025-03-15');

    service.dateFrom.set('');
    expect(service.dateFrom()).toBe('');
  });
});
