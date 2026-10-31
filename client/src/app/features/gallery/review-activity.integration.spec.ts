import { MatDialog } from '@angular/material/dialog';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { OverlayContainer } from '@angular/cdk/overlay';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpRequest, provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, filter, firstValueFrom, take } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService } from '../../core/services/scan.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { GalleryComponent } from './gallery.component';
import { RouterTestingHarness } from '@angular/router/testing';
import { StackEditorPageComponent } from './stack-editor-page.component';
import { GalleryStore } from './gallery.store';

const counts = { total: 2, undecided: 2, kept: 0, rejected: 0 };
const rows = [makePhoto({ path: '/trip/a.jpg' }), makePhoto({ path: '/trip/b.jpg' })];
const page = { photos: rows, total: 2, page: 1, per_page: 64, total_pages: 1, has_more: false };
const config = {
  pagination: { default_per_page: 64 },
  defaults: { sort: 'star_rating', sort_direction: 'ASC', gallery_mode: 'grid', hide_details: true },
  display: { card_width_px: 168, image_width_px: 640, tags_per_photo: 5 },
  features: { show_rating_controls: true },
  quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
  sort_options_grouped: [], search_threshold_default: 0.15,
};

describe('manual activity from rendered gallery menus and stacks', () => {
  let fixture: ComponentFixture<GalleryComponent>;
  let store: GalleryStore;
  let http: HttpTestingController;
  let auth: AuthService;
  let requests: Subject<HttpRequest<unknown>>;
  const requested = (url: string) => firstValueFrom(requests.pipe(filter(request => request.url === url), take(1)));
  const progressRequests = () => http.match(request => request.url === '/api/photos/review_progress');
  const flushSideData = () => {
    for (const request of http.match(request => request.url.startsWith('/api/filter_options/') || request.url === '/api/type_counts')) {
      request.flush({ types: [], cameras: [], lenses: [], tags: [], persons: [], patterns: [], temps: [], hue_buckets: [], ranges: {} });
    }
    for (const request of http.match('/api/photos/keeper_hints')) request.flush({});
  };

  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear();
    requests = new Subject();
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(withXhr(), withInterceptors([(request, next) => { requests.next(request); return next(request); }])), provideHttpClientTesting(), provideRouter([]), provideNativeDateAdapter(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {}, paramMap: convertToParamMap({}) } } },
      { provide: ScanService, useValue: { canLaunch: signal(false) } },
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', t: (key: string, params?: unknown) => `${key} ${JSON.stringify(params ?? {})}` } },
      { provide: AssistantChangesService, useValue: { batch$: NEVER } },
      { provide: MatSnackBar, useValue: { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) } },
    ] });
    auth = TestBed.inject(AuthService);
    auth.status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    http = TestBed.inject(HttpTestingController);
    store = TestBed.inject(GalleryStore);
    fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    const photosStarted = requested('/api/photos');
    http.expectOne('/api/config').flush(config);
    await photosStarted;
    const sideDataStarted = requested('/api/filter_options/metric_ranges');
    http.expectOne(request => request.url === '/api/photos').flush(page);
    progressRequests().forEach(request => request.flush(counts));
    await sideDataStarted;
    flushSideData();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(store.photos()).toHaveLength(2);
  });

  afterEach(() => {
    fixture.destroy();
    TestBed.resetTestingModule();
    http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });

  it('creates a reviewed stack from the rendered selection bar and records activity only after HTTP success', async () => {
    const router = TestBed.inject(Router);
    router.resetConfig([{ path: 'stacks/edit', component: StackEditorPageComponent }, { path: '', component: GalleryComponent }]);
    const routed = await RouterTestingHarness.create();
    const journal = TestBed.inject(UserActivityJournal);
    const cursor = journal.since().until;
    const selected = [...rows, makePhoto({ path: '/trip/c.jpg' })];
    store.restoreSelection(selected.map(photo => photo.path)); fixture.detectChanges();
    const start = requested('/api/stacks/regroup/preview');
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-create-stack]')!.click();
    await vi.waitFor(() => expect(router.url).toBe('/stacks/edit')); routed.detectChanges();
    await start;
    http.expectOne('/api/stacks/regroup/preview').flush({ selected_paths: selected.map(p => p.path), mode: 'combine', paths: selected.map(p => p.path), cover_path: rows[0].path, source_stacks: [], unstacked_paths: selected.map(p => p.path), affected_paths: selected.map(p => p.path), expected_state: 'a'.repeat(64) });
    await fixture.whenStable();
    routed.detectChanges();
    const stackDialog = routed.routeNativeElement!;
    expect(router.url).toBe('/stacks/edit');
    expect(TestBed.inject(MatDialog).openDialogs).toHaveLength(0);
    expect(stackDialog).toBeTruthy();
    expect([...stackDialog.querySelectorAll('img')].every(image => image.getAttribute('src')?.startsWith('/thumbnail?'))).toBe(true);
    stackDialog.querySelector<HTMLButtonElement>('[data-stack-focus="/trip/b.jpg"]')!.click(); routed.detectChanges();
    stackDialog.querySelector<HTMLButtonElement>('button[data-stack-cover]')!.click();
    await fixture.whenStable();
    const refresh = vi.spyOn(store, 'refreshPaths');
    const saving = requested('/api/stacks/regroup/apply');
    stackDialog.querySelector<HTMLButtonElement>('button[mat-flat-button]')!.click(); await saving;
    const request = http.expectOne('/api/stacks/regroup/apply');
    expect(request.request.body).toEqual({ paths: selected.map(photo => photo.path), cover_path: rows[1].path, selected_paths: selected.map(photo => photo.path), mode: 'combine', expected_state: 'a'.repeat(64) });
    expect(journal.since(cursor).items.filter(item => item.kind === 'stack')).toEqual([]);
    request.flush({ stack: { id: 's1', revision: 1, editable: true, cover_path: rows[1].path,
      members: selected.map((photo, position) => ({ path: photo.path, position })) }, undo: { entry_id: 55 }, changed: true, affected_paths: selected.map(photo => photo.path) });
    await fixture.whenStable(); routed.detectChanges();
    expect(router.url).toBe('/stacks/edit');
    await vi.waitFor(() => { routed.detectChanges(); expect(stackDialog.querySelector('[data-stack-saved]')).not.toBeNull(); });
    http.expectNone(req => req.url === '/api/photos');
    fixture.destroy();
    const refreshed = requested('/api/photos');
    stackDialog.querySelector<HTMLButtonElement>('[data-stack-back]')!.click();
    await vi.waitFor(() => expect(router.url).toBe('/')); routed.detectChanges();
    await refreshed;
    http.expectOne(req => req.url === '/api/photos').flush({ ...page, photo_total: 4, total: 2, photos: [{ ...rows[1], stack_id: 's1', stack_count: 3, stack_total_count: 3 }, makePhoto({ path: '/trip/unstacked.jpg' })] });
    progressRequests().forEach(req => req.flush(counts)); flushSideData();
    await refresh.mock.results[0].value;
    await routed.fixture.whenStable(); routed.detectChanges();
    expect(journal.since(cursor).items.filter(item => item.kind === 'stack')).toEqual([expect.objectContaining({ kind: 'stack', paths: selected.map(photo => photo.path), value: 'create' })]);
    expect(routed.routeNativeElement!.textContent).toContain('stacks.totals');
    expect(store.selectedPaths().size).toBe(0);
    expect(routed.routeNativeElement!.textContent).not.toContain('gallery.selection.view_scope_offer');
    const cards = [...(routed.routeNativeElement as HTMLElement).querySelectorAll('app-photo-card [role=button]')];
    expect(cards.map(card => card.getAttribute('aria-pressed'))).toEqual(['false', 'false']);
    routed.fixture.destroy();
  });

  it('explicitly selects every permitted member through the separate stack editor', async () => {
    store.photos.set([{ ...rows[0], stack_id: 's1', stack_count: 1, stack_total_count: 3 }]);
    fixture.detectChanges(); const loading = requested('/api/stacks/s1');
    const { StackDialogComponent } = await import('./stack-dialog.component');
    TestBed.inject(MatDialog).open(StackDialogComponent, { data: { stackId: 's1' } });
    fixture.detectChanges(); await loading;
    const members = ['/trip/a.jpg', '/elsewhere/filtered.jpg', '/rejected/member.jpg'];
    http.expectOne('/api/stacks/s1').flush({ id: 's1', revision: 7, editable: false, cover_path: members[0],
      members: members.map((path, position) => ({ path, position })) });
    await fixture.whenStable();
    const dialog = TestBed.inject(OverlayContainer).getContainerElement().querySelector('app-stack-dialog')!;
    expect(dialog.querySelectorAll('[data-stack-tile] img')).toHaveLength(3);
    expect(dialog.textContent).toContain('stacks.read_only');
    const select = [...dialog.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes('stacks.select_all'))!;
    select.click(); await fixture.whenStable();
    expect([...store.selectedPaths()]).toEqual(members);
    expect(store.viewScopeSelected()).toBe(false);
    http.expectNone(request => request.method === 'PUT' || request.method === 'DELETE');
  });

  it('disables stack creation for whole-view selection and discloses folded members', async () => {
    store.selectWholeView(); fixture.detectChanges();
    const button = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-create-stack]')!;
    expect(button.disabled).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('stacks.folded_scope');
    button.click(); http.expectNone('/api/stacks');
  });

  it.each([
    ['kept', false], ['undecided', false], ['kept', true], ['undecided', true],
  ] as const)('reports %s from the real %s-bulk context-menu dispatch after HTTP success', async (decision, bulk) => {
    const journal = TestBed.inject(UserActivityJournal);
    const cursor = journal.since().until;
    const batch = vi.spyOn(store, 'batchReview');
    if (bulk) store.selectedPaths.set(new Set(rows.map(photo => photo.path)));
    fixture.detectChanges();
    const card = fixture.nativeElement.querySelector('app-photo-card');
    card.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2 }));
    fixture.detectChanges();
    await fixture.whenStable();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    const label = decision === 'kept' ? 'review.keep' : 'review.reset';
    const button = [...overlay.querySelectorAll<HTMLButtonElement>('button[mat-menu-item]')]
      .find(button => button.textContent?.includes(label + ' {}'));
    expect(button).toBeDefined();
    const writeStarted = requested('/api/photos/batch_review');
    button!.click();
    await writeStarted;
    expect(journal.since(cursor).items).toEqual([]);
    const request = http.expectOne('/api/photos/batch_review');
    expect(request.request.body).toEqual({ photo_paths: bulk ? rows.map(photo => photo.path) : [rows[0].path], decision });
    const countStarted = requested('/api/photos/review_progress');
    request.flush({ count: bulk ? 2 : 1 });
    await countStarted;
    progressRequests().forEach(request => request.flush(counts));
    await batch.mock.results[0].value;
    await fixture.whenStable();
    expect(journal.since(cursor).items).toEqual([expect.objectContaining({
      kind: 'review', value: decision, paths: bulk ? rows.map(photo => photo.path) : [rows[0].path],
    })]);
  });
});
