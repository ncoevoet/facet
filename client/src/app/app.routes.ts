import { Route, Routes, Router } from '@angular/router';
import { inject } from '@angular/core';
import { ComparisonSessionService } from './features/gallery/comparison-session.service';
import { authGuard } from './core/guards/auth.guard';
import { editionGuard } from './core/guards/edition.guard';
import { I18N } from './core/i18n/keys';

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
    path: 'photo-compare',
    title: I18N.compare.title,
    loadComponent: () => import('./features/gallery/comparison-workspace.component').then(m => m.ComparisonWorkspaceComponent),
    canActivate: [authGuard, () => inject(ComparisonSessionService).snapshot().photos.length >= 2 || inject(Router).parseUrl('/')],
  },
  {
    path: '',
    title: I18N.nav.gallery,
    loadComponent: () =>
      import('./features/gallery/gallery.component').then(m => m.GalleryComponent),
    canActivate: [authGuard],
  },
  {
    path: 'login',
    title: I18N.login.title,
    loadComponent: () =>
      import('./features/auth/login.component').then(m => m.LoginComponent),
  },
  {
    path: 'persons',
    title: I18N.nav.persons,
    loadComponent: () =>
      import('./features/persons/manage-persons.component').then(m => m.ManagePersonsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'merge-suggestions',
    title: I18N.merge_suggestions.title,
    loadComponent: () =>
      import('./features/persons/merge-suggestions.component').then(m => m.MergeSuggestionsComponent),
    ...EDITION_ONLY,
  },
  {
    path: 'compare',
    title: I18N.comparison.title,
    loadComponent: () =>
      import('./features/comparison/comparison.component').then(m => m.ComparisonComponent),
    ...EDITION_ONLY,
  },
  {
    path: 'culling',
    title: I18N.culling.title,
    loadComponent: () =>
      import('./features/gallery/burst-culling.component').then(m => m.BurstCullingComponent),
    ...EDITION_ONLY,
  },
  {
    path: 'stacks/edit',
    title: I18N.stacks.create,
    loadComponent: () => import('./features/gallery/stack-editor-page.component').then(m => m.StackEditorPageComponent),
    ...EDITION_ONLY,
  },
  {
    path: 'scenes',
    title: I18N.scenes.title,
    loadComponent: () =>
      import('./features/scenes/scenes.component').then(m => m.ScenesComponent),
    canActivate: [authGuard],
  },
  {
    path: 'junk',
    title: I18N.nav.junk_sweep,
    loadComponent: () =>
      import('./features/junk-sweep/junk-sweep.component').then(m => m.JunkSweepComponent),
    ...EDITION_ONLY,
  },
  {
    path: 'stats',
    title: I18N.nav.stats,
    loadComponent: () =>
      import('./features/stats/stats.component').then(m => m.StatsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'albums',
    title: I18N.albums.title,
    loadComponent: () =>
      import('./features/albums/albums.component').then(m => m.AlbumsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'album/:albumId',
    title: I18N.albums.title,
    loadComponent: () =>
      import('./features/gallery/gallery.component').then(m => m.GalleryComponent),
    canActivate: [authGuard],
  },
  {
    path: 'capsules',
    title: I18N.capsules.title,
    loadComponent: () =>
      import('./features/capsules/capsules.component').then(m => m.CapsulesComponent),
    canActivate: [authGuard],
  },
  {
    path: 'folders',
    title: I18N.folders.title,
    loadComponent: () =>
      import('./features/folders/folders.component').then(m => m.FoldersComponent),
    canActivate: [authGuard],
  },
  {
    path: 'timeline',
    title: I18N.timeline.title,
    loadComponent: () =>
      import('./features/timeline/timeline.component').then(m => m.TimelineComponent),
    canActivate: [authGuard],
  },
  {
    path: 'timeline/:year',
    title: I18N.timeline.title,
    loadComponent: () =>
      import('./features/timeline/timeline.component').then(m => m.TimelineComponent),
    canActivate: [authGuard],
  },
  {
    path: 'timeline/:year/:month',
    title: I18N.timeline.title,
    loadComponent: () =>
      import('./features/timeline/timeline.component').then(m => m.TimelineComponent),
    canActivate: [authGuard],
  },
  {
    path: 'map',
    title: I18N.map.title,
    loadComponent: () =>
      import('./features/map/map.component').then(m => m.MapComponent),
    canActivate: [authGuard],
  },
  {
    path: 'photo',
    title: I18N.photo_detail.details,
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
