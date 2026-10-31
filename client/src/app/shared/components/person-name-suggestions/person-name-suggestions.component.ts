import { Component, ViewChild, input, ChangeDetectionStrategy } from '@angular/core';
import { MatAutocomplete, MatAutocompleteModule } from '@angular/material/autocomplete';
import { Pipe, PipeTransform } from '@angular/core';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { PluralKeyPipe } from '../../pipes/plural-key.pipe';
import { PersonThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { i18nKeys } from '../../../core/i18n/keys';
import { PersonNameOption, matchPersonNames } from '../../utils/person-name';

/** ``options | personNameMatches:query``: the options whose folded name contains the folded query. */
@Pipe({ name: 'personNameMatches', standalone: true, pure: true })
export class PersonNameMatchesPipe implements PipeTransform {
  transform(options: readonly PersonNameOption[] | null, query: string | null): PersonNameOption[] {
    return matchPersonNames(options ?? [], query ?? '');
  }
}

/**
 * The existing-name suggestions shared by the persons page cards and the gallery's
 * naming bar: a ``mat-autocomplete`` whose options show each person's face
 * thumbnail, name and photo count, filtered by ``query`` with the shared
 * name-folding rule. Wire it to an input with
 * ``[matAutocomplete]="suggestions.panel"`` on a ``#suggestions`` reference;
 * choosing an option writes its name into the input.
 */
@Component({
  selector: 'app-person-name-suggestions',
  imports: [MatAutocompleteModule, TranslatePipe, PluralKeyPipe, PersonThumbnailUrlPipe, PersonNameMatchesPipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'contents' },
  template: `
    <mat-autocomplete #panel="matAutocomplete" class="!max-h-72">
      @for (o of options() | personNameMatches:query(); track o.id) {
        <mat-option [value]="o.name">
          <span class="flex items-center gap-2 min-w-0">
            <img [src]="o.id | personThumbnailUrl" alt="" loading="lazy"
                 class="w-8 h-8 rounded-full object-cover shrink-0 bg-[var(--mat-sys-surface-container-high)]" />
            <span class="truncate flex-1">{{ o.name }}</span>
            <span class="text-xs opacity-70 shrink-0">
              {{ o.count | pluralKey:I18N.persons.name_suggestion_photos:I18N.persons.name_suggestion_photos_plural | translate:{ count: o.count } }}
            </span>
          </span>
        </mat-option>
      }
    </mat-autocomplete>
  `,
})
export class PersonNameSuggestionsComponent {
  protected readonly I18N = i18nKeys();
  readonly options = input<readonly PersonNameOption[]>([]);
  /** What the user has typed so far. */
  readonly query = input('');
  /** Static, so a sibling input's ``[matAutocomplete]`` binding sees it on its first check. */
  @ViewChild('panel', { static: true }) panel!: MatAutocomplete;
}
