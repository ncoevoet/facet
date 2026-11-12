import { TestBed } from '@angular/core/testing';
import { Subject, throwError, of } from 'rxjs';
import { ApiService } from './api.service';
import { GeoPhotosService } from './geo-photos.service';

describe('GeoPhotosService', () => {
  let get: ReturnType<typeof vi.fn>;
  let service: GeoPhotosService;

  beforeEach(() => {
    get = vi.fn();
    TestBed.configureTestingModule({ providers: [{ provide: ApiService, useValue: { get } }] });
    service = TestBed.inject(GeoPhotosService);
  });

  it('follows the map count across refreshes, so a first or last location toggles it', async () => {
    expect(service.available()).toBe(false);
    get.mockReturnValue(of({ count: 1 }));
    await service.refresh();
    expect(get).toHaveBeenCalledWith('/photos/map/count');
    expect(service.available()).toBe(true);
    get.mockReturnValue(of({ count: 0 }));
    await service.refresh();
    expect(service.available()).toBe(false);
  });

  it('keeps the last known state when the count fails', async () => {
    get.mockReturnValue(of({ count: 3 }));
    await service.refresh();
    get.mockReturnValue(throwError(() => new Error('offline')));
    await service.refresh();
    expect(service.available()).toBe(true);
  });

  it('ignores an older answer that lands after a newer one', async () => {
    const older = new Subject<{ count: number }>();
    get.mockReturnValueOnce(older).mockReturnValueOnce(of({ count: 0 }));
    const first = service.refresh();
    await service.refresh();
    older.next({ count: 5 }); older.complete();
    await first;
    expect(service.available()).toBe(false);
  });
});
