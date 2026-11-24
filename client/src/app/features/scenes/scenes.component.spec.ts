import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Location } from '@angular/common';
import { HttpContext, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideLocationMocks } from '@angular/common/testing';
import { ActivatedRoute, convertToParamMap, NavigationEnd, provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { BehaviorSubject, filter, firstValueFrom, of, Subject, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { errorInterceptor } from '../../core/interceptors/error.interceptor';
import { AlbumService } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PageContextService } from '../../core/agent/page-context.service';
import { GalleryStore } from '../gallery/gallery.store';
import { ScenesComponent } from './scenes.component';

describe('ScenesComponent page context', () => {
  let mockApi: { get: Mock };
  let pageContext: PageContextService;

  const setup = (album: string | null = null): ScenesComponent => {
    const queryParamMap = convertToParamMap(album === null ? {} : { album });
    mockApi = { get: vi.fn(() => of({ scenes: [], total: 7, page: 1, per_page: 20, total_pages: 1 })) };
    TestBed.configureTestingModule({
      providers: [
        ScenesComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key) } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap }, queryParamMap: of(queryParamMap) } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: AlbumService, useValue: { listNonSmart: () => of([]) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: GalleryStore, useValue: { config: () => null } },
      ],
    });
    pageContext = TestBed.inject(PageContextService);
    return TestBed.inject(ScenesComponent);
  };

  it('registers the scenes page with an empty scope before anything loads', () => {
    setup();
    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: null, total: 0 });
  });

  it('reports the album scope and total once loaded', async () => {
    const component = setup('42');
    await component.ngOnInit();
    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: '42', total: 7 });
  });

  it('removes the registration when the component is destroyed', () => {
    setup();
    expect(pageContext.snapshot()).not.toBeNull();
    TestBed.resetTestingModule();
    expect(pageContext.snapshot()).toBeNull();
  });
});

describe('ScenesComponent load more', () => {
  it('re-requests the same page after a failed load-more, not the next one', async () => {
    const page1 = { scenes: [], total: 60, page: 1, per_page: 20, total_pages: 3 };
    const api = { get: vi.fn(() => of(page1)) };
    TestBed.configureTestingModule({
      providers: [
        ScenesComponent,
        { provide: ApiService, useValue: api },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key) } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap({}) }, queryParamMap: of(convertToParamMap({})) } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: AlbumService, useValue: { listNonSmart: () => of([]) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: GalleryStore, useValue: { config: () => null } },
      ],
    });
    const component = TestBed.inject(ScenesComponent) as any;
    const lastPage = () => (api.get.mock.calls.at(-1) as unknown as [string, { page: number }])[1].page;

    await component.ngOnInit();
    expect(lastPage()).toBe(1);

    api.get.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.loadMore();
    expect(lastPage()).toBe(2);

    await component.loadMore();
    expect(lastPage()).toBe(2);
  });
});

describe('ScenesComponent layout', () => {
  async function render() {
    const scene = (id: number) => ({
      scene_id: id, start: '2026-01-01T10:00:00', end: '2026-01-01T10:05:00', count: 1, best_path: '/a.jpg',
      photos: [{ path: '/a.jpg', filename: 'a.jpg', aggregate: 7, date_taken: null }],
    });
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get: vi.fn(() => of({ scenes: [scene(1), scene(2)], total: 2, page: 1, per_page: 20, total_pages: 1 })) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key), translations: () => ({}) } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap({}) }, queryParamMap: of(convertToParamMap({})) } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: AlbumService, useValue: { listNonSmart: () => of([]) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: GalleryStore, useValue: { config: () => null } },
      ],
    });
    const fixture = TestBed.createComponent(ScenesComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('insets its content 16px (px-4) like the other pages, not centred in a padded column', async () => {
    const content = (await render()).querySelector('div.w-full') as HTMLElement;
    expect(content.className).toContain('px-4');
    expect(content.className).not.toContain('md:px-8');
    expect(content.className).not.toContain('mx-auto');
    expect(content.className).not.toContain('max-w-');
  });

  it('lays the scenes out as cards, two to a row from xl, three tiles per row inside', async () => {
    const host = await render();
    const grid = host.querySelector('[data-scene-grid]') as HTMLElement;
    expect(grid.className).toContain('grid-cols-1');
    expect(grid.className).toContain('xl:grid-cols-2');
    expect(grid.querySelectorAll(':scope > mat-card').length).toBe(2);
    expect(grid.querySelector('mat-card .grid')!.className).toContain('xl:grid-cols-3');
  });

  it('wraps the header row and keeps the title for assistive tech only', async () => {
    const host = await render();
    const heading = host.querySelector('h1') as HTMLElement;
    expect(heading.classList.contains('sr-only')).toBe(true);
    expect(heading.parentElement!.classList.contains('flex-wrap')).toBe(true);
  });
});

