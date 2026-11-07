import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { HttpRequest, provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideLocationMocks } from '@angular/common/testing';
import { NavigationEnd, provideRouter, Router, RouteReuseStrategy } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatDialog } from '@angular/material/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { OrganizationHistoryDialogComponent } from '../photo-detail/organization-history-dialog.component';
import { ComparisonWorkspaceComponent } from './comparison-workspace.component';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, filter, firstValueFrom, take } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService } from '../../core/services/scan.service';
import { ThemeService } from '../../core/services/theme.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { GalleryReuseStrategy } from '../../core/gallery-reuse.strategy';
import { makePhoto } from '../../../testing/photo.fixture';
import { GalleryComponent } from './gallery.component';
import { GalleryStore } from './gallery.store';

const config = {
  pagination: { default_per_page: 64 },
  defaults: { sort: 'star_rating', sort_direction: 'ASC', gallery_mode: 'grid', hide_details: true },
  display: { card_width_px: 168, image_width_px: 640, tags_per_photo: 5 },
  features: { show_rating_controls: true }, cull: { trash_available: true },
  quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
  sort_options_grouped: [], search_threshold_default: 0.15,
};
const rows = Array.from({ length: 7 }, (_, index) => makePhoto({ path: `/trip/${index}.jpg`, filename: `${index}.jpg`, is_kept: false }));
const selected = rows.slice(0, 6).map(photo => photo.path);
const page = (kept: boolean) => ({ photos: rows.map((photo, index) => ({ ...photo, is_kept: kept && index < 6 })), total: 7, page: 1, per_page: 64, total_pages: 1, has_more: false });
const historyEntry = { id: 701, kind: 'review', created_at: '2026-11-02T10:00:00', part: 1, parts: 1, reverted: false,
  changes: selected.map(path => ({ path, before: [0, 0, 0, 0], after: [0, 0, 0, 1], revision: 1 })) };

