import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';

/** Localized name of a stored scoring category id; falls back to the id itself when no translation exists. */
@Pipe({ name: 'categoryName', standalone: true, pure: false })
export class CategoryNamePipe implements PipeTransform {
  private i18n = inject(I18nService);

  transform(category: string | null | undefined): string {
    if (!category) return '';
    const key = category === 'top_picks' ? 'photo_types.top_picks' : `category_names.${category}`;
    const translated = this.i18n.t(key);
    return translated === key ? category : translated;
  }
}
