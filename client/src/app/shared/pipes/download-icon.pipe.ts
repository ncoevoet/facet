import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'downloadIcon', standalone: true, pure: true })
export class DownloadIconPipe implements PipeTransform {
  transform(type: string): string {
    switch (type) {
      case 'darktable': return 'photo_filter';
      case 'raw': return 'raw_on';
      default: return 'image';
    }
  }
}
