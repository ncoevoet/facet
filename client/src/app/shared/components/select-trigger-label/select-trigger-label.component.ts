import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import type { SortOptionIcon } from '../../pipes/sort-option-icon.pipe';

/** Icon classes that keep a /stats select's trigger aligned with its options' icons. */
export const SELECT_TRIGGER_STATS_ICON = '!w-8 shrink-0 text-center';

/**
 * The content of a `mat-select-trigger`: an option's icon followed by its truncating label.
 * The label is projected; `icon` is what the `sortOptionIcon` / `albumTypeIcon` pipes return.
 */
@Component({
  selector: 'app-select-trigger-label',
  imports: [MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'inline-flex max-w-full items-center align-top' },
  template: `
    <mat-icon aria-hidden="true" [class]="iconClass() + ' ' + icon().classes">{{ icon().text }}</mat-icon>
    <span class="truncate"><ng-content /></span>
  `,
})
export class SelectTriggerLabelComponent {
  readonly icon = input.required<SortOptionIcon>();
  /** Layout classes for the icon, matching the select's own options. */
  readonly iconClass = input(SELECT_TRIGGER_STATS_ICON);
}
