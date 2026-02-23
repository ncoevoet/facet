import { Component, input, output, viewChild, ElementRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';

export interface Person {
  id: number;
  name: string | null;
  face_count: number;
  face_thumbnail: boolean;
}

@Component({
  selector: 'app-person-card',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatCheckboxModule,
    MatTooltipModule,
    TranslatePipe,
    PersonThumbnailUrlPipe,
  ],
  template: `
    <mat-card
      class="!overflow-hidden cursor-pointer transition-shadow hover:shadow-lg"
      [class.!ring-2]="isSelected()"
      [class.!ring-blue-500]="isSelected()"
      (click)="selected.emit(person().id)"
    >
      <!-- Avatar -->
      <div class="relative aspect-square bg-neutral-800 overflow-hidden">
        @if (person().face_thumbnail) {
          <img
            [src]="person().id | personThumbnailUrl"
            [alt]="person().name ?? ''"
            class="absolute inset-0 w-full h-full object-cover"
            loading="lazy"
          />
        } @else {
          <div class="w-full h-full flex items-center justify-center">
            <mat-icon class="!text-5xl !w-12 !h-12 opacity-30">person</mat-icon>
          </div>
        }
      </div>

      <mat-card-content class="!px-3 !pt-2 !pb-1">
        <div class="flex items-start gap-2">
          <!-- Checkbox -->
          @if (canEdit()) {
            <mat-checkbox
              class="shrink-0 -ml-1.5 -mt-0.5"
              [checked]="isSelected()"
              (change)="selected.emit(person().id)"
              (click)="$event.stopPropagation()"
            />
          }
          <!-- Name & count -->
          <div class="min-w-0 flex-1">
            @if (isEditing()) {
              <div class="flex items-center gap-1" (click)="$event.stopPropagation()">
                <input
                  #nameInput
                  class="flex-1 bg-transparent border-b border-current outline-none text-sm py-0.5"
                  [value]="person().name ?? ''"
                  (keyup.enter)="onSave()"
                  (keyup.escape)="editCancel.emit()"
                />
                <button mat-icon-button class="!w-7 !h-7" [matTooltip]="'dialog.confirm' | translate" (click)="onSave()">
                  <mat-icon class="!text-base">check</mat-icon>
                </button>
                <button mat-icon-button class="!w-7 !h-7" [matTooltip]="'dialog.cancel' | translate" (click)="editCancel.emit()">
                  <mat-icon class="!text-base">close</mat-icon>
                </button>
              </div>
            } @else {
              <p class="text-sm font-medium truncate">
                {{ person().name || ('persons.unnamed' | translate) }}
              </p>
            }
            <p class="text-xs opacity-60 mt-0.5">
              {{ 'persons.face_count' | translate:{ count: person().face_count } }}
            </p>
          </div>
        </div>
      </mat-card-content>

      <!-- Actions -->
      @if (canEdit() && !isEditing()) {
        <mat-card-actions class="!px-2 !pb-2 !pt-0" (click)="$event.stopPropagation()">
          <button mat-icon-button [matTooltip]="'persons.rename' | translate" (click)="editStart.emit(person().id)">
            <mat-icon class="!text-lg">edit</mat-icon>
          </button>
          <a
            mat-icon-button
            [routerLink]="'/person/' + person().id"
            [matTooltip]="'persons.view_photos' | translate"
          >
            <mat-icon class="!text-lg">photo_library</mat-icon>
          </a>
          <button mat-icon-button [matTooltip]="'persons.share_link' | translate" (click)="share.emit(person().id)">
            <mat-icon class="!text-lg">link</mat-icon>
          </button>
          <button mat-icon-button [matTooltip]="'persons.delete' | translate" (click)="deleted.emit(person().id)">
            <mat-icon class="!text-lg">delete</mat-icon>
          </button>
        </mat-card-actions>
      }
    </mat-card>
  `,
})
export class PersonCardComponent {
  readonly person = input.required<Person>();
  readonly isSelected = input(false);
  readonly isEditing = input(false);
  readonly canEdit = input(false);

  readonly nameInput = viewChild<ElementRef<HTMLInputElement>>('nameInput');

  readonly selected = output<number>();
  readonly editStart = output<number>();
  readonly editSave = output<{ id: number; name: string }>();
  readonly editCancel = output<void>();
  readonly share = output<number>();
  readonly deleted = output<number>();

  onSave(): void {
    const value = this.nameInput()?.nativeElement.value ?? '';
    this.editSave.emit({ id: this.person().id, name: value });
  }
}
