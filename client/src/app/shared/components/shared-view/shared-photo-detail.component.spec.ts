import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of, Subject } from 'rxjs';
import { SharedPhotoDetailComponent } from './shared-photo-detail.component';
import { ApiService } from '../../../core/services/api.service';
import { I18nService } from '../../../core/services/i18n.service';
import { makePhoto } from '../../../../testing/photo.fixture';

describe('Shared photo detail extended metric availability', () => {
  beforeEach(() => TestBed.configureTestingModule({
    imports: [SharedPhotoDetailComponent],
    providers: [
      { provide: ApiService, useValue: { imageUrl: () => '/image', get: () => of({ options: [] }) } },
      { provide: I18nService, useValue: { t: (key: string) => key, locale: () => 'en', translations: () => ({}) } },
      { provide: Router, useValue: { navigate: vi.fn() } },
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({}), queryParamMap: convertToParamMap({}), url: [] } } },
    ],
  }));

  it('preserves zero, hides present NULL (no library config in the shared view), and hides fields omitted by an older payload', () => {
    const view = TestBed.createComponent(SharedPhotoDetailComponent);
    vi.spyOn(view.componentInstance, 'ngOnInit').mockResolvedValue(undefined);
    view.componentInstance.photo.set(makePhoto({ aesthetic_v25: 0, qrealign_score: null, deqa_score: null }));
    view.detectChanges();
    expect(view.nativeElement.querySelector('[data-testid="aesthetic_v25-score"]').textContent.trim()).toBe('0.0');
    for (const key of ['qrealign_score', 'deqa_score']) {
      expect(view.nativeElement.querySelector(`[data-testid="${key}-row"]`)).toBeNull();
    }
    view.componentInstance.photo.set(makePhoto());
    view.detectChanges();
    expect(view.nativeElement.querySelectorAll('app-extended-quality [data-testid$="-row"]').length).toBe(0);
  });
});

describe('Shared photo detail album capability transport', () => {
  const asset = '1.' + 'a'.repeat(64);
  const sharedPhoto = () => { const metadata: Partial<ReturnType<typeof makePhoto>> = makePhoto(); delete metadata.path; return { ...metadata, asset_id: asset }; };
  function setup() {
    const query = convertToParamMap({ token: 'fixture-album-token', asset_id: asset });
    const route = { snapshot: { paramMap: convertToParamMap({ albumId: '7' }), queryParamMap: query, url: [] } };
    const read = vi.fn(() => of(sharedPhoto()));
    const navigate = vi.fn();
    TestBed.configureTestingModule({ imports: [SharedPhotoDetailComponent], providers: [
      { provide: ApiService, useValue: { get: read, imageUrl: () => '/ordinary-image' } },
      { provide: ActivatedRoute, useValue: route },
      { provide: Router, useValue: { navigate } },
      { provide: I18nService, useValue: { t: (key: string) => key, locale: () => 'en', translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(SharedPhotoDetailComponent);
    return { fixture, route, read, navigate };
  }

  it('revalidates history, loads only scoped metadata and uses scoped image/thumbnail/retry URLs', async () => {
    const { fixture, read } = setup();
    const previous = history.state;
    history.replaceState({ photo: makePhoto({ path: '/untrusted-history.jpg' }) }, '');
    try {
      await fixture.componentInstance.ngOnInit();
      expect(read).toHaveBeenCalledTimes(1);
      expect(read).toHaveBeenCalledWith('/shared/album/7/photo', {
        asset_id: asset, token: 'fixture-album-token', 'ngsw-bypass': '1',
      });
      const component = fixture.componentInstance as any;
      expect(component.photo().path).toBe(asset);
      for (const value of [component.fullImageUrl(), component.thumbnailImageUrl()]) {
        const url = new URL(value, 'http://facet.test');
        expect(url.pathname).toContain('/api/shared/album/7/media/');
        expect(url.searchParams.get('token')).toBe('fixture-album-token');
        expect(url.searchParams.get('ngsw-bypass')).toBe('1');
      }
      component.retryFullImage();
      expect(new URL(component.fullImageUrl(), 'http://facet.test').searchParams.has('facet_retry')).toBe(true);
    } finally { history.replaceState(previous, ''); fixture.destroy(); }
  });

  it('discards a metadata completion after changing the link token', async () => {
    const { fixture, read, route, navigate } = setup();
    const pending = new Subject<ReturnType<typeof sharedPhoto>>();
    read.mockReturnValueOnce(pending);
    const load = fixture.componentInstance.ngOnInit();
    route.snapshot.queryParamMap = convertToParamMap({ token: 'new-link', asset_id: asset });
    pending.next(sharedPhoto()); pending.complete(); await load;
    expect(fixture.componentInstance.photo()).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
    fixture.destroy();
  });
});
