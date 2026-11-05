import { Pipe, PipeTransform } from '@angular/core';
import { basename } from '../utils/clipboard';

/** Display a native photo filename while callers retain the original path as identity. */
@Pipe({ name: 'filename', standalone: true, pure: true })
export class FilenamePipe implements PipeTransform {
  transform(path: string, maximumLength?: number): string {
    const name = basename(path);
    const characters = Array.from(name);
    if (!maximumLength || characters.length <= maximumLength) return name;
    const tailLength = Math.ceil((maximumLength - 1) / 2);
    return characters.slice(0, maximumLength - tailLength - 1).join('') + '…' + characters.slice(-tailLength).join('');
  }
}
