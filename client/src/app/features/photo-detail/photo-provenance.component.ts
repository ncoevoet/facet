import { PhotoPanelReader } from './photo-panel-reader';
import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { I18N } from '../../core/i18n/keys';
import type { PhotoProvenance } from '../../core/api/types';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';

function sharedSource(rows: readonly { sourceLabel: string }[]): string | null {
  return rows.length && rows.every(row => row.sourceLabel === rows[0].sourceLabel) ? rows[0].sourceLabel : null;
}

@Component({
  selector: 'app-photo-provenance',
  imports: [MatExpansionModule, MatIconModule, TranslatePipe, ContextHelpComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    <mat-expansion-panel #panel data-photo-provenance class="!rounded-none !bg-transparent !shadow-none [&_.mat-expansion-panel-body]:!px-0 [&_.mat-expansion-panel-body]:!pb-2"
                         [expanded]="expanded()" (expandedChange)="setExpanded($event, panel)" (keydown.escape)="expanded() && close($event, header)">
      <mat-expansion-panel-header #header class="!h-11 !ps-0 !pe-2 !text-xs !font-medium">
        <mat-panel-title class="!m-0 items-center gap-2"><mat-icon aria-hidden="true" class="!h-5 !w-5 shrink-0 !text-xl">history</mat-icon>{{ I18N.metadata_sources.title | translate }}</mat-panel-title>
      </mat-expansion-panel-header>
      @if (expanded()) {
        <div class="space-y-2 pb-2 text-xs">
          @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
          @else if (failed()) {
            <p role="alert">{{ I18N.metadata_sources.failed | translate }}</p>
            <button type="button" class="min-h-11 cursor-pointer underline focus-visible:outline-2" (click)="load()">{{ I18N.gallery.load_error.retry | translate }}</button>
          } @else if (data(); as result) {
            <div data-provenance-scope class="flex items-center gap-1">
              <p class="m-0 min-w-0 flex-1 font-medium">{{ (result.review_scope === 'personal' ? I18N.metadata_sources.personal : I18N.metadata_sources.catalog) | translate }}</p>
              <app-context-help [label]="I18N.metadata_sources.help_title" [keys]="helpKeys" [iconOnly]="true" />
            </div>
            @if (rows().length) {
              <table data-provenance-review class="w-full border-collapse">
                <thead class="text-[var(--mat-sys-on-surface-variant)]"><tr>
                  <th scope="col" class="py-1 pe-2 text-start font-normal">{{ I18N.metadata_sources.field | translate }}</th>
                  <th scope="col" class="py-1 pe-2 text-start font-normal">{{ I18N.metadata_sources.value | translate }}</th>
                  @if (!reviewSource()) { <th scope="col" class="py-1 text-start font-normal">{{ I18N.metadata_sources.source | translate }}</th> }
                </tr></thead>
                <tbody>
                  @for (row of rows(); track row.field) {
                    <tr class="border-t border-[var(--mat-sys-outline-variant)]">
                      <th scope="row" class="py-1 pe-2 text-start font-normal">{{ row.label | translate }}</th>
                      <td class="py-1 pe-2 tabular-nums">{{ row.value === null ? (I18N.photo_detail.assessment.unavailable | translate) : row.field === 'star_rating' ? row.value : (row.valueLabel | translate) }}</td>
                      @if (!reviewSource()) { <td class="py-1 text-[var(--mat-sys-on-surface-variant)]">{{ row.sourceLabel | translate }}</td> }
                    </tr>
                  }
                </tbody>
              </table>
              @if (reviewSource(); as source) { <p data-provenance-review-source class="m-0 text-[var(--mat-sys-on-surface-variant)]">{{ I18N.metadata_sources.all_fields | translate:{ source: (source | translate) } }}</p> }
            }
            <p class="m-0 pt-2 font-medium">{{ I18N.metadata_sources.shared_tags | translate }}</p>
            @for (tag of tagRows(); track tag.tag) {
              <div class="flex items-start justify-between gap-2"><span class="min-w-0 break-words">{{ tag.tag }}</span>@if (!tagSource()) { <span class="shrink-0 text-[var(--mat-sys-on-surface-variant)]">{{ tag.sourceLabel | translate }}</span> }</div>
            } @empty { <p class="m-0 text-[var(--mat-sys-on-surface-variant)]">{{ I18N.metadata_sources.no_tags | translate }}</p> }
            @if (tagSource(); as source) { <p data-provenance-tag-source class="m-0 text-[var(--mat-sys-on-surface-variant)]">{{ I18N.metadata_sources.all_tags | translate:{ source: (source | translate) } }}</p> }
            @if (result.manual_tags_truncated) { <p>{{ I18N.metadata_sources.tag_limit | translate }}</p> }
            @if (result.capture_date_override) { <p class="m-0">{{ I18N.metadata_sources.date_override | translate }}</p> }
            @if (result.gps_override) { <p class="m-0">{{ I18N.metadata_sources.gps_override | translate }}</p> }
          }
        </div>
      }
    </mat-expansion-panel>
  `,
})
export class PhotoProvenanceComponent extends PhotoPanelReader<PhotoProvenance> {
  protected readonly endpoint = '/photo/provenance';
  protected readonly I18N = I18N;
  protected readonly helpKeys = [I18N.metadata_sources.help];

  protected readonly rows = computed(() => (this.data()?.review ?? []).map(row => ({
    ...row,
    valueLabel: row.value ? I18N.organization_history.yes : I18N.organization_history.no,
    label: ({ star_rating: I18N.rating.stars, is_favorite: I18N.rating.favorite,
      is_kept: I18N.review.kept, is_rejected: I18N.review.rejected })[row.field],
    sourceLabel: ({ local: I18N.metadata_sources.local, xmp: I18N.metadata_sources.xmp,
      unrecorded: I18N.metadata_sources.unrecorded })[row.source],
  })));
  protected readonly tagRows = computed(() => (this.data()?.manual_tags ?? []).map(tag => ({
    ...tag,
    sourceLabel: ({ user: I18N.metadata_sources.typed, xmp: I18N.metadata_sources.xmp,
      unrecorded: I18N.metadata_sources.unrecorded })[tag.source],
  })));
  /** The one source every review field shares, shown once under the table instead of in a column. */
  protected readonly reviewSource = computed(() => sharedSource(this.rows()));
  protected readonly tagSource = computed(() => sharedSource(this.tagRows()));

}
