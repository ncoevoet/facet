import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { Photo } from '../../models/photo.model';
import { CategoryLabelPipe } from '../../pipes/category-label.pipe';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { I18N } from '../../../core/i18n/keys';

/** Extra columns follow the row container's width, including docked panels. */
@Component({
  selector: 'app-photo-list-extra',
  imports: [CategoryLabelPipe, FixedPipe, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'contents' },
  template: `
    <div data-list-scores class="hidden min-w-0 text-xs leading-5 @[80rem]:block">
      <div class="truncate font-medium">{{ photo().category | categoryLabel }}</div>
      <div class="flex flex-wrap gap-x-2 text-[var(--mat-sys-on-surface-variant)]">
        <span [title]="I18N.tooltip.aesthetic | translate" class="inline-flex gap-1"><span class="max-w-12 truncate">{{ I18N.tooltip.aesthetic | translate }}</span><b class="font-medium">{{ (photo().aesthetic | fixed:1) || '—' }}</b></span>
        <span [title]="I18N.tooltip.composition | translate" class="inline-flex gap-1"><span class="max-w-12 truncate">{{ I18N.tooltip.composition | translate }}</span><b class="font-medium">{{ (photo().comp_score | fixed:1) || '—' }}</b></span>
        <span [title]="I18N.tooltip.face_quality | translate" class="inline-flex gap-1"><span class="max-w-12 truncate">{{ I18N.tooltip.face_quality | translate }}</span><b class="font-medium">{{ (photo().face_quality | fixed:1) || '—' }}</b></span>
      </div>
    </div>
    <div data-list-context class="hidden min-w-0 text-xs leading-5 @[100rem]:block">
      <div class="truncate" [title]="tags()">{{ tags() || '—' }}</div>
      <div class="truncate text-[var(--mat-sys-on-surface-variant)]" [title]="people()">{{ people() || '—' }}</div>
      <div class="truncate text-[var(--mat-sys-on-surface-variant)]">{{ location() }} @if (photo().image_width && photo().image_height) { @if (location()) { · } {{ photo().image_width }} × {{ photo().image_height }} }</div>
    </div>
  `,
})
export class PhotoListExtraComponent {
  protected readonly I18N = I18N;
  readonly photo = input.required<Photo>();
  protected readonly tags = computed(() => [...new Set([...(this.photo().tags_list ?? []), ...(this.photo().manual_tags ?? [])])].join(', '));
  protected readonly people = computed(() => (this.photo().persons ?? []).map(person => person.name).filter(Boolean).join(', '));
  protected readonly location = computed(() => typeof this.photo().gps_latitude === 'number' && typeof this.photo().gps_longitude === 'number' ? `${this.photo().gps_latitude!.toFixed(3)}, ${this.photo().gps_longitude!.toFixed(3)}` : '');
}
