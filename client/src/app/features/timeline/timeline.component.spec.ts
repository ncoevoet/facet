import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ApplicationRef, Component, input, output, signal } from '@angular/core';
import { Subject } from 'rxjs';
import { Router, ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { TimelineFiltersService } from './timeline-filters.service';
import { TimelineComponent } from './timeline.component';
import { PageContextService } from '../../core/agent/page-context.service';
import { GalleryStore } from '../gallery/gallery.store';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { I18nService } from '../../core/services/i18n.service';
import { TimelineDensityComponent } from './timeline-density.component';
import { TimelineFeedComponent } from './timeline-feed.component';
import { TimelineYearsComponent } from './timeline-years.component';
import { TimelineMonthsComponent } from './timeline-months.component';
import { TimelineDaysComponent } from './timeline-days.component';
import { DateRangeFilterComponent } from '../../shared/components/date-range-filter/date-range-filter.component';


const timelinePersonalReset = { type: '', hide_rejected: 'false', favorites_only: 'false', is_monochrome: 'false', review_status: '', show_rejected: 'false', blinks_only: 'false', duplicates_only: 'false' };

describe('TimelineComponent', () => {

  let component: any;
  let mockRouter: { navigate: Mock };
  let mockFilters: {
    dateFrom: ReturnType<typeof signal<string>>;
    dateTo: ReturnType<typeof signal<string>>;
    sortDirection: ReturnType<typeof signal<'older' | 'newer'>>;
    showOverview: ReturnType<typeof signal<boolean>>;
  };
  let mockStore: { viewFilterParams: ReturnType<typeof signal>; showAllHidden: Mock };
  let paramMapSubject: { get: Mock };

  const noneHidden = {
    hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0',
  };

  beforeEach(() => {
    mockRouter = { navigate: vi.fn() };
    mockFilters = {
      dateFrom: signal(''),
      dateTo: signal(''),
      sortDirection: signal<'older' | 'newer'>('older'),
      showOverview: signal(false),
    };
    mockStore = { viewFilterParams: signal({ ...noneHidden }), showAllHidden: vi.fn() };
    paramMapSubject = { get: vi.fn().mockReturnValue(null) };

    TestBed.configureTestingModule({
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: TimelineFiltersService, useValue: mockFilters },
        { provide: ActivatedRoute, useValue: { paramMap: of(paramMapSubject) } },
        { provide: GalleryStore, useValue: mockStore },
      ],
    });
    component = TestBed.runInInjectionContext(() => new TimelineComponent());
  });

  describe('page context', () => {
    it('registers the timeline page and reads its filters live', () => {
      const context = TestBed.inject(PageContextService);
      expect(context.snapshot()).toEqual({ id: 'timeline', date_from: '', date_to: '', sort: 'older' });
      mockFilters.sortDirection.set('newer');
      expect(context.snapshot()).toMatchObject({ sort: 'newer' });
    });
  });

  it('retains calendar mode when timeline navigation recreates the component', () => {
    component.showOverview.set(true);
    const recreated: any = TestBed.runInInjectionContext(() => new TimelineComponent());
    expect(recreated.showOverview()).toBe(true);
    recreated.showOverview.set(false);
    expect(component.showOverview()).toBe(false);
  });

  describe('initial state', () => {
    it('should start at years level with no route params', () => {
      expect(component.level()).toBe('years');
    });

    it('should be at months level when year param is set', () => {
      paramMapSubject.get.mockImplementation((key: string) => key === 'year' ? '2024' : null);
      // Re-create with updated route
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      expect(component.level()).toBe('months');
      expect(component.year()).toBe('2024');
    });

    it('should be at days level when year and month params are set', () => {
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '6' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      expect(component.level()).toBe('days');
      expect(component.year()).toBe('2024');
      expect(component.month()).toBe('6');
    });
  });

  describe('selectedMonthFormatted', () => {
    it('returns empty string when no params', () => {
      expect(component.selectedMonthFormatted()).toBe('');
    });

    it('formats month with zero padding', () => {
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '6' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      expect(component.selectedMonthFormatted()).toBe('2024-06');
    });
  });

  describe('navigation methods', () => {
    it('goToYears navigates to /timeline', () => {
      component.goToYears();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/timeline']);
    });

    it('goToMonths navigates to /timeline/:year', () => {
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '6' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      component.goToMonths();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/timeline', '2024']);
    });

    it('onYearSelected navigates to /timeline/:year', () => {
      component.onYearSelected('2024');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/timeline', '2024']);
    });

    it('onMonthSelected navigates to /timeline/:year/:month', () => {
      TestBed.resetTestingModule();
      const newParamMap = { get: (key: string) => key === 'year' ? '2024' : null };
      TestBed.configureTestingModule({
        providers: [
          { provide: Router, useValue: mockRouter },
          { provide: TimelineFiltersService, useValue: mockFilters },
          { provide: ActivatedRoute, useValue: { paramMap: of(newParamMap) } },
          { provide: GalleryStore, useValue: mockStore },
        ],
      });
      component = TestBed.runInInjectionContext(() => new TimelineComponent());
      component.onMonthSelected('2024-06');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/timeline', '2024', '6']);
    });
  });

  describe('day selection', () => {
    it('onDaySelected navigates to gallery with date filter params', () => {
      component.onDaySelected('2024-06-15');
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        queryParams: {
          ...Object.fromEntries(Object.keys(noneHidden).map(key => [key, 'false'])),
          ...timelinePersonalReset,
          date_from: '2024-06-15',
          date_to: '2024-06-15',
          sort: 'date_taken',
          sort_direction: 'DESC',
        },
      });
    });
  });

  describe('anyHiddenByFilters (reachability banner)', () => {
    it('is false when every hide toggle is off', () => {
      expect(component.anyHiddenByFilters()).toBe(false);
    });

    it('is true when at least one hide toggle is on', () => {
      mockStore.viewFilterParams.set({ ...noneHidden, hide_bursts: '1' });
      expect(component.anyHiddenByFilters()).toBe(true);
    });

    it('goes back to false once every toggle is off again', () => {
      mockStore.viewFilterParams.set({ ...noneHidden, hide_panoramas: '1' });
      expect(component.anyHiddenByFilters()).toBe(true);
      mockStore.viewFilterParams.set({ ...noneHidden });
      expect(component.anyHiddenByFilters()).toBe(false);
    });
  });
});


