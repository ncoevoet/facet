import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GeoPhotosService } from '../../core/services/geo-photos.service';
import { PhotoRefreshDialogComponent } from './photo-refresh-dialog.component';

describe('PhotoRefreshDialogComponent HTTP workflow', () => {
  let owner: ReturnType<typeof signal<string>>;
  let edition: ReturnType<typeof signal<boolean>>;
  let close: ReturnType<typeof vi.fn>;
  let geoRefresh: ReturnType<typeof vi.fn>;
  let http: HttpTestingController;
  let fixture: ReturnType<typeof TestBed.createComponent<PhotoRefreshDialogComponent>>;
  beforeEach(() => {
    owner = signal('alice');
    edition = signal(true);
    close = vi.fn();
    geoRefresh = vi.fn();
    TestBed.configureTestingModule({
      imports: [PhotoRefreshDialogComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(),
        { provide: MAT_DIALOG_DATA, useValue: ['/a.jpg', '/b.jpg'] },
        { provide: AuthService, useValue: { identity: owner, isEdition: edition } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: GeoPhotosService, useValue: { refresh: geoRefresh } },
        { provide: MatDialogRef, useValue: { close, beforeClosed: () => new Subject<void>() } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(PhotoRefreshDialogComponent);
    fixture.detectChanges();
  });
  afterEach(() => { fixture.destroy(); http.verify(); });

  it('waits for explicit confirmation and retries only failed photos', async () => {
    http.expectNone('/api/photos/refresh');
    const start = [...fixture.nativeElement.querySelectorAll('button')]
      .find((button: HTMLButtonElement) => button.textContent?.trim() === 'photo_refresh.start') as HTMLButtonElement;
    start.click();
    const request = http.expectOne('/api/photos/refresh');
    expect(request.request.body).toEqual({ paths: ['/a.jpg', '/b.jpg'] });
    request.flush({ refreshed: ['/a.jpg'], failed: [{ path: '/b.jpg', reason: 'unavailable' }] });
    await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('photo_refresh.failed');
    expect(fixture.nativeElement.textContent).toContain('/b.jpg — photo_refresh.reasons.unavailable');
    start.click();
    const retry = http.expectOne('/api/photos/refresh');
    expect(retry.request.body).toEqual({ paths: ['/b.jpg'] });
    retry.flush({ refreshed: ['/b.jpg'], failed: [] });
    await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.componentInstance.completed()).toEqual(['/a.jpg', '/b.jpg']);
    expect(start.disabled).toBe(true);
    // Re-read EXIF can add or drop GPS, so each run that refreshed a photo re-checks the Map link.
    expect(geoRefresh).toHaveBeenCalledTimes(2);
  });

  it('does not start twice while the first request is in flight', async () => {
    const pending = fixture.componentInstance.run();
    const request = http.expectOne('/api/photos/refresh');
    await fixture.componentInstance.run();
    http.expectNone('/api/photos/refresh');
    request.flush({ refreshed: ['/a.jpg', '/b.jpg'], failed: [] });
    await pending;
  });

  it('ignores completion immediately after account identity changes', async () => {
    const pending = fixture.componentInstance.run();
    const request = http.expectOne('/api/photos/refresh');
    owner.set('bob');
    request.flush({ refreshed: ['/a.jpg', '/b.jpg'], failed: [] });
    await pending;
    expect(fixture.componentInstance.completed()).toEqual([]);
    fixture.detectChanges();
    expect(close).toHaveBeenCalled();
  });

  it('closes when the edition session ends', () => {
    edition.set(false);
    fixture.detectChanges();
    expect(close).toHaveBeenCalled();
  });

  it('makes a failed request retryable without claiming success', async () => {
    const pending = fixture.componentInstance.run();
    http.expectOne('/api/photos/refresh').flush({ detail: 'Another library job is running' }, { status: 503, statusText: 'Unavailable' });
    await pending; fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('photo_refresh.failed');
    expect(fixture.nativeElement.textContent).toContain('Another library job is running');
    expect(fixture.componentInstance.completed()).toEqual([]);
    const retry = fixture.componentInstance.run();
    http.expectOne('/api/photos/refresh').flush({ refreshed: ['/a.jpg', '/b.jpg'], failed: [] });
    await retry;
    expect(fixture.componentInstance.completed()).toHaveLength(2);
  });
});
