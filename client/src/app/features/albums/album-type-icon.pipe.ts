import { Pipe, PipeTransform } from '@angular/core';
import { FEATURE_MARK, MarkTonePipe } from '../../shared/pipes/mark-tone.pipe';
import { SortOptionIcon } from '../../shared/pipes/sort-option-icon.pipe';

/** Decorative hints only: the translated option text remains the type's label. */
export const ALBUM_TYPE_ICONS: Readonly<Record<string, string>> = {
  '': 'photo_library',
  manual: 'photo_album',
  smart: FEATURE_MARK,
};

const MARK_TONE = new MarkTonePipe();

@Pipe({ name: 'albumTypeIcon', standalone: true, pure: true })
export class AlbumTypeIconPipe implements PipeTransform {
  transform(type: string): SortOptionIcon {
    if (!Object.hasOwn(ALBUM_TYPE_ICONS, type)) return { text: ALBUM_TYPE_ICONS[''], classes: '' };
    return { text: ALBUM_TYPE_ICONS[type], classes: type === 'smart' ? MARK_TONE.transform('smart') : '' };
  }
}
