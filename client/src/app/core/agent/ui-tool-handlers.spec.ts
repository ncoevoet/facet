import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { Component } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { HttpBackend, HttpErrorResponse, HttpRequest, HttpResponse } from '@angular/common/http';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from '../services/api.service';
import { AuthService } from '../services/auth.service';
import { AlbumService } from '../services/album.service';
import type { Album } from '../services/album.service';
import { I18nService } from '../services/i18n.service';
import { GalleryStore, PhotosResponse, ViewerConfig } from '../../features/gallery/gallery.store';
import { makePhoto } from '../../../testing/photo.fixture';
import { contractHandlerMismatch, WebMcpToolRegistry } from './webmcp-registry.service';
import { routes } from '../../app.routes';
import { CULL_DEFAULT_STRICTNESS, CULL_PROFILE_KEY, CULL_STRICTNESS_KEY } from '../../features/gallery/culling.store';
import { DEFAULT_FILTERS, SMART_ALBUM_EXCLUDE_KEYS } from '../../features/gallery/gallery-filters.util';
import { CONTRACT_TO_CLIENT_KEY, applicableActions, capCullingSnapshot, createUiToolHandlers } from './ui-tool-handlers';
import { CompareFiltersService } from '../../features/comparison/compare-filters.service';
import { ViewActionRegistry } from './view-action-registry.service';
import { CONNECT_ASSISTANT_DIALOG_ID, PageContextService } from './page-context.service';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { MatDialog } from '@angular/material/dialog';
import { AssistantChangeBatch, AssistantChangesService } from './assistant-changes.service';
import { UserActivityJournal } from './user-activity-journal.service';
import { AssistantCullPlanService, type CullPlanEntryInput } from './assistant-cull-plan.service';
import contractFile from './ui-tools.schema.json';
import { UI_TOOL_ERROR_CODES, UiToolContractFile, UiToolEnvelope } from './ui-tool.types';

@Component({ selector: 'app-stub-page', template: '' })
class StubPage {}

const CONFIG = {
  pagination: { default_per_page: 64 },
  defaults: { type: '', sort: 'aggregate', sort_direction: 'DESC', hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true, hide_details: true, tooltip_mode: 'hover', panel_activation: 'both', hide_rejected: true },
  display: { tags_per_photo: 5, card_width_px: 300, image_width_px: 640 },
  sort_options_grouped: null,
  features: {},
  quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
  search_threshold_default: 0.15,
} as unknown as ViewerConfig;

function photosResponse(paths: string[], hasMore = false): PhotosResponse {
  return {
    photos: paths.map(path => makePhoto({ path, filename: path.slice(1) })),
    total: 120, page: 1, per_page: 64, total_pages: 2, has_more: hasMore,
  };
}

