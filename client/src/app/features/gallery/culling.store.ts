import { SEQUENCE_KINDS_KEPT_WHOLE } from '../../shared/pipes/sequence-kind.pipe';
import { DestroyRef, Injectable, Injector, inject, signal, computed, WritableSignal } from '@angular/core';
import { Subject, firstValueFrom } from 'rxjs';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { UndoService } from '../../core/services/undo.service';
import { StackReviewDraft } from './stack-editor-host';
import { StackReviewActionsService } from './stack-review-actions.service';
import { StackActionsService } from './stack-actions.service';
import { STACK_SUGGESTION_MAX, STACK_SUGGESTION_MAX_PHOTOS } from './stack-limits';
import { ApiService } from '../../core/services/api.service';
import type { ComparisonStats } from '../../core/api/types';
import { Album, AlbumService } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { CULLING_GROUP_TYPES, CullDateRangePipe, cullingGroupKey, type CullingGroup } from './burst-culling.pipes';
import { plainScopeDate } from '../../shared/utils/date-format';
import {
  AssistantCullPlanService, type CullPlanFlip, type CullPlanPin, type CullPlanRequest, type CullSuggestionAction,
} from '../../core/agent/assistant-cull-plan.service';
import type { components } from '../../core/api/schema';
import type { Photo } from '../../shared/models/photo.model';

/** Private provenance shared only by rows loaded in this visit and their mark-only replacements. */
interface LoadedStackSuggestion {
  epoch: number;
  membership: string;
  /** Private draft state lives only as long as this loaded proposal or its Undo callback. */
  rejected: WritableSignal<ReadonlyMap<string, object>>;
}

/** A feed row that is a stack suggestion: only those carry the key and a stackable kind. */
type StackSuggestionRow = CullingGroup & { type: 'burst' | 'duplicate'; suggestionKey: string };

export interface CullingGroupsResponse {
  groups: CullingGroup[];
  total_groups: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/** Response of POST /culling/plan: the groups come back as feed rows plus their `plan` block. */
export interface CullingPlanResponse extends Omit<components['schemas']['CullingPlanResponse'], 'groups'> {
  groups: CullingGroup[];
}

/** How a plan load ended: `out_of_date` is the 412 (the digest moved), `superseded` a newer load or reset overtook it. */
export type CullPlanLoadOutcome = 'landed' | 'out_of_date' | 'failed' | 'superseded';

/** Groups revealed per step; the feed's page size, which plan mode reuses so `loadMore` behaves the same. */
export const CULL_PAGE_SIZE = 20;

/** A genre culling preset (GET /api/culling/profiles) bundling the culling knobs. */
export interface CullProfile {
  id: string;
  label_key: string;
  strictness: number | null;
  eyes_closed_max: number | null;
  poor_expression_min: number | null;
  keep_min_per_group: number;
  similarity_threshold: number | null;
}
export interface CullProfilesResponse { profiles: CullProfile[]; default: string; }

// Per-user culling toolbar preferences, persisted so the page reopens the way
// the user left it. The URL query param (deep links / "Cull this scene") still
// overrides the stored granularity.
export const CULL_GROUP_BY_KEY = 'facet_culling_group_by';
export const CULL_SORT_KEY = 'facet_culling_sort';
export const CULL_SORT_DIR_KEY = 'facet_culling_sort_direction';
export const CULL_PROFILE_KEY = 'facet_culling_profile';
/** The slider's strictness, stored on every change so a reload restores it and `ui_get_context` reports it live. */
export const CULL_STRICTNESS_KEY = 'facet_culling_strictness';
/** The auto-keep strictness the page starts at when none is stored; the assistant's `auto_cull` plans with the stored one when the user stored no profile. */
export const CULL_DEFAULT_STRICTNESS = 100;
/** How long the slider must settle in plan mode before the plan is recomputed: a drag fires `valueChange` per step. */
export const CULL_REPLAN_DEBOUNCE_MS = 400;

export const GROUP_BY_VALUES = ['all', ...CULLING_GROUP_TYPES] as const;
export type GroupBy = typeof GROUP_BY_VALUES[number];
const SORT_VALUES = ['easiest', 'redundant', 'best', 'recent', 'needs_comparisons', 'chronological'];

export function readStoredGroupBy(): GroupBy {
  const v = localStorage.getItem(CULL_GROUP_BY_KEY);
  return (GROUP_BY_VALUES as readonly string[]).includes(v ?? '') ? v as GroupBy : 'all';
}

export function readStoredSort(): string {
  const v = localStorage.getItem(CULL_SORT_KEY);
  return v && SORT_VALUES.includes(v) ? v : 'easiest';
}

/** The stored strictness when it is an integer in 0..100, else null; a blocked localStorage reads as nothing stored. */
export function readStoredStrictnessOrNull(): number | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(CULL_STRICTNESS_KEY);
  } catch {
    return null;
  }
  if (raw === null || !/^\d{1,3}$/.test(raw)) return null;
  const value = Number(raw);
  return value <= 100 ? value : null;
}

/** The stored strictness when it is an integer in 0..100, else the default. */
export function readStoredStrictness(): number {
  return readStoredStrictnessOrNull() ?? CULL_DEFAULT_STRICTNESS;
}

/** Stored sort direction. '' means "whatever the active mode naturally does". */
export function readStoredSortDirection(): '' | 'asc' | 'desc' {
  const v = localStorage.getItem(CULL_SORT_DIR_KEY);
  return v === 'asc' || v === 'desc' ? v : '';
}

/** Replace one key of a Map held in a signal (clones, so the signal notifies). */
export function updateMapSignal<K, V>(sig: WritableSignal<Map<K, V>>, key: K, value: V): void {
  sig.update(m => { const next = new Map(m); next.set(key, value); return next; });
}

/** Drop one key of a Map held in a signal (clones, so the signal notifies). */
export function deleteMapKey<K, V>(sig: WritableSignal<Map<K, V>>, key: K): void {
  sig.update(m => { if (!m.has(key)) return m; const next = new Map(m); next.delete(key); return next; });
}

/** Add a value to a Set held in a signal (clones, so the signal notifies). */
export function addToSetSignal<V>(sig: WritableSignal<Set<V>>, value: V): void {
  sig.update(s => { const next = new Set(s); next.add(value); return next; });
}

/** Response of POST /api/culling/auto (dry-run preview and apply share the shape). */
export interface AutoCullResponse {
  groups_processed: number;
  kept: number;
  rejected: number;
  highlights_added: number;
  dry_run: boolean;
  /** One page of whole groups; `number` is the 1-based position in the full plan. */
  preview: { number: number; group_id: number; type: string; keep_paths: string[]; reject_paths: string[]; best_path: string }[];
  /** Cursor of the next page, null when the preview is complete. */
  next_cursor: number | null;
  plan_digest: string;
}

/** Request body of POST /culling/auto. The dry run's body is kept verbatim so
 *  the apply re-sends the very parameters the displayed counts came from. */
export interface AutoCullRequest {
  group_by: GroupBy;
  strictness: number;
  dry_run: boolean;
  highlights_album: string;
  trim_brackets: boolean;
  profile?: string;
  album_id?: number;
  date_from?: string;
  date_to?: string;
}

/** How an auto-cull dry run ended, for the callers that reconcile their own
 *  state against the snapshot it publishes. `superseded` covers both a newer
 *  run and the destructive apply owning the dialog: in neither case is the
 *  outcome this caller's to act on, and reading it as its own failure reverts
 *  UI state to a snapshot that is no longer the one on screen. */
export type AutoCullRunOutcome = 'landed' | 'superseded' | 'failed';

/** Response of GET /api/culling/suggest_profile: the preset the scope's own
 *  content argues for, and the confidence it named it with (surfaced in the
 *  Suggested badge's tooltip). The endpoint also returns `evidence` -- the
 *  per-genre counts `confidence` was computed from -- which nothing here
 *  reads, so it is left off this type rather than declared and ignored. */
export interface ProfileSuggestion {
  profile: string | null;
  confidence: number;
}

/** Monotonic guard for the two passes here that can be superseded while they
 *  await — darkroom focus peaking and the auto-cull dry run. A pass takes a
 *  ticket with `next()` and drops its result unless `isCurrent(ticket)` still
 *  holds; `cancel()` invalidates whatever is in flight without starting one. */
export class RunGeneration {
  private value = 0;

  next(): number {
    return ++this.value;
  }

  isCurrent(run: number): boolean {
    return run === this.value;
  }

  cancel(): void {
    this.value++;
  }
}

/** A user-facing message the store wants shown. The store never touches the
 *  snackbar: the component renders these, so the store stays free of the DOM. */
export interface CullingNotice {
  key: string;
  params?: Record<string, string | number>;
  duration: number;
}

/** `POST /photos/by_paths` accepts at most this many paths (BY_PATHS_MAX). */
export const BY_PATHS_CHUNK = 500;

/**
 * Data state and API calls of the darkroom (`BurstCullingComponent`).
 *
 * Provided by the component (`providers: [CullingStore]`), so its lifetime is
 * one darkroom visit: decisions never persist across visits. The `root`
 * registration exists only so the component can still be instantiated as a
 * plain service by a test bed, which ignores component-level providers.
 * View state (zoom, focus, keyboard, layout, DOM) stays in the component.
 */
/** How long after an accept a click or double-click on that photo's tile is taken as the rest of the badge's double-click. */
const ACCEPT_DOUBLE_CLICK_MS = 500;

@Injectable({ providedIn: 'root' })
export class CullingStore {
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly plan = inject(AssistantCullPlanService);

  private readonly injector = inject(Injector);
  // These dependencies belong to the optional stack workflow, so cull-only consumers need not construct them.
  private get stacks(): PhotoStackService { return this.injector.get(PhotoStackService); }
  private get stackActions(): StackActionsService { return this.injector.get(StackActionsService); }
  private get reviewActions(): StackReviewActionsService { return this.injector.get(StackReviewActionsService); }
  private get undo(): UndoService { return this.injector.get(UndoService); }

  readonly mode = signal<'cull' | 'stacks'>('cull');
  readonly stackBusy = signal(false);
  /** Project only live rows; completed proposal state is retained weakly with its provenance. */
  readonly stackExcluded = computed<Record<string, boolean>>(() => {
    const excluded: Record<string, boolean> = Object.create(null);
    for (const group of this.groups()) {
      const rejected = this.suggestionProvenance.get(group)?.rejected();
      if (rejected) for (const path of rejected.keys()) excluded[path] = true;
    }
    return excluded;
  });
  readonly stackDrafts = computed(() => Object.fromEntries(this.groups().map(group => {
    const paths = group.photos.filter(photo => !this.stackExcluded()[photo.path]).map(photo => photo.path);
    return [this.groupKey(group), { paths, excludedCount: group.photos.length - paths.length }];
  })));