describe('Timeline missing-date and range transitions', () => {
  it.each([
    ['2024-02-20', '2024-02-10'],
    ['2024-03-01', '2024-03-31'],
  ])('keeps an empty date intersection on the timeline until corrected (%s, %s)', (from, to) => {
    const navigate = vi.fn();
    const dateFrom = signal(from); const dateTo = signal(to);
    TestBed.configureTestingModule({ providers: [
      { provide: Router, useValue: { navigate } },
      { provide: ActivatedRoute, useValue: { paramMap: of({ get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '2' : null }) } },
      { provide: TimelineFiltersService, useValue: { dateFrom, dateTo, sortDirection: signal('older'), showOverview: signal(false) } },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({ hide_bursts: '1' }) } },
    ] });
    const component: any = TestBed.runInInjectionContext(() => new TimelineComponent());
    component.viewRange();
    expect(navigate).not.toHaveBeenCalled();
    expect(component.emptyRange()).toBe(true);
    dateFrom.set('2024-02-29'); dateTo.set('2024-02-29');
    expect(component.emptyRange()).toBe(false);
    component.viewRange();
    expect(navigate).toHaveBeenCalledWith(['/'], { queryParams: {
      ...timelinePersonalReset, hide_bursts: 'true', date_from: '2024-02-29', date_to: '2024-02-29',
      sort: 'date_taken', sort_direction: 'DESC',
    } });
  });

  it('opens the selected route month intersected with the typed range instead of widening to the whole library', () => {
    const navigate = vi.fn();
    TestBed.configureTestingModule({ providers: [
      { provide: Router, useValue: { navigate } },
      { provide: ActivatedRoute, useValue: { paramMap: of({ get: (key: string) => key === 'year' ? '2024' : key === 'month' ? '2' : null }) } },
      { provide: TimelineFiltersService, useValue: { dateFrom: signal('2024-02-12'), dateTo: signal(''), sortDirection: signal('older'), showOverview: signal(false) } },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({ hide_bursts: '1' }) } },
    ] });
    const component: any = TestBed.runInInjectionContext(() => new TimelineComponent());
    component.viewRange();
    expect(navigate).toHaveBeenCalledWith(['/'], { queryParams: { ...timelinePersonalReset, hide_bursts: 'true', date_from: '2024-02-12', date_to: '2024-02-29', sort: 'date_taken', sort_direction: 'DESC' } });
  });
  it('carries only visibility into the chosen date scope, and resets the timeline window', () => {
    const navigate = vi.fn();
    const dateFrom = signal('2026-01-01'); const dateTo = signal('2026-02-01');
    TestBed.configureTestingModule({ providers: [
      { provide: Router, useValue: { navigate } },
      { provide: ActivatedRoute, useValue: { paramMap: of({ get: () => null }) } },
      { provide: TimelineFiltersService, useValue: { dateFrom, dateTo, sortDirection: signal('older'), showOverview: signal(false) } },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({ hide_bursts: '1' }) } },
    ] });
    const component: any = TestBed.runInInjectionContext(() => new TimelineComponent());
    component.viewRange();
    expect(navigate).toHaveBeenLastCalledWith(['/'], { queryParams: { ...timelinePersonalReset, hide_bursts: 'true', date_from: '2026-01-01', date_to: '2026-02-01', sort: 'date_taken', sort_direction: 'DESC' } });
    component.viewUnknownDates();
    expect(navigate).toHaveBeenLastCalledWith(['/'], { queryParams: { ...timelinePersonalReset, hide_bursts: 'true', no_capture_date: '1', sort: 'filename', sort_direction: 'ASC' } });
    component.resetDates();
    expect(dateFrom()).toBe(''); expect(dateTo()).toBe('');
    expect(navigate).toHaveBeenLastCalledWith(['/timeline']);
  });
});


