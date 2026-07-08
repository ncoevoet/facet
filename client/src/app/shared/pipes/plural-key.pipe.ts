import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'pluralKey', standalone: true, pure: true })
export class PluralKeyPipe implements PipeTransform {
  transform(count: number, singularKey: string, pluralKey: string): string {
    return count === 1 ? singularKey : pluralKey;
  }
}
