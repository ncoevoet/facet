import { Component, inject, signal, computed, OnInit, OnDestroy, ElementRef, viewChild, effect } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink, Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import {
  MatDialogModule,
  MatDialog,
  MAT_DIALOG_DATA,
  MatDialogRef,
} from '@angular/material/dialog';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

export interface Person {
  id: number;
  name: string | null;
  face_count: number;
  face_thumbnail: boolean;
}

interface PersonsResponse {
  persons: Person[];
  total: number;
}

@Component({
  selector: 'app-confirm-dialog',
  imports: [MatButtonModule, MatDialogModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content>
      <p>{{ data.message }}</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(false)">
        {{ data.cancelLabel ?? ('dialog.cancel' | translate) }}
      </button>
      <button mat-flat-button color="warn" (click)="dialogRef.close(true)">
        {{ data.confirmLabel ?? ('dialog.confirm' | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class ConfirmDialogComponent {
  data: { title: string; message: string; cancelLabel?: string; confirmLabel?: string } =
    inject(MAT_DIALOG_DATA);
  dialogRef = inject(MatDialogRef<ConfirmDialogComponent>);
}

@Component({
  selector: 'app-merge-target-dialog',
  imports: [MatButtonModule, MatDialogModule, MatIconModule, TranslatePipe, PersonThumbnailUrlPipe],
  template: `
    <h2 mat-dialog-title>{{ 'persons.select_merge_target' | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm text-gray-400 mb-4">{{ 'persons.select_merge_target_desc' | translate }}</p>
      <div class="grid grid-cols-3 gap-3">
        @for (person of data.persons; track person.id) {
          <button
            class="flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-colors"
            [class.border-blue-500]="selectedTarget === person.id"
            [class.border-transparent]="selectedTarget !== person.id"
            [class.bg-blue-900/30]="selectedTarget === person.id"
            [class.hover:bg-neutral-800]="selectedTarget !== person.id"
            (click)="selectedTarget = person.id">
            @if (person.face_thumbnail) {
              <img [src]="person.id | personThumbnailUrl" class="w-16 h-16 rounded-full object-cover" alt="" />
            } @else {
              <div class="w-16 h-16 rounded-full bg-neutral-700 flex items-center justify-center">
                <mat-icon class="opacity-40">person</mat-icon>
              </div>
            }
            <span class="text-sm truncate w-full text-center">{{ person.name || ('persons.unnamed' | translate) }}</span>
            <span class="text-xs opacity-60">{{ 'persons.face_count' | translate:{ count: person.face_count } }}</span>
          </button>
        }
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">{{ 'dialog.cancel' | translate }}</button>
      <button mat-flat-button [disabled]="!selectedTarget" (click)="dialogRef.close(selectedTarget)">
        {{ 'persons.merge_action' | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class MergeTargetDialogComponent {
  data: { persons: Person[] } = inject(MAT_DIALOG_DATA);
  dialogRef = inject(MatDialogRef<MergeTargetDialogComponent>);
  selectedTarget: number | null = null;
}

@Component({
  selector: 'app-manage-persons',
  imports: [
    FormsModule,
    RouterLink,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatCheckboxModule,
    MatDialogModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatTooltipModule,
    TranslatePipe,
    PersonThumbnailUrlPipe,
  ],
  template: `
    <div class="p-4 md:p-6 max-w-screen-2xl mx-auto">
      <!-- Header -->
      <div class="flex flex-wrap items-center gap-4 mb-6">
        <h1 class="text-2xl font-medium">{{ 'persons.manage_title' | translate }}</h1>
        <div class="flex-1"></div>
        @if (auth.isEdition()) {
          <a mat-button routerLink="/merge-suggestions">
            <mat-icon>auto_fix_high</mat-icon>
            {{ 'persons.merge_suggestions' | translate }}
          </a>
        }
      </div>

      <!-- Search bar -->
      <div class="flex flex-wrap items-center gap-3 mb-3">
        <mat-form-field class="flex-1 min-w-48" subscriptSizing="dynamic">
          <mat-icon matPrefix>search</mat-icon>
          <input
            matInput
            [placeholder]="'persons.search_placeholder' | translate"
            [(ngModel)]="searchQuery"
            (ngModelChange)="onSearchChange()"
          />
          @if (searchQuery) {
            <button matSuffix mat-icon-button (click)="clearSearch()">
              <mat-icon>close</mat-icon>
            </button>
          }
        </mat-form-field>
      </div>

      <!-- Loading -->
      @if (loading() && persons().length === 0) {
        <div class="flex justify-center py-16">
          <mat-spinner diameter="48" />
        </div>
      }

      <!-- Person grid -->
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
        @for (person of persons(); track person.id) {
          <mat-card
            class="!overflow-hidden cursor-pointer transition-shadow hover:shadow-lg"
            [class.!ring-2]="selectedIds().has(person.id)"
            [class.!ring-blue-500]="selectedIds().has(person.id)"
            (click)="onPersonClick(person)"
          >
            <!-- Avatar -->
            <div class="relative aspect-square bg-neutral-800 overflow-hidden">
              @if (person.face_thumbnail) {
                <img
                  [src]="person.id | personThumbnailUrl"
                  [alt]="person.name ?? ''"
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
                @if (auth.isEdition()) {
                  <mat-checkbox
                    class="shrink-0 -ml-1.5 -mt-0.5"
                    [checked]="selectedIds().has(person.id)"
                    (change)="toggleSelect(person.id, $event.checked)"
                    (click)="$event.stopPropagation()"
                  />
                }
                <!-- Name & count -->
                <div class="min-w-0 flex-1">
                  @if (editingId() === person.id) {
                    <div class="flex items-center gap-1" (click)="$event.stopPropagation()">
                      <input
                        #nameInput
                        class="flex-1 bg-transparent border-b border-current outline-none text-sm py-0.5"
                        [value]="person.name ?? ''"
                        (keyup.enter)="saveName(person, nameInput.value)"
                        (keyup.escape)="cancelEdit()"
                      />
                      <button mat-icon-button class="!w-7 !h-7" [matTooltip]="'dialog.confirm' | translate" (click)="saveName(person, nameInput.value)">
                        <mat-icon class="!text-base">check</mat-icon>
                      </button>
                      <button mat-icon-button class="!w-7 !h-7" [matTooltip]="'dialog.cancel' | translate" (click)="cancelEdit()">
                        <mat-icon class="!text-base">close</mat-icon>
                      </button>
                    </div>
                  } @else {
                    <p class="text-sm font-medium truncate">
                      {{ person.name || ('persons.unnamed' | translate) }}
                    </p>
                  }
                  <p class="text-xs opacity-60 mt-0.5">
                    {{ 'persons.face_count' | translate:{ count: person.face_count } }}
                  </p>
                </div>
              </div>
            </mat-card-content>

            <!-- Actions -->
            @if (auth.isEdition() && editingId() !== person.id) {
              <mat-card-actions class="!px-2 !pb-2 !pt-0" (click)="$event.stopPropagation()">
                <button mat-icon-button [matTooltip]="'persons.rename' | translate" (click)="startEdit(person.id)">
                  <mat-icon class="!text-lg">edit</mat-icon>
                </button>
                <a
                  mat-icon-button
                  [routerLink]="'/person/' + person.id"
                  [matTooltip]="'persons.view_photos' | translate"
                >
                  <mat-icon class="!text-lg">photo_library</mat-icon>
                </a>
                <button mat-icon-button [matTooltip]="'persons.share_link' | translate" (click)="copyShareLink(person)">
                  <mat-icon class="!text-lg">link</mat-icon>
                </button>
                <button mat-icon-button [matTooltip]="'persons.delete' | translate" (click)="deletePerson(person)">
                  <mat-icon class="!text-lg">delete</mat-icon>
                </button>
              </mat-card-actions>
            }
          </mat-card>
        }
      </div>

      <!-- Empty state -->
      @if (!loading() && persons().length === 0) {
        <div class="text-center py-16 opacity-50">
          <mat-icon class="!text-5xl !w-12 !h-12 mb-4">people</mat-icon>
          <p>{{ 'persons.no_persons' | translate }}</p>
        </div>
      }

      <!-- Infinite scroll sentinel -->
      @if (hasMore()) {
        <div #scrollSentinel class="flex justify-center py-8">
          <mat-spinner diameter="36" />
        </div>
      }
    </div>

    <!-- Selection action bar (sticky bottom) -->
    @if (auth.isEdition() && selectedIds().size > 0) {
      <div class="fixed bottom-14 lg:bottom-0 left-0 right-0 z-50 flex flex-col lg:flex-row items-center justify-center gap-2 lg:gap-3 px-4 lg:px-6 py-2 lg:py-3 bg-[var(--mat-sys-surface-container-high)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
        <span class="text-sm font-medium">{{ 'gallery.selection.count' | translate:{ count: selectedIds().size } }}</span>
        <div class="flex items-center gap-2">
          <button mat-button (click)="clearSelection()">
            <mat-icon>close</mat-icon>
            {{ 'persons.clear_selection' | translate }}
          </button>
          <button mat-flat-button [disabled]="selectedIds().size < 2" (click)="openMergeDialog()">
            <mat-icon>merge</mat-icon>
            {{ 'persons.merge_action' | translate }}
          </button>
          <button mat-stroked-button color="warn" (click)="batchDelete()">
            <mat-icon>delete</mat-icon>
            {{ 'persons.delete_selected' | translate:{ count: selectedIds().size } }}
          </button>
        </div>
      </div>
    }
  `,
})
export class ManagePersonsComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);

  readonly scrollSentinel = viewChild<ElementRef>('scrollSentinel');

  readonly persons = signal<Person[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly editingId = signal<number | null>(null);
  readonly selectedIds = signal<Set<number>>(new Set());

  searchQuery = '';
  private page = 1;
  private readonly perPage = 48;
  private searchTimeout: ReturnType<typeof setTimeout> | null = null;
  private observer: IntersectionObserver | null = null;

  readonly hasMore = computed(() => this.persons().length < this.total());

  constructor() {
    effect(() => {
      const el = this.scrollSentinel()?.nativeElement;
      if (!el) return;
      this.observer?.disconnect();
      const scrollRoot = el.closest('main') ?? null;
      this.observer = new IntersectionObserver(
        (entries) => {
          if (entries[0]?.isIntersecting && this.hasMore() && !this.loading()) {
            this.loadMore();
          }
        },
        { root: scrollRoot, rootMargin: '200px' },
      );
      this.observer.observe(el);
    });
  }

  async ngOnInit(): Promise<void> {
    await this.loadPersons(true);
  }

  ngOnDestroy(): void {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.observer?.disconnect();
  }

  onSearchChange(): void {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    this.searchTimeout = setTimeout(() => this.loadPersons(true), 300);
  }

  clearSearch(): void {
    this.searchQuery = '';
    this.loadPersons(true);
  }

  async loadPersons(reset: boolean): Promise<void> {
    if (reset) {
      this.page = 1;
      this.persons.set([]);
    }
    this.loading.set(true);

    try {
      const res = await firstValueFrom(
        this.api.get<PersonsResponse>('/persons', {
          search: this.searchQuery,
          page: this.page,
          per_page: this.perPage,
        }),
      );

      if (reset) {
        this.persons.set(res.persons);
      } else {
        this.persons.update((prev) => [...prev, ...res.persons]);
      }
      this.total.set(res.total);
    } catch {
      this.snackBar.open(this.i18n.t('persons.error_loading'), '', { duration: 3000 });
    } finally {
      this.loading.set(false);
    }
  }

  loadMore(): void {
    this.page++;
    this.loadPersons(false);
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
      this.snackBar.open(this.i18n.t('persons.renamed'), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t('persons.rename_error'), '', { duration: 3000 });
    } finally {
      this.editingId.set(null);
    }
  }

  // --- Delete ---

  async deletePerson(person: Person): Promise<void> {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t('persons.confirm_delete_title'),
        message: this.i18n.t('persons.confirm_delete_message', {
          name: person.name || this.i18n.t('persons.unnamed'),
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
      this.snackBar.open(this.i18n.t('persons.deleted'), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t('persons.delete_error'), '', { duration: 3000 });
    }
  }

  onPersonClick(person: Person): void {
    if (this.auth.isEdition()) {
      this.toggleSelect(person.id, !this.selectedIds().has(person.id));
    } else {
      this.router.navigate(['/'], { queryParams: { person_id: String(person.id) } });
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

  // --- Share link ---

  async copyShareLink(person: Person): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.get<{ token: string }>(`/auth/person/${person.id}/share-token`),
      );
      const url = `${window.location.origin}/person/${person.id}?token=${res.token}`;
      await navigator.clipboard.writeText(url);
      this.snackBar.open(this.i18n.t('persons.link_copied'), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t('persons.link_copy_error'), '', { duration: 3000 });
    }
  }

  // --- Batch delete ---

  async batchDelete(): Promise<void> {
    const ids = [...this.selectedIds()];
    if (ids.length === 0) return;

    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t('persons.confirm_batch_delete_title'),
        message: this.i18n.t('persons.confirm_batch_delete_message', { count: ids.length }),
      },
    });

    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;

    try {
      await firstValueFrom(this.api.post('/persons/delete_batch', { person_ids: ids }));
      this.persons.update((list) => list.filter((p) => !ids.includes(p.id)));
      this.total.update((t) => t - ids.length);
      this.selectedIds.set(new Set());
      this.snackBar.open(this.i18n.t('persons.batch_deleted', { count: ids.length }), '', {
        duration: 2000,
      });
    } catch {
      this.snackBar.open(this.i18n.t('persons.delete_error'), '', { duration: 3000 });
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

      // Remove sources, update target face count
      this.persons.update((list) =>
        list
          .filter((p) => !sourceIds.includes(p.id))
          .map((p) =>
            p.id === targetId ? { ...p, face_count: p.face_count + totalMergedFaces } : p,
          ),
      );
      this.total.update((t) => t - sourceIds.length);
      this.selectedIds.set(new Set());
      this.snackBar.open(this.i18n.t('persons.merged'), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t('persons.merge_error'), '', { duration: 3000 });
    }
  }
}
