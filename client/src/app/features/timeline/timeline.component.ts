import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Component, inject, computed, DestroyRef, ChangeDetectionStrategy, effect, signal, viewChild, TemplateRef } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TIMELINE_CALENDAR_VIEW_KEY, TimelineFiltersService } from './timeline-filters.service';
import { registerPageContext } from '../../core/agent/page-context.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { TimelineYearsComponent } from './timeline-years.component';
import { TimelineMonthsComponent } from './timeline-months.component';
import { TimelineDaysComponent } from './timeline-days.component';
import { TimelineDatePipe } from './timeline-date.pipe';
import { TimelineFeedComponent } from './timeline-feed.component';
import { timelineDayQuery, timelineGalleryQuery, timelineRangeQuery } from './timeline-day-query.pipe';
import { TimelineDensityComponent } from './timeline-density.component';
import { TimelineMonthJumpComponent } from './timeline-month-jump.component';
import { timelineRouteActivity } from './timeline-route-activity';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { timelineWindow } from './timeline-density.util';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { ControlPopoverComponent } from '../../shared/components/control-popover/control-popover.component';
import { PageHelpService } from '../../core/services/page-help.service';
import { DateRangeFilterComponent } from '../../shared/components/date-range-filter/date-range-filter.component';
import { GalleryStore, anyHideToggleActive } from '../gallery/gallery.store';
import { MOBILE_BAR_ROW, XL_LABEL_BUTTON } from '../../shared/utils/mobile-bar';

const DENSITY_HIDDEN_KEY = 'facet_timeline_density_hidden';

function readDensityVisible(): boolean {
  try { return localStorage.getItem(DENSITY_HIDDEN_KEY) !== '1'; } catch { return true; }
}

