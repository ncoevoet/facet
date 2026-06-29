import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class PageHelpService {
  /** Whether the global help panel is shown (toggled by the header button). */
  readonly open = signal(false);
  /** i18n key of the current page's help description (null = no help). */
  readonly descriptionKey = signal<string | null>(null);

  setDescription(key: string | null): void {
    this.descriptionKey.set(key);
  }

  toggle(): void {
    this.open.update(v => !v);
  }
}
