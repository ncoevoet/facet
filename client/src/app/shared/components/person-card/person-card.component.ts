import { Component, input, output, signal, viewChild, ElementRef, ChangeDetectionStrategy } from '@angular/core';
import { MatAutocompleteModule, MatAutocompleteTrigger } from '@angular/material/autocomplete';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { PersonNameSuggestionsComponent } from '../person-name-suggestions/person-name-suggestions.component';
import { EnterPickGuard } from '../../utils/enter-pick-guard';
import { PersonNameOption } from '../../utils/person-name';

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
    MatAutocompleteModule,
    PersonNameSuggestionsComponent,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <mat-card
      class="group !overflow-hidden cursor-pointer transition-shadow hover:shadow-lg"
      [class.!ring-2]="isSelected()"
      [class.!ring-blue-500]="isSelected()"
      [class.opacity-50]="person().is_hidden"
      role="button"
      tabindex="0"
      [attr.aria-label]="person().name || ('persons.unnamed' | translate)"
      (click)="selected.emit(person().id)"
      (dblclick)="viewPhotos.emit(person().id)"
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
          <span class="text-white text-xs font-medium truncate">{{ person().name || ('persons.unnamed' | translate) }}</span>
          @if (person().is_hidden) {
            <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-white/80 shrink-0" [matTooltip]="'persons.hidden' | translate">visibility_off</mat-icon>
          }
        </div>
        <!-- Photo/face count badge (top-right) -->
        <span class="absolute top-1.5 right-1.5 z-10 px-2 py-0.5 rounded-full bg-black/60 text-white text-xs font-semibold leading-none"
              [matTooltip]="'persons.face_count' | translate:{ count: person().face_count }"
              [attr.aria-label]="'persons.face_count' | translate:{ count: person().face_count }">
          {{ person().face_count }}
        </span>
        <!-- While the name line is open the action row is not shown, so the card's
             actions sit on the avatar: view photos, find more, ignore. -->
        @if (canEdit() && isEditing() && !restoreOnly()) {
          <div class="absolute bottom-1.5 right-1.5 z-10 flex gap-1" role="presentation" (keydown)="$event.stopPropagation()" (dblclick)="$event.stopPropagation()">
            <button
              class="w-8 h-8 rounded-full bg-black/60 hover:bg-black/80 transition-colors text-white inline-flex items-center justify-center cursor-pointer"
              [matTooltip]="'persons.view_photos' | translate"
              [attr.aria-label]="'persons.view_photos' | translate"
              (click)="viewPhotos.emit(person().id); $event.stopPropagation()">
              <mat-icon class="!text-lg !w-5 !h-5 !leading-5">photo_library</mat-icon>
            </button>
            <button
              class="w-8 h-8 rounded-full bg-black/60 hover:bg-black/80 transition-colors text-white inline-flex items-center justify-center cursor-pointer"
              [matTooltip]="'persons.find_more' | translate"
              [attr.aria-label]="'persons.find_more' | translate"
              (click)="findMore.emit(person().id); $event.stopPropagation()">
              <mat-icon class="!text-lg !w-5 !h-5 !leading-5">person_search</mat-icon>
            </button>
            <button
              class="w-8 h-8 rounded-full bg-black/60 hover:bg-black/80 transition-colors text-white inline-flex items-center justify-center cursor-pointer"
              [matTooltip]="'persons.hide' | translate"
              [attr.aria-label]="'persons.hide' | translate"
              (click)="hidden.emit(person().id); $event.stopPropagation()">
              <mat-icon class="!text-lg !w-5 !h-5 !leading-5">block</mat-icon>
            </button>
          </div>
        }
      </div>

      <mat-card-content class="!px-3 !pt-2 !pb-2">
        <div class="flex items-center gap-1">
          <!-- Checkbox: not while the name line is open, where it is no use and its
               focus halo sat beside the input. -->
          @if (canEdit() && !isEditing()) {
            <mat-checkbox
              class="shrink-0 -ml-1.5"
              [checked]="isSelected()"
              (change)="selected.emit(person().id)"
              (click)="$event.stopPropagation()"
              (dblclick)="$event.stopPropagation()"
            />
          }
          <!-- Name & count -->
          <div class="min-w-0 flex-1">
            @if (isEditing()) {
              <div class="flex flex-wrap items-center justify-end gap-1 outline-none"
                   role="presentation"
                   tabindex="-1"
                   (click)="$event.stopPropagation()"
                   (keydown)="$event.stopPropagation()"
                   (dblclick)="$event.stopPropagation()">
                <input
                  #nameInput
                  class="min-w-24 flex-1 h-7 bg-transparent border-0 border-b-2 border-[var(--mat-sys-outline-variant)] focus:border-[var(--mat-sys-primary)] !outline-none focus-visible:!outline-none text-sm"
                  [value]="person().name ?? ''"
                  [matAutocomplete]="suggestions.panel"
                  autocomplete="off"
                  (input)="draft.set($any($event.target).value)"
                  (keydown.enter)="onEnterDown()"
                  (keyup.enter)="onEnterUp()"
                  (keyup.escape)="editCancel.emit()"
                  [attr.aria-label]="'persons.rename' | translate"
                />
                <app-person-name-suggestions #suggestions [options]="nameOptions()" [query]="draft()" />
                <button mat-icon-button class="!w-7 !h-7 !p-0 !inline-flex items-center justify-center shrink-0" [matTooltip]="'dialog.confirm' | translate" [attr.aria-label]="'dialog.confirm' | translate" (click)="onSave()">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">check</mat-icon>
                </button>
                <button mat-icon-button class="!w-7 !h-7 !p-0 !inline-flex items-center justify-center shrink-0" [matTooltip]="'dialog.cancel' | translate" [attr.aria-label]="'dialog.cancel' | translate" (click)="editCancel.emit()">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">close</mat-icon>
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
                 (keydown)="$event.stopPropagation()"
                 (dblclick)="$event.stopPropagation()">
              @if (!restoreOnly()) {
                <button mat-icon-button [matTooltip]="'persons.rename' | translate" [attr.aria-label]="'persons.rename' | translate" (click)="editStart.emit(person().id)">
                  <mat-icon class="opacity-60">edit</mat-icon>
                </button>
              }
              <button mat-icon-button [matTooltip]="'persons.view_photos' | translate" [attr.aria-label]="'persons.view_photos' | translate" (click)="viewPhotos.emit(person().id)">
                <mat-icon class="opacity-60">photo_library</mat-icon>
              </button>
              @if (!restoreOnly()) {
                <button mat-icon-button [matTooltip]="'persons.split' | translate" [attr.aria-label]="'persons.split' | translate" (click)="split.emit(person().id)">
                  <mat-icon class="opacity-60">call_split</mat-icon>
                </button>
                <button mat-icon-button [matTooltip]="'persons.find_more' | translate" [attr.aria-label]="'persons.find_more' | translate" (click)="findMore.emit(person().id)">
                  <mat-icon class="opacity-60">person_search</mat-icon>
                </button>
              }
              @if (person().is_hidden) {
                <button mat-icon-button [matTooltip]="'persons.unhide' | translate" [attr.aria-label]="'persons.unhide' | translate" (click)="unhidden.emit(person().id)">
                  <mat-icon class="opacity-60">visibility</mat-icon>
                </button>
              } @else {
                <button mat-icon-button [matTooltip]="'persons.hide' | translate" [attr.aria-label]="'persons.hide' | translate" (click)="hidden.emit(person().id)">
                  <mat-icon class="opacity-60">visibility_off</mat-icon>
                </button>
              }
              <button mat-icon-button [matTooltip]="'persons.delete' | translate" [attr.aria-label]="'persons.delete' | translate" (click)="deleted.emit(person().id)">
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
  readonly person = input.required<Person>();
  readonly isSelected = input(false);
  readonly isEditing = input(false);
  readonly canEdit = input(false);
  /** Only view photos, restore and delete: the Ignored section, where renaming or splitting makes no sense. */
  readonly restoreOnly = input(false);
  /** Existing names offered while typing one (with each person's face and photo count). */
  readonly nameOptions = input<readonly PersonNameOption[]>([]);

  readonly nameInput = viewChild<ElementRef<HTMLInputElement>>('nameInput');
  private readonly autocomplete = viewChild(MatAutocompleteTrigger);
  /** What is typed in the name line, which filters the suggestions. */
  protected readonly draft = signal('');
  /** Keeps an Enter keydown that picked a suggestion from also saving on its keyup. */
  private readonly enterGuard = new EnterPickGuard();

  readonly selected = output<number>();
  readonly viewPhotos = output<number>();
  readonly editStart = output<number>();
  readonly editSave = output<{ id: number; name: string }>();
  readonly editCancel = output<void>();
  readonly deleted = output<number>();
  readonly hidden = output<number>();
  readonly unhidden = output<number>();
  readonly split = output<number>();
  readonly findMore = output<number>();

  protected onEnterDown(): void {
    this.enterGuard.down(this.autocomplete());
  }

  protected onEnterUp(): void {
    if (this.enterGuard.up()) this.onSave();
  }

  onSave(): void {
    const value = this.nameInput()?.nativeElement.value ?? '';
    this.editSave.emit({ id: this.person().id, name: value });
  }
}
