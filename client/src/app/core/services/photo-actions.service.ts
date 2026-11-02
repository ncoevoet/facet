import { DestroyRef, Injectable, inject } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from '../../features/gallery/gallery.store';
import { ExportService } from './export.service';
import { I18nService } from './i18n.service';
import { ApiService } from './api.service';
import { I18N } from '../i18n/keys';
import { AuthService } from './auth.service';
import { StalenessGuardFactory } from './staleness-guard.service';
import { clearThumbnailCaches } from './thumbnail-cache';

/** `POST /api/photo/delete` response — per-path, see `api.routers.export.api_photo_delete`. */
export interface PhotoDeleteResponse {
  dry_run: boolean;
  would_trash?: string[] | null;
  deleted: string[];
  not_found: string[];
  not_visible: string[];
  refused_bracket_lead: string[];
  sequence_siblings: string[];
  skipped: string[];
  /** Rows removed because their file was already gone (`remove_missing`).
   *  Never folded into `deleted`: no file was trashed for these. */
  removed_missing: string[];
  removed_catalog?: string[];
  trashed: number;
  errors: Record<string, string>;
}

/** Mirrors `MAX_REFRESH_PATHS` in api/routers/photo_refresh.py. */
export const MAX_REFRESH_PATHS = 100;

@Injectable({ providedIn: 'root' })
export class PhotoActionsService {
  private readonly dialog = inject(MatDialog);
  private readonly store = inject(GalleryStore);
  private readonly snackBar = inject(MatSnackBar);
  private readonly exportService = inject(ExportService);
  private readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);

  /** Explicit catalog erasure. No filesystem operation, expansion or Undo. */
  async removeFromCatalog(input: readonly string[], canProceed: () => boolean = () => true): Promise<string[]> {
    if (!canProceed() || !this.auth.isEdition() || !input.length || input.length > 10000) return [];
    const paths = [...new Set(input)];
    const token = this.auth.token;
    const guard = this.staleness.create(this.destroyRef, { track: 'status', valid: () => this.auth.token === token });
    try {
      const { ConfirmDialogComponent } = await import('../../shared/components/confirm-dialog/confirm-dialog.component');
      if (!guard.current()) return [];
      const ref = this.dialog.open(ConfirmDialogComponent, {
        width: '95vw', maxWidth: '30rem', data: {
          title: this.i18n.t(I18N.photo_detail.remove_catalog.title),
          message: this.i18n.t(I18N.photo_detail.remove_catalog.confirm, { count: paths.length }),
          confirmLabel: this.i18n.t(I18N.photo_detail.remove_catalog.action),
        },
      });
      if (!await firstValueFrom(ref.afterClosed()) || !guard.current() || !canProceed()) return [];
      const result = await firstValueFrom(this.api.post<PhotoDeleteResponse>('/photo/delete', {
        paths, catalog_only: true, dry_run: false,
      }));
      // Service-worker thumbnail copies outlive their database rows. Clear the
      // local thumbnail cache after an accepted erase, including old revisions.
      const removed = result.removed_catalog ?? [];
      if (removed.length) await clearThumbnailCaches();
      if (!guard.current()) return [];
      this.store.removePhotos(removed);
      this.snackBar.open(this.i18n.t(I18N.photo_detail.remove_catalog.result, { count: removed.length }), '', { duration: 4000 });
      return removed;
    } catch {
      if (guard.current()) this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
      return [];
    } finally { guard.dispose(); }
  }

  /**
   * Send photos to the OS trash via `POST /api/photo/delete`.
   *
   * Owns the request and the failure snackbar, matching `embedMetadata`'s
   * shape -- the only local effect of a delete is REMOVING rows, which the
   * caller applies via `GalleryStore.removePhotos` (this service never
   * reaches into the store for that), so there is no optimistic patch to own
   * here the way `toggleFavorite`/`toggleRejected` do per-component.
   *
   * Returns `null` (rather than throwing) on failure so callers can bail out
   * without a try/catch of their own; the error snackbar is already shown.
   */
  async deletePhotos(
    paths: string[],
    opts: { includeCompanions: boolean; includeSequenceSiblings: boolean; removeMissing?: boolean },
  ): Promise<PhotoDeleteResponse | null> {
    try {
      return await firstValueFrom(this.api.post<PhotoDeleteResponse>('/photo/delete', {
        paths,
        include_companions: opts.includeCompanions,
        include_sequence_siblings: opts.includeSequenceSiblings,
        remove_missing: opts.removeMissing ?? false,
        dry_run: false,
      }));
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
      return null;
    }
  }

  private readonly staleness = inject(StalenessGuardFactory);
  private readonly destroyRef = inject(DestroyRef);
  private refreshOpening = false;
  protected loadRefreshDialog() { return import('../../features/photo-detail/photo-refresh-dialog.component'); }

  async refreshPhotos(paths: string[]): Promise<string[]> {
    if (!this.auth.isEdition() || this.refreshOpening || this.dialog.openDialogs.length) return [];
    if (!paths.length || paths.length > MAX_REFRESH_PATHS) {
      this.snackBar.open(this.i18n.t(I18N.photo_refresh.limit), '', { duration: 4000 });
      return [];
    }
    this.refreshOpening = true;
    const owner = this.auth.identity();
    const { current, dispose } = this.staleness.create(this.destroyRef);
    try {
      const { PhotoRefreshDialogComponent } = await this.loadRefreshDialog();
      if (!current() || this.dialog.openDialogs.length) return [];
      const ref = this.dialog.open(PhotoRefreshDialogComponent, {
        width: '95vw', maxWidth: '520px', closeOnNavigation: false, data: [...paths],
      });
      const completed = ref.componentInstance.completed;
      const refreshed: string[] = await firstValueFrom(ref.afterClosed()) ?? completed();
      if (owner !== this.auth.identity() || !this.auth.isEdition()) return [];
      if (refreshed.length) await this.store.refreshPaths(refreshed);
      return refreshed;
    } finally { this.refreshOpening = false; dispose(); }
  }

  embedMetadata(photo: Photo): void {
    this.exportService.embedMetadata(photo.path).subscribe({
      next: () => this.snackBar.open(this.i18n.t(I18N.notifications.metadata_embedded), '', { duration: 2000 }),
      error: () => this.snackBar.open(this.i18n.t(I18N.notifications.metadata_embed_failed), '', { duration: 3000 }),
    });
  }

  openCritique(photo: Photo): void {
    import('../../features/gallery/photo-critique-dialog.component').then(m => {
      const vlmAvailable = this.store.config()?.features?.show_vlm_critique ?? false;
      this.dialog.open(m.PhotoCritiqueDialogComponent, {
        data: { photoPath: photo.path, vlmAvailable },
        width: '95vw',
        maxWidth: '600px',
      });
    });
  }

  openAddPerson(photo: Photo, onAssigned?: () => void): void {
    const owner = this.auth.identity();
    import('../../features/gallery/face-selector-dialog.component').then(m => {
      if (this.auth.identity() !== owner) return;
      const faceRef = this.dialog.open(m.FaceSelectorDialogComponent, {
        data: { photoPath: photo.path },
        width: '95vw',
        maxWidth: '400px',
      });
      faceRef.afterClosed().subscribe(face => {
        if (!face || this.auth.identity() !== owner) return;
        import('../../features/gallery/person-selector-dialog.component').then(m2 => {
          if (this.auth.identity() !== owner) return;
          const personRef = this.dialog.open(m2.PersonSelectorDialogComponent, {
            width: '95vw',
            maxWidth: '400px',
          });
          personRef.afterClosed().subscribe(async result => {
            if (!result || this.auth.identity() !== owner) return;
            if (result.kind === 'create') {
              const created = await this.store.createPerson(result.name, [face.id], photo.path);
              if (this.auth.identity() !== owner) return;
              if (created) {
                this.snackBar.open(this.i18n.t(I18N.notifications.faces_assigned), '', { duration: 2000 });
                onAssigned?.();
              } else {
                this.snackBar.open(this.i18n.t(I18N.persons.create_error), '', { duration: 3000 });
              }
            } else if (result.kind === 'select') {
              const assigned = await this.store.assignFace(face.id, result.person.id, photo.path, result.person.name);
              if (this.auth.identity() !== owner) return;
              if (assigned) {
                this.snackBar.open(this.i18n.t(I18N.notifications.faces_assigned), '', { duration: 2000 });
                onAssigned?.();
              } else {
                this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
              }
            }
          });
        });
      });
    });
  }
}
