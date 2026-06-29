import { Injectable, signal, TemplateRef } from '@angular/core';

/**
 * Lets a routed feature page project a cluster of controls into the global
 * toolbar. The page registers an <ng-template> on view init and clears it on
 * destroy; the shell renders it on large screens while the page renders the
 * same template in its own bottom bar on small screens.
 */
@Injectable({ providedIn: 'root' })
export class HeaderSlotService {
  readonly template = signal<TemplateRef<unknown> | null>(null);

  set(template: TemplateRef<unknown>): void {
    this.template.set(template);
  }

  clear(template: TemplateRef<unknown>): void {
    if (this.template() === template) {
      this.template.set(null);
    }
  }
}
