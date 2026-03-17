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
    path: 'culling',
    loadComponent: () =>
      import('./features/gallery/burst-culling.component').then(m => m.BurstCullingComponent),
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
    path: 'capsules',
    loadComponent: () =>
      import('./features/capsules/capsules.component').then(m => m.CapsulesComponent),
    canActivate: [authGuard],
  },
  {
    path: 'folders',
    loadComponent: () =>
      import('./features/folders/folders.component').then(m => m.FoldersComponent),
    canActivate: [authGuard],
  },
  {
    path: 'timeline',
    loadComponent: () =>
      import('./features/timeline/timeline.component').then(m => m.TimelineComponent),
    canActivate: [authGuard],
  },
  {
    path: 'map',
    loadComponent: () =>
      import('./features/map/map.component').then(m => m.MapComponent),
    canActivate: [authGuard],
  },
  {
    path: 'photo',
    loadComponent: () =>
      import('./features/photo-detail/photo-detail.component').then(m => m.PhotoDetailComponent),
    canActivate: [authGuard],
  },
  {
    path: 'shared/album/:albumId',
    loadComponent: () =>
      import('./shared/components/shared-view/shared-view.component').then(m => m.SharedViewComponent),
  },
  {
    path: 'shared/person/:personId',
    loadComponent: () =>
      import('./shared/components/shared-view/shared-view.component').then(m => m.SharedViewComponent),
  },
  {
    path: '**',
    redirectTo: '',
  },
];
