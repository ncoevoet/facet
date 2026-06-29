import { Component, input, output, viewChild, ElementRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { I18N } from '../../../core/i18n/keys';

export interface Person {
  id: number;
  name: string | null;
  face_count: number;
  face_thumbnail: boolean;
  is_hidden?: boolean;
}

@Component({
  selector: 'app-person-card',
  standalone: true,
  imports: [
    FormsModule,
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
      class="group !overflow-hidden cursor-pointer transition-shadow hover:shadow-lg"
      [class.!ring-2]="isSelected()"
      [class.!ring-blue-500]="isSelected()"
      [class.opacity-50]="person().is_hidden"
      role="button"
      tabindex="0"
      [attr.aria-label]="person().name || (I18N.persons.unnamed | translate)"
      (click)="selected.emit(person().id)"
      (keydown.enter)="selected.emit(person().id)"
      (keydown.space)="selected.emit(person().id); $event.preventDefault()"
    >
      <!-- Avatar -->
      <div class="relative aspect-[4/3] bg-[var(--mat-sys-surface-container)] overflow-hidden">
        @if (person().face_thumbnail) {
          <img
            [src]="person().id | personThumbnailUrl"
            [alt]="person().name ?? ''"
            class="absolute inset-0 w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            loading="lazy"
          />
        } @else {
          <div class="w-full h-full flex items-center justify-center">
            <mat-icon class="!text-5xl !w-12 !h-12 opacity-30">person</mat-icon>
          </div>
        }
        <!-- Name overlay (top-left over a darkened gradient, gallery-card style) -->
        <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
          <span class="text-white text-xs font-medium truncate">{{ person().name || (I18N.persons.unnamed | translate) }}</span>
          @if (person().is_hidden) {
            <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-white/80 shrink-0" [matTooltip]="I18N.persons.hidden | translate">visibility_off</mat-icon>
          }
        </div>
        <!-- Photo/face count badge (top-right) -->
        <span class="absolute top-1.5 right-1.5 z-10 px-2 py-0.5 rounded-full bg-black/60 text-white text-xs font-semibold leading-none"
              [matTooltip]="I18N.persons.face_count | translate:{ count: person().face_count }"
              [attr.aria-label]="I18N.persons.face_count | translate:{ count: person().face_count }">
          {{ person().face_count }}
        </span>
      </div>

      <mat-card-content class="!px-3 !pt-2 !pb-2">
        <div class="flex items-center gap-1">
          <!-- Checkbox -->
          @if (canEdit()) {
            <mat-checkbox
              class="shrink-0 -ml-1.5"
              [checked]="isSelected()"
              (change)="selected.emit(person().id)"
              (click)="$event.stopPropagation()"
            />
          }
          <!-- Name & count -->
          <div class="min-w-0 flex-1">
            @if (isEditing()) {
              <div class="flex items-center gap-1"
                   role="presentation"
                   tabindex="-1"
                   (click)="$event.stopPropagation()"
                   (keydown)="$event.stopPropagation()">
                <input
                  #nameInput
                  class="flex-1 bg-transparent border-b border-current outline-none text-sm py-0.5"
                  [value]="person().name ?? ''"
                  (keyup.enter)="onSave()"
                  (keyup.escape)="editCancel.emit()"
                  [attr.aria-label]="I18N.persons.rename | translate"
                />
                <button mat-icon-button class="!w-7 !h-7" [matTooltip]="I18N.dialog.confirm | translate" (click)="onSave()">
                  <mat-icon class="!text-base">check</mat-icon>
                </button>
                <button mat-icon-button class="!w-7 !h-7" [matTooltip]="I18N.dialog.cancel | translate" (click)="editCancel.emit()">
                  <mat-icon class="!text-base">close</mat-icon>
                </button>
              </div>
            }
            <!-- Name + count now render as overlays on the avatar (top-left / top-right). -->
          </div>
          <!-- Actions (inline, right side) -->
          @if (canEdit() && !isEditing()) {
            <div class="flex items-center shrink-0"
                 role="presentation"
                 tabindex="-1"
                 (click)="$event.stopPropagation()"
                 (keydown)="$event.stopPropagation()">
              <button mat-icon-button [matTooltip]="I18N.persons.rename | translate" (click)="editStart.emit(person().id)">
                <mat-icon class="opacity-60">edit</mat-icon>
              </button>
              <button mat-icon-button [matTooltip]="I18N.persons.view_photos | translate" (click)="viewPhotos.emit(person().id)">
                <mat-icon class="opacity-60">photo_library</mat-icon>
              </button>
              <button mat-icon-button [matTooltip]="I18N.persons.split | translate" [attr.aria-label]="I18N.persons.split | translate" (click)="split.emit(person().id)">
                <mat-icon class="opacity-60">call_split</mat-icon>
              </button>
              @if (person().is_hidden) {
                <button mat-icon-button [matTooltip]="I18N.persons.unhide | translate" [attr.aria-label]="I18N.persons.unhide | translate" (click)="unhidden.emit(person().id)">
                  <mat-icon class="opacity-60">visibility</mat-icon>
                </button>
              } @else {
                <button mat-icon-button [matTooltip]="I18N.persons.hide | translate" [attr.aria-label]="I18N.persons.hide | translate" (click)="hidden.emit(person().id)">
                  <mat-icon class="opacity-60">visibility_off</mat-icon>
                </button>
              }
              <button mat-icon-button [matTooltip]="I18N.persons.delete | translate" (click)="deleted.emit(person().id)">
                <mat-icon class="opacity-60">delete</mat-icon>
              </button>
            </div>
          }
        </div>
      </mat-card-content>
    </mat-card>
  `,
})
export class PersonCardComponent {
  protected readonly I18N = I18N;
  readonly person = input.required<Person>();
  readonly isSelected = input(false);
  readonly isEditing = input(false);
  readonly canEdit = input(false);

  readonly nameInput = viewChild<ElementRef<HTMLInputElement>>('nameInput');

  readonly selected = output<number>();
  readonly viewPhotos = output<number>();
  readonly editStart = output<number>();
  readonly editSave = output<{ id: number; name: string }>();
  readonly editCancel = output<void>();
  readonly deleted = output<number>();
  readonly hidden = output<number>();
  readonly unhidden = output<number>();
  readonly split = output<number>();

  onSave(): void {
    const value = this.nameInput()?.nativeElement.value ?? '';
    this.editSave.emit({ id: this.person().id, name: value });
  }
}
