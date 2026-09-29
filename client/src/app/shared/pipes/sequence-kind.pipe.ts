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

/**
 * Sets whose frames were shot to be combined: kept whole by default, and never
 * a source of comparison pairs. Shared by every surface that must treat a
 * bracket/panorama/hdr_panorama set as a unit -- the gallery's and
 * photo-detail's delete guards (a lone frame from one of these sets cannot be
 * deleted without pulling in the rest), and the culling darkroom's own
 * `_KEEP_WHOLE_KINDS`.
 *
 * Kept as `readonly string[]` rather than `SequenceKind[]` for historical
 * reasons only -- the two lists happen to name the same three kinds today.
 * `bracket` WAS excluded from `SequenceKind` on the premise that a bracket's
 * membership is a physical fact of the exposures (`sequence_ev_offset`), never
 * a movable override; #162 overturned that premise for the case of a missed
 * bracket the detector never grouped, so `SequenceKind` (and
 * `SequenceOverrideService.set`) now cover `bracket` too, mirroring the
 * existing panorama correction.
 */
export const SEQUENCE_KINDS_KEPT_WHOLE: readonly string[] = ['bracket', 'panorama', 'hdr_panorama'];

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

/**
 * Translation key for the photo-card's pending-override badge tooltip, keyed
 * off the override value a photo carries (`sequence_override`) -- never a
 * template method call. `'suppressed'` has no kind to name, so it keeps its
 * own generic wording; `'bracket'` gets its own wording because "marked as a
 * panorama" would misdescribe it; every other forced kind (`panorama`,
 * `hdr_panorama`) still reads the original generic badge key.
 */
@Pipe({ name: 'sequenceOverrideBadgeKey', standalone: true })
export class SequenceOverrideBadgeKeyPipe implements PipeTransform {
  transform(override: string | null | undefined): string {
    if (!override) return '';
    if (override === SUPPRESSED_OVERRIDE) return I18N.gallery.sequence_override.badge_suppressed;
    if (override === 'bracket') return I18N.gallery.sequence_override.badge_bracket;
    return I18N.gallery.sequence_override.badge;
  }
}