describe('selection, comparison, explicit review and history restore through real components', () => {
  let harness: RouterTestingHarness;
  let http: HttpTestingController;
  let router: Router;
  let store: GalleryStore;
  let requests: Subject<HttpRequest<unknown>>;
  let kept: boolean;
  const requested = (url: string) => firstValueFrom(requests.pipe(filter(request => request.url === url), take(1)));
  const arrived = () => firstValueFrom(router.events.pipe(filter(event => event instanceof NavigationEnd), take(1)));
  const sideData = () => {
    http.match(request => request.url.startsWith('/api/filter_options/') || request.url === '/api/type_counts')
      .forEach(request => request.flush({ types: [], cameras: [], lenses: [], tags: [], persons: [], ranges: {} }));
    http.match('/api/photos/keeper_hints').forEach(request => request.flush({}));
    http.match('/api/photos/review_progress').forEach(request => request.flush({ total: 7, undecided: kept ? 1 : 7, kept: kept ? 6 : 0, rejected: 0 }));
  };
  const render = async () => { harness.detectChanges(); sideData(); await Promise.resolve(); harness.detectChanges(); sideData(); };
  const cards = () => harness.routeNativeElement!.querySelectorAll<HTMLElement>('app-photo-card [role="button"]');
  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear(); requests = new Subject(); kept = false;
    TestBed.configureTestingModule({ providers: [
      { provide: RouteReuseStrategy, useClass: GalleryReuseStrategy },
      provideRouter([{ path: '', component: GalleryComponent }, { path: 'photo-compare', component: ComparisonWorkspaceComponent }]),
      provideLocationMocks(), provideNativeDateAdapter(),
      provideHttpClient(withXhr(), withInterceptors([(request, next) => { requests.next(request); return next(request); }])),
      provideHttpClientTesting(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      { provide: ScanService, useValue: { canLaunch: signal(false) } },
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', languages: signal([]), t: (key: string) => key } },
      { provide: AssistantChangesService, useValue: { batch$: NEVER, active: signal(false), activity: signal([]) } },
      { provide: ThemeService, useValue: { theme: signal(''), darkMode: signal(true), THEMES: [], accentColor: signal('#ff6600'), complementaryColor: signal('#0099ff') } },
      { provide: MatSnackBar, useValue: { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) } },
    ] });
    TestBed.inject(AuthService).status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    http = TestBed.inject(HttpTestingController); router = TestBed.inject(Router); router.setUpLocationChangeListener(); store = TestBed.inject(GalleryStore);
    harness = await RouterTestingHarness.create('/?camera=Camera');
    const photosStarted = requested('/api/photos'); http.expectOne('/api/config').flush(config); await photosStarted;
    const ready = requested('/api/type_counts'); http.expectOne(request => request.url === '/api/photos').flush(page(false)); await ready; await render();
  });
  afterEach(() => {
    TestBed.inject(MatDialog).closeAll(); sideData(); harness.fixture.destroy(); TestBed.resetTestingModule(); http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });

  it.each([200, 409])('preserves the current selection after comparison, Keep and history response %s', async status => {
    const gallery = harness.routeDebugElement!.componentInstance;
    const originalCards = [...cards()];
    const scroll = harness.routeNativeElement!.querySelector<HTMLElement>('mat-sidenav-content')!;
    scroll.scrollTop = 180;
    const scrollTo = vi.fn((options: ScrollToOptions) => { if (options.top !== undefined) scroll.scrollTop = options.top; });
    Object.defineProperty(scroll, 'scrollTo', { value: scrollTo, configurable: true });
    for (const card of originalCards.slice(0, 6)) card.click();
    await render();
    expect([...store.selectedPaths()]).toEqual(selected);
    const compare = harness.routeNativeElement!.querySelector<HTMLButtonElement>('[aria-label="gallery.selection.compare"]')!;
    expect(compare.disabled).toBe(false);
    const opening = arrived(); compare.click(); await opening; await render();
    expect(harness.routeNativeElement!.querySelectorAll('app-synced-zoom')).toHaveLength(2);
    expect(harness.routeNativeElement!.querySelectorAll('[data-candidate-thumbnail]')).toHaveLength(6);
    harness.routeNativeElement!.querySelectorAll<HTMLButtonElement>('[data-candidate-thumbnail]')[5].click(); await render();
    expect([...harness.routeNativeElement!.querySelectorAll('app-synced-zoom')].map(pane => pane.getAttribute('aria-label')))
      .toEqual([rows[0].filename, rows[5].filename]);
    http.expectNone(request => request.method !== 'GET');
    const returning = arrived();
    harness.routeNativeElement!.querySelector<HTMLButtonElement>('[aria-label="ui.buttons.back"]')!.click();
    await returning; await render();
    expect(router.url).toBe('/?camera=Camera');
    expect(harness.routeDebugElement!.componentInstance).toBe(gallery);
    expect([...cards()]).toEqual(originalCards);
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 180 }));
    expect([...store.selectedPaths()]).toEqual(selected);
    http.expectNone(request => request.url === '/api/photos');
    harness.routeNativeElement!.querySelector<HTMLButtonElement>('[data-selection-keep]')!.click();
    const write = http.expectOne('/api/photos/batch_review');
    expect(write.request.body).toEqual({ photo_paths: selected, decision: 'kept' });
    kept = true; write.flush({ count: 6 });
    await vi.waitFor(() => { sideData(); harness.detectChanges(); expect(store.selectedPaths().size).toBe(0); });
    expect(store.photos().slice(0, 6).every(photo => photo.is_kept)).toBe(true);
    cards()[6].click(); await render();
    expect([...store.selectedPaths()]).toEqual([rows[6].path]);
    // Use the actual history dialog and store; the global navigation opener is
    // covered separately by App's integration tests.
    const dialog = TestBed.inject(MatDialog).open(OrganizationHistoryDialogComponent);
    harness.detectChanges(); http.expectOne('/api/organization_history').flush({ entries: [historyEntry] }); await render();
    const root = TestBed.inject(OverlayContainer).getContainerElement().querySelector('app-organization-history-dialog')!;
    root.querySelector<HTMLButtonElement>('section > button[aria-label]')!.click(); await render();
    http.expectNone('/api/organization_history/701/revert');
    root.querySelector<HTMLButtonElement>('[data-history-apply]')!.click();
    const restore = http.expectOne('/api/organization_history/701/revert');
    if (status === 409) {
      restore.flush({}, { status: 409, statusText: 'Conflict' });
      await vi.waitFor(() => { harness.detectChanges(); expect(root.textContent).toContain('organization_history.conflict'); });
      expect(store.photos().slice(0, 6).every(photo => photo.is_kept)).toBe(true);
      http.expectNone(request => request.url === '/api/photos');
    } else {
      const refreshStarted = requested('/api/photos');
      kept = false; restore.flush({ changed: 6 }); await refreshStarted;
      const refresh = http.expectOne(request => request.url === '/api/photos');
      expect(refresh.request.params.get('camera')).toBe('Camera');
      refresh.flush(page(false));
      http.expectOne('/api/organization_history').flush({ entries: [{ ...historyEntry, reverted: true }] });
      await vi.waitFor(() => { sideData(); harness.detectChanges(); expect(store.photos().slice(0, 6).every(photo => !photo.is_kept)).toBe(true); });
      expect(dialog.componentInstance.wasRestored()).toBe(true);
    }
    dialog.close(); await render();
    expect([...store.selectedPaths()]).toEqual([rows[6].path]);
    expect(router.url).toBe('/?camera=Camera');
    expect([...cards()].map(card => card.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'false', 'false', 'false', 'false', 'true']);
  });
});
