import { Route, Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { editionGuard } from './core/guards/edition.guard';

/**
 * Pages whose purpose is an edition write (some, like merge-suggestions, load
 * their data with a plain authenticated GET). One spread carries both the
 * guard and the `data.edition` flag, so the flag `App.lockEdition` reads to
 * decide which pages to leave cannot drift from the routes actually guarded.
 */
const EDITION_ONLY = {
  canActivate: [authGuard, editionGuard],
  data: { edition: true },
} satisfies Pick<Route, 'canActivate' | 'data'>;

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
    path: 'persons',
    loadComponent: () =>
      import('./features/persons/manage-persons.component').then(m => m.ManagePersonsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'merge-suggestions',
    loadComponent: () =>
      import('./features/persons/merge-suggestions.component').then(m => m.MergeSuggestionsComponent),
    ...EDITION_ONLY,
  },
  {
    path: 'compare',
    loadComponent: () =>
      import('./features/comparison/comparison.component').then(m => m.ComparisonComponent),
    ...EDITION_ONLY,
  },
  {
    path: 'culling',
    loadComponent: () =>
      import('./features/gallery/burst-culling.component').then(m => m.BurstCullingComponent),
    ...EDITION_ONLY,
  },
  {
    path: 'scenes',
    loadComponent: () =>
      import('./features/scenes/scenes.component').then(m => m.ScenesComponent),
    canActivate: [authGuard],
  },
  {
    path: 'junk',
    loadComponent: () =>
      import('./features/junk-sweep/junk-sweep.component').then(m => m.JunkSweepComponent),
    ...EDITION_ONLY,
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
    path: 'timeline/:year',
    loadComponent: () =>
      import('./features/timeline/timeline.component').then(m => m.TimelineComponent),
    canActivate: [authGuard],
  },
  {
    path: 'timeline/:year/:month',
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
    path: 'shared/album/:albumId/photo',
    loadComponent: () =>
      import('./shared/components/shared-view/shared-photo-detail.component').then(m => m.SharedPhotoDetailComponent),
  },
  {
    path: '**',
    redirectTo: '',
  },
];
