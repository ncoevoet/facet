import { ControlPopoverComponent } from '../control-popover/control-popover.component';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { TranslatePipe } from '../../pipes/translate.pipe';

/** Help stays one click away without expanding the surrounding layout. */
@Component({
  selector: 'app-context-help',
  imports: [ControlPopoverComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    <app-control-popover [label]="label() | translate" icon="info" [fill]="fill()" [content]="helpContent" />
    <ng-template #helpContent>
      <div data-context-help class="space-y-2 text-xs leading-5 text-[var(--mat-sys-on-surface-variant)]">
        @for (key of keys(); track key) { <p class="m-0">{{ key | translate }}</p> }
      </div>
    </ng-template>
  `,
})
export class ContextHelpComponent {
  readonly label = input.required<string>();
  readonly keys = input.required<readonly string[]>();
  /** Stretch the trigger and widen the panel to the details rail; see ControlPopoverComponent.fill. */
  readonly fill = input(false);
}