@Component({ selector: 'app-timeline-density', template: '' })
class DensityStub { readonly year = input(''); readonly month = input(''); }
@Component({ selector: 'app-timeline-feed', template: '' })
class FeedStub { readonly year = input(''); readonly month = input(''); }
@Component({ selector: 'app-timeline-years', template: '' })
class YearsStub { readonly yearSelected = output<string>(); }
@Component({ selector: 'app-timeline-months', template: '' })
class MonthsStub { readonly year = input(''); readonly monthSelected = output<string>(); }
@Component({ selector: 'app-timeline-days', template: '' })
class DaysStub { readonly year = input(''); readonly month = input(''); readonly daySelected = output<string>(); }
@Component({ selector: 'app-date-range-filter', template: '' })
class DateRangeStub {
  readonly from = input(''); readonly to = input(''); readonly compact = input(false);
  readonly fromClass = input(''); readonly toClass = input('');
  readonly fromChange = output<string>(); readonly toChange = output<string>();
}

describe('Timeline page-actions bar (rendered)', () => {
  const navigate = vi.fn();
  let dateFrom: ReturnType<typeof signal<string>>;
  let dateTo: ReturnType<typeof signal<string>>;
  let params: Record<string, string>;
  let store: { viewFilterParams: ReturnType<typeof signal>; hiddenFiltersStash: ReturnType<typeof signal>; showAllHidden: Mock; restoreHidden: Mock };

  function setup(routeParams: Record<string, string> = {}) {
    navigate.mockReset();
    dateFrom = signal('');
    dateTo = signal('');
    store = { viewFilterParams: signal({ ...noneHiddenParams }), hiddenFiltersStash: signal(null), showAllHidden: vi.fn(), restoreHidden: vi.fn() };
    params = routeParams;
    TestBed.configureTestingModule({
      providers: [
        { provide: Router, useValue: { navigate, events: new Subject() } },
        { provide: ActivatedRoute, useValue: { paramMap: of({ get: (k: string) => params[k] ?? null }) } },
        { provide: TimelineFiltersService, useValue: { dateFrom, dateTo, sortDirection: signal('older'), showOverview: signal(true) } },
        { provide: GalleryStore, useValue: store },
        { provide: I18nService, useValue: {
          translations: signal({}),
          t: (key: string, vars?: Record<string, string>) => vars ? `${key}|${JSON.stringify(vars)}` : key,
        } },
      ],
    });
    TestBed.overrideComponent(TimelineComponent, {
      remove: { imports: [TimelineDensityComponent, TimelineFeedComponent, TimelineYearsComponent, TimelineMonthsComponent, TimelineDaysComponent, DateRangeFilterComponent] },
      add: { imports: [DensityStub, FeedStub, YearsStub, MonthsStub, DaysStub, DateRangeStub] },
    });
    const fixture = TestBed.createComponent(TimelineComponent);
    fixture.detectChanges();
    return fixture;
  }

  const noneHiddenParams = { hide_blinks: '0', hide_bursts: '0', hide_duplicates: '0', hide_brackets: '0', hide_panoramas: '0' };

  /** Render the registered header-slot template the way the shell does at lg+. */
  function renderBar() {
    const tpl = TestBed.inject(HeaderSlotService).template();
    expect(tpl).not.toBeNull();
    const view = tpl!.createEmbeddedView(null);
    TestBed.inject(ApplicationRef).attachView(view);
    view.detectChanges();
    const host = document.createElement('div');
    view.rootNodes.forEach((n: Node) => host.appendChild(n));
    return host;
  }

  it('registers one template with the header slot and clears it on destroy', () => {
    const fixture = setup();
    const slot = TestBed.inject(HeaderSlotService);
    expect(slot.template()).not.toBeNull();
    fixture.destroy();
    expect(slot.template()).toBeNull();
  });

  it('shows a static All years label (no button) in the bar at the years level', () => {
    setup();
    const bar = renderBar();
    expect(bar.textContent).toContain('timeline.all_years');
    expect(Array.from(bar.querySelectorAll('button')).some(b => b.textContent?.includes('timeline.all_years'))).toBe(false);
  });

  it('shows the breadcrumb path in the bar at the months level', () => {
    setup({ year: '2024' });
    const bar = renderBar();
    const text = bar.textContent ?? '';
    expect(text).toContain('timeline.all_years');
    expect(text).toContain('2024');
  });

  it('keeps an lg:hidden sticky z-20 breadcrumb row in the page at the years level too', () => {
    const fixture = setup();
    const row = (fixture.nativeElement as HTMLElement).querySelector('[data-timeline-breadcrumb-row]');
    expect(row).not.toBeNull();
    expect(row!.className).toContain('lg:hidden');
    expect(row!.className).toContain('sticky');
    expect(row!.className).toContain('top-0');
    expect(row!.className).toContain('z-20');
    expect(row!.textContent).toContain('timeline.all_years');
  });

  it('replaces the old details block and in-content toggle with the bar', () => {
    const fixture = setup();
    expect((fixture.nativeElement as HTMLElement).querySelector('details')).toBeNull();
  });

  it('shows the active-range chip only with a range, and its remove button resets the dates', () => {
    setup();
    expect(renderBar().querySelector('[data-timeline-range-chip]')).toBeNull();
    dateFrom.set('2024-02-01');
    const bar = renderBar();
    const chip = bar.querySelector('[data-timeline-range-chip]');
    expect(chip).not.toBeNull();
    const remove = chip!.querySelector('button') as HTMLButtonElement;
    expect(remove.getAttribute('aria-label')).toContain('gallery.criteria.remove|');
    expect(remove.getAttribute('aria-label')).toContain('"label":');
    remove.click();
    expect(dateFrom()).toBe('');
    expect(navigate).toHaveBeenCalledWith(['/timeline']);
  });

  it('puts the feed/overview toggle and a Dates popover on the right of the bar', () => {
    setup();
    const bar = renderBar();
    const right = bar.querySelector('.ml-auto');
    expect(right).not.toBeNull();
    expect(right!.querySelectorAll('button[aria-pressed]').length).toBe(2);
    const trigger = right!.querySelector('app-control-popover button[aria-haspopup="dialog"]') as HTMLButtonElement;
    expect(trigger.getAttribute('aria-label')).toBe('timeline.dates');
  });

  it('keeps the empty-range description target inside the Dates popover', () => {
    setup();
    dateFrom.set('2024-03-01');
    dateTo.set('2024-02-01');
    const bar = renderBar();
    (bar.querySelector('app-control-popover button[aria-haspopup="dialog"]') as HTMLButtonElement).click();
    TestBed.inject(ApplicationRef).tick();
    const target = document.querySelector('#timeline-empty-range');
    expect(target).not.toBeNull();
    expect(document.querySelector('[aria-describedby="timeline-empty-range"]')).not.toBeNull();
  });

  it('exposes Show all / Restore as an icon button in the bar', () => {
    setup();
    store.viewFilterParams.set({ ...noneHiddenParams, hide_bursts: '1' });
    let bar = renderBar();
    const showAll = bar.querySelector('button[aria-label="gallery.hidden_banner.show_all"]') as HTMLButtonElement;
    expect(showAll).not.toBeNull();
    showAll.click();
    expect(store.showAllHidden).toHaveBeenCalled();
    store.viewFilterParams.set({ ...noneHiddenParams });
    store.hiddenFiltersStash.set({} as never);
    bar = renderBar();
    const restore = bar.querySelector('button[aria-label="gallery.hidden_banner.restore"]') as HTMLButtonElement;
    expect(restore).not.toBeNull();
    restore.click();
    expect(store.restoreHidden).toHaveBeenCalled();
  });
});
