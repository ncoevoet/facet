import { LEVEL_RANK, agentLevel } from './agent-level';
import { NavigationExtras, Router } from '@angular/router';
import { pathOf } from '../../shared/utils/url-path';
import { AuthService } from '../services/auth.service';
import type { Album } from '../services/album.service';
import { GalleryStore } from '../../features/gallery/gallery.store';
import {
  DEFAULT_FILTERS,
  GalleryFilters,
  RANGE_AND_SELECT_KEYS,
  RELEVANCE_SORT,
  SEARCH_THRESHOLD_MAX,
  buildApiParams,
  seededSearchThreshold,
  smartAlbumFilterJson,
} from '../../features/gallery/gallery-filters.util';
import { CULL_DEFAULT_STRICTNESS, CULL_PROFILE_KEY, readStoredStrictnessOrNull } from '../../features/gallery/culling.store';
import { COMPARE_TAB_INDEX, CompareFiltersService, CompareTabName } from '../../features/comparison/compare-filters.service';
import { ViewActionRegistry } from './view-action-registry.service';
import { UserActivityJournal } from './user-activity-journal.service';
import { PageContextService } from './page-context.service';
import { AssistantCullPlanService, type CullPlanRequest, type CullSuggestionAction, MAX_STORED_NOTES, MAX_STORED_SUGGESTIONS } from './assistant-cull-plan.service';
import type { CullPlanSnapshot } from './assistant-cull-plan.service';
import { UiActionRow, UiToolError, UiToolHandler } from './ui-tool.types';

export interface UiToolDeps {
  gallery: GalleryStore;
  router: Router;
  auth: AuthService;
  viewActions: ViewActionRegistry;
  /** What the open page shows and which modal surfaces cover it; read by `ui_get_context`. */
  pageContext: PageContextService;
  /** The generated `actions` table (empty until the contract has loaded). */
  actions: () => readonly UiActionRow[];
  /** Category / strategy / tab state of the comparison page. */
  compareFilters: CompareFiltersService;
  /** What the user did in this tab; read by `ui_get_context`. */
  journal: UserActivityJournal;
  /** The assistant's culling plan: the pin `ui_show_culling_plan` sets and the read model `ui_get_context` reports. */
  plan: AssistantCullPlanService;
  /** Reads one album as the album page would; rejects with the HTTP status. Bypasses the app's HTTP interceptors. */
  fetchAlbum: (id: number) => Promise<Album>;
}

/** Answer of a tool refused because a dialog, bottom sheet or slideshow covers the page. */
export const MODAL_OPEN_MESSAGE = 'A dialog, bottom sheet or slideshow is open in the tab; ask the user to close it.';

/** The contract's cap on `ui_show_photos` paths (api/agent/ui_tools.py MAX_SHOW_PATHS). */
const MAX_SHOW_PATHS = 200;
/** The contract's bounds on `ui_open_album.album_id` and the timeline `year` (api/agent/ui_tools.py). */
const MAX_ALBUM_ID = 2 ** 31 - 1;
const TIMELINE_YEARS = { min: 1900, max: 2100 };

/**
 * The pages `ui_navigate` may open, read from the live router config so a new page
 * or a new edition-only flag cannot drift from a hand list: static top-level paths
 * only (no parameters, redirects, the login page or the public `shared/**` pages).
 */
function appRoutes(router: Router): { allowed: Set<string>; editionOnly: Set<string> } {
  const allowed = new Set<string>();
  const editionOnly = new Set<string>();
  for (const route of router.config) {
    const path = route.path;
    if (path === undefined || route.redirectTo !== undefined || /[:*]/.test(path)) continue;
    if (path === 'login' || path.startsWith('shared/')) continue;
    allowed.add(`/${path}`);
    if ((route.data as { edition?: boolean } | undefined)?.edition === true) editionOnly.add(`/${path}`);
  }
  return { allowed, editionOnly };
}

/**
 * The path segments after `/timeline` for `ui_navigate`'s `year` / `month` (unpadded: the timeline page reads the
 * number it finds in the URL). Anything the contract forbids is `invalid_input`, checked before any side effect.
 */
function timelineSegments(route: string, args: Record<string, unknown>, query: Record<string, unknown>): string[] {
  const { year, month } = args;
  if (year === undefined && month === undefined) return [];
  if (route !== '/timeline') throw new UiToolError('invalid_input', 'year and month are only valid with the /timeline route.');
  if (Object.keys(query).length > 0) throw new UiToolError('invalid_input', 'query cannot be combined with year or month.');
  if (typeof year !== 'number' || !Number.isInteger(year) || year < TIMELINE_YEARS.min || year > TIMELINE_YEARS.max) {
    throw new UiToolError('invalid_input', `year must be an integer from ${TIMELINE_YEARS.min} to ${TIMELINE_YEARS.max}, and month needs it.`);
  }
  if (month === undefined) return [String(year)];
  if (typeof month !== 'number' || !Number.isInteger(month) || month < 1 || month > 12) {
    throw new UiToolError('invalid_input', 'month must be an integer from 1 to 12.');
  }
  return [String(year), String(month)];
}