describe('ScenesComponent album query navigation', () => {
  it('reloads page one on select, Back and Forward in the same component and drops late responses', async () => {
    const late = new Subject<unknown>();
    const response = (total: number) => ({ scenes: [], total, page: 1, per_page: 20, total_pages: 1 });
    const get = vi.fn().mockReturnValueOnce(of(response(1))).mockReturnValueOnce(late)
      .mockReturnValueOnce(of(response(3))).mockReturnValueOnce(of(response(4)));
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{
          path: 'scenes',
          component: ScenesComponent,
          runGuardsAndResolvers: 'paramsOrQueryParamsChange',
          canActivate: [route => route.queryParamMap.get('album') !== '99'],
        }]),
        provideLocationMocks(),
        { provide: ApiService, useValue: { get } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key), translations: () => ({}) } },
        { provide: AlbumService, useValue: { listNonSmart: () => of([]) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: GalleryStore, useValue: { config: () => null } },
      ],
    });
    const router = TestBed.inject(Router);
    router.setUpLocationChangeListener();
    const location = TestBed.inject(Location);
    const pageContext = TestBed.inject(PageContextService);
    const harness = await RouterTestingHarness.create('/scenes?album=42');
    const component = harness.routeDebugElement!.componentInstance as unknown as {
      selectAlbum(album: string | null): Promise<void>;
    };
    const arrived = () => firstValueFrom(router.events.pipe(filter(event => event instanceof NavigationEnd)));

    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: '42', total: 1 });
    const selected = arrived();
    void component.selectAlbum('84');
    await selected;
    expect(get.mock.calls.at(-1)).toEqual(['/scenes', { page: 1, per_page: 20, album_id: '84' }, expect.any(HttpContext)]);

    const wentBack = arrived();
    location.back();
    await wentBack;
    await harness.fixture.whenStable();
    expect(harness.routeDebugElement!.componentInstance).toBe(component);
    expect(router.url).toBe('/scenes?album=42');
    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: '42', total: 3 });

    late.next(response(99));
    await harness.fixture.whenStable();
    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: '42', total: 3 });

    const wentForward = arrived();
    location.forward();
    await wentForward;
    await harness.fixture.whenStable();
    expect(router.url).toBe('/scenes?album=84');
    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: '84', total: 4 });

    await component.selectAlbum('84');
    expect(await router.navigateByUrl('/scenes?album=84&extra=1')).toBe(true);
    await component.selectAlbum('99');
    await harness.fixture.whenStable();
    expect(router.url).toBe('/scenes?album=84&extra=1');
    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: '84', total: 4 });
    expect(get.mock.calls).toEqual(['42', '84', '42', '84'].map(album_id =>
      ['/scenes', { page: 1, per_page: 20, album_id }, expect.any(HttpContext)],
    ));
  });
});

