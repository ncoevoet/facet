import { NgTemplateOutlet } from '@angular/common';
import { Component, inject, computed, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TimelineFiltersService } from './timeline-filters.service';
import { registerPageContext } from '../../core/agent/page-context.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { TimelineYearsComponent } from './timeline-years.component';
import { TimelineMonthsComponent } from './timeline-months.component';
import { TimelineDaysComponent } from './timeline-days.component';
import { TimelineDatePipe } from './timeline-date.pipe';
import { TimelineFeedComponent } from './timeline-feed.component';
import { timelineDayQuery, timelineGalleryQuery, timelineRangeQuery } from './timeline-day-query.pipe';
import { TimelineDensityComponent } from './timeline-density.component';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { timelineWindow } from './timeline-density.util';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { PageHelpService } from '../../core/services/page-help.service';
import { DateRangeFilterComponent } from '../../shared/components/date-range-filter/date-range-filter.component';
import { GalleryStore, anyHideToggleActive } from '../gallery/gallery.store';

@Component({
  selector: 'app-timeline',
  standalone: true,
  imports: [
    NgTemplateOutlet,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    TranslatePipe,
    TimelineYearsComponent,
    TimelineMonthsComponent,
    TimelineDaysComponent,
    TimelineDatePipe,
    TimelineFeedComponent,
    TimelineDensityComponent,
    CaptureDatePipe,
    DateRangeFilterComponent,
  ],
  host: { class: 'block h-full overflow-auto' },
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <ng-template #timelineToolbar>
      @if (anyHiddenByFilters()) {
        <button mat-button class="!min-w-0"
                [matTooltip]="I18N.gallery.hidden_banner.some_hidden | translate"
                (click)="store.showAllHidden()">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">visibility_off</mat-icon>
          {{ I18N.gallery.hidden_banner.show_all | translate }}
        </button>
      } @else if (store.hiddenFiltersStash()) {
        <button mat-button class="!min-w-0"
                [matTooltip]="I18N.gallery.hidden_banner.showing_all | translate"
                (click)="store.restoreHidden()">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">visibility</mat-icon>
          {{ I18N.gallery.hidden_banner.restore | translate }}
        </button>
      }
    </ng-template>
    @if (anyHiddenByFilters() || store.hiddenFiltersStash()) {
      <div class="px-2"><ng-container [ngTemplateOutlet]="timelineToolbar" /></div>
    }
    <details class="mx-4 mt-1 border-b border-[var(--mat-sys-outline-variant)] pb-2">
      <summary class="cursor-pointer text-sm leading-6">{{ I18N.timeline.capture_scope | translate }}</summary>
      <p class="my-2 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.timeline.scope_help | translate }}</p>
      <div class="flex flex-wrap items-center gap-2">
        <app-date-range-filter [compact]="true"
          [from]="filters.dateFrom()" [to]="filters.dateTo()"
          fromClass="w-40" toClass="w-40"
          (fromChange)="filters.dateFrom.set($event)" (toChange)="filters.dateTo.set($event)" />
        <button mat-button [disabled]="emptyRange()" [attr.aria-describedby]="emptyRange() ? 'timeline-empty-range' : null" (click)="viewRange()">{{ I18N.timeline.open_range | translate }}</button>
        <button mat-button (click)="resetDates()">{{ I18N.timeline.all_dates | translate }}</button>
        <button mat-button (click)="viewUnknownDates()">{{ I18N.gallery.no_capture_date | translate }}</button>
      </div>
      @if (emptyRange()) {
        <p id="timeline-empty-range" role="status" class="mt-2 text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.timeline.empty_range | translate }}</p>
      }
    </details>
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

    <div class="px-4 pb-2" [class.pt-4]="level() === 'years'">
      @if (filters.dateFrom() || filters.dateTo()) {
        <div class="flex min-h-11 flex-wrap items-center gap-2 text-sm" role="status">
          <span>{{ filters.dateFrom() ? (filters.dateFrom() | captureDate) : '…' }} – {{ filters.dateTo() ? (filters.dateTo() | captureDate) : '…' }}</span>
          <button mat-button (click)="resetDates()">{{ I18N.timeline.all_dates | translate }}</button>
        </div>
      }
      <app-timeline-density [year]="year()" [month]="month()" />
      <div class="flex items-center justify-end gap-1" role="group" [attr.aria-label]="I18N.timeline.title | translate">
        <button mat-button [attr.aria-pressed]="!showOverview()" (click)="showOverview.set(false)">
          <mat-icon>photo_library</mat-icon>{{ I18N.timeline.photo_feed | translate }}
        </button>
        <button mat-button [attr.aria-pressed]="showOverview()" (click)="showOverview.set(true)">
          <mat-icon>calendar_month</mat-icon>{{ I18N.timeline.calendar | translate }}
        </button>
      </div>
      @if (!showOverview()) {
        <app-timeline-feed [year]="year()" [month]="month()" />
      } @else {
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
      }
    </div>
  `,
})
export class TimelineComponent {
  protected readonly I18N = i18nKeys();
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  protected readonly filters = inject(TimelineFiltersService);
  protected readonly showOverview = this.filters.showOverview;
  private readonly pageHelp = inject(PageHelpService);
  protected readonly store = inject(GalleryStore);

  /** At least one hide toggle is on — the years/months/days views can then show a
   *  count of 0 for a bucket whose photos are entirely hidden, and timeline-days
   *  makes a count-0 cell non-clickable, so this is the only way to reach it. */
  protected readonly anyHiddenByFilters = computed(() => anyHideToggleActive(this.store.viewFilterParams()));
  /** Timeline API flags use 1/0; gallery URLs use true/false. */
  private readonly galleryVisibility = computed(() => timelineGalleryQuery(this.store.viewFilterParams()));

  constructor() {
    registerPageContext('timeline', () => ({
      date_from: this.filters.dateFrom(),
      date_to: this.filters.dateTo(),
      sort: this.filters.sortDirection(),
    }));
    this.pageHelp.setDescription(I18N.timeline.help);
    inject(DestroyRef).onDestroy(() => {
      this.pageHelp.setDescription(null);
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
      queryParams: timelineDayQuery(date, this.store.viewFilterParams()),
    });
  }

  private readonly selectedRange = computed(() =>
    timelineWindow(this.year(), this.month(), this.filters.dateFrom(), this.filters.dateTo()));
  protected readonly emptyRange = computed(() => {
    const { from, to } = this.selectedRange();
    return !!from && !!to && from > to;
  });

  protected viewRange(): void {
    if (this.emptyRange()) return;
    const range = this.selectedRange();
    this.router.navigate(['/'], { queryParams:
      timelineRangeQuery(range.from, range.to, this.store.viewFilterParams(), 'DESC'),
    });
  }

  protected viewUnknownDates(): void {
    this.router.navigate(['/'], { queryParams: {
      ...this.galleryVisibility(), no_capture_date: '1',
      sort: 'filename', sort_direction: 'ASC',
    } });
  }

  protected resetDates(): void {
    this.filters.dateFrom.set('');
    this.filters.dateTo.set('');
    this.router.navigate(['/timeline']);
  }
}
