import { Pipe, PipeTransform } from '@angular/core';

import { I18N } from '../../core/i18n/keys';

/**
 * The deliberate multi-frame set kinds a photo can belong to.
 *
 * Lives in shared rather than beside the culling pipes because the gallery tile
 * needs it too, and shared must not depend on a feature. Every place that draws
 * a kind reads these maps -- tile badge, culling group header and its relabel
 * menu, the gallery selection actions -- so an icon changes in one edit. Chrome
 * that merely alludes to the feature, such as the settings tab's own icon, is
 * deliberately not routed through here: it names no kind.
 */
export const SEQUENCE_KIND_ICONS: Record<string, string> = {
  bracket: 'hdr_on',
  panorama: 'panorama_photosphere',
  hdr_panorama: 'vrpano',
};

export const SEQUENCE_KIND_LABELS: Record<string, string> = {
  bracket: I18N.culling.bracket.label,
  panorama: I18N.culling.panorama.label,
  hdr_panorama: I18N.culling.panorama.hdr_label,
};

/**
 * The `sequence_override` value standing for "this is not a set".
 *
 * A correction can force a kind or deny one; the denial has no kind to name, so
 * the API reports this sentinel where the others report the forced kind.
 */
export const SUPPRESSED_OVERRIDE = 'suppressed';

/** Material icon for a photo's sequence kind, or '' when it belongs to no set. */
@Pipe({ name: 'sequenceKindIcon', standalone: true })
export class SequenceKindIconPipe implements PipeTransform {
  transform(kind: string | null | undefined): string {
    return (kind && SEQUENCE_KIND_ICONS[kind]) || '';
  }
}

/** Translation key naming a photo's sequence kind, or '' when it belongs to no set. */
@Pipe({ name: 'sequenceKindLabel', standalone: true })
export class SequenceKindLabelPipe implements PipeTransform {
  transform(kind: string | null | undefined): string {
    return (kind && SEQUENCE_KIND_LABELS[kind]) || '';
  }
}
