import { ControlPopoverComponent } from '../control-popover/control-popover.component';
import { ChangeDetectionStrategy, Component, input, viewChild } from '@angular/core';
import { TranslatePipe } from '../../pipes/translate.pipe';

/** Help stays one click away without expanding the surrounding layout. */
@Component({
  selector: 'app-context-help',
  imports: [ControlPopoverComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0', '[class.!inline-flex]': 'iconOnly()', '[class.shrink-0]': 'iconOnly()' },
  template: `
    <app-control-popover [label]="label() | translate" [icon]="iconOnly() ? 'help_outline' : 'info'" [iconOnly]="iconOnly()" [fill]="fill()" [content]="helpContent" />
    <ng-template #helpContent>
      <div data-context-help class="space-y-2 text-xs leading-5 text-[var(--mat-sys-on-surface-variant)]">
        @for (key of keys(); track key) { <p class="m-0">{{ key | translate:params() }}</p> }
      </div>
    </ng-template>
  `,
})
export class ContextHelpComponent {
  readonly label = input.required<string>();
  readonly keys = input.required<readonly string[]>();
  /** Values for the placeholders in those paragraphs, such as `{max}`. */
  readonly params = input<Record<string, string | number>>({});
  /** Stretch the trigger and widen the panel to the details rail; see ControlPopoverComponent.fill. */
  readonly fill = input(false);
  /** A help_outline icon beside the heading or value it explains, named by its tooltip and aria-label. */
  readonly iconOnly = input(false);
  private readonly popover = viewChild.required(ControlPopoverComponent);

  /** Close the panel, for a host that hides behind another page. */
  close(): void {
    this.popover().open.set(false);
  }

  hideTooltips(): void {
    this.popover().hideTooltips();
  }
}