  readonly stackFilters = signal<Record<string, string>>({});
  /**
   * The one guard of every cull write: each public cull entry point returns early on it, and work
   * resumed after an await re-checks it through `cullLoadCurrent`, so Suggested stacks never reaches one.
   */
  readonly cullWritesAllowed = computed(() => this.mode() === 'cull');
  readonly batchFull = signal(false);
  /** The page falls back to cull mode for invalid endpoint filters; network failures stay retryable. */
  readonly stackScopeInvalid = signal(false);
  private visitEpoch = 0;
  private stackSession: (() => boolean) | null = null;
  private stackScope = '';
  private stackBatchPending: Promise<void> | null = null;
  /** Exhaustion decisions newer than a pending snapshot still require a fresh batch when it lands empty. */
  private stackRefillVersion = 0;
  private readonly stackDecisions = new Set<string>();
  private readonly suggestionProvenance = new WeakMap<CullingGroup, LoadedStackSuggestion>();
  // Only a live inverse command should keep completed photo rows reachable.
  private completedSuggestions = new WeakMap<LoadedStackSuggestion, CullingGroup>();
  // Suppress only completions that could race the current read snapshot.
  private stackBatchCompletions: Set<string> | null = null;

  /** Cull work resumed after an await still applies: the page is in cull mode and no reset or reload overtook it. */
  private cullLoadCurrent(gen: number): boolean {
    return this.cullWritesAllowed() && gen === this.loadGenerationId;
  }

  /** Set before the page starts any cull effects. A held global assistant pin belongs to its owner. */
  enterStackMode(filters: Record<string, string>): void {
    this.visitEpoch++;
    this.cancelReplan();
    this.clearAllPassTimers();
    this.closeAutoCull();
    this.planActive.set(false);
    this.planDigest.set(null);
    this.planAll = [];
    this.mode.set('stacks');
    this.stackFilters.set({ ...filters });
    this.stackScope = JSON.stringify(this.stackFilters());
    this.stackSession = this.stacks.context();
    this.stackRefillVersion = 0;
    this.resetStackVisitState();
    this.resetFeed();
    this.hiddenGroups.set(new Set());
  }

  leaveStackMode(): void {
    this.visitEpoch++;
    this.stackSession = null;
    this.resetStackVisitState();
    this.mode.set('cull');
    this.stackFilters.set({});
    this.clearAllPassTimers();
    this.resetFeed();
  }

  /** Forget the per-visit stack workflow state; entering and leaving both start from it. */
  private resetStackVisitState(): void {
    this.stackBatchPending = null;
    this.stackDecisions.clear(); this.stackBusy.set(false);
    this.completedSuggestions = new WeakMap();
    this.stackBatchCompletions = null;
    this.batchFull.set(false);
    this.stackScopeInvalid.set(false);
  }

  private stackVisitCurrent(epoch = this.visitEpoch): boolean {
    return epoch === this.visitEpoch && this.mode() === 'stacks'
      && this.stackScope === JSON.stringify(this.stackFilters())
      && !!this.stackSession && this.stacks.isLive(this.stackSession);
  }

  private suggestionIdentity(group: CullingGroup): string {
    return `${this.groupKey(group)}:${group.suggestionKey ?? ''}`;
  }

  private suggestionMembership(group: CullingGroup): string {
    return JSON.stringify([group.type, group.group_id, group.suggestionKey, group.photos.map(photo => photo.path)]);
  }

  private static isSuggestionRow(group: CullingGroup): group is StackSuggestionRow {
    return !!group.suggestionKey && (group.type === 'burst' || group.type === 'duplicate');
  }

  /** The row of this visit the caller's `group` stands for, with the provenance that ties them. */
  private loadedSuggestion(group: CullingGroup): { row: StackSuggestionRow; provenance: LoadedStackSuggestion } | undefined {
    if (!CullingStore.isSuggestionRow(group)) return;
    const provenance = this.suggestionProvenance.get(group);
    if (!provenance || provenance.epoch !== this.visitEpoch || provenance.membership !== this.suggestionMembership(group)) return;
    const row = this.groups().find(item => this.suggestionProvenance.get(item) === provenance
      && this.suggestionMembership(item) === provenance.membership);
    return row && CullingStore.isSuggestionRow(row) ? { row, provenance } : undefined;
  }

  private loadStackBatch(): Promise<void> {
    if (!this.stackVisitCurrent()) return Promise.resolve();
    if (this.stackBatchPending) return this.stackBatchPending;
    const epoch = this.visitEpoch;
    const generation = ++this.loadGenerationId;
    const refillVersion = this.stackRefillVersion;
    const completed = new Set<string>();
    this.stackBatchCompletions = completed;
    let refillRequired = false;
    this.loading.set(true);
    const run = (async () => {
      try {
        const result = await firstValueFrom(this.api.post<components['schemas']['StackSuggestionsResponse']>(
          '/stacks/suggestions', { filters: this.stackFilters(), include_photos: true }));
        if (!this.stackVisitCurrent(epoch) || generation !== this.loadGenerationId) return;
        const incoming: CullingGroup[] = result.suggestions.map(group => {
          if (!group.photos) throw new Error('Stack suggestion photos missing');
          const row: CullingGroup = {
            group_id: group.group_id, type: group.kind, best_path: group.cover_path,
            count: group.paths.length, reason: '', suggestionKey: group.key, photos: group.photos,
          };
          this.suggestionProvenance.set(row, { epoch, membership: this.suggestionMembership(row), rejected: signal(new Map<string, object>()) });
          return row;
        });
        // Undo can restore an earlier batch while this request is running. Retain it and dedupe by both identities.
        this.groups.update(retained => {
          const keys = new Set(retained.map(group => this.suggestionIdentity(group)));
          return [...retained, ...incoming.filter(group => {
            const key = this.suggestionIdentity(group);
            if (keys.has(key) || completed.has(key)) return false;
            keys.add(key);
            return true;
          })];
        });
        this.shareStackExclusions();
        this.totalGroups.set(this.groups().length);
        this.totalPages.set(1);
        this.currentPage.set(1);
        this.batchFull.set(result.suggestions.length >= STACK_SUGGESTION_MAX
          || result.suggestions.reduce((count, group) => count + group.paths.length, 0) >= STACK_SUGGESTION_MAX_PHOTOS);
        this.selectionsMap.set(new Map());
        refillRequired = this.groups().length === 0 && refillVersion !== this.stackRefillVersion;
      } catch (error) {
        if (this.stackVisitCurrent(epoch) && generation === this.loadGenerationId) {
          this.stackScopeInvalid.set((error as { status?: number } | null)?.status === 422);
          this.notice$.next({ key: I18N.stacks.suggestions_error, duration: 2000 });
        }
      } finally {
        if (epoch === this.visitEpoch && generation === this.loadGenerationId) {
          this.loading.set(false);
          this.stackBatchPending = null;
          this.stackBatchCompletions = null;
          if (refillRequired) void this.loadStackBatch();
        }
      }
    })();
    this.stackBatchPending = run;
    return run;
  }

  async stackSuggestion(group: CullingGroup, coverPath: string): Promise<boolean> {
    const loaded = this.loadedSuggestion(group)?.row;
    if (!loaded || !loaded.photos.some(photo => photo.path === coverPath)) return false;
    const epoch = this.visitEpoch;
    const rootSession = this.stackSession;
    const session = () => this.stackVisitCurrent(epoch) && !!rootSession && rootSession();
    const paths = loaded.photos.filter(photo => !this.stackExcluded()[photo.path]).map(photo => photo.path);
    if (paths.length < 2) return false;
    coverPath = paths.includes(coverPath) ? coverPath : paths.includes(loaded.best_path) ? loaded.best_path : paths[0];
    return this.decideStackSuggestion(loaded, () => this.stackActions.commit(this.stacks.create(paths, coverPath), {
      paths, action: 'create', session, live: session,
      labelKey: I18N.stacks.stacked, labelParams: { count: paths.length },
      onUndone: () => this.restoreStackSuggestion(loaded),
    }));
  }

  reviewDraft(group: CullingGroup): StackReviewDraft {
    const epoch = this.visitEpoch;
    const provenance = this.suggestionProvenance.get(group);
    const live = () => this.stackVisitCurrent(epoch) && !!this.loadedSuggestion(group);
    return {
      current: live,
      excluded: computed(() => new Set(group.photos.filter(photo => this.stackExcluded()[photo.path]).map(photo => photo.path))),
      lock: () => {
        if (!live() || this.stackBusy() || this.stackDecisions.size > 0) return false;
        this.stackBusy.set(true); return true;
      },
      unlock: () => { if (this.stackVisitCurrent(epoch)) this.stackBusy.set(false); },
      exclude: path => {
        if (!live() || !provenance || !group.photos.some(photo => photo.path === path)) throw new Error('Stack draft expired');
        const token = {};
        provenance.rejected.update(rejected => new Map(rejected).set(path, token));
        this.shareStackExclusions();
        return () => {
          if (!live() || provenance.rejected().get(path) !== token) return;
          for (const owner of new Set([provenance, ...this.groups().map(item => this.suggestionProvenance.get(item))])) {
            if (owner?.rejected().get(path) === token) {
              owner.rejected.update(rejected => { const next = new Map(rejected); next.delete(path); return next; });
            }
          }
        };
      },
    };
  }

  /** Undo can restore a previous batch beside a newer overlapping detector proposal. */
  private shareStackExclusions(): void {
    const rejected = new Map<string, object>();
    for (const group of this.groups()) {
      const owner = this.suggestionProvenance.get(group);
      if (owner) for (const [path, token] of owner.rejected()) rejected.set(path, token);
    }
    if (!rejected.size) return;
    for (const group of this.groups()) {
      const owner = this.suggestionProvenance.get(group);
      if (!owner) continue;
      const missing = group.photos.filter(photo => rejected.has(photo.path) && !owner.rejected().has(photo.path));
      if (missing.length) owner.rejected.update(current => {
        const next = new Map(current);
        for (const photo of missing) next.set(photo.path, rejected.get(photo.path)!);
        return next;
      });
    }
  }

  async rejectStackPhoto(group: CullingGroup, path: string): Promise<boolean> {
    const loaded = this.loadedSuggestion(group)?.row;
    if (!loaded || this.stackBusy() || this.stackDecisions.has(this.suggestionIdentity(loaded)) || this.stackExcluded()[path] || !loaded.photos.some(photo => photo.path === path)) return false;
    const draft = this.reviewDraft(loaded);
    if (!draft.lock()) return false;
    try {
      return await this.reviewActions.reject(path, {
        session: draft.current, live: draft.current,
        beginUndo: () => !draft.current() || draft.lock(),
        endUndo: draft.unlock,
        exclude: () => draft.exclude(path),
      });
    } catch {
      if (draft.current()) this.notice$.next({ key: I18N.stacks.suggestion_failed, duration: 2000 });
      return false;
    } finally { draft.unlock(); }
  }

  async skipSuggestion(group: CullingGroup): Promise<boolean> {
    const loaded = this.loadedSuggestion(group)?.row;
    if (!loaded) return false;
    const epoch = this.visitEpoch;
    const session = this.stackSession;
    return this.decideStackSuggestion(loaded, async () => {
      await firstValueFrom(this.stacks.dismissSuggestion(loaded.type, loaded.photos.map(photo => photo.path)));
      if (!this.stackVisitCurrent(epoch) || !session) return;
      this.undo.register({
        labelKey: I18N.stacks.suggestion_skipped,
        undo: async () => {
          this.stacks.assertLive(() => this.stackVisitCurrent(epoch) && session());
          await firstValueFrom(this.stacks.restoreSuggestion(loaded.suggestionKey));
          this.stacks.assertLive(() => this.stackVisitCurrent(epoch) && session());
          this.restoreStackSuggestion(loaded);
        },
      });
    });
  }

