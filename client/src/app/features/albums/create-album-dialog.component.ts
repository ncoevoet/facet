import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { AlbumService } from '../../core/services/album.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Component({
  selector: 'app-create-album-dialog',
  standalone: true,
  imports: [
    FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatTooltipModule, TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="'albums.create' | translate">{{ 'albums.create' | translate }}</h2>
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
      <button mat-flat-button [disabled]="!name.trim() || saving()" (click)="save()">
        {{ saving() ? ('ui.buttons.saving' | translate) : ('albums.create' | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class CreateAlbumDialogComponent {
  private albumService = inject(AlbumService);
  private dialogRef = inject(MatDialogRef<CreateAlbumDialogComponent>);

  name = '';
  description = '';
  readonly saving = signal(false);

  async save(): Promise<void> {
    if (!this.name.trim() || this.saving()) return;
    this.saving.set(true);
    try {
      const album = await firstValueFrom(this.albumService.create(this.name.trim(), this.description.trim()));
      this.dialogRef.close(album);
    } catch {
      this.saving.set(false);
    }
  }
}
