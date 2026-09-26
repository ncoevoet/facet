import { Pipe, PipeTransform } from '@angular/core';

import { I18N } from '../../core/i18n/keys';
import { SEQUENCE_KIND_ICONS, SEQUENCE_KIND_LABELS } from './sequence-kind.pipe';

/**
 * Every kind of multi-frame set a photo can belong to, as resolved by
 * `GET /api/photo/set`: the three deliberate sequence kinds plus the two
 * derived groupings that endpoint also reports. Composes
 * SEQUENCE_KIND_ICONS/LABELS rather than duplicating them, so a sequence-kind
 * icon or label still changes in one place -- burst and duplicate have no
 * `sequence_kind` counterpart to reuse, since neither is a value that column
 * can hold.
 */
export const PHOTO_SET_KIND_ICONS: Record<string, string> = {
  ...SEQUENCE_KIND_ICONS,
  burst: 'burst_mode',
  duplicate: 'content_copy',
};

export const PHOTO_SET_KIND_LABELS: Record<string, string> = {
  ...SEQUENCE_KIND_LABELS,
  burst: I18N.culling.type_burst,
  duplicate: I18N.photo_detail.set.kind_duplicate,
};

/** Material icon for a photo-set kind, or '' when it names no known kind. */
@Pipe({ name: 'photoSetKindIcon', standalone: true })
export class PhotoSetKindIconPipe implements PipeTransform {
  transform(kind: string | null | undefined): string {
    return (kind && PHOTO_SET_KIND_ICONS[kind]) || '';
  }
}

/** Translation key naming a photo-set kind, or '' when it names no known kind. */
@Pipe({ name: 'photoSetKindLabel', standalone: true })
export class PhotoSetKindLabelPipe implements PipeTransform {
  transform(kind: string | null | undefined): string {
    return (kind && PHOTO_SET_KIND_LABELS[kind]) || '';
  }
}

/**
 * Translation key for the "Best of <kind>" tile badge -- distinct from
 * PHOTO_SET_KIND_LABELS, which the tooltip and photo-detail panel use to say
 * "Burst"/"Duplicate" on their own (correct there, but not what the tile
 * badge means: this tile is the representative frame picked over the rest of
 * the set).
 */
export const PHOTO_SET_KIND_BEST_LABELS: Record<string, string> = {
  bracket: I18N.ui.badges.best_of_bracket,
  panorama: I18N.ui.badges.best_of_panorama,
  hdr_panorama: I18N.ui.badges.best_of_hdr_panorama,
  burst: I18N.ui.badges.best_of_burst,
  duplicate: I18N.ui.badges.best_of_duplicate,
};

/** Translation key for the "Best of <kind>" badge, or '' when it names no known kind. */
@Pipe({ name: 'photoSetKindBestLabel', standalone: true })
export class PhotoSetKindBestLabelPipe implements PipeTransform {
  transform(kind: string | null | undefined): string {
    return (kind && PHOTO_SET_KIND_BEST_LABELS[kind]) || '';
  }
}