  private async decideStackSuggestion(group: CullingGroup, write: () => Promise<unknown>): Promise<boolean> {
    const epoch = this.visitEpoch;
    const key = this.suggestionIdentity(group);
    if (!this.stackVisitCurrent(epoch) || this.stackBusy() || this.stackDecisions.has(key)) return false;
    this.stackDecisions.add(key);
    try {
      const committed = await write();
      if (committed === false || !this.stackVisitCurrent(epoch)) return false;
      return this.completeStackSuggestion(group);
    } catch {
      if (this.stackVisitCurrent(epoch)) this.notice$.next({ key: I18N.stacks.suggestion_failed, duration: 2000 });
      return false;
    } finally {
      if (epoch === this.visitEpoch) this.stackDecisions.delete(key);
    }
  }

  /** Editor save consumes only the group captured when that editor opened. */
  completeStackSuggestion(group: CullingGroup): boolean {
    if (!this.stackVisitCurrent()) return false;
    const loaded = this.loadedSuggestion(group);
    if (!loaded) return false;
    const { row, provenance } = loaded;
    this.completedSuggestions.set(provenance, row);
    this.stackBatchCompletions?.add(this.suggestionIdentity(row));
    this.groups.update(groups => groups.filter(item => item !== row));
    this.totalGroups.set(this.groups().length);
    if (this.groups().length === 0) {
      this.stackRefillVersion++;
      void this.loadStackBatch();
    }
    return true;
  }

  /** Undo remains valid across batch requests, but never across visits or accounts. */
  restoreStackSuggestion(group: CullingGroup): void {
    const provenance = this.suggestionProvenance.get(group);
    if (!this.stackVisitCurrent() || !provenance || provenance.epoch !== this.visitEpoch
      || provenance.membership !== this.suggestionMembership(group)) return;
    const completed = this.completedSuggestions.get(provenance);
    if (!completed || this.suggestionMembership(completed) !== provenance.membership) return;
    if (!this.groups().some(item => this.suggestionIdentity(item) === this.suggestionIdentity(completed))) {
      this.groups.update(groups => [completed, ...groups]);
    }
    this.shareStackExclusions();
    this.totalGroups.set(this.groups().length);
    this.completedSuggestions.delete(provenance);
  }

  constructor() {
    // Lets `ui_show_culling_plan` refuse to replace what this visit's user has decided but not committed.
    // In plan mode the committed groups are the assistant's to re-plan, so only a commit in flight counts.
    const destroyRef = inject(DestroyRef);
    destroyRef.onDestroy(this.plan.registerDecisionsProbe(() => this.cullWritesAllowed() && (this.planActive()
      ? this.passingGroups().size > 0 || this.confirming()
      : this.hasUncommittedDecisions())));
    destroyRef.onDestroy(this.plan.registerClosedGroupsProbe(() => this.cullWritesAllowed() ? this.closedGroupKeys() : new Set()));
    destroyRef.onDestroy(() => { this.visitEpoch++; this.cancelReplan(); });
  }

  /** The assistant's suggestions on the plan on screen (the service stays private to the store). */
  readonly suggestions = this.plan.suggestions;

  /** True while the darkroom shows the assistant's plan instead of the feed. */
  readonly planActive = signal(false);
  /** Digest of the plan on screen (or loading); lets the page tell a new pin from the one it already holds. */
  readonly planDigest = signal<string | null>(null);
  /** Groups the plan left out because one exceeds the confirm route's photo cap. */
  readonly planOversize = signal(0);
  /** The whole plan as loaded; `groups` shows a growing prefix of it. */
  private planAll: CullingGroup[] = [];
  /** The pending slider re-plan (`scheduleReplan`), null when none is waiting. */
  private replanTimer: ReturnType<typeof setTimeout> | null = null;
  /** Bumped by every re-plan, by a newer slider move and by leaving or replacing the plan: a re-plan whose ticket moved drops its answer. */
  private replanSeq = 0;
  /** The slider and preset the plan on screen was computed with: what a failed re-plan puts back. */
  private previousPlanStrictness = CULL_DEFAULT_STRICTNESS;
  private previousPlanProfile = '';
  /** The window and scene label the plan on screen was computed for: what a failed re-plan puts back. */
  private previousPlanFrom: string | null = null;
  private previousPlanTo: string | null = null;
  private previousPlanScene: string | null = null;
  /** The shown plan was computed with an explicit strictness: a preset loading later must not move the slider off it. */
  private planHasStrictness = false;
  /** True from a re-plan's flush until its answer lands or fails: confirm, skip and "confirm all" are paused. */
  private readonly replanningState = signal(false);
  readonly replanning = this.replanningState.asReadonly();
  /** Confirm commits (and "confirm all" runs) on their way to the server; a re-plan waits for them so the new plan already leaves those groups out. */
  private readonly inFlightCommits = new Set<Promise<void>>();

  /**
   * An assistant write the loaded feed cannot absorb (a filter-scoped write, a cull move) landed while
   * the user held decisions a reload would discard. Persistent state rather than a snackbar: the next
   * batch's notice would replace a snackbar and lose the only way to apply the write. Cleared by any
   * full reload of the feed.
   */
  readonly pendingReload = signal(false);
  /** Messages for the component to show (error and success toasts). */
  readonly notice$ = new Subject<CullingNotice>();

  /** Granularity served by the feed: all (merged burst+similar) | burst | similar | scene. */
  readonly groupBy = signal<GroupBy>(readStoredGroupBy());

  // Optional scope from "Cull this scene" / album entry points (query params).
  readonly scopeAlbum = signal<string | null>(null);
  readonly scopeFrom = signal<string | null>(null);
  readonly scopeTo = signal<string | null>(null);
  readonly scopeScene = signal<string | null>(null);
  /** A capture-date window narrows the feed (alone or on top of an album). */
  readonly dateRangeActive = computed(() => !!(this.scopeFrom() || this.scopeTo()));
  readonly albums = signal<Album[]>([]);
  readonly scopeAlbumName = computed(() =>
    AlbumService.nameById(this.albums(), this.scopeAlbum()));
  /** Human label for the scope button / banner (null = whole library). */
  readonly albumScopeLabel = computed(() => {
    const album = this.scopeAlbumName();
    const scene = this.scopeScene();
    if (album && scene) return `${album} · ${scene}`;
    return album ?? scene ?? null;
  });
  /** The scope as a whole (album, scene, else the date range): names the highlights album. */
  readonly scopeLabel = computed(() =>
    this.albumScopeLabel() ?? (this.dateRangeActive() ? new CullDateRangePipe().transform(this.scopeFrom(), this.scopeTo()) : null));

  /** The darkroom lightbox's current photo, mirrored by the component for `ui_get_context`; null when no lightbox is open. */

  // Personal-ranker status, surfaced as the "this cull trains My Taste" chip.
  readonly rankerComparisons = signal<number | null>(null);
  readonly rankerTrained = signal(false);
  /** Per-category comparison counts + threshold, for the weight-tuning chip. */
  readonly comparisonStats = signal<ComparisonStats | null>(null);

  readonly similarityThreshold = signal(85);
  private readonly strictnessState = signal(readStoredStrictness());
  /** Auto-keep strictness (0-100): higher keeps fewer photos below the best. Written only through `setStrictness`. */
  readonly strictness = this.strictnessState.asReadonly();
  readonly excludeRejected = signal(true);
  /** Server-side ordering of culling groups. */
  readonly sortMode = signal(readStoredSort());
  /** Explicit sort direction; '' leaves each mode its natural one. */
  readonly sortDirection = signal<'' | 'asc' | 'desc'>(readStoredSortDirection());

  /** Genre culling presets (GET /api/culling/profiles). */
  readonly cullProfiles = signal<CullProfile[]>([]);

  readonly groups = signal<CullingGroup[]>([]);
  readonly totalGroups = signal(0);
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly currentPage = signal(1);
  readonly totalPages = signal(1);
  readonly hasMore = computed(() => this.cullWritesAllowed() && this.currentPage() < this.totalPages());

  /** groupKey -> set of kept paths (ids collide across types, so the type is part of the key) */
  readonly selectionsMap = signal<Map<string, Set<string>>>(new Map());
  /** Set of confirmed group keys (group_id + '_' + type) */
  readonly confirmedGroups = signal<Set<string>>(new Set());

  /** Seconds a skipped group stays cancellable before it is hidden. */
  readonly passCountdownSeconds = 7;
  /** Map of group key -> remaining countdown seconds for groups being passed */
  readonly passingGroups = signal<Map<string, number>>(new Map());
  /** Set of group keys hidden after pass timeout */
  readonly hiddenGroups = signal<Set<string>>(new Set());
  /**
   * Group keys the user has decided something in (a keep toggle, an exclusive pick, a confirm or skip).
   * `loadGroups` seeds `selectionsMap` with the auto-selection, so that map is never empty and cannot
   * tell "the user decided" from "the machine decided".
   */
  readonly touchedGroups = signal<Set<string>>(new Set());
  /** Keys of groups no decision can change any more: confirmed, counting down to a confirm or skip, or hidden. */
  readonly closedGroupKeys = computed(() => new Set([
    ...this.confirmedGroups(), ...this.passingGroups().keys(), ...this.hiddenGroups(),
  ]));
  readonly confirming = signal(false);

  /** Group keys in the feed carrying a correction the detector has not applied yet. */
  readonly pendingCorrectionKeys = computed(
    () => new Set(this.groups()
      .filter(g => g.photos.some(p => p.sequence_override && p.sequence_override_pending))
      .map(g => this.groupKey(g))),
  );

  /**
   * Corrections dropped this session that the detector had already applied.
   *
   * Dropping a still-pending correction needs no re-run: the detector never
   * touched `photos` for it. But dropping an APPLIED one (`sequence_override`
   * set, not pending) leaves the forced set sitting in `photos` until the
   * detector runs again -- and by then `pendingCorrectionKeys` sees nothing, so
   * the re-run banner would never appear without this counter.
   *
   * A key is only ever removed here by a successful re-run (see
   * `pollDetection`): the group may still be pending again in the meantime
   * (re-marked) or no longer pending (undone), but in either case `photos`
   * still holds the stale applied set until the detector runs, so the key
   * must stay recorded regardless of what happens to the pending correction.
   */
  readonly droppedApplied = signal<Set<string>>(new Set());

  /** Groups needing a re-run: the union of still-pending corrections and applied
   *  ones dropped this session. A group that is both pending and dropped counts
   *  once, and keeps counting even after its pending correction is cleared or
   *  re-marked away, because `droppedApplied` is never trimmed by that. */
  readonly rerunNeeded = computed(
    () => new Set([...this.pendingCorrectionKeys(), ...this.droppedApplied()]).size);

  /** Active timers for passing groups (for cleanup) */
  private readonly passTimers = new Map<string, { timeoutId: ReturnType<typeof setTimeout>; intervalId: ReturnType<typeof setInterval>; onElapsed: () => Promise<void> | void; commit: boolean }>();

