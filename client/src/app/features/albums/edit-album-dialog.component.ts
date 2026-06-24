import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { AlbumService, Album } from '../../core/services/album.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

export interface EditAlbumDialogData {
  album: Album;
}

@Component({
  selector: 'app-edit-album-dialog',
  standalone: true,
  imports: [
    FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatTooltipModule, TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="'albums.edit' | translate">{{ 'albums.edit' | translate }}</h2>
    <mat-dialog-content>
      <mat-form-field class="w-full">
        <mat-label>{{ 'albums.name' | translate }}</mat-label>
        <input matInput [(ngModel)]="name" maxlength="100" (keydown.enter)="save()" />
      </mat-form-field>
      <mat-form-field class="w-full">
        <mat-label>{{ 'albums.description_label' | translate }}</mat-label>
        <textarea matInput [(ngModel)]="description" maxlength="500" rows="2"></textarea>
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'ui.buttons.cancel' | translate }}</button>
      <button mat-flat-button [disabled]="!name.trim() || saving()" (click)="save()">{{ saving() ? ('ui.buttons.saving' | translate) : ('ui.buttons.save' | translate) }}</button>
    </mat-dialog-actions>
  `,
})
export class EditAlbumDialogComponent {
  private readonly albumService = inject(AlbumService);
  private readonly dialogRef = inject(MatDialogRef<EditAlbumDialogComponent>);
  private readonly data = inject<EditAlbumDialogData>(MAT_DIALOG_DATA);

  protected name = this.data.album.name;
  protected description = this.data.album.description || '';
  protected readonly saving = signal(false);

  protected async save(): Promise<void> {
    if (!this.name.trim() || this.saving()) return;
    this.saving.set(true);
    try {
      const album = await firstValueFrom(
        this.albumService.update(this.data.album.id, {
          name: this.name.trim(),
          description: this.description.trim(),
        }),
      );
      this.dialogRef.close(album);
    } catch {
      this.saving.set(false);
    }
  }
}
