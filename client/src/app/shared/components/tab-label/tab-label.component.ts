import { afterNextRender, ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { DEFAULT_BREAKPOINT_PX, useDesktopSignal } from '../../utils/media-query';

/**
 * A page tab's icon and name. Below `md` only the icon shows: the name stays the
 * tab's accessible name and becomes its tooltip, so the tabs fit one row up to a portrait tablet.
 * A hint replaces the tooltip from `md` up; below it the name stays on the first line.
 */
@Component({
  selector: 'app-tab-label',
  imports: [MatIconModule, MatTooltipModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'inline-flex' },
  template: `
    <span data-tab-label class="pointer-events-auto inline-flex items-center gap-2" [matTooltip]="tooltip()" matTooltipClass="whitespace-pre-line" [matTooltipDisabled]="!tooltip()">
      <mat-icon aria-hidden="true">{{ icon() }}</mat-icon>
      <span data-tab-name class="whitespace-nowrap max-md:sr-only">{{ label() }}</span>
    </span>
  `,
})
export class TabLabelComponent {
  readonly icon = input.required<string>();
  /** The translated tab name. */
  readonly label = input.required<string>();
  /** A tooltip shown at every width, such as why the tab is disabled. */
  readonly hint = input('');
  private readonly breakpoint = useDesktopSignal({ breakpointPx: DEFAULT_BREAKPOINT_PX });
  protected readonly tooltip = computed(() => {
    if (this.breakpoint.isDesktop()) return this.hint();
    return this.hint() ? `${this.label()}\n${this.hint()}` : this.label();
  });

  constructor() {
    afterNextRender(() => this.breakpoint.setup());
    inject(DestroyRef).onDestroy(() => this.breakpoint.cleanup());
  }
}

/** Tab-group classes that share a narrow screen's width between icon-only tabs instead of scrolling them. */
export const COMPACT_PAGE_TABS = 'max-md:[&_.mat-mdc-tab]:!min-w-0 max-md:[&_.mat-mdc-tab]:!px-0 max-md:[&_.mat-mdc-tab]:!flex-[1_1_auto] max-md:[&_.mat-mdc-tab-labels]:!flex-[1_1_0%]';
