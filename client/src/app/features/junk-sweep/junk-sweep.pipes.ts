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

const KIND_ICONS: Record<string, string> = {
  any: 'filter_alt',
  screenshot: 'screenshot',
  document: 'description',
  receipt: 'receipt_long',
  meme: 'mood',
  slide: 'slideshow',
};

/**
 * Map a junk-kind key (or the "any" filter sentinel) to a Material icon name for
 * the header filter menu and its trigger. Unknown kinds fall back to a generic
 * image glyph.
 */
@Pipe({ name: 'junkKindIcon' })
export class JunkKindIconPipe implements PipeTransform {
  transform(kind: string | null | undefined): string {
    return (kind && KIND_ICONS[kind]) || 'image';
  }
}
