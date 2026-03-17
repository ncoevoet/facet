import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { TimelineFiltersService } from './timeline-filters.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { TimelineYearsComponent } from './timeline-years.component';
import { TimelineMonthsComponent } from './timeline-months.component';
import { TimelineDaysComponent } from './timeline-days.component';
import { TimelineDatePipe } from './timeline-date.pipe';

@Component({
  selector: 'app-timeline',
  standalone: true,
  imports: [
    MatIconModule,
    MatButtonModule,
    TranslatePipe,
    TimelineYearsComponent,
    TimelineMonthsComponent,
    TimelineDaysComponent,
    TimelineDatePipe,
  ],
  host: { class: 'block h-full overflow-auto' },
  template: `
    <!-- Breadcrumb navigation -->
    <nav class="flex items-center gap-1 px-4 pt-3 pb-2 max-w-[1800px] mx-auto text-sm flex-wrap">
      @switch (level()) {
        @case ('years') {
          <span class="font-medium">{{ 'timeline.years_title' | translate }}</span>
        }
        @case ('months') {
          <button mat-button class="!min-w-0 !px-2" (click)="goToYears()">
            {{ 'timeline.all_years' | translate }}
          </button>
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          <span class="px-2 font-medium">{{ filters.selectedYear() }}</span>
        }
        @case ('days') {
          <button mat-button class="!min-w-0 !px-2" (click)="goToYears()">
            {{ 'timeline.all_years' | translate }}
          </button>
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          <button mat-button class="!min-w-0 !px-2" (click)="goToMonths()">
            {{ filters.selectedYear() }}
          </button>
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          <span class="px-2 font-medium">{{ filters.selectedMonth() | timelineDate }}</span>
        }
      }
    </nav>

    <div class="px-4 pb-4 max-w-[1800px] mx-auto">
      @switch (level()) {
        @case ('years') {
          <app-timeline-years (yearSelected)="onYearSelected($event)" />
        }
        @case ('months') {
          <app-timeline-months
            [year]="filters.selectedYear()"
            (monthSelected)="onMonthSelected($event)" />
        }
        @case ('days') {
          <app-timeline-days
            [year]="filters.selectedYear()"
            [month]="selectedMonthNumber()"
            (daySelected)="onDaySelected($event)" />
        }
      }
    </div>
  `,
})
export class TimelineComponent {
  private readonly router = inject(Router);
  protected readonly filters = inject(TimelineFiltersService);

  protected readonly level = signal<'years' | 'months' | 'days'>('years');

  protected selectedMonthNumber(): string {
    // Extract month number from "2025-03" → "3"
    const m = this.filters.selectedMonth();
    if (!m) return '';
    const parts = m.split('-');
    return parts.length > 1 ? String(+parts[1]) : '';
  }

  protected goToYears(): void {
    this.level.set('years');
    this.filters.selectedYear.set('');
    this.filters.selectedMonth.set('');
  }

  protected goToMonths(): void {
    this.level.set('months');
    this.filters.selectedMonth.set('');
  }

  protected onYearSelected(year: string): void {
    this.filters.selectedYear.set(year);
    this.level.set('months');
  }

  protected onMonthSelected(month: string): void {
    this.filters.selectedMonth.set(month);
    this.level.set('days');
  }

  protected onDaySelected(date: string): void {
    this.router.navigate(['/'], {
      queryParams: {
        date_from: date,
        date_to: date,
        sort: 'date_taken',
        sort_direction: 'DESC',
      },
    });
  }
}