/** The contract names a filter the way the server's `GalleryParams` does; the tab stores a few under another name. */
export const CONTRACT_TO_CLIENT_KEY: Record<string, keyof GalleryFilters> = {
  person: 'person_id',
  category: 'type',
  semantic_query: 'semanticQuery',
  semantic_threshold: 'search_threshold',
};

const CLIENT_TO_CONTRACT_KEY: Record<string, string> = {
  person_id: 'person',
  type: 'category',
  semanticQuery: 'semantic_query',
  search_threshold: 'semantic_threshold',
};

/** The contract speaks 0-1 fractions (like the MCP tools and the REST routes); the store keeps percent strings. */
const FRACTION_KEYS = new Set(['semantic_threshold', 'min_similarity']);
const SIMILARITY_MODES = ['visual', 'color', 'person'];

function fractionToPercent(key: string, value: unknown): string {
  const fraction = typeof value === 'number' ? value : Number(value);
  const max = key === 'semantic_threshold' ? SEARCH_THRESHOLD_MAX / 100 : 1;
  if (!Number.isFinite(fraction) || fraction < 0 || fraction > max) {
    throw new UiToolError('invalid_input', `${key} must be a number between 0 and ${max}.`);
  }
  return String(Number((fraction * 100).toFixed(4)));
}

function percentToFraction(percent: string): number {
  return Number((Number(percent) / 100).toFixed(6));
}

const SELECTION_PATH_LIMIT = 1000;
/** A selection frame must stay under the bridge's 256 KB limit, so its path lists share this budget. */
const SELECTION_BYTE_BUDGET = 200 * 1024;
/** Room for the snapshot keys around the lists (route, scope, count, truncation flags). */
const SNAPSHOT_ENVELOPE_BYTES = 1024;
const TEXT_ENCODER = new TextEncoder();
const WAIT_STEP_MS = 25;
const WAIT_TIMEOUT_MS = 10_000;

const COMPACT_KEYS = [
  'stack_id', 'stack_count', 'stack_total_count', 'stack_revision',
  'path', 'filename', 'date_taken', 'aggregate', 'aesthetic', 'comp_score', 'face_quality',
  'category', 'face_count', 'is_favorite', 'star_rating', 'is_rejected', 'sequence_kind',
] as const;

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitFor(condition: () => boolean, timeoutMs = WAIT_TIMEOUT_MS): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() >= deadline) return false;
    await delay(WAIT_STEP_MS);
  }
  return true;
}

function isGalleryUrl(url: string): boolean {
  const path = pathOf(url);
  return path === '/' || path === '' || path.startsWith('/album/');
}

const UNSAVED_DECISIONS_MESSAGE = 'The user has decisions on the darkroom they have not confirmed; ask them to confirm or leave them first.';

function toBoolean(key: string, value: unknown): boolean {
  if (typeof value === 'boolean') return value;
  if (value === 1 || value === '1' || value === 'true') return true;
  if (value === 0 || value === '0' || value === 'false') return false;
  throw new UiToolError('invalid_input', `${key} must be a boolean`);
}

/** The longest prefix of `paths` (at most `limit`) that fits `budget` bytes once JSON-encoded. */
function fitPaths(paths: readonly string[], budget: number, limit = SELECTION_PATH_LIMIT): string[] {
  const kept: string[] = [];
  let used = 0;
  for (const path of paths) {
    used += TEXT_ENCODER.encode(JSON.stringify(path)).length + 1;
    if (kept.length >= limit || used > budget) break;
    kept.push(path);
  }
  return kept;
}

/**
 * The facts of a tab's state; the same rules as the server's `actions.facts_for`, so the
 * generated `actions` table means the same thing on both sides.
 */
export function actionFacts(route: string, selectionCount: number, pinned: boolean): Set<string> {
  const path = pathOf(route) || '/';
  const facts = new Set(['any']);
  if (path === '/' || path.startsWith('/album/')) facts.add('gallery');
  if (path === '/photo') facts.add('detail');
  if (path === '/culling') facts.add('culling');
  if (path === '/persons' || path === '/merge-suggestions') facts.add('persons');
  if (path === '/albums' || path.startsWith('/album/')) facts.add('albums');
  if (selectionCount > 0) facts.add('selection');
  if (pinned) facts.add('pinned');
  return facts;
}

