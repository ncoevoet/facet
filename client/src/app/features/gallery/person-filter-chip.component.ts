import { Component, inject, input, output, signal, computed, effect, viewChild, afterNextRender, ElementRef, Injector, ChangeDetectionStrategy } from '@angular/core';
import { MatAutocompleteModule, MatAutocompleteTrigger } from '@angular/material/autocomplete';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { GalleryStore } from './gallery.store';
import { RenamePersonResponse, SameNameMergeService } from '../persons/same-name-merge.service';
import { EnterPickGuard } from '../../shared/utils/enter-pick-guard';
import { isUnnamedPerson, personNameOptions, sameName } from '../../shared/utils/person-name';
import { PersonNameSuggestionsComponent } from '../../shared/components/person-name-suggestions/person-name-suggestions.component';
import { PersonFaceMenuComponent } from '../persons/person-face-menu.component';
import { i18nKeys, I18N } from '../../core/i18n/keys';

/** One row of ``GET /api/filter_options/persons``: ``[id, name, photo_count]``. */
type PersonOptionRow = [number, string | null, number];

interface PersonOptionItem {
  id: number;
  name: string | null;
  count: number;
}

/** The compact icon buttons on the chip: 24 px, the icon centred. */
const CHIP_BUTTON = 'inline-flex items-center justify-center w-6 h-6 shrink-0 rounded-full hover:bg-black/20 transition-colors';

/**
 * One person in the gallery's active-filter row. In edition mode it carries an edit
 * pencil, which turns the chip into a name field with the photo suggestions, and the
 * shared person menu (⋮). The name always goes through the rename endpoint; when the
 * server reports other persons already carrying it, the persons page's same-name
 * merge is offered, and a merge into another person points the filter at it.
 * Read-only, it is the plain chip with its remove button.
 */
