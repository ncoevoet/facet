import { inject, Pipe, PipeTransform } from '@angular/core';
import { i18nKeys } from '../../core/i18n/keys';
import { I18nService } from '../../core/services/i18n.service';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { DEFAULT_FILTERS } from './gallery-filters.util';
import { GalleryStore } from './gallery.store';

@Pipe({ name: 'albumRuleValue', pure: false })
export class AlbumRuleValuePipe implements PipeTransform {
  private readonly i18n = inject(I18nService);
  private readonly store = inject(GalleryStore);
  private readonly date = new CaptureDatePipe();
  transform(value: string, key: string): string {
    const I18N = i18nKeys();
    if (!value) return this.i18n.t(I18N.albums.rules.any);
    if (typeof DEFAULT_FILTERS[key as keyof typeof DEFAULT_FILTERS] === 'boolean' && (value === 'true' || value === 'false')) {
      return this.i18n.t(value === 'true' ? I18N.organization_history.yes : I18N.organization_history.no);
    }
    if (key === 'person_id') {
      // `person_id` is a comma-separated id list; each id reads as its own name.
      const persons = this.store.persons();
      return value.split(',').map(raw => raw.trim()).filter(Boolean).map(id =>
        persons.find(person => String(person.id) === id)?.name || this.i18n.t(I18N.albums.rules.person_fallback, { id })).join(', ');
    }
    if (key === 'date_from' || key === 'date_to') return this.date.transform(value);
    const enumKeys: Record<string, string> = {
      sort: `sort_options.${value}`, sort_direction: value === 'ASC' ? I18N.gallery.sort_asc : value === 'DESC' ? I18N.gallery.sort_desc : '',
      review_status: `gallery.sidebar.review.values.${value}`,
      type: value === 'top_picks' ? 'photo_types.top_picks' : `category_names.${value}`,
      person_match: `gallery.people_match.${value}`, composition_pattern: `composition_patterns.${value}`,
      sequence_override: `gallery.sequence_override.${value}`, color_temp: `gallery.color_temps.${value}`,
      hue_bucket: `gallery.hue_buckets.${value}`, quality_tier: `gallery.quality_tiers.${value}`,
    };
    const translationKey = enumKeys[key];
    if (!translationKey) return value;
    const translated = this.i18n.t(translationKey);
    return translated === translationKey ? value : translated;
  }
}
