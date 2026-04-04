import { TestBed } from '@angular/core/testing';
import { CapsuleFiltersService } from './capsule-filters.service';

describe('CapsuleFiltersService', () => {
  let service: CapsuleFiltersService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [CapsuleFiltersService],
    });
    service = TestBed.inject(CapsuleFiltersService);
  });

  it('should have empty dateFrom by default', () => {
    expect(service.dateFrom()).toBe('');
  });

  it('should have empty dateTo by default', () => {
    expect(service.dateTo()).toBe('');
  });

  it('should have regenerate counter at 0 by default', () => {
    expect(service.regenerate()).toBe(0);
  });

  it('should have refreshing false by default', () => {
    expect(service.refreshing()).toBe(false);
  });

  it('should update dateFrom signal', () => {
    service.dateFrom.set('2025-01-01');
    expect(service.dateFrom()).toBe('2025-01-01');
  });

  it('should update dateTo signal', () => {
    service.dateTo.set('2025-12-31');
    expect(service.dateTo()).toBe('2025-12-31');
  });

  it('should increment regenerate counter', () => {
    service.regenerate.update((v) => v + 1);
    expect(service.regenerate()).toBe(1);

    service.regenerate.update((v) => v + 1);
    expect(service.regenerate()).toBe(2);
  });

  it('should toggle refreshing signal', () => {
    service.refreshing.set(true);
    expect(service.refreshing()).toBe(true);

    service.refreshing.set(false);
    expect(service.refreshing()).toBe(false);
  });
});
