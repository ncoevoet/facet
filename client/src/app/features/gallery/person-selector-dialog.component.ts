import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { PersonOption } from './gallery.store';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Component({
  selector: 'app-person-selector-dialog',
  imports: [
    FormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    PersonThumbnailUrlPipe,
    TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title>{{ 'manage_persons.assign_face' | translate }}</h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px]">
      <mat-form-field subscriptSizing="dynamic" class="w-full">
        <mat-icon matPrefix>search</mat-icon>
        <input matInput
               [placeholder]="'manage_persons.search_persons' | translate"
               [(ngModel)]="searchQuery"
               (input)="filter()" />
      </mat-form-field>

      @if (filtered().length) {
        <div class="flex flex-col gap-1 max-h-[360px] overflow-y-auto">
          @for (person of filtered(); track person.id) {
            <button
              class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--mat-sys-surface-container-high)] transition-colors text-left w-full"
              (click)="dialogRef.close(person)"
            >
              <img [src]="person.id | personThumbnailUrl"
                   class="w-14 h-14 rounded-full object-cover border border-neutral-700" />
              <div class="flex flex-col min-w-0">
                <span class="text-base font-medium truncate">{{ person.name }}</span>
                <span class="text-xs text-neutral-500">{{ 'gallery.photo_count' | translate:{ count: person.face_count } }}</span>
              </div>
            </button>
          }
        </div>
      } @else {
        <p class="text-sm text-neutral-500 text-center py-4">{{ 'manage_persons.no_named_persons' | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">{{ 'dialog.cancel' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class PersonSelectorDialogComponent {
  readonly data: PersonOption[] = inject(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<PersonSelectorDialogComponent>);

  searchQuery = '';
  readonly filtered = signal<PersonOption[]>([]);

  constructor() {
    this.filtered.set(this.data);
  }

  filter(): void {
    const q = this.searchQuery.toLowerCase();
    this.filtered.set(
      q ? this.data.filter(p => p.name?.toLowerCase().includes(q)) : this.data,
    );
  }
}
