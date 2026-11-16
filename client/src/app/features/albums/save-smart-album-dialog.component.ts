import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';
import { afterNextRender, Component, DestroyRef, ElementRef, inject, Injector, signal, viewChild, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { UserActivityJournal, activityName } from '../../core/agent/user-activity-journal.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService } from '../../core/services/album.service';
import { AlbumDialogContext } from './album-dialog-context';
import { Router } from '@angular/router';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../core/i18n/keys';

@Component({
  selector: 'app-save-smart-album-dialog',
  standalone: true,
  imports: [
    FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatTooltipModule, TranslatePipe, ContextHelpComponent,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="I18N.albums.save_smart | translate">{{ I18N.albums.save_smart | translate }}</h2>
    <mat-dialog-content>
      <mat-form-field class="w-full">
        <mat-label>{{ I18N.albums.name | translate }}</mat-label>
        <input matInput [(ngModel)]="name" maxlength="200" (keydown.enter)="save()" />
      </mat-form-field>
      <app-context-help [label]="I18N.albums.creation.help" [keys]="helpKeys" />
      @if (saveFailed()) {
        <p #saveError role="alert" tabindex="-1" class="rounded-md bg-[var(--mat-sys-error-container)] p-3 text-[var(--mat-sys-on-error-container)]">{{ I18N.albums.save_error | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button [disabled]="!name.trim() || saving()" (click)="save()">
        {{ saving() ? (I18N.ui.buttons.saving | translate) : (I18N.albums.save_smart | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class SaveSmartAlbumDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly helpKeys = [this.I18N.albums.creation.smart];
  private albumService = inject(AlbumService);
  private journal = inject(UserActivityJournal);
  private dialogRef = inject(MatDialogRef<SaveSmartAlbumDialogComponent>);
  private data = inject<{ filterJson: string }>(MAT_DIALOG_DATA);
  // The other album dialogs' stale-session guard: the result of a save that
  // lands after a sign-out or navigation must not touch the store.
  private readonly guard = new AlbumDialogContext(inject(AuthService), inject(Router), inject(DestroyRef));
  private readonly errorElement = viewChild<ElementRef<HTMLElement>>('saveError');
  private readonly injectorRef = inject(Injector);

  name = '';
  readonly saving = signal(false);
  readonly saveFailed = signal(false);

  async save(): Promise<void> {
    if (!this.name.trim() || this.saving() || !this.guard.canStart()) return;
    this.saving.set(true);
    this.saveFailed.set(false);
    try {
      const album = await firstValueFrom(
        this.albumService.create(this.name.trim(), '', true, this.data.filterJson),
      );
      if (!await this.guard.settled()) return;
      this.journal.record('album', [], { album_id: album.id, action: 'create', name: activityName(album.name), is_smart: true });
      this.dialogRef.close(album);
    } catch {
      if (await this.guard.settled()) {
        this.saving.set(false);
        this.saveFailed.set(true);
        afterNextRender(() => this.errorElement()?.nativeElement.focus(), { injector: this.injectorRef });
      }
    }
  }
}
