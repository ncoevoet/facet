import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { MAT_DATE_FORMATS, type MatDateFormats } from '@angular/material/core';
import { MatDatepickerModule, type MatDatepicker } from '@angular/material/datepicker';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

/** Month-and-year display only here: the Dates popover keeps the app-wide format for its range fields. */
const MONTH_FORMATS: MatDateFormats = {
  parse: { dateInput: null },
  display: { dateInput: { year: 'numeric', month: 'long' }, monthYearLabel: { year: 'numeric', month: 'short' },
    dateA11yLabel: { year: 'numeric', month: 'long', day: 'numeric' }, monthYearA11yLabel: { year: 'numeric', month: 'long' } },
};

@Component({
  selector: 'app-timeline-month-jump',
  standalone: true,
  imports: [MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatDatepickerModule, MatTooltipModule, TranslatePipe],
  providers: [{ provide: MAT_DATE_FORMATS, useValue: MONTH_FORMATS }],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block shrink-0' },
  template: `
    @if (compact()) {
      <!-- The datepicker needs an input to anchor to; this one is invisible and sits under the button, so the popup opens beside it -->
      <span class="relative inline-flex">
        <input readonly tabindex="-1" aria-hidden="true" class="pointer-events-none absolute inset-0 opacity-0" [matDatepicker]="picker" [disabled]="disabled()" [value]="value()" />
        <button mat-icon-button type="button" data-month-jump-compact class="!h-11 !w-11" [disabled]="disabled()"
                [matTooltip]="I18N.timeline.jump_month | translate" [attr.aria-label]="I18N.timeline.jump_month | translate" (click)="picker.open()">
          <mat-icon>move_down</mat-icon>
        </button>
        <mat-datepicker #picker startView="multi-year" (monthSelected)="select($event, picker)" />
      </span>
    } @else {
      <mat-form-field class="w-48" subscriptSizing="dynamic">
        <mat-label>{{ I18N.timeline.jump_month | translate }}</mat-label>
        <input matInput readonly [matDatepicker]="picker" [disabled]="disabled()" [value]="value()" (click)="picker.open()" />
        <mat-datepicker-toggle matIconSuffix [for]="picker" [attr.aria-label]="I18N.timeline.jump_month | translate" />
        <mat-datepicker #picker startView="multi-year" (monthSelected)="select($event, picker)" />
      </mat-form-field>
    }
  `,
})
export class TimelineMonthJumpComponent {
  protected readonly I18N = i18nKeys();
  private readonly router = inject(Router);
  readonly year = input('');
  readonly month = input('');
  /** The route is not the timeline's (or a navigation is pending): picking must not start another one. */
  readonly disabled = input(false);
  /** An icon button instead of the labelled field, for the phone bottom bar. */
  readonly compact = input(false);
  protected readonly value = computed(() => this.year() && this.month() ? new Date(+this.year(), +this.month() - 1, 1) : null);

  protected select(date: Date, picker: MatDatepicker<Date>): void {
    picker.close();
    if (!this.disabled()) void this.router.navigate(['/timeline', String(date.getFullYear()), String(date.getMonth() + 1)]);
  }
}
