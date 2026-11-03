import { createGalleryFilterContext } from './gallery-filter-context';
import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, signal, viewChild } from '@angular/core';
import { GalleryStore } from './gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';
import { parseTagQuery, serializeTagQuery, TAG_QUERY_GROUPS, TAG_QUERY_LIMIT, TAG_QUERY_NAME_LIMIT, TagQueryGroup } from './tag-query.util';

@Component({
  selector: 'app-tag-groups', imports: [TranslatePipe], changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' }, template: `
    <details data-tag-groups [open]="!!store.filters().tag_groups">
      <summary #ruleSummary class="cursor-pointer min-h-11 flex items-center text-sm font-medium">{{ I18N.gallery.tag_groups.title | translate }}</summary>
      @if (groups(); as current) {
        <p class="my-1 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.tag_groups.hint | translate }}</p>
        <fieldset class="border-0 m-0 p-0">
          <legend class="text-xs">{{ I18N.gallery.tag_groups.add_to | translate }}</legend>
          <div class="flex flex-wrap gap-3">
            @for (row of rows(); track row.id) {
              <label class="inline-flex min-h-11 items-center gap-1"><input type="radio" name="tag-group-mode" [value]="row.id" [checked]="mode() === row.id" (change)="mode.set(row.id)" />{{ row.label | translate }}</label>
            }
          </div>
        </fieldset>
        <label class="block text-xs" for="tag-rule-input">{{ I18N.gallery.tag_groups.name | translate }}</label>
        <div class="flex items-center gap-2">
          <input #ruleInput id="tag-rule-input" data-tag-rule-input type="text" list="tag-rule-suggestions" autocomplete="off" [maxLength]="nameLimit * 2"
                 [attr.aria-invalid]="error() ? true : null" [attr.aria-describedby]="error() ? 'tag-rule-error' : null"
                 class="h-10 min-w-0 flex-1 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-lowest)] px-2 text-base"
                 [value]="draft()" (input)="draft.set($any($event.target).value)" (keydown.enter)="add($event)" />
          <button type="button" data-tag-rule-add class="min-h-11 rounded border border-[var(--mat-sys-outline)] px-3 text-sm" [disabled]="!canAdd()" (click)="add()">{{ I18N.gallery.tag_groups.add | translate }}</button>
        </div>
        <datalist id="tag-rule-suggestions">@for (tag of suggestions(); track tag.value) { <option [value]="tag.value"></option> }</datalist>
        @if (total() >= limit) { <p role="status" class="text-xs">{{ I18N.gallery.tag_groups.limit | translate:{ max: limit } }}</p> }
        @if (error()) { <p id="tag-rule-error" role="alert" class="text-xs">{{ I18N.gallery.tag_groups.invalid_name | translate:{ max: nameLimit } }}</p> }
        @for (row of rows(); track row.id) {
          @if (row.tags.length) {
            <section class="mt-2">
              <h3 class="m-0 text-xs font-semibold">{{ row.label | translate }}</h3>
              <ul class="m-0 flex flex-wrap gap-1 p-0 list-none">
                @for (tag of row.tags; track tag) {
                  <li><button type="button" class="min-h-11 max-w-full break-words rounded border border-[var(--mat-sys-outline-variant)] px-2 text-xs"
                              [attr.aria-label]="I18N.gallery.tag_groups.remove | translate:{ name: tag }" (click)="remove(row.id, tag)"><bdi>{{ tag }}</bdi><span aria-hidden="true"> ×</span></button></li>
                }
              </ul>
            </section>
          }
        }
      } @else { <p role="alert" class="text-xs">{{ I18N.gallery.tag_groups.invalid | translate }}</p> }
      @if (store.filters().tag_groups) { <button type="button" data-tag-rule-clear class="min-h-11 text-xs underline" (click)="clear()">{{ I18N.gallery.tag_groups.clear | translate }}</button> }
    </details>
  `,
})
export class TagGroupsComponent {
  protected readonly I18N = I18N;
  protected readonly store = inject(GalleryStore);
  private readonly ruleInput = viewChild<ElementRef<HTMLInputElement>>('ruleInput');
  private readonly ruleSummary = viewChild<ElementRef<HTMLElement>>('ruleSummary');
  protected readonly mode = signal<TagQueryGroup>('any');
  protected readonly draft = signal('');
  protected readonly error = signal(false);
  protected readonly limit = TAG_QUERY_LIMIT;
  protected readonly nameLimit = TAG_QUERY_NAME_LIMIT;
  protected readonly groups = computed(() => parseTagQuery(this.store.filters().tag_groups));
  protected readonly rows = computed(() => TAG_QUERY_GROUPS.map(id => ({ id, label: I18N.gallery.tag_groups[id], tags: this.groups()?.[id] ?? [] })));
  protected readonly total = computed(() => this.rows().reduce((sum, row) => sum + row.tags.length, 0));
  protected readonly suggestions = computed(() => this.store.tags().filter(tag => tag.value.toLowerCase().includes(this.draft().toLowerCase())));
  protected readonly canAdd = computed(() => !!this.draft().trim() && this.total() < TAG_QUERY_LIMIT && !this.context.pending());

  private readonly context = createGalleryFilterContext({
    authChanged: () => { this.draft.set(''); this.error.set(false); },
    navigationStarted: () => this.draft.set(''),
  });

  protected add(event?: Event): void {
    if (event instanceof KeyboardEvent && (event.isComposing || event.repeat || event.keyCode === 229)) return;
    event?.preventDefault();
    if (!this.context.current() || !this.canAdd()) return;
    const groups = this.groups();
    if (!groups) return;
    const next = { ...groups, [this.mode()]: [...new Set([...groups[this.mode()], this.draft()])] };
    if (!parseTagQuery(JSON.stringify(next))) { this.error.set(true); return; }
    void this.store.updateFilter('tag_groups', serializeTagQuery(next));
    this.draft.set(''); this.error.set(false);
  }

  protected remove(group: TagQueryGroup, tag: string): void {
    if (!this.context.current()) return;
    const groups = this.groups();
    if (groups) {
      this.ruleInput()?.nativeElement.focus();
      void this.store.updateFilter('tag_groups', serializeTagQuery({ ...groups, [group]: groups[group].filter(value => value !== tag) }));
    }
  }

  protected clear(): void {
    if (!this.context.current()) return;
    this.ruleSummary()?.nativeElement.focus();
    void this.store.updateFilter('tag_groups', '');
  }
}
