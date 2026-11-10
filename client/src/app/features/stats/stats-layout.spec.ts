import { NO_ERRORS_SCHEMA, Pipe, PipeTransform, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router } from '@angular/router';
import { NEVER, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ThemeService } from '../../core/services/theme.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { GalleryStore } from '../gallery/gallery.store';
import { GearChartCardComponent } from './gear-chart-card.component';
import { StatsCorrelationsTabComponent } from './stats-correlations-tab.component';
import { StatsTimelineTabComponent } from './stats-timeline-tab.component';
import { StatsComponent } from './stats.component';

@Pipe({ name: 'translate', standalone: true })
class MockTranslatePipe implements PipeTransform { transform(key: string): string { return key; } }

describe('statistics page states', () => {
  let failOverview: boolean;
  let failedPath: string | null;
  let requested: string[];
  const locale = signal('de');
  const owner = signal('owner');
  const overview = { total_photos: 18432, total_persons: 50, avg_score: 6.5, total_faces: 300 };
  beforeEach(async () => {
    failOverview = false; failedPath = null; requested = []; locale.set('de'); owner.set('owner'); overview.total_photos = 18432;
    await TestBed.configureTestingModule({
      imports: [StatsComponent, NoopAnimationsModule],
      providers: [
        { provide: ApiService, useValue: { get: (path: string) => {
          requested.push(path);
          if (path === failedPath) return throwError(() => new Error('offline'));
          if (path === '/stats/overview') return failOverview ? throwError(() => new Error('offline')) : of(overview);
          if (path === '/stats/gear') return of({ cameras: [], lenses: [], combos: [] });
          return of([]);
        } } },
        { provide: AuthService, useValue: { identity: owner, isAuthenticated: () => true, status: () => ({}), token: 'token' } },
        { provide: GalleryStore, useValue: { types: signal([]), loadTypeCounts: vi.fn(() => Promise.resolve()) } },
        { provide: I18nService, useValue: { t: (key: string) => key, locale, translations: () => ({}) } },
        { provide: ThemeService, useValue: { accentColor: () => '#123456', complementaryColor: () => '#123456', darkMode: () => false } },
        { provide: Router, useValue: { navigate: vi.fn(), events: NEVER } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
      ],
    }).overrideComponent(StatsComponent, {
      remove: { imports: [TranslatePipe, GearChartCardComponent, StatsTimelineTabComponent, StatsCorrelationsTabComponent] },
      add: { imports: [MockTranslatePipe], schemas: [NO_ERRORS_SCHEMA] },
    }).compileComponents();
  });

  afterEach(() => { TestBed.resetTestingModule(); });

  it('renders localized summary numbers and keeps mobile filters available', async () => {
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges();
    await fixture.whenStable(); fixture.detectChanges();
    const host: HTMLElement = fixture.nativeElement;
    expect(host.querySelector('[data-stats-overview]')?.textContent).toContain('18.432');
    expect(host.querySelector('[data-stats-overview]')?.textContent).toContain('6,5');
    expect(host.querySelector('details summary')?.textContent).toContain('ui.buttons.filters');
    expect(host.querySelector('details [data-stats-filters]')).not.toBeNull();
    expect(host.querySelector('h1')?.textContent).toContain('nav.stats');
    const tabs = Array.from(host.querySelectorAll('[role="tab"]')).map(tab => tab.textContent ?? '');
    expect(tabs).toHaveLength(4);
    expect(tabs.join(' ')).toContain('stats.gear');
    expect(tabs.join(' ')).toContain('stats.categories.tab');
    expect(tabs.join(' ')).toContain('stats.timeline');
    expect(tabs.join(' ')).toContain('stats.tabs.correlations');
  });

  it('shows a readable active filter summary while the mobile filter disclosure is closed', async () => {
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    fixture.componentInstance.statsFilters.filterCategory.set('astro');
    fixture.componentInstance.statsFilters.dateFrom.set('2026-11-06');
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const summary = fixture.nativeElement.querySelector('details summary');
    expect(summary.textContent).toContain('astro');
    expect(summary.textContent).toContain('06/11/2026');
  });

  it('shows only the page failure instead of empty chart states when the overview fails', async () => {
    failOverview = true;
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const host: HTMLElement = fixture.nativeElement;
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('stats.correlations.error');
    expect(host.querySelector('mat-tab-group')).toBeNull();
    expect(host.querySelector('app-gear-chart-card')).toBeNull();
  });

  it('does not read the unused top cameras, and keeps the page when a single section read fails', async () => {
    failedPath = '/stats/gear';
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const host: HTMLElement = fixture.nativeElement;
    expect(requested).not.toContain('/stats/top_cameras');
    expect(host.querySelector('mat-tab-group')).not.toBeNull();
    expect(host.querySelectorAll('[role="alert"]')).toHaveLength(1);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('stats.correlations.error');
  });

  it('shows an unavailable average for an empty collection', async () => {
    overview.total_photos = 0; overview.avg_score = 0;
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const values = fixture.nativeElement.querySelectorAll('[data-stats-overview] dd');
    expect(values[2].textContent.trim()).toBe('—');
    overview.avg_score = 6.5;
  });

  it('shows a no-data message instead of a blank histogram', async () => {
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    (fixture.componentInstance as any).selectedTab.set(1);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('stats.no_data');
    expect(fixture.nativeElement.querySelector('canvas')).toBeNull();
  });

  it('provides localized histogram values and category chart tables with real headings', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const page = fixture.componentInstance as any;
    page.selectedTab.set(1);
    page.scoreBins.set([{ range: '1.5', min: 1.5, max: 2, count: 1234, percentage: 1 }]);
    page.categoryStats.set([{ category: 'portrait', count: 1, avg_score: 6.5, avg_f_stop: 2.8, avg_iso: 1400,
      avg_focal_length: 50, avg_aesthetic: 6, avg_composition: 7, avg_sharpness: 8,
      avg_color: 6, avg_exposure: 7, avg_face_quality: 8, avg_contrast: 6 }]);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const host: HTMLElement = fixture.nativeElement;
    const hist = Array.from(host.querySelectorAll('table')).find(table => table.querySelector('caption')?.textContent?.includes('stats.score_histogram'));
    // 1.26 rounds to 1.5; the API min/max fields must not be shown as its range.
    expect(hist?.textContent).toContain('1,5');
    expect(hist?.textContent).not.toContain('1,5–2');
    expect(hist?.textContent).toContain('1.234');
    expect(hist?.querySelector('thead')?.textContent).toContain('stats.axes.score');
    expect(hist?.querySelector('thead')?.textContent).not.toContain('gallery.score_range');
    expect(hist?.querySelector('thead')?.textContent).toContain('stats.axes.photos');
    expect(host.querySelectorAll('h2[mat-card-title]').length).toBeGreaterThanOrEqual(3);
    expect(host.textContent).toContain('stats.show_chart_data');
    const tables = Array.from(host.querySelectorAll('table'));
    expect(tables.some(table => table.textContent?.includes('2,8'))).toBe(true);
    expect(tables.some(table => table.textContent?.includes('6,5'))).toBe(true);
    page.categoryMetric.set('avg_iso');
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const metric = Array.from(host.querySelectorAll('table')).find(table => table.querySelector('caption')?.textContent?.includes('stats.category_metric_title'));
    expect(metric?.textContent).toContain('1.400');
    expect(metric?.textContent).not.toContain('1.400,0');
    const gearTitle = Array.from(host.querySelectorAll('h2')).find(heading => heading.textContent?.includes('stats.categories_gear_profile'));
    const gearTable = gearTitle?.closest('mat-card')?.querySelector('table');
    expect(gearTable?.textContent).toContain('1.400');
    expect(gearTable?.textContent).toContain('2,8');
    vi.restoreAllMocks();
  });

  it('aligns the category cards to the top and gives a tall Score Profile its own full-width scroll wrapper', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const fixture = TestBed.createComponent(StatsComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const page = fixture.componentInstance as any;
    page.selectedTab.set(1);
    page.categoryStats.set([{ category: 'portrait', count: 1, avg_score: 6.5, avg_f_stop: 2.8, avg_iso: 1400,
      avg_focal_length: 50, avg_aesthetic: 6, avg_composition: 7, avg_sharpness: 8,
      avg_color: 6, avg_exposure: 7, avg_face_quality: 8, avg_contrast: 6 }]);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const host: HTMLElement = fixture.nativeElement;
    const profile = Array.from(host.querySelectorAll('h2')).find(h => h.textContent?.includes('stats.categories_score_profile'))?.closest('mat-card') as HTMLElement;
    expect(profile).toBeTruthy();
    expect(profile.parentElement?.classList.contains('items-start')).toBe(true);
    expect(profile.classList.contains('lg:col-span-2')).toBe(true);
    expect(profile.classList.contains('2xl:col-span-3')).toBe(true);
    const canvas = profile.querySelector('canvas') as HTMLElement;
    const wrapper = canvas.parentElement?.parentElement as HTMLElement;
    expect(wrapper.classList.contains('max-h-[70vh]')).toBe(true);
    expect(wrapper.classList.contains('overflow-y-auto')).toBe(true);
    vi.restoreAllMocks();
  });
});
