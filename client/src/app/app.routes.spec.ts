import { RouteReuseStrategy } from '@angular/router';
import { appConfig } from './app.config';
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
});
