import { Component, DestroyRef, ElementRef, Injector, afterNextRender, inject, signal, viewChild, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { UserActivityJournal, activityName } from '../../core/agent/user-activity-journal.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../core/i18n/keys';
import { AuthService } from '../../core/services/auth.service';
import { Router } from '@angular/router';
import { AlbumDialogContext } from './album-dialog-context';

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
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="I18N.albums.edit | translate">{{ I18N.albums.edit | translate }}</h2>
    <mat-dialog-content>
      <mat-form-field class="w-full">
        <mat-label>{{ I18N.albums.name | translate }}</mat-label>
        <input matInput [(ngModel)]="name" maxlength="200" (keydown.enter)="save()" />
      </mat-form-field>
      <mat-form-field class="w-full">
        <mat-label>{{ I18N.albums.description_label | translate }}</mat-label>
        <textarea matInput [(ngModel)]="description" maxlength="500" rows="2"></textarea>
      </mat-form-field>
      @if (saveFailed()) {
        <p #saveError role="alert" tabindex="-1" class="rounded-md bg-[var(--mat-sys-error-container)] p-3 text-[var(--mat-sys-on-error-container)]">{{ I18N.albums.save_error | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close class="max-sm:!min-h-11">{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button class="max-sm:!min-h-11" [disabled]="!name.trim() || saving()" (click)="save()">{{ saving() ? (I18N.ui.buttons.saving | translate) : (I18N.ui.buttons.save | translate) }}</button>
    </mat-dialog-actions>
  `,
})
export class EditAlbumDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly albumService = inject(AlbumService);
  private readonly journal = inject(UserActivityJournal);
  private readonly dialogRef = inject(MatDialogRef<EditAlbumDialogComponent>);
  private readonly data = inject<EditAlbumDialogData>(MAT_DIALOG_DATA);
  private readonly injector = inject(Injector);
  private readonly errorElement = viewChild<ElementRef<HTMLElement>>('saveError');
  private readonly guard = new AlbumDialogContext(inject(AuthService), inject(Router), inject(DestroyRef));

  protected name = this.data.album.name;
  protected description = this.data.album.description || '';
  protected readonly saving = signal(false);
  protected readonly saveFailed = signal(false);

  protected async save(): Promise<void> {
    if (!this.name.trim() || this.saving() || !this.guard.canStart()) return;
    this.saving.set(true);
    this.saveFailed.set(false);
    try {
      const album = await firstValueFrom(
        this.albumService.update(this.data.album.id, {
          name: this.name.trim(),
          description: this.description.trim(),
        }),
      );
      if (!await this.guard.settled()) return;
      if (album.name !== this.data.album.name) {
        this.journal.record('album', [], { album_id: album.id, action: 'rename', name: activityName(album.name) });
      } else if ((album.description || '') !== (this.data.album.description || '')) {
        this.journal.record('album', [], { album_id: album.id, action: 'edit' });
      }
      this.dialogRef.close(album);
    } catch {
      if (await this.guard.settled()) {
        this.saving.set(false);
        this.saveFailed.set(true);
        afterNextRender(() => this.errorElement()?.nativeElement.focus(), { injector: this.injector });
      }
    }
  }
}
