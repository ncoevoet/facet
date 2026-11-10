import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
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
    mockApi = { get: vi.fn(() => of({ scenes: [], total: 7, page: 1, per_page: 20, total_pages: 1 })) };
    TestBed.configureTestingModule({
      providers: [
        ScenesComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key) } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => album } } } },
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
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
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
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => null } } } },
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
