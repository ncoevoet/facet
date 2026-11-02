import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';
import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { UserActivityJournal, activityName } from '../../core/agent/user-activity-journal.service';
import { AlbumService } from '../../core/services/album.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../core/i18n/keys';

@Component({
  selector: 'app-create-album-dialog',
  standalone: true,
  imports: [
    FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatTooltipModule, TranslatePipe, ContextHelpComponent,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="I18N.albums.create | translate">{{ I18N.albums.create | translate }}</h2>
    <mat-dialog-content>
      <mat-form-field class="w-full">
        <mat-label>{{ I18N.albums.name | translate }}</mat-label>
        <input matInput [(ngModel)]="name" maxlength="200" (keydown.enter)="save()" />
      </mat-form-field>
      <mat-form-field class="w-full">
        <mat-label>{{ I18N.albums.description_label | translate }}</mat-label>
        <textarea matInput [(ngModel)]="description" maxlength="500" rows="2"></textarea>
      </mat-form-field>
      <app-context-help [label]="I18N.albums.creation.help" [keys]="helpKeys" />
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button [disabled]="!name.trim() || saving()" (click)="save()">
        {{ saving() ? (I18N.ui.buttons.saving | translate) : (I18N.albums.create | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class CreateAlbumDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly helpKeys = [this.I18N.albums.creation.manual];
  private albumService = inject(AlbumService);
  private journal = inject(UserActivityJournal);
  private dialogRef = inject(MatDialogRef<CreateAlbumDialogComponent>);

  name = '';
  description = '';
  readonly saving = signal(false);

  async save(): Promise<void> {
    if (!this.name.trim() || this.saving()) return;
    this.saving.set(true);
    try {
      const album = await firstValueFrom(this.albumService.create(this.name.trim(), this.description.trim()));
      this.journal.record('album', [], { album_id: album.id, action: 'create', name: activityName(album.name) });
      this.dialogRef.close(album);
    } catch {
      this.saving.set(false);
    }
  }
}