describe('ScenesComponent first-page recovery', () => {
  const response = (withScene = false) => ({
    scenes: withScene ? [{
      scene_id: 1, start: '2026-01-01T10:00:00', end: '2026-01-01T10:05:00',
      count: 1, best_path: '/a.jpg', photos: [],
    }] : [],
    total: withScene ? 1 : 0, page: 1, per_page: 20, total_pages: 1,
  });

  function setup(get?: Mock) {
    const queryParamMap = new BehaviorSubject(convertToParamMap({ album: '42' }));
    TestBed.configureTestingModule({
      providers: [
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: queryParamMap.value }, queryParamMap } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        ...(get ? [{ provide: ApiService, useValue: { get } }]
          : [provideHttpClient(withInterceptors([errorInterceptor])), provideHttpClientTesting()]),
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: AlbumService, useValue: { listNonSmart: () => of([]) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: GalleryStore, useValue: { config: () => null } },
      ],
    });
    const fixture = TestBed.createComponent(ScenesComponent);
    const host: HTMLElement = fixture.nativeElement;
    const render = async () => {
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
    };
    return { host, render, queryParamMap };
  }

  it('keeps failure distinct from an empty album and retries the same first page once', async () => {
    const pending = new Subject<ReturnType<typeof response>>();
    const get = vi.fn().mockReturnValueOnce(throwError(() => new Error('first')))
      .mockReturnValueOnce(pending);
    const { host, render } = setup(get);

    await render();
    expect(host.textContent).not.toContain('scenes.empty');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('scenes.load_error');
    const retry = host.querySelector<HTMLButtonElement>('[data-scenes-retry]')!;
    retry.click();
    await render();
    retry.click();
    expect(get.mock.calls).toEqual(Array.from({ length: 2 }, () =>
      ['/scenes', { page: 1, per_page: 20, album_id: '42' }, expect.any(HttpContext)]));
    expect(retry.getAttribute('aria-disabled')).toBe('true');

    pending.next(response(true));
    await render();
    expect(host.querySelectorAll('[data-scene-grid] mat-card')).toHaveLength(1);
    expect(host.querySelector('[data-scenes-retry]')).toBeNull();
  });

  it('clears a prior failure on album change and shows the genuine empty state', async () => {
    const get = vi.fn().mockReturnValueOnce(throwError(() => new Error('first')))
      .mockReturnValueOnce(of(response()));
    const { host, render, queryParamMap } = setup(get);

    await render();
    expect(host.querySelector('[data-scenes-retry]')).not.toBeNull();
    queryParamMap.next(convertToParamMap({ album: '84' }));
    await render();
    expect(get.mock.calls.at(-1)).toEqual(['/scenes', { page: 1, per_page: 20, album_id: '84' }, expect.any(HttpContext)]);
    expect(host.querySelector('[data-scenes-retry]')).toBeNull();
    expect(host.textContent).toContain('scenes.empty');
  });

  it('keeps server errors local while the interceptor still reports crashes', async () => {
    const { host, render, queryParamMap } = setup();
    const http = TestBed.inject(HttpTestingController);
    const snack = TestBed.inject(MatSnackBar);
    const requestFor = (album: string) => http.expectOne(req =>
      req.url === '/api/scenes' && req.params.get('album_id') === album && req.params.get('page') === '1');
    const serverFailure = { status: 500, statusText: 'Server error' };
    const acknowledgeCrashReport = () => http.expectOne('/api/client-errors').flush(null);

    await render();
    requestFor('42').flush(null, serverFailure);
    acknowledgeCrashReport();
    await render();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('scenes.load_error');
    expect(snack.open).not.toHaveBeenCalled();

    host.querySelector<HTMLButtonElement>('[data-scenes-retry]')!.click();
    const oldRetry = requestFor('42');
    queryParamMap.next(convertToParamMap({ album: '84' }));
    requestFor('84').flush(response(true));
    await render();
    oldRetry.flush(null, serverFailure);
    acknowledgeCrashReport();
    await render();
    expect(host.querySelector('[data-scenes-retry]')).toBeNull();
    expect(host.querySelectorAll('[data-scene-grid] mat-card')).toHaveLength(1);
    expect(snack.open).not.toHaveBeenCalled();
    http.verify();
  });
});