/** The jobs that apply to `facts` for a session at `level`; tools above the level are left out. */
export function applicableActions(
  rows: readonly UiActionRow[], facts: ReadonlySet<string>, level: string,
): { id: string; summary: string; tools: string[] }[] {
  const rank = LEVEL_RANK[level] ?? -1;
  const out: { id: string; summary: string; tools: string[] }[] = [];
  for (const row of rows) {
    if (!row.when.includes('any') && !row.when.some(fact => facts.has(fact))) continue;
    const tools = row.tools.filter(tool => (LEVEL_RANK[tool.required_level] ?? Infinity) <= rank).map(tool => tool.name);
    if (tools.length) out.push({ id: row.id, summary: row.summary, tools });
  }
  return out;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

export function createUiToolHandlers(deps: UiToolDeps): Record<string, UiToolHandler> {
  const { gallery, router, auth, viewActions, pageContext, actions, compareFilters, journal, plan, fetchAlbum } = deps;

  const requireGalleryView = (): void => {
    if (!isGalleryUrl(router.url)) {
      throw new UiToolError('no_active_view', `The gallery is not open (the tab shows ${pathOf(router.url) || '/'}). Use ui_navigate to "/" first.`);
    }
  };

  /** Refuse a navigation that would leave /culling (to `target`) while the user holds decisions not yet confirmed. */
  const leaveCullingGuard = (target?: string): void => {
    if (pathOf(router.url) === '/culling' && target !== '/culling' && plan.hasUnsavedDecisions()) {
      throw new UiToolError('unsaved_decisions', UNSAVED_DECISIONS_MESSAGE);
    }
  };

  /**
   * Navigate, and throw `navigation_refused` when the router resolves false. With `sameUrlOk` a resolve of
   * false while the tab already shows the target is not a refusal (navigating to the same URL resolves false);
   * `onRefuse` runs just before the throw. Returns the router's result.
   */
  const navigateOrRefuse = async (
    commands: (string | number)[],
    extras: NavigationExtras | undefined,
    message: string,
    options: { sameUrlOk?: boolean; onRefuse?: () => void } = {},
  ): Promise<boolean> => {
    const alreadyThere = options.sameUrlOk === true && pathOf(router.url) === commands[0];
    const ok = await (extras ? router.navigate(commands, extras) : router.navigate(commands));
    if (!ok && !alreadyThere) {
      options.onRefuse?.();
      throw new UiToolError('navigation_refused', message);
    }
    return ok;
  };

  /**
   * Bring the tab to the gallery and wait until its first load has settled, so a
   * filter patch is not overwritten by the page's own init. The signal is the
   * store's mount counter (bumped when the gallery page initialises), never a delay.
   */
  const ensureGalleryView = async (): Promise<void> => {
    if (!isGalleryUrl(router.url)) {
      leaveCullingGuard();
      const mounts = gallery.galleryMounts();
      await navigateOrRefuse(['/'], undefined, 'The tab could not open the gallery.');
      if (!await waitFor(() => gallery.galleryMounts() > mounts)) {
        throw new UiToolError('upstream_error', 'The gallery did not open.');
      }
    }
    const settled = await waitFor(() => !gallery.initializing() && gallery.config() !== null);
    if (!settled) throw new UiToolError('upstream_error', 'The gallery did not finish loading.');
  };

  /** Leave an album page for the plain gallery, so a view change is never saved as that album's smart filter. */
  const leaveAlbum = async (): Promise<void> => {
    if (!pathOf(router.url).startsWith('/album/')) return;
    const mounts = gallery.galleryMounts();
    await navigateOrRefuse(['/'], undefined, 'The tab could not leave the album.');
    if (!await waitFor(() => gallery.galleryMounts() > mounts)) throw new UiToolError('upstream_error', 'The gallery did not open.');
  };

  const filterDefault = (key: keyof GalleryFilters): GalleryFilters[keyof GalleryFilters] => {
    const configured = gallery.config()?.defaults as Record<string, unknown> | undefined;
    const fromConfig = configured?.[key];
    return fromConfig !== undefined && typeof fromConfig === typeof DEFAULT_FILTERS[key]
      ? fromConfig as GalleryFilters[keyof GalleryFilters]
      : DEFAULT_FILTERS[key];
  };

  const clearedFilters = (): Partial<GalleryFilters> => {
    const keys: (keyof GalleryFilters)[] = [
      ...RANGE_AND_SELECT_KEYS, 'album_id', 'favorites_only', 'is_monochrome', 'manual_faces_need_review', 'faces_need_names', 'similar_to', 'semanticQuery',
      'hide_blinks', 'hide_bursts', 'hide_duplicates', 'hide_brackets', 'hide_panoramas', 'hide_rejected',
      'show_rejected', 'blinks_only', 'duplicates_only',
      'sequence_group_id', 'sequence_kind', 'burst_group_id', 'duplicate_group_id',
    ];
    const cleared: Record<string, unknown> = {};
    for (const key of keys) cleared[key] = filterDefault(key);
    return cleared as Partial<GalleryFilters>;
  };

  /** Contract patch -> the tab's filter shape. An unknown or doubled key refuses the whole patch, never half applies it. */
  const patchToUpdates = (patch: Record<string, unknown>): Partial<GalleryFilters> => {
    const updates: Record<string, unknown> = {};
    for (const [contractKey, value] of Object.entries(patch)) {
      const key = Object.hasOwn(CONTRACT_TO_CLIENT_KEY, contractKey) ? CONTRACT_TO_CLIENT_KEY[contractKey] : contractKey;
      if (!Object.hasOwn(DEFAULT_FILTERS, key)) {
        throw new UiToolError('invalid_input', `This tab has no filter named ${contractKey}.`);
      }
      if (Object.hasOwn(updates, key)) {
        throw new UiToolError('invalid_input', `${CLIENT_TO_CONTRACT_KEY[key] ?? key} was given twice (as category and type, or person and person_id).`);
      }
      const clientKey = key as keyof GalleryFilters;
      if (value === null) {
        updates[clientKey] = clientKey === 'search_threshold'
          ? seededSearchThreshold(gallery.config()?.search_threshold_default)
          : filterDefault(clientKey);
      } else if (FRACTION_KEYS.has(contractKey)) {
        updates[clientKey] = fractionToPercent(contractKey, value);
      } else if (clientKey === 'similarity_mode') {
        if (!SIMILARITY_MODES.includes(String(value))) {
          throw new UiToolError('invalid_input', `similarity_mode must be one of ${SIMILARITY_MODES.join(', ')}.`);
        }
        updates[clientKey] = String(value);
      } else if (typeof DEFAULT_FILTERS[clientKey] === 'boolean') {
        updates[clientKey] = toBoolean(contractKey, value);
      } else if (clientKey === 'sort_direction') {
        updates[clientKey] = String(value).toUpperCase();
      } else {
        updates[clientKey] = String(value);
      }
    }
    if (updates['show_rejected'] && updates['favorites_only']) {
      throw new UiToolError('invalid_input', 'show_rejected and favorites_only cannot be combined in the tab.');
    }
    if (updates['similar_to'] && updates['semanticQuery']) {
      throw new UiToolError('invalid_input', 'similar_to and semantic_query cannot be combined (the tab ranks by one of them).');
    }
    return updates as Partial<GalleryFilters>;
  };

  const viewFilters = (): Record<string, string | number | boolean> => {
    const f = gallery.filters();
    const params = buildApiParams(f, gallery.currentAlbum()?.is_smart ?? false, gallery.config()?.search_threshold_default);
    delete params['page'];
    // The contract names these `semantic_query` / `semantic_threshold` (api/agent/show.py); added below.
    delete params['semantic_q'];
    delete params['semantic_threshold'];
    delete params['per_page'];
    // Relevance is this tab's own sort for a semantic query; the contract's sort enum has no such column.
    if (params['sort'] === RELEVANCE_SORT) {
      delete params['sort'];
      delete params['sort_direction'];
    }
    const out: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(params)) out[Object.hasOwn(CLIENT_TO_CONTRACT_KEY, key) ? CLIENT_TO_CONTRACT_KEY[key] : key] = value;
    if (f.semanticQuery) {
      out['semantic_query'] = f.semanticQuery;
      if (f.search_threshold) out['semantic_threshold'] = percentToFraction(f.search_threshold);
    }
    if (f.similar_to) {
      out['similar_to'] = f.similar_to;
      out['similarity_mode'] = f.similarity_mode;
      out['min_similarity'] = percentToFraction(f.min_similarity);
    }
    return out;
  };

  const selectionSnapshot = (): Record<string, unknown> => {
    // The page rides with the selection: the gallery selection outlives leaving the gallery, and a server tool
    // that must act on the gallery's own selection reads the page from the same answer.
    const route = pathOf(router.url) || '/';
    const budget = SELECTION_BYTE_BUDGET - SNAPSHOT_ENVELOPE_BYTES - TEXT_ENCODER.encode(JSON.stringify({ route })).length;
    if (gallery.viewScopeSelected()) {
      const filters = gallery.filterPayload();
      const excluded = [...gallery.excludedPaths()];
      const kept = fitPaths(excluded, budget - TEXT_ENCODER.encode(JSON.stringify(filters)).length);
      return {
        route,
        scope: 'view',
        count: gallery.selectionCount(),
        filters,
        excluded_paths: kept,
        excluded_count: excluded.length,
        excluded_truncated: kept.length < excluded.length,
      };
    }
    const paths = [...gallery.selectedPaths()];
    const kept = fitPaths(paths, budget);
    return {
      route,
      scope: 'paths',
      count: paths.length,
      paths: kept,
      ...(kept.length < paths.length ? { truncated: true } : {}),
    };
  };

  /** The session level this tab carries, as the server's bridge records it. */
  const sessionLevel = (): string => agentLevel({ authenticated: auth.isAuthenticated(), multi_user: auth.isMultiUser(), edition_authenticated: auth.isEdition() });

  return {
    ui_navigate: async args => {
      const route = args['route'] as string;
      const { allowed, editionOnly } = appRoutes(router);
      if (!allowed.has(route)) throw new UiToolError('invalid_input', `${String(route).slice(0, 80)} is not a page of this app.`);
      if (editionOnly.has(route) && !auth.isEdition()) {
        throw new UiToolError('forbidden_level', `${route} needs an edition session.`);
      }
      const query = (args['query'] ?? {}) as Record<string, string | number | boolean>;
      const queryParams = Object.fromEntries(Object.entries(query).map(([k, v]) => [k, String(v)]));
      const commands = [route, ...timelineSegments(route, args, query)];
      leaveCullingGuard(route);
      await navigateOrRefuse(commands, { queryParams, onSameUrlNavigation: 'reload' }, `The tab refused to open ${route}.`);
      return { route: pathOf(router.url) || '/' };
    },

    ui_set_gallery_filters: async args => {
      const patch = (args['patch'] ?? {}) as Record<string, unknown>;
      patchToUpdates(patch);
      // On an album page the store saves every filter change as that album's smart filter (edition sessions),
      // which a readonly-granted agent must never cause: leave the album for any change, not only a replace.
      await leaveAlbum();
      await ensureGalleryView();
      // Built after the gallery is up: the cleared state and null resets use the configured defaults, which load with it.
      await gallery.updateFilters({ ...(args['replace'] === true ? clearedFilters() : {}), ...patchToUpdates(patch) });
      if (gallery.loadError()) throw new UiToolError('upstream_error', 'The gallery could not load photos for these filters.');
      return {
        applied: Object.keys(patch),
        total: gallery.total(), photo_total: gallery.photoTotal(),
        loaded: gallery.photos().length,
        filters: viewFilters(),
      };
    },

    ui_show_photos: async args => {
      const paths = stringList(args['paths']);
      if (paths.length === 0 || paths.length > MAX_SHOW_PATHS) {
        throw new UiToolError('invalid_input', `Give 1 to ${MAX_SHOW_PATHS} paths.`);
      }
      await leaveAlbum();
      await ensureGalleryView();
      const missing = await gallery.showPaths(paths);
      if (gallery.loadError()) throw new UiToolError('upstream_error', 'The gallery could not load these photos.');
      return {
        shown: gallery.photos().length,
        missing: missing.slice(0, 50),
        total: gallery.total(), photo_total: gallery.photoTotal(),
      };
    },

    ui_get_gallery_view: async args => {
      requireGalleryView();
      const limit = typeof args['limit'] === 'number' ? args['limit'] : 50;
      const photos = gallery.photos().slice(0, limit).map(photo => {
        const row = photo as unknown as Record<string, unknown>;
        return Object.fromEntries(COMPACT_KEYS.map(key => [key, row[key] ?? null]));
      });
      return {
        route: pathOf(router.url) || '/',
        filters: viewFilters(),
        sort: gallery.filters().sort,
        sort_direction: gallery.filters().sort_direction,
        total: gallery.total(), photo_total: gallery.photoTotal(),
        loaded: gallery.photos().length,
        has_more: gallery.hasMore(),
        photos,
        selection_count: gallery.selectionCount(),
        hidden_summary: gallery.hiddenSummary(),
        // The page's own init (filters reset, album applied, first page requested) is loading too, though the store's flag is still false.
        loading: gallery.loading() || gallery.initializing(),
        // What the gallery itself would save for a smart album of this view, and whether the view is one a
        // stored album can express (not similar / semantic / an assistant-pinned list): `create_album` target "view".
        album_filter_json: smartAlbumFilterJson(gallery.filters()),
        filters_scopable: gallery.canScopeSelectionToView(),
      };
    },

    ui_open_photo: async args => {
      const path = args['path'] as string;
      leaveCullingGuard();
      await navigateOrRefuse(['/photo'], { queryParams: { path }, onSameUrlNavigation: 'reload' }, 'The tab could not open that photo.');
      return { route: '/photo', path };
    },

    ui_open_album: async args => {
      const id = args['album_id'];
      if (typeof id !== 'number' || !Number.isInteger(id) || id < 1 || id > MAX_ALBUM_ID) {
        throw new UiToolError('invalid_input', `album_id must be an integer from 1 to ${MAX_ALBUM_ID}.`);
      }
      leaveCullingGuard();
      const route = `/album/${id}`;
      if (pathOf(router.url) === route) return { route, album_id: id, already_open: true };
      // The gallery page swallows a failed album read and would show a gallery scoped to nothing, so existence is checked here.
      const album = await fetchAlbum(id).catch((err: unknown) => {
        const status = (err as { status?: number } | null)?.status;
        if (status === 404 || status === 403) throw new UiToolError('not_found', `There is no album ${id} for this account.`);
        throw new UiToolError('upstream_error', `The album could not be read (${status ? status : 'network error'}).`);
      });
      // The user may have flipped a group while the album was being read; /culling has no deactivation guard of its own.
      leaveCullingGuard();
      if (pageContext.overlays().length) throw new UiToolError('modal_open', MODAL_OPEN_MESSAGE);
      const mounts = gallery.galleryMounts();
      await navigateOrRefuse(['/album', id], { onSameUrlNavigation: 'reload' }, 'The tab could not open that album.');
      // Resolve only once the page shows this album: its filters applied and its first page loaded.
      const shown = await waitFor(() => gallery.galleryMounts() > mounts && !gallery.initializing() && gallery.currentAlbum()?.id === id);
      if (!shown) throw new UiToolError('upstream_error', 'The album did not finish loading.');
      return { route, album_id: id, name: album.name, is_smart: album.is_smart };
    },

    ui_select_photos: async args => {
      const paths = args['paths'] === undefined ? undefined : stringList(args['paths']);
      const selectView = args['select_view'] === true;
      const mode = (args['mode'] ?? 'replace') as 'replace' | 'add' | 'remove';
      if (selectView === (paths !== undefined && paths.length > 0)) {
        throw new UiToolError('invalid_input', 'Give exactly one of a non-empty `paths` and `select_view: true`.');
      }
      if (selectView) {
        if (mode === 'remove') throw new UiToolError('invalid_input', '`select_view` cannot be combined with mode "remove".');
        requireGalleryView();
        if (!gallery.canScopeSelectionToView()) {
          throw new UiToolError('invalid_input', 'This view (similar-photo, semantic search or an assistant-chosen list) cannot be selected as a whole.');
        }
        gallery.selectWholeView();
        return selectionSnapshot();
      }
      const wanted = paths ?? [];
      if (mode === 'replace') {
        gallery.restoreSelection(wanted);
        return selectionSnapshot();
      }
      // Under a view-scoped selection the edited set is the exclusion list, so adding a photo takes it OUT of that set.
      const viewScoped = gallery.viewScopeSelected();
      const edited = new Set(viewScoped ? gallery.excludedPaths() : gallery.selectedPaths());
      const insert = viewScoped ? mode === 'remove' : mode === 'add';
      const inView = new Set(gallery.photos().map(photo => photo.path));
      const notInView: string[] = [];
      for (const path of wanted) {
        if (viewScoped && insert && !inView.has(path)) notInView.push(path);
        else if (insert) edited.add(path);
        else edited.delete(path);
      }
      if (!viewScoped) {
        gallery.restoreSelection(edited);
      } else {
        gallery.excludedPaths.set(edited);
        // An exclusion outside the view would shrink the count below the number of photos actually selected.
        if (notInView.length) return { ...selectionSnapshot(), not_in_view: notInView.slice(0, SELECTION_PATH_LIMIT) };
      }
      return selectionSnapshot();
    },

    ui_clear_selection: async () => {
      gallery.clearSelection();
      return selectionSnapshot();
    },

    ui_get_selection: async () => selectionSnapshot(),

    ui_get_context: async args => {
      const route = pathOf(router.url) || '/';
      const inGallery = isGalleryUrl(router.url);
      const albumMatch = /^\/album\/(\d+)$/.exec(route);
      const timelineMatch = /^\/timeline\/(\d+)(?:\/(\d+))?$/.exec(route);
      const params = new URLSearchParams(router.url.split('#')[0].split('?')[1] ?? '');
      const selection = selectionSnapshot();
      const pinned = gallery.pinnedPaths() !== null;
      const level = sessionLevel();
      const storedProfile = localStorage.getItem(CULL_PROFILE_KEY) || null;
      const since = typeof args['activity_since'] === 'number' ? args['activity_since'] : 0;
      const focusedPath = inGallery
        ? gallery.focusedPath()
        : route === '/photo'
          ? params.get('path')
          : route === '/culling'
            ? journal.darkroomFocus()
            : null;
      return {
        route,
        focused: focusedPath ? { path: focusedPath } : null,
        user_activity: journal.since(since),
        ...(route === '/photo' && params.get('path') ? { query_path: params.get('path') } : {}),
        ...(albumMatch ? { album_id: Number(albumMatch[1]) } : {}),
        timeline: timelineMatch ? { year: Number(timelineMatch[1]), month: timelineMatch[2] ? Number(timelineMatch[2]) : null } : null,
        selection: { scope: selection['scope'], count: selection['count'] },
        gallery: inGallery
          ? { total: gallery.total(), photo_total: gallery.photoTotal(), loaded: gallery.photos().length, has_more: gallery.hasMore(), pinned }
          : null,
        culling: pageContext.snapshot()?.['mode'] === 'stacks' ? null : capCullingSnapshot(plan.snapshot()),
        // A stored preset without a stored slider value reports no strictness: the preset's own applies.
        culling_defaults: {
          profile: storedProfile,
          strictness: readStoredStrictnessOrNull() ?? (storedProfile ? null : CULL_DEFAULT_STRICTNESS),
        },
        page: pageContext.snapshot(),
        overlays: pageContext.overlays(),
        mounted_actions: viewActions.names(),
        level,
        actions: applicableActions(actions(), actionFacts(route, gallery.selectionCount(), pinned), level),
      };
    },

    ui_next_page: async () => {
      requireGalleryView();
      const before = gallery.photos().length;
      if (gallery.hasMore()) await gallery.nextPage();
      return {
        loaded: gallery.photos().length,
        added: gallery.photos().length - before,
        total: gallery.total(), photo_total: gallery.photoTotal(),
        has_more: gallery.hasMore(),
      };
    },

    /**
     * Puts the compare page on a tab (A/B by default; snapshots, suggestions or weights to review a change
     * the assistant made) for the user to answer. A locked suggestions tab is not checked here: the page shows its
     * own locked state. It only sets the page's own
     * state through the service: it never submits a comparison and sends no key event, so the
     * answer stays the user's click (ArrowLeft / ArrowRight / T are the page's answer shortcuts).
     */
    ui_show_comparison: async args => {
      if (!auth.isEdition()) throw new UiToolError('forbidden_level', 'The comparison page needs an edition session.');
      const tab = args['tab'] === undefined ? 'ab' : args['tab'];
      if (typeof tab !== 'string' || !Object.hasOwn(COMPARE_TAB_INDEX, tab)) {
        throw new UiToolError('invalid_input', `Unknown comparison tab; use one of ${Object.keys(COMPARE_TAB_INDEX).join(', ')}.`);
      }
      // Before any compareFilters write, so a refusal leaves no side effect.
      leaveCullingGuard();
      const category = typeof args['category'] === 'string' ? args['category'] : '';
      const strategy = typeof args['strategy'] === 'string' ? args['strategy'] : '';
      if (category) compareFilters.selectedCategory.set(category);
      if (strategy) compareFilters.strategy.set(strategy);
      compareFilters.activeTab.set(COMPARE_TAB_INDEX[tab as CompareTabName]);
      // Already there: navigating to the same URL resolves false, which is not a refusal.
      if (pathOf(router.url) !== '/compare') {
        await navigateOrRefuse(['/compare'], undefined, 'The tab refused to open the comparison page.');
      }
      return {
        route: '/compare',
        category: compareFilters.selectedCategory() || null,
        strategy: compareFilters.strategy() || null,
        tab,
      };
    },

    ui_show_culling_group: async args => {
      if (pageContext.snapshot()?.['mode'] === 'stacks') throw new UiToolError('stack_mode_active', 'Suggested stacks is active.');
      if (!auth.isEdition()) throw new UiToolError('forbidden_level', 'The darkroom needs an edition session.');
      const name = 'ui_show_culling_group';
      if (!viewActions.get(name)) {
        await navigateOrRefuse(['/culling'], undefined, 'The tab refused to open the darkroom.', { sameUrlOk: true });
        await waitFor(() => viewActions.get(name) !== undefined);
      }
      const action = viewActions.get(name);
      if (!action) throw new UiToolError('no_active_view', 'The darkroom did not open.');
      return action(args);
    },

    /**
     * Pins the assistant's culling plan and opens /culling on it. The tab reproduces the plan itself (the
     * store posts `request` and `plan_digest` to `/culling/plan`), so no group data crosses the bridge.
     * The same digest as the held pin only moves the focus: nothing is re-fetched or re-seeded. A different
     * digest replaces the plan, which would throw away what the user decided but has not committed, so it
     * is refused with `unsaved_decisions` first. A plan the library has moved past is `plan_changed`.
     */
    ui_show_culling_plan: async args => {
      if (pageContext.snapshot()?.['mode'] === 'stacks') throw new UiToolError('stack_mode_active', 'Suggested stacks is active.');
      if (!auth.isEdition()) throw new UiToolError('forbidden_level', 'The darkroom needs an edition session.');
      const digest = args['plan_digest'] as string;
      const focus = typeof args['focus'] === 'number' ? args['focus'] : undefined;
      if (plan.pin()?.digest === digest) {
        if (focus !== undefined) plan.setFocus(focus);
      } else {
        if (plan.hasUnsavedDecisions()) {
          throw new UiToolError('unsaved_decisions', UNSAVED_DECISIONS_MESSAGE);
        }
        // A different plan is a different set of photos: the assistant's marks on the old one go with it.
        plan.clearSuggestions();
        plan.setPin({ digest, request: args['request'] as CullPlanRequest, focusNumber: focus });
      }
      const name = 'ui_show_culling_group';
      if (pathOf(router.url) !== '/culling' || !viewActions.get(name)) {
        const ok = await navigateOrRefuse(['/culling'], undefined, 'The tab refused to open the darkroom.', {
          sameUrlOk: true,
          onRefuse: () => plan.clear(),
        });
        if (ok) await waitFor(() => viewActions.get(name) !== undefined);
      }
      const loaded = (): boolean => plan.pin()?.digest !== digest || plan.snapshot()?.plan_digest === digest;
      if (!await waitFor(loaded)) throw new UiToolError('upstream_error', 'The plan did not load.');
      const snapshot = plan.snapshot();
      if (plan.pin()?.digest !== digest || !snapshot) {
        if (plan.loadFailure(digest) === 'failed') {
          throw new UiToolError('plan_load_failed', 'The tab could not load the plan; try again.');
        }
        throw new UiToolError('plan_changed', 'The library changed since the plan was previewed; preview again.');
      }
      return { route: '/culling', plan_digest: digest, groups_total: snapshot.groups_total };
    },

    /**
     * Annotates the plan the tab holds with the assistant's per-photo suggestions and per-group notes. It
     * never changes the plan, its digest or a selection: the user accepts a badge with a click. The in-page
     * WebMCP path validates only against the JSON schema, so the model's own rules are checked here too.
     */
    ui_suggest_culling: async args => {
      if (!auth.isEdition()) throw new UiToolError('forbidden_level', 'The darkroom needs an edition session.');
      const { photos, groups, replace } = parseSuggestArgs(args);
      const snapshot = plan.snapshot();
      if (!snapshot) throw new UiToolError('no_plan', 'The tab holds no culling plan; show one with auto_cull first.');
      const outcome = plan.suggest(photos, groups, replace);
      if (outcome === 'too_large') {
        throw new UiToolError('too_large', `Too many suggestions held in the tab (limit ${MAX_STORED_SUGGESTIONS} photos / ${MAX_STORED_NOTES} notes), not the result-size limit; use replace.`);
      }
      return { plan_digest: snapshot.plan_digest, ...outcome };
    },
  };
}

