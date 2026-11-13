import { createGalleryFilterContext } from './gallery-filter-context';
import { afterNextRender, ChangeDetectionStrategy, Component, computed, ElementRef, inject, Injector, signal, viewChildren } from '@angular/core';
import { MatAutocompleteModule, MatAutocompleteSelectedEvent, MatAutocompleteTrigger } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { FilterOption, GalleryStore } from './gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';
import { parseTagQuery, serializeTagQuery, TAG_QUERY_GROUPS, TAG_QUERY_LIMIT, TAG_QUERY_NAME_LIMIT, TagQueryGroup } from './tag-query.util';

/** Suggestions shown per row; the catalog can hold thousands of tags. */
const SUGGESTION_LIMIT = 50;
const EMPTY_DRAFTS: Record<TagQueryGroup, string> = { any: '', all: '', none: '' };

/** One chip row per tag rule group (Any, All, None); the groups combine with AND. */
@Component({
  selector: 'app-tag-groups',
  imports: [TranslatePipe, MatAutocompleteModule, MatButtonModule, MatChipsModule, MatFormFieldModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' }, template: `
    <div data-tag-groups class="flex flex-col gap-2 pb-2">
      <p id="tag-rule-hint" class="sr-only">{{ I18N.gallery.tag_groups.hint | translate }}</p>
      <p id="tag-rule-enter" class="m-0 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.tag_groups.enter_hint | translate }}</p>
      @if (groups()) {
        @for (row of rows(); track row.id) {
          <mat-form-field subscriptSizing="dynamic" class="w-full" [attr.data-tag-rule-row]="row.id">
            <mat-label>{{ row.label | translate }}</mat-label>
            <mat-chip-grid #grid [attr.aria-label]="row.label | translate">
              @for (tag of row.tags; track tag) {
                <mat-chip-row (removed)="remove(row.id, tag)">
                  <bdi>{{ tag }}</bdi>
                  <button matChipRemove type="button" [attr.aria-label]="I18N.gallery.tag_groups.remove | translate:{ name: tag }"><mat-icon>cancel</mat-icon></button>
                </mat-chip-row>
              }
              <input #ruleInput data-tag-rule-input autocomplete="off" [maxLength]="nameLimit * 2"
                     [placeholder]="I18N.gallery.tag_groups.name | translate"
                     [matChipInputFor]="grid" [matChipInputSeparatorKeyCodes]="noSeparators" [matAutocomplete]="auto"
                     [attr.aria-describedby]="error() === row.id ? 'tag-rule-hint tag-rule-enter tag-rule-error' : 'tag-rule-hint tag-rule-enter'"
                     [attr.aria-invalid]="error() === row.id || null"
                     [value]="drafts()[row.id]" (input)="setDraft(row.id, $any($event.target).value)"
                     (keydown.enter)="add(row.id, $event)" />
            </mat-chip-grid>
            <mat-autocomplete #auto="matAutocomplete" (optionSelected)="pick(row.id, $event, ruleInput)">
              @for (tag of suggestions()[row.id]; track tag.value) {
                <mat-option [value]="tag.value"><bdi>{{ tag.value }}</bdi> ({{ tag.count }})</mat-option>
              }
            </mat-autocomplete>
          </mat-form-field>
        }
        @if (total() >= limit) { <p role="status" class="m-0 text-xs">{{ I18N.gallery.tag_groups.limit | translate:{ max: limit } }}</p> }
        @if (error()) { <p id="tag-rule-error" role="alert" class="m-0 text-xs">{{ I18N.gallery.tag_groups.invalid_name | translate:{ max: nameLimit } }}</p> }
      } @else { <p role="alert" class="m-0 text-xs">{{ I18N.gallery.tag_groups.invalid | translate }}</p> }
      @if (store.filters().tag_groups) {
        <button mat-button type="button" data-tag-rule-clear class="self-end" (click)="clear()">{{ I18N.gallery.tag_groups.clear | translate }}</button>
      }
    </div>
  `,
})
export class TagGroupsComponent {
  protected readonly I18N = I18N;
  protected readonly store = inject(GalleryStore);
  private readonly injector = inject(Injector);
  private readonly ruleInputs = viewChildren<ElementRef<HTMLInputElement>>('ruleInput');
  private readonly triggers = viewChildren(MatAutocompleteTrigger);
  /** Enter is handled by `add`, which guards IME composition and key repeat; commas are literal. */
  protected readonly noSeparators: readonly number[] = [];
  protected readonly drafts = signal<Record<TagQueryGroup, string>>(EMPTY_DRAFTS);
  /** The row whose last name was refused, so only its input points at the error. */
  protected readonly error = signal<TagQueryGroup | null>(null);
  protected readonly limit = TAG_QUERY_LIMIT;
  protected readonly nameLimit = TAG_QUERY_NAME_LIMIT;
  protected readonly groups = computed(() => parseTagQuery(this.store.filters().tag_groups));
  protected readonly rows = computed(() => TAG_QUERY_GROUPS.map(id => ({ id, label: I18N.gallery.tag_groups[id], tags: this.groups()?.[id] ?? [] })));
  protected readonly total = computed(() => this.rows().reduce((sum, row) => sum + row.tags.length, 0));
  protected readonly suggestions = computed((): Record<TagQueryGroup, FilterOption[]> => {
    const groups = this.groups();
    const drafts = this.drafts();
    const tags = this.store.tags();
    return Object.fromEntries(TAG_QUERY_GROUPS.map(id => {
      const query = drafts[id].trim().toLowerCase();
      const taken = new Set(groups?.[id] ?? []);
      return [id, tags.filter(tag => !taken.has(tag.value) && tag.value.toLowerCase().includes(query)).slice(0, SUGGESTION_LIMIT)];
    })) as Record<TagQueryGroup, FilterOption[]>;
  });

  private readonly context = createGalleryFilterContext({
    authChanged: () => { this.drafts.set(EMPTY_DRAFTS); this.error.set(null); },
    navigationStarted: () => { this.drafts.set(EMPTY_DRAFTS); this.error.set(null); },
  });

  protected setDraft(group: TagQueryGroup, value: string): void {
    this.drafts.update(drafts => ({ ...drafts, [group]: value }));
  }

  protected add(group: TagQueryGroup, event: Event): void {
    if (event instanceof KeyboardEvent && (event.isComposing || event.repeat || event.keyCode === 229)) return;
    // Enter on a highlighted suggestion is the autocomplete's pick, never the typed text as well.
    if (event.defaultPrevented) return;
    event.preventDefault();
    this.commit(group, this.drafts()[group]);
  }

  protected pick(group: TagQueryGroup, event: MatAutocompleteSelectedEvent, input: HTMLInputElement): void {
    // A refused pick leaves the typed text in the box, so the input never hides what Enter would add.
    input.value = this.commit(group, String(event.option.value)) ? '' : this.drafts()[group];
  }

  /** Close the suggestion lists, for a gallery parking behind a photo page. */
  closeOverlays(): void {
    for (const trigger of this.triggers()) trigger.closePanel();
  }

  private commit(group: TagQueryGroup, raw: string): boolean {
    const name = raw.trim();
    if (!this.context.current() || !name || this.total() >= TAG_QUERY_LIMIT || this.context.pending()) return false;
    const groups = this.groups();
    if (!groups) return false;
    const next = { ...groups, [group]: [...new Set([...groups[group], name])] };
    if (!parseTagQuery(JSON.stringify(next))) {
      this.error.set(group);
      return false;
    }
    void this.store.updateFilter('tag_groups', serializeTagQuery(next));
    this.setDraft(group, '');
    this.error.set(null);
    return true;
  }

  protected remove(group: TagQueryGroup, tag: string): void {
    if (!this.context.current()) return;
    const groups = this.groups();
    if (groups) void this.store.updateFilter('tag_groups', serializeTagQuery({ ...groups, [group]: groups[group].filter(value => value !== tag) }));
  }

  protected clear(): void {
    if (!this.context.current()) return;
    void this.store.updateFilter('tag_groups', '');
    this.error.set(null);
    // The Clear button leaves with the rules; an invalid set only renders its inputs afterwards.
    // Focusing the row opens its suggestions, which nobody asked for: close them again.
    afterNextRender({ write: () => {
      this.ruleInputs()[0]?.nativeElement.focus();
      this.triggers()[0]?.closePanel();
    } }, { injector: this.injector });
  }
}
