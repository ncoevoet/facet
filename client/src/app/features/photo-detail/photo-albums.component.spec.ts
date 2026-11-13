import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { PhotoAlbumsComponent } from './photo-albums.component';

describe('PhotoAlbumsComponent', () => {
  let http: HttpTestingController;
  beforeEach(() => {
    const status = signal<object | null>({ user_id: 'alice' });
    const auth = { status, session: computed(() => (status() as { user_id?: string } | null)?.user_id ?? null), token: 'one' };
    TestBed.configureTestingModule({
      imports: [PhotoAlbumsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([]),
        { provide: AuthService, useValue: auth },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } }],
    });
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => { try { http.verify(); } finally { TestBed.resetTestingModule(); } });

  async function render(path = '/a.jpg') {
    const fixture = TestBed.createComponent(PhotoAlbumsComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path }));
    fixture.detectChanges();
    await fixture.whenStable();
    return fixture;
  }
  const chips = (root: HTMLElement) => [...root.querySelectorAll<HTMLAnchorElement>('[data-album-chip]')];

  it('reads the photo albums without any click and renders chips linking to each album', async () => {
    const fixture = await render();
    const request = http.expectOne('/api/photo/albums?path=/a.jpg');
    request.flush([{ id: 3, name: 'Alps', is_smart: false }, { id: 9, name: 'Best of', is_smart: true }]);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const items = chips(root);
    expect(items.map(a => a.textContent!.replace(/\s+/g, ' ').trim())).toEqual(['Alps', 'auto_awesomephoto_detail.smart_album:Best of']);
    expect(items[0].getAttribute('href')).toBe('/album/3');
    expect(items[1].getAttribute('href')).toBe('/album/9');
    expect(items[0].querySelector('mat-icon')).toBeNull();
    expect(items[1].querySelector('mat-icon')!.textContent).toContain('auto_awesome');
    expect(root.querySelector('h2')!.textContent).toContain('photo_detail.albums');
    expect(items[0].className).toContain('min-h-11');
  });

  it('renders nothing when the photo is in no album', async () => {
    const fixture = await render();
    http.expectOne('/api/photo/albums?path=/a.jpg').flush([]);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('section')).toBeNull();
  });

  it('renders nothing when the read fails', async () => {
    const fixture = await render();
    http.expectOne('/api/photo/albums?path=/a.jpg').flush('no', { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('section')).toBeNull();
  });

  it('ignores a stale response after the path changed and reads the new photo', async () => {
    const fixture = await render('/a.jpg');
    const stale = http.expectOne('/api/photo/albums?path=/a.jpg');
    fixture.componentRef.setInput('photo', makePhoto({ path: '/b.jpg' }));
    fixture.detectChanges();
    await fixture.whenStable();
    const fresh = http.expectOne('/api/photo/albums?path=/b.jpg');
    expect(stale.cancelled).toBe(true);
    fixture.detectChanges();
    expect(chips(fixture.nativeElement)).toHaveLength(0);
    fresh.flush([{ id: 2, name: 'New', is_smart: false }]);
    fixture.detectChanges();
    expect(chips(fixture.nativeElement).map(a => a.textContent!.trim())).toEqual(['New']);
  });
});
