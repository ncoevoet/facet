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
  const locale = signal('de');
  const owner = signal('owner');
  const overview = { total_photos: 18432, total_persons: 50, avg_score: 6.5, total_faces: 300 };
  beforeEach(async () => {
    failOverview = false; locale.set('de'); owner.set('owner'); overview.total_photos = 18432;
    await TestBed.configureTestingModule({
      imports: [StatsComponent, NoopAnimationsModule],
      providers: [
        { provide: ApiService, useValue: { get: (path: string) => {
          if (path === '/stats/overview') return failOverview ? throwError(() => new Error('offline')) : of(overview);
          if (path === '/stats/gear') return of({ cameras: [], lenses: [], combos: [] });
          return of([]);
        } } },
        { provide: AuthService, useValue: { identity: owner, isAuthenticated: () => true, status: () => ({}), token: 'token' } },
        { provide: GalleryStore, useValue: { types: signal([]) } },
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
});
