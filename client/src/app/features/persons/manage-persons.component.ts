import { Component, inject, signal, computed, OnInit, effect, untracked, DestroyRef, viewChild, TemplateRef, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { NgTemplateOutlet } from '@angular/common';
import { MatTabsModule } from '@angular/material/tabs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import {
  MatDialogModule,
  MatDialog,
  MAT_DIALOG_DATA,
  MatDialogRef,
} from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe, FaceThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { PersonCardComponent, Person } from '../../shared/components/person-card/person-card.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { PersonsFiltersService } from './persons-filters.service';
import {
  FindMoreFacesDialogComponent,
  FindMoreFacesDialogData,
  FindMoreFacesResult,
} from './find-more-faces-dialog.component';
import { RenamePersonResponse, SameNamePerson, SameNameMergeService } from './same-name-merge.service';
import { PersonHideService } from './person-hide.service';
import { PersonNameOption, personNameOptions } from '../../shared/utils/person-name';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';
import { onPageQuery } from '../../shared/utils/page-query';
import { registerPageContext } from '../../core/agent/page-context.service';
import { UserActivityJournal, activityName } from '../../core/agent/user-activity-journal.service';
import { GalleryStore } from '../gallery/gallery.store';
import { I18N, i18nKeys } from '../../core/i18n/keys';

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
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="I18N.persons.select_merge_target | translate">{{ I18N.persons.select_merge_target | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm text-gray-400 mb-4">{{ I18N.persons.select_merge_target_desc | translate }}</p>
      <div class="grid grid-cols-3 gap-3">
        @for (person of data.persons; track person.id) {
          <button
            class="flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-colors cursor-pointer"
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
  protected readonly I18N = i18nKeys();
  data: { persons: Person[] } = inject(MAT_DIALOG_DATA);
  dialogRef = inject(MatDialogRef<MergeTargetDialogComponent>);
  selectedTarget: number | null = null;
}

@Component({
  selector: 'app-new-person-dialog',
  imports: [FormsModule, MatButtonModule, MatDialogModule, MatFormFieldModule, MatInputModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
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
  protected readonly I18N = i18nKeys();
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
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="data.personName || (I18N.persons.unnamed | translate)">
      {{ I18N.persons.split_dialog_title | translate }}
    </h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px] min-h-[160px]">
      <p class="text-sm text-gray-400">{{ I18N.persons.split_dialog_desc | translate }}</p>
      @if (loading()) {
        <div class="flex items-center justify-center py-8">
          <mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      } @else if (faces().length === 0) {
        <p class="text-sm opacity-60 text-center py-8">{{ I18N.persons.no_faces | translate }}</p>
      } @else {
        <div class="flex flex-wrap gap-2 justify-center">
          @for (face of faces(); track face.id; let i = $index) {
            <button
              class="relative rounded-lg overflow-hidden border-2 transition-colors cursor-pointer"
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
  protected readonly I18N = i18nKeys();
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

/** The /persons tabs, as written in ``?tab=``. */
export type PersonsTab = 'named' | 'naming';
/** Orders the Needs naming tab offers; a name sort means nothing on unnamed persons. */
export type NamingSort = 'faces' | 'recent';

@Component({
  selector: 'app-manage-persons',
  imports: [
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatTooltipModule,
    TranslatePipe,
    PersonCardComponent,
    InfiniteScrollDirective,
    RouterLink,
    MatTabsModule,
    NgTemplateOutlet,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <ng-template #personsToolbar>
      @if (namingTabActive()) {
        <mat-form-field class="!hidden lg:!inline-flex w-44 ml-2" subscriptSizing="dynamic">
          <mat-label>{{ I18N.gallery.sort | translate }}</mat-label>
          <mat-select data-naming-sort [value]="namingSort()" (selectionChange)="namingSort.set($event.value)">
            <mat-option value="faces">{{ I18N.persons.sort_faces | translate }}</mat-option>
            <mat-option value="recent">{{ I18N.persons.sort_recent | translate }}</mat-option>
          </mat-select>
        </mat-form-field>
        <button
          class="!hidden lg:!inline-flex"
          mat-icon-button
          data-naming-sort-direction
          (click)="namingSortDirection.set(namingSortDirection() === 'desc' ? 'asc' : 'desc')"
          [matTooltip]="namingSortDirection() === 'desc' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)"
          [attr.aria-label]="namingSortDirection() === 'desc' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)"
        >
          <mat-icon>{{ namingSortDirection() === 'desc' ? 'arrow_downward' : 'arrow_upward' }}</mat-icon>
        </button>
      } @else {
        <mat-form-field class="!hidden lg:!inline-flex w-52 ml-2" subscriptSizing="dynamic">
          <mat-label>{{ I18N.persons.search_placeholder | translate }}</mat-label>
          <input matInput [value]="personsFilters.search()" (input)="personsFilters.search.set($any($event.target).value)" />
          <mat-icon matPrefix class="opacity-60">search</mat-icon>
          @if (personsFilters.search()) {
            <button matSuffix mat-icon-button (click)="personsFilters.search.set('')" [attr.aria-label]="I18N.persons.clear_search | translate">
              <mat-icon>close</mat-icon>
            </button>
          }
        </mat-form-field>
        <mat-form-field class="!hidden lg:!inline-flex w-44" subscriptSizing="dynamic">
          <mat-label>{{ I18N.gallery.sort | translate }}</mat-label>
          <mat-select [value]="personsFilters.sort()" (selectionChange)="onPersonsSortChange($event.value)">
            <mat-option value="count">{{ I18N.persons.sort_count | translate }}</mat-option>
            <mat-option value="name">{{ I18N.persons.sort_name | translate }}</mat-option>
          </mat-select>
        </mat-form-field>
        <button
          class="!hidden lg:!inline-flex"
          mat-icon-button
          (click)="togglePersonsSortDirection()"
          [matTooltip]="personsFilters.sortDirection() === 'desc' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)"
          [attr.aria-label]="personsFilters.sortDirection() === 'desc' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)"
        >
          <mat-icon>{{ personsFilters.sortDirection() === 'desc' ? 'arrow_downward' : 'arrow_upward' }}</mat-icon>
        </button>
      }
      @if (auth.isEdition()) {
        <button mat-icon-button class="!hidden lg:!inline-flex" [matTooltip]="I18N.manage_persons.new_person | translate" [attr.aria-label]="I18N.manage_persons.new_person | translate" (click)="personsFilters.createRequested.set(personsFilters.createRequested() + 1)">
          <mat-icon>person_add</mat-icon>
        </button>
        @if (store.config()?.features?.show_merge_suggestions) {
          <a mat-icon-button class="!hidden lg:!inline-flex" routerLink="/merge-suggestions" [matTooltip]="I18N.persons.merge_suggestions | translate" [attr.aria-label]="I18N.persons.merge_suggestions | translate">
            <mat-icon>auto_fix_high</mat-icon>
          </a>
        }
        <button
          class="!hidden lg:!inline-flex"
          mat-icon-button
          [class.!text-[var(--mat-sys-primary)]]="personsFilters.showHidden()"
          [attr.aria-pressed]="personsFilters.showHidden()"
          [matTooltip]="I18N.persons.show_hidden | translate"
          [attr.aria-label]="I18N.persons.show_hidden | translate"
          (click)="personsFilters.showHidden.set(!personsFilters.showHidden())"
        >
          <mat-icon>{{ personsFilters.showHidden() ? 'visibility' : 'visibility_off' }}</mat-icon>
        </button>
      }
    </ng-template>

    <ng-template #namedPane>
      <!-- Loading -->
      @if (loading() && persons().length === 0) {
        <div class="flex justify-center py-16">
          <mat-spinner diameter="48" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      }

      <!-- Person grid -->
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
        @for (person of persons(); track person.id) {
          <app-person-card
            [person]="person"
            [nameOptions]="nameOptions()"
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
            (findMore)="onFindMore($event)"
          />
        }
      </div>

      <!-- Empty state -->
      @if (!loading() && persons().length === 0) {
        <div class="text-center py-16 opacity-50 max-w-md mx-auto">
          <mat-icon class="!text-5xl !w-12 !h-12 mb-4">people</mat-icon>
          <p>{{ I18N.persons.no_persons | translate }}</p>
          <p class="text-sm mt-3 opacity-80">{{ I18N.persons.empty_hint | translate }}</p>
        </div>
      }

      <!-- Infinite scroll sentinel -->
      @if (hasMore()) {
        <div appInfiniteScroll (scrollReached)="onScrollReached()" class="flex justify-center py-8">
          <mat-spinner diameter="36" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      }
      <!-- Ignored: hidden persons (staff, strangers), with Restore -->
      @if (auth.isEdition() && ignored().length > 0) {
        <div class="mt-6 rounded-xl border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] overflow-hidden">
          <button
            class="flex items-center w-full px-4 py-2 gap-2 text-left hover:bg-[var(--mat-sys-surface-container-high)] transition-colors cursor-pointer"
            [attr.aria-expanded]="ignoredExpanded()"
            (click)="ignoredExpanded.set(!ignoredExpanded())"
          >
            <mat-icon class="opacity-60">{{ ignoredExpanded() ? 'expand_more' : 'chevron_right' }}</mat-icon>
            <span class="font-medium flex-1" [matTooltip]="I18N.persons.ignored_help | translate">{{ I18N.persons.ignored_section | translate }} ({{ ignoredTotal() }})</span>
          </button>
          @if (ignoredExpanded()) {
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 p-4">
              @for (p of ignored(); track p.id) {
                <app-person-card
                  [person]="p"
                  [canEdit]="true"
                  [restoreOnly]="true"
                  (viewPhotos)="onViewPhotos($event)"
                  (unhidden)="onUnhide($event)"
                  (deleted)="onDelete($event)"
                />
              }
            </div>
            @if (ignored().length < ignoredTotal()) {
              <div class="flex items-center justify-center gap-3 px-4 pb-4 text-sm">
                <span class="opacity-70">{{ I18N.persons.ignored_shown_of | translate:{ shown: ignored().length, total: ignoredTotal() } }}</span>
                <button mat-button [disabled]="ignoredLoading()" (click)="loadMoreIgnored()">{{ I18N.persons.load_more | translate }}</button>
              </div>
            }
          }
        </div>
      }

    </ng-template>

    <div class="px-4 pt-4 pb-4">
      @if (auth.isEdition()) {
        <mat-tab-group mat-stretch-tabs="false" mat-align-tabs="start" animationDuration="0ms"
                       [selectedIndex]="tab() === 'naming' ? 1 : 0" (selectedIndexChange)="selectTab($event === 1 ? 'naming' : 'named')">
          <mat-tab>
            <ng-template mat-tab-label>
              <span data-tab="named">{{ I18N.manage_persons.named | translate }} ({{ total() }})</span>
            </ng-template>
            <div class="pt-4">
              <ng-container [ngTemplateOutlet]="namedPane" />
            </div>
          </mat-tab>
          <mat-tab>
            <ng-template mat-tab-label>
              <span data-tab="naming" [matTooltip]="I18N.manage_persons.needs_naming_help | translate">{{ I18N.manage_persons.needs_naming | translate }} ({{ needsNaming().length }})</span>
            </ng-template>
            <div class="pt-4">
              @if (needsNamingSorted().length > 0) {
                <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
                  @for (p of needsNamingSorted(); track p.id) {
                    <app-person-card
                      [person]="p"
                      [isEditing]="true"
                      [canEdit]="true"
                      [nameOptions]="nameOptions()"
                      (editSave)="onNeedsNamingSave($event)"
                      (findMore)="onFindMore($event)"
                      (editCancel)="onNeedsNamingCancel()"
                      (viewPhotos)="onViewPhotos($event)"
                      (hidden)="onHide($event)"
                    />
                  }
                </div>
              } @else {
                <div data-needs-naming-empty class="text-center py-16 opacity-60 max-w-md mx-auto">
                  <mat-icon class="!text-5xl !w-12 !h-12 mb-4">how_to_reg</mat-icon>
                  <p>{{ I18N.manage_persons.needs_naming_empty | translate }}</p>
                </div>
              }
            </div>
          </mat-tab>
        </mat-tab-group>
      } @else {
        <ng-container [ngTemplateOutlet]="namedPane" />
      }
    </div>

    <!-- Selection action bar (sticky bottom) -->
    @if (auth.isEdition() && selectedIds().size > 0) {
      <div class="fixed bottom-0 left-0 right-0 z-50 flex flex-col lg:flex-row items-center justify-center gap-2 lg:gap-3 px-4 lg:px-6 py-2 lg:py-3 max-lg:pb-[max(0.5rem,env(safe-area-inset-bottom))] bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
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
  protected readonly I18N = i18nKeys();
  readonly auth = inject(AuthService);
  protected readonly store = inject(GalleryStore);
  private readonly api = inject(ApiService);
  private readonly journal = inject(UserActivityJournal);
  private readonly i18n = inject(I18nService);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly router = inject(Router);
  protected readonly personsFilters = inject(PersonsFiltersService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private readonly sameNameMerge = inject(SameNameMergeService);
  private readonly faceBoxes = inject(PersonFaceBoxesService);
  private readonly hide = inject(PersonHideService);
  private readonly personsToolbar = viewChild<TemplateRef<unknown>>('personsToolbar');

  readonly persons = signal<Person[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly editingId = signal<number | null>(null);
  readonly selectedIds = this.personsFilters.selectedIds;
  readonly needsNaming = signal<Person[]>([]);
  /** Existing names offered while typing a name (see loadNameOptions). */
  readonly nameOptions = signal<PersonNameOption[]>([]);
  /** Needs naming's own sort, applied locally to the fully loaded list: its rows carry only face counts and ids. */
  readonly namingSort = signal<NamingSort>('faces');
  readonly namingSortDirection = signal<'asc' | 'desc'>('desc');
  /** Needs naming in the toolbar's order: by face count, or newest group first (the highest id). */
  readonly needsNamingSorted = computed(() => {
    const key = this.namingSort();
    const dir = this.namingSortDirection() === 'desc' ? -1 : 1;
    return [...this.needsNaming()].sort((a, b) =>
      dir * (key === 'faces' ? a.face_count - b.face_count || a.id - b.id : a.id - b.id));
  });
  /** The toolbar acts on Needs naming while that tab is shown to an edition user. */
  readonly namingTabActive = computed(() => this.auth.isEdition() && this.tab() === 'naming');

  /** The selected tab, mirrored in ``?tab=``; Named unless the URL asks for Needs naming. */
  readonly tab = signal<PersonsTab>(
    inject(ActivatedRoute).snapshot.queryParamMap.get('tab') === 'naming' ? 'naming' : 'named');
  /** Hidden persons, shown in the Ignored section (collapsed by default). */
  readonly ignored = signal<Person[]>([]);
  /** Every hidden person, from the response; the section loads them a page at a time. */
  readonly ignoredTotal = signal(0);
  readonly ignoredLoading = signal(false);
  readonly ignoredExpanded = signal(false);
  private ignoredPage = 1;
  private readonly ignoredPerPage = 200;

  private page = 1;
  private readonly perPage = 48;
  private initialized = false;

  readonly hasMore = computed(() => this.persons().length < this.total());

  constructor() {
    registerPageContext('persons', () => ({
      search: this.personsFilters.search(),
      sort: this.personsFilters.sort(),
      sort_direction: this.personsFilters.sortDirection(),
      show_hidden: this.personsFilters.showHidden(),
    }));
    // The assistant's `list_persons show=true` sends the search every time: the page takes exactly that query.
    onPageQuery('/persons', ['search'], query => {
      const search = query.get('search');
      if (search === null) return;
      this.personsFilters.search.set(search);
      this.personsFilters.showHidden.set(false);
      this.personsFilters.sort.set('count');
      this.personsFilters.sortDirection.set('desc');
    });
    inject(DestroyRef).onDestroy(() => {
      this.pageHelp.setDescription(null);
      this.clearSelection();
      const t = this.personsToolbar();
      if (t) this.headerSlot.clear(t);
    });
    effect(() => {
      const t = this.personsToolbar();
      if (t) this.headerSlot.set(t);
    });
    effect(() => {
      this.personsFilters.sort();
      this.personsFilters.sortDirection();
      this.personsFilters.search();
      this.personsFilters.showHidden();
      // Locking or unlocking edition shows or hides Needs naming, which decides
      // whether the grid lists unnamed persons too.
      this.auth.isEdition();
      if (this.initialized) {
        untracked(() => this.loadPersons(true));
      }
    });
    // Unlocking edition after the page opened shows Needs naming and Ignored, which
    // read-only users never load.
    let wasEdition = this.auth.isEdition();
    effect(() => {
      const edition = this.auth.isEdition();
      if (edition && !wasEdition && this.initialized) {
        untracked(() => void Promise.all([this.loadNeedsNaming(), this.loadIgnored()]));
      }
      wasEdition = edition;
    });
    // Open the new-person dialog when the shell's add button increments the counter
    const initialCreate = this.personsFilters.createRequested();
    effect(() => {
      if (this.personsFilters.createRequested() !== initialCreate) {
        untracked(() => this.openNewPersonDialog());
      }
    });
  }

  async ngOnInit(): Promise<void> {
    this.pageHelp.setDescription(I18N.persons.help);
    this.initialized = true;
    await Promise.all([this.loadPersons(true), this.loadNeedsNaming(), this.loadNameOptions(), this.loadIgnored()]);
  }

  /** Switch tabs and keep the choice in the URL, so a reload or Back returns to it. */
  selectTab(tab: PersonsTab): void {
    if (tab === this.tab()) return;
    this.tab.set(tab);
    void this.router.navigate([], { queryParams: { tab }, queryParamsHandling: 'merge', replaceUrl: true });
  }

  onPersonsSortChange(sort: string): void {
    this.personsFilters.sort.set(sort);
  }

  togglePersonsSortDirection(): void {
    this.personsFilters.sortDirection.update(d => d === 'desc' ? 'asc' : 'desc');
  }

  /** The Ignored section's first page; read-only users never see the section, so it is not asked for. */
  async loadIgnored(): Promise<void> {
    if (!this.auth.isEdition()) return;
    this.ignoredPage = 1;
    await this.fetchIgnored(false);
  }

  async loadMoreIgnored(): Promise<void> {
    if (this.ignoredLoading() || this.ignored().length >= this.ignoredTotal()) return;
    this.ignoredPage++;
    await this.fetchIgnored(true);
  }

  private async fetchIgnored(append: boolean): Promise<void> {
    this.ignoredLoading.set(true);
    try {
      const res = await firstValueFrom(
        this.api.get<PersonsResponse>('/persons', {
          hidden_only: true, page: this.ignoredPage, per_page: this.ignoredPerPage, sort: 'count_desc',
        }),
      );
      const page = res.persons ?? [];
      this.ignored.update((list) => (append ? [...list, ...page.filter((p) => !list.some((q) => q.id === p.id))] : page));
      this.ignoredTotal.set(res.total ?? page.length);
    } catch {
      // silent: the section just won't render
      if (append) this.ignoredPage--;
    } finally {
      this.ignoredLoading.set(false);
    }
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
    const faceCount = this.needsNaming().find(p => p.id === id)?.face_count ?? 0;
    let res: RenamePersonResponse;
    try {
      res = await firstValueFrom(this.api.post<RenamePersonResponse>(`/persons/${id}/rename`, { name: trimmed }));
      this.journal.record('person', [], { action: 'rename', person_id: id, name: activityName(trimmed) });
      // Drop the now-named person from the needs-naming section.
      this.needsNaming.update(list => list.filter(p => p.id !== id));
      // Mirror the new name into the main grid if the same person is rendered there.
      this.persons.update(list => list.map(p => p.id === id ? { ...p, name: trimmed } : p));
      this.snackBar.open(this.i18n.t(I18N.persons.renamed), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.rename_error), '', { duration: 3000 });
      return;
    }
    // The newly named person moves from Needs naming into the named-only grid;
    // an attempted merge has reloaded the grid itself, a declined one has not.
    const reloaded = await this.offerSameNameMerge(id, faceCount, trimmed, res.same_name_persons ?? []);
    if (!reloaded) await this.loadPersons(true);
  }

  /**
   * Every distinct person name, for the name line's suggestions. Read from the
   * filter options (all persons, not just the loaded page); names that fold to the
   * same key are offered once, as the person with the most photos.
   */
  async loadNameOptions(): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.get<{ persons: [number, string | null, number][] }>('/filter_options/persons'),
      );
      this.nameOptions.set(personNameOptions(res.persons ?? []));
    } catch {
      // keep the previous suggestions
    }
  }

  /**
   * After a rename, offer to merge the persons already carrying the name (see
   * SameNameMergeService: the user picks which). Returns true when a merge was
   * attempted, which reloads the grid, Needs naming and the suggestions; otherwise
   * (no namesake, or declined) only the suggestions are refreshed, so the caller
   * still owns the grid.
   */
  async offerSameNameMerge(
    personId: number,
    faceCount: number,
    name: string,
    sameName: SameNamePerson[],
  ): Promise<boolean> {
    if (sameName.length > 0) {
      const result = await this.sameNameMerge.offer({ id: personId, face_count: faceCount }, name, sameName);
      if (result.status === 'merged') {
        this.journal.record('person', [], mergeActivity(
          result.merges.length, result.merges.map(m => [m.source_id, m.target_id]), false));
      }
      if (result.status !== 'declined') {
        await Promise.all([this.loadPersons(true), this.loadNeedsNaming(), this.loadNameOptions()]);
        return true;
      }
    }
    await this.loadNameOptions();
    return false;
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
      this.journal.record('person', [], { action: 'create', person_id: created.id, name: activityName(created.name) });
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

  /**
   * While Needs naming is on screen (edition mode) it lists every unnamed person,
   * so the grid shows named persons only. Showing hidden persons lists everyone,
   * so a hidden unnamed cluster can still be found and unhidden.
   */
  namedOnly(): boolean {
    return this.auth.isEdition() && !this.personsFilters.showHidden();
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
          include_hidden: this.personsFilters.showHidden(),
          named_only: this.namedOnly(),
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

    let res: RenamePersonResponse;
    try {
      res = await firstValueFrom(this.api.post<RenamePersonResponse>(`/persons/${person.id}/rename`, { name: trimmed }));
      this.journal.record('person', [], { action: 'rename', person_id: person.id, name: activityName(trimmed) });
      this.persons.update((list) =>
        list.map((p) => (p.id === person.id ? { ...p, name: trimmed } : p)),
      );
      this.snackBar.open(this.i18n.t(I18N.persons.renamed), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.rename_error), '', { duration: 3000 });
      return;
    } finally {
      this.editingId.set(null);
    }
    await this.offerSameNameMerge(person.id, person.face_count, trimmed, res.same_name_persons ?? []);
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
      this.journal.record('person', [], { action: 'delete', person_id: person.id });
      const inGrid = this.persons().some((p) => p.id === person.id);
      this.persons.update((list) => list.filter((p) => p.id !== person.id));
      if (this.ignored().some((p) => p.id === person.id)) {
        this.ignored.update((list) => list.filter((p) => p.id !== person.id));
        this.ignoredTotal.update((t) => Math.max(0, t - 1));
      }
      if (inGrid) this.total.update((t) => t - 1);
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
    const person = this.persons().find((p) => p.id === id) ?? this.ignored().find((p) => p.id === id);
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

  onFindMore(id: number): void {
    // Needs-naming cards are not necessarily on the loaded page of the main grid.
    const person = this.persons().find((p) => p.id === id) ?? this.needsNaming().find((p) => p.id === id);
    if (person) void this.findMoreFaces(person);
  }

  // --- Find more faces ---

  async findMoreFaces(person: Person): Promise<void> {
    const ref = this.dialog.open(FindMoreFacesDialogComponent, {
      data: { personId: person.id, personName: person.name } as FindMoreFacesDialogData,
      width: '95vw',
      maxWidth: '720px',
    });

    const result: FindMoreFacesResult | undefined = await firstValueFrom(ref.afterClosed());
    if (!result || result.added <= 0) return;

    this.journal.record('person', [], { action: 'find_more', person_id: person.id, count: result.added });
    this.snackBar.open(this.i18n.t(I18N.persons.find_more_added, { count: result.added }), '', { duration: 2000 });
    // Faces may have come from other persons, emptying (and deleting) them: reload rather than patch.
    await Promise.all([this.loadPersons(true), this.loadNeedsNaming()]);
  }

  // --- Hide / Unhide ---

  async setHidden(personId: number, hidden: boolean): Promise<void> {
    const known = this.persons().find((p) => p.id === personId) ?? this.needsNaming().find((p) => p.id === personId);
    // Reload instead of restoring a snapshot on Undo: anything done since the ignore stays.
    const stored = await this.hide.setHidden(personId, hidden,
      async () => { await Promise.all([this.loadPersons(true), this.loadNeedsNaming(), this.loadIgnored()]); });
    if (!stored) return;
    // Ignoring moves a person out of Needs naming and into Ignored; restoring
    // moves it back, to whichever list its name decides. Ignored is patched in
    // place so the pages already loaded there stay loaded.
    if (hidden) {
      this.needsNaming.update((list) => list.filter((p) => p.id !== personId));
      if (known) this.addIgnored({ ...known, is_hidden: true });
    } else {
      if (this.ignored().some((p) => p.id === personId)) {
        this.ignored.update((list) => list.filter((p) => p.id !== personId));
        this.ignoredTotal.update((t) => Math.max(0, t - 1));
      }
      void this.loadNeedsNaming();
    }
    if (hidden && !this.personsFilters.showHidden()) {
      // Drop the person from the list when hidden persons are not shown; one only
      // in Needs naming was never counted in the grid's total (the Named tab count).
      if (this.persons().some((p) => p.id === personId)) this.total.update((t) => t - 1);
      this.persons.update((list) => list.filter((p) => p.id !== personId));
    } else if (!hidden && !this.persons().some((p) => p.id === personId)) {
      // A restored person the grid does not hold comes back into it, and its count.
      void this.loadPersons(true);
    } else {
      this.persons.update((list) =>
        list.map((p) => (p.id === personId ? { ...p, is_hidden: hidden } : p)),
      );
    }
  }

  /**
   * Put a newly ignored person into the loaded Ignored rows at its ``count_desc``
   * place. When it sorts past the last loaded row while more remain, only the total
   * grows: the next page will bring it.
   */
  private addIgnored(person: Person): void {
    if (this.ignored().some((p) => p.id === person.id)) return;
    const list = this.ignored();
    const at = list.findIndex((p) => p.face_count < person.face_count);
    const complete = list.length >= this.ignoredTotal();
    this.ignoredTotal.update((t) => t + 1);
    if (at === -1 && !complete) return;
    this.ignored.set(at === -1 ? [...list, person] : [...list.slice(0, at), person, ...list.slice(at)]);
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

      this.journal.record('person', [], { action: 'split', person_id: person.id, count: result.faceIds.length });
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
      this.journal.record('person', [], { action: 'delete', count: ids.length });
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
    let merged = 0;
    try {
      for (const sourceId of sourceIds) {
        const sourcePerson = this.persons().find((p) => p.id === sourceId);
        totalMergedFaces += sourcePerson?.face_count ?? 0;
        await firstValueFrom(
          this.api.post('/persons/merge', { source_id: sourceId, target_id: targetId }),
        );
        merged += 1;
      }
      this.faceBoxes.clear();
      this.journal.record('person', [], mergeActivity(merged, sourceIds.length === 1 ? [[sourceIds[0], targetId]] : null, false));

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
      if (merged > 0) {
        this.faceBoxes.clear();
        this.journal.record('person', [], mergeActivity(merged, null, true));
      }
      this.snackBar.open(this.i18n.t(I18N.persons.merge_error), '', { duration: 3000 });
    }
  }
}

/** A merge entry: `pairs` only for a single merge, `count` always, `partial` when a later one failed. */
function mergeActivity(count: number, pairs: number[][] | null, partial: boolean): Record<string, unknown> {
  return { action: 'merge', count, ...(pairs ? { pairs } : {}), ...(partial ? { partial: true } : {}) };
}
