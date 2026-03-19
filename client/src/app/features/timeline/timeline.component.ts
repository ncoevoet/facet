import { Component, inject, computed } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
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
    <nav class="flex items-center gap-1 px-4 pt-3 pb-2 text-sm flex-wrap">
      @switch (level()) {
        @case ('years') {
          <span class="font-medium">{{ 'timeline.years_title' | translate }}</span>
        }
        @case ('months') {
          <button mat-button class="!min-w-0 !px-2" (click)="goToYears()">
            {{ 'timeline.all_years' | translate }}
          </button>
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          <span class="px-2 font-medium">{{ year() }}</span>
        }
        @case ('days') {
          <button mat-button class="!min-w-0 !px-2" (click)="goToYears()">
            {{ 'timeline.all_years' | translate }}
          </button>
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          <button mat-button class="!min-w-0 !px-2" (click)="goToMonths()">
            {{ year() }}
          </button>
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          <span class="px-2 font-medium">{{ selectedMonthFormatted() | timelineDate }}</span>
        }
      }
    </nav>

    <div class="px-4 pb-4">
      @switch (level()) {
        @case ('years') {
          <app-timeline-years (yearSelected)="onYearSelected($event)" />
        }
        @case ('months') {
          <app-timeline-months
            [year]="year()"
            (monthSelected)="onMonthSelected($event)" />
        }
        @case ('days') {
          <app-timeline-days
            [year]="year()"
            [month]="month()"
            (daySelected)="onDaySelected($event)" />
        }
      }
    </div>
  `,
})
export class TimelineComponent {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  protected readonly filters = inject(TimelineFiltersService);

  private readonly routeParams = toSignal(this.route.paramMap.pipe(
    map(p => ({ year: p.get('year') ?? '', month: p.get('month') ?? '' })),
  ), { initialValue: { year: '', month: '' } });

  protected readonly year = computed(() => this.routeParams().year);
  protected readonly month = computed(() => this.routeParams().month);
  protected readonly level = computed<'years' | 'months' | 'days'>(() => {
    if (this.month()) return 'days';
    if (this.year()) return 'months';
    return 'years';
  });

  /** Reconstruct YYYY-MM string for the timelineDatePipe. */
  protected readonly selectedMonthFormatted = computed(() => {
    const y = this.year();
    const m = this.month();
    if (!y || !m) return '';
    return `${y}-${m.padStart(2, '0')}`;
  });

  protected goToYears(): void {
    this.router.navigate(['/timeline']);
  }

  protected goToMonths(): void {
    this.router.navigate(['/timeline', this.year()]);
  }

  protected onYearSelected(year: string): void {
    this.router.navigate(['/timeline', year]);
  }

  protected onMonthSelected(month: string): void {
    // month comes as "YYYY-MM" from the months component
    const parts = month.split('-');
    const monthNum = parts.length > 1 ? String(+parts[1]) : month;
    this.router.navigate(['/timeline', this.year(), monthNum]);
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
