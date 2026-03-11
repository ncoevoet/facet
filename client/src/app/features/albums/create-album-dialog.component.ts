import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { firstValueFrom } from 'rxjs';
import { AlbumService } from '../../core/services/album.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Component({
  selector: 'app-create-album-dialog',
  standalone: true,
  imports: [
    FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title>{{ 'albums.create' | translate }}</h2>
    <mat-dialog-content>
      <mat-form-field class="w-full">
        <mat-label>{{ 'albums.name' | translate }}</mat-label>
        <input matInput [(ngModel)]="name" (keydown.enter)="save()" />
      </mat-form-field>
      <mat-form-field class="w-full">
        <mat-label>{{ 'albums.description_label' | translate }}</mat-label>
        <textarea matInput [(ngModel)]="description" rows="2"></textarea>
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'ui.buttons.cancel' | translate }}</button>
      <button mat-flat-button [disabled]="!name.trim()" (click)="save()">{{ 'albums.create' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class CreateAlbumDialogComponent {
  private albumService = inject(AlbumService);
  private dialogRef = inject(MatDialogRef<CreateAlbumDialogComponent>);

  name = '';
  description = '';

  async save(): Promise<void> {
    if (!this.name.trim()) return;
    await firstValueFrom(this.albumService.create(this.name.trim(), this.description.trim()));
    this.dialogRef.close(true);
  }
}
