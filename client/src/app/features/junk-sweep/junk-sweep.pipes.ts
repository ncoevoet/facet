import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';

/**
 * Translate a junk-kind key ("screenshot") into its localized label
 * ("Screenshots"), falling back to the raw key for any kind absent from the
 * bundles. Impure so it re-renders on a language switch.
 */
@Pipe({ name: 'junkKindLabel', pure: false })
export class JunkKindLabelPipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(kind: string | null | undefined): string {
    if (!kind) return '';
    const key = `junk.kinds.${kind}`;
    const label = this.i18n.t(key);
    return label === key ? kind : label;
  }
}