const SUGGEST_MAX_PHOTOS = 100;
const SUGGEST_MAX_GROUPS = 50;
const SUGGEST_MAX_TEXT = 200;
const SUGGEST_MAX_PATH = 4096;

/** A non-empty string of at most `max` characters, or `invalid_input` naming `label`. */
function boundedString(value: unknown, max: number, label: string): string {
  if (typeof value !== 'string' || [...value].length < 1 || [...value].length > max) {
    throw new UiToolError('invalid_input', `${label} must be a string of 1 to ${max} characters.`);
  }
  return value;
}

/** The entries of an optional array whose items are objects with exactly `keys`, at most `limit` of them. */
function strictEntries(value: unknown, keys: readonly string[], limit: number, label: string): Record<string, unknown>[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > limit) {
    throw new UiToolError('invalid_input', `${label} must be an array of at most ${limit} entries.`);
  }
  return value.map(item => {
    const known = item !== null && typeof item === 'object' && !Array.isArray(item)
      && Object.keys(item).length === keys.length && keys.every(key => key in item);
    if (!known) throw new UiToolError('invalid_input', `Each ${label} entry takes exactly ${keys.join(', ')}.`);
    return item as Record<string, unknown>;
  });
}

function parseSuggestArgs(args: Record<string, unknown>): {
  photos: { path: string; action: CullSuggestionAction; reason: string }[];
  groups: { path: string; note: string }[];
  replace: boolean;
} {
  const photos = strictEntries(args['photos'], ['path', 'action', 'reason'], SUGGEST_MAX_PHOTOS, 'photos').map(item => {
    if (item['action'] !== 'keep' && item['action'] !== 'reject') {
      throw new UiToolError('invalid_input', 'A photo action must be "keep" or "reject".');
    }
    return {
      path: boundedString(item['path'], SUGGEST_MAX_PATH, 'A photo path'),
      action: item['action'] as CullSuggestionAction,
      reason: boundedString(item['reason'], SUGGEST_MAX_TEXT, 'A reason'),
    };
  });
  const groups = strictEntries(args['groups'], ['path', 'note'], SUGGEST_MAX_GROUPS, 'groups').map(item => ({
    path: boundedString(item['path'], SUGGEST_MAX_PATH, 'A group path'),
    note: boundedString(item['note'], SUGGEST_MAX_TEXT, 'A note'),
  }));
  if (args['replace'] !== undefined && typeof args['replace'] !== 'boolean') {
    throw new UiToolError('invalid_input', 'replace must be a boolean.');
  }
  const replace = args['replace'] === true;
  if (!photos.length && !groups.length && !replace) {
    throw new UiToolError('invalid_input', 'Nothing to suggest: give photos, groups or replace: true.');
  }
  return { photos, groups, replace };
}

