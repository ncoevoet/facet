import { Pipe, PipeTransform } from '@angular/core';

/** Returns true when the string looks like a real lens name (contains "mm" or "f/"). */
@Pipe({ name: 'isLensName' })
export class IsLensNamePipe implements PipeTransform {
  transform(value: string | null): boolean {
    return value != null && (/mm\b/i.test(value) || /f\//i.test(value));
  }
}
