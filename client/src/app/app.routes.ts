import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./features/gallery/gallery.component').then(m => m.GalleryComponent),
    canActivate: [authGuard],
  },
  {
    path: 'login',
    loadComponent: () =>
      import('./features/auth/login.component').then(m => m.LoginComponent),
  },
  {
    path: 'person/:personId',
    loadComponent: () =>
      import('./features/persons/person-page.component').then(m => m.PersonPageComponent),
    canActivate: [authGuard],
  },
  {
    path: 'persons',
    loadComponent: () =>
      import('./features/persons/manage-persons.component').then(m => m.ManagePersonsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'merge-suggestions',
    loadComponent: () =>
      import('./features/persons/merge-suggestions.component').then(m => m.MergeSuggestionsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'compare',
    loadComponent: () =>
      import('./features/comparison/comparison.component').then(m => m.ComparisonComponent),
    canActivate: [authGuard],
  },
  {
    path: 'stats',
    loadComponent: () =>
      import('./features/stats/stats.component').then(m => m.StatsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'albums',
    loadComponent: () =>
      import('./features/albums/albums.component').then(m => m.AlbumsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'album/:albumId',
    loadComponent: () =>
      import('./features/gallery/gallery.component').then(m => m.GalleryComponent),
    canActivate: [authGuard],
  },
  {
    path: '**',
    redirectTo: '',
  },
];
