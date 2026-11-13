import { Pipe, PipeTransform } from '@angular/core';
import { I18N } from '../../core/i18n/keys';

export type ExifCodeKind = 'flash' | 'whiteBalance' | 'metering';

const WHITE_BALANCE: Record<number, string> = { 0: I18N.tooltip.white_balance_auto, 1: I18N.tooltip.white_balance_manual };
const METERING: Record<number, string> = {
  0: I18N.tooltip.metering_unknown, 1: I18N.tooltip.metering_average, 2: I18N.tooltip.metering_center_weighted,
  3: I18N.tooltip.metering_spot, 4: I18N.tooltip.metering_multi_spot, 5: I18N.tooltip.metering_pattern,
  6: I18N.tooltip.metering_partial, 255: I18N.tooltip.metering_other,
};

/**
 * A raw EXIF code as an i18n key for the `translate` pipe; an unmapped code comes
 * back as its number, which `translate` renders as is. Flash reads bit 0 only
 * (fired / did not fire): the rest of the bitfield is noise for a viewer.
 */
@Pipe({ name: 'exifCode' })
export class ExifCodePipe implements PipeTransform {
  transform(code: number | null | undefined, kind: ExifCodeKind): string {
    if (code == null) return '';
    if (kind === 'flash') return code & 1 ? I18N.tooltip.flash_fired : I18N.tooltip.flash_off;
    return (kind === 'whiteBalance' ? WHITE_BALANCE : METERING)[code] ?? String(code);
  }
}