  /** Active preset id ('' = custom / none). Persisted; re-applied on open. */
  readonly selectedProfile = signal<string>(localStorage.getItem(CULL_PROFILE_KEY) ?? '');
  /** The preset the current scope's own content argues for
   *  (GET /culling/suggest_profile), or null while none was inferred. */
  readonly profileSuggestion = signal<ProfileSuggestion | null>(null);
  /** Set the moment the user picks a preset or moves a knob — including a
   *  choice restored from a previous session. A manual choice is never
   *  overwritten by a suggestion for the rest of the session. */
  readonly profileChosen = signal(false);
  /** The scope the cached suggestion answers for; a scope change refetches. */
  private suggestionScopeKey: string | null = null;
  private suggestionApplied = false;

  /** Dry-run result of POST /culling/auto shown in the confirm dialog (null = closed). */
  readonly autoCullPreview = signal<AutoCullResponse | null>(null);
  /** The dry-run body the preview on screen was computed from, set with it and
   *  never re-derived: Apply re-sends this verbatim (dry_run flipped) so the
   *  counts the user agreed to and the knobs that run cannot diverge. A
   *  suggestion applying a preset mid-flight used to move strictness and the
   *  profile between the request and its answer, and the apply then read the
   *  moved signals. */
  readonly autoCullRequest = signal<AutoCullRequest | null>(null);
  /** Bumped per dry run, so a superseded one can never publish over a newer
   *  preview — the pair above must always describe the same run. */
  readonly autoCullRun = new RunGeneration();
  /** True between a dry run's request and its answer. A suggestion landing in
   *  that window has to re-run too: the dialog is not open yet, so waiting on
   *  `autoCullPreview` would have opened it on counts from the knobs the
   *  suggestion just replaced. */
  dryRunInFlight = false;
  /** True while any auto-cull request is in flight (dry run or apply): it drives
   *  the dialog's spinner and disables the knobs that would re-run it. */
  readonly autoCullLoading = signal(false);
  /** True while the *destructive* apply is in flight — the one request that
   *  cannot be abandoned. Every dismissal path (Cancel, backdrop, Escape) is
   *  ignored for its duration and Apply refuses to fire twice, because
   *  dismissing mid-flight re-armed Apply over a snapshot already being applied,
   *  and the apply's own close then bumped the dry-run generation over the run
   *  the reopened dialog was waiting on. */
  readonly autoCullApplying = signal(false);
  /** What the dialog actually renders busy. Not `autoCullLoading` alone: a dry
   *  run that a profile suggestion started behind the apply clears that flag
   *  when it lands, which would drop the spinner and re-arm the knobs while the
   *  destructive request is still open. */
  readonly autoCullBusy = computed(() => this.autoCullLoading() || this.autoCullApplying());
  /** Whether the apply also fills the Highlights album (dialog checkbox, opt-in). */
  readonly autoCullHighlights = signal(false);
  /** Whether auto-cull also proposes trimming redundant, non-clipping bracket
   *  exposures (dialog checkbox); toggling re-runs the dry run since it
   *  changes the preview's group/keep/reject counts. */
  readonly trimBrackets = signal(false);
  /** Translated preset name whose suggestion re-ran an already-open dialog's
   *  preview — the counts changed under the user, so the dialog says why. */
  readonly autoCullSuggestionNotice = signal<string | null>(null);
  /** True when trimming brackets returned the very same counts: without this the
   *  toggle looks broken, since a re-run that changes nothing is silent. */
  readonly trimBracketsUnchanged = signal(false);


  /** Monotonic id bumped on every filter change; loadGroups/loadMore drop late responses whose generation no longer matches. */
  private loadGenerationId = 0;
  private readonly similarSeed = Math.floor(Math.random() * 1_000_000);

  groupKey(group: CullingGroup): string {
    return cullingGroupKey(group);
  }

  buildParams(page: number): Record<string, string | number | boolean> {
    const params: Record<string, string | number | boolean> = {
      page,
      per_page: CULL_PAGE_SIZE,
      similarity_threshold: (this.similarityThreshold() / 100).toString(),
      seed: this.similarSeed,
      exclude_rejected: this.excludeRejected(),
      sort: this.sortMode(),
      direction: this.sortDirection(),
      group_by: this.groupBy(),
    };
    return Object.assign(params, this.scopeParams());
  }

  /** The scope as request params: the one place that decides an empty album or date is left out. */
  private scopeParams(): { album_id?: string; date_from?: string; date_to?: string } {
    const album = this.scopeAlbum();
    const from = this.scopeFrom();
    const to = this.scopeTo();
    return { ...(album ? { album_id: album } : {}), ...(from ? { date_from: from } : {}), ...(to ? { date_to: to } : {}) };
  }

  /** The same scope for the endpoints that take the album as a number. */
  private numericScopeParams(): { album_id?: number; date_from?: string; date_to?: string } {
    const { album_id, ...dates } = this.scopeParams();
    return { ...(album_id ? { album_id: Number(album_id) } : {}), ...dates };
  }

  /** Drop the loaded feed and its per-feed decisions, invalidating any load in flight. */
  resetFeed(): void {
    this.loadGenerationId++;
    if (this.mode() === 'stacks') {
      // A reset supersedes the request, not the visit: its Undo commands remain valid.
      this.stackBatchPending = null;
      this.loading.set(false);
    }
    // The superseded loadMore's finally no longer matches the generation, so it will not clear this itself.
    this.loadingMore.set(false);
    this.pendingReload.set(false);
    this.currentPage.set(1);
    this.groups.set([]);
    this.confirmedGroups.set(new Set());
    this.selectionsMap.set(new Map());
    this.touchedGroups.set(new Set());
  }

  /** Reload the feed from page 1 under the current filters. */
  resetForReload(): void {
    this.dropPlan();
    this.resetFeed();
    this.clearAllPassTimers();
    void this.loadGroups();
  }