/**
 * Byte budget of the `culling` block in `ui_get_context`. The bridge replaces a whole result above
 * 250 KiB with `too_large`, so the block is cut here, well under that, and the rest (activity,
 * actions) keeps its room.
 */
export const CULLING_BLOCK_BUDGET = 100 * 1024;

const CULLING_LISTS = ['confirmed', 'pending', 'changed', 'suggestions_open'] as const;

/**
 * Trim the snapshot's lists from the tail until its JSON fits `CULLING_BLOCK_BUDGET`. The biggest list is
 * halved each round. A cut records the true size of every list in `<name>_count` (the fields the server's
 * `fit_culling` emits) and sets `truncated`; `groups_total` and `untouched` stay true. `plan_truncated`
 * is the plan's own cap and is never touched.
 */
export function capCullingSnapshot(snapshot: CullPlanSnapshot | null, budget = CULLING_BLOCK_BUDGET): Record<string, unknown> | null {
  if (!snapshot) return null;
  const size = (value: unknown): number => new TextEncoder().encode(JSON.stringify(value)).length;
  if (size(snapshot) <= budget) return { ...snapshot };
  const out: Record<string, unknown> = {
    ...snapshot,
    confirmed_count: snapshot.confirmed.length,
    pending_count: snapshot.pending.length,
    changed_count: snapshot.changed.length,
    suggestions_open_count: snapshot.suggestions_open.length,
    truncated: true,
  };
  while (size(out) > budget) {
    let biggest: (typeof CULLING_LISTS)[number] | null = null;
    let biggestSize = 0;
    for (const name of CULLING_LISTS) {
      const list = out[name] as unknown[];
      const listSize = list.length ? size(list) : 0;
      if (listSize > biggestSize) {
        biggest = name;
        biggestSize = listSize;
      }
    }
    if (!biggest) break;
    const list = out[biggest] as unknown[];
    out[biggest] = list.slice(0, Math.floor(list.length / 2));
  }
  return out;
}
