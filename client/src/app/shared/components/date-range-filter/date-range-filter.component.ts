import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { TranslatePipe } from '../../pipes/translate.pipe';

/**
 * A from/to date-range pair of Material date inputs, shared by the stats,
 * timeline, map, and capsule toolbars (previously duplicated inline in
 * app.html). The host uses `display: contents` so the two form fields remain
 * direct children of the parent flex container in both the desktop toolbar and
 * the mobile bottom bar. Labels are i18n keys; class inputs let each call site
 * keep its own responsive styling.
 */
@Component({
  selector: 'app-date-range-filter',
  imports: [MatFormFieldModule, MatInputModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'contents' },
  template: `
    <mat-form-field [class]="fromClass()" subscriptSizing="dynamic">
      <mat-label>{{ fromLabel() | translate }}</mat-label>
      <input matInput type="date" [value]="from()" (change)="onInput('from', $event)" />
    </mat-form-field>
    <mat-form-field [class]="toClass() || fromClass()" subscriptSizing="dynamic">
      <mat-label>{{ toLabel() | translate }}</mat-label>
      <input matInput type="date" [value]="to()" (change)="onInput('to', $event)" />
    </mat-form-field>
  `,
})
export class DateRangeFilterComponent {
  readonly from = input('');
  readonly to = input('');
  readonly fromLabel = input('ui.labels.from');
  readonly toLabel = input('ui.labels.to');
  readonly fromClass = input('w-44');
  /** Falls back to fromClass when empty — lets the "to" field drop a leading margin. */
  readonly toClass = input('');
  readonly fromChange = output<string>();
  readonly toChange = output<string>();

  protected onInput(which: 'from' | 'to', event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    (which === 'from' ? this.fromChange : this.toChange).emit(value);
  }
}
