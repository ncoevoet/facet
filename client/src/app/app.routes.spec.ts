import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Title } from '@angular/platform-browser';
import { RouteReuseStrategy, RouterStateSnapshot, TitleStrategy } from '@angular/router';
import { appConfig } from './app.config';
import { I18nTitleStrategy } from './core/i18n-title.strategy';
import { I18N } from './core/i18n/keys';
import { I18nService } from './core/services/i18n.service';
import { routes } from './app.routes';
import { authGuard } from './core/guards/auth.guard';
import { editionGuard } from './core/guards/edition.guard';
import { GALLERY_PATHS, GalleryReuseStrategy, PHOTO_PATH } from './core/gallery-reuse.strategy';
import { GalleryComponent } from './features/gallery/gallery.component';

describe('route table', () => {
  const EDITION_PAGES = ['compare', 'culling', 'junk', 'merge-suggestions', 'stacks/edit'];

  it.each(EDITION_PAGES)('/%s carries authGuard then editionGuard', path => {
    const route = routes.find(r => r.path === path);
    expect(route?.canActivate).toEqual([authGuard, editionGuard]);
  });

  it('flags exactly the guarded pages with data.edition (what lockEdition reads)', () => {
    const flagged = routes.filter(r => r.data?.['edition'] === true).map(r => r.path);
    expect(flagged.sort()).toEqual([...EDITION_PAGES].sort());
  });

  it('no other route carries editionGuard', () => {
    const guarded = routes.filter(r => r.canActivate?.includes(editionGuard)).map(r => r.path);
    expect(guarded.sort()).toEqual([...EDITION_PAGES].sort());
  });

  it('has the gallery and photo routes GalleryReuseStrategy keeps alive', async () => {
    expect(GALLERY_PATHS).toEqual(['', 'album/:albumId']);
    expect(PHOTO_PATH).toBe('photo');
    for (const path of GALLERY_PATHS) {
      expect(await routes.find(r => r.path === path)?.loadComponent?.(), path).toBe(GalleryComponent);
    }
    expect(routes.some(r => r.path === PHOTO_PATH)).toBe(true);
  });

  it('registers GalleryReuseStrategy as the app\'s RouteReuseStrategy', () => {
    expect(appConfig.providers).toContainEqual({ provide: RouteReuseStrategy, useClass: GalleryReuseStrategy });
  });

  it('gives every page except the shared views and the fallback a translated tab title', () => {
    const untitled = routes.filter(r => !r.title).map(r => r.path);
    expect(untitled.sort()).toEqual(['**', 'shared/album/:albumId', 'shared/album/:albumId/photo']);
    for (const route of routes.filter(r => r.title)) {
      const key = route.title as string;
      expect(key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], I18N), route.path).toBe(key);
    }
  });
});

describe('I18nTitleStrategy', () => {
  const translations = signal<Record<string, unknown>>({});

  function strategy(): { title: Title; apply: (key: string | undefined) => void } {
    TestBed.configureTestingModule({
      providers: [{ provide: I18nService, useValue: {
        isLoaded: () => Object.keys(translations()).length > 0,
        t: (key: string) => (translations()['nav'] as Record<string, string> | undefined)?.[key.split('.')[1]] ?? key,
      } }],
    });
    let current: string | undefined;
    const instance = TestBed.inject(I18nTitleStrategy);
    vi.spyOn(instance, 'buildTitle').mockImplementation(() => current);
    return {
      title: TestBed.inject(Title),
      apply: key => { current = key; instance.updateTitle({} as RouterStateSnapshot); TestBed.tick(); },
    };
  }

  it('names the page, waits for translations, and follows a language switch', () => {
    translations.set({});
    const { title, apply } = strategy();
    apply('nav.stats');
    expect(title.getTitle()).toBe('Facet');
    translations.set({ nav: { stats: 'Statistics' } });
    TestBed.tick();
    expect(title.getTitle()).toBe('Statistics · Facet');
    translations.set({ nav: { stats: 'Statistiques' } });
    TestBed.tick();
    expect(title.getTitle()).toBe('Statistiques · Facet');
    apply(undefined);
    expect(title.getTitle()).toBe('Facet');
  });

  it('is the app\'s TitleStrategy', () => {
    expect(appConfig.providers).toContainEqual({ provide: TitleStrategy, useExisting: I18nTitleStrategy });
  });
});