@Component({
  selector: 'app-timeline',
  standalone: true,
  imports: [
    NgTemplateOutlet,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    TranslatePipe,
    PluralKeyPipe,
    DecimalPipe,
    TimelineMonthJumpComponent,
    TimelineYearsComponent,
    TimelineMonthsComponent,
    TimelineDaysComponent,
    TimelineDatePipe,
    TimelineFeedComponent,
    TimelineDensityComponent,
    CaptureDatePipe,
    DateRangeFilterComponent,
    ControlPopoverComponent,
  ],
  // A flex column so the month calendar can take the height left under the bars; other views grow past it and scroll.
  host: { class: 'flex h-full flex-col overflow-auto' },
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h1 class="sr-only">{{ I18N.timeline.title | translate }}</h1>
    <ng-template #breadcrumb>
      <nav [attr.aria-label]="I18N.timeline.title | translate" class="flex min-w-0 shrink items-center gap-1 overflow-hidden whitespace-nowrap text-sm">
        @switch (level()) {
          @case ('years') {
            <span class="min-w-0 truncate px-2 font-medium">{{ I18N.timeline.all_years | translate }}</span>
          }
          @case ('months') {
            <button mat-button class="!min-w-0 !px-2" (click)="goToYears()">
              {{ I18N.timeline.all_years | translate }}
            </button>
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 shrink-0 opacity-40">chevron_right</mat-icon>
            <span class="min-w-0 truncate px-2 font-medium">{{ year() }}</span>
          }
          @case ('days') {
            <button mat-button class="!min-w-0 !px-2" (click)="goToYears()">
              {{ I18N.timeline.all_years | translate }}
            </button>
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 shrink-0 opacity-40">chevron_right</mat-icon>
            <button mat-button class="!min-w-0 !px-2" (click)="goToMonths()">
              {{ year() }}
            </button>
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 shrink-0 opacity-40">chevron_right</mat-icon>
            <span class="min-w-0 truncate px-2 font-medium">{{ selectedMonthFormatted() | timelineDate }}</span>
          }
        }
      </nav>
      @let total = densityTotal();
      @if (total !== null) {
        <span data-timeline-count class="shrink-0 whitespace-nowrap text-sm tabular-nums text-[var(--mat-sys-on-surface-variant)]">·
          {{ (total | pluralKey:I18N.gallery.photo_count_one:I18N.gallery.photo_count) | translate:{ count: (total | number) ?? '' } }}</span>
      }
    </ng-template>
    <ng-template #viewToggle>
      <div class="flex shrink-0 items-center gap-1" role="group" [attr.aria-label]="I18N.timeline.title | translate">
        <button mat-button class="${XL_LABEL_BUTTON}" [class]="!showOverview() ? '!bg-[var(--mat-sys-secondary-container)]' : ''" [attr.aria-pressed]="!showOverview()"
          [matTooltip]="I18N.timeline.photo_feed | translate" [attr.aria-label]="I18N.timeline.photo_feed | translate" (click)="setCalendarView(false)">
          <mat-icon>photo_library</mat-icon><span class="hidden xl:inline">{{ I18N.timeline.photo_feed | translate }}</span>
        </button>
        <button mat-button class="${XL_LABEL_BUTTON}" [class]="showOverview() ? '!bg-[var(--mat-sys-secondary-container)]' : ''" [attr.aria-pressed]="showOverview()"
          [matTooltip]="I18N.timeline.calendar | translate" [attr.aria-label]="I18N.timeline.calendar | translate" (click)="setCalendarView(true)">
          <mat-icon>calendar_view_month</mat-icon><span class="hidden xl:inline">{{ I18N.timeline.calendar | translate }}</span>
        </button>
      </div>
    </ng-template>
    <ng-template #feedControls let-compact="compact">
      @if (!showOverview()) {
        <app-timeline-month-jump [year]="year()" [month]="month()" [disabled]="!active()" [compact]="!!compact" />
        @let sortLabel = (filters.sortDirection() === 'older' ? I18N.timeline.newest_first : I18N.timeline.oldest_first) | translate;
        <button mat-button class="shrink-0 ${XL_LABEL_BUTTON}" (click)="toggleDirection()" [disabled]="!active()" [matTooltip]="sortLabel" [attr.aria-label]="sortLabel">
          <mat-icon>{{ filters.sortDirection() === 'older' ? 'arrow_downward' : 'arrow_upward' }}</mat-icon><span class="hidden xl:inline">{{ sortLabel }}</span>
        </button>
      }
    </ng-template>
    <ng-template #densityToggle>
      @let densityLabel = (densityVisible() ? I18N.timeline.density_hide : I18N.timeline.density_show) | translate;
      <button mat-button class="shrink-0 ${XL_LABEL_BUTTON}" [class]="densityVisible() ? '!bg-[var(--mat-sys-secondary-container)]' : ''"
        [attr.aria-pressed]="densityVisible()" [matTooltip]="densityLabel" [attr.aria-label]="densityLabel" (click)="toggleDensity()">
        <mat-icon>bar_chart</mat-icon><span class="hidden xl:inline">{{ densityLabel }}</span>
      </button>
    </ng-template>
    <ng-template #datesPanel>
      <div class="flex flex-col gap-3">
        <p class="m-0 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.timeline.scope_help | translate }}</p>
        <div class="flex flex-col gap-2">
          <app-date-range-filter
            [from]="filters.dateFrom()" [to]="filters.dateTo()"
            fromClass="w-full" toClass="w-full"
            (fromChange)="filters.dateFrom.set($event)" (toChange)="filters.dateTo.set($event)" />
        </div>
        <button mat-flat-button class="w-full" [disabled]="emptyRange()" [attr.aria-describedby]="emptyRange() ? 'timeline-empty-range' : null" (click)="viewRange()">{{ I18N.timeline.open_range | translate }}</button>
        @if (emptyRange()) {
          <p id="timeline-empty-range" role="status" class="m-0 text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.timeline.empty_range | translate }}</p>
        }
        <div class="flex flex-col border-t border-[var(--mat-sys-outline-variant)] pt-2">
          <button mat-button class="!justify-start" (click)="resetDates()"><mat-icon>restart_alt</mat-icon>{{ I18N.timeline.all_dates | translate }}</button>
          <button mat-button class="!justify-start" (click)="viewUnknownDates()"><mat-icon>event_busy</mat-icon>{{ I18N.gallery.no_capture_date | translate }}</button>
        </div>
      </div>
    </ng-template>
    <ng-template #datesControl>
      <app-control-popover icon="date_range" [compact]="true" [label]="I18N.timeline.dates | translate" [content]="datesPanel" />
    </ng-template>
    <ng-template #rangeChip>
      @if (filters.dateFrom() || filters.dateTo()) {
        @let range = (filters.dateFrom() ? (filters.dateFrom() | captureDate) : '…') + ' – ' + (filters.dateTo() ? (filters.dateTo() | captureDate) : '…');
        <div data-timeline-range-chip role="status" class="inline-flex shrink-0 items-center gap-1 pl-2.5 pr-1 py-0.5 rounded-full bg-[var(--mat-sys-secondary-container)] text-[var(--mat-sys-on-secondary-container)] text-xs font-medium">
          <span class="mx-0.5 max-w-64 truncate" [title]="range">{{ range }}</span>
          <button
            class="inline-flex items-center justify-center min-w-8 min-h-8 max-sm:min-w-11 max-sm:min-h-11 rounded-full hover:bg-black/20 transition-colors"
            (click)="resetDates()"
            [attr.aria-label]="I18N.gallery.criteria.remove | translate:{ label: range }"
          >
            <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px]">close</mat-icon>
          </button>
        </div>
      }
    </ng-template>
    <ng-template #hiddenFilters>
      @if (anyHiddenByFilters()) {
        <button mat-button class="shrink-0 ${XL_LABEL_BUTTON}"
                [matTooltip]="I18N.gallery.hidden_banner.some_hidden | translate"
                [attr.aria-label]="I18N.gallery.hidden_banner.show_all | translate"
                (click)="store.showAllHidden()">
          <mat-icon>visibility_off</mat-icon><span class="hidden xl:inline">{{ I18N.gallery.hidden_banner.show_all | translate }}</span>
        </button>
      } @else if (store.hiddenFiltersStash()) {
        <button mat-button class="shrink-0 ${XL_LABEL_BUTTON}"
                [matTooltip]="I18N.gallery.hidden_banner.showing_all | translate"
                [attr.aria-label]="I18N.gallery.hidden_banner.restore | translate"
                (click)="store.restoreHidden()">
          <mat-icon>visibility</mat-icon><span class="hidden xl:inline">{{ I18N.gallery.hidden_banner.restore | translate }}</span>
        </button>
      }
    </ng-template>
    <ng-template #timelineToolbar>
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <ng-container [ngTemplateOutlet]="breadcrumb" />
        <span data-timeline-divider aria-hidden="true" class="h-6 w-px shrink-0 bg-[var(--mat-sys-outline-variant)]"></span>
        <ng-container [ngTemplateOutlet]="viewToggle" />
        <ng-container [ngTemplateOutlet]="feedControls" />
        <ng-container [ngTemplateOutlet]="datesControl" />
        <ng-container [ngTemplateOutlet]="densityToggle" />
        <ng-container [ngTemplateOutlet]="rangeChip" />
        <ng-container [ngTemplateOutlet]="hiddenFilters" />
      </div>
    </ng-template>
    <!-- Below lg: the top row names where you are, the bottom bar holds the actions in thumb reach -->
    <div data-timeline-breadcrumb-row class="lg:hidden sticky top-0 z-20 flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] px-4 py-2">
      <ng-container [ngTemplateOutlet]="breadcrumb" />
      <ng-container [ngTemplateOutlet]="rangeChip" />
    </div>
    <!-- Packed like every other bar: the scope controls from the left, the view switch at the right end -->
    <div data-timeline-mobile-bar class="lg:hidden fixed bottom-0 left-0 right-0 z-50 ${MOBILE_BAR_ROW} [&_.mat-mdc-button-base]:!h-11 [&_.mat-mdc-button]:!min-w-11 [&_.mat-mdc-button]:!px-2.5 [&_.mat-mdc-button]:!rounded-full [&_app-control-popover_button]:!rounded-full bg-[var(--mat-sys-surface-container)] border-t border-[var(--mat-sys-outline-variant)] safe-area-pb">
      <ng-container [ngTemplateOutlet]="feedControls" [ngTemplateOutletContext]="{ compact: true }" />
      <span class="relative inline-flex">
        <ng-container [ngTemplateOutlet]="datesControl" />
        @if (filters.dateFrom() || filters.dateTo()) {
          <span data-timeline-dates-dot aria-hidden="true" class="pointer-events-none absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-[var(--mat-sys-primary)]"></span>
        }
      </span>
      <ng-container [ngTemplateOutlet]="densityToggle" />
      <ng-container [ngTemplateOutlet]="hiddenFilters" />
      <div data-timeline-bar-end class="ml-auto flex shrink-0">
        <ng-container [ngTemplateOutlet]="viewToggle" />
      </div>
    </div>

    <div class="flex flex-1 flex-col px-4 pb-2 pt-2">
      <app-timeline-density [year]="year()" [month]="month()" [visible]="densityVisible()" (total)="densityTotal.set($event)" />
      @if (!showOverview()) {
        <app-timeline-feed [year]="year()" [month]="month()" />
      } @else {
      @switch (level()) {
        @case ('years') {
          <app-timeline-years [class.mt-4]="densityVisible()" (yearSelected)="onYearSelected($event)" />
        }
        @case ('months') {
          <app-timeline-months [class.mt-4]="densityVisible()"
            [year]="year()"
            (monthSelected)="onMonthSelected($event)" />
        }
        @case ('days') {
          <app-timeline-days [class.mt-4]="densityVisible()"
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

  protected readonly active = timelineRouteActivity();
  /** Scope total reported by the density strip, which keeps reading while hidden. */
  protected readonly densityTotal = signal<number | null>(null);
  protected readonly densityVisible = signal(readDensityVisible());

  protected toggleDensity(): void {
    const visible = !this.densityVisible();
    this.densityVisible.set(visible);
    try { if (visible) localStorage.removeItem(DENSITY_HIDDEN_KEY); else localStorage.setItem(DENSITY_HIDDEN_KEY, '1'); } catch { /* storage unavailable: the choice lasts for this page only */ }
  }

  protected setCalendarView(calendar: boolean): void {
    this.showOverview.set(calendar);
    try { if (calendar) localStorage.setItem(TIMELINE_CALENDAR_VIEW_KEY, '1'); else localStorage.removeItem(TIMELINE_CALENDAR_VIEW_KEY); } catch { /* storage unavailable: the choice lasts for this page only */ }
  }

  protected toggleDirection(): void {
    if (this.active()) this.filters.sortDirection.update(value => value === 'older' ? 'newer' : 'older');
  }

  private readonly headerSlot = inject(HeaderSlotService);
  private readonly timelineToolbar = viewChild<TemplateRef<unknown>>('timelineToolbar');

  constructor() {
    effect(() => {
      const t = this.timelineToolbar();
      if (t) this.headerSlot.set(t);
    });
    registerPageContext('timeline', () => ({
      date_from: this.filters.dateFrom(),
      date_to: this.filters.dateTo(),
      sort: this.filters.sortDirection(),
    }));
    this.pageHelp.setDescription(I18N.timeline.help);
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
