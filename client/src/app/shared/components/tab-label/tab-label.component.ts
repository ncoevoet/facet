import { afterNextRender, ChangeDetectionStrategy, Component, DestroyRef, inject, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SM_BREAKPOINT_PX, useDesktopSignal } from '../../utils/media-query';

/**
 * A page tab's icon and name. Below `sm` only the icon shows: the name stays the
 * tab's accessible name and becomes its tooltip, so the tabs fit a phone on one row.
 */
@Component({
  selector: 'app-tab-label',
  imports: [MatIconModule, MatTooltipModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'inline-flex' },
  template: `
    <span data-tab-label class="pointer-events-auto inline-flex items-center gap-2" [matTooltip]="hint() || label()" [matTooltipDisabled]="!hint() && wide()">
      <mat-icon aria-hidden="true">{{ icon() }}</mat-icon>
      <span data-tab-name class="whitespace-nowrap max-sm:sr-only">{{ label() }}</span>
    </span>
  `,
})
export class TabLabelComponent {
  readonly icon = input.required<string>();
  /** The translated tab name. */
  readonly label = input.required<string>();
  /** A tooltip shown at every width in place of the name, such as why the tab is disabled. */
  readonly hint = input('');
  private readonly breakpoint = useDesktopSignal({ breakpointPx: SM_BREAKPOINT_PX });
  protected readonly wide = this.breakpoint.isDesktop;

  constructor() {
    afterNextRender(() => this.breakpoint.setup());
    inject(DestroyRef).onDestroy(() => this.breakpoint.cleanup());
  }
}

/** Tab-group classes that share a phone's width between icon-only tabs instead of scrolling them. */
export const COMPACT_PAGE_TABS = 'max-sm:[&_.mat-mdc-tab]:!min-w-0 max-sm:[&_.mat-mdc-tab]:!px-0 max-sm:[&_.mat-mdc-tab]:!flex-[1_1_auto] max-sm:[&_.mat-mdc-tab-labels]:!flex-[1_1_0%]';
