import { Pipe, PipeTransform } from '@angular/core';

/** The directory part of a file path, for both `/` and `\` separators; empty when the path has none. */
@Pipe({ name: 'folderPath' })
export class FolderPathPipe implements PipeTransform {
  transform(path: string | null | undefined): string {
    if (!path) return '';
    const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
    if (cut < 0) return '';
    return cut === 0 ? path.charAt(0) : path.slice(0, cut);
  }
}
