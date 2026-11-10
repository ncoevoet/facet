import { Component, DestroyRef, effect, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { PersonOption } from './gallery.store';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../core/i18n/keys';
import { AuthService } from '../../core/services/auth.service';
import { PersonAssignmentHistoryService } from '../../core/services/person-assignment-history.service';
import { ApiService } from '../../core/services/api.service';
import { firstValueFrom } from 'rxjs';
import type { components } from '../../core/api/schema';

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
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2
      mat-dialog-title
      class="truncate"
      [matTooltip]="I18N.manage_persons.assign_face | translate"
    >
      {{ I18N.manage_persons.assign_face | translate }}
    </h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px]">
      @if (creating()) {
        <mat-form-field subscriptSizing="dynamic" class="w-full">
          <mat-label>{{
            I18N.manage_persons.new_person_dialog.name_placeholder | translate
          }}</mat-label>
          <input matInput [(ngModel)]="newName" (keydown.enter)="confirmCreate()" cdkFocusInitial />
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
          <input
            matInput
            [placeholder]="I18N.manage_persons.search_persons | translate"
            aria-describedby="person-assignment-ordering-hint"
            [(ngModel)]="searchQuery"
            (input)="filter()"
          />
        </mat-form-field>

        <p id="person-assignment-ordering-hint" class="text-xs text-neutral-500">{{ I18N.person_selector.ordering_hint | translate }}</p>
        <div class="flex flex-col gap-1 max-h-[360px] overflow-y-auto">
          @if (allowCreate) {
          <button
            class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--mat-sys-surface-container-high)] transition-colors text-left w-full border border-dashed border-neutral-600 cursor-pointer"
            (click)="startCreate()"
          >
            <div
              class="w-14 h-14 rounded-full bg-[var(--mat-sys-surface-container-high)] flex items-center justify-center"
            >
              <mat-icon>person_add</mat-icon>
            </div>
            <div class="flex flex-col min-w-0">
              <span class="text-base font-medium">{{
                I18N.person_selector.create_new | translate
              }}</span>
            </div>
          </button>

          }
          @if (loading()) {
            <p role="status">{{ I18N.ui.labels.loading | translate }}</p>
          }
          @if (failed()) {
            <p role="alert">{{ I18N.notifications.connection_error | translate }}</p>
            <button mat-button (click)="retry()" [disabled]="loading()">
              {{ I18N.gallery.load_error.retry | translate }}
            </button>
          }
          @for (person of filtered(); track person.id) {
            <button
              class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--mat-sys-surface-container-high)] transition-colors text-left w-full cursor-pointer"
              (click)="dialogRef.close({ kind: 'select', person })"
            >
              <img
                [src]="person.id | personThumbnailUrl"
                [alt]="person.name"
                class="w-14 h-14 rounded-full object-cover border border-neutral-700"
              />
              <div class="flex flex-col min-w-0">
                <span class="text-base font-medium truncate">{{ person.name }}</span>
                <span class="text-xs text-neutral-500">{{
                  (person.face_count === 1 ? I18N.person_selector.face_count_one : I18N.person_selector.face_count) | translate: { count: person.face_count }
                }}</span>
              </div>
            </button>
          }
          @if (hasMore()) {
            <button mat-button (click)="loadMore()" [disabled]="loading()">
              {{ I18N.ui.buttons.load_more | translate }}
            </button>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">
        {{ I18N.dialog.cancel | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class PersonSelectorDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly allowCreate = inject<{ allowCreate?: boolean } | null>(MAT_DIALOG_DATA, { optional: true })?.allowCreate !== false;
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly owner = this.auth.identity();
  private readonly recentIds = inject(PersonAssignmentHistoryService).recentIds().join(',');
  private readonly destroyRef = inject(DestroyRef);
  readonly dialogRef = inject(MatDialogRef<PersonSelectorDialogComponent>);

  searchQuery = '';
  newName = '';
  readonly filtered = signal<PersonOption[]>([]);
  readonly creating = signal(false);

  readonly loading = signal(false);
  readonly failed = signal(false);
  readonly hasMore = signal(false);
  private requestId = 0;
  private page = 0;
  private activeSearch = '';
  private searchTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    effect(() => {
      if (this.auth.identity() !== this.owner) {
        this.requestId++;
        clearTimeout(this.searchTimer);
        this.filtered.set([]);
        this.dialogRef.close(null);
      }
    });
    this.destroyRef.onDestroy(() => {
      clearTimeout(this.searchTimer);
      this.requestId++;
    });
    void this.loadPage(1, '', this.requestId);
  }

  filter(): void {
    clearTimeout(this.searchTimer);
    const requestId = ++this.requestId;
    this.activeSearch = this.searchQuery.trim();
    this.page = 0;
    this.filtered.set([]);
    this.hasMore.set(false);
    this.failed.set(false);
    this.loading.set(true);
    this.searchTimer = setTimeout(() => {
      void this.loadPage(1, this.activeSearch, requestId);
    }, 250);
  }

  async loadMore(): Promise<void> {
    if (this.loading() || !this.hasMore()) return;
    await this.loadPage(this.page + 1, this.activeSearch, this.requestId);
  }

  async retry(): Promise<void> {
    if (this.loading()) return;
    await this.loadPage(this.page + 1, this.activeSearch, this.requestId);
  }

  private async loadPage(page: number, search: string, requestId: number): Promise<void> {
    if (this.destroyRef.destroyed || this.auth.identity() !== this.owner) return;
    this.loading.set(true);
    this.failed.set(false);
    try {
      const result = await firstValueFrom(
        this.api.get<components['schemas']['PersonsListResponse']>('/persons', {
          page,
          per_page: 48,
          search,
          sort: 'assignment',
          recent_ids: this.recentIds,
        }),
      );
      if (this.destroyRef.destroyed || this.auth.identity() !== this.owner || requestId !== this.requestId) return;
      const named = result.persons
        .filter((person) => person.name?.trim())
        .map((person) => ({
          id: person.id,
          name: person.name!,
          face_count: person.face_count ?? 0,
        }));
      this.filtered.update((current) => page === 1 ? named : [...current, ...named.filter(
        (person) => !current.some((row) => row.id === person.id),
      )]);
      this.page = page;
      this.hasMore.set(page * 48 < result.total);
    } catch {
      if (!this.destroyRef.destroyed && requestId === this.requestId) this.failed.set(true);
    } finally {
      if (!this.destroyRef.destroyed && requestId === this.requestId) this.loading.set(false);
    }
  }

  startCreate(): void {
    if (!this.allowCreate) return;
    this.newName = this.searchQuery.trim();
    this.creating.set(true);
  }

  cancelCreate(): void {
    this.creating.set(false);
    this.newName = '';
  }

  confirmCreate(): void {
    if (!this.allowCreate) return;
    const name = this.newName.trim();
    if (!name) return;
    this.dialogRef.close({ kind: 'create', name });
  }
}
