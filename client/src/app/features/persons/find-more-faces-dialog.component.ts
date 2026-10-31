import { Component, inject, signal, computed, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NgTemplateOutlet } from '@angular/common';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import type { components } from '../../core/api/schema';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { FaceThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { i18nKeys, I18N } from '../../core/i18n/keys';
import { isUnnamedPerson, sameName } from '../../shared/utils/person-name';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';

/** One row of ``GET /api/person/{id}/possible_faces``, with its current owner. */
export type PossibleFace = components['schemas']['PossibleFace'];
/** Another person whose centroid looks like this one's. */
export type SimilarGroup = components['schemas']['SimilarGroup'];
export type PossibleFaceCounts = components['schemas']['PossibleFaceCounts'];
export type PossibleFacesResponse = components['schemas']['PossibleFacesResponse'];
/** Who a candidate face belongs to now: no group, a group nobody named, or a named person. */
export type FaceOwner = PossibleFace['owner'];
export const FACE_OWNERS: readonly FaceOwner[] = ['ungrouped', 'unnamed_group', 'named'];

export interface FindMoreFacesDialogData {
  personId: number;
  personName: string | null;
}

/** What the dialog closes with: how many faces it moved onto the person. */
export interface FindMoreFacesResult {
  added: number;
}

export type FindMoreStrictness = 'very_strict' | 'strict' | 'normal' | 'loose' | 'very_loose';
/** ``min_similarity`` per strictness. */
export const FIND_MORE_STRICTNESS: Record<FindMoreStrictness, number> = {
  very_strict: 0.6, strict: 0.5, normal: 0.35, loose: 0.25, very_loose: 0.2,
};
/** Faces shown per round. */
export const FIND_MORE_PAGE = 48;
/** Rows asked of the server per round, so the faces dismissed earlier can be dropped and still fill a page. */
export const FIND_MORE_FETCH = 100;
/** A face at or above this similarity is a "Strong" match, and starts ticked unless another named person owns it. */
export const FIND_MORE_STRONG = 0.5;

/**
 * Why the search was narrowed: ``ungrouped`` after the full search was over the
 * server's ceiling, ``year`` once even that was, until the user picks a year.
 */
export type FindMoreFallback = 'none' | 'ungrouped' | 'year';

/** Signal bars drawn per level: more lit bars, closer matches only. */
const STRICTNESS_BARS: Record<FindMoreStrictness, number> = {
  very_strict: 5, strict: 4, normal: 3, loose: 2, very_loose: 1,
};

/** Height of each of the five bars, shortest first. */
const BAR_HEIGHTS = ['h-1', 'h-1.5', 'h-2', 'h-3', 'h-3.5'] as const;

const STRICTNESS_LABELS: Record<FindMoreStrictness, string> = {
  very_strict: I18N.persons.find_more_very_strict,
  strict: I18N.persons.find_more_strict,
  very_loose: I18N.persons.find_more_very_loose,
  normal: I18N.persons.find_more_normal,
  loose: I18N.persons.find_more_loose,
};

const STRICTNESS_HELP: Record<FindMoreStrictness, string> = {
  very_strict: I18N.persons.find_more_very_strict_help,
  strict: I18N.persons.find_more_strict_help,
  very_loose: I18N.persons.find_more_very_loose_help,
  normal: I18N.persons.find_more_normal_help,
  loose: I18N.persons.find_more_loose_help,
};

const STRICTNESS_LEVELS: readonly FindMoreStrictness[] = ['very_strict', 'strict', 'normal', 'loose', 'very_loose'];

const STRICTNESS_PERCENT = Object.fromEntries(
  STRICTNESS_LEVELS.map((level) => [level, Math.round(FIND_MORE_STRICTNESS[level] * 100)]),
) as Record<FindMoreStrictness, number>;

const OWNER_HELP: Record<FaceOwner, string> = {
  ungrouped: I18N.persons.find_more_owner_ungrouped_help,
  unnamed_group: I18N.persons.find_more_owner_unnamed_group_help,
  named: I18N.persons.find_more_owner_named_help,
};

const OWNER_LABELS: Record<FaceOwner, string> = {
  ungrouped: I18N.persons.find_more_owner_ungrouped,
  unnamed_group: I18N.persons.find_more_owner_unnamed_group,
  named: I18N.persons.find_more_owner_named,
};

/**
 * "Find more faces like this person": a teach-by-example loop over the
 * ``possible_faces`` search. Each round lists the faces closest to the person's
 * centroid; the user ticks the right ones and adds them, which recomputes the
 * centroid server-side. Faces shown in a round and left unticked are taken as "not
 * this person" and are not offered again while the dialog stays open.
 *
 * The search covers every face, narrowed by owner chips (ungrouped and unnamed
 * groups by default; named people opt-in, since adding one takes it from them),
 * and lists whole groups that look alike above the faces, each mergeable at once.
 * An add shows the next page of the results already fetched, searching again only
 * once those run out. A search over the server's ceiling falls back to ungrouped
 * faces, then to one year at a time.
 */
@Component({
  selector: 'app-find-more-faces-dialog',
  imports: [
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSelectModule,
    MatMenuModule,
    NgTemplateOutlet,
    MatTooltipModule,
    TranslatePipe,
    PluralKeyPipe,
    FaceThumbnailUrlPipe,
    PersonThumbnailUrlPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate">
      {{ I18N.persons.find_more_title | translate }}
    </h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px] min-h-[160px]">
      <div data-target-person class="flex items-center gap-3">
        <img [src]="data.personId | personThumbnailUrl" alt="" class="w-14 h-14 rounded-full object-cover shrink-0 border-2 border-[var(--mat-sys-primary)]" />
        <div class="flex flex-col min-w-0">
          <span class="font-medium truncate">
            {{ displayName() }}
            @if (!data.personName) { <span class="text-xs font-normal opacity-70">#{{ data.personId }}</span> }
          </span>
          <p class="text-sm text-gray-400">
            {{ I18N.persons.find_more_desc | translate:{ name: displayName() } }}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2 flex-wrap md:flex-nowrap" role="group" [attr.aria-label]="I18N.persons.find_more_owners | translate">
        @for (chip of chips(); track chip.owner) {
          <button type="button"
                  class="h-8 px-2 rounded-md border text-xs whitespace-nowrap transition-colors"
                  [class]="chip.on ? 'border-[var(--mat-sys-primary)] bg-[var(--mat-sys-primary-container)] text-[var(--mat-sys-on-primary-container)]' : 'border-[var(--mat-sys-outline)]'"
                  [attr.data-owner]="chip.owner"
                  [attr.aria-pressed]="chip.on"
                  [disabled]="chip.disabled"
                  [matTooltip]="chip.help | translate"
                  (click)="toggleOwner(chip.owner)">
            @if (chip.on) { <mat-icon class="!text-sm !w-4 !h-4 !leading-4 align-middle">check</mat-icon> }
            {{ chip.label | translate:{ count: chip.count } }}
          </button>
        }
        <span class="flex-1"></span>
        <button mat-stroked-button data-strictness
                class="shrink-0 !h-8 !px-2 !min-w-0 text-xs"
                [matMenuTriggerFor]="strictnessMenu"
                [matTooltip]="(I18N.persons.find_more_strictness | translate) + ': ' + (STRICTNESS_HELP[strictness()] | translate)"
                [attr.aria-label]="(I18N.persons.find_more_strictness | translate) + ': ' + (STRICTNESS_LABELS[strictness()] | translate)">
          <ng-container *ngTemplateOutlet="bars; context: { $implicit: STRICTNESS_BARS[strictness()] }" />
          <span class="ml-1">≥{{ STRICTNESS_PERCENT[strictness()] }}%</span>
        </button>
        <mat-menu #strictnessMenu="matMenu" xPosition="before">
          @for (level of STRICTNESS_LEVELS; track level) {
            <button mat-menu-item role="menuitemradio" [attr.data-level]="level"
                    [attr.aria-checked]="level === strictness()"
                    (click)="setStrictness(level)">
              <span class="flex items-center gap-3">
              <ng-container *ngTemplateOutlet="bars; context: { $implicit: STRICTNESS_BARS[level] }" />
              <span class="flex flex-col py-1 leading-tight">
                <span [class.font-semibold]="level === strictness()">{{ STRICTNESS_LABELS[level] | translate }} · ≥{{ STRICTNESS_PERCENT[level] }}%</span>
                <span class="text-xs opacity-70">{{ STRICTNESS_HELP[level] | translate }}</span>
              </span>
              </span>
            </button>
          }
        </mat-menu>
        <ng-template #bars let-lit>
          <span class="inline-flex items-end gap-px h-3.5" aria-hidden="true">
            @for (h of BAR_HEIGHTS; track $index) {
              <span class="w-1 rounded-[1px]" [class]="h"
                    [class.bg-current]="$index < lit"
                    [class.bg-[var(--mat-sys-outline-variant)]]="$index >= lit"></span>
            }
          </span>
        </ng-template>
      </div>
      <div class="flex items-center gap-2 flex-wrap text-sm">
        <span data-match-count class="opacity-70">
          {{ matchCount() | pluralKey:I18N.persons.find_more_matches_one:I18N.persons.find_more_matches | translate:{ count: matchCount() } }}
        </span>
        <span class="flex-1"></span>
        @if (rows().length > 0) {
          <button mat-button [matTooltip]="I18N.persons.find_more_select_strong_help | translate" (click)="selectStrong()">{{ I18N.persons.find_more_select_strong | translate }}</button>
          <button mat-button (click)="selectAll()">{{ I18N.persons.find_more_select_all | translate }}</button>
          <button mat-button (click)="clearSelection()">{{ I18N.persons.find_more_clear | translate }}</button>
        }
      </div>
      @if (fallback() !== 'none') {
        <p data-fallback class="text-sm">
          {{ (fallback() === 'year' ? I18N.persons.find_more_fallback_year : I18N.persons.find_more_fallback_ungrouped) | translate }}
        </p>
        @if (fallback() === 'year') {
          <mat-form-field class="w-40" subscriptSizing="dynamic">
            <mat-label>{{ I18N.persons.find_more_year | translate }}</mat-label>
            <mat-select [value]="year()" (selectionChange)="pickYear($event.value)">
              @for (y of years(); track y) {
                <mat-option [value]="y">{{ y }}</mat-option>
              }
            </mat-select>
          </mat-form-field>
        }
      }
      @if (groups().length > 0) {
        <div class="flex flex-col gap-1" data-similar-groups>
          <div class="text-xs uppercase tracking-wider opacity-70">{{ I18N.persons.find_more_similar_groups | translate }}</div>
          @for (g of groups(); track g.person_id) {
            <div class="flex items-center gap-3 rounded-lg px-2 py-1 bg-[var(--mat-sys-surface-container)]" [attr.data-group]="g.person_id">
              <img [src]="g.person_id | personThumbnailUrl" alt="" class="w-12 h-12 rounded-full object-cover shrink-0" />
              <div class="flex flex-col min-w-0 flex-1 text-sm">
                <span class="font-medium truncate">{{ g.name || (I18N.persons.find_more_unnamed_group | translate) }}</span>
                <span class="opacity-70">
                  {{ g.face_count | pluralKey:I18N.person_selector.face_count_one:I18N.person_selector.face_count | translate:{ count: g.face_count } }}
                  · {{ I18N.persons.find_more_alike | translate:{ percent: g.percent } }}
                </span>
              </div>
              <button mat-stroked-button [disabled]="busy()" (click)="mergeGroup(g)">
                <mat-icon>merge</mat-icon>
                {{ I18N.persons.find_more_merge_all | translate }}
              </button>
            </div>
          }
        </div>
      }
      @if (loading()) {
        <div class="flex items-center justify-center py-8">
          <mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      } @else if (error()) {
        <p class="text-sm text-center py-8">{{ error() }}</p>
      } @else if (rows().length === 0) {
        @if (fallback() !== 'year' || year()) {
          <div data-empty class="flex flex-col items-center gap-2 py-6 text-sm">
            <p class="opacity-70 text-center">
              @if (closest(); as c) {
                {{ I18N.persons.find_more_none_closest | translate:{ name: displayName(), percent: c.percent } }}
              } @else {
                {{ I18N.persons.find_more_none | translate }}
              }
            </p>
            <div class="flex gap-2 flex-wrap justify-center">
              @if (strictness() !== 'loose' && strictness() !== 'very_loose') {
                <button mat-stroked-button data-try-loose (click)="setStrictness('loose')">{{ I18N.persons.find_more_try_loose | translate }}</button>
              }
              @if (offerNamed()) {
                <button mat-stroked-button data-include-named (click)="toggleOwner('named')">{{ I18N.persons.find_more_include_named | translate }}</button>
              }
            </div>
          </div>
        }
      } @else {
        <div class="grid grid-cols-3 sm:grid-cols-5 gap-2">
          @for (row of rows(); track row.face_id; let i = $index) {
            <button
              class="relative rounded-lg overflow-hidden border-2 transition-colors cursor-pointer"
              [class.border-blue-500]="row.selected"
              [class.border-transparent]="!row.selected"
              [attr.data-face]="row.face_id"
              [attr.aria-pressed]="row.selected"
              [attr.aria-label]="(I18N.persons.find_more_select_face_detail | translate:{ index: i + 1, percent: row.percent, strength: ((row.strong ? I18N.persons.find_more_strong : I18N.persons.find_more_possible) | translate) }) + (row.fromName ? ', ' + (I18N.persons.find_more_from | translate:{ name: row.fromName }) : '')"
              (click)="onFaceClick(i, $event)"
              (keydown.space)="onFaceSpace(row.face_id, $event)">
              <img [src]="row.face_id | faceThumbnailUrl" alt="" class="w-full aspect-square object-cover block" />
              <span class="absolute top-1 left-1 rounded px-1 text-[0.625rem] font-semibold"
                    [matTooltip]="(row.strong ? I18N.persons.find_more_strong_help : I18N.persons.find_more_possible_help) | translate"
                    [class]="row.strong ? 'bg-green-700 text-white' : 'bg-black/60 text-white'">
                {{ (row.strong ? I18N.persons.find_more_strong : I18N.persons.find_more_possible) | translate }}
              </span>
              <span class="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[0.625rem] px-1 truncate">
                {{ I18N.persons.find_more_similarity | translate:{ percent: row.percent } }}
                @if (row.fromName) { · {{ I18N.persons.find_more_from | translate:{ name: row.fromName } }} }
              </span>
              @if (row.selected) {
                <span class="absolute top-1 right-1 bg-blue-500 text-white rounded-full flex items-center justify-center w-5 h-5">
                  <mat-icon class="!text-sm !w-4 !h-4 leading-4">check</mat-icon>
                </span>
              }
            </button>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end" class="!flex-wrap gap-2">
      @if (movingCount() > 0) {
        <p data-moves-warning class="text-sm text-[var(--mat-sys-error)] flex-1 min-w-48">
          {{ I18N.persons.find_more_moves_warning | translate:{ count: movingCount(), name: displayName() } }}
        </p>
      }
      <button mat-button (click)="close()">{{ I18N.dialog.cancel | translate }}</button>
      <button mat-flat-button data-add [disabled]="selectedIds().size === 0 || busy()" (click)="addSelected()">
        <mat-icon>person_add</mat-icon>
        <span class="truncate max-w-64">{{ I18N.persons.find_more_add | translate:{ count: selectedIds().size, name: displayName() } }}</span>
      </button>
    </mat-dialog-actions>
  `,
})
export class FindMoreFacesDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  protected readonly STRICTNESS_LEVELS = STRICTNESS_LEVELS;
  protected readonly STRICTNESS_BARS = STRICTNESS_BARS;
  protected readonly BAR_HEIGHTS = BAR_HEIGHTS;
  protected readonly STRICTNESS_LABELS = STRICTNESS_LABELS;
  protected readonly STRICTNESS_HELP = STRICTNESS_HELP;
  protected readonly STRICTNESS_PERCENT = STRICTNESS_PERCENT;
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialog);
  private readonly faceBoxes = inject(PersonFaceBoxesService);
  readonly data: FindMoreFacesDialogData = inject(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<FindMoreFacesDialogComponent, FindMoreFacesResult>);

  readonly owners = signal<ReadonlySet<FaceOwner>>(new Set<FaceOwner>(['ungrouped', 'unnamed_group']));
  readonly strictness = signal<FindMoreStrictness>('normal');
  readonly fallback = signal<FindMoreFallback>('none');
  readonly year = signal<string | null>(null);
  readonly years = signal<string[]>([]);
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly counts = signal<PossibleFaceCounts | null>(null);
  readonly bestSimilarity = signal<number | null>(null);
  readonly similarGroups = signal<SimilarGroup[]>([]);
  readonly selectedIds = signal<Set<number>>(new Set());
  /** Faces shown in an earlier round and left unticked: not offered again. */
  private readonly dismissed = new Set<number>();
  /**
   * This round's results not yet dismissed or added, every owner class the search
   * fetched. The owner chips filter it client-side (``visible``), so toggling one
   * does not search again.
   */
  private readonly buffer = signal<PossibleFace[]>([]);
  private added = 0;
  /** The face a shift-click extends the selection from. */
  private anchor: number | null = null;
  /** Only the latest search may show its answer. */
  private loadToken = 0;

  /**
   * The buffered faces the active owner chips list. The narrowed (412) searches
   * fetch ungrouped faces only and ignore the chips, so they are shown whole.
   */
  private readonly visible = computed(() => {
    const on = this.owners();
    return this.fallback() === 'none' ? this.buffer().filter((f) => on.has(f.owner)) : this.buffer();
  });

  /** The first page of the visible faces. */
  readonly faces = computed(() => this.visible().slice(0, FIND_MORE_PAGE));

  protected readonly displayName = computed(() => this.data.personName || this.i18n.t(I18N.persons.unnamed));

  readonly rows = computed(() => {
    const selected = this.selectedIds();
    return this.faces().map((f) => ({
      ...f,
      selected: selected.has(f.face_id),
      percent: Math.round(f.similarity * 100),
      strong: f.similarity >= FIND_MORE_STRONG,
      fromName: f.owner === 'named' ? (f.person_name ?? null) : null,
    }));
  });

  /** The owner chips; while the search is narrowed to ungrouped faces they cannot change it. */
  readonly chips = computed(() => {
    const on = this.owners();
    const counts = this.counts();
    const narrowed = this.fallback() !== 'none';
    return FACE_OWNERS.map((owner) => ({
      owner,
      label: OWNER_LABELS[owner],
      help: OWNER_HELP[owner],
      count: counts?.[owner] ?? 0,
      on: on.has(owner),
      // The last chip on stays on: an empty search has nothing to show.
      disabled: narrowed || (on.has(owner) && on.size === 1),
    }));
  });

  /** Faces the active chips would list, over the whole scan. */
  readonly matchCount = computed(() => {
    const counts = this.counts();
    if (!counts) return 0;
    return FACE_OWNERS.filter((o) => this.owners().has(o)).reduce((n, o) => n + (counts[o] ?? 0), 0);
  });

  /** Look-alike groups: the unnamed ones always, the named ones with the Named chip. */
  readonly groups = computed(() => {
    const named = this.owners().has('named');
    return this.similarGroups()
      .filter((g) => named || isUnnamedPerson(g.name))
      .map((g) => ({ ...g, percent: Math.round(g.similarity * 100) }));
  });

  /** The closest face scanned, wrapped so a 0% best still shows. */
  readonly closest = computed(() => {
    const best = this.bestSimilarity();
    return best === null ? null : { percent: Math.round(best * 100) };
  });


  readonly offerNamed = computed(() =>
    this.fallback() === 'none' && !this.owners().has('named') && (this.counts()?.named ?? 0) > 0);

  /** Ticked faces another named person owns: adding them moves them. */
  readonly movingCount = computed(() => {
    const selected = this.selectedIds();
    return this.faces().filter((f) => f.owner === 'named' && selected.has(f.face_id)
      && !sameName(f.person_name, this.data.personName)).length;
  });

  constructor() {
    // Every way out must report the faces already added, so the host refreshes.
    this.dialogRef.disableClose = true;
    this.dialogRef.backdropClick().pipe(takeUntilDestroyed()).subscribe(() => this.close());
    this.dialogRef.keydownEvents().pipe(takeUntilDestroyed()).subscribe((event: KeyboardEvent) => {
      if (event.key === 'Escape') this.close();
    });
  }

  ngOnInit(): Promise<void> {
    return this.load();
  }

  private params(): Record<string, string | number> {
    const base = { limit: FIND_MORE_FETCH, min_similarity: FIND_MORE_STRICTNESS[this.strictness()] };
    if (this.fallback() === 'none') {
      // Every owner class, FIND_MORE_FETCH of each (``per_owner``), so the chips can filter without a new search.
      return { ...base, scope: 'all', owners: FACE_OWNERS.join(','), per_owner: 'true' };
    }
    // The indexed scope, so the narrowed search reads fewer faces, not just shows fewer.
    const narrowed = { ...base, scope: 'unassigned', owners: 'ungrouped' };
    const y = this.year();
    return y ? { ...narrowed, date_from: `${y}-01-01`, date_to: `${y}-12-31` } : narrowed;
  }

  async load(): Promise<void> {
    const token = ++this.loadToken;
    this.loading.set(true);
    this.error.set(null);
    try {
      for (;;) {
        if (this.fallback() === 'year' && !this.year()) {
          this.clearResults();
          return;
        }
        try {
          const res = await firstValueFrom(
            this.api.get<PossibleFacesResponse>(`/person/${this.data.personId}/possible_faces`, this.params()));
          if (token !== this.loadToken) return;
          this.counts.set(res.counts ?? null);
          this.bestSimilarity.set(res.best_similarity ?? null);
          this.similarGroups.set(res.similar_groups ?? []);
          this.buffer.set((res.faces ?? []).filter((f) => !this.dismissed.has(f.face_id)));
          this.showPage();
          return;
        } catch (err) {
          if (token !== this.loadToken) return;
          if (!tooManyFaces(err)) {
            this.clearResults();
            this.error.set(this.errorMessage(err));
            return;
          }
          if (this.fallback() === 'none') {
            this.fallback.set('ungrouped');
            continue;
          }
          if (this.fallback() === 'ungrouped') {
            this.fallback.set('year');
            void this.loadYears();
            continue;
          }
          this.clearResults();
          this.error.set(this.i18n.t(I18N.persons.find_more_too_many_unassigned));
          return;
        }
      }
    } finally {
      if (token === this.loadToken) this.loading.set(false);
    }
  }

  private clearResults(): void {
    this.buffer.set([]);
    this.selectedIds.set(new Set());
  }

  /** The library's years, newest first, for the narrowed search's picker. */
  private async loadYears(): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.get<{ years: { year: string }[] }>('/timeline/years'));
      this.years.set((res.years ?? []).map((y) => y.year).sort().reverse());
    } catch {
      this.years.set([]);
    }
  }

  /** Show the visible faces' first page, ticking the strong matches no other named person owns. */
  private showPage(): void {
    const faces = this.faces();
    this.anchor = null;
    // A face owned by a person of the same name is a split-off cluster of this one, not someone else.
    this.selectedIds.set(new Set(
      faces
        .filter((f) => f.similarity >= FIND_MORE_STRONG
          && (f.owner !== 'named' || sameName(f.person_name, this.data.personName)))
        .map((f) => f.face_id),
    ));
  }

  toggleOwner(owner: FaceOwner): void {
    const next = new Set(this.owners());
    if (next.has(owner)) {
      if (next.size === 1) return;
      next.delete(owner);
    } else {
      next.add(owner);
    }
    this.owners.set(next);
    // The narrowed searches ignore the chips: ask again, as before. Otherwise the buffer already holds every owner.
    if (this.fallback() === 'none') {
      this.showPage();
    } else {
      void this.load();
    }
  }

  setStrictness(strictness: FindMoreStrictness): void {
    if (strictness === this.strictness()) return;
    this.strictness.set(strictness);
    void this.load();
  }

  pickYear(year: string): void {
    this.year.set(year);
    void this.load();
  }

  toggle(faceId: number): void {
    this.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(faceId)) {
        next.delete(faceId);
      } else {
        next.add(faceId);
      }
      return next;
    });
  }

  /** A click toggles a face; a shift-click ticks every face from the last one clicked. */
  onFaceClick(index: number, event: MouseEvent): void {
    const faces = this.faces();
    if (event.shiftKey && this.anchor !== null && this.anchor < faces.length) {
      const [from, to] = this.anchor < index ? [this.anchor, index] : [index, this.anchor];
      this.selectedIds.update((set) => {
        const next = new Set(set);
        for (const f of faces.slice(from, to + 1)) next.add(f.face_id);
        return next;
      });
    } else {
      this.toggle(faces[index].face_id);
    }
    this.anchor = index;
  }

  /** Space toggles the focused face; handled here so the key never also clicks. */
  onFaceSpace(faceId: number, event: Event): void {
    event.preventDefault();
    this.toggle(faceId);
  }

  selectStrong(): void {
    this.selectedIds.set(new Set(this.faces().filter((f) => f.similarity >= FIND_MORE_STRONG).map((f) => f.face_id)));
  }

  selectAll(): void {
    this.selectedIds.set(new Set(this.faces().map((f) => f.face_id)));
  }

  clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  async addSelected(): Promise<void> {
    const faceIds = [...this.selectedIds()];
    if (faceIds.length === 0 || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(
        this.api.post(`/persons/${this.data.personId}/assign_faces`, { face_ids: faceIds }),
      );
      this.added += faceIds.length;
      // The faces came from photos anywhere in the library: drop every cached gallery outline.
      this.faceBoxes.clear();
      const chosen = new Set(faceIds);
      // The added faces now belong to this person, so they leave the counts.
      this.counts.update((counts) => {
        if (!counts) return counts;
        const next = { ...counts };
        for (const f of this.faces()) if (chosen.has(f.face_id)) next[f.owner] = Math.max(0, next[f.owner] - 1);
        return next;
      });
      for (const f of this.faces()) {
        if (!chosen.has(f.face_id)) this.dismissed.add(f.face_id);
      }
      this.buffer.update((list) => list.filter((f) => !chosen.has(f.face_id) && !this.dismissed.has(f.face_id)));
      if (this.visible().length === 0) {
        await this.load();
      } else {
        this.showPage();
      }
    } catch {
      this.error.set(this.i18n.t(I18N.persons.find_more_add_error));
    } finally {
      this.busy.set(false);
    }
  }

  /** Fold a whole look-alike group into this person; a named one is confirmed first. */
  async mergeGroup(group: SimilarGroup): Promise<void> {
    if (this.busy()) return;
    const name = group.name ?? '';
    if (!isUnnamedPerson(name)) {
      const ref = this.dialog.open(ConfirmDialogComponent, {
        data: {
          title: this.i18n.t(I18N.persons.find_more_merge_named_title, { name }),
          message: this.i18n.t(I18N.persons.find_more_merge_named_message,
            { name, count: group.face_count, target: this.displayName() }),
          confirmLabel: this.i18n.t(I18N.persons.find_more_merge_all),
        },
      });
      if (!(await firstValueFrom(ref.afterClosed()))) return;
    }
    this.busy.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(this.api.post('/persons/merge', { source_id: group.person_id, target_id: this.data.personId }));
    } catch {
      this.error.set(this.i18n.t(I18N.persons.find_more_merge_error));
      this.busy.set(false);
      return;
    }
    this.added += group.face_count;
    this.faceBoxes.clear();
    this.similarGroups.update((list) => list.filter((g) => g.person_id !== group.person_id));
    this.busy.set(false);
    await this.load();
  }

  close(): void {
    this.dialogRef.close({ added: this.added });
  }

  /** A 412 that is not a scan over the ceiling means no usable centroid yet; the raw detail is never shown. */
  private errorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse && err.status === 412) {
      return this.i18n.t(I18N.persons.find_more_no_centroid);
    }
    return this.i18n.t(I18N.persons.find_more_error);
  }
}

/** The server's 412 for a scan over its ceiling, as opposed to a person with no centroid. */
function tooManyFaces(err: unknown): boolean {
  if (!(err instanceof HttpErrorResponse) || err.status !== 412) return false;
  const detail = typeof err.error?.detail === 'string' ? err.error.detail : '';
  return !detail.includes('centroid');
}
