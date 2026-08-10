import { Pipe, PipeTransform } from '@angular/core';

import { I18N } from '../../core/i18n/keys';

/**
 * The deliberate multi-frame set kinds a photo can belong to.
 *
 * Lives in shared rather than beside the culling pipes because the gallery tile
 * needs it too, and shared must not depend on a feature. The culling
 * granularity pipes consume these maps so the icon for a panorama is chosen in
 * one place, whether it is labelling a culling group or a single tile.
 */
export const SEQUENCE_KIND_ICONS: Record<string, string> = {
  bracket: 'exposure',
  panorama: 'panorama_photosphere',
  hdr_panorama: 'hdr_on',
};

export const SEQUENCE_KIND_LABELS: Record<string, string> = {
  bracket: I18N.culling.bracket.label,
  panorama: I18N.culling.panorama.label,
  hdr_panorama: I18N.culling.panorama.hdr_label,
};

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