  async loadGroups(): Promise<void> {
    if (this.mode() === 'stacks') return this.groups().length === 0 ? this.loadStackBatch() : undefined;
    this.dropPlan();
    const gen = this.loadGenerationId;
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<CullingGroupsResponse>('/culling-groups', this.buildParams(1)),
      );
      if (gen !== this.loadGenerationId) return;
      this.groups.set(data.groups);
      this.totalGroups.set(data.total_groups);
      this.totalPages.set(data.total_pages);
      this.currentPage.set(1);
      this.selectionsMap.set(this.autoSelectBest(data.groups));
    } catch {
      if (gen !== this.loadGenerationId) return;
      this.notice$.next({ key: I18N.culling.error_loading, duration: 2000 });
    } finally {
      if (gen === this.loadGenerationId) this.loading.set(false);
    }
  }

  async loadMore(): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    if (!this.hasMore() || this.loadingMore()) return;
    if (this.planActive()) {
      // The plan arrived whole; revealing is a slice, so a shown group never moves under the user.
      const nextPage = this.currentPage() + 1;
      this.groups.update(existing => [...existing, ...this.planAll.slice(existing.length, nextPage * CULL_PAGE_SIZE)]);
      this.currentPage.set(nextPage);
      return;
    }
    const gen = this.loadGenerationId;
    this.loadingMore.set(true);
    try {
      const nextPage = this.currentPage() + 1;
      const data = await firstValueFrom(
        this.api.get<CullingGroupsResponse>('/culling-groups', this.buildParams(nextPage)),
      );
      if (gen !== this.loadGenerationId) return;
      this.groups.update(existing => [...existing, ...data.groups]);
      this.totalPages.set(data.total_pages);
      this.currentPage.set(nextPage);
      this.selectionsMap.set(this.autoSelectBest(data.groups, this.selectionsMap()));
    } catch {
      if (gen !== this.loadGenerationId) return;
      this.notice$.next({ key: I18N.culling.error_loading, duration: 2000 });
    } finally {
      if (gen === this.loadGenerationId) this.loadingMore.set(false);
    }
  }

  /**
   * Enter plan mode: reproduce the assistant's plan through `POST /culling/plan` and show it as the feed.
   *
   * Scope and granularity come from the request (the URL-driven feed load is skipped); selections are seeded
   * from each group's `plan.keep_paths`, never from `autoSelectBest`. A 412 means the library moved since the
   * assistant previewed: the pin is dropped, the user is told, and the manual feed loads instead.
   */
  async enterPlan(pin: CullPlanPin): Promise<CullPlanLoadOutcome> {
    if (!this.cullWritesAllowed()) return 'superseded';
    // A new pin supersedes a re-plan the slider queued (or started) for the previous one.
    this.cancelReplan();
    this.resetFeed();
    this.clearAllPassTimers();
    const gen = this.loadGenerationId;
    this.planAll = [];
    this.planActive.set(true);
    this.planDigest.set(pin.digest);
    this.planOversize.set(0);
    const { album_id: album, date_from: from, date_to: to, group_by: groupBy } = pin.request;
    this.scopeAlbum.set(album != null ? String(album) : null);
    this.scopeFrom.set(plainScopeDate(from, 'from'));
    this.scopeTo.set(plainScopeDate(to, 'to'));
    this.scopeScene.set(null);
    this.groupBy.set(groupBy ?? 'all');
    // Before the held-plan shortcut, so a re-mount puts the slider back on the plan's value too.
    this.adoptPlanKnobs(pin.request);
    const held = this.plan.heldPlan<CullingPlanResponse>(pin.digest);
    if (held) {
      this.showPlan(held.data, held.state);
      return 'landed';
    }
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.post<CullingPlanResponse>('/culling/plan', { ...pin.request, expected_digest: pin.digest }),
      );
      if (gen !== this.loadGenerationId) return 'superseded';
      this.showPlan(data, null);
      this.plan.hold(pin.digest, data);
      return 'landed';
    } catch (err) {
      if (gen !== this.loadGenerationId) return 'superseded';
      const outOfDate = (err as { status?: number } | null)?.status === 412;
      this.plan.recordLoadFailure(pin.digest, outOfDate ? 'out_of_date' : 'failed');
      this.notice$.next(outOfDate
        ? { key: I18N.culling.plan.out_of_date, duration: 4000 }
        : { key: I18N.culling.error_loading, duration: 2000 });
      void this.loadGroups();
      return outOfDate ? 'out_of_date' : 'failed';
    }
  }

  /**
   * Show a loaded plan as the feed. `state` is what the user left of an earlier visit (a re-mount): the
   * confirmed and skipped groups stay hidden, the confirmed ones count in the banner, and a flipped group
   * keeps its keepers. A fresh load passes null and registers the plan with the read model.
   *
   * `flips` are the user's open flips carried over from the plan a re-plan replaces. Group ids are not
   * stable across plans, so a flip is matched to a group by its photo set; it seeds that group's
   * selection and its read-model `current`. Returns how many flips matched no group (they are dropped).
   *
   * `confirmed` are the groups the user confirmed on that plan. A burst or similar group leaves the
   * re-plan (the server marks it reviewed); a scene group can come back, smaller when its rejected frames
   * drop out. A group whose photos all belong to one confirmed group is that group again: it comes back
   * confirmed and hidden with the user's keepers, as a confirm would leave it, and is not re-posted.
   */
  private showPlan(
    data: CullingPlanResponse,
    state: Map<string, { status: string; current: string[] }> | null,
    flips: CullPlanFlip[] = [],
    confirmed: CullPlanFlip[] = [],
  ): number {
    const flipsByPaths = new Map(flips.map(flip => [pathSetKey(flip.paths), flip]));
    const confirmedByPath = new Map(confirmed.flatMap(entry => entry.paths.map(path => [path, entry] as const)));
    const carried = new Map<string, string[]>();
    const carriedConfirmed = new Set<string>();
    const matched = new Set<CullPlanFlip>();
    for (const g of data.groups) {
      const paths = g.photos.map(p => p.path);
      const key = this.groupKey(g);
      const owner = paths.length > 0 ? confirmedByPath.get(paths[0]) : undefined;
      if (owner && paths.every(path => confirmedByPath.get(path) === owner)) {
        const own = new Set(paths);
        carried.set(key, owner.current.filter(path => own.has(path)));
        carriedConfirmed.add(key);
        continue;
      }
      const flip = flipsByPaths.get(pathSetKey(paths));
      if (!flip) continue;
      carried.set(key, flip.current);
      matched.add(flip);
    }
    this.planAll = data.groups;
    this.groups.set(data.groups.slice(0, CULL_PAGE_SIZE));
    this.totalGroups.set(data.total_groups);
    this.totalPages.set(Math.max(1, Math.ceil(data.groups.length / CULL_PAGE_SIZE)));
    this.currentPage.set(1);
    this.planOversize.set(data.oversize_groups);
    this.selectionsMap.set(new Map(data.groups.map(g => {
      const key = this.groupKey(g);
      const current = state?.get(key)?.current ?? carried.get(key);
      return [key, new Set(current ?? g.plan?.keep_paths ?? [])];
    })));
    if (state) {
      const done = (status: string) => data.groups.map(g => this.groupKey(g)).filter(key => state.get(key)?.status === status);
      const confirmed = done('confirmed');
      this.confirmedGroups.set(new Set(confirmed));
      this.hiddenGroups.set(new Set([...confirmed, ...done('skipped')]));
      this.touchedGroups.set(new Set(this.hiddenGroups()));
    } else {
      this.plan.register(
        data.groups.map(g => ({
          key: this.groupKey(g),
          type: g.type,
          group_id: g.group_id,
          number: g.plan?.number ?? 0,
          paths: g.photos.map(p => p.path),
          keep_paths: g.plan?.keep_paths ?? [],
          ...(carried.has(this.groupKey(g)) ? { current_paths: carried.get(this.groupKey(g)) } : {}),
          ...(carriedConfirmed.has(this.groupKey(g)) ? { confirmed: true } : {}),
        })),
        { total: data.total_groups, truncated: data.truncated },
      );
      if (carriedConfirmed.size > 0) {
        this.confirmedGroups.update(s => new Set([...s, ...carriedConfirmed]));
        this.hiddenGroups.update(s => new Set([...s, ...carriedConfirmed]));
        this.touchedGroups.update(s => new Set([...s, ...carriedConfirmed]));
      }
    }
    this.loading.set(false);
    return flipsByPaths.size - matched.size;
  }

  /**
   * Put the slider (and the stored preset) on the knobs a shown plan was computed with. Signals and
   * localStorage only: going through `applyProfile` would reload the feed, ending the plan, whenever the
   * preset's similarity threshold differs. Never re-plans.
   */
  private adoptPlanKnobs(request: CullPlanRequest): void {
    // Both are stored when both were given: strictness beats the preset's own server-side, while the preset
    // still supplies its other knobs (the keeper floor), and a later no-knob `auto_cull` uses the pair.
    if (request.profile) {
      this.selectedProfile.set(request.profile);
      localStorage.setItem(CULL_PROFILE_KEY, request.profile);
      this.profileChosen.set(true);
    }
    if (request.strictness != null) {
      this.setStrictness(request.strictness);
      this.profileChosen.set(true);
      if (!request.profile) this.clearProfileSelection();
    } else if (request.profile) {
      // Presets not loaded yet: `loadCullProfiles` moves the slider once they are.
      const profile = this.cullProfiles().find(p => p.id === request.profile);
      if (profile?.strictness != null) this.setStrictness(profile.strictness);
    }
    this.planHasStrictness = request.strictness != null;
    this.previousPlanStrictness = this.strictness();
    this.previousPlanProfile = this.selectedProfile();
    this.previousPlanFrom = this.scopeFrom();
    this.previousPlanTo = this.scopeTo();
    this.previousPlanScene = this.scopeScene();
  }

  /**
   * Narrow the feed to a capture-date window (null/null = all dates), keeping the album. A plan is
   * recomputed for the new window like a slider move; the manual feed reloads. The scene label goes:
   * it names a window that no longer applies.
   */
  setDateRange(from: string | null, to: string | null): void {
    if (from === this.scopeFrom() && to === this.scopeTo()) return;
    this.resetProfileSuggestion();
    this.scopeFrom.set(from);
    this.scopeTo.set(to);
    this.scopeScene.set(null);
    if (this.planActive()) this.scheduleReplan();
    else this.resetForReload();
  }

  /** The slider moved while a plan is shown: recompute the plan once it settles. */
  scheduleReplan(): void {
    if (!this.cullWritesAllowed()) return;
    if (!this.planActive()) return;
    if (this.replanTimer !== null) clearTimeout(this.replanTimer);
    // A re-plan already in flight answers for a value the user has moved away from.
    this.replanSeq++;
    this.replanTimer = setTimeout(() => {
      this.replanTimer = null;
      void this.replan();
    }, CULL_REPLAN_DEBOUNCE_MS);
  }

  /** Drop a queued re-plan and orphan one in flight. */
  private cancelReplan(): void {
    if (this.replanTimer !== null) clearTimeout(this.replanTimer);
    this.replanTimer = null;
    this.replanSeq++;
    this.replanningState.set(false);
  }

  /**
   * Recompute the shown plan at the slider's strictness: the pin's request with only the knobs changed,
   * and no digest (there is none to verify for a plan nobody has seen yet). Pending confirms and skips are
   * committed first, so the server already leaves the confirmed groups out. The old plan stays on screen
   * until the new one lands; the user's open flips and confirmed groups are carried over by photo set.
   * Confirm, skip and "confirm all" are paused (`replanning`) from the flush until the answer lands, so no
   * decision is made against a plan about to be replaced. A failure keeps the old plan and puts the slider
   * (and the preset) back.
   */
  async replan(): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    const seq = ++this.replanSeq;
    const pin = this.plan.pin();
    const startDigest = this.planDigest();
    if (!this.planActive() || !pin || pin.digest !== startDigest) {
      this.replanningState.set(false);
      return;
    }
    this.replanningState.set(true);
    try {
      await this.runReplan(seq, pin, startDigest);
    } finally {
      // A newer re-plan owns the flag; a cancelled one already cleared it.
      if (seq === this.replanSeq) this.replanningState.set(false);
    }
  }

  private async runReplan(seq: number, pin: CullPlanPin, startDigest: string | null): Promise<void> {
    const prev = {
      strictness: this.previousPlanStrictness, profile: this.previousPlanProfile,
      from: this.previousPlanFrom, to: this.previousPlanTo, scene: this.previousPlanScene,
    };
    await this.flushPassTimers();
    if (!this.cullWritesAllowed() || seq !== this.replanSeq || !this.planActive()) return;
    // The pin's preset stays: the explicit strictness wins over its own server-side, and it still supplies
    // the preset's other knobs (a wedding preset's two keepers per group).
    // The dates are `null`, not omitted, so All dates clears a window the pin carried.
    const request: CullPlanRequest = {
      ...pin.request, date_from: this.scopeFrom(), date_to: this.scopeTo(), strictness: this.strictness(),
    };
    let data: CullingPlanResponse;
    try {
      data = await firstValueFrom(this.api.post<CullingPlanResponse>('/culling/plan', request));
    } catch {
      if (seq !== this.replanSeq) return;
      this.setStrictness(prev.strictness);
      this.scopeFrom.set(prev.from);
      this.scopeTo.set(prev.to);
      this.scopeScene.set(prev.scene);
      this.selectedProfile.set(prev.profile);
      if (prev.profile) localStorage.setItem(CULL_PROFILE_KEY, prev.profile);
      else localStorage.removeItem(CULL_PROFILE_KEY);
      this.notice$.next({ key: I18N.culling.error_loading, duration: 2000 });
      return;
    }
    if (seq !== this.replanSeq || !this.planActive() || this.planDigest() !== startDigest
      || this.plan.pin()?.digest !== startDigest) return;
    // Read at landing, not before the request: a flip made while it was in flight counts too.
    const flips = this.plan.openFlips();
    const confirmed = this.plan.confirmedEntries();
    const depth = this.groups().length;
    // The digest first, so the page's pin follower sees the new pin as the plan it already holds.
    this.planDigest.set(data.plan_digest);
    this.plan.setPin({ digest: data.plan_digest, request });
    this.plan.hold(data.plan_digest, data);
    // The old plan's feed is gone. No cooldown or commit is left to land on it -- the flush committed
    // them and `replanning` kept new ones from starting -- but a stale generation must still never hide or
    // journal a group of the new plan that reuses its key (similar-group ids are positional).
    this.loadGenerationId++;
    this.confirmedGroups.set(new Set());
    this.hiddenGroups.set(new Set());
    this.touchedGroups.set(new Set());
    const dropped = this.showPlan(data, null, flips, confirmed);
    this.planHasStrictness = true;
    // Keep the depth the user had paged to; never slice the plan itself.
    while (this.groups().length < depth && this.hasMore()) await this.loadMore();
    this.previousPlanStrictness = this.strictness();
    this.previousPlanProfile = this.selectedProfile();
    this.previousPlanFrom = this.scopeFrom();
    this.previousPlanTo = this.scopeTo();
    this.previousPlanScene = this.scopeScene();
    if (dropped > 0) {
      this.notice$.next({ key: I18N.culling.plan.replan_flips_dropped, params: { count: dropped }, duration: 4000 });
    }
  }

  /** Leave plan mode if in it: the plan, its pin and its read model go; the caller reloads the feed. */
  private dropPlan(): void {
    this.cancelReplan();
    if (!this.planActive()) return;
    this.planActive.set(false);
    this.planDigest.set(null);
    this.planOversize.set(0);
    this.planAll = [];
    this.plan.clear();
  }

  /** Tell the plan's read model about a group's keepers; a no-op outside plan mode. */
  private reportSelection(key: string, kept: Iterable<string>): void {
    if (this.planActive()) this.plan.recordSelection(key, kept);
  }

  /** Fetch the genre presets; null when the list cannot load. */
  async fetchCullProfiles(): Promise<CullProfile[] | null> {
    if (!this.cullWritesAllowed()) return null;
    try {
      const gen = this.loadGenerationId;
      const data = await firstValueFrom(this.api.get<CullProfilesResponse>('/culling/profiles'));
      if (!this.cullLoadCurrent(gen)) return null;
      return data.profiles ?? [];
    } catch {
      return null;
    }
  }

  /** Fetch per-category comparison counts + threshold for the weight-tuning chip. */
  async refreshComparisonStats(): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    const gen = this.loadGenerationId;
    try {
      const stats = await firstValueFrom(this.api.get<ComparisonStats>('/comparison/stats'));
      if (this.cullLoadCurrent(gen)) this.comparisonStats.set(stats);
    } catch {
      // Best-effort: the chip simply stays hidden if stats are unavailable.
    }
  }

  /** Fetch personal-ranker status for the "trains My Taste" chip (best-effort). */
  async refreshRankerStatus(): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    const gen = this.loadGenerationId;
    try {
      const s = await firstValueFrom(
        this.api.get<{ trained: boolean; comparison_count: number }>('/ranker/status'),
      );
      if (!this.cullLoadCurrent(gen)) return;
      this.rankerTrained.set(!!s.trained);
      this.rankerComparisons.set(s.comparison_count ?? null);
    } catch {
      // The chip is a nice-to-have; ignore status failures.
    }
  }

  private autoSelectBest(groups: CullingGroup[], base?: Map<string, Set<string>>): Map<string, Set<string>> {
    const map = base ? new Map(base) : new Map<string, Set<string>>();
    for (const group of groups) {
      const key = this.groupKey(group);
      if (!map.has(key)) {
        const kept = this.computeAutoKeep(group);
        if (kept.size > 0) {
          map.set(key, kept);
        }
      }
    }
    return map;
  }

  /**
   * Derive the auto-keep set for a group from the current strictness (0-100).
   * The best photo is always kept; additional photos whose burst_score falls
   * within a strictness-derived margin of the best are also kept. At strictness
   * 100 only the single best survives; at 0 everything within ~5 points stays.
   *
   * A bracket or a panorama is the exception and starts fully kept whatever the
   * strictness: their frames were shot to be merged, not to compete, so
   * proposing to drop the flanking exposures or half a sweep would be proposing
   * to destroy the set. Trimming a bracket stays available deliberately,
   * through auto-cull's `trim_brackets`, which first checks the base exposure
   * clips nothing.
   */
  private computeAutoKeep(group: CullingGroup): Set<string> {
    if (group.sequence_kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(group.sequence_kind)) {
      return new Set<string>(group.photos.map(p => p.path));
    }
    const best = group.best_path || group.photos[0]?.path;
    if (!best) return new Set<string>();
    const kept = new Set<string>([best]);

    const bestScore = group.photos.find(p => p.path === best)?.burst_score
      ?? Math.max(0, ...group.photos.map(p => p.burst_score));
    // strictness 100 -> margin 0 (only the best); strictness 0 -> margin 5.
    const margin = (100 - this.strictness()) / 100 * 5;
    if (margin > 0) {
      for (const photo of group.photos) {
        if (bestScore - photo.burst_score <= margin) {
          kept.add(photo.path);
        }
      }
    }
    return kept;
  }

  /**
   * Re-derive the auto-keep selection for every loaded group from the current
   * strictness. Purely client-side over the burst_score values already
   * returned — no backend round-trip. Confirmed groups are left untouched.
   */
  reselectFromStrictness(): void {
    if (!this.cullWritesAllowed()) return;
    // The plan's keepers are the assistant's decision, not a strictness derivation.
    if (this.planActive()) return;
    const confirmed = this.confirmedGroups();
    const map = new Map<string, Set<string>>();
    for (const group of this.groups()) {
      const key = this.groupKey(group);
      if (confirmed.has(key)) {
        const existing = this.selectionsMap().get(key);
        if (existing) map.set(key, existing);
        continue;
      }
      const kept = this.computeAutoKeep(group);
      if (kept.size > 0) map.set(key, kept);
    }
    this.selectionsMap.set(map);
  }

  /** The one write behind every darkroom decision: the ↑ / ↓ keys, a swipe, and
   *  the per-pane buttons a compare grid needs. */
  setPhotoKept(group: CullingGroup, path: string, keep: boolean): void {
    if (!this.cullWritesAllowed()) return;
    const key = this.groupKey(group);
    addToSetSignal(this.touchedGroups, key);
    const map = new Map(this.selectionsMap());
    const kept = new Set(map.get(key) ?? []);
    if (keep) kept.add(path); else kept.delete(path);
    map.set(key, kept);
    this.selectionsMap.set(map);
    this.reportSelection(key, kept);
  }

  /**
   * Take the assistant's suggestion for a photo: a plain manual flip, so the group becomes touched and
   * `culling.changed` / `pending` follow with no second code path. Refused outside plan mode and for a
   * group already confirmed, counting down or hidden, and while a "confirm all" runs: its keepers were captured for the commit and a late
   * flip would desync the page from what the server was told. Allowed while a re-plan is in flight, which
   * carries open flips over.
   */
  acceptSuggestion(group: CullingGroup, path: string, action: CullSuggestionAction): void {
    if (!this.cullWritesAllowed()) return;
    if (!this.planActive() || this.confirming() || this.closedGroupKeys().has(this.groupKey(group))) return;
    this.setPhotoKept(group, path, action === 'keep');
    this.lastAccept = { path, at: Date.now() };
  }

  /** The photo the last accept flipped. The badge unmounts on that click, so the rest of a double-click lands on the tile. */
  private lastAccept: { path: string; at: number } | null = null;

  private justAccepted(path: string): boolean {
    return this.lastAccept?.path === path && Date.now() - this.lastAccept.at < ACCEPT_DOUBLE_CLICK_MS;
  }

  /** A click on a photo tile; the tail of a double-click on a just-accepted badge is not a decision. */
  tileClick(path: string, group: CullingGroup): void {
    if (!this.justAccepted(path)) this.toggleSelection(path, group);
  }

  /** A double-click on a photo tile; see `tileClick`. */
  tileDoubleClick(path: string, group: CullingGroup): void {
    if (!this.justAccepted(path)) this.selectExclusive(path, group);
  }

  /** Put a group's keepers back to an earlier set (a swipe's Undo); not a new decision, so `touchedGroups` is left alone. */
  restoreSelection(group: CullingGroup, kept: Set<string>): void {
    if (!this.cullWritesAllowed()) return;
    const key = this.groupKey(group);
    updateMapSignal(this.selectionsMap, key, kept);
    this.reportSelection(key, kept);
  }

  toggleSelection(path: string, group: CullingGroup): void {
    if (!this.cullWritesAllowed()) return;
    this.setPhotoKept(group, path, !(this.selectionsMap().get(this.groupKey(group))?.has(path) ?? false));
  }

  /**
   * A bracket or a pan is a no-op here: its frames were shot to be merged, not
   * to compete (see SEQUENCE_KINDS_KEPT_WHOLE), and every other surface -- computeAutoKeep,
   * the hidden auto-cull button -- already protects that.
   */
  selectExclusive(path: string, group: CullingGroup): void {
    if (!this.cullWritesAllowed()) return;
    if (group.sequence_kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(group.sequence_kind)) return;
    const key = this.groupKey(group);
    addToSetSignal(this.touchedGroups, key);
    updateMapSignal(this.selectionsMap, key, new Set([path]));
    this.reportSelection(key, [path]);
  }

  /** The body of POST /culling-groups/confirm for one group. */
  private confirmBody(group: CullingGroup, keepPaths: string[]) {
    return {
      group_id: group.group_id,
      type: group.type,
      paths: group.photos.map(p => p.path),
      keep_paths: keepPaths,
    };
  }

  /**
   * Grey the group and start the cancellable cooldown; the commit only happens
   * when it elapses, so cancelling within the window fully reverts it. Returns
   * false when the group has nothing kept (nothing to confirm).
   */
  confirmGroup(group: CullingGroup): boolean {
    if (!this.cullWritesAllowed()) return false;
    // Paused while a re-plan is in flight: the plan it would land on is about to be replaced.
    if (this.replanning()) return false;
    const key = this.groupKey(group);
    const kept = this.selectionsMap().get(key);
    if (!kept || kept.size === 0) return false;
    const keepPaths = [...kept];
    // A commit that lands after the feed was reset (Exit, a scope change) belongs to a feed that is gone:
    // it still reaches the server, but must not hide a same-keyed group of the new feed or journal a confirm.
    const gen = this.loadGenerationId;
    addToSetSignal(this.touchedGroups, key);
    addToSetSignal(this.confirmedGroups, key);
    this.startCountdown(key, () => {
      const commit = firstValueFrom(this.api.post('/culling-groups/confirm', this.confirmBody(group, keepPaths)))
        .then(() => {
          if (gen !== this.loadGenerationId) return;
          if (this.planActive()) this.plan.recordConfirm(key, keepPaths);
          addToSetSignal(this.hiddenGroups, key);
          void this.refreshComparisonStats();
          void this.refreshRankerStatus();
        })
        .catch(() => {
          if (!this.cullLoadCurrent(gen)) return;
          this.unconfirmGroup(key);
          this.notice$.next({ key: I18N.culling.error_confirming, duration: 2000 });
        });
      this.inFlightCommits.add(commit);
      void commit.finally(() => this.inFlightCommits.delete(commit));
      return commit;
    }, true);
    return true;
  }

  unconfirmGroup(key: string): void {
    this.confirmedGroups.update(s => {
      const next = new Set(s);
      next.delete(key);
      return next;
    });
  }

  /** Confirm every not-yet-confirmed group of `visible` that has a kept photo, five at a time. */
  async confirmAllRemaining(visible: CullingGroup[]): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    if (this.replanning()) return;
    // Tracked like a single confirm's commit, so a re-plan started meanwhile waits for every batch.
    const run = this.runConfirmAll(visible);
    this.inFlightCommits.add(run);
    try {
      await run;
    } finally {
      this.inFlightCommits.delete(run);
    }
  }

  private async runConfirmAll(visible: CullingGroup[]): Promise<void> {
    this.confirming.set(true);
    try {
      const confirmed = this.confirmedGroups();
      const remaining = visible.filter(g => !confirmed.has(this.groupKey(g)));
      for (const g of remaining) addToSetSignal(this.touchedGroups, this.groupKey(g));
      const toConfirm = remaining.filter(g => {
        const kept = this.selectionsMap().get(this.groupKey(g));
        return kept && kept.size > 0;
      });
      const gen = this.loadGenerationId;
      // Process in batches of 5 to avoid overwhelming the server
      const batchSize = 5;
      for (let i = 0; i < toConfirm.length; i += batchSize) {
        if (!this.cullLoadCurrent(gen)) return;
        const batch = toConfirm.slice(i, i + batchSize);
        await Promise.all(batch.map(g => {
          const kept = [...this.selectionsMap().get(this.groupKey(g))!];
          return firstValueFrom(this.api.post('/culling-groups/confirm', this.confirmBody(g, kept)))
            .then(() => {
              if (gen === this.loadGenerationId && this.planActive()) this.plan.recordConfirm(this.groupKey(g), kept);
            });
        }));
        if (!this.cullLoadCurrent(gen)) return;
        this.confirmedGroups.update(s => {
          const next = new Set(s);
          for (const g of batch) next.add(this.groupKey(g));
          return next;
        });
      }
      const skipped = remaining.filter(g => !toConfirm.includes(g));
      this.confirmedGroups.update(s => {
        const next = new Set(s);
        for (const g of skipped) next.add(this.groupKey(g));
        return next;
      });
      this.notice$.next({ key: I18N.culling.confirmed, duration: 2000 });
    } catch {
      this.notice$.next({ key: I18N.culling.error_auto_select, duration: 2000 });
    } finally {
      this.confirming.set(false);
    }
  }

  skipGroup(group: CullingGroup): void {
    if (!this.cullWritesAllowed()) return;
    if (this.replanning()) return;
    const key = this.groupKey(group);
    addToSetSignal(this.touchedGroups, key);
    const gen = this.loadGenerationId;
    this.startCountdown(key, () => {
      if (gen !== this.loadGenerationId) return;
      if (this.planActive()) this.plan.recordSkip(key);
      addToSetSignal(this.hiddenGroups, key);
    });
  }

  cancelPass(group: CullingGroup): void {
    const key = this.groupKey(group);
    this.clearPassTimer(key);
    this.unconfirmGroup(key);
  }

  /**
   * Shared 7s cooldown: a per-second countdown in passingGroups plus a one-shot
   * timer that runs onElapsed (hide for skip; commit + hide for confirm). Cancel
   * via cancelPass before it fires fully reverts the action.
   */
  private startCountdown(key: string, onElapsed: () => Promise<void> | void, commit = false): void {
    this.clearPassTimer(key);
    updateMapSignal(this.passingGroups, key, this.passCountdownSeconds);
    const intervalId = setInterval(() => {
      this.passingGroups.update(m => {
        const current = m.get(key);
        if (current === undefined) return m;
        const next = new Map(m);
        next.set(key, current - 1);
        return next;
      });
    }, 1000);
    const timeoutId = setTimeout(() => {
      this.clearPassTimer(key);
      void onElapsed();
    }, this.passCountdownSeconds * 1000);
    this.passTimers.set(key, { timeoutId, intervalId, onElapsed, commit });
  }

  private clearPassTimer(key: string): void {
    const timers = this.passTimers.get(key);
    if (timers) {
      clearTimeout(timers.timeoutId);
      clearInterval(timers.intervalId);
      this.passTimers.delete(key);
    }
    deleteMapKey(this.passingGroups, key);
  }

  clearAllPassTimers(): void {
    // A confirm defers its server commit into the cooldown timer; cancelling
    // that timer on teardown/reload without running it would silently drop the
    // user's keep/reject decision. So flush pending confirm commits here (skip
    // timers only hide a group, nothing to persist). Explicit cancelPass goes
    // through clearPassTimer and is unaffected — an abort still aborts.
    const pendingCommits: (() => Promise<void> | void)[] = [];
    for (const { timeoutId, intervalId, onElapsed, commit } of this.passTimers.values()) {
      clearTimeout(timeoutId);
      clearInterval(intervalId);
      if (commit) pendingCommits.push(onElapsed);
    }
    this.passTimers.clear();
    this.passingGroups.set(new Map());
    this.hiddenGroups.set(new Set());
    for (const commit of pendingCommits) void commit();
  }

  /**
   * Elapse every cooldown now -- confirms commit, skips hide -- and wait for every confirm commit,
   * including ones already in flight. Unlike `clearAllPassTimers` the hidden groups stay hidden: the feed
   * is not being reset, its decisions are being made final.
   */
  private async flushPassTimers(): Promise<void> {
    const pending = [...this.passTimers.values()];
    for (const { timeoutId, intervalId } of pending) {
      clearTimeout(timeoutId);
      clearInterval(intervalId);
    }
    this.passTimers.clear();
    this.passingGroups.set(new Map());
    for (const { onElapsed } of pending) void onElapsed();
    await Promise.all([...this.inFlightCommits]);
  }

  /** Whether the user has decisions a reload would discard (or one still counting down / committing). */
  hasUserDecisions(): boolean {
    return this.touchedGroups().size > 0 || this.confirmedGroups().size > 0
      || this.passingGroups().size > 0 || this.confirming();
  }

  /**
   * Whether replacing the feed would lose something: a group touched but neither confirmed nor skipped, or a
   * confirm or skip still counting down or committing. A landed confirm is on the server already.
   */
  hasUncommittedDecisions(): boolean {
    const confirmed = this.confirmedGroups();
    const hidden = this.hiddenGroups();
    return [...this.touchedGroups()].some(key => !confirmed.has(key) && !hidden.has(key))
      || this.passingGroups().size > 0 || this.confirming();
  }

  /**
   * Fold an assistant's write into the loaded feed without losing the user's decisions.
   *
   * A listed path is re-read through `POST /photos/by_paths` and only its rating/favorite/reject fields
   * are merged into the loaded row (a fresh `groups` array; selections and confirmations are never
   * touched). A path the server no longer returns was moved or deleted: it leaves its group and the
   * group's selection, and a group left empty is hidden. `null` means the scope is not enumerable
   * (a filter-scoped write, a cull move): reload when nothing is at stake, otherwise tell the user.
   */
  applyExternalChanges(
    paths: string[] | null,
    options: { lightboxOpen?: boolean; count?: number } = {},
  ): Promise<void> {
    // Chained so overlapping batches land in arrival order; a failure never blocks the next one.
    const run = this.externalChain.then(() => this.applyExternal(paths, options));
    this.externalChain = run.catch(() => undefined);
    return run;
  }

  private externalChain: Promise<void> = Promise.resolve();

  private async applyExternal(
    paths: string[] | null,
    options: { lightboxOpen?: boolean; count?: number },
  ): Promise<void> {
    if (paths === null) {
      // A plan on screen is the assistant's whole proposal; reloading would quietly end it.
      if (!this.hasUserDecisions() && !options.lightboxOpen && !this.planActive()) {
        this.resetForReload();
        return;
      }
      this.pendingReload.set(true);
      return;
    }
    const loaded = new Set(this.groups().flatMap(g => g.photos.map(p => p.path)));
    const wanted = [...new Set(paths)].filter(path => loaded.has(path));
    if (wanted.length === 0) return;
    const gen = this.loadGenerationId;
    const fresh = new Map<string, Photo>();
    try {
      for (let i = 0; i < wanted.length; i += BY_PATHS_CHUNK) {
        const response = await firstValueFrom(
          this.api.post<{ photos: Photo[] }>('/photos/by_paths', { paths: wanted.slice(i, i + BY_PATHS_CHUNK) }),
        );
        for (const photo of response.photos) fresh.set(photo.path, photo);
      }
    } catch {
      return;
    }
    if (gen !== this.loadGenerationId) return;
    const missing = new Set(wanted.filter(path => !fresh.has(path)));
    this.mergeExternal(fresh, missing);
  }

  private mergeExternal(fresh: Map<string, Photo>, missing: Set<string>): void {
    const emptied: string[] = [];
    const selections = new Map(this.selectionsMap());
    let selectionsChanged = false;
    const next = this.groups().map(group => {
      if (!group.photos.some(p => fresh.has(p.path) || missing.has(p.path))) return group;
      const photos = group.photos
        .filter(p => !missing.has(p.path))
        .map(p => {
          const row = fresh.get(p.path);
          return row ? { ...p, is_rejected: row.is_rejected ? 1 : 0, is_favorite: row.is_favorite ? 1 : 0, star_rating: row.star_rating ?? 0 } : p;
        });
      const key = this.groupKey(group);
      const kept = selections.get(key);
      if (kept && group.photos.some(p => missing.has(p.path) && kept.has(p.path))) {
        const remaining = new Set([...kept].filter(path => !missing.has(path)));
        selections.set(key, remaining);
        this.reportSelection(key, remaining);
        selectionsChanged = true;
      }
      if (photos.length === 0) emptied.push(this.groupKey(group));
      const updated = { ...group, photos, count: photos.length };
      const provenance = this.suggestionProvenance.get(group);
      // Mark refreshes may replace display rows, but only unchanged membership keeps a captured decision valid.
      if (provenance && provenance.membership === this.suggestionMembership(updated)) {
        this.suggestionProvenance.set(updated, provenance);
      }
      return updated;
    });
    this.groups.set(next);
    if (selectionsChanged) this.selectionsMap.set(selections);
    if (emptied.length > 0) this.hiddenGroups.update(s => new Set([...s, ...emptied]));
  }

  /** Set one override value on the named frames, wherever they sit in the feed. */
  patchOverrides(paths: string[], value: string | null): void {
    if (!this.cullWritesAllowed()) return;
    this.restoreOverrides(new Map(paths.map(path => [path, value])));
  }

  /** Write back per-path override values (the undo path restores the old ones). */
  restoreOverrides(values: Map<string, string | null>): void {
    if (!this.cullWritesAllowed()) return;
    // `droppedApplied` is deliberately left untouched here: `rerunNeeded` unions it
    // with the pending-correction keys, so re-marking (or undoing the re-mark) a
    // group whose applied override was already dropped this session must not stop
    // it counting -- `photos` still holds the stale applied set either way.
    this.groups.update(groups => groups.map(group => (
      group.photos.some(p => values.has(p.path))
        ? {
            ...group,
            photos: group.photos.map(p => (
              values.has(p.path)
                ? {
                    ...p,
                    sequence_override: values.get(p.path) ?? null,
                    // Anything just written here is by definition unapplied: the
                    // detector is a batch pass, not a live query.
                    sequence_override_pending: values.get(p.path) ? 1 : null,
                  }
                : p
            )),
          }
        : group
    )));
  }

  /** The one writer of the strictness: the slider, a preset and a shown plan all store what they set. */
  setStrictness(value: number): void {
    this.strictnessState.set(value);
    try {
      localStorage.setItem(CULL_STRICTNESS_KEY, String(value));
    } catch {
      // Storage full or blocked: the value still applies for this visit.
    }
  }

  /** Moving a knob by hand drops the preset label — the mix is now custom. */
  clearProfileSelection(): void {
    if (this.selectedProfile()) {
      this.selectedProfile.set('');
      localStorage.removeItem(CULL_PROFILE_KEY);
    }
  }

  // --- Genre culling profiles (preset selector + moment auto-suggest) ---

  /** Load the genre culling presets; re-apply the persisted one on open. */
  async loadCullProfiles(): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    try {
      const profiles = await this.fetchCullProfiles();
      if (!profiles) return;
      this.cullProfiles.set(profiles);
      const stored = this.cullProfiles().find(p => p.id === this.selectedProfile());
      if (stored) {
        // A restored preset is a choice the user made, just in an earlier
        // session; a suggestion must not silently replace it.
        this.profileChosen.set(true);
        if (this.planActive()) {
          // The plan froze the grouping: applying the preset could reload the feed and end the plan.
          // Only the slider follows the preset the plan was computed with, unless the plan carries its own.
          if (stored.strictness != null && !this.planHasStrictness) {
            this.setStrictness(stored.strictness);
          }
          this.previousPlanStrictness = this.strictness();
        } else {
          // `applyProfile` writes the preset's own strictness over the slider's stored value: read it first.
          const storedStrictness = readStoredStrictnessOrNull();
          this.applyProfile(stored, false);
          if (storedStrictness != null && storedStrictness !== this.strictness()) {
            this.setStrictness(storedStrictness);
            this.reselectFromStrictness();
          }
        }
      } else {
        this.clearProfileSelection();
      }
    } catch {
      // Preset selector stays hidden when the list can't load.
    }
  }

  /**
   * Apply a preset: set strictness first (so a reload auto-selects with it) and
   * the similarity threshold, remember the choice, then re-derive the auto-keep
   * selection in place — or reload only when the threshold changed the grouping.
   */
  applyProfile(p: CullProfile, persist = true): void {
    if (!this.cullWritesAllowed()) return;
    this.selectedProfile.set(p.id);
    if (persist) {
      localStorage.setItem(CULL_PROFILE_KEY, p.id);
      this.profileChosen.set(true);
    }
    if (p.strictness != null) this.setStrictness(p.strictness);
    if (p.similarity_threshold != null && p.similarity_threshold !== this.similarityThreshold()) {
      this.similarityThreshold.set(p.similarity_threshold);
      this.resetForReload();
    } else if (p.strictness != null) {
      this.reselectFromStrictness();
    }
  }

  /** Identity of the current scope, so a scope change refetches its suggestion. */
  scopeKey(): string {
    const scope = this.scopeParams();
    return [scope.album_id ?? '', scope.date_from ?? '', scope.date_to ?? ''].join('|');
  }

  /** Drop a suggestion that answered for another scope. */
  resetProfileSuggestion(): void {
    this.suggestionScopeKey = null;
    this.suggestionApplied = false;
    this.profileSuggestion.set(null);
  }

  /**
   * Preselect the preset the scope's content argues for, at most once per scope.
   *
   * Fetched alongside the dry run rather than before it, so the dialog opens at
   * the same speed whether or not a suggestion arrives; one that lands while the
   * dialog is open — or while its dry run is still in flight — re-runs the
   * preview under the suggested knobs rather than leaving stale counts on
   * screen. An explicit choice — a preset click, a knob move, or one restored
   * from a previous session — is never overwritten.
   *
   * Refused outright once the destructive apply is in flight, and refused again
   * after the fetch, since that is the whole window this can resolve in. The
   * apply owns the knobs the same way it owns the snapshot: refusing only at the
   * dry run's door came after applyProfile() had already moved strictness and lit
   * the preset chip, so the user watched them jump under a request neither the
   * counts on screen nor the apply itself were computed from. Nothing is queued
   * for afterwards — the dialog a late suggestion would repaint is gone by then.
   */
  async applySuggestedProfile(): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    if (this.profileChosen() || this.suggestionApplied || this.autoCullApplying()) return;
    const key = this.scopeKey();
    const suggestion = this.suggestionScopeKey === key
      ? this.profileSuggestion()
      : await this.fetchProfileSuggestion(key);
    const suggested = suggestion?.profile;
    if (!suggested || this.profileChosen() || this.autoCullApplying()) return;
    const profile = this.cullProfiles().find(p => p.id === suggested);
    if (!profile || profile.id === this.selectedProfile()) return;
    this.suggestionApplied = true;
    this.applyProfile(profile, false);
    if (this.autoCullPreview() || this.dryRunInFlight) {
      // Named only once the re-run published: a refused one (the apply owns the
      // dialog) leaves the counts exactly as they were, and the notice claims
      // they were recomputed under the preset it names.
      if (await this.openAutoCull() === 'landed') {
        this.autoCullSuggestionNotice.set(this.i18n.t(profile.label_key));
      }
    }
  }

  /** Ask the backend which preset this scope's stored content looks like. */
  async fetchProfileSuggestion(key: string): Promise<ProfileSuggestion | null> {
    if (!this.cullWritesAllowed()) return null;
    const params: Record<string, string | number> = this.numericScopeParams();
    const gen = this.loadGenerationId;
    try {
      const data = await firstValueFrom(
        this.api.get<ProfileSuggestion>('/culling/suggest_profile', params),
      );
      if (!this.cullLoadCurrent(gen)) return null;
      this.suggestionScopeKey = key;
      this.profileSuggestion.set(data);
      return data;
    } catch {
      // No suggestion: the dialog keeps whatever preset is already active.
      return null;
    }
  }

  // --- Auto-cull (one-button cull under a keeper budget) ---

  /** Request body for POST /culling/auto, reusing the page's scope + strictness. */
  autoCullBody(dryRun: boolean, highlightsAlbum: string): AutoCullRequest {
    const body: AutoCullRequest = {
      group_by: this.groupBy(),
      strictness: this.strictness(),
      dry_run: dryRun,
      highlights_album: highlightsAlbum,
      trim_brackets: this.trimBrackets(),
    };
    const profile = this.selectedProfile();
    if (profile) body.profile = profile;
    return Object.assign(body, this.numericScopeParams());
  }

  /** Deterministic Highlights album name for the current scope and day. */
  highlightsAlbumName(): string {
    const scope = this.scopeLabel() ?? this.i18n.t(I18N.culling.scope_whole_library);
    const day = new Date().toISOString().slice(0, 10);
    return `${this.i18n.t(I18N.culling.auto_cull.highlights_name)} — ${scope} ${day}`;
  }

  /** True while this dry run is still the one the dialog answers to: no newer
   *  run took over, and the destructive apply does not own the snapshot. */
  ownsAutoCullDialog(run: number): boolean {
    return this.autoCullRun.isCurrent(run) && !this.autoCullApplying();
  }

  /**
   * Put the trim-brackets checkbox back to what the snapshot Apply sends carries.
   *
   * Called from the failure of whichever run owns the dialog, because that run is
   * the one the box has to agree with — not necessarily the one the user clicked.
   * A failed run never moved the snapshot, so a box left on the value that run
   * asked for promises a trim the apply would not perform.
   */
  reconcileTrimBrackets(): void {
    const applied = this.autoCullRequest();
    if (applied) this.trimBrackets.set(applied.trim_brackets);
  }

  /**
   * Dry-run the auto-cull for the current scope and open the confirm dialog.
   *
   * Refused outright while the apply is in flight, and its answer dropped if an
   * apply started under it: the apply sends the snapshot below verbatim, so a dry
   * run repainting it mid-flight would leave the dialog describing a request the
   * user never agreed to. The suggestion's re-run is fire-and-forget, so it can
   * arrive at any point — including over the destructive request.
   *
   * The outcome is for the callers that mirror the snapshot in their own state:
   * a bail-out is not this caller's run failing, and reconciling on it reverts to
   * a snapshot the newer run is about to replace.
   */
  async openAutoCull(): Promise<AutoCullRunOutcome> {
    if (!this.cullWritesAllowed()) return 'superseded';
    if (this.autoCullApplying()) return 'superseded';
    // Only a fresh open clears the notices: the re-runs that raise them come back
    // through here, and clearing unconditionally would erase them on the way in —
    // including the re-run of a dry run whose preview has not landed yet.
    if (!this.autoCullPreview() && !this.dryRunInFlight) this.clearAutoCullNotices();
    const run = this.autoCullRun.next();
    this.dryRunInFlight = true;
    void this.applySuggestedProfile();
    const body = this.autoCullBody(true, this.highlightsAlbumName());
    this.autoCullLoading.set(true);
    try {
      const preview = await firstValueFrom(this.api.post<AutoCullResponse>('/culling/auto', body));
      if (!this.ownsAutoCullDialog(run)) return 'superseded';
      this.autoCullPreview.set(preview);
      this.autoCullRequest.set(body);
      return 'landed';
    } catch {
      if (!this.ownsAutoCullDialog(run)) return 'superseded';
      this.reconcileTrimBrackets();
      this.notice$.next({ key: I18N.culling.auto_cull.error, duration: 2000 });
      return 'failed';
    } finally {
      if (this.autoCullRun.isCurrent(run)) {
        this.dryRunInFlight = false;
        this.autoCullLoading.set(false);
      }
    }
  }

  /** Every dismissal lands here — the Cancel button, the backdrop and Escape.
   *  It is a no-op while the apply is in flight: the destructive request cannot
   *  be called off, so the dialog stays up with its spinner rather than pretend
   *  it was. */
  cancelAutoCull(): void {
    if (this.autoCullApplying()) return;
    this.closeAutoCull();
    this.clearAutoCullNotices();
  }

  /** Drop the dialog and the run behind it, so a dry run still in flight cannot
   *  reopen it with counts nobody asked for. Safe from the apply's own success
   *  path for the same reason the guard above exists: no dismissal can have
   *  reopened the dialog mid-apply, so the bump can only cancel a dry run whose
   *  preview this apply just made obsolete. */
  closeAutoCull(): void {
    this.autoCullRun.cancel();
    this.dryRunInFlight = false;
    this.autoCullPreview.set(null);
    this.autoCullRequest.set(null);
    this.autoCullLoading.set(false);
  }

  clearAutoCullNotices(): void {
    this.autoCullSuggestionNotice.set(null);
    this.trimBracketsUnchanged.set(false);
  }

  /** Trim-brackets changes the group set the dry run splits, so the preview
   *  counts must be re-fetched through the same path openAutoCull() uses.
   *
   *  A scope with no redundant exposures answers with the very same counts, which
   *  is indistinguishable from a dead toggle — so that case is stated. The
   *  identity check on the preview object keeps a failed re-run (which leaves the
   *  old preview in place) from being read as "nothing to trim".
   *
   *  Reverting the checkbox over a failed re-run is not this handler's to do: the
   *  run that fails is not always the one this call started. A superseded re-run
   *  reads from here exactly like its own failure, and the snapshot it would be
   *  reconciled against is the stale one the newer run has not replaced yet — so
   *  the box would be reverted to a value that run is about to contradict, and
   *  the newer run failing in turn would leave nobody to put it back. The run
   *  that owns the dialog reconciles the box, in openAutoCull(); this handler
   *  only reads the outcome. */
  async onTrimBracketsChange(value: boolean): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    if (this.autoCullApplying()) return;
    const before = this.autoCullPreview();
    this.trimBrackets.set(value);
    this.trimBracketsUnchanged.set(false);
    if (await this.openAutoCull() !== 'landed') return;
    const after = this.autoCullPreview();
    this.trimBracketsUnchanged.set(
      value && !!before && !!after && after !== before
      && after.groups_processed === before.groups_processed
      && after.kept === before.kept
      && after.rejected === before.rejected,
    );
  }

  /**
   * Apply the previewed auto-cull (dry_run=false), then refresh the feed.
   *
   * The body is the dry run's own, not one rebuilt from the live signals: a
   * profile suggestion can land between the preview request and its answer, and
   * rebuilding here would then apply knobs the counts on screen never described.
   * Only the Highlights album is the dialog's to decide, being a checkbox the
   * user ticks after the preview.
   *
   * The `autoCullApplying` gate makes the click idempotent: a second one over
   * the same snapshot is refused rather than sent, since the two applies would
   * reject different sets — the first has already moved the state the second
   * would be computed from.
   *
   * `onApplied` runs once the apply landed, before the stats refresh: the caller
   * resets its own view state and reloads the feed there.
   */
  async confirmAutoCull(onApplied: () => void): Promise<void> {
    if (!this.cullWritesAllowed()) return;
    const previewed = this.autoCullRequest();
    if (!previewed || this.autoCullApplying()) return;
    const gen = this.loadGenerationId;
    this.autoCullApplying.set(true);
    this.autoCullLoading.set(true);
    try {
      const body: AutoCullRequest = {
        ...previewed,
        dry_run: false,
        highlights_album: this.autoCullHighlights() ? previewed.highlights_album : '',
      };
      const result = await firstValueFrom(this.api.post<AutoCullResponse>('/culling/auto', body));
      if (!this.cullLoadCurrent(gen)) return;
      this.closeAutoCull();
      this.clearAutoCullNotices();
      this.notice$.next({
        key: I18N.culling.auto_cull.applied,
        params: { kept: result.kept, rejected: result.rejected },
        duration: 3000,
      });
      onApplied();
      void this.refreshComparisonStats();
      void this.refreshRankerStatus();
    } catch {
      this.notice$.next({ key: I18N.culling.auto_cull.error, duration: 2000 });
    } finally {
      this.autoCullApplying.set(false);
      this.autoCullLoading.set(false);
    }
  }
}

/** Order-free identity of a group's photo set, which survives a re-plan renumbering the groups. */
function pathSetKey(paths: string[]): string {
  return [...paths].sort().join('\n');
}
