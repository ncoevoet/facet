import { Pipe, PipeTransform } from '@angular/core';

/**
 * Whether a persisted filter-sidebar section is open: a stored value wins, an unset one
 * falls back to `defaultOpen`, and `allOpen` (a saved view showing its panels) forces it.
 */
@Pipe({ name: 'sectionOpen', standalone: true, pure: true })
export class SectionOpenPipe implements PipeTransform {
  transform(states: Readonly<Record<string, boolean>>, key: string, defaultOpen: boolean, allOpen = false): boolean {
    if (allOpen) return true;
    const stored = states[key];
    return stored === undefined ? defaultOpen : stored;
  }
}