@Component({
  selector: 'app-person-filter-chip',
  imports: [FormsModule, MatAutocompleteModule, MatIconModule, MatTooltipModule, TranslatePipe, PersonThumbnailUrlPipe, PersonNameSuggestionsComponent, PersonFaceMenuComponent],
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'contents' },
  template: `
    <div data-person-chip
         class="inline-flex items-center gap-1 pl-0.5 pr-1 py-0.5 min-h-9 rounded-full border-2 bg-[var(--mat-sys-secondary-container)] text-[var(--mat-sys-on-secondary-container)] text-xs font-medium"
         [class]="unnamed() ? 'border-dashed border-[var(--mat-sys-primary)]' : 'border-solid border-transparent'"
         [attr.data-person-id]="personId()">
      <img data-person-chip-avatar [src]="personId() | personThumbnailUrl" class="w-8 h-8 rounded-full object-cover shrink-0" [alt]="label()" />
      @if (editing()) {
        <input #nameInput
          data-person-name-input
          class="bg-transparent border-0 border-b-2 border-[var(--mat-sys-outline)] focus:border-[var(--mat-sys-primary)] !outline-none focus-visible:!outline-none py-0.5 w-48 min-w-24 text-sm"
          [placeholder]="(unnamed() ? I18N.gallery.person_chip.name_placeholder : I18N.gallery.person_chip.rename_placeholder) | translate"
          [attr.aria-label]="I18N.gallery.person_chip.name_placeholder | translate"
          autocomplete="off"
          [matAutocomplete]="suggestions.panel"
          [ngModel]="draft()"
          (ngModelChange)="draft.set($event)"
          (keydown.enter)="onEnterDown()"
          (keyup.enter)="onEnterUp()"
          (keydown.escape)="cancelEdit()" />
        <app-person-name-suggestions #suggestions [options]="otherNames()" [query]="draft()" />
        <button type="button" data-person-name-save [class]="CHIP_BUTTON"
                [disabled]="busy()" (click)="$event.stopPropagation(); assign()"
                [matTooltip]="I18N.ui.buttons.save | translate" [attr.aria-label]="I18N.ui.buttons.save | translate">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4">check</mat-icon>
        </button>
        <button type="button" data-person-name-cancel [class]="CHIP_BUTTON"
                (click)="$event.stopPropagation(); cancelEdit()"
                [matTooltip]="I18N.ui.buttons.cancel | translate" [attr.aria-label]="I18N.ui.buttons.cancel | translate">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4">close</mat-icon>
        </button>
      } @else {
        <span class="hidden xl:inline mx-0.5">{{ label() }}</span>
        @if (canEdit()) {
          <button type="button" data-person-name-edit [class]="CHIP_BUTTON"
                  (click)="$event.stopPropagation(); startEdit()"
                  [matTooltip]="I18N.persons.rename | translate" [attr.aria-label]="I18N.persons.rename | translate">
            <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px]">edit</mat-icon>
          </button>
          <button type="button" data-person-more [class]="CHIP_BUTTON" aria-haspopup="menu"
                  (click)="$event.stopPropagation(); openMenu($event)"
                  [matTooltip]="I18N.nav.more | translate" [attr.aria-label]="I18N.nav.more | translate">
            <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px]">more_vert</mat-icon>
          </button>
        }
        <button type="button" data-person-remove [class]="CHIP_BUTTON"
                (click)="$event.stopPropagation(); remove.emit()"
                [matTooltip]="I18N.gallery.person_chip.remove | translate" [attr.aria-label]="I18N.gallery.person_chip.remove | translate">
          <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px]">close</mat-icon>
        </button>
      }
    </div>
    @if (canEdit()) {
      <app-person-face-menu [canEdit]="canEdit()" (changed)="afterMenuChange()" (hiddenChanged)="hidden.set($event.hidden)" />
    }
  `,
})
export class PersonFilterChipComponent {
  protected readonly I18N = i18nKeys();
  protected readonly CHIP_BUTTON = CHIP_BUTTON;
  private readonly api = inject(ApiService);
  private readonly sameNameMerge = inject(SameNameMergeService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly store = inject(GalleryStore);
  private readonly injector = inject(Injector);

  readonly personId = input.required<number>();
  readonly canEdit = input(false);
  /** The remove (×) button: the gallery drops this person from its filter. */
  readonly remove = output<void>();

  private readonly options = signal<PersonOptionItem[]>([]);
  protected readonly busy = signal(false);
  protected readonly draft = signal('');
  /** True while the chip is the name field. */
  protected readonly editing = signal(false);
  /** Set once the person was ignored or restored from the ⋮ menu: filter options do not say. */
  protected readonly hidden = signal(false);
  private readonly autocomplete = viewChild(MatAutocompleteTrigger);
  private readonly nameInput = viewChild<ElementRef<HTMLInputElement>>('nameInput');
  private readonly menu = viewChild(PersonFaceMenuComponent);
  /** Keeps an Enter keydown that picked a suggestion from also saving on its keyup. */
  private readonly enterGuard = new EnterPickGuard();

  readonly person = computed(() => this.options().find((o) => o.id === this.personId()) ?? null);
  readonly name = computed(() => this.person()?.name ?? null);
  protected readonly unnamed = computed(() => isUnnamedPerson(this.name()));
  protected readonly label = computed(() => (this.unnamed() ? null : this.name()) || this.i18n.t(I18N.persons.unnamed));

  /** Every other named person, one per folded name, for the suggestions. */
  readonly otherNames = computed(() =>
    personNameOptions(this.options().map((o) => [o.id, o.name, o.count] as const), this.personId()));

  constructor() {
    effect(() => {
      const id = this.personId();
      this.draft.set('');
      this.editing.set(false);
      this.hidden.set(false);
      void this.load(id);
    });
  }

  async load(id: number = this.personId()): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.get<{ persons: PersonOptionRow[] }>('/filter_options/persons', { ids: String(id) }));
      if (id !== this.personId()) return;
      this.options.set((res.persons ?? []).map(([pid, name, count]) => ({ id: pid, name, count })));
    } catch {
      if (id === this.personId()) this.options.set([]);
    }
  }

  /** Turn the chip into the name field, focused, with the suggestions open. */
  startEdit(): void {
    this.draft.set('');
    this.editing.set(true);
    afterNextRender(() => {
      this.nameInput()?.nativeElement.focus();
      this.autocomplete()?.openPanel();
    }, { injector: this.injector });
  }

  /** Back to the chip, nothing saved. */
  cancelEdit(): void {
    this.autocomplete()?.closePanel();
    this.draft.set('');
    this.editing.set(false);
  }

  protected openMenu(event: Event): void {
    this.menu()?.openBelow(
      { person: { id: this.personId(), name: this.name(), hidden: this.hidden() }, face: null },
      event.currentTarget as HTMLElement);
  }

  protected async afterMenuChange(): Promise<void> {
    await this.load();
    await this.store.reloadPhotos();
  }

  protected onEnterDown(): void {
    this.enterGuard.down(this.autocomplete());
  }

  protected onEnterUp(): void {
    if (this.enterGuard.up()) void this.assign();
  }

  async assign(): Promise<void> {
    const id = this.personId();
    const name = this.draft().trim();
    if (!name || this.busy()) return;
    if (sameName(this.name(), name)) {
      this.cancelEdit();
      return;
    }
    this.busy.set(true);
    try {
      let res: RenamePersonResponse;
      try {
        res = await firstValueFrom(this.api.post<RenamePersonResponse>(`/persons/${id}/rename`, { name }));
      } catch {
        this.snackBar.open(this.i18n.t(I18N.gallery.person_chip.error), '', { duration: 3000 });
        return;
      }
      this.snackBar.open(this.i18n.t(I18N.gallery.person_chip.named, { name }), '', { duration: 2500 });
      this.cancelEdit();
      const namesakes = res.same_name_persons ?? [];
      const merge = namesakes.length > 0
        ? await this.sameNameMerge.offer({ id, face_count: res.face_count }, name, namesakes)
        : null;
      await this.store.reloadPersonOptions();
      // Only a merge that folded this person away moves the filter; one that kept it, or left it out, does not.
      if (merge?.status === 'merged' && merge.merges.some((m) => m.source_id === id)) {
        // Point the filter at the person that survived, keeping the other chips.
        const ids = this.store.filters().person_id.split(',').filter(Boolean)
          .map((pid) => (pid === String(id) ? String(merge.targetId) : pid));
        await this.store.updateFilters({ person_id: [...new Set(ids)].join(',') });
      } else {
        await this.load(id);
      }
    } finally {
      this.busy.set(false);
    }
  }
}
