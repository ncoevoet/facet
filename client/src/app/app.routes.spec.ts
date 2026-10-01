import { routes } from './app.routes';
import { authGuard } from './core/guards/auth.guard';
import { editionGuard } from './core/guards/edition.guard';

describe('route table', () => {
  const EDITION_PAGES = ['compare', 'culling', 'junk', 'merge-suggestions'];

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
});
