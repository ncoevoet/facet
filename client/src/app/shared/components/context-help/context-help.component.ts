import { ChangeDetectionStrategy, Component, input, signal } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { I18N } from '../../../core/i18n/keys';
import { TranslatePipe } from '../../pipes/translate.pipe';

/** Help occupies space only after an explicit request; Escape belongs to it first. */
@Component({
  selector: 'app-context-help',
  imports: [MatIconModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    <details #help data-context-help (toggle)="expanded.set(help.open)"
             (keydown.escape)="help.open && close($event, help, trigger)">
      <summary #trigger class="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded text-xs text-[var(--mat-sys-on-surface-variant)] focus-visible:outline-2">
        <mat-icon aria-hidden="true" class="!h-5 !w-5 !text-xl">info</mat-icon>
        <span>{{ label() | translate }}</span>
      </summary>
      @if (expanded()) {
        <div class="flex items-start gap-2 rounded border border-[var(--mat-sys-outline-variant)] p-2 text-xs text-[var(--mat-sys-on-surface-variant)]">
          <div class="min-w-0 flex-1 space-y-2">
            @for (key of keys(); track key) { <p class="m-0">{{ key | translate }}</p> }
          </div>
          <button type="button" data-context-help-close class="flex min-h-11 min-w-11 cursor-pointer items-center justify-center rounded hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2"
                  [attr.aria-label]="I18N.dialog.close | translate" (click)="close($event, help, trigger)"><mat-icon aria-hidden="true">close</mat-icon></button>
        </div>
      }
    </details>
  `,
})
export class ContextHelpComponent {
  protected readonly I18N = I18N;
  readonly label = input.required<string>();
  readonly keys = input.required<readonly string[]>();
  protected readonly expanded = signal(false);

  protected close(event: Event, help: HTMLDetailsElement, trigger: HTMLElement): void {
    event.preventDefault();
    event.stopPropagation();
    help.open = false;
    this.expanded.set(false);
    trigger.focus();
  }
}
