import { Injectable, inject } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from '../../features/gallery/gallery.store';
import { ExportService } from './export.service';
import { I18nService } from './i18n.service';
import { I18N } from '../i18n/keys';

@Injectable({ providedIn: 'root' })
export class PhotoActionsService {
  private readonly dialog = inject(MatDialog);
  private readonly store = inject(GalleryStore);
  private readonly snackBar = inject(MatSnackBar);
  private readonly exportService = inject(ExportService);
  private readonly i18n = inject(I18nService);

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
    import('../../features/gallery/face-selector-dialog.component').then(m => {
      const faceRef = this.dialog.open(m.FaceSelectorDialogComponent, {
        data: { photoPath: photo.path },
        width: '95vw',
        maxWidth: '400px',
      });
      faceRef.afterClosed().subscribe(face => {
        if (!face) return;
        import('../../features/gallery/person-selector-dialog.component').then(m2 => {
          const persons = this.store.persons().filter(p => p.name);
          const personRef = this.dialog.open(m2.PersonSelectorDialogComponent, {
            data: persons,
            width: '95vw',
            maxWidth: '400px',
          });
          personRef.afterClosed().subscribe(async result => {
            if (!result) return;
            if (result.kind === 'create') {
              const created = await this.store.createPerson(result.name, [face.id], photo.path);
              if (created) {
                this.snackBar.open(this.i18n.t(I18N.notifications.faces_assigned), '', { duration: 2000 });
                onAssigned?.();
              } else {
                this.snackBar.open(this.i18n.t(I18N.persons.create_error), '', { duration: 3000 });
              }
            } else if (result.kind === 'select') {
              await this.store.assignFace(face.id, result.person.id, photo.path, result.person.name);
              this.snackBar.open(this.i18n.t(I18N.notifications.faces_assigned), '', { duration: 2000 });
              onAssigned?.();
            }
          });
        });
      });
    });
  }
}
