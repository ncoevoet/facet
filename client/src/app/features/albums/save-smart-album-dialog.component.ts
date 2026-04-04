import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { AlbumService } from '../../core/services/album.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Component({
  selector: 'app-save-smart-album-dialog',
  standalone: true,
  imports: [
    FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatTooltipModule, TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="'albums.save_smart' | translate">{{ 'albums.save_smart' | translate }}</h2>
    <mat-dialog-content>
      <mat-form-field class="w-full">
        <mat-label>{{ 'albums.name' | translate }}</mat-label>
        <input matInput [(ngModel)]="name" (keydown.enter)="save()" />
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'ui.buttons.cancel' | translate }}</button>
      <button mat-flat-button [disabled]="!name.trim() || saving()" (click)="save()">
        {{ saving() ? ('ui.buttons.saving' | translate) : ('albums.save_smart' | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class SaveSmartAlbumDialogComponent {
  private albumService = inject(AlbumService);
  private dialogRef = inject(MatDialogRef<SaveSmartAlbumDialogComponent>);
  private data = inject<{ filterJson: string }>(MAT_DIALOG_DATA);

  name = '';
  readonly saving = signal(false);

  async save(): Promise<void> {
    if (!this.name.trim() || this.saving()) return;
    this.saving.set(true);
    try {
      await firstValueFrom(
        this.albumService.create(this.name.trim(), '', true, this.data.filterJson),
      );
      this.dialogRef.close(true);
    } catch {
      this.saving.set(false);
    }
  }
}
