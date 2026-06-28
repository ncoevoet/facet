import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { PersonOption } from './gallery.store';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

@Component({
  selector: 'app-person-selector-dialog',
  imports: [
    FormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatTooltipModule,
    PersonThumbnailUrlPipe,
    TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="I18N.manage_persons.assign_face | translate">{{ I18N.manage_persons.assign_face | translate }}</h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px]">
      @if (creating()) {
        <mat-form-field subscriptSizing="dynamic" class="w-full">
          <mat-label>{{ I18N.manage_persons.new_person_dialog.name_placeholder | translate }}</mat-label>
          <input matInput
                 [(ngModel)]="newName"
                 (keydown.enter)="confirmCreate()"
                 cdkFocusInitial />
        </mat-form-field>
        <div class="flex gap-2 justify-end">
          <button mat-button (click)="cancelCreate()">{{ I18N.dialog.cancel | translate }}</button>
          <button mat-flat-button [disabled]="!newName.trim()" (click)="confirmCreate()">
            {{ I18N.manage_persons.new_person_dialog.save | translate }}
          </button>
        </div>
      } @else {
        <mat-form-field subscriptSizing="dynamic" class="w-full">
          <mat-label>{{ I18N.manage_persons.search_persons | translate }}</mat-label>
          <mat-icon matPrefix>search</mat-icon>
          <input matInput
                 [placeholder]="I18N.manage_persons.search_persons | translate"
                 [(ngModel)]="searchQuery"
                 (input)="filter()" />
        </mat-form-field>

        <div class="flex flex-col gap-1 max-h-[360px] overflow-y-auto">
          <button
            class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--mat-sys-surface-container-high)] transition-colors text-left w-full border border-dashed border-neutral-600"
            (click)="startCreate()"
          >
            <div class="w-14 h-14 rounded-full bg-[var(--mat-sys-surface-container-high)] flex items-center justify-center">
              <mat-icon>person_add</mat-icon>
            </div>
            <div class="flex flex-col min-w-0">
              <span class="text-base font-medium">{{ I18N.person_selector.create_new | translate }}</span>
            </div>
          </button>

          @for (person of filtered(); track person.id) {
            <button
              class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--mat-sys-surface-container-high)] transition-colors text-left w-full"
              (click)="dialogRef.close({ kind: 'select', person })"
            >
              <img [src]="person.id | personThumbnailUrl"
                   [alt]="person.name"
                   class="w-14 h-14 rounded-full object-cover border border-neutral-700" />
              <div class="flex flex-col min-w-0">
                <span class="text-base font-medium truncate">{{ person.name }}</span>
                <span class="text-xs text-neutral-500">{{ I18N.gallery.photo_count | translate:{ count: person.face_count } }}</span>
              </div>
            </button>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">{{ I18N.dialog.cancel | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class PersonSelectorDialogComponent {
  protected readonly I18N = I18N;
  readonly data: PersonOption[] = inject(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<PersonSelectorDialogComponent>);

  searchQuery = '';
  newName = '';
  readonly filtered = signal<PersonOption[]>([]);
  readonly creating = signal(false);

  constructor() {
    this.filtered.set(this.data);
  }

  filter(): void {
    const q = this.searchQuery.toLowerCase();
    this.filtered.set(
      q ? this.data.filter(p => p.name?.toLowerCase().includes(q)) : this.data,
    );
  }

  startCreate(): void {
    this.newName = this.searchQuery.trim();
    this.creating.set(true);
  }

  cancelCreate(): void {
    this.creating.set(false);
    this.newName = '';
  }

  confirmCreate(): void {
    const name = this.newName.trim();
    if (!name) return;
    this.dialogRef.close({ kind: 'create', name });
  }
}
