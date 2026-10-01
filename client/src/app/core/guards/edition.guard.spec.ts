import { TestBed } from '@angular/core/testing';
import { Router, ActivatedRouteSnapshot, RouterStateSnapshot, UrlTree } from '@angular/router';
import { signal } from '@angular/core';
import { editionGuard } from './edition.guard';
import { AuthService } from '../services/auth.service';

describe('editionGuard', () => {
  const isEdition = signal(false);
  const tree = {} as UrlTree;
  const createUrlTree = vi.fn(() => tree);

  beforeEach(() => {
    isEdition.set(false);
    createUrlTree.mockClear();
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { isEdition } },
        { provide: Router, useValue: { createUrlTree } },
      ],
    });
  });

  const runGuard = () =>
    TestBed.runInInjectionContext(() =>
      editionGuard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot),
    );

  it('allows a session holding edition', () => {
    isEdition.set(true);
    expect(runGuard()).toBe(true);
    expect(createUrlTree).not.toHaveBeenCalled();
  });

  it('redirects a session without edition (open install included) to the gallery', () => {
    expect(runGuard()).toBe(tree);
    expect(createUrlTree).toHaveBeenCalledWith(['/']);
  });
});