describe('UI tool registry and handlers', () => {
  let registry: WebMcpToolRegistry;
  let store: GalleryStore;
  let apiGet: Mock;
  let navigate: Mock;
  let router: { navigate: Mock; url: string; events: unknown; config: unknown };
  let edition: boolean;
  let multiUser: boolean;
  let viewActions: ViewActionRegistry;
  let routerEvents: Subject<unknown>;
  let assistantBatches: Subject<AssistantChangeBatch>;
  let fetchAlbum: Mock;
  let openDialogs: { id?: string; componentInstance?: unknown }[];

  const run = (name: string, args: unknown = {}): Promise<UiToolEnvelope> => registry.execute(name, args);
  /** The handlers without the registry's schema gate, to prove each one defends itself. */
  const direct = (): ReturnType<typeof createUiToolHandlers> => createUiToolHandlers({
    gallery: store, router: router as unknown as Router,
    auth: { isEdition: () => edition } as unknown as AuthService, viewActions, actions: () => [],
    compareFilters: TestBed.inject(CompareFiltersService),
    journal: TestBed.inject(UserActivityJournal),
    plan: TestBed.inject(AssistantCullPlanService),
    pageContext: TestBed.inject(PageContextService),
    fetchAlbum,
  });

  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    edition = false;
    multiUser = false;
    openDialogs = [];
    fetchAlbum = vi.fn((id: number) => Promise.resolve({ id, name: 'Iceland', is_smart: false } as Album));
    apiGet = vi.fn(() => of(photosResponse(['/a.jpg', '/b.jpg', '/c.jpg'])));
    navigate = vi.fn(() => Promise.resolve(true));
    routerEvents = new Subject<unknown>();
    assistantBatches = new Subject<AssistantChangeBatch>();
    router = { navigate, url: '/', events: routerEvents, config: routes };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get: apiGet, post: vi.fn(() => of({})) } },
        { provide: Router, useValue: router },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { identity: () => '0|', isEdition: () => edition, isMultiUser: () => multiUser, isAuthenticated: () => true } },
        // The real GalleryStore subscribes to assistant write batches; none arrive here.
        { provide: AssistantChangesService, useValue: { batch$: assistantBatches } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: MatDialog, useValue: { get openDialogs() { return openDialogs; } } },
        { provide: MatBottomSheet, useValue: { _openedBottomSheetRef: null } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.config.set(CONFIG);
    viewActions = TestBed.inject(ViewActionRegistry);
    registry = TestBed.inject(WebMcpToolRegistry);
    await registry.load();
  });

  describe('registry', () => {
    it('has a handler for every contract entry and a contract entry for every handler', () => {
      const handlers = createUiToolHandlers({
        gallery: store, router: router as unknown as Router,
        auth: { isEdition: () => edition } as unknown as AuthService, viewActions, actions: () => [],
        compareFilters: TestBed.inject(CompareFiltersService),
        journal: TestBed.inject(UserActivityJournal),
        plan: TestBed.inject(AssistantCullPlanService),
        pageContext: TestBed.inject(PageContextService),
        fetchAlbum,
      });
      const mismatch = contractHandlerMismatch((contractFile as unknown as UiToolContractFile).tools, handlers);
      expect(mismatch).toEqual({ missingHandlers: [], missingContract: [] });
      expect(registry.toolNames.length).toBe((contractFile as unknown as UiToolContractFile).tools.length);
    });

    it('reports the error codes the server lets a tab use', () => {
      expect([...UI_TOOL_ERROR_CODES].sort()).toEqual((contractFile as unknown as UiToolContractFile).error_codes);
    });

    it('keeps the filter-name table and the smart-album exclusions equal to the server contract', () => {
      const file = contractFile as unknown as UiToolContractFile;
      expect(CONTRACT_TO_CLIENT_KEY).toEqual(file.filter_key_map);
      expect([...SMART_ALBUM_EXCLUDE_KEYS].sort()).toEqual(file.smart_album_exclude_keys);
    });

    describe('modal_open', () => {
      const file = contractFile as unknown as UiToolContractFile;
      const CALLS: Record<string, Record<string, unknown>> = {
        ui_navigate: { route: '/stats' },
        ui_set_gallery_filters: { patch: {} },
        ui_open_photo: { path: '/a.jpg' },
        ui_open_album: { album_id: 3 },
        ui_show_photos: { paths: ['/a.jpg'] },
        ui_select_photos: { paths: ['/a.jpg'] },
        ui_clear_selection: {},
        ui_next_page: {},
        ui_show_culling_group: { type: 'burst', group_id: 1 },
        ui_show_culling_plan: { plan_digest: 'd1', request: { group_by: 'burst', strictness: 40 } },
        ui_suggest_culling: {},
        ui_show_comparison: {},
      };
      const mutating = file.tools.filter(tool => !tool.annotations.readOnlyHint).map(tool => tool.name);

      it('has a call for every tool that changes the view', () => {
        expect(Object.keys(CALLS).sort()).toEqual([...mutating].sort());
      });

      it.each(mutating)('%s answers modal_open under a dialog and touches nothing', async name => {
        openDialogs.push({ componentInstance: {} });
        const selectSpy = vi.spyOn(store, 'clearSelection');
        edition = true;
        const result = await run(name, CALLS[name]);
        expect(result).toMatchObject({ ok: false, error: 'modal_open' });
        expect(navigate).not.toHaveBeenCalled();
        expect(selectSpy).not.toHaveBeenCalled();
        expect(apiGet).not.toHaveBeenCalled();
      });

      it('lets the read-only tools answer under a dialog', async () => {
        openDialogs.push({ componentInstance: {} });
        for (const name of ['ui_get_context', 'ui_get_selection', 'ui_get_gallery_view']) {
          expect((await run(name)).ok, name).toBe(true);
        }
      });

      it('still answers invalid_input first, and modal_open before the unsaved-decisions guard', async () => {
        openDialogs.push({ componentInstance: {} });
        expect(await run('ui_navigate', { route: '/admin' })).toMatchObject({ ok: false, error: 'invalid_input' });
        router.url = '/culling';
        expect(await run('ui_navigate', { route: '/stats' })).toMatchObject({ ok: false, error: 'modal_open' });
      });

      it('ui_open_album re-checks the gate after the album read and does not navigate', async () => {
        let resolveAlbum: (album: Album) => void = () => undefined;
        fetchAlbum.mockImplementationOnce(() => new Promise<Album>(resolve => { resolveAlbum = resolve; }));
        const pending = direct()['ui_open_album']({ album_id: 3 });
        openDialogs.push({ componentInstance: {} });
        resolveAlbum({ id: 3, name: 'Iceland', is_smart: false } as Album);
        await expect(pending).rejects.toMatchObject({ code: 'modal_open' });
        expect(navigate).not.toHaveBeenCalled();
      });

      it('does not refuse for the connect-assistant dialog alone', async () => {
        openDialogs.push({ id: CONNECT_ASSISTANT_DIALOG_ID });
        expect(await run('ui_navigate', { route: '/stats' })).toMatchObject({ ok: true });
      });
    });

    it('answers invalid_input for an enum violation and never throws', async () => {
      const result = await run('ui_navigate', { route: '/admin' });
      expect(result).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(navigate).not.toHaveBeenCalled();
    });

    it('rejects unknown properties and answers not_found for an unknown tool', async () => {
      expect(await run('ui_clear_selection', { surprise: 1 })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_nope')).toMatchObject({ ok: false, error: 'not_found' });
    });

    it('reports a handler failure as upstream_error rather than throwing', async () => {
      navigate.mockRejectedValueOnce(new Error('boom'));
      expect(await run('ui_navigate', { route: '/stats' })).toMatchObject({ ok: false, error: 'upstream_error', message: 'boom' });
    });
  });

  describe('ui_navigate', () => {
    it('navigates to an allowed route with the query', async () => {
      const result = await run('ui_navigate', { route: '/stats', query: { year: 2024 } });
      expect(result.ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/stats'], { queryParams: { year: '2024' }, onSameUrlNavigation: 'reload' });
    });

    it('refuses edition-only routes for a non-edition session', async () => {
      for (const route of ['/culling', '/junk', '/compare', '/merge-suggestions']) {
        expect(await run('ui_navigate', { route })).toMatchObject({ ok: false, error: 'forbidden_level' });
      }
      expect(navigate).not.toHaveBeenCalled();
    });

    it('allows edition-only routes for an edition session', async () => {
      edition = true;
      expect((await run('ui_navigate', { route: '/culling' })).ok).toBe(true);
    });

    it('reports a refused navigation as navigation_refused', async () => {
      navigate.mockResolvedValueOnce(false);
      expect(await run('ui_navigate', { route: '/stats' })).toMatchObject({ ok: false, error: 'navigation_refused' });
    });
  });

  describe('prototype names', () => {
    it('are refused as filter keys by the schema and by the handler itself', async () => {
      for (const key of ['constructor', 'hasOwnProperty', 'toString', '__proto__']) {
        const patch = JSON.parse(`{"${key}":"x"}`);
        expect(await run('ui_set_gallery_filters', { patch })).toMatchObject({ ok: false, error: 'invalid_input' });
        await expect(direct()['ui_set_gallery_filters']({ patch })).rejects.toMatchObject({ code: 'invalid_input' });
      }
      expect(Object.hasOwn(store.filters(), 'constructor')).toBe(false);
      expect(Object.hasOwn(store.filters(), 'hasOwnProperty')).toBe(false);
    });
  });

  describe('contract parity', () => {
    it('every ui_set_gallery_filters patch key lands on a key of DEFAULT_FILTERS', () => {
      const tool = (contractFile as unknown as UiToolContractFile).tools.find(t => t.name === 'ui_set_gallery_filters');
      const patchKeys = Object.keys(tool?.inputSchema.properties?.['patch'].properties ?? {});
      const rename: Record<string, string> = { person: 'person_id', category: 'type', semantic_query: 'semanticQuery', semantic_threshold: 'search_threshold' };
      expect(patchKeys.length).toBeGreaterThan(50);
      const orphans = patchKeys.filter(key => !Object.hasOwn(DEFAULT_FILTERS, rename[key] ?? key));
      expect(orphans).toEqual([]);
    });

    it('rejects category together with type, whichever comes first', async () => {
      expect(await run('ui_set_gallery_filters', { patch: { category: 'macro', type: 'portrait' } })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_set_gallery_filters', { patch: { type: 'portrait', category: 'macro' } })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(store.filters().type).toBe('');
    });

    it('echoes the contract names in the view, category rather than type', async () => {
      await run('ui_set_gallery_filters', { patch: { category: 'macro' } });
      const data = ((await run('ui_get_gallery_view', {})) as { data: { filters: Record<string, unknown> } }).data;
      expect(data.filters['category']).toBe('macro');
      expect(data.filters).not.toHaveProperty('type');
    });
  });

  describe('ui_navigate against the real client routes', () => {
    const contractRoutes = (): string[] => {
      const tool = (contractFile as unknown as UiToolContractFile).tools.find(t => t.name === 'ui_navigate');
      return (tool?.inputSchema.properties?.['route'] as { enum?: string[] } | undefined)?.enum ?? [];
    };

    it('every route the contract offers is a static path the app router defines', () => {
      const defined = new Set(routes.filter(r => r.path !== undefined && r.redirectTo === undefined).map(r => `/${r.path}`));
      expect(contractRoutes().length).toBeGreaterThan(10);
      expect(contractRoutes().filter(route => !defined.has(route))).toEqual([]);
    });

    it('a same-URL navigation resolves true on a real router instead of being skipped', async () => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [provideRouter([{ path: 'stats', component: StubPage }, { path: '', component: StubPage }])],
      });
      const realRouter = TestBed.inject(Router);
      await realRouter.navigateByUrl('/stats');
      const handlers = createUiToolHandlers({
        gallery: store, router: realRouter, auth: { isEdition: () => false } as unknown as AuthService, viewActions, actions: () => [],
        compareFilters: TestBed.inject(CompareFiltersService),
        journal: TestBed.inject(UserActivityJournal),
        plan: TestBed.inject(AssistantCullPlanService),
        pageContext: TestBed.inject(PageContextService),
        fetchAlbum,
      });
      await expect(handlers['ui_navigate']({ route: '/stats' })).resolves.toEqual({ route: '/stats' });
    });
  });

  /** A navigation that mounts a fresh gallery which finishes loading `album` after a short delay, as the real page does. */
  const mountsAlbum = (target: GalleryStore, album: { id: number; name: string; is_smart: boolean }): void => {
    navigate.mockImplementation(() => {
      target.galleryMounts.update(n => n + 1);
      target.currentAlbum.set(null);
      target.initializing.set(true);
      setTimeout(() => {
        target.currentAlbum.set(album as Album);
        target.initializing.set(false);
      }, 40);
      return Promise.resolve(true);
    });
  };

  describe('ui_open_album', () => {
    beforeEach(() => mountsAlbum(store, { id: 5, name: 'Iceland', is_smart: false }));

    it('resolves only once the gallery shows the requested album', async () => {
      router.url = '/album/2';
      store.currentAlbum.set({ id: 2, name: 'Old', is_smart: true } as Album);
      await direct()['ui_open_album']({ album_id: 5 });
      expect(store.initializing()).toBe(false);
      expect(store.currentAlbum()?.id).toBe(5);
    });

    it('refuses with unsaved_decisions when decisions appear while the album is being read', async () => {
      router.url = '/culling';
      const plan = TestBed.inject(AssistantCullPlanService);
      let unsaved = false;
      plan.hasUnsavedDecisions = () => unsaved;
      let release: (album: Album) => void = () => undefined;
      fetchAlbum.mockReturnValueOnce(new Promise<Album>(resolve => { release = resolve; }));
      const pending = direct()['ui_open_album']({ album_id: 5 });
      unsaved = true;
      release({ id: 5, name: 'Iceland', is_smart: false } as Album);
      await expect(pending).rejects.toMatchObject({ code: 'unsaved_decisions' });
      expect(navigate).not.toHaveBeenCalled();
    });

    it('treats a status 0 failure as a network error', async () => {
      fetchAlbum.mockRejectedValueOnce({ status: 0 });
      await expect(direct()['ui_open_album']({ album_id: 5 })).rejects.toMatchObject({ code: 'upstream_error', message: expect.stringContaining('network error') });
    });

    it('opens a fixed album and a smart album, reporting name and kind', async () => {
      expect(await direct()['ui_open_album']({ album_id: 5 })).toEqual({ route: '/album/5', album_id: 5, name: 'Iceland', is_smart: false });
      expect(navigate).toHaveBeenCalledWith(['/album', 5], { onSameUrlNavigation: 'reload' });
      mountsAlbum(store, { id: 6, name: 'Best of', is_smart: true });
      fetchAlbum.mockResolvedValueOnce({ id: 6, name: 'Best of', is_smart: true });
      expect(await direct()['ui_open_album']({ album_id: 6 })).toEqual({ route: '/album/6', album_id: 6, name: 'Best of', is_smart: true });
    });

    it('answers not_found for an unknown (404) or another user\'s (403) album and does not navigate', async () => {
      for (const status of [404, 403]) {
        fetchAlbum.mockRejectedValueOnce({ status });
        await expect(direct()['ui_open_album']({ album_id: 99 })).rejects.toMatchObject({ code: 'not_found' });
      }
      expect(navigate).not.toHaveBeenCalled();
    });

    it('answers upstream_error for a server failure and does not navigate', async () => {
      fetchAlbum.mockRejectedValueOnce({ status: 500 });
      await expect(direct()['ui_open_album']({ album_id: 5 })).rejects.toMatchObject({ code: 'upstream_error' });
      expect(navigate).not.toHaveBeenCalled();
    });

    it('reports a declined navigation as navigation_refused', async () => {
      navigate.mockResolvedValueOnce(false);
      await expect(direct()['ui_open_album']({ album_id: 5 })).rejects.toMatchObject({ code: 'navigation_refused' });
    });

    it('refuses a bad id as invalid_input before any request', async () => {
      for (const album_id of [0, -1, 1.5, '5', 2 ** 31, null]) {
        await expect(direct()['ui_open_album']({ album_id })).rejects.toMatchObject({ code: 'invalid_input' });
      }
      expect(fetchAlbum).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
    });

    it('is refused with unsaved_decisions on /culling before the album is fetched', async () => {
      router.url = '/culling';
      TestBed.inject(AssistantCullPlanService).hasUnsavedDecisions = () => true;
      await expect(direct()['ui_open_album']({ album_id: 5 })).rejects.toMatchObject({ code: 'unsaved_decisions' });
      expect(fetchAlbum).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
    });

    it('answers already_open without fetching or navigating when the album is on screen', async () => {
      router.url = '/album/5?sort=date';
      expect(await direct()['ui_open_album']({ album_id: 5 })).toEqual({ route: '/album/5', album_id: 5, already_open: true });
      expect(fetchAlbum).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
    });

    it('keeps parameterised and shared paths unreachable as a bare route', async () => {
      for (const route of ['/album/5', '/timeline/2024/3', '/shared/album/5']) {
        await expect(direct()['ui_navigate']({ route })).rejects.toMatchObject({ code: 'invalid_input' });
      }
    });
  });

  describe('ui_navigate timeline year and month', () => {
    it('lands on the unpadded month, the year alone, or the plain timeline', async () => {
      await direct()['ui_navigate']({ route: '/timeline', year: 2024, month: 3 });
      expect(navigate).toHaveBeenLastCalledWith(['/timeline', '2024', '3'], { queryParams: {}, onSameUrlNavigation: 'reload' });
      await direct()['ui_navigate']({ route: '/timeline', year: 2024 });
      expect(navigate).toHaveBeenLastCalledWith(['/timeline', '2024'], { queryParams: {}, onSameUrlNavigation: 'reload' });
      await direct()['ui_navigate']({ route: '/timeline' });
      expect(navigate).toHaveBeenLastCalledWith(['/timeline'], { queryParams: {}, onSameUrlNavigation: 'reload' });
    });

    it('refuses month without year, out-of-range values, another route and a query, without navigating', async () => {
      const bad = [
        { route: '/timeline', month: 3 },
        { route: '/timeline', year: 2024, month: 13 },
        { route: '/timeline', year: 2024, month: 0 },
        { route: '/timeline', year: 1800 },
        { route: '/timeline', year: 2024.5 },
        { route: '/stats', year: 2024 },
        { route: '/stats', year: 2024, month: 3 },
        { route: '/timeline', year: 2024, query: { a: 1 } },
      ];
      for (const args of bad) await expect(direct()['ui_navigate'](args)).rejects.toMatchObject({ code: 'invalid_input' });
      expect(navigate).not.toHaveBeenCalled();
    });

    it('is refused with unsaved_decisions when it would leave /culling', async () => {
      router.url = '/culling';
      TestBed.inject(AssistantCullPlanService).hasUnsavedDecisions = () => true;
      await expect(direct()['ui_navigate']({ route: '/timeline', year: 2024, month: 3 })).rejects.toMatchObject({ code: 'unsaved_decisions' });
      expect(navigate).not.toHaveBeenCalled();
    });

    it('ui_get_context reports the timeline year and month, and null elsewhere', async () => {
      router.url = '/timeline/2024/3';
      expect(((await run('ui_get_context')) as { data: unknown }).data).toMatchObject({ timeline: { year: 2024, month: 3 } });
      router.url = '/timeline/2024';
      expect(((await run('ui_get_context')) as { data: unknown }).data).toMatchObject({ timeline: { year: 2024, month: null } });
      router.url = '/timeline';
      expect(((await run('ui_get_context')) as { data: unknown }).data).toMatchObject({ timeline: null });
      router.url = '/stats';
      expect(((await run('ui_get_context')) as { data: unknown }).data).toMatchObject({ timeline: null });
    });
  });

  describe('ui_open_album probe through the registry', () => {
    it('reads the album without an interceptor toast, revalidation or crash report', async () => {
      const handle = vi.fn(() => of(new HttpResponse({ status: 200, body: { id: 5, name: 'Iceland', is_smart: false } })));
      TestBed.resetTestingModule();
      const open = vi.fn();
      const revalidate = vi.fn();
      TestBed.configureTestingModule({
        providers: [
          { provide: HttpBackend, useValue: { handle } },
          { provide: Router, useValue: router },
          { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
          { provide: AuthService, useValue: { token: 'tok', identity: () => '0|', isEdition: () => false, isMultiUser: () => false, isAuthenticated: () => true, revalidate } },
          { provide: AssistantChangesService, useValue: { batch$: assistantBatches } },
          { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })) } },
          { provide: ApiService, useValue: { get: apiGet, post: vi.fn(() => of({})) } },
          { provide: MatSnackBar, useValue: { open } },
          { provide: I18nService, useValue: { t: (k: string) => k } },
        ],
      });
      mountsAlbum(TestBed.inject(GalleryStore), { id: 5, name: 'Iceland', is_smart: false });
      const fresh = TestBed.inject(WebMcpToolRegistry);
      await fresh.load();
      expect(await fresh.execute('ui_open_album', { album_id: 5 })).toMatchObject({ ok: true, data: { name: 'Iceland' } });
      const sent = (handle.mock.calls[0] as unknown as [HttpRequest<unknown>])[0];
      expect(sent.url).toBe('/api/albums/5');
      expect(sent.headers.get('Authorization')).toBe('Bearer tok');
      handle.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500, url: '/api/albums/5' })));
      expect(await fresh.execute('ui_open_album', { album_id: 6 })).toMatchObject({ ok: false, error: 'upstream_error' });
      handle.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 403, url: '/api/albums/7' })));
      expect(await fresh.execute('ui_open_album', { album_id: 7 })).toMatchObject({ ok: false, error: 'not_found' });
      expect(open).not.toHaveBeenCalled();
      expect(revalidate).not.toHaveBeenCalled();
      expect(handle).toHaveBeenCalledTimes(3);
    });
  });

  describe('ui_show_comparison', () => {
    it('sets category, strategy and the A/B tab through the service, submits nothing and sends no answer key', async () => {
      edition = true;
      const filters = TestBed.inject(CompareFiltersService);
      const post = TestBed.inject(ApiService).post as unknown as Mock;
      const keys: string[] = [];
      const onKey = (event: KeyboardEvent): void => { keys.push(event.key); };
      // The comparison page's shortcuts listen on window, so a key sent from the tool would land there.
      window.addEventListener('keydown', onKey, true);
      document.addEventListener('keydown', onKey, true);
      try {
        const result = await direct()['ui_show_comparison']({ category: 'portrait', strategy: 'boundary' });
        expect(result).toEqual({ route: '/compare', category: 'portrait', strategy: 'boundary', tab: 'ab' });
      } finally {
        window.removeEventListener('keydown', onKey, true);
        document.removeEventListener('keydown', onKey, true);
      }
      expect(navigate).toHaveBeenCalledWith(['/compare']);
      expect(filters.selectedCategory()).toBe('portrait');
      expect(filters.strategy()).toBe('boundary');
      expect(filters.activeTab()).toBe(1);
      expect(post).not.toHaveBeenCalled();
      expect(keys).toEqual([]);
    });

    it.each([
      ['snapshots', 0],
      ['ab', 1],
      ['suggestions', 2],
      ['weights', 3],
    ])('opens the %s tab (index %i) and reports it', async (tab, index) => {
      edition = true;
      const filters = TestBed.inject(CompareFiltersService);
      const result = await direct()['ui_show_comparison']({ tab });
      expect(result).toMatchObject({ route: '/compare', tab });
      expect(filters.activeTab()).toBe(index);
    });

    it('refuses an unknown tab before touching the filters or navigating', async () => {
      edition = true;
      const filters = TestBed.inject(CompareFiltersService);
      await expect(direct()['ui_show_comparison']({ tab: 'priority', category: 'portrait' })).rejects.toMatchObject({ code: 'invalid_input' });
      expect(filters.selectedCategory()).toBe('');
      expect(navigate).not.toHaveBeenCalled();
    });

    it('answers success without navigating when the tab is already on /compare', async () => {
      edition = true;
      router.url = '/compare?x=1';
      navigate.mockResolvedValue(false);
      const result = await direct()['ui_show_comparison']({ strategy: 'boundary' });
      expect(result).toMatchObject({ route: '/compare', strategy: 'boundary', tab: 'ab' });
      expect(navigate).not.toHaveBeenCalled();
    });

    it('still reports a refused navigation when coming from another page', async () => {
      edition = true;
      router.url = '/';
      navigate.mockResolvedValue(false);
      await expect(direct()['ui_show_comparison']({})).rejects.toMatchObject({ code: 'navigation_refused' });
    });

    it('needs an edition session and touches nothing without one', async () => {
      const filters = TestBed.inject(CompareFiltersService);
      await expect(direct()['ui_show_comparison']({ category: 'portrait' })).rejects.toMatchObject({ code: 'forbidden_level' });
      expect(navigate).not.toHaveBeenCalled();
      expect(filters.selectedCategory()).toBe('');
    });

    it('the contract offers no property that could carry an answer', () => {
      const tool = (contractFile as unknown as UiToolContractFile).tools.find(t => t.name === 'ui_show_comparison');
      expect(tool).toBeDefined();
      const props = Object.keys(tool?.inputSchema.properties ?? {});
      expect(props.filter(p => /choice|winner|answer|submit/.test(p))).toEqual([]);
    });
  });

  describe('ui_navigate route restriction', () => {
    it('refuses anything that is not a static app route, before navigating', async () => {
      for (const route of ['//evil.example', 'https://evil.example', 'javascript:alert(1)', '/login', '/shared/album/1', '/album/3', '/nope', 'stats']) {
        await expect(direct()['ui_navigate']({ route })).rejects.toMatchObject({ code: 'invalid_input' });
      }
      expect(navigate).not.toHaveBeenCalled();
    });

    it('derives the edition-only pages from the route data, not a hand list', async () => {
      const editionRoutes = routes.filter(r => (r.data as { edition?: boolean } | undefined)?.edition).map(r => `/${r.path}`);
      expect(editionRoutes.length).toBeGreaterThan(0);
      for (const route of editionRoutes) {
        await expect(direct()['ui_navigate']({ route })).rejects.toMatchObject({ code: 'forbidden_level' });
      }
      expect(navigate).not.toHaveBeenCalled();
    });
  });

  describe('ui_set_gallery_filters', () => {
    it('writes the store filters and syncs the URL', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { min_aesthetic: '7' } });
      expect(result).toMatchObject({ ok: true });
      expect(store.filters().min_aesthetic).toBe('7');
      expect(navigate).toHaveBeenCalledWith([], expect.objectContaining({
        queryParams: expect.objectContaining({ min_aesthetic: '7' }),
      }));
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ min_aesthetic: '7', page: 1 }));
    });

    it('stringifies numbers, renames person and upper-cases the sort direction', async () => {
      await run('ui_set_gallery_filters', { patch: { min_score: 8.5, person: 12, sort: 'date_taken', sort_direction: 'asc' } });
      expect(store.filters()).toMatchObject({ min_score: '8.5', person_id: '12', sort: 'date_taken', sort_direction: 'ASC' });
    });

    it('clears a filter with null', async () => {
      await run('ui_set_gallery_filters', { patch: { camera: 'Canon' } });
      await run('ui_set_gallery_filters', { patch: { camera: null } });
      expect(store.filters().camera).toBe('');
    });

    it('coerces booleans', async () => {
      await run('ui_set_gallery_filters', { patch: { hide_bursts: false, favorites_only: '1' } });
      expect(store.filters()).toMatchObject({ hide_bursts: false, favorites_only: true });
    });

    it('replace starts from no filters', async () => {
      await run('ui_set_gallery_filters', { patch: { camera: 'Canon', min_iso: 100 } });
      await run('ui_set_gallery_filters', { patch: { lens: '50mm' }, replace: true });
      expect(store.filters()).toMatchObject({ camera: '', min_iso: '', lens: '50mm' });
    });

    it('accepts and reports the review queue, then clears it on replace', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { review_status: 'undecided' } });
      expect(result.ok).toBe(true);
      expect(store.filters()).toMatchObject({ review_status: 'undecided', sort: 'date_taken', sort_direction: 'ASC' });
      const view = await run('ui_get_gallery_view', {});
      expect(view).toMatchObject({ data: { filters: { review_status: 'undecided' } } });
      await run('ui_set_gallery_filters', { patch: { lens: '50mm' }, replace: true });
      expect(store.filters()).toMatchObject({ review_status: '', lens: '50mm' });
    });

    it('replace also lifts a set scope the user opened', async () => {
      await store.updateFilters({ sequence_group_id: '4', sequence_kind: 'burst', burst_group_id: '4', duplicate_group_id: '2' });
      await run('ui_set_gallery_filters', { patch: { lens: '50mm' }, replace: true });
      expect(store.filters()).toMatchObject({ sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '' });
    });

    it('refuses a filter the tab cannot show, without applying the rest', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { camera: 'Canon', junk_kind: 'blurry' } });
      expect(result).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(store.filters().camera).toBe('');
    });

    it('opens the gallery first when another page is showing', async () => {
      router.url = '/stats';
      navigate.mockImplementationOnce(async () => {
        router.url = '/';
        store.galleryMounts.update(n => n + 1);
        return true;
      });
      const pending = run('ui_set_gallery_filters', { patch: { camera: 'Canon' } });
      expect((await pending).ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/']);
    });
  });

  describe('semantic and similar views', () => {
    it('maps a 0-1 semantic threshold to the percent string the store keeps', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { semantic_query: 'red sunset', semantic_threshold: 0.25 }, replace: true });
      expect(result.ok).toBe(true);
      expect(store.filters()).toMatchObject({ semanticQuery: 'red sunset', search_threshold: '25' });
    });

    it('lands on relevance for a semantic query without leaking the sort into the view contract', async () => {
      await run('ui_set_gallery_filters', { patch: { semantic_query: 'red sunset' }, replace: true });
      expect(store.filters()).toMatchObject({ semanticQuery: 'red sunset', sort: 'relevance', sort_direction: 'DESC' });
      const data = ((await run('ui_get_gallery_view', {})) as { data: { filters: Record<string, unknown> } }).data;
      expect(data.filters).not.toHaveProperty('sort');
      expect(data.filters).not.toHaveProperty('sort_direction');
      await run('ui_set_gallery_filters', { patch: {}, replace: true });
      expect(store.filters().sort).not.toBe('relevance');
    });

    it('maps similar_to with its mode and a 0-1 floor to a percent string', async () => {
      await run('ui_set_gallery_filters', { patch: { similar_to: '/a.jpg', similarity_mode: 'color', min_similarity: 0.8 }, replace: true });
      expect(store.filters()).toMatchObject({ similar_to: '/a.jpg', similarity_mode: 'color', min_similarity: '80' });
    });

    it('keeps a fractional percent without rounding loss', async () => {
      await run('ui_set_gallery_filters', { patch: { similar_to: '/a.jpg', min_similarity: 0.855 } });
      expect(store.filters().min_similarity).toBe('85.5');
    });

    it('refuses similar_to together with semantic_query, applying nothing', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { similar_to: '/a.jpg', semantic_query: 'x' } });
      expect(result).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(store.filters()).toMatchObject({ similar_to: '', semanticQuery: '' });
    });

    it('refuses a threshold above the slider ceiling and an unknown mode', async () => {
      expect(await direct()['ui_set_gallery_filters']({ patch: { semantic_query: 'x', semantic_threshold: 0.7 } }).catch((e: unknown) => e))
        .toMatchObject({ code: 'invalid_input' });
      expect(await direct()['ui_set_gallery_filters']({ patch: { similar_to: '/a.jpg', similarity_mode: 'nope' } }).catch((e: unknown) => e))
        .toMatchObject({ code: 'invalid_input' });
    });

    it('null puts the knobs back to the seeded or default values', async () => {
      await run('ui_set_gallery_filters', { patch: { semantic_query: 'x', semantic_threshold: 0.3 } });
      await run('ui_set_gallery_filters', { patch: { semantic_threshold: null, semantic_query: null } });
      expect(store.filters()).toMatchObject({ semanticQuery: '', search_threshold: '15' });
    });

    it('echoes the new keys in the view under contract names and 0-1 units', async () => {
      await run('ui_set_gallery_filters', { patch: { similar_to: '/a.jpg', similarity_mode: 'color', min_similarity: 0.8 } });
      let data = ((await run('ui_get_gallery_view', {})) as { data: { filters: Record<string, unknown> } }).data;
      expect(data.filters).toMatchObject({ similar_to: '/a.jpg', similarity_mode: 'color', min_similarity: 0.8 });
      await run('ui_set_gallery_filters', { patch: { semantic_query: 'x', semantic_threshold: 0.25 }, replace: true });
      data = ((await run('ui_get_gallery_view', {})) as { data: { filters: Record<string, unknown> } }).data;
      expect(data.filters).toMatchObject({ semantic_query: 'x', semantic_threshold: 0.25 });
      expect(data.filters).not.toHaveProperty('search_threshold');
      expect(data.filters).not.toHaveProperty('semantic_q');
    });
  });

  describe('replace on an album page', () => {
    it('leaves the album before applying, so no smart filter is saved for it', async () => {
      router.url = '/album/7';
      navigate.mockImplementationOnce(async () => {
        router.url = '/';
        store.galleryMounts.update(n => n + 1);
        return true;
      });
      const update = vi.spyOn(store, 'updateFilters');
      const result = await run('ui_set_gallery_filters', { patch: { camera: 'Canon' }, replace: true });
      expect(result.ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/']);
      expect(navigate.mock.invocationCallOrder[0]).toBeLessThan(update.mock.invocationCallOrder[0]);
      expect(TestBed.inject(AlbumService).update).not.toHaveBeenCalled();
    });

    it('leaves the album for a patch without replace too, and the edition tab then saves no album filter', async () => {
      edition = true;
      router.url = '/album/7';
      store.currentAlbum.set({ id: 7, is_smart: true } as unknown as Album);
      const albumUpdate = TestBed.inject(AlbumService).update as unknown as Mock;
      navigate.mockImplementationOnce(async () => {
        router.url = '/';
        store.currentAlbum.set(null);
        store.galleryMounts.update(n => n + 1);
        return true;
      });
      const result = await run('ui_set_gallery_filters', { patch: { camera: 'Canon' } });
      expect(result.ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/']);
      TestBed.tick();
      await new Promise(resolve => setTimeout(resolve, 700));
      TestBed.tick();
      expect(albumUpdate).not.toHaveBeenCalled();
    });
  });

  describe('ui_get_gallery_view', () => {
    it('returns filters, the visible rows and the selection count', async () => {
      await run('ui_set_gallery_filters', { patch: { min_aesthetic: '7', person: '3' } });
      const result = await run('ui_get_gallery_view', { limit: 2 });
      expect(result.ok).toBe(true);
      const data = (result as { data: Record<string, unknown> }).data;
      expect((data['photos'] as { path: string }[]).map(p => p.path)).toEqual(['/a.jpg', '/b.jpg']);
      expect(data['total']).toBe(120);
      expect(data['filters']).toMatchObject({ min_aesthetic: '7', person: '3' });
      expect(data['filters']).not.toHaveProperty('page');
      expect(data['route']).toBe('/');
    });

    it('reports the smart-album JSON of the view and whether a stored album can express it', async () => {
      await run('ui_set_gallery_filters', { patch: { min_aesthetic: '7', person: '3', category: 'macro', hide_bursts: true } });
      const data = ((await run('ui_get_gallery_view', {})) as { data: Record<string, unknown> }).data;
      const stored = JSON.parse(data['album_filter_json'] as string) as Record<string, unknown>;
      expect(stored).toMatchObject({ min_aesthetic: '7', person_id: '3', type: 'macro' });
      expect(stored).not.toHaveProperty('hide_bursts');
      expect(data['filters_scopable']).toBe(true);
      expect(data['loading']).toBe(false);
      await run('ui_set_gallery_filters', { patch: { semantic_query: 'sunset' } });
      const semantic = ((await run('ui_get_gallery_view', {})) as { data: Record<string, unknown> }).data;
      expect(semantic['filters_scopable']).toBe(false);
    });

    it('answers no_active_view away from the gallery', async () => {
      router.url = '/stats';
      expect(await run('ui_get_gallery_view', {})).toMatchObject({ ok: false, error: 'no_active_view' });
    });
  });

  describe('ui_open_photo', () => {
    it('navigates to /photo?path=', async () => {
      await run('ui_open_photo', { path: '/x/y.jpg' });
      expect(navigate).toHaveBeenCalledWith(['/photo'], { queryParams: { path: '/x/y.jpg' }, onSameUrlNavigation: 'reload' });
    });

    it('reports a refused navigation as navigation_refused, not not_found', async () => {
      navigate.mockResolvedValueOnce(false);
      expect(await run('ui_open_photo', { path: '/x/y.jpg' })).toMatchObject({ ok: false, error: 'navigation_refused' });
    });
  });

  describe('ui_show_photos', () => {
    const byPaths = (shown: string[], missing: string[]) => {
      const post = TestBed.inject(ApiService).post as unknown as Mock;
      post.mockImplementation(() => of({ photos: shown.map(path => makePhoto({ path })), total: shown.length, missing }));
      return post;
    };

    it('pins the list, reports what was missing, and leaves the filters alone', async () => {
      const post = byPaths(['/a.jpg', '/b.jpg', '/c.jpg'], ['/x.jpg', '/y.jpg']);
      const before = JSON.stringify(store.filters());
      const result = await run('ui_show_photos', { paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/x.jpg', '/y.jpg'] });
      expect(result).toMatchObject({ ok: true, data: { shown: 3, missing: ['/x.jpg', '/y.jpg'], total: 3 } });
      expect(post).toHaveBeenCalledWith('/photos/by_paths', { paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/x.jpg', '/y.jpg'] });
      expect(store.pinnedPaths()).toHaveLength(5);
      expect(JSON.stringify(store.filters())).toBe(before);
    });

    it('leaves an album page first, without saving a smart filter', async () => {
      byPaths(['/a.jpg'], []);
      router.url = '/album/3';
      navigate.mockImplementationOnce(async () => {
        router.url = '/';
        store.galleryMounts.update(n => n + 1);
        return true;
      });
      const result = await run('ui_show_photos', { paths: ['/a.jpg'] });
      expect(result.ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/']);
      expect(TestBed.inject(AlbumService).update).not.toHaveBeenCalled();
    });

    it('rejects an empty list and 201 paths before touching the gallery', async () => {
      const post = byPaths([], []);
      expect(await run('ui_show_photos', { paths: [] })).toMatchObject({ ok: false, error: 'invalid_input' });
      const tooMany = Array.from({ length: 201 }, (_, n) => `/p${n}.jpg`);
      expect(await run('ui_show_photos', { paths: tooMany })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(post).not.toHaveBeenCalled();
    });

    it('refuses selecting the whole view while the list is pinned', async () => {
      byPaths(['/a.jpg'], []);
      await run('ui_show_photos', { paths: ['/a.jpg'] });
      expect(await run('ui_select_photos', { select_view: true })).toMatchObject({ ok: false, error: 'invalid_input' });
    });

    it('pins exactly the requested paths and reports no annotation', async () => {
      byPaths(['/a.jpg', '/b.jpg'], []);
      const spy = vi.spyOn(store, 'showPaths');
      const result = await run('ui_show_photos', { paths: ['/a.jpg', '/b.jpg'] });
      expect(spy.mock.calls).toEqual([[['/a.jpg', '/b.jpg']]]);
      expect(result).toMatchObject({ ok: true, data: { shown: 2 } });
      expect((result as { data: object }).data).not.toHaveProperty('annotated');
    });

    it('ignores the removed annotation arguments instead of forwarding them to the store', async () => {
      byPaths(['/a.jpg', '/b.jpg'], []);
      const spy = vi.spyOn(store, 'showPaths');
      await direct()['ui_show_photos']({ paths: ['/a.jpg', '/b.jpg'], groups: [1, 1], marks: ['keep', 'remove'], kinds: ['burst', 'burst'] });
      expect(spy.mock.calls).toEqual([[['/a.jpg', '/b.jpg']]]);
    });

    it('is reported as pinned by ui_get_context', async () => {
      byPaths(['/a.jpg'], []);
      await run('ui_show_photos', { paths: ['/a.jpg'] });
      expect(await run('ui_get_context')).toMatchObject({ ok: true, data: { gallery: { pinned: true } } });
    });
  });

  describe('selection', () => {
    beforeEach(async () => {
      await store.loadPhotos();
    });

    it('requires exactly one of paths and select_view', async () => {
      expect(await run('ui_select_photos', {})).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_select_photos', { paths: [] })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_select_photos', { paths: ['/a.jpg'], select_view: true })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(store.selectionCount()).toBe(0);
    });

    it('rejects select_view with mode remove', async () => {
      expect(await run('ui_select_photos', { select_view: true, mode: 'remove' })).toMatchObject({ ok: false, error: 'invalid_input' });
    });

    it('replaces, adds and removes explicit paths', async () => {
      await run('ui_select_photos', { paths: ['/a.jpg', '/b.jpg'] });
      expect([...store.selectedPaths()]).toEqual(['/a.jpg', '/b.jpg']);
      await run('ui_select_photos', { paths: ['/c.jpg'], mode: 'add' });
      expect(store.selectionCount()).toBe(3);
      await run('ui_select_photos', { paths: ['/a.jpg'], mode: 'remove' });
      expect([...store.selectedPaths()].sort()).toEqual(['/b.jpg', '/c.jpg']);
    });

    it('selects the whole view in view scope, and remove then excludes paths', async () => {
      const result = await run('ui_select_photos', { select_view: true });
      expect(store.selectionScope()).toBe('view');
      expect(result).toMatchObject({ ok: true, data: { scope: 'view', count: 120 } });
      await run('ui_select_photos', { paths: ['/a.jpg'], mode: 'remove' });
      expect([...store.excludedPaths()]).toEqual(['/a.jpg']);
      const selection = await run('ui_get_selection');
      expect(selection).toMatchObject({ ok: true, data: { scope: 'view', count: 119, excluded_paths: ['/a.jpg'] } });
      expect((selection as { data: { filters: unknown } }).data.filters).toMatchObject({ hide_bursts: 'true' });
      await run('ui_select_photos', { paths: ['/a.jpg'], mode: 'add' });
      expect(store.excludedPaths().size).toBe(0);
    });

    it('remove under view scope ignores paths that are not in the view, so the count stays right', async () => {
      await run('ui_select_photos', { select_view: true });
      const result = await run('ui_select_photos', { paths: ['/zzz.jpg', '/a.jpg'], mode: 'remove' });
      expect([...store.excludedPaths()]).toEqual(['/a.jpg']);
      expect(store.selectionCount()).toBe(119);
      expect(result).toMatchObject({ ok: true, data: { count: 119, not_in_view: ['/zzz.jpg'] } });
    });

    it('refuses select_view when the view cannot be a filter', async () => {
      store.filters.update(f => ({ ...f, semanticQuery: 'sunset' }));
      expect(await run('ui_select_photos', { select_view: true })).toMatchObject({ ok: false, error: 'invalid_input' });
    });

    it('clears the selection', async () => {
      await run('ui_select_photos', { select_view: true });
      await run('ui_clear_selection');
      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(0);
    });
  });

  describe('selection snapshot bounds', () => {
    beforeEach(async () => {
      await store.loadPhotos();
    });

    it('reports the page the selection is read from, for both scopes', async () => {
      const paths = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(typeof paths['route']).toBe('string');
      await run('ui_select_photos', { select_view: true });
      const view = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(view['route']).toBe(paths['route']);
    });

    it('flags 1001 exclusions and reports the real count', async () => {
      await run('ui_select_photos', { select_view: true });
      store.excludedPaths.set(new Set(Array.from({ length: 1001 }, (_, i) => `/x${i}.jpg`)));
      const data = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(data['excluded_count']).toBe(1001);
      expect(data['excluded_truncated']).toBe(true);
      expect((data['excluded_paths'] as string[]).length).toBe(1000);
    });

    it('does not flag a view selection whose exclusions all fit', async () => {
      await run('ui_select_photos', { select_view: true });
      store.excludedPaths.set(new Set(['/x.jpg']));
      const data = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(data).toMatchObject({ excluded_count: 1, excluded_truncated: false });
    });

    it('measures paths as JSON-escaped encoded bytes, so escapes cannot overflow the frame', async () => {
      const paths = Array.from({ length: 300 }, (_, i) => `/${'"'.repeat(3000)}/${i}.jpg`);
      store.restoreSelection(paths);
      const data = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(data['truncated']).toBe(true);
      expect(new TextEncoder().encode(JSON.stringify(data)).length).toBeLessThan(200 * 1024);
    });

    it('cuts 3000 long paths to a 200 KB frame and marks the selection truncated', async () => {
      const paths = Array.from({ length: 3000 }, (_, i) => `/${'d'.repeat(3000)}/${i}.jpg`);
      store.restoreSelection(paths);
      const data = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(data['truncated']).toBe(true);
      expect(data['count']).toBe(3000);
      expect(JSON.stringify(data).length).toBeLessThan(200 * 1024);
      expect((data['paths'] as string[]).length).toBeLessThan(1000);
    });
  });

  describe('ui_get_context', () => {
    const context = async (): Promise<Record<string, unknown>> =>
      ((await run('ui_get_context')) as { data: Record<string, unknown> }).data;
    const jobIds = (data: Record<string, unknown>): string[] => (data['actions'] as { id: string }[]).map(a => a.id);

    describe('culling_defaults', () => {
      it('reports the stored profile and the page default strictness', async () => {
        localStorage.setItem(CULL_PROFILE_KEY, 'sports');
        localStorage.setItem(CULL_STRICTNESS_KEY, '35');
        expect((await context())['culling_defaults']).toEqual({ profile: 'sports', strictness: 35 });
      });

      it('reports a null strictness for a stored profile with no stored slider value, so the preset applies', async () => {
        localStorage.setItem(CULL_PROFILE_KEY, 'wedding');
        expect((await context())['culling_defaults']).toEqual({ profile: 'wedding', strictness: null });
      });

      it('reports a null strictness for a stored profile whose stored slider value is invalid', async () => {
        localStorage.setItem(CULL_PROFILE_KEY, 'wedding');
        localStorage.setItem(CULL_STRICTNESS_KEY, '150');
        expect((await context())['culling_defaults']).toEqual({ profile: 'wedding', strictness: null });
      });

      it('reports a null profile when none is stored', async () => {
        expect((await context())['culling_defaults']).toEqual({ profile: null, strictness: 100 });
      });

      it('reports the slider\'s stored strictness, read live on every call', async () => {
        localStorage.setItem(CULL_STRICTNESS_KEY, '35');
        expect((await context())['culling_defaults']).toEqual({ profile: null, strictness: 35 });
        localStorage.setItem(CULL_STRICTNESS_KEY, '70');
        expect((await context())['culling_defaults']).toEqual({ profile: null, strictness: 70 });
      });

      it('falls back to the default for a stored value that is not 0..100', async () => {
        localStorage.setItem(CULL_STRICTNESS_KEY, '150');
        expect((await context())['culling_defaults']).toEqual({ profile: null, strictness: CULL_DEFAULT_STRICTNESS });
      });
    });

    describe('user_activity', () => {
      /** Straight to the handler: the generated contract does not list `activity_since` until the server side merges. */
      const activity = async (since?: number): Promise<{ items: { kind: string; seq: number }[]; until: number; truncated: boolean }> =>
        (await createUiToolHandlers({
          gallery: store, router: router as unknown as Router, auth: TestBed.inject(AuthService), viewActions, actions: () => [],
          compareFilters: TestBed.inject(CompareFiltersService),
          journal: TestBed.inject(UserActivityJournal),
          plan: TestBed.inject(AssistantCullPlanService),
          pageContext: TestBed.inject(PageContextService),
          fetchAlbum,
        })['ui_get_context'](since === undefined ? {} : { activity_since: since }) as
          { user_activity: { items: { kind: string; seq: number }[]; until: number; truncated: boolean } }).user_activity;

      it('reads activity_since through the registry: the contract accepts it, and culling is null outside plan mode', async () => {
        await store.loadPhotos();
        await store.setRating('/a.jpg', 4);
        const first = ((await run('ui_get_context')) as { data: { user_activity: { until: number; items: unknown[] }; culling: unknown; review?: unknown } }).data;
        expect(first.user_activity.items).toHaveLength(1);
        const since = (await run('ui_get_context', { activity_since: first.user_activity.until })) as { ok: boolean; data: { user_activity: { items: unknown[]; until: number } } };
        expect(since.ok).toBe(true);
        expect(since.data.user_activity.items).toEqual([]);
        expect(since.data.user_activity.until).toBe(first.user_activity.until);
        expect(first.culling).toBeNull();
        expect(first).not.toHaveProperty('review');
        expect(await run('ui_get_context', { activity_since: -1 })).toMatchObject({ ok: false, error: 'invalid_input' });
        expect(await run('ui_get_context', { activity_since: 'x' })).toMatchObject({ ok: false, error: 'invalid_input' });
      });

      it('lists a rating made through the store, and a second call without the argument returns the same', async () => {
        await store.loadPhotos();
        await store.setRating('/a.jpg', 4);
        const first = await activity();
        expect(first.items.map(i => i.kind)).toEqual(['rating']);
        expect(await activity()).toEqual(first);
        expect((await activity(first.until)).items).toEqual([]);
      });

      it('keeps the newest 50 of 60 actions and flags the cut', async () => {
        await store.loadPhotos();
        for (let i = 0; i < 60; i++) await store.setRating('/a.jpg', (i % 5) + 1);
        const report = await activity();
        expect(report.items).toHaveLength(50);
        expect(report.truncated).toBe(true);
        expect(report.until).toBe(60);
      });

      it('does not list an assistant change batch', async () => {
        await store.loadPhotos();
        assistantBatches.next({ paths: ['/a.jpg'] });
        await Promise.resolve();
        expect((await activity()).items).toEqual([]);
      });

      it('lists a route change as navigate', async () => {
        const { NavigationEnd } = await import('@angular/router');
        routerEvents.next(new NavigationEnd(1, '/stats', '/stats'));
        expect((await activity()).items.map(i => i.kind)).toEqual(['navigate']);
      });

      it('adds nothing for an agent ui_show_photos or ui_navigate run through the registry', async () => {
        const { NavigationEnd } = await import('@angular/router');
        navigate.mockImplementationOnce(async () => {
          routerEvents.next(new NavigationEnd(2, '/stats', '/stats'));
          return true;
        });
        expect((await run('ui_navigate', { route: '/stats' })).ok).toBe(true);
        const post = TestBed.inject(ApiService).post as unknown as Mock;
        post.mockImplementation(() => of({ photos: [makePhoto({ path: '/a.jpg' })], total: 1, missing: [] }));
        expect((await run('ui_show_photos', { paths: ['/a.jpg'] })).ok).toBe(true);
        expect((await activity()).items).toEqual([]);
      });
    });

    describe('focused', () => {
      const focused = async (): Promise<unknown> => (await context())['focused'];

      it('is null on the gallery with no cursor, then the cursor photo', async () => {
        await store.loadPhotos();
        expect(await focused()).toBeNull();
        store.focusedPath.set('/b.jpg');
        expect(await focused()).toEqual({ path: '/b.jpg' });
      });

      it('is the query path on /photo', async () => {
        router.url = '/photo?path=x.jpg';
        expect(await focused()).toEqual({ path: 'x.jpg' });
      });

      it('is the lightbox photo in the darkroom', async () => {
        router.url = '/culling';
        TestBed.inject(UserActivityJournal).darkroomFocus.set('/c.jpg');
        expect(await focused()).toEqual({ path: '/c.jpg' });
      });

      it('is null on any other route', async () => {
        store.focusedPath.set('/b.jpg');
        router.url = '/stats';
        expect(await focused()).toBeNull();
      });
    });

    describe('page and overlays', () => {
      let pageContext: PageContextService;
      beforeEach(() => {
        pageContext = TestBed.inject(PageContextService);
      });

      it('is null on a page that registers nothing, with no overlays', async () => {
        router.url = '/';
        const data = await context();
        expect(data['page']).toBeNull();
        expect(data['overlays']).toEqual([]);
      });

      it('reports the registered page, live, and null again once it is removed', async () => {
        router.url = '/persons';
        let search = 'ann';
        const unregister = pageContext.register('persons', () => ({ search, sort: 'count' }));
        expect((await context())['page']).toEqual({ id: 'persons', search: 'ann', sort: 'count' });
        search = 'bob';
        expect(((await context())['page'] as Record<string, unknown>)['search']).toBe('bob');
        unregister();
        expect((await context())['page']).toBeNull();
      });

      it('cuts a long search to 200 characters but returns a 4096-character compare path whole', async () => {
        router.url = '/compare';
        pageContext.register('compare', () => ({ search: 'x'.repeat(500), pair_a: 'p'.repeat(4096), tab: null }));
        const page = (await context())['page'] as Record<string, unknown>;
        expect((page['search'] as string).length).toBe(200);
        expect((page['pair_a'] as string).length).toBe(4096);
        expect(page['tab']).toBeNull();
      });

      it('lists an open dialog and ignores the connect-assistant dialog alone', async () => {
        openDialogs.push({ id: CONNECT_ASSISTANT_DIALOG_ID });
        expect((await context())['overlays']).toEqual([]);
        openDialogs.push({ componentInstance: {} });
        expect((await context())['overlays']).toEqual(['dialog']);
      });
    });

    it('reports the open photo of the detail route', async () => {
      router.url = '/photo?path=a.jpg';
      expect(await context()).toMatchObject({ route: '/photo', query_path: 'a.jpg', gallery: null });
    });

    it('reports the album id on an album page', async () => {
      router.url = '/album/7';
      expect(await context()).toMatchObject({ route: '/album/7', album_id: 7, gallery: { pinned: false } });
    });

    it('answers off the gallery with gallery null instead of throwing', async () => {
      router.url = '/stats';
      const data = await context();
      expect(data['gallery']).toBeNull();
      expect(data['selection']).toEqual({ scope: 'paths', count: 0 });
    });

    it('reports scope and count of a view selection and nothing else about it', async () => {
      await store.loadPhotos();
      await run('ui_select_photos', { select_view: true });
      const data = await context();
      expect(data['selection']).toEqual({ scope: 'view', count: 120 });
      expect(data['gallery']).toMatchObject({ total: 120, loaded: 3, has_more: false, pinned: false });
    });

    it('lists the registered page actions by name', async () => {
      const off = viewActions.register('ui_show_culling_group', async () => ({}));
      expect((await context())['mounted_actions']).toEqual(['ui_show_culling_group']);
      off();
      expect((await context())['mounted_actions']).toEqual([]);
    });

    it('lists the jobs that apply to the gallery and drops the tools above the session level', async () => {
      const data = await context();
      expect(data['level']).toBe('readonly');
      const ids = jobIds(data);
      expect(ids).toContain('steer_gallery');
      expect(ids).not.toContain('work_darkroom');
      expect(ids).not.toContain('edit_many');
      const rate = (data['actions'] as { id: string; tools: string[] }[]).find(a => a.id === 'rate_photos');
      expect(rate).toBeUndefined();
    });

    it('lists the editing jobs for an edition session once photos are selected', async () => {
      edition = true;
      await store.loadPhotos();
      store.restoreSelection(['/a.jpg']);
      const data = await context();
      expect(data['level']).toBe('edition');
      const edit = (data['actions'] as { id: string; tools: string[] }[]).find(a => a.id === 'edit_many');
      expect(edit?.tools).toContain('batch_set_rating');
      expect(jobIds(data)).toContain('cull_or_delete');
    });

    it('reports the user level of a signed-in multi-user session', async () => {
      multiUser = true;
      const data = await context();
      expect(data['level']).toBe('user');
      const rate = (data['actions'] as { id: string; tools: string[] }[]).find(a => a.id === 'rate_photos');
      expect(rate?.tools).toEqual(['set_rating', 'set_favorite', 'set_rejected']);
    });

    it('lists the darkroom job on /culling and not the selection jobs', async () => {
      edition = true;
      router.url = '/culling';
      const ids = jobIds(await context());
      expect(ids).toContain('work_darkroom');
      expect(ids).not.toContain('edit_many');
    });

    it('carries exactly the jobs of the generated table for the same facts', async () => {
      edition = true;
      router.url = '/stats';
      const rows = (contractFile as unknown as UiToolContractFile).actions;
      const expected = rows.filter(row => row.when.includes('any')).map(row => row.id);
      expect(jobIds(await context())).toEqual(expected);
    });
  });

  describe('ui_next_page', () => {
    it('loads the next page', async () => {
      apiGet.mockReturnValue(of(photosResponse(['/a.jpg'], true)));
      await store.loadPhotos();
      apiGet.mockReturnValue(of(photosResponse(['/d.jpg'], false)));
      const result = await run('ui_next_page');
      expect(result).toMatchObject({ ok: true, data: { added: 1, loaded: 2, has_more: false } });
    });

    it('answers no_active_view away from the gallery', async () => {
      router.url = '/albums';
      expect(await run('ui_next_page')).toMatchObject({ ok: false, error: 'no_active_view' });
    });
  });

  describe('ui_show_culling_group', () => {
    it('is refused for a non-edition session', async () => {
      expect(await run('ui_show_culling_group', { type: 'burst', group_id: 1 })).toMatchObject({ ok: false, error: 'forbidden_level' });
    });

    it('calls the registered darkroom action with the group identity', async () => {
      edition = true;
      const action = vi.fn(async () => ({ shown: true }));
      const unregister = viewActions.register('ui_show_culling_group', action);
      const result = await run('ui_show_culling_group', { type: 'scene', group_id: 4 });
      expect(result).toEqual({ ok: true, data: { shown: true } });
      expect(action).toHaveBeenCalledWith({ type: 'scene', group_id: 4 });
      expect(navigate).not.toHaveBeenCalled();
      unregister();
      expect(viewActions.get('ui_show_culling_group')).toBeUndefined();
    });

    it('answers no_active_view when the darkroom never registers', async () => {
      edition = true;
      vi.useFakeTimers();
      try {
        const pending = run('ui_show_culling_group', { type: 'burst', group_id: 1 });
        await vi.advanceTimersByTimeAsync(11_000);
        expect(await pending).toMatchObject({ ok: false, error: 'no_active_view' });
        expect(navigate).toHaveBeenCalledWith(['/culling']);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('ui_show_culling_plan', () => {
    const REQUEST = { group_by: 'burst' as const, strictness: 40 };
    const entry = (number: number, id: number, paths: string[], keep: string[]): CullPlanEntryInput => ({
      key: `${id}_burst`, type: 'burst', group_id: id, number, paths, keep_paths: keep,
    });
    let plan: AssistantCullPlanService;

    /** Stand in for the darkroom: once /culling is requested it registers its action and loads the plan the pin names. */
    const darkroomLoads = (outcome: 'landed' | 'stale'): void => {
      navigate.mockImplementation(async (commands: string[]) => {
        router.url = commands[0];
        viewActions.register('ui_show_culling_group', async () => ({}));
        const pin = plan.pin();
        if (pin && outcome === 'landed') plan.register([entry(1, 5, ['/a.jpg', '/b.jpg'], ['/a.jpg'])], { total: 3, truncated: false });
        if (pin && outcome === 'stale') plan.clear();
        return true;
      });
    };

    beforeEach(() => {
      edition = true;
      plan = TestBed.inject(AssistantCullPlanService);
    });

    it('is refused for a non-edition session and pins nothing', async () => {
      edition = false;
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST })).toMatchObject({ ok: false, error: 'forbidden_level' });
      expect(plan.pin()).toBeNull();
      expect(navigate).not.toHaveBeenCalled();
    });

    it('pins the digest and the request, opens /culling and answers once the plan loaded', async () => {
      darkroomLoads('landed');
      const result = await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST });
      expect(result).toEqual({ ok: true, data: { route: '/culling', plan_digest: 'd1', groups_total: 3 } });
      expect(navigate).toHaveBeenCalledWith(['/culling']);
      expect(plan.pin()).toEqual({ digest: 'd1', request: REQUEST, focusNumber: undefined });
    });

    it('carries the requested focus on the new pin', async () => {
      darkroomLoads('landed');
      await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST, focus: 4 });
      expect(plan.pin()?.focusNumber).toBe(4);
    });

    it('with the same digest only moves the focus: no navigation, no new pin, the read model survives', async () => {
      darkroomLoads('landed');
      await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST });
      navigate.mockClear();
      const setPin = vi.spyOn(plan, 'setPin');
      const result = await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST, focus: 3 });
      expect(result).toMatchObject({ ok: true, data: { plan_digest: 'd1', groups_total: 3 } });
      expect(plan.pin()?.focusNumber).toBe(3);
      expect(setPin).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
      expect(plan.snapshot()).not.toBeNull();
    });

    it('refuses a different digest while the darkroom holds manual decisions', async () => {
      router.url = '/culling';
      viewActions.register('ui_show_culling_group', async () => ({}));
      plan.registerDecisionsProbe(() => true);
      const result = await run('ui_show_culling_plan', { plan_digest: 'd2', request: REQUEST });
      expect(result).toMatchObject({ ok: false, error: 'unsaved_decisions' });
      expect(plan.pin()).toBeNull();
    });

    it('refuses a different digest while an unconfirmed plan group is flipped, but not once it is confirmed', async () => {
      router.url = '/culling';
      viewActions.register('ui_show_culling_group', async () => ({}));
      plan.registerDecisionsProbe(() => false);
      plan.setPin({ digest: 'd1', request: REQUEST });
      plan.register([entry(1, 5, ['/a.jpg', '/b.jpg'], ['/a.jpg'])], { total: 1, truncated: false });
      plan.recordSelection('5_burst', ['/b.jpg']);
      expect(await run('ui_show_culling_plan', { plan_digest: 'd2', request: REQUEST })).toMatchObject({ ok: false, error: 'unsaved_decisions' });
      expect(plan.pin()?.digest).toBe('d1');
      plan.recordConfirm('5_burst', ['/b.jpg']);
      // The mounted darkroom follows the new pin on its own and registers the plan it loaded.
      const setPin = plan.setPin.bind(plan);
      vi.spyOn(plan, 'setPin').mockImplementation(pin => {
        setPin(pin);
        plan.register([entry(1, 6, ['/c.jpg', '/d.jpg'], ['/c.jpg'])], { total: 2, truncated: false });
      });
      expect(await run('ui_show_culling_plan', { plan_digest: 'd2', request: REQUEST })).toMatchObject({ ok: true });
      expect(plan.pin()?.digest).toBe('d2');
    });

    it('does not count decisions of a darkroom that is no longer mounted', async () => {
      darkroomLoads('landed');
      const unregister = plan.registerDecisionsProbe(() => true);
      unregister();
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST })).toMatchObject({ ok: true });
    });

    it('maps a plan the store dropped (412) to plan_changed', async () => {
      darkroomLoads('stale');
      const result = await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST });
      expect(result).toMatchObject({ ok: false, error: 'plan_changed' });
      expect(plan.pin()).toBeNull();
    });

    it('maps a failed plan load that is not a 412 to plan_load_failed', async () => {
      navigate.mockImplementation(async (commands: string[]) => {
        router.url = commands[0];
        viewActions.register('ui_show_culling_group', async () => ({}));
        plan.recordLoadFailure('d1', 'failed');
        plan.clear();
        return true;
      });
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST })).toMatchObject({ ok: false, error: 'plan_load_failed' });
    });

    it('maps a recorded 412 to plan_changed', async () => {
      navigate.mockImplementation(async (commands: string[]) => {
        router.url = commands[0];
        viewActions.register('ui_show_culling_group', async () => ({}));
        plan.recordLoadFailure('d1', 'out_of_date');
        plan.clear();
        return true;
      });
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST })).toMatchObject({ ok: false, error: 'plan_changed' });
    });

    it('caps a large culling block in ui_get_context under the bridge frame limit, keeping true counts', async () => {
      plan.setPin({ digest: 'd1', request: REQUEST });
      const groups = Array.from({ length: 5 }, (_, i) => {
        const paths = Array.from({ length: 1000 }, (_, j) => `/library/2026/some/long/folder/name/photo_${i}_${j}.jpg`);
        return entry(i + 1, i + 1, paths, [paths[0]]);
      });
      plan.register(groups, { total: 5, truncated: false });
      for (const g of groups) plan.recordSelection(g.key, [g.paths[1]]);
      const data = ((await run('ui_get_context')) as { data: Record<string, unknown> }).data;
      const culling = data['culling'] as Record<string, unknown>;
      expect(new TextEncoder().encode(JSON.stringify(data)).length).toBeLessThan(250 * 1024);
      expect(culling['truncated']).toBe(true);
      expect(culling['changed_count']).toBe(5);
      expect(culling['pending_count']).toBe(5);
      expect(culling['confirmed_count']).toBe(0);
      expect((culling['changed'] as unknown[]).length).toBeLessThan(5);
      expect(culling['groups_total']).toBe(5);
      expect(culling['plan_truncated']).toBe(false);
      expect(culling['scope']).toEqual({ album_id: null, date_from: null, date_to: null });
    });

    it('reports the plan\'s dates in ui_get_context after a date re-plan moved the pin', async () => {
      plan.setPin({ digest: 'd1', request: REQUEST });
      plan.register([entry(1, 5, ['/a.jpg', '/b.jpg'], ['/a.jpg'])], { total: 1, truncated: false });
      plan.setPin({ digest: 'd2', request: { ...REQUEST, date_from: '2026-07-01', date_to: '2026-07-31' } });
      plan.register([entry(1, 5, ['/a.jpg', '/b.jpg'], ['/a.jpg'])], { total: 1, truncated: false });
      const culling = ((await run('ui_get_context')) as { data: Record<string, unknown> }).data['culling'] as Record<string, unknown>;
      expect(culling['scope']).toEqual({ album_id: null, date_from: '2026-07-01', date_to: '2026-07-31' });
    });

    it('leaves a small culling block untouched: no counts, no truncated', async () => {
      plan.setPin({ digest: 'd1', request: REQUEST });
      plan.register([entry(1, 5, ['/a.jpg', '/b.jpg'], ['/a.jpg'])], { total: 1, truncated: false });
      const culling = (((await run('ui_get_context')) as { data: Record<string, unknown> }).data['culling']) as Record<string, unknown>;
      expect(culling).not.toHaveProperty('truncated');
      expect(culling).not.toHaveProperty('changed_count');
    });

    it('drops the pin when the tab refuses to open /culling', async () => {
      navigate.mockResolvedValue(false);
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST })).toMatchObject({ ok: false, error: 'navigation_refused' });
      expect(plan.pin()).toBeNull();
    });

    it('rejects a call without the digest or with a focus below 1 before touching anything', async () => {
      expect(await run('ui_show_culling_plan', { request: REQUEST })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST, focus: 0 })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(plan.pin()).toBeNull();
    });

    it('reports culling from the plan service in ui_get_context, with the changed groups carrying their paths', async () => {
      expect(((await run('ui_get_context')) as { data: Record<string, unknown> }).data['culling']).toBeNull();
      plan.setPin({ digest: 'd1', request: REQUEST });
      plan.register([entry(1, 5, ['/a.jpg', '/b.jpg'], ['/a.jpg'])], { total: 1, truncated: false });
      plan.recordSelection('5_burst', ['/b.jpg']);
      const data = ((await run('ui_get_context')) as { data: Record<string, unknown> }).data;
      expect(data).not.toHaveProperty('review');
      expect(data['culling']).toEqual({
        plan_digest: 'd1', groups_total: 1, confirmed: [], pending: [1], untouched: 0, plan_truncated: false,
        scope: { album_id: null, date_from: null, date_to: null },
        suggestions_total: 0, suggestions_accepted: 0, suggestions_open: [],
        changed: [{ type: 'burst', group_id: 5, number: 1, keep_paths: ['/b.jpg'], reject_paths: ['/a.jpg'] }],
      });
    });
  });

  describe('leaving /culling with unsaved decisions', () => {
    const REQUEST = { group_by: 'burst' as const, strictness: 40 };
    const entry = (): CullPlanEntryInput => ({
      key: '5_burst', type: 'burst', group_id: 5, number: 1, paths: ['/a.jpg', '/b.jpg'], keep_paths: ['/a.jpg'],
    });
    let plan: AssistantCullPlanService;

    beforeEach(() => {
      edition = true;
      plan = TestBed.inject(AssistantCullPlanService);
      router.url = '/culling';
    });

    const leaving: [string, () => Promise<UiToolEnvelope>][] = [
      ['ui_navigate', () => run('ui_navigate', { route: '/stats' })],
      ['ui_open_photo', () => run('ui_open_photo', { path: '/x/y.jpg' })],
      ['ui_show_photos', () => run('ui_show_photos', { paths: ['/a.jpg'] })],
      ['ui_set_gallery_filters', () => run('ui_set_gallery_filters', { patch: { min_score: 7 } })],
    ];

    for (const [name, call] of leaving) {
      it(`${name} is refused with unsaved_decisions and never navigates`, async () => {
        plan.registerDecisionsProbe(() => true);
        expect(await call()).toMatchObject({ ok: false, error: 'unsaved_decisions' });
        expect(navigate).not.toHaveBeenCalled();
      });
    }

    it('ui_show_comparison is refused first and leaves the compare filters untouched', async () => {
      plan.registerDecisionsProbe(() => true);
      const filters = TestBed.inject(CompareFiltersService);
      expect(await run('ui_show_comparison', { category: 'portrait', strategy: 'boundary' })).toMatchObject({ ok: false, error: 'unsaved_decisions' });
      expect(navigate).not.toHaveBeenCalled();
      expect(filters.selectedCategory()).toBe('');
      expect(filters.strategy()).toBe('');
      expect(filters.activeTab()).toBe(0);
    });

    it('an unconfirmed flipped plan group also blocks leaving, until it is confirmed', async () => {
      plan.registerDecisionsProbe(() => false);
      plan.setPin({ digest: 'd1', request: REQUEST });
      plan.register([entry()], { total: 1, truncated: false });
      plan.recordSelection('5_burst', ['/b.jpg']);
      expect(await run('ui_navigate', { route: '/stats' })).toMatchObject({ ok: false, error: 'unsaved_decisions' });
      expect(navigate).not.toHaveBeenCalled();
      plan.recordConfirm('5_burst', ['/b.jpg']);
      expect((await run('ui_navigate', { route: '/stats' })).ok).toBe(true);
      expect(navigate).toHaveBeenCalledTimes(1);
    });

    it('does not block a navigation that stays on /culling', async () => {
      plan.registerDecisionsProbe(() => true);
      expect((await run('ui_navigate', { route: '/culling' })).ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/culling'], expect.anything());
    });

    it('does not block ui_show_culling_group', async () => {
      plan.registerDecisionsProbe(() => true);
      viewActions.register('ui_show_culling_group', async () => ({ shown: true }));
      expect(await run('ui_show_culling_group', { type: 'burst', group_id: 5 })).toEqual({ ok: true, data: { shown: true } });
    });

    it('does not block ui_show_culling_plan for the held digest', async () => {
      plan.registerDecisionsProbe(() => true);
      viewActions.register('ui_show_culling_group', async () => ({}));
      plan.setPin({ digest: 'd1', request: REQUEST });
      plan.register([entry()], { total: 1, truncated: false });
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST })).toMatchObject({ ok: true });
    });

    it('navigates normally when no probe is registered', async () => {
      expect((await run('ui_navigate', { route: '/stats' })).ok).toBe(true);
    });

    it('navigates normally when the probe reports nothing to lose', async () => {
      plan.registerDecisionsProbe(() => false);
      expect((await run('ui_open_photo', { path: '/x/y.jpg' })).ok).toBe(true);
    });

    it('navigates normally from another page even if a probe is still registered', async () => {
      plan.registerDecisionsProbe(() => true);
      router.url = '/stats';
      expect((await run('ui_open_photo', { path: '/x/y.jpg' })).ok).toBe(true);
    });
  });

  describe('navigation_refused', () => {
    beforeEach(() => { edition = true; });

    it('is reported when the gallery cannot be opened', async () => {
      router.url = '/stats';
      navigate.mockResolvedValueOnce(false);
      expect(await run('ui_show_photos', { paths: ['/a.jpg'] })).toMatchObject({ ok: false, error: 'navigation_refused' });
    });

    it('is reported when an album page cannot be left', async () => {
      router.url = '/album/3';
      navigate.mockResolvedValueOnce(false);
      expect(await run('ui_set_gallery_filters', { patch: { min_score: 7 } })).toMatchObject({ ok: false, error: 'navigation_refused' });
    });

    it('is reported by ui_show_culling_group when coming from another page', async () => {
      router.url = '/stats';
      navigate.mockResolvedValueOnce(false);
      expect(await run('ui_show_culling_group', { type: 'burst', group_id: 1 })).toMatchObject({ ok: false, error: 'navigation_refused' });
    });

    it('is reported by ui_show_culling_plan from another page, and the pin is dropped', async () => {
      const plan = TestBed.inject(AssistantCullPlanService);
      router.url = '/stats';
      navigate.mockResolvedValueOnce(false);
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: { group_by: 'burst', strictness: 40 } }))
        .toMatchObject({ ok: false, error: 'navigation_refused' });
      expect(plan.pin()).toBeNull();
    });

    it('ui_show_culling_group treats a false from /culling as a same-URL skip, not a refusal', async () => {
      router.url = '/culling';
      navigate.mockResolvedValue(false);
      vi.useFakeTimers();
      try {
        const pending = run('ui_show_culling_group', { type: 'burst', group_id: 1 });
        await vi.advanceTimersByTimeAsync(11_000);
        expect(await pending).toMatchObject({ ok: false, error: 'no_active_view' });
      } finally {
        vi.useRealTimers();
      }
    });

    it('ui_show_culling_plan treats a false from /culling as a same-URL skip: no refusal, the pin survives', async () => {
      const plan = TestBed.inject(AssistantCullPlanService);
      router.url = '/culling';
      navigate.mockResolvedValue(false);
      const setPin = plan.setPin.bind(plan);
      vi.spyOn(plan, 'setPin').mockImplementation(pin => {
        setPin(pin);
        plan.register([{ key: '5_burst', type: 'burst', group_id: 5, number: 1, paths: ['/a.jpg', '/b.jpg'], keep_paths: ['/a.jpg'] }], { total: 1, truncated: false });
      });
      const result = await run('ui_show_culling_plan', { plan_digest: 'd1', request: { group_by: 'burst', strictness: 40 } });
      expect(result).toMatchObject({ ok: true });
      expect(plan.pin()?.digest).toBe('d1');
    });
  });

  describe('ui_suggest_culling', () => {
    const REQUEST = { group_by: 'burst' as const, strictness: 40 };
    const entry = (number: number, id: number, paths: string[], keep: string[]): CullPlanEntryInput => ({
      key: `${id}_burst`, type: 'burst', group_id: id, number, paths, keep_paths: keep,
    });
    const reject = (path: string, reason = 'soft') => ({ path, action: 'reject', reason });
    let plan: AssistantCullPlanService;

    const loadPlan = (): void => {
      plan.setPin({ digest: 'd1', request: REQUEST });
      plan.register([entry(1, 5, ['/a.jpg', '/b.jpg'], ['/a.jpg']), entry(2, 6, ['/c.jpg', '/d.jpg'], ['/c.jpg'])], { total: 2, truncated: false });
    };

    beforeEach(() => {
      edition = true;
      plan = TestBed.inject(AssistantCullPlanService);
    });

    it('is refused for a non-edition session', async () => {
      edition = false;
      loadPlan();
      expect(await run('ui_suggest_culling', { photos: [reject('/a.jpg')] })).toMatchObject({ ok: false, error: 'forbidden_level' });
      expect(plan.suggestions().photos.size).toBe(0);
    });

    it('answers no_plan when the tab holds no plan', async () => {
      expect(await run('ui_suggest_culling', { photos: [reject('/a.jpg')] })).toMatchObject({ ok: false, error: 'no_plan' });
    });

    it('stores what differs, answers the counts and lists, and never touches the plan or its digest', async () => {
      loadPlan();
      const before = plan.snapshot();
      const result = await run('ui_suggest_culling', {
        photos: [reject('/a.jpg'), reject('/b.jpg'), reject('/zzz.jpg')], groups: [{ path: '/c.jpg', note: 'tight' }],
      });
      expect(result).toEqual({ ok: true, data: {
        plan_digest: 'd1', applied: ['/a.jpg'], redundant: ['/b.jpg'], closed: [], missing: ['/zzz.jpg'],
        groups_applied: ['/c.jpg'], groups_missing: [], groups_closed: [], suggestions_total: 1, notes_total: 1,
      } });
      expect(plan.pin()?.digest).toBe('d1');
      expect(plan.snapshot()).toMatchObject({ ...before, suggestions_total: 1, suggestions_open: [{ path: '/a.jpg', action: 'reject' }] });
    });

    it('merges a second call, and replace with nothing clears', async () => {
      loadPlan();
      await run('ui_suggest_culling', { photos: [reject('/a.jpg')] });
      await run('ui_suggest_culling', { photos: [reject('/c.jpg')] });
      expect([...plan.suggestions().photos.keys()]).toEqual(['/a.jpg', '/c.jpg']);
      await run('ui_suggest_culling', { photos: [reject('/d.jpg')], replace: true });
      expect([...plan.suggestions().photos.keys()]).toEqual([]);
      await run('ui_suggest_culling', { photos: [reject('/a.jpg')] });
      expect(await run('ui_suggest_culling', { replace: true })).toMatchObject({ ok: true, data: { suggestions_total: 0, notes_total: 0 } });
      expect(plan.suggestions().photos.size).toBe(0);
    });

    it('refuses an over-cap merge as too_large, naming the suggestion cap, and applies nothing', async () => {
      plan.setPin({ digest: 'd1', request: REQUEST });
      const paths = Array.from({ length: 301 }, (_, i) => `/p${i}.jpg`);
      plan.register([entry(1, 5, paths, [])], { total: 1, truncated: false });
      const keep = (p: string) => ({ path: p, action: 'keep', reason: 'ok' });
      for (let i = 0; i < 3; i++) {
        expect(await run('ui_suggest_culling', { photos: paths.slice(i * 100, i * 100 + 100).map(keep) })).toMatchObject({ ok: true });
      }
      const result = await run('ui_suggest_culling', { photos: [keep('/p300.jpg')] });
      expect(result).toMatchObject({ ok: false, error: 'too_large' });
      expect((result as { message: string }).message).toContain('300');
      expect(plan.suggestions().photos.size).toBe(300);
    });

    it('is cleared by showing a different plan, kept by the same digest, and kept by a refused show', async () => {
      loadPlan();
      await run('ui_suggest_culling', { photos: [reject('/a.jpg')] });
      router.url = '/culling';
      viewActions.register('ui_show_culling_group', async () => ({}));
      expect(await run('ui_show_culling_plan', { plan_digest: 'd1', request: REQUEST, focus: 2 })).toMatchObject({ ok: true });
      expect(plan.suggestions().photos.size).toBe(1);
      plan.registerDecisionsProbe(() => false);
      plan.recordSelection('5_burst', ['/b.jpg']);
      expect(await run('ui_show_culling_plan', { plan_digest: 'd2', request: REQUEST })).toMatchObject({ ok: false, error: 'unsaved_decisions' });
      expect(plan.suggestions().photos.size).toBe(1);
      plan.recordSelection('5_burst', ['/a.jpg']);
      const setPin = plan.setPin.bind(plan);
      vi.spyOn(plan, 'setPin').mockImplementation(pin => {
        setPin(pin);
        plan.register([entry(1, 7, ['/e.jpg', '/f.jpg'], ['/e.jpg'])], { total: 1, truncated: false });
      });
      expect(await run('ui_show_culling_plan', { plan_digest: 'd2', request: REQUEST })).toMatchObject({ ok: true });
      expect(plan.suggestions().photos.size).toBe(0);
    });

    it('survives a store-style re-plan that pins a new digest', async () => {
      loadPlan();
      await run('ui_suggest_culling', { photos: [reject('/a.jpg')], groups: [{ path: '/a.jpg', note: 'n' }] });
      plan.setPin({ digest: 'd-slider', request: REQUEST });
      expect(plan.suggestions().photos.size).toBe(1);
      expect(plan.suggestions().notes.size).toBe(1);
    });

    it('counts length in code points like the server model: 200 emoji pass', async () => {
      loadPlan();
      const result = await run('ui_suggest_culling', { photos: [reject('/a.jpg', '😀'.repeat(200))] });
      expect(result).toMatchObject({ ok: true, data: { applied: ['/a.jpg'] } });
    });

    it('validates its own arguments, since the in-page path never runs the server model', async () => {
      loadPlan();
      const handler = direct()['ui_suggest_culling'];
      const bad: Record<string, unknown>[] = [
        {},
        { photos: [{ path: '/a.jpg', action: 'reject', reason: 'x', why: 'y' }] },
        { groups: [{ path: '/a.jpg', note: 'n', why: 'y' }] },
        { photos: [reject('/a.jpg', 'x'.repeat(201))] },
        { photos: Array.from({ length: 101 }, () => reject('/a.jpg')) },
        { groups: Array.from({ length: 51 }, () => ({ path: '/a.jpg', note: 'n' })) },
        { photos: [{ path: 5, action: 'reject', reason: 'x' }] },
        { photos: [{ path: '', action: 'reject', reason: 'x' }] },
        { photos: [{ path: '/a.jpg', action: 'maybe', reason: 'x' }] },
        { photos: [reject('/a.jpg', '')] },
        { photos: [reject('/a.jpg', '😀'.repeat(201))] },
        { photos: 'nope' },
        { photos: [reject('/a.jpg')], replace: 'yes' },
      ];
      for (const args of bad) {
        await expect(handler(args), JSON.stringify(args).slice(0, 80)).rejects.toMatchObject({ code: 'invalid_input' });
      }
      expect(plan.suggestions().photos.size).toBe(0);
    });
  });

  describe('capCullingSnapshot suggestions', () => {
    it('halves a huge suggestions_open list, flags the cut and records the true count', () => {
      const open = Array.from({ length: 2000 }, (_, i) => ({ path: `/photos/${'a'.repeat(80)}/${i}.jpg`, action: 'reject' as const }));
      const snap = {
        plan_digest: 'd', groups_total: 3, confirmed: [], pending: [], changed: [], untouched: 3, plan_truncated: false,
        scope: { album_id: null, date_from: null, date_to: null },
        suggestions_total: 2000, suggestions_accepted: 1, suggestions_open: open,
      };
      const out = capCullingSnapshot(snap, 20 * 1024)!;
      expect(out['truncated']).toBe(true);
      expect(out['suggestions_open_count']).toBe(2000);
      expect((out['suggestions_open'] as unknown[]).length).toBeLessThan(2000);
      expect(out['suggestions_total']).toBe(2000);
      expect(out['scope']).toEqual({ album_id: null, date_from: null, date_to: null });
    });
  });
});

describe('applicableActions', () => {
  const rows = [{ id: 'a', summary: 's', when: ['any'], tools: [{ name: 'read', required_level: 'readonly' }, { name: 'odd', required_level: 'mystery' }] }];

  it('fails closed on an unknown required level', () => {
    expect(applicableActions(rows, new Set(), 'edition')[0].tools).toEqual(['read']);
  });

  it('lists nothing for an unknown session level', () => {
    expect(applicableActions(rows, new Set(), 'mystery')).toEqual([]);
  });
});
