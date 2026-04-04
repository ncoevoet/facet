import { TestBed } from '@angular/core/testing';
import { AlbumsFiltersService } from './albums-filters.service';

describe('AlbumsFiltersService', () => {
  let service: AlbumsFiltersService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [AlbumsFiltersService],
    });
    service = TestBed.inject(AlbumsFiltersService);
  });

  it('should have empty search by default', () => {
    expect(service.search()).toBe('');
  });

  it('should have updated_at as default sort', () => {
    expect(service.sort()).toBe('updated_at');
  });

  it('should have empty string as default type filter', () => {
    expect(service.typeFilter()).toBe('');
  });

  it('should update search signal', () => {
    service.search.set('vacation');
    expect(service.search()).toBe('vacation');
  });

  it('should update sort signal', () => {
    service.sort.set('name');
    expect(service.sort()).toBe('name');

    service.sort.set('photo_count');
    expect(service.sort()).toBe('photo_count');
  });

  it('should update typeFilter signal', () => {
    service.typeFilter.set('smart');
    expect(service.typeFilter()).toBe('smart');

    service.typeFilter.set('manual');
    expect(service.typeFilter()).toBe('manual');
  });
});
