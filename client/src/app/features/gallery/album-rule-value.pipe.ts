import { Pipe, PipeTransform } from '@angular/core';
import { I18N } from '../../core/i18n/keys';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';

@Pipe({ name: 'albumRuleValue' })
export class AlbumRuleValuePipe implements PipeTransform {
  private readonly date = new CaptureDatePipe();
  transform(value: string, key: string): string {
    if (!value) return I18N.albums.rules.any;
    if (key === 'sort') return `sort_options.${value}`;
    if (key === 'sort_direction') return value === 'ASC' ? I18N.gallery.sort_asc : I18N.gallery.sort_desc;
    if (key === 'review_status') return `gallery.sidebar.review.values.${value}`;
    if (key === 'type') return value === 'top_picks' ? 'photo_types.top_picks' : `category_names.${value}`;
    if (value === 'true' || value === 'false') return value === 'true' ? I18N.organization_history.yes : I18N.organization_history.no;
    if (key === 'date_from' || key === 'date_to') return this.date.transform(value);
    return value;
  }
}
