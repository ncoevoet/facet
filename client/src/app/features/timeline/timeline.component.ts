import { Component, inject, computed, effect, viewChild, TemplateRef, DestroyRef } from '@angular/core';
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
import { I18N } from '../../core/i18n/keys';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { DateRangeFilterComponent } from '../../shared/components/date-range-filter/date-range-filter.component';

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
    DateRangeFilterComponent,
  ],
  host: { class: 'block h-full overflow-auto' },
  template: `
    <ng-template #timelineToolbar>
      <app-date-range-filter
        [from]="filters.dateFrom()" [to]="filters.dateTo()"
        fromClass="!hidden lg:!inline-flex w-44 ml-2" toClass="!hidden lg:!inline-flex w-44"
        (fromChange)="filters.dateFrom.set($event)" (toChange)="filters.dateTo.set($event)" />
    </ng-template>
    <!-- Breadcrumb navigation -->
    @if (level() !== 'years') {
    <nav class="sticky top-0 z-10 bg-[var(--mat-sys-surface)] flex items-center gap-1 px-4 pt-4 pb-2 text-sm flex-wrap">
      @switch (level()) {
        @case ('months') {
          <button mat-button class="!min-w-0 !px-2" (click)="goToYears()">
            {{ I18N.timeline.all_years | translate }}
          </button>
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          <span class="px-2 font-medium">{{ year() }}</span>
        }
        @case ('days') {
          <button mat-button class="!min-w-0 !px-2" (click)="goToYears()">
            {{ I18N.timeline.all_years | translate }}
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
    }

    <div class="px-4 pb-4" [class.pt-4]="level() === 'years'">
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
  protected readonly I18N = I18N;
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  protected readonly filters = inject(TimelineFiltersService);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly timelineToolbar = viewChild<TemplateRef<unknown>>('timelineToolbar');

  constructor() {
    this.pageHelp.setDescription(I18N.timeline.help);
    effect(() => {
      const t = this.timelineToolbar();
      if (t) this.headerSlot.set(t);
    });
    inject(DestroyRef).onDestroy(() => {
      this.pageHelp.setDescription(null);
      const t = this.timelineToolbar();
      if (t) this.headerSlot.clear(t);
    });
  }

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
