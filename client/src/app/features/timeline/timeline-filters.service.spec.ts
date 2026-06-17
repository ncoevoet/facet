import { TestBed } from '@angular/core/testing';
import { TimelineFiltersService } from './timeline-filters.service';

describe('TimelineFiltersService', () => {
  let service: TimelineFiltersService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [TimelineFiltersService],
    });
    service = TestBed.inject(TimelineFiltersService);
  });

  it('should have empty dateFrom by default', () => {
    expect(service.dateFrom()).toBe('');
  });

  it('should have empty dateTo by default', () => {
    expect(service.dateTo()).toBe('');
  });

  it('should have older as default sortDirection', () => {
    expect(service.sortDirection()).toBe('older');
  });

  it('should update dateFrom signal', () => {
    service.dateFrom.set('2023-01-01');
    expect(service.dateFrom()).toBe('2023-01-01');
  });

  it('should update dateTo signal', () => {
    service.dateTo.set('2023-12-31');
    expect(service.dateTo()).toBe('2023-12-31');
  });

  it('should toggle sortDirection between older and newer', () => {
    service.sortDirection.set('newer');
    expect(service.sortDirection()).toBe('newer');

    service.sortDirection.set('older');
    expect(service.sortDirection()).toBe('older');
  });

  it('should track date range and sortDirection independently', () => {
    service.dateFrom.set('2022-05-01');
    service.dateTo.set('2022-05-31');
    service.sortDirection.set('newer');

    expect(service.dateFrom()).toBe('2022-05-01');
    expect(service.dateTo()).toBe('2022-05-31');
    expect(service.sortDirection()).toBe('newer');
  });

  it('should clear a date filter back to empty', () => {
    service.dateTo.set('2021-08-08');
    expect(service.dateTo()).toBe('2021-08-08');

    service.dateTo.set('');
    expect(service.dateTo()).toBe('');
  });
});
