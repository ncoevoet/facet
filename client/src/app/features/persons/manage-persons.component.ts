import { Component, inject, signal, computed, OnInit, effect, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import {
  MatDialogModule,
  MatDialog,
  MAT_DIALOG_DATA,
  MatDialogRef,
} from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe, FaceThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { PersonCardComponent, Person } from '../../shared/components/person-card/person-card.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { PersonsFiltersService } from './persons-filters.service';
import { I18N } from '../../core/i18n/keys';

interface PersonsResponse {
  persons: Person[];
  total: number;
}

interface PersonFace {
  id: number;
  photo_path: string;
  face_index: number;
}

export interface PersonFacesDialogData {
  personId: number;
  personName: string | null;
}

export interface SplitPersonResult {
  faceIds: number[];
  name: string | null;
}

@Component({
  selector: 'app-merge-target-dialog',
  imports: [MatButtonModule, MatDialogModule, MatIconModule, MatTooltipModule, TranslatePipe, PersonThumbnailUrlPipe],
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="I18N.persons.select_merge_target | translate">{{ I18N.persons.select_merge_target | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm text-gray-400 mb-4">{{ I18N.persons.select_merge_target_desc | translate }}</p>
      <div class="grid grid-cols-3 gap-3">
        @for (person of data.persons; track person.id) {
          <button
            class="flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-colors"
            [class.border-blue-500]="selectedTarget === person.id"
            [class.border-transparent]="selectedTarget !== person.id"
            [class.bg-blue-900/30]="selectedTarget === person.id"
            [class.hover:bg-[var(--mat-sys-surface-container-high)]]="selectedTarget !== person.id"
            (click)="selectedTarget = person.id">
            @if (person.face_thumbnail) {
              <img [src]="person.id | personThumbnailUrl" class="w-16 h-16 rounded-full object-cover" [alt]="person.name || (I18N.persons.unnamed | translate)" />
            } @else {
              <div class="w-16 h-16 rounded-full bg-[var(--mat-sys-surface-container-high)] flex items-center justify-center">
                <mat-icon class="opacity-40">person</mat-icon>
              </div>
            }
            <span class="text-sm truncate w-full text-center">{{ person.name || (I18N.persons.unnamed | translate) }}</span>
            <span class="text-xs opacity-60">{{ I18N.persons.face_count | translate:{ count: person.face_count } }}</span>
          </button>
        }
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">{{ I18N.dialog.cancel | translate }}</button>
      <button mat-flat-button [disabled]="!selectedTarget" (click)="dialogRef.close(selectedTarget)">
        {{ I18N.persons.merge_action | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class MergeTargetDialogComponent {
  protected readonly I18N = I18N;
  data: { persons: Person[] } = inject(MAT_DIALOG_DATA);
  dialogRef = inject(MatDialogRef<MergeTargetDialogComponent>);
  selectedTarget: number | null = null;
}

@Component({
  selector: 'app-new-person-dialog',
  imports: [FormsModule, MatButtonModule, MatDialogModule, MatFormFieldModule, MatInputModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ I18N.manage_persons.new_person_dialog.title | translate }}</h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px]">
      <mat-form-field subscriptSizing="dynamic" class="w-full">
        <mat-label>{{ I18N.manage_persons.new_person_dialog.name_placeholder | translate }}</mat-label>
        <input matInput
               [(ngModel)]="name"
               (keydown.enter)="confirm()"
               cdkFocusInitial />
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">{{ I18N.dialog.cancel | translate }}</button>
      <button mat-flat-button [disabled]="!name.trim()" (click)="confirm()">
        {{ I18N.manage_persons.new_person_dialog.save | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class NewPersonDialogComponent {
  protected readonly I18N = I18N;
  dialogRef = inject(MatDialogRef<NewPersonDialogComponent>);
  name = '';

  confirm(): void {
    const trimmed = this.name.trim();
    if (trimmed) this.dialogRef.close(trimmed);
  }
}

@Component({
  selector: 'app-person-faces-dialog',
  imports: [
    FormsModule,
    MatButtonModule,
    MatDialogModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    TranslatePipe,
    FaceThumbnailUrlPipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="data.personName || (I18N.persons.unnamed | translate)">
      {{ I18N.persons.split_dialog_title | translate }}
    </h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px] min-h-[160px]">
      <p class="text-sm text-gray-400">{{ I18N.persons.split_dialog_desc | translate }}</p>
      @if (loading()) {
        <div class="flex items-center justify-center py-8">
          <mat-spinner diameter="32" />
        </div>
      } @else if (faces().length === 0) {
        <p class="text-sm opacity-60 text-center py-8">{{ I18N.persons.no_faces | translate }}</p>
      } @else {
        <div class="flex flex-wrap gap-2 justify-center">
          @for (face of faces(); track face.id; let i = $index) {
            <button
              class="relative rounded-lg overflow-hidden border-2 transition-colors"
              [class.border-blue-500]="selectedIds().has(face.id)"
              [class.border-transparent]="!selectedIds().has(face.id)"
              [attr.aria-pressed]="selectedIds().has(face.id)"
              [attr.aria-label]="I18N.persons.split_select_face | translate:{ index: i + 1 }"
              (click)="toggle(face.id)">
              <img [src]="face.id | faceThumbnailUrl" alt="" class="w-24 h-24 object-cover" />
              @if (selectedIds().has(face.id)) {
                <span class="absolute top-1 right-1 bg-blue-500 text-white rounded-full flex items-center justify-center w-5 h-5">
                  <mat-icon class="!text-sm !w-4 !h-4 leading-4">check</mat-icon>
                </span>
              }
            </button>
          }
        </div>
        <mat-form-field subscriptSizing="dynamic" class="w-full">
          <mat-label>{{ I18N.persons.split_name_placeholder | translate }}</mat-label>
          <input matInput [(ngModel)]="name" />
        </mat-form-field>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">{{ I18N.dialog.cancel | translate }}</button>
      <button mat-flat-button [disabled]="selectedIds().size === 0" (click)="confirm()">
        <mat-icon>call_split</mat-icon>
        {{ I18N.persons.split_action | translate:{ count: selectedIds().size } }}
      </button>
    </mat-dialog-actions>
  `,
})
export class PersonFacesDialogComponent implements OnInit {
  protected readonly I18N = I18N;
  private readonly api = inject(ApiService);
  readonly data: PersonFacesDialogData = inject(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<PersonFacesDialogComponent, SplitPersonResult>);

  readonly loading = signal(true);
  readonly faces = signal<PersonFace[]>([]);
  readonly selectedIds = signal<Set<number>>(new Set());
  name = '';

  async ngOnInit(): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.get<{ faces: PersonFace[] }>(`/person/${this.data.personId}/faces`),
      );
      this.faces.set(res.faces ?? []);
    } catch {
      // leave empty — the dialog shows the empty state
    } finally {
      this.loading.set(false);
    }
  }

  toggle(faceId: number): void {
    this.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(faceId)) {
        next.delete(faceId);
      } else {
        next.add(faceId);
      }
      return next;
    });
  }

  confirm(): void {
    const faceIds = [...this.selectedIds()];
    if (faceIds.length === 0) return;
    const trimmed = this.name.trim();
    this.dialogRef.close({ faceIds, name: trimmed || null });
  }
}

@Component({
  selector: 'app-manage-persons',
  imports: [
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatSlideToggleModule,
    MatTooltipModule,
    TranslatePipe,
    PersonCardComponent,
    InfiniteScrollDirective,
  ],
  template: `
    <div class="px-4 pt-4 pb-4">
      <!-- Header -->
      <div class="flex flex-wrap items-center justify-start gap-4 mb-3">
        @if (auth.isEdition()) {
          <!-- Small screen: icon-only buttons -->
          <button mat-icon-button class="sm:!hidden" (click)="openNewPersonDialog()"
                  [matTooltip]="I18N.manage_persons.new_person | translate"
                  [attr.aria-label]="I18N.manage_persons.new_person | translate">
            <mat-icon>person_add</mat-icon>
          </button>
          <a mat-icon-button class="sm:!hidden" routerLink="/merge-suggestions"
             [matTooltip]="I18N.persons.merge_suggestions | translate"
             [attr.aria-label]="I18N.persons.merge_suggestions | translate">
            <mat-icon>auto_fix_high</mat-icon>
          </a>
          <!-- Larger screens: full buttons with labels -->
          <button mat-flat-button class="!hidden sm:!inline-flex" (click)="openNewPersonDialog()">
            <mat-icon>person_add</mat-icon>
            {{ I18N.manage_persons.new_person | translate }}
          </button>
          <a mat-flat-button class="!hidden sm:!inline-flex" routerLink="/merge-suggestions">
            <mat-icon>auto_fix_high</mat-icon>
            {{ I18N.persons.merge_suggestions | translate }}
          </a>
          <mat-slide-toggle class="ml-auto" [checked]="showHidden()" (change)="toggleShowHidden($event.checked)">
            {{ I18N.persons.show_hidden | translate }}
          </mat-slide-toggle>
        }
      </div>

      <!-- Loading -->
      @if (loading() && persons().length === 0) {
        <div class="flex justify-center py-16">
          <mat-spinner diameter="48" />
        </div>
      }

      <!-- Needs naming section -->
      @if (auth.isEdition() && needsNaming().length > 0) {
        <div class="mb-6 rounded-xl border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] overflow-hidden">
          <button
            class="flex items-center w-full px-4 py-2 gap-2 text-left hover:bg-[var(--mat-sys-surface-container-high)] transition-colors"
            (click)="needsNamingExpanded.set(!needsNamingExpanded())"
          >
            <mat-icon class="opacity-60">{{ needsNamingExpanded() ? 'expand_more' : 'chevron_right' }}</mat-icon>
            <span class="font-medium">{{ I18N.manage_persons.needs_naming | translate }} ({{ needsNaming().length }})</span>
            <span class="text-xs opacity-60 ml-2">{{ I18N.manage_persons.needs_naming_help | translate }}</span>
          </button>
          @if (needsNamingExpanded()) {
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 p-4">
              @for (p of needsNaming(); track p.id) {
                <app-person-card
                  [person]="p"
                  [isEditing]="true"
                  [canEdit]="true"
                  (editSave)="onNeedsNamingSave($event)"
                  (editCancel)="onNeedsNamingCancel()"
                  (selected)="onViewPhotos($event)"
                  (viewPhotos)="onViewPhotos($event)"
                />
              }
            </div>
          }
        </div>
      }

      <!-- Person grid -->
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
        @for (person of persons(); track person.id) {
          <app-person-card
            [person]="person"
            [isSelected]="selectedIds().has(person.id)"
            [isEditing]="editingId() === person.id"
            [canEdit]="auth.isEdition()"
            (selected)="onPersonSelected($event)"
            (viewPhotos)="onViewPhotos($event)"
            (editStart)="startEdit($event)"
            (editSave)="onEditSave($event)"
            (editCancel)="cancelEdit()"
            (deleted)="onDelete($event)"
            (hidden)="onHide($event)"
            (unhidden)="onUnhide($event)"
            (split)="onSplit($event)"
          />
        }
      </div>

      <!-- Empty state -->
      @if (!loading() && persons().length === 0) {
        <div class="text-center py-16 opacity-50">
          <mat-icon class="!text-5xl !w-12 !h-12 mb-4">people</mat-icon>
          <p>{{ I18N.persons.no_persons | translate }}</p>
        </div>
      }

      <!-- Infinite scroll sentinel -->
      @if (hasMore()) {
        <div appInfiniteScroll (scrollReached)="onScrollReached()" class="flex justify-center py-8">
          <mat-spinner diameter="36" />
        </div>
      }
    </div>

    <!-- Selection action bar (sticky bottom) -->
    @if (auth.isEdition() && selectedIds().size > 0) {
      <div class="fixed bottom-[45px] lg:bottom-0 left-0 right-0 z-50 flex flex-col lg:flex-row items-center justify-center gap-2 lg:gap-3 px-4 lg:px-6 py-2 lg:py-3 bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
        <span class="text-sm font-medium">{{ I18N.gallery.selection.count | translate:{ count: selectedIds().size } }}</span>
        <div class="flex items-center gap-2">
          <button mat-button (click)="clearSelection()">
            <mat-icon>close</mat-icon>
            {{ I18N.persons.clear_selection | translate }}
          </button>
          <button mat-flat-button [disabled]="selectedIds().size < 2" (click)="openMergeDialog()">
            <mat-icon>merge</mat-icon>
            {{ I18N.persons.merge_action | translate }}
          </button>
          <button mat-stroked-button color="warn" (click)="batchDelete()">
            <mat-icon>delete</mat-icon>
            {{ I18N.persons.delete_selected | translate:{ count: selectedIds().size } }}
          </button>
        </div>
      </div>
    }
  `,
})
export class ManagePersonsComponent implements OnInit {
  protected readonly I18N = I18N;
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly personsFilters = inject(PersonsFiltersService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);

  readonly persons = signal<Person[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly editingId = signal<number | null>(null);
  readonly selectedIds = signal<Set<number>>(new Set());
  readonly needsNaming = signal<Person[]>([]);
  readonly needsNamingExpanded = signal(true);
  readonly showHidden = signal(false);

  private page = 1;
  private readonly perPage = 48;
  private initialized = false;

  readonly hasMore = computed(() => this.persons().length < this.total());

  constructor() {
    effect(() => {
      this.personsFilters.sort();
      this.personsFilters.sortDirection();
      this.personsFilters.search();
      if (this.initialized) {
        untracked(() => this.loadPersons(true));
      }
    });
  }

  async ngOnInit(): Promise<void> {
    this.initialized = true;
    await Promise.all([this.loadPersons(true), this.loadNeedsNaming()]);
  }

  async loadNeedsNaming(): Promise<void> {
    if (!this.auth.isEdition()) return;
    try {
      const res = await firstValueFrom(
        this.api.get<{ persons: Person[]; total: number }>('/persons/needs_naming'),
      );
      this.needsNaming.set(res.persons ?? []);
    } catch {
      // silent — the section just won't render
    }
  }

  async onNeedsNamingSave({ id, name }: { id: number; name: string }): Promise<void> {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await firstValueFrom(this.api.post(`/persons/${id}/rename`, { name: trimmed }));
      // Drop the now-named person from the needs-naming section.
      this.needsNaming.update(list => list.filter(p => p.id !== id));
      // Mirror the new name into the main grid if the same person is rendered there.
      this.persons.update(list => list.map(p => p.id === id ? { ...p, name: trimmed } : p));
      this.snackBar.open(this.i18n.t(I18N.persons.renamed), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.rename_error), '', { duration: 3000 });
    }
  }

  onNeedsNamingCancel(): void {
    // Stay in edit mode in this section; cancel just blurs the input (no-op here).
  }

  async openNewPersonDialog(): Promise<void> {
    const ref = this.dialog.open(NewPersonDialogComponent, {
      width: '95vw',
      maxWidth: '420px',
    });
    const name: string | null = await firstValueFrom(ref.afterClosed());
    if (!name) return;
    try {
      const created = await firstValueFrom(
        this.api.post<{ id: number; name: string; face_count: number }>(
          '/persons',
          { name, face_ids: [] },
        ),
      );
      const newPerson: Person = {
        id: created.id,
        name: created.name,
        face_count: created.face_count,
        face_thumbnail: false,
      };
      this.persons.update(list => [newPerson, ...list]);
      this.total.update(t => t + 1);
      this.editingId.set(created.id);
      this.snackBar.open(this.i18n.t(I18N.persons.created), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.create_error), '', { duration: 3000 });
    }
  }

  async loadPersons(reset: boolean): Promise<void> {
    if (reset) {
      this.page = 1;
      this.persons.set([]);
    }
    this.loading.set(true);

    try {
      const sortParam = this.personsFilters.sort() === 'name'
        ? (this.personsFilters.sortDirection() === 'asc' ? 'name_asc' : 'name_desc')
        : (this.personsFilters.sortDirection() === 'asc' ? 'count_asc' : 'count_desc');
      const res = await firstValueFrom(
        this.api.get<PersonsResponse>('/persons', {
          search: this.personsFilters.search(),
          page: this.page,
          per_page: this.perPage,
          sort: sortParam,
          include_hidden: this.showHidden(),
        }),
      );

      if (reset) {
        this.persons.set(res.persons);
      } else {
        this.persons.update((prev) => [...prev, ...res.persons]);
      }
      this.total.set(res.total);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.error_loading), '', { duration: 3000 });
    } finally {
      this.loading.set(false);
    }
  }

  onScrollReached(): void {
    if (this.hasMore() && !this.loading()) {
      this.page++;
      this.loadPersons(false);
    }
  }

  // --- Inline rename ---

  startEdit(personId: number): void {
    this.editingId.set(personId);
  }

  cancelEdit(): void {
    this.editingId.set(null);
  }

  async saveName(person: Person, newName: string): Promise<void> {
    const trimmed = newName.trim();
    if (!trimmed || trimmed === person.name) {
      this.editingId.set(null);
      return;
    }

    try {
      await firstValueFrom(this.api.post(`/persons/${person.id}/rename`, { name: trimmed }));
      this.persons.update((list) =>
        list.map((p) => (p.id === person.id ? { ...p, name: trimmed } : p)),
      );
      this.snackBar.open(this.i18n.t(I18N.persons.renamed), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.rename_error), '', { duration: 3000 });
    } finally {
      this.editingId.set(null);
    }
  }

  // --- Delete ---

  async deletePerson(person: Person): Promise<void> {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.persons.confirm_delete_title),
        message: this.i18n.t(I18N.persons.confirm_delete_message, {
          name: person.name || this.i18n.t(I18N.persons.unnamed),
        }),
      },
    });

    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;

    try {
      await firstValueFrom(this.api.post(`/persons/${person.id}/delete`));
      this.persons.update((list) => list.filter((p) => p.id !== person.id));
      this.total.update((t) => t - 1);
      this.selectedIds.update((s) => {
        const next = new Set(s);
        next.delete(person.id);
        return next;
      });
      this.snackBar.open(this.i18n.t(I18N.persons.deleted), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.delete_error), '', { duration: 3000 });
    }
  }

  // --- Card output handlers ---

  onPersonSelected(id: number): void {
    if (this.auth.isEdition()) {
      this.toggleSelect(id, !this.selectedIds().has(id));
    } else {
      this.router.navigate(['/'], { queryParams: { person_id: String(id) } });
    }
  }

  onViewPhotos(id: number): void {
    this.router.navigate(['/'], { queryParams: { person_id: String(id) } });
  }

  onEditSave({ id, name }: { id: number; name: string }): void {
    const person = this.persons().find((p) => p.id === id);
    if (person) void this.saveName(person, name);
  }

  onDelete(id: number): void {
    const person = this.persons().find((p) => p.id === id);
    if (person) void this.deletePerson(person);
  }

  onHide(id: number): void {
    void this.setHidden(id, true);
  }

  onUnhide(id: number): void {
    void this.setHidden(id, false);
  }

  onSplit(id: number): void {
    const person = this.persons().find((p) => p.id === id);
    if (person) void this.splitPerson(person);
  }

  // --- Show hidden toggle ---

  toggleShowHidden(checked: boolean): void {
    this.showHidden.set(checked);
    void this.loadPersons(true);
  }

  // --- Hide / Unhide ---

  async setHidden(personId: number, hidden: boolean): Promise<void> {
    try {
      await firstValueFrom(
        this.api.post(`/persons/${personId}/${hidden ? 'hide' : 'unhide'}`),
      );
      if (hidden && !this.showHidden()) {
        // Drop the person from the list when hidden persons are not shown.
        this.persons.update((list) => list.filter((p) => p.id !== personId));
        this.total.update((t) => t - 1);
      } else {
        this.persons.update((list) =>
          list.map((p) => (p.id === personId ? { ...p, is_hidden: hidden } : p)),
        );
      }
      this.snackBar.open(
        this.i18n.t(hidden ? 'persons.hidden_done' : 'persons.unhidden_done'),
        '',
        { duration: 2000 },
      );
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.hide_error), '', { duration: 3000 });
    }
  }

  // --- Split ---

  async splitPerson(person: Person): Promise<void> {
    const ref = this.dialog.open(PersonFacesDialogComponent, {
      data: { personId: person.id, personName: person.name } as PersonFacesDialogData,
      width: '95vw',
      maxWidth: '560px',
    });

    const result: SplitPersonResult | null = await firstValueFrom(ref.afterClosed());
    if (!result || result.faceIds.length === 0) return;

    try {
      const res = await firstValueFrom(
        this.api.post<{
          success: boolean;
          new_person_id: number;
          name: string | null;
          new_count: number;
          source_count: number;
        }>(`/persons/${person.id}/split`, {
          face_ids: result.faceIds,
          ...(result.name ? { name: result.name } : {}),
        }),
      );

      const sourceEmptied = res.source_count <= 0;
      this.persons.update((list) => {
        const newPerson: Person = {
          id: res.new_person_id,
          name: res.name ?? result.name,
          face_count: res.new_count,
          face_thumbnail: false,
        };
        const next = list.flatMap((p) => {
          if (p.id !== person.id) return [p];
          // Source person: update its remaining count, or drop it if emptied.
          return sourceEmptied ? [] : [{ ...p, face_count: res.source_count }];
        });
        return [newPerson, ...next];
      });
      // Net change: +1 new person, and -1 source if it was emptied.
      this.total.update((t) => t + (sourceEmptied ? 0 : 1));
      this.snackBar.open(this.i18n.t(I18N.persons.split_done), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.split_error), '', { duration: 3000 });
    }
  }

  // --- Selection ---

  toggleSelect(personId: number, checked: boolean): void {
    this.selectedIds.update((set) => {
      const next = new Set(set);
      if (checked) {
        next.add(personId);
      } else {
        next.delete(personId);
      }
      return next;
    });
  }

  clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  // --- Batch delete ---

  async batchDelete(): Promise<void> {
    const ids = [...this.selectedIds()];
    if (ids.length === 0) return;

    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.persons.confirm_batch_delete_title),
        message: this.i18n.t(I18N.persons.confirm_batch_delete_message, { count: ids.length }),
      },
    });

    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;

    try {
      await firstValueFrom(this.api.post('/persons/delete_batch', { person_ids: ids }));
      this.persons.update((list) => list.filter((p) => !ids.includes(p.id)));
      this.total.update((t) => t - ids.length);
      this.selectedIds.set(new Set());
      this.snackBar.open(this.i18n.t(I18N.persons.batch_deleted, { count: ids.length }), '', {
        duration: 2000,
      });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.delete_error), '', { duration: 3000 });
    }
  }

  // --- Merge via target picker ---

  async openMergeDialog(): Promise<void> {
    const ids = [...this.selectedIds()];
    if (ids.length < 2) return;

    const selectedPersons = this.persons().filter((p) => ids.includes(p.id));
    const ref = this.dialog.open(MergeTargetDialogComponent, {
      data: { persons: selectedPersons },
      width: '95vw',
      maxWidth: '480px',
    });

    const targetId: number | null = await firstValueFrom(ref.afterClosed());
    if (!targetId) return;

    await this.mergeIntoTarget(targetId);
  }

  private async mergeIntoTarget(targetId: number): Promise<void> {
    const sourceIds = [...this.selectedIds()].filter((id) => id !== targetId);
    if (sourceIds.length === 0) return;

    let totalMergedFaces = 0;
    try {
      for (const sourceId of sourceIds) {
        const sourcePerson = this.persons().find((p) => p.id === sourceId);
        totalMergedFaces += sourcePerson?.face_count ?? 0;
        await firstValueFrom(
          this.api.post('/persons/merge', { source_id: sourceId, target_id: targetId }),
        );
      }

      this.persons.update((list) =>
        list
          .filter((p) => !sourceIds.includes(p.id))
          .map((p) =>
            p.id === targetId ? { ...p, face_count: p.face_count + totalMergedFaces } : p,
          ),
      );
      this.total.update((t) => t - sourceIds.length);
      this.selectedIds.set(new Set());
      this.snackBar.open(this.i18n.t(I18N.persons.merged), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.merge_error), '', { duration: 3000 });
    }
  }
}
