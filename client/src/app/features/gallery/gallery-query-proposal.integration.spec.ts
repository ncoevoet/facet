import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideLocationMocks } from '@angular/common/testing';
import { NavigationEnd, NavigationStart, Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, filter, firstValueFrom, take } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AssistantChangesService, type AssistantChangeBatch } from '../../core/agent/assistant-changes.service';
import { WebMcpToolRegistry } from '../../core/agent/webmcp-registry.service';
import { GalleryStore, type ViewerConfig } from './gallery.store';
import { GalleryQueryProposalComponent } from './gallery-query-proposal.component';
import { makePhoto } from '../../../testing/photo.fixture';

@Component({ imports: [GalleryQueryProposalComponent], template: '<button id="proposal-return">Gallery actions</button><app-gallery-query-proposal [active]="active()" />' })
class QueryHost {
  readonly active = signal(true);
  constructor() {
    inject(Router).events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) this.active.set(false);
      else if (event instanceof NavigationEnd) this.active.set(true);
    });
  }
}
@Component({ template: '<button id="away">Other page</button>' })
class OtherPage {}

describe('Query proposal with real Router, Store and HTTP', () => {
  let harness: RouterTestingHarness;
  let http: HttpTestingController;
  let router: Router;
  let store: GalleryStore;
  let registry: WebMcpToolRegistry;
  const root = () => harness.routeNativeElement!;
  const aux = () => {
    http.match('/api/filter_options/metric_ranges').forEach(request => request.flush({ ranges: {} }));
    http.match('/api/photos/keeper_hints').forEach(request => request.flush({}));
    http.match('/api/photos/review_progress').forEach(request => request.flush({ total: 1, undecided: 1, kept: 0, rejected: 0 }));
    http.match(request => request.url === '/api/filter_options/location_name').forEach(request => request.flush({ name: 'Fixture location' }));
  };
  const photos = { photos: [makePhoto({ path: '/a.jpg' })], total: 1, photo_total: 1, page: 1, per_page: 64, total_pages: 1, has_more: false };
  async function propose(patch: object): Promise<void> {
    root().querySelector<HTMLButtonElement>('#proposal-return')!.focus();
    expect(await registry.execute('ui_set_gallery_filters', { patch,
      proposal: { source_query: 'birds from last spring', unrepresented: [] } })).toMatchObject({ ok: true, data: { applied: false, status: 'awaiting_user' } });
    await harness.fixture.whenStable(); harness.detectChanges();
  }
  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient(withXhr()), provideHttpClientTesting(), provideLocationMocks(),
      provideRouter([{ path: '', component: QueryHost }, { path: 'persons', component: OtherPage }]),
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
      { provide: AssistantChangesService, useValue: { batch$: new Subject<AssistantChangeBatch>() } },
      { provide: MatSnackBar, useValue: { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) } },
    ] });
    http = TestBed.inject(HttpTestingController); router = TestBed.inject(Router);
    const auth = TestBed.inject(AuthService);
    auth.status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    store = TestBed.inject(GalleryStore);
    store.config.set({ pagination: { default_per_page: 64 }, defaults: { type: '', sort: 'aggregate', sort_direction: 'DESC',
      hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      hide_details: true, tooltip_mode: 'hover', panel_activation: 'both', hide_rejected: true },
      display: { tags_per_photo: 5, card_width_px: 300, image_width_px: 640 }, sort_options_grouped: null,
      features: {}, quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 }, search_threshold_default: 0.15 } as ViewerConfig);
    harness = await RouterTestingHarness.create('/'); harness.detectChanges();
    registry = TestBed.inject(WebMcpToolRegistry); await registry.load();
  });
  afterEach(() => {
    aux(); harness.fixture.destroy(); TestBed.resetTestingModule(); http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });

  it('retains failed-result feedback across its own query navigation and retries the read without applying twice', async () => {
    const updates = vi.spyOn(store, 'updateFilters');
    const selected = new Set(['/outside.jpg']); store.selectedPaths.set(selected);
    await propose({ date_from: '2024-03-01', tag: 'Birds' }); http.expectNone(() => true);
    const arrived = firstValueFrom(router.events.pipe(filter(event => event instanceof NavigationEnd), take(1)));
    root().querySelector<HTMLButtonElement>('[data-apply-query-proposal]')!.click();
    const request = http.expectOne(value => value.url === '/api/photos');
    expect(request.request.params.get('tag')).toBe('Birds');
    expect(request.request.params.get('date_from')).toBe('2024-03-01');
    await arrived; harness.detectChanges();
    expect(root().querySelector('[data-query-proposal]')).not.toBeNull();
    request.flush({}, { status: 503, statusText: 'unavailable' }); aux();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(root().querySelector('[role="alert"]')?.textContent).toContain('gallery.proposal.load_error');
    expect(store.selectedPaths()).toBe(selected);
    root().querySelector<HTMLButtonElement>('[data-retry-query-results]')!.click();
    http.expectOne(value => value.url === '/api/photos').flush(photos); aux();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(updates).toHaveBeenCalledOnce(); expect(store.selectedPaths()).toBe(selected);
    expect(root().querySelector('[data-query-proposal]')).toBeNull();
    expect(document.activeElement).toBe(root().querySelector('#proposal-return'));
  });

  it('shows dependent clears and refuses contradictory requested predicates before any photo read', async () => {
    store.filters.update(value => ({ ...value, gps_lat: '12', gps_lng: '30', gps_radius_km: '5' }));
    await propose({ no_gps: '1', semantic_query: 'sunset' });
    expect(root().querySelector('[data-effective-field="gps_lat"]')?.textContent).toContain('12');
    expect(root().querySelector('[role="alert"]')?.textContent).toContain('Semantic Query');
    expect(root().querySelector<HTMLButtonElement>('[data-apply-query-proposal]')!.disabled).toBe(true);
    http.expectNone(request => request.url === '/api/photos' || request.method !== 'GET');
    expect(store.filters().gps_lat).toBe('12');
  });
});
