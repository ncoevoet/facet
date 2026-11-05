import { PhotoPanelReader } from './photo-panel-reader';
import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { I18N } from '../../core/i18n/keys';
import type { PhotoProvenance } from '../../core/api/types';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';

@Component({
  selector: 'app-photo-provenance',
  imports: [MatIconModule, TranslatePipe, ContextHelpComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    <details [open]="expanded()" data-photo-provenance
             (keydown.escape)="expanded() && close($event, trigger)" class="[&[open]>summary>mat-icon:last-child]:rotate-180">
      <summary #trigger (click)="toggle($event)" class="flex min-h-9 max-sm:min-h-11 pointer-coarse:min-h-11 cursor-pointer items-center gap-2 text-xs font-medium focus-visible:outline-2">
        <mat-icon aria-hidden="true" class="!h-5 !w-5 !text-xl">history</mat-icon><h3 class="m-0 text-xs font-medium">{{ I18N.metadata_sources.title | translate }}</h3>
        <mat-icon aria-hidden="true" class="ml-auto !h-5 !w-5 shrink-0 !text-xl transition-transform motion-reduce:transition-none">expand_more</mat-icon>
      </summary>
      @if (expanded()) {
        <div class="space-y-2 pb-2 text-xs">
          @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
          @else if (failed()) {
            <p role="alert">{{ I18N.metadata_sources.failed | translate }}</p>
            <button type="button" class="min-h-11 cursor-pointer underline focus-visible:outline-2" (click)="load()">{{ I18N.gallery.load_error.retry | translate }}</button>
          } @else if (data(); as result) {
            <p class="m-0 font-medium">{{ (result.review_scope === 'personal' ? I18N.metadata_sources.personal : I18N.metadata_sources.catalog) | translate }}</p>
            <dl class="m-0 space-y-2">
              @for (row of rows(); track row.field) {
                <div class="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2">
                  <dt class="flex flex-wrap items-baseline gap-x-2">{{ row.label | translate }} <span class="tabular-nums">{{ row.value === null ? (I18N.photo_detail.assessment.unavailable | translate) : row.field === 'star_rating' ? row.value : (row.valueLabel | translate) }}</span></dt>
                  <dd class="m-0 text-[var(--mat-sys-on-surface-variant)]">{{ row.sourceLabel | translate }}</dd>
                </div>
              }
            </dl>
            <p class="m-0 font-medium">{{ I18N.metadata_sources.shared_tags | translate }}</p>
            @for (tag of tagRows(); track tag.tag) {
              <div class="flex items-start justify-between gap-2"><span class="min-w-0 break-words">{{ tag.tag }}</span><span class="shrink-0 text-[var(--mat-sys-on-surface-variant)]">{{ tag.sourceLabel | translate }}</span></div>
            } @empty { <p class="m-0 text-[var(--mat-sys-on-surface-variant)]">{{ I18N.metadata_sources.no_tags | translate }}</p> }
            @if (result.manual_tags_truncated) { <p>{{ I18N.metadata_sources.tag_limit | translate }}</p> }
            @if (result.capture_date_override) { <p class="m-0">{{ I18N.metadata_sources.date_override | translate }}</p> }
            @if (result.gps_override) { <p class="m-0">{{ I18N.metadata_sources.gps_override | translate }}</p> }
            <app-context-help [label]="I18N.metadata_sources.help_title" [keys]="helpKeys" />
          }
        </div>
      }
    </details>
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

}
