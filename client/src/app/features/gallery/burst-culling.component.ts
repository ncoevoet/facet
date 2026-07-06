import { Component, inject, signal, computed, effect, viewChild, ElementRef, OnDestroy, WritableSignal, HostListener, TemplateRef } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { DecimalPipe, NgClass, NgTemplateOutlet } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatSliderModule } from '@angular/material/slider';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { GalleryStore } from './gallery.store';
import { SceneDatePipe, MomentLabelPipe, MomentUncertainPipe } from '../scenes/scenes.pipes';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, FaceThumbnailUrlPipe, ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { I18nService } from '../../core/services/i18n.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { isTypingContext } from '../../shared/utils/keyboard';
import { createLoupeState } from '../../shared/utils/loupe-state';
import { SyncedZoomComponent, ZoomState, FIT_ZOOM } from './synced-zoom.component';
import { CompareFiltersService } from '../comparison/compare-filters.service';
import { firstValueFrom } from 'rxjs';
import { I18N } from '../../core/i18n/keys';
import {
  IsKeptPipe, IsDecidedPipe, IsConfirmedPipe, IsPassingPipe, PassCountdownPipe,
  CullReasonPipe, FacesForPathPipe, FacePoorExpressionPipe, FaceRingClassPipe,
  FaceDimmedPipe, WeightRemainingPipe, CullGroupIconPipe, CullGroupLabelPipe,
  BetterInGroupPipe, CullingGroup, CullingFace, FaceThresholds,
} from './burst-culling.pipes';

interface CullingGroupsResponse {
  groups: CullingGroup[];
  total_groups: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/** Response of POST /api/culling/auto (dry-run preview and apply share the shape). */
interface AutoCullResponse {
  groups_processed: number;
  kept: number;
  rejected: number;
  highlights_added: number;
  dry_run: boolean;
  preview: { group_id: number; type: string; keep_paths: string[]; reject_paths: string[]; best_path: string }[];
  preview_truncated: boolean;
}

/** A genre culling preset (GET /api/culling/profiles) bundling the culling knobs. */
interface CullProfile {
  id: string;
  label_key: string;
  strictness: number | null;
  eyes_closed_max: number | null;
  poor_expression_min: number | null;
  keep_min_per_group: number;
  similarity_threshold: number | null;
}
interface CullProfilesResponse { profiles: CullProfile[]; default: string; }

/** GET /api/culling/profiles/suggest — dominant-moment preset suggestion for a scope. */
interface ProfileSuggestion { profile: string | null; moment: string | null; share: number; total: number; }

// Per-user culling toolbar preferences, persisted so the page reopens the way
// the user left it. The URL query param (deep links / "Cull this scene") still
// overrides the stored granularity.
const CULL_GROUP_BY_KEY = 'facet_culling_group_by';
const CULL_SORT_KEY = 'facet_culling_sort';
const CULL_CATEGORY_KEY = 'facet_culling_category';
const CULL_FACE_EYES_KEY = 'facet_culling_face_eyes_min';
const CULL_FACE_SMILE_KEY = 'facet_culling_face_smile_min';
const CULL_PROFILE_KEY = 'facet_culling_profile';

/** Stored face-panel slider value (0-10); 0 = highlight filter off. */
function readStoredFaceMin(key: string): number {
  const v = Number(localStorage.getItem(key));
  return Number.isFinite(v) && v >= 0 && v <= 10 ? v : 0;
}
const GROUP_BY_VALUES = ['all', 'burst', 'similar', 'scene'] as const;
type GroupBy = typeof GROUP_BY_VALUES[number];
const SORT_VALUES = ['easiest', 'redundant', 'best', 'recent', 'needs_comparisons'];

function readStoredGroupBy(): GroupBy {
  const v = localStorage.getItem(CULL_GROUP_BY_KEY);
  return (GROUP_BY_VALUES as readonly string[]).includes(v ?? '') ? v as GroupBy : 'all';
}

function readStoredSort(): string {
  const v = localStorage.getItem(CULL_SORT_KEY);
  return v && SORT_VALUES.includes(v) ? v : 'easiest';
}

/** Lightweight scene shape for the album→scene scope cascade (GET /scenes?summary=true). */
interface SceneSummary {
  scene_id: number;
  start: string | null;
  end: string | null;
  count: number;
  moment?: string | null;
}

/** Minimal read-shape of GET /comparison/stats needed for the per-category weight-tuning chip. */
interface ComparisonStatsLite {
  category_breakdown?: { category: string; count: number }[];
  min_comparisons_for_optimization?: number;
}

interface ShortcutRow {
  keys: string[];
  labelKey: string;
}

@Component({
  selector: 'app-burst-culling',
  imports: [
    DecimalPipe,
    NgClass,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatSliderModule,
    TranslatePipe,
    SceneDatePipe,
    MomentLabelPipe,
    MomentUncertainPipe,
    LoupeDirective,
    ThumbnailUrlPipe,
    FaceThumbnailUrlPipe,
    ImageUrlPipe,
    SyncedZoomComponent,
    IsKeptPipe,
    IsDecidedPipe,
    IsConfirmedPipe,
    IsPassingPipe,
    PassCountdownPipe,
    CullReasonPipe,
    FacesForPathPipe,
    FacePoorExpressionPipe,
    FaceRingClassPipe,
    FaceDimmedPipe,
    WeightRemainingPipe,
    CullGroupIconPipe,
    CullGroupLabelPipe,
    BetterInGroupPipe,
    InfiniteScrollDirective,
    NgTemplateOutlet,
  ],
  template: `
    <div class="px-2 pt-2 md:px-8 md:pt-3 mx-auto w-full lg:max-w-[96%] h-full flex flex-col">
      <!-- Header (sticky: only the group list below scrolls) -->
      <!-- The toolbar projects into the global header on lg+ (HeaderSlotService) and
           renders as a fixed bottom bar on small screens (same #cullToolbar template).
           When scoped, the back button is its first element (see below). -->
      <div class="lg:hidden">
        <ng-container [ngTemplateOutlet]="cullToolbar" />
      </div>
      <ng-template #cullToolbar>
        <div class="flex items-center gap-3 md:gap-4
                    max-lg:fixed max-lg:bottom-0 max-lg:left-0 max-lg:right-0 max-lg:z-40
                    max-lg:flex-nowrap max-lg:overflow-x-auto max-lg:px-3 max-lg:py-2
                    max-lg:bg-[var(--mat-sys-surface-container)] max-lg:border-t max-lg:border-[var(--mat-sys-outline-variant)]
                    max-lg:shadow-lg safe-area-pb">
          @if (scoped()) {
            <button mat-icon-button (click)="exitScope()"
                    [matTooltip]="I18N.culling.exit_scene | translate"
                    [attr.aria-label]="I18N.culling.exit_scene | translate">
              <mat-icon>arrow_back</mat-icon>
            </button>
          }
          <!-- Controls ordered by impact: granularity → sort → category →
               thresholds → exclude → scope → status/loupe/help. -->
          <button mat-icon-button [matMenuTriggerFor]="cullGroupByMenu"
                  [class.!text-[var(--mat-sys-primary)]]="groupBy() !== 'all'"
                  [matTooltip]="I18N.culling.group_by.label | translate"
                  [attr.aria-label]="I18N.culling.group_by.label | translate">
            <mat-icon>{{ groupBy() | cullGroupIcon }}</mat-icon>
          </button>
          <mat-menu #cullGroupByMenu="matMenu">
            <button mat-menu-item (click)="onGroupByChange('all')">
              <mat-icon>{{ 'all' | cullGroupIcon }}</mat-icon>
              <span [class.font-bold]="groupBy() === 'all'">{{ I18N.culling.group_by.all | translate }}</span>
            </button>
            <button mat-menu-item (click)="onGroupByChange('burst')">
              <mat-icon>{{ 'burst' | cullGroupIcon }}</mat-icon>
              <span [class.font-bold]="groupBy() === 'burst'">{{ I18N.culling.group_by.bursts | translate }}</span>
            </button>
            <button mat-menu-item (click)="onGroupByChange('similar')">
              <mat-icon>{{ 'similar' | cullGroupIcon }}</mat-icon>
              <span [class.font-bold]="groupBy() === 'similar'">{{ I18N.culling.group_by.similar | translate }}</span>
            </button>
            @if (store.config()?.features?.show_scenes || groupBy() === 'scene') {
              <button mat-menu-item (click)="onGroupByChange('scene')">
                <mat-icon>{{ 'scene' | cullGroupIcon }}</mat-icon>
                <span [class.font-bold]="groupBy() === 'scene'">{{ I18N.culling.group_by.scenes | translate }}</span>
              </button>
            }
          </mat-menu>
          @if (groupBy() !== 'scene') {
            <button mat-icon-button [matMenuTriggerFor]="cullSortMenu"
                    [class.!text-[var(--mat-sys-primary)]]="sortMode() !== 'easiest'"
                    [matTooltip]="I18N.culling.sort.label | translate"
                    [attr.aria-label]="I18N.culling.sort.label | translate">
              <mat-icon>sort</mat-icon>
            </button>
            <mat-menu #cullSortMenu="matMenu">
              @for (m of sortModes; track m) {
                <button mat-menu-item (click)="onSortChange(m)">
                  <span [class.font-bold]="sortMode() === m">{{ 'culling.sort.' + m | translate }}</span>
                </button>
              }
            </mat-menu>
          }
          @if (categoryOptions().length > 0) {
            <button mat-icon-button [matMenuTriggerFor]="cullCategoryMenu"
                    [class.!text-[var(--mat-sys-primary)]]="categoryFilter() !== ''"
                    [matTooltip]="I18N.culling.filter_category | translate"
                    [attr.aria-label]="I18N.culling.filter_category | translate">
              <mat-icon>category</mat-icon>
            </button>
            <mat-menu #cullCategoryMenu="matMenu">
              <button mat-menu-item (click)="onCategoryFilterChange('')">
                <span [class.font-bold]="categoryFilter() === ''">{{ I18N.culling.all_categories | translate }}</span>
              </button>
              @for (c of categoryOptions(); track c) {
                <button mat-menu-item (click)="onCategoryFilterChange(c)">
                  <span [class.font-bold]="categoryFilter() === c">{{ 'category_names.' + c | translate }}</span>
                </button>
              }
            </mat-menu>
          }
          @if (groupBy() === 'similar' || groupBy() === 'all') {
            <div class="hidden lg:flex items-center gap-2">
              <span class="text-xs opacity-60">{{ I18N.culling.threshold | translate }}</span>
              <mat-slider class="!w-28 !min-w-0" [min]="70" [max]="95" [step]="5" [discrete]="true">
                <input matSliderThumb [value]="similarityThreshold()" (valueChange)="onThresholdChange($event)" [attr.aria-label]="I18N.culling.threshold | translate" />
              </mat-slider>
              <span class="text-xs font-medium w-8">{{ similarityThreshold() }}%</span>
            </div>
            <button mat-icon-button class="lg:!hidden" [matMenuTriggerFor]="thresholdMenu"
                    [matTooltip]="I18N.culling.threshold | translate"
                    [attr.aria-label]="I18N.culling.threshold | translate">
              <mat-icon>compare</mat-icon>
            </button>
            <mat-menu #thresholdMenu="matMenu">
              <div class="flex items-center gap-2 px-4 py-3" (click)="$event.stopPropagation()" (keydown)="$event.stopPropagation()">
                <span class="text-xs opacity-60">{{ I18N.culling.threshold | translate }}</span>
                <mat-slider class="!w-28 !min-w-0" [min]="70" [max]="95" [step]="5" [discrete]="true">
                  <input matSliderThumb [value]="similarityThreshold()" (valueChange)="onThresholdChange($event)" [attr.aria-label]="I18N.culling.threshold | translate" />
                </mat-slider>
                <span class="text-xs font-medium w-8">{{ similarityThreshold() }}%</span>
              </div>
            </mat-menu>
          }
          @if (cullProfiles().length > 0) {
            <button mat-stroked-button [matMenuTriggerFor]="profileMenu"
                    [class.!text-[var(--mat-sys-primary)]]="selectedProfile() !== ''"
                    [matTooltip]="I18N.culling.profiles.tooltip | translate" class="!text-xs">
              <mat-icon class="!text-base">theaters</mat-icon>
              {{ selectedProfileLabel() | translate }}
            </button>
            <mat-menu #profileMenu="matMenu">
              @for (p of cullProfiles(); track p.id) {
                <button mat-menu-item (click)="applyProfile(p)">
                  <span [class.font-bold]="selectedProfile() === p.id">{{ p.label_key | translate }}</span>
                </button>
              }
            </mat-menu>
            @if (suggestedProfile(); as sp) {
              <button mat-stroked-button (click)="applySuggestion()" class="!text-xs !border-dashed"
                      [matTooltip]="I18N.culling.profiles.tooltip | translate"
                      [attr.aria-label]="I18N.culling.profiles.apply | translate">
                <mat-icon class="!text-base">auto_awesome</mat-icon>
                {{ I18N.culling.profiles.suggested | translate:{ name: (sp.label_key | translate) } }}
              </button>
            }
          }
          <div class="hidden lg:flex items-center gap-2" [matTooltip]="I18N.culling.strictness_tooltip | translate">
            <span class="text-xs opacity-60">{{ I18N.culling.strictness | translate }}</span>
            <mat-slider class="!w-28 !min-w-0" [min]="0" [max]="100" [step]="10" [discrete]="true">
              <input matSliderThumb [value]="strictness()" (valueChange)="onStrictnessChange($event)" [attr.aria-label]="I18N.culling.strictness | translate" />
            </mat-slider>
            <span class="text-xs font-medium w-8">{{ strictness() }}%</span>
          </div>
          <button mat-icon-button class="lg:!hidden" [matMenuTriggerFor]="strictnessMenu"
                  [matTooltip]="I18N.culling.strictness | translate"
                  [attr.aria-label]="I18N.culling.strictness | translate">
            <mat-icon>tune</mat-icon>
          </button>
          <mat-menu #strictnessMenu="matMenu">
            <div class="flex items-center gap-2 px-4 py-3" (click)="$event.stopPropagation()" (keydown)="$event.stopPropagation()">
              <span class="text-xs opacity-60">{{ I18N.culling.strictness | translate }}</span>
              <mat-slider class="!w-28 !min-w-0" [min]="0" [max]="100" [step]="10" [discrete]="true">
                <input matSliderThumb [value]="strictness()" (valueChange)="onStrictnessChange($event)" [attr.aria-label]="I18N.culling.strictness | translate" />
              </mat-slider>
              <span class="text-xs font-medium w-8">{{ strictness() }}%</span>
            </div>
          </mat-menu>
          <button mat-icon-button (click)="onExcludeRejectedChange(!excludeRejected())"
                  [class.!text-[var(--mat-sys-primary)]]="excludeRejected()"
                  [attr.aria-pressed]="excludeRejected()"
                  [matTooltip]="I18N.culling.exclude_rejected | translate"
                  [attr.aria-label]="I18N.culling.exclude_rejected | translate">
            <mat-icon>{{ excludeRejected() ? 'visibility_off' : 'visibility' }}</mat-icon>
          </button>
          @if (albums().length > 0) {
            <button mat-stroked-button [matMenuTriggerFor]="scopeMenu"
                    [matTooltip]="I18N.culling.scope | translate" class="!text-xs">
              <mat-icon class="!text-base">filter_alt</mat-icon>
              {{ scopeLabel() ?? (I18N.culling.scope_whole_library | translate) }}
            </button>
          }
          <mat-menu #scopeMenu="matMenu">
            <button mat-menu-item (click)="scopeWholeLibrary()">
              {{ I18N.culling.scope_whole_library | translate }}
            </button>
            @for (a of albums(); track a.id) {
              <button mat-menu-item [matMenuTriggerFor]="sceneMenu" (menuOpened)="loadAlbumScenes(a)">
                {{ a.name }}
              </button>
            }
          </mat-menu>
          <mat-menu #sceneMenu="matMenu">
            <button mat-menu-item (click)="scopeAlbumWhole()">
              {{ I18N.culling.scope_whole_album | translate }}
            </button>
            @if (loadingScenes()) {
              <div class="flex justify-center px-4 py-2"><mat-spinner diameter="18" /></div>
            } @else {
              @for (s of expandedScenes(); track s.scene_id) {
                <button mat-menu-item (click)="scopeAlbumScene(s)">
                  {{ s.start | sceneDate }} · {{ s.count }}@if (s.moment | momentLabel; as ml) { · {{ ml }}}
                </button>
              }
            }
          </mat-menu>
          <button mat-icon-button (click)="loupeActive.set(!loupeActive())"
                  [class.!text-[var(--mat-sys-primary)]]="loupeActive()"
                  [attr.aria-pressed]="loupeActive()"
                  [matTooltip]="I18N.culling.loupe_hint | translate"
                  [attr.aria-label]="I18N.culling.loupe | translate">
            <mat-icon>{{ loupeActive() ? 'zoom_in' : 'search' }}</mat-icon>
          </button>
          @if (loupeActive()) {
            <mat-slider class="!w-28 !min-w-0" [min]="2" [max]="8" [step]="1" [discrete]="true">
              <input matSliderThumb [value]="loupeZoom()" (valueChange)="loupeZoom.set($event)"
                     [attr.aria-label]="I18N.culling.loupe | translate" />
            </mat-slider>
          }
          @if (auth.isEdition()) {
            <button mat-icon-button (click)="openAutoCull()" [disabled]="autoCullLoading()"
                    [matTooltip]="I18N.culling.auto_cull.tooltip | translate"
                    [attr.aria-label]="I18N.culling.auto_cull.button | translate">
              <mat-icon>auto_fix_high</mat-icon>
            </button>
          }
          @if (unconfirmedCount() > 0) {
            <button mat-flat-button (click)="confirmAllRemaining()" [disabled]="confirming()" class="!hidden lg:!inline-flex !rounded-md shrink-0">
              <mat-icon>done_all</mat-icon>
              {{ I18N.culling.confirm_all | translate }} ({{ unconfirmedCount() }})
            </button>
          }
        </div>
      </ng-template>

      @if (pageHelp.open()) {
        <div class="shrink-0 p-3 mb-3 rounded-lg bg-[var(--mat-sys-surface-container)] space-y-3">
          <p class="text-sm opacity-80">{{ I18N.culling.help_text | translate }}</p>
          @if (rankerComparisons() !== null) {
            <span class="text-xs opacity-70 flex items-center gap-1"
                  [matTooltip]="I18N.culling.my_taste_tooltip | translate">
              <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-[var(--mat-sys-primary)]">auto_awesome</mat-icon>
              {{ (rankerTrained() ? I18N.culling.my_taste_trained : I18N.culling.my_taste_learning)
                 | translate:{ count: (rankerComparisons() ?? 0) } }}
            </span>
          }
          <div class="flex flex-wrap gap-x-10 gap-y-3">
            @for (section of shortcutSections; track section.titleKey) {
              <div>
                <div class="text-xs font-semibold uppercase opacity-50 mb-1.5">{{ section.titleKey | translate }}</div>
                <div class="space-y-1">
                  @for (row of section.rows; track row.labelKey) {
                    <div class="flex items-center gap-2 text-xs">
                      <span class="flex gap-1">
                        @for (k of row.keys; track k) {
                          <kbd class="px-1.5 py-0.5 rounded border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container-high)] text-xs font-mono">{{ k }}</kbd>
                        }
                      </span>
                      <span class="opacity-80">{{ row.labelKey | translate }}</span>
                    </div>
                  }
                </div>
              </div>
            }
          </div>
        </div>
      }

      <!-- Scrollable group list; the header above stays fixed -->
      <div class="flex-1 min-h-0 overflow-y-auto -mx-4 px-4 md:-mx-8 md:px-8 pb-4 max-lg:pb-24" data-culling-scroll>
      <!-- Content -->
      @if (loading()) {
        <div class="flex justify-center items-center py-20">
          <mat-spinner diameter="40" />
        </div>
      } @else if (visibleGroups().length === 0) {
        <p class="text-center py-20 opacity-60">{{ (scoped() ? I18N.culling.scene_complete : I18N.culling.no_bursts) | translate }}</p>
      } @else {
        <div class="space-y-3 pb-4">
          @for (group of visibleGroups(); track group.group_id + '_' + group.type; let i = $index) {
            <div class="rounded-xl border-2 overflow-hidden transition-colors duration-300"
                 [attr.data-gidx]="i"
                 [ngClass]="i === selectedGroupIndex()
                   ? 'bg-[var(--mat-sys-surface-container-high)] border-[var(--mat-sys-surface-container-high)]'
                   : 'bg-[var(--mat-sys-surface-container)] border-[var(--mat-sys-surface-container)]'">
              @if (group.start) {
                <div class="flex items-center gap-2 px-4 pt-2 text-xs">
                  <mat-icon class="!text-base text-[var(--mat-sys-primary)]">schedule</mat-icon>
                  <span class="opacity-80">{{ group.start | sceneDate }}</span>
                  @if (group.moment | momentLabel; as ml) {
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[var(--mat-sys-primary)]/20 text-[var(--mat-sys-primary)]"
                          [class.!opacity-50]="group.moment_confidence | momentUncertain:momentConfidenceMin()">
                      <mat-icon class="!text-sm !w-4 !h-4 !leading-4">auto_awesome</mat-icon>{{ ml }}@if (group.moment_confidence | momentUncertain:momentConfidenceMin()) { <span class="opacity-80">({{ I18N.moments.uncertain | translate }})</span> }
                    </span>
                  }
                </div>
              }
              <!-- Photos -->
              <div class="flex gap-2 md:gap-3 overflow-x-auto px-2 py-3 items-center transition-opacity duration-300 [&::-webkit-scrollbar]:h-2.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[var(--mat-sys-outline-variant)] [&::-webkit-scrollbar-track]:bg-transparent"
                   [class.pointer-events-none]="(group | isConfirmed:confirmedGroups())"
                   [class.opacity-40]="(group | isConfirmed:confirmedGroups())">
                @for (photo of group.photos; track photo.path; let pIdx = $index) {
                  <div class="group/photo relative cursor-pointer rounded-lg overflow-hidden border-2 transition-colors flex-shrink-0 h-full max-w-[480px]"
                       [class.border-green-500]="photo.path | isKept:selectionsMap():group.group_id"
                       [class.border-red-500]="!(photo.path | isKept:selectionsMap():group.group_id) && (photo.path | isDecided:selectionsMap():group.group_id)"
                       [class.border-transparent]="!(photo.path | isDecided:selectionsMap():group.group_id)"
                       role="button"
                       tabindex="0"
                       [attr.aria-label]="photo.filename"
                       [attr.aria-pressed]="photo.path | isKept:selectionsMap():group.group_id"
                       (click)="toggleSelection(photo.path, group)"
                       (keydown.enter)="toggleSelection(photo.path, group); $event.stopPropagation()"
                       (keydown.space)="toggleSelection(photo.path, group); $event.stopPropagation(); $event.preventDefault()"
                       (dblclick)="selectExclusive(photo.path, group); $event.stopPropagation()">
                    <img [src]="photo.path | thumbnailUrl:640"
                         [appLoupe]="photo.path | imageUrl:true"
                         [loupeActive]="loupeActive()"
                         [loupeZoom]="loupeZoom()"
                         class="h-72 md:h-96 w-auto object-contain" [alt]="photo.filename" loading="lazy" />
                    @if (photo.path === group.best_path) {
                      <div class="absolute top-2 left-2 px-2 py-0.5 rounded bg-green-600 text-white text-xs font-bold">
                        {{ I18N.culling.auto_best | translate }}
                      </div>
                    } @else if (photo.cull_reason; as reason) {
                      <div class="absolute top-2 left-2 px-2 py-0.5 rounded bg-black/70 text-white text-xs font-medium max-w-[160px] truncate">
                        {{ reason | cullReason }}
                      </div>
                    }
                    @if (photo.path | betterInGroup:group.best_path) {
                      <div class="absolute top-9 left-2 w-6 h-6 rounded-full bg-amber-500/90 inline-flex items-center justify-center"
                           role="img"
                           [matTooltip]="I18N.culling.auto_cull.better_tooltip | translate"
                           [attr.aria-label]="I18N.culling.auto_cull.better_tooltip | translate">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-white">stars</mat-icon>
                      </div>
                    }
                    @if (photo.path | isKept:selectionsMap():group.group_id) {
                      <div class="absolute top-2 right-2 w-7 h-7 rounded-full bg-green-600 inline-flex items-center justify-center">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-white">check</mat-icon>
                      </div>
                    } @else if (photo.path | isDecided:selectionsMap():group.group_id) {
                      <div class="absolute inset-0 inline-flex items-center justify-center bg-red-900/30 pointer-events-none">
                        <mat-icon class="!text-3xl !w-9 !h-9 !leading-9 text-red-300">close</mat-icon>
                      </div>
                    }
                    <div class="absolute bottom-2 left-2 px-2 py-0.5 rounded bg-black/60 text-white text-xs font-medium">
                      {{ photo.aggregate | number:'1.1-1' }}
                    </div>
                    @if (photo.is_blink) {
                      <div class="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-yellow-600 text-white text-xs font-bold">
                        {{ I18N.ui.badges.blink | translate }}
                      </div>
                    }
                    @if (!(photo.path | isKept:selectionsMap():group.group_id)) {
                      <button class="absolute top-2 right-2 w-7 h-7 rounded-full bg-black/60 inline-flex items-center justify-center opacity-0 group-hover/photo:opacity-100 transition-opacity"
                              [matTooltip]="I18N.culling.view_detail | translate"
                              [attr.aria-label]="I18N.culling.view_detail | translate"
                              (click)="openDetail($event, photo.path)">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-white">info</mat-icon>
                      </button>
                    }
                  </div>
                }
              </div>

              <!-- Group actions -->
              <div class="flex flex-wrap items-center gap-x-2 gap-y-2 px-2 py-2 border-t border-[var(--mat-sys-outline-variant)]">
                <mat-icon class="inline-flex !text-base !w-4 !h-4 !leading-4 opacity-60"
                          [matTooltip]="group.type | cullGroupLabel | translate"
                          [attr.aria-label]="group.type | cullGroupLabel | translate">{{ group.type | cullGroupIcon }}</mat-icon>
                <span class="text-xs opacity-50">{{ group.count }} {{ I18N.culling.photos | translate }}</span>
                @if (group.category; as category) {
                  @if (comparisonStats(); as stats) {
                    @if ((category | weightRemaining:stats); as remaining) {
                      <button class="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-[var(--mat-sys-surface-container-high)] transition-colors"
                              (click)="tuneCategory(category)"
                              [matTooltip]="I18N.culling.weight_remaining | translate:{ count: remaining }"
                              [attr.aria-label]="I18N.culling.weight_remaining | translate:{ count: remaining }">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-60">tune</mat-icon>
                      </button>
                    } @else {
                      <button class="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-[var(--mat-sys-surface-container-high)] transition-colors"
                              (click)="tuneCategory(category)"
                              [matTooltip]="I18N.culling.weight_ready | translate"
                              [attr.aria-label]="I18N.culling.weight_ready | translate">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-green-500">tune</mat-icon>
                      </button>
                    }
                  }
                  <span class="text-xs opacity-50">{{ 'category_names.' + category | translate }}</span>
                }
                @if ((group | isConfirmed:confirmedGroups())) {
                  <span class="inline-flex items-center gap-1 text-xs text-green-500 font-medium">
                    <mat-icon class="inline-flex !text-sm !w-4 !h-4 !leading-4">check_circle</mat-icon>
                    {{ I18N.culling.confirmed_badge | translate }}
                  </span>
                }
                <div class="flex gap-2 ml-auto">
                  @if (group | isPassing:passingGroups()) {
                    <div class="relative overflow-hidden rounded-md">
                      <button mat-stroked-button (click)="cancelPass(group)" class="!h-8 !text-sm !rounded-md relative z-10"
                              [matTooltip]="I18N.culling.cancel_restore | translate">
                        {{ I18N.culling.cancel_pass | translate }} ({{ group | passCountdown:passingGroups() }}s)
                      </button>
                      <div class="absolute inset-0 bg-[var(--mat-sys-outline-variant)] opacity-30 origin-right transition-transform duration-1000 ease-linear"
                           [style.transform]="'scaleX(' + ((group | passCountdown:passingGroups()) / passCountdownSeconds) + ')'"></div>
                    </div>
                  } @else {
                    <button mat-icon-button (click)="openLightbox(group, 0)"
                            [matTooltip]="I18N.culling.darkroom_tooltip | translate"
                            [attr.aria-label]="I18N.culling.darkroom | translate">
                      <mat-icon>fullscreen</mat-icon>
                    </button>
                    <button mat-icon-button (click)="skipGroup(group)"
                            [matTooltip]="I18N.culling.skip_tooltip | translate"
                            [attr.aria-label]="I18N.culling.skip | translate">
                      <mat-icon>skip_next</mat-icon>
                    </button>
                    <button mat-icon-button (click)="confirmGroup(group)" [disabled]="confirming()"
                            [matTooltip]="I18N.culling.confirm_tooltip | translate"
                            [attr.aria-label]="I18N.culling.confirm | translate">
                      <mat-icon>check_circle</mat-icon>
                    </button>
                  }
                </div>
              </div>
            </div>
          }

          <!-- Infinite scroll sentinel -->
          @if (hasMore()) {
            <div appInfiniteScroll scrollRoot="[data-culling-scroll]" (scrollReached)="onScrollReached()" class="flex justify-center py-6">
              @if (loadingMore()) {
                <mat-spinner diameter="32" />
              }
            </div>
          }
        </div>
      }
      </div>

      <!-- Sticky footer (small screens only): on lg+ the action moves into the top toolbar -->
      @if (unconfirmedCount() > 0) {
        <div class="lg:!hidden shrink-0 flex justify-center py-3 border-t border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface)]">
          <button mat-flat-button (click)="confirmAllRemaining()" [disabled]="confirming()" class="!px-6 !rounded-md">
            <mat-icon>done_all</mat-icon>
            {{ I18N.culling.confirm_all | translate }} ({{ unconfirmedCount() }})
          </button>
        </div>
      }
    </div>

    <!-- Lightbox overlay -->
    @if (lightboxGroup(); as lbGroup) {
      <div #lightboxDialog class="fixed inset-0 z-[100] bg-black/95 flex flex-col"
           role="dialog"
           aria-modal="true"
           tabindex="-1"
           (click)="closeLightbox()"
           (keydown.escape)="closeLightbox()">
        <!-- Header -->
        <div class="flex items-center justify-between gap-4 px-4 py-2.5 text-white text-sm">
          <div class="opacity-70 shrink-0">
            {{ lightboxIndex() + 1 }} / {{ lbGroup.photos.length }}
          </div>
          <div class="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-sm">
            @for (row of darkroomShortcuts; track row.labelKey) {
              <span class="inline-flex items-center gap-1.5">
                <span class="flex gap-1">
                  @for (k of row.keys; track k) {
                    <kbd class="px-1.5 py-0.5 rounded border border-white/30 bg-white/10 text-xs font-mono leading-none">{{ k }}</kbd>
                  }
                </span>
                <span class="opacity-80">{{ row.labelKey | translate }}</span>
              </span>
            }
          </div>
          <div class="flex items-center gap-1 shrink-0" role="presentation"
               (click)="$event.stopPropagation()" (keydown)="$event.stopPropagation()">
            <button mat-icon-button [class.!text-white]="compareMode() !== 'single'"
                    [class.!text-[var(--mat-sys-primary)]]="compareMode() === 'single'"
                    [matTooltip]="I18N.culling.compare.single | translate"
                    (click)="setCompareMode('single')"><mat-icon>crop_original</mat-icon></button>
            <button mat-icon-button [class.!text-white]="compareMode() !== '2up'"
                    [class.!text-[var(--mat-sys-primary)]]="compareMode() === '2up'"
                    [matTooltip]="I18N.culling.compare['2up'] | translate"
                    (click)="setCompareMode('2up')"><mat-icon>splitscreen</mat-icon></button>
            <button mat-icon-button [class.!text-white]="compareMode() !== '4up'"
                    [class.!text-[var(--mat-sys-primary)]]="compareMode() === '4up'"
                    [matTooltip]="I18N.culling.compare['4up'] | translate"
                    (click)="setCompareMode('4up')"><mat-icon>grid_view</mat-icon></button>
          </div>
          <button mat-icon-button
                  [matTooltip]="I18N.slideshow.fullscreen | translate"
                  [attr.aria-label]="I18N.slideshow.fullscreen | translate"
                  (click)="toggleFullscreen(); $event.stopPropagation()" class="!text-white">
            <mat-icon>{{ isFullscreen() ? 'fullscreen_exit' : 'fullscreen' }}</mat-icon>
          </button>
          <button mat-icon-button
                  [attr.aria-label]="I18N.dialog.cancel | translate"
                  (click)="closeLightbox(); $event.stopPropagation()" class="!text-white">
            <mat-icon>close</mat-icon>
          </button>
        </div>
        <!-- Image -->
        @if (lbGroup.photos[lightboxIndex()]; as lbPhoto) {
          @if (compareMode() === 'single') {
            <app-synced-zoom class="flex-1 min-h-0"
                             role="presentation"
                             (click)="$event.stopPropagation()"
                             (keydown)="$event.stopPropagation()"
                             [src]="lbPhoto.path | thumbnailUrl:1920"
                             [fullResSrc]="lbPhoto.path | imageUrl:true"
                             [zoom]="zoom()"
                             (zoomChange)="zoom.set($event)"
                             [alt]="lbPhoto.filename" />
          } @else {
            <div class="flex-1 grid grid-cols-2 gap-1 overflow-hidden p-1"
                 [class.grid-rows-2]="compareMode() === '4up'"
                 role="presentation"
                 (click)="$event.stopPropagation()"
                 (keydown)="$event.stopPropagation()">
              @for (photo of compareFrames(); track photo.path) {
                <div class="relative w-full h-full min-h-0 rounded overflow-hidden"
                     [class.ring-2]="photo.path === lbPhoto.path"
                     [class.ring-inset]="photo.path === lbPhoto.path"
                     [class.ring-amber-400]="photo.path === lbPhoto.path">
                  <app-synced-zoom class="w-full h-full min-h-0"
                                   [src]="photo.path | thumbnailUrl:1920"
                                   [fullResSrc]="photo.path | imageUrl:true"
                                   [zoom]="zoom()"
                                   (zoomChange)="zoom.set($event)"
                                   [alt]="photo.filename" />
                  @if (photo.path | isKept:selectionsMap():lbGroup.group_id) {
                    <mat-icon class="absolute top-1 left-1 !text-base !w-5 !h-5 !leading-5 rounded-full bg-black/60 text-green-400">check</mat-icon>
                  } @else if (photo.path | isDecided:selectionsMap():lbGroup.group_id) {
                    <mat-icon class="absolute top-1 left-1 !text-base !w-5 !h-5 !leading-5 rounded-full bg-black/60 text-red-400">close</mat-icon>
                  }
                </div>
              }
            </div>
          }
          <!-- Footer status -->
          <div class="px-4 py-3 text-center"
               role="presentation"
               (click)="$event.stopPropagation()"
               (keydown)="$event.stopPropagation()">
            @if (lbPhoto.path | isKept:selectionsMap():lbGroup.group_id) {
              <span class="inline-flex items-center gap-1 text-green-400 text-sm">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">check</mat-icon>
                {{ I18N.culling.lightbox.kept | translate }}
              </span>
            } @else if (lbPhoto.path | isDecided:selectionsMap():lbGroup.group_id) {
              <span class="inline-flex items-center gap-1 text-red-400 text-sm">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">close</mat-icon>
                {{ I18N.culling.lightbox.rejected | translate }}
              </span>
            } @else {
              <span class="text-white/40 text-sm">{{ I18N.culling.lightbox.undecided | translate }}</span>
            }
          </div>
        }

        <!-- Face / expression close-up grid -->
        @if (faceGridHasFaces()) {
          <div class="border-t border-white/10 px-4 py-3 overflow-x-auto"
               role="presentation"
               (click)="$event.stopPropagation()"
               (keydown)="$event.stopPropagation()">
            <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2">
              <div class="text-white/50 text-xs">{{ I18N.culling.face_grid_title | translate }}</div>
              <div class="flex items-center gap-2"
                   [matTooltip]="'culling.face_eyes_min_tooltip' | translate">
                <span class="text-white/50 text-xs">{{ 'culling.face_eyes_min' | translate }}</span>
                <mat-slider class="!w-24 !min-w-0" [min]="0" [max]="10" [step]="1" [discrete]="true">
                  <input matSliderThumb [value]="faceEyesMin()" (valueChange)="onFaceEyesMinChange($event)"
                         [attr.aria-label]="'culling.face_eyes_min' | translate" />
                </mat-slider>
                <span class="text-white/70 text-xs font-medium w-4">{{ faceEyesMin() }}</span>
              </div>
              <div class="flex items-center gap-2"
                   [matTooltip]="'culling.face_smile_min_tooltip' | translate">
                <span class="text-white/50 text-xs">{{ 'culling.face_smile_min' | translate }}</span>
                <mat-slider class="!w-24 !min-w-0" [min]="0" [max]="10" [step]="1" [discrete]="true">
                  <input matSliderThumb [value]="faceSmileMin()" (valueChange)="onFaceSmileMinChange($event)"
                         [attr.aria-label]="'culling.face_smile_min' | translate" />
                </mat-slider>
                <span class="text-white/70 text-xs font-medium w-4">{{ faceSmileMin() }}</span>
              </div>
            </div>
            <div class="flex gap-3 items-start">
              @for (photo of lbGroup.photos; track photo.path; let pIdx = $index) {
                @if ((photo.path | facesForPath:faceMap()).length > 0) {
                  <div class="flex flex-col items-center gap-1 flex-shrink-0">
                    <div class="flex gap-1">
                      @for (face of photo.path | facesForPath:faceMap(); track face.id) {
                        <div class="relative">
                          <img [src]="face.id | faceThumbnailUrl"
                               class="w-16 h-16 rounded object-cover ring-2 ring-inset transition-opacity"
                               [ngClass]="face | faceRingClass:faceThresholds()"
                               [class.opacity-40]="face | faceDimmed:faceEyesMin():faceSmileMin()"
                               [alt]="photo.filename" loading="lazy" />
                          @if (face.confidence !== null && face.confidence !== undefined) {
                            <div class="absolute top-0 right-0 bg-black/60 text-white/80 text-[9px] leading-none px-1 py-0.5 rounded-bl">
                              {{ face.confidence | number:'1.0-2' }}
                            </div>
                          }
                          @if (face.is_blink) {
                            <div class="absolute bottom-0 inset-x-0 bg-yellow-600/90 text-white text-[10px] leading-tight text-center font-bold py-0.5">
                              {{ I18N.ui.badges.blink | translate }}
                            </div>
                          } @else if (face | facePoorExpression:faceThresholds()) {
                            <div class="absolute bottom-0 inset-x-0 bg-orange-600/80 text-white text-[10px] leading-tight text-center font-bold py-0.5">
                              {{ I18N.culling.face_badge_expression | translate }}
                            </div>
                          }
                          <div class="absolute bottom-1 right-1 px-1 py-0.5 rounded bg-black/70 text-white text-[10px] leading-none">{{ pIdx + 1 }}</div>
                        </div>
                      }
                    </div>
                    @if (photo.path === lbGroup.best_path) {
                      <span class="text-green-400 text-[10px] font-bold">{{ I18N.culling.auto_best | translate }}</span>
                    } @else if (photo.cull_reason; as reason) {
                      <span class="text-white/60 text-[10px] max-w-[80px] truncate">{{ reason | cullReason }}</span>
                    }
                  </div>
                }
              }
            </div>
          </div>
        }
      </div>
    }

    <!-- Auto-cull preview / confirm dialog -->
    @if (autoCullPreview(); as ac) {
      <div class="fixed inset-0 z-[110] bg-black/50 flex items-center justify-center p-4"
           role="presentation"
           (click)="cancelAutoCull()"
           (keydown.escape)="cancelAutoCull()">
        <div #autoCullDialog class="rounded-xl bg-[var(--mat-sys-surface-container-high)] p-6 w-full max-w-md space-y-4"
             role="dialog"
             aria-modal="true"
             aria-labelledby="autoCullTitle"
             tabindex="-1"
             (click)="$event.stopPropagation()"
             (keydown)="$event.stopPropagation()">
          <h2 id="autoCullTitle" class="text-lg font-semibold">{{ I18N.culling.auto_cull.title | translate }}</h2>
          @if (ac.groups_processed === 0) {
            <p class="text-sm opacity-80">{{ I18N.culling.auto_cull.empty | translate }}</p>
          } @else {
            <p class="text-sm opacity-80">
              {{ I18N.culling.auto_cull.summary | translate:{ groups: ac.groups_processed, kept: ac.kept, rejected: ac.rejected } }}
            </p>
            <p class="text-xs opacity-60">{{ I18N.culling.strictness | translate }} · {{ strictness() }}%</p>
            @if (ac.highlights_added > 0) {
              <label class="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" class="accent-[var(--mat-sys-primary)]"
                       [checked]="autoCullHighlights()"
                       (change)="autoCullHighlights.set(!autoCullHighlights())" />
                {{ I18N.culling.auto_cull.highlights_label | translate:{ count: ac.highlights_added } }}
              </label>
            }
          }
          <div class="flex justify-end gap-2">
            <button mat-stroked-button (click)="cancelAutoCull()">{{ I18N.dialog.cancel | translate }}</button>
            @if (ac.groups_processed > 0) {
              <button mat-flat-button (click)="confirmAutoCull()" [disabled]="autoCullLoading()">
                {{ I18N.culling.auto_cull.apply | translate:{ rejected: ac.rejected } }}
              </button>
            }
          </div>
        </div>
      </div>
    }
  `,
  host: { class: 'block h-full' },
})
export class BurstCullingComponent implements OnDestroy {
  protected readonly I18N = I18N;
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  protected readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly albumService = inject(AlbumService);
  private readonly compareFilters = inject(CompareFiltersService);
  protected readonly auth = inject(AuthService);
  protected readonly store = inject(GalleryStore);
  private readonly sceneDate = new SceneDatePipe();

  /** Granularity served by the feed: all (merged burst+similar) | burst | similar | scene.
   *  Restored from localStorage (default 'all'); a ?group_by= query param overrides it. */
  protected readonly groupBy = signal<GroupBy>(readStoredGroupBy());
  /** Min posterior below which a moment label is shown dimmed + "(uncertain)". */
  protected readonly momentConfidenceMin = computed(
    () => this.store.config()?.moment_confidence_min ?? 0,
  );

  // Optional scope from "Cull this scene" / album entry points (query params).
  protected readonly scopeAlbum = signal<string | null>(null);
  protected readonly scopeFrom = signal<string | null>(null);
  protected readonly scopeTo = signal<string | null>(null);
  protected readonly scopeScene = signal<string | null>(null);
  protected readonly scoped = computed(
    () => !!(this.scopeAlbum() || this.scopeFrom() || this.scopeTo()),
  );
  // Non-smart albums + lazily-loaded scenes powering the scope cascade menu.
  protected readonly albums = signal<Album[]>([]);
  protected readonly expandedAlbumId = signal<number | null>(null);
  protected readonly expandedScenes = signal<SceneSummary[]>([]);
  protected readonly loadingScenes = signal(false);
  // Album name for the current scope, resolved from the loaded album list
  // (works for both menu selection and a deep-linked ?album=ID).
  protected readonly scopeAlbumName = computed(() =>
    AlbumService.nameById(this.albums(), this.scopeAlbum()));
  // Human label for the scope button / banner (null = whole library).
  protected readonly scopeLabel = computed(() => {
    const album = this.scopeAlbumName();
    const scene = this.scopeScene();
    if (album && scene) return `${album} · ${scene}`;
    return album ?? scene ?? null;
  });
  // Personal-ranker status, surfaced as the "this cull trains My Taste" chip.
  protected readonly rankerComparisons = signal<number | null>(null);
  protected readonly rankerTrained = signal(false);

  // Photo-Mechanic-style hover loupe over the group tiles (Z toggles; zoom slider).
  private readonly loupe = createLoupeState();
  protected readonly loupeActive = this.loupe.loupeActive;
  protected readonly loupeZoom = this.loupe.loupeZoom;
  protected readonly similarityThreshold = signal(85);
  /** Auto-keep strictness (0-100): higher keeps fewer photos below the best. */
  protected readonly strictness = signal(100);

  /** Genre culling presets (GET /api/culling/profiles). */
  protected readonly cullProfiles = signal<CullProfile[]>([]);
  /** Active preset id ('' = custom / none). Persisted; re-applied on open. */
  protected readonly selectedProfile = signal<string>(localStorage.getItem(CULL_PROFILE_KEY) ?? '');
  /** Moment-derived preset suggestion for the current scope (null = none). */
  protected readonly profileSuggestion = signal<ProfileSuggestion | null>(null);
  /** Label of the active preset, or "Custom" when none matches the current knobs. */
  protected readonly selectedProfileLabel = computed(() => {
    const p = this.cullProfiles().find(x => x.id === this.selectedProfile());
    return p ? p.label_key : I18N.culling.profiles.custom;
  });
  /** The suggested preset to offer as a chip — only when it differs from the
   *  active one and resolves to a known profile. */
  protected readonly suggestedProfile = computed<CullProfile | null>(() => {
    const s = this.profileSuggestion();
    if (!s || !s.profile || s.profile === this.selectedProfile()) return null;
    return this.cullProfiles().find(x => x.id === s.profile) ?? null;
  });
  protected readonly excludeRejected = signal(true);
  protected readonly groups = signal<CullingGroup[]>([]);
  protected readonly totalGroups = signal(0);
  protected readonly loading = signal(true);
  protected readonly loadingMore = signal(false);
  protected readonly confirming = signal(false);

  /** Monotonic id bumped on every filter change; loadGroups/loadMore drop late responses whose generation no longer matches. */
  private loadGenerationId = 0;

  /** group_id -> set of kept paths */
  protected readonly selectionsMap = signal<Map<number, Set<string>>>(new Map());

  /** Set of confirmed group keys (group_id + '_' + type) */
  protected readonly confirmedGroups = signal<Set<string>>(new Set());

  /** Seconds a skipped group stays cancellable before it is hidden. */
  protected readonly passCountdownSeconds = 7;

  /** Map of group key -> remaining countdown seconds for groups being passed */
  protected readonly passingGroups = signal<Map<string, number>>(new Map());

  /** Set of group keys hidden after pass timeout */
  private readonly hiddenGroups = signal<Set<string>>(new Set());

  /** Active timers for passing groups (for cleanup) */
  private readonly passTimers = new Map<string, { timeoutId: ReturnType<typeof setTimeout>; intervalId: ReturnType<typeof setInterval>; onElapsed: () => void; commit: boolean }>();

  protected readonly currentPage = signal(1);
  protected readonly totalPages = signal(1);
  private readonly similarSeed = Math.floor(Math.random() * 1_000_000);

  protected readonly hasMore = computed(() => this.currentPage() < this.totalPages());

  /** Lightbox state — group being viewed, and current photo index inside it. */
  protected readonly lightboxGroupId = signal<string | null>(null);
  protected readonly lightboxIndex = signal(0);
  protected readonly lightboxGroup = computed<CullingGroup | null>(() => {
    const key = this.lightboxGroupId();
    if (!key) return null;
    return this.groups().find(g => this.groupKey(g) === key) ?? null;
  });

  /** Compare mode for the darkroom: single view, or a synced 2-up / 4-up grid. */
  protected readonly compareMode = signal<'single' | '2up' | '4up'>('single');
  /** Pan/zoom transform shared by every compare pane (synced peek). */
  protected readonly zoom = signal<ZoomState>(FIT_ZOOM);
  /** True while the darkroom dialog is the document's fullscreen element. */
  protected readonly isFullscreen = signal(false);

  /** The frames shown in compare mode: N photos from the current index, clamped. */
  protected readonly compareFrames = computed(() => {
    const group = this.lightboxGroup();
    if (!group) return [];
    const count = this.compareMode() === '4up' ? 4 : 2;
    const start = Math.min(this.lightboxIndex(), Math.max(0, group.photos.length - count));
    return group.photos.slice(start, start + count);
  });

  protected setCompareMode(mode: 'single' | '2up' | '4up'): void {
    this.compareMode.set(mode);
    this.zoom.set(FIT_ZOOM);
  }

  /** True Fullscreen API on the darkroom overlay (mirrors the slideshow pattern). */
  protected toggleFullscreen(): void {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    } else {
      void this.lightboxDialog()?.nativeElement.requestFullscreen().catch(() => {});
    }
  }

  /** The fullscreen darkroom dialog element, focused on open so the photo tiles
   *  behind the overlay stop receiving keystrokes (otherwise Space double-fires). */
  private readonly lightboxDialog = viewChild<ElementRef<HTMLElement>>('lightboxDialog');
  /** The auto-cull confirm dialog, focused on open so keyboard users aren't
   *  stranded behind the modal overlay near the destructive "Reject" button. */
  private readonly autoCullDialog = viewChild<ElementRef<HTMLElement>>('autoCullDialog');
  private readonly cullToolbar = viewChild<TemplateRef<unknown>>('cullToolbar');

  /** photo path -> detected faces, loaded lazily when a lightbox group opens. */
  protected readonly faceMap = signal<Map<string, CullingFace[]>>(new Map());

  /** Config-driven face-signal cutoffs from the faces response (ring colors + badges). */
  protected readonly faceThresholds = signal<FaceThresholds | null>(null);

  /** Face-panel live-highlight sliders (0 = off): faces below the chosen
   *  eyes-open / smile value stay bright while the rest dim. Persisted. */
  protected readonly faceEyesMin = signal(readStoredFaceMin(CULL_FACE_EYES_KEY));
  protected readonly faceSmileMin = signal(readStoredFaceMin(CULL_FACE_SMILE_KEY));

  protected onFaceEyesMinChange(value: number): void {
    this.faceEyesMin.set(value);
    localStorage.setItem(CULL_FACE_EYES_KEY, String(value));
  }

  protected onFaceSmileMinChange(value: number): void {
    this.faceSmileMin.set(value);
    localStorage.setItem(CULL_FACE_SMILE_KEY, String(value));
  }

  /** True when at least one photo in the focused group has loaded faces. */
  protected readonly faceGridHasFaces = computed(() => {
    const group = this.lightboxGroup();
    if (!group) return false;
    const map = this.faceMap();
    return group.photos.some(p => (map.get(p.path)?.length ?? 0) > 0);
  });

  /** Groups visible in the UI (excludes hidden groups + honors the category filter). */
  protected readonly visibleGroups = computed(() => {
    const hidden = this.hiddenGroups();
    const cat = this.categoryFilter();
    return this.groups().filter(g => !hidden.has(this.groupKey(g)) && (!cat || g.category === cat));
  });

  protected readonly unconfirmedCount = computed(() => {
    const confirmed = this.confirmedGroups();
    return this.visibleGroups().filter(g => !confirmed.has(this.groupKey(g))).length;
  });

  /** Index of the keyboard-selected group (page-level nav when the lightbox is closed). */
  protected readonly selectedGroupIndex = signal(0);

  /** Server-side ordering of culling groups; reloads from page 1 on change. Persisted. */
  protected readonly sortMode = signal(readStoredSort());
  protected readonly sortModes = ['easiest', 'redundant', 'best', 'recent', 'needs_comparisons'] as const;

  /** Content-category to cull ('' = all). Filters the visible group list client-side. Persisted. */
  protected readonly categoryFilter = signal(localStorage.getItem(CULL_CATEGORY_KEY) ?? '');

  /** Distinct categories among loaded groups, for the header filter select. */
  protected readonly availableCategories = computed<string[]>(() => {
    const set = new Set<string>();
    for (const g of this.groups()) if (g.category) set.add(g.category);
    return [...set].sort();
  });

  /** Options for the category select: loaded categories plus the persisted filter
   *  value, so a stale stored category (from another library/feed) stays visible
   *  and the user can always clear it back to "All categories" — otherwise the
   *  select would hide while visibleGroups() filtered everything out. */
  protected readonly categoryOptions = computed<string[]>(() => {
    const set = new Set(this.availableCategories());
    const active = this.categoryFilter();
    if (active) set.add(active);
    return [...set].sort();
  });

  /** Per-category comparison counts + threshold, for the weight-tuning chip. */
  protected readonly comparisonStats = signal<ComparisonStatsLite | null>(null);

  /** Dry-run result of POST /culling/auto shown in the confirm dialog (null = closed). */
  protected readonly autoCullPreview = signal<AutoCullResponse | null>(null);
  protected readonly autoCullLoading = signal(false);
  /** Whether the apply also fills the Highlights album (dialog checkbox, opt-in). */
  protected readonly autoCullHighlights = signal(false);

  protected readonly darkroomShortcuts: ShortcutRow[] = [
    { keys: ['←', '→'], labelKey: 'culling.shortcuts.navigate' },
    { keys: ['↑'], labelKey: 'culling.shortcuts.keep' },
    { keys: ['↓'], labelKey: 'culling.shortcuts.reject' },
    { keys: ['Z'], labelKey: 'culling.shortcuts.zoom' },
    { keys: ['F'], labelKey: 'slideshow.fullscreen' },
    { keys: ['Space'], labelKey: 'culling.shortcuts.confirm_next' },
    { keys: ['Esc'], labelKey: 'culling.shortcuts.close' },
  ];

  protected readonly shortcutSections: { titleKey: string; rows: ShortcutRow[] }[] = [
    {
      titleKey: 'culling.shortcuts.page_title',
      rows: [
        { keys: ['↑', '↓'], labelKey: 'culling.shortcuts.select' },
        { keys: ['Enter'], labelKey: 'culling.shortcuts.open' },
        { keys: ['Space'], labelKey: 'culling.shortcuts.confirm_next' },
      ],
    },
    { titleKey: 'culling.shortcuts.darkroom_title', rows: this.darkroomShortcuts },
  ];

  constructor() {
    this.pageHelp.setDescription(null);
    const qp = this.route.snapshot.queryParamMap;
    this.scopeAlbum.set(qp.get('album'));
    this.scopeFrom.set(qp.get('from'));
    this.scopeTo.set(qp.get('to'));
    this.scopeScene.set(qp.get('scene'));
    const gb = qp.get('group_by');
    if (gb === 'all' || gb === 'burst' || gb === 'similar' || gb === 'scene') this.groupBy.set(gb);
    void this.loadGroups();
    void this.loadAlbums();
    void this.loadCullProfiles();
    void this.refreshSuggestion();
    void this.refreshComparisonStats();
    void this.refreshRankerStatus();
    // Keep the keyboard selection in bounds as groups load / get hidden.
    effect(() => {
      const count = this.visibleGroups().length;
      if (count === 0) return;
      const clamped = Math.min(this.selectedGroupIndex(), count - 1);
      if (clamped !== this.selectedGroupIndex()) this.selectedGroupIndex.set(clamped);
    });
    // Scroll the keyboard-selected group into view (mirrors gallery.focusCard).
    effect(() => {
      if (this.lightboxGroup()) return;
      const idx = this.selectedGroupIndex();
      queueMicrotask(() => {
        document.querySelector(`[data-gidx="${idx}"]`)?.scrollIntoView({ block: 'nearest' });
      });
    });
    // Move focus onto the darkroom dialog when it opens so the photo tiles behind
    // it stop receiving keydowns (the tile's own Space handler would otherwise
    // re-open its group and fight the confirm+advance).
    effect(() => {
      this.lightboxDialog()?.nativeElement.focus();
    });
    // Focus the auto-cull confirm dialog on open so keyboard users land inside
    // the modal (not stranded on the tiles behind it) next to a destructive action.
    effect(() => {
      if (this.autoCullPreview()) this.autoCullDialog()?.nativeElement.focus();
    });
    // Project the toolbar into the global header on lg+ (the page renders it in
    // its own bottom bar on small screens — see the #cullToolbar template).
    effect(() => {
      const tpl = this.cullToolbar();
      if (tpl) this.headerSlot.set(tpl);
    });
  }

  /** Update a signal holding a Map by cloning and setting a key. */
  private updateMapSignal<K, V>(sig: WritableSignal<Map<K, V>>, key: K, value: V): void {
    sig.update(m => { const next = new Map(m); next.set(key, value); return next; });
  }

  /** Update a signal holding a Map by cloning and deleting a key. */
  private deleteMapKey<K, V>(sig: WritableSignal<Map<K, V>>, key: K): void {
    sig.update(m => { if (!m.has(key)) return m; const next = new Map(m); next.delete(key); return next; });
  }

  /** Update a signal holding a Set by cloning and adding a value. */
  private addToSetSignal<V>(sig: WritableSignal<Set<V>>, value: V): void {
    sig.update(s => { const next = new Set(s); next.add(value); return next; });
  }

  ngOnDestroy(): void {
    this.pageHelp.setDescription(null);
    this.clearAllPassTimers();
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    }
    const tpl = this.cullToolbar();
    if (tpl) this.headerSlot.clear(tpl);
  }

  protected groupKey(group: CullingGroup): string {
    return `${group.group_id}_${group.type}`;
  }

  private buildParams(page: number): Record<string, string | number | boolean> {
    const params: Record<string, string | number | boolean> = {
      page,
      per_page: 20,
      similarity_threshold: (this.similarityThreshold() / 100).toString(),
      seed: this.similarSeed,
      exclude_rejected: this.excludeRejected(),
      sort: this.sortMode(),
      group_by: this.groupBy(),
    };
    const album = this.scopeAlbum();
    const from = this.scopeFrom();
    const to = this.scopeTo();
    if (album) params['album_id'] = album;
    if (from) params['date_from'] = from;
    if (to) params['date_to'] = to;
    return params;
  }

  /** Clear the scene/album scope and return to the full unreviewed feed. */
  protected exitScope(): void {
    this.scopeAlbum.set(null);
    this.scopeFrom.set(null);
    this.scopeTo.set(null);
    this.scopeScene.set(null);
    void this.router.navigate(['/culling']);
    void this.loadGroups();
    void this.refreshSuggestion();
  }

  /** Non-smart albums for the scope cascade's first level (best-effort). */
  private async loadAlbums(): Promise<void> {
    try {
      this.albums.set(await firstValueFrom(this.albumService.listNonSmart()));
    } catch {
      // Scope menu keeps the "Whole library" entry only.
    }
  }

  /** Lazily load an album's scenes when its submenu opens (summary = no photos[]). */
  protected async loadAlbumScenes(album: Album): Promise<void> {
    if (this.expandedAlbumId() === album.id) return;
    this.expandedAlbumId.set(album.id);
    this.expandedScenes.set([]);
    this.loadingScenes.set(true);
    try {
      const data = await firstValueFrom(this.api.get<{ scenes: SceneSummary[] }>(
        '/scenes', { album_id: album.id, summary: true, per_page: 100 },
      ));
      if (this.expandedAlbumId() === album.id) this.expandedScenes.set(data.scenes);
    } catch {
      // Submenu still offers "Whole album".
    } finally {
      if (this.expandedAlbumId() === album.id) this.loadingScenes.set(false);
    }
  }

  private applyScope(album: string | null, from: string | null, to: string | null, scene: string | null): void {
    this.scopeAlbum.set(album);
    this.scopeFrom.set(from);
    this.scopeTo.set(to);
    this.scopeScene.set(scene);
    void this.router.navigate(['/culling'], {
      queryParams: { album: album ?? null, from: from ?? null, to: to ?? null, scene: scene ?? null },
    });
    this.selectedGroupIndex.set(0);
    this.resetForReload();
    void this.refreshSuggestion();
  }

  protected scopeWholeLibrary(): void {
    this.applyScope(null, null, null, null);
  }

  protected scopeAlbumWhole(): void {
    const id = this.expandedAlbumId();
    if (id === null) return;
    this.applyScope(id.toString(), null, null, null);
  }

  protected scopeAlbumScene(scene: SceneSummary): void {
    const id = this.expandedAlbumId();
    if (id === null) return;
    this.applyScope(id.toString(), scene.start, scene.end, this.sceneDate.transform(scene.start));
  }

  /** Fetch personal-ranker status for the "trains My Taste" chip (best-effort). */
  private async refreshRankerStatus(): Promise<void> {
    try {
      const s = await firstValueFrom(
        this.api.get<{ trained: boolean; comparison_count: number }>('/ranker/status'),
      );
      this.rankerTrained.set(!!s.trained);
      this.rankerComparisons.set(s.comparison_count ?? null);
    } catch {
      // The chip is a nice-to-have; ignore status failures.
    }
  }

  private autoSelectBest(groups: CullingGroup[], base?: Map<number, Set<string>>): Map<number, Set<string>> {
    const map = base ? new Map(base) : new Map<number, Set<string>>();
    for (const group of groups) {
      if (!map.has(group.group_id)) {
        const kept = this.computeAutoKeep(group);
        if (kept.size > 0) {
          map.set(group.group_id, kept);
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
   */
  private computeAutoKeep(group: CullingGroup): Set<string> {
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

  protected onThresholdChange(value: number): void {
    this.similarityThreshold.set(value);
    this.clearProfileSelection();
    this.resetForReload();
  }

  /** Moving a knob by hand drops the preset label — the mix is now custom. */
  private clearProfileSelection(): void {
    if (this.selectedProfile()) {
      this.selectedProfile.set('');
      localStorage.removeItem(CULL_PROFILE_KEY);
    }
  }

  protected onStrictnessChange(value: number): void {
    this.strictness.set(value);
    this.clearProfileSelection();
    this.reselectFromStrictness();
  }

  /**
   * Re-derive the auto-keep selection for every loaded group from the current
   * strictness. Purely client-side over the burst_score values already
   * returned — no backend round-trip. Confirmed groups are left untouched.
   */
  private reselectFromStrictness(): void {
    const confirmed = this.confirmedGroups();
    const map = new Map<number, Set<string>>();
    for (const group of this.groups()) {
      if (confirmed.has(this.groupKey(group))) {
        const existing = this.selectionsMap().get(group.group_id);
        if (existing) map.set(group.group_id, existing);
        continue;
      }
      const kept = this.computeAutoKeep(group);
      if (kept.size > 0) map.set(group.group_id, kept);
    }
    this.selectionsMap.set(map);
  }

  // --- Genre culling profiles (preset selector + moment auto-suggest) ---

  /** Load the genre culling presets; re-apply the persisted one on open. */
  private async loadCullProfiles(): Promise<void> {
    try {
      const data = await firstValueFrom(this.api.get<CullProfilesResponse>('/culling/profiles'));
      this.cullProfiles.set(data.profiles ?? []);
      const stored = this.cullProfiles().find(p => p.id === this.selectedProfile());
      if (stored) this.applyProfile(stored, false);
      else this.clearProfileSelection();
    } catch {
      // Preset selector stays hidden when the list can't load.
    }
  }

  /** Re-suggest a preset from the current scope's dominant narrative moment. */
  private async refreshSuggestion(): Promise<void> {
    const params: Record<string, string | number | boolean> = { group_by: this.groupBy() };
    const album = this.scopeAlbum();
    const from = this.scopeFrom();
    const to = this.scopeTo();
    if (album) params['album_id'] = album;
    if (from) params['date_from'] = from;
    if (to) params['date_to'] = to;
    try {
      this.profileSuggestion.set(
        await firstValueFrom(this.api.get<ProfileSuggestion>('/culling/profiles/suggest', params)));
    } catch {
      this.profileSuggestion.set(null);
    }
  }

  /**
   * Apply a preset: set strictness first (so a reload auto-selects with it) and
   * the similarity threshold, remember the choice, then re-derive the auto-keep
   * selection in place — or reload only when the threshold changed the grouping.
   */
  protected applyProfile(p: CullProfile, persist = true): void {
    this.selectedProfile.set(p.id);
    if (persist) localStorage.setItem(CULL_PROFILE_KEY, p.id);
    if (p.strictness != null) this.strictness.set(p.strictness);
    if (p.similarity_threshold != null && p.similarity_threshold !== this.similarityThreshold()) {
      this.similarityThreshold.set(p.similarity_threshold);
      this.resetForReload();
    } else if (p.strictness != null) {
      this.reselectFromStrictness();
    }
  }

  protected applySuggestion(): void {
    const p = this.suggestedProfile();
    if (p) this.applyProfile(p);
  }

  protected onExcludeRejectedChange(value: boolean): void {
    this.excludeRejected.set(value);
    this.resetForReload();
  }

  protected onCategoryFilterChange(value: string): void {
    this.categoryFilter.set(value);
    localStorage.setItem(CULL_CATEGORY_KEY, value);
    this.selectedGroupIndex.set(0);
  }

  protected onSortChange(value: string): void {
    this.sortMode.set(value);
    localStorage.setItem(CULL_SORT_KEY, value);
    this.selectedGroupIndex.set(0);
    this.resetForReload();
  }

  /** Switch the feed granularity (all | burst | similar | scene); reloads from page 1. */
  protected onGroupByChange(value: GroupBy): void {
    if (value === this.groupBy()) return;
    this.groupBy.set(value);
    localStorage.setItem(CULL_GROUP_BY_KEY, value);
    this.selectedGroupIndex.set(0);
    void this.router.navigate([], { queryParams: { group_by: value }, queryParamsHandling: 'merge' });
    this.resetForReload();
  }

  private resetForReload(): void {
    this.loadGenerationId++;
    this.currentPage.set(1);
    this.groups.set([]);
    this.confirmedGroups.set(new Set());
    this.selectionsMap.set(new Map());
    this.clearAllPassTimers();
    void this.loadGroups();
  }

  protected async loadGroups(): Promise<void> {
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
      this.snackBar.open(this.i18n.t(I18N.culling.error_loading), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      if (gen === this.loadGenerationId) this.loading.set(false);
    }
  }

  protected async loadMore(): Promise<void> {
    if (!this.hasMore()) return;
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
      this.snackBar.open(this.i18n.t(I18N.culling.error_loading), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      if (gen === this.loadGenerationId) this.loadingMore.set(false);
    }
  }

  protected onScrollReached(): void {
    if (this.hasMore() && !this.loadingMore()) {
      this.loadMore();
    }
  }

  protected openDetail(event: Event, path: string): void {
    event.stopPropagation();
    this.router.navigate(['/photo'], { queryParams: { path } });
  }

  /** Open Comparison scoped to a group's category so its weights can be tuned. */
  protected tuneCategory(category: string): void {
    this.compareFilters.selectedCategory.set(category);
    void this.router.navigate(['/compare']);
  }

  // --- Lightbox handlers ---

  protected openLightbox(group: CullingGroup, index: number): void {
    this.zoom.set(FIT_ZOOM);  // never inherit a prior session's zoom/pan
    this.lightboxGroupId.set(this.groupKey(group));
    this.lightboxIndex.set(index);
    const gi = this.visibleGroups().findIndex(g => this.groupKey(g) === this.groupKey(group));
    if (gi >= 0) this.selectedGroupIndex.set(gi);
    void this.loadFacesForGroup(group);
  }

  protected closeLightbox(): void {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    }
    // Leave the page focused on the group just reviewed in the darkroom, so its
    // keep/reject choices (already written to the shared selectionsMap) are the
    // ones highlighted and scrolled into view on exit.
    const group = this.lightboxGroup();
    if (group) {
      const gi = this.visibleGroups().findIndex(g => this.groupKey(g) === this.groupKey(group));
      if (gi >= 0) this.selectedGroupIndex.set(gi);
    }
    this.lightboxGroupId.set(null);
  }

  /**
   * Lazily fetch detected faces for the focused group in a single batch call,
   * enriched with per-face eyes-open/expression/confidence/is_blink so the
   * lightbox can tile face crops with per-face badges. Results are cached in
   * faceMap; already-loaded paths are skipped.
   */
  private async loadFacesForGroup(group: CullingGroup): Promise<void> {
    const missing = group.photos.filter(p => !this.faceMap().has(p.path));
    if (missing.length === 0) return;
    try {
      const data = await firstValueFrom(
        this.api.post<{ faces_by_path: Record<string, CullingFace[]>; thresholds?: FaceThresholds }>(
          '/culling-group/faces', { paths: missing.map(p => p.path), profile: this.selectedProfile() || undefined },
        ),
      );
      if (data.thresholds) this.faceThresholds.set(data.thresholds);
      const byPath = data.faces_by_path ?? {};
      this.faceMap.update(m => {
        const next = new Map(m);
        for (const photo of missing) next.set(photo.path, byPath[photo.path] ?? []);
        return next;
      });
    } catch {
      // Best-effort: record empty results so we don't refetch on every open.
      this.faceMap.update(m => {
        const next = new Map(m);
        for (const photo of missing) next.set(photo.path, []);
        return next;
      });
    }
  }

  private clampIndex(value: number, max: number): number {
    if (max <= 0) return 0;
    return Math.max(0, Math.min(max - 1, value));
  }

  @HostListener('document:keydown.arrowleft', ['$event'])
  protected onArrowLeft(event: Event): void {
    const group = this.lightboxGroup();
    if (!group) return;
    event.preventDefault();
    this.lightboxIndex.update(i => this.clampIndex(i - 1, group.photos.length));
    this.zoom.set(FIT_ZOOM);
  }

  @HostListener('document:keydown.arrowright', ['$event'])
  protected onArrowRight(event: Event): void {
    const group = this.lightboxGroup();
    if (!group) return;
    event.preventDefault();
    this.lightboxIndex.update(i => this.clampIndex(i + 1, group.photos.length));
    this.zoom.set(FIT_ZOOM);
  }

  /** Z toggles the darkroom zoom (fit ↔ 2×) when open, else the grid hover loupe. */
  @HostListener('document:keydown.z', ['$event'])
  protected onZoomToggle(event: Event): void {
    if (isTypingContext(event)) return;
    if (!this.lightboxGroup()) {
      this.loupeActive.set(!this.loupeActive());
      return;
    }
    event.preventDefault();
    this.zoom.set(this.zoom().scale > 1 ? FIT_ZOOM : { scale: 2, tx: 0, ty: 0 });
  }

  /** F toggles true fullscreen on the open darkroom (mirrors the slideshow's F key). */
  @HostListener('document:keydown.f', ['$event'])
  protected onFullscreenToggle(event: Event): void {
    if (!this.lightboxGroup()) return;
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.toggleFullscreen();
  }

  @HostListener('document:fullscreenchange')
  protected onFullscreenChange(): void {
    this.isFullscreen.set(!!document.fullscreenElement);
  }

  private setCurrentLightboxPhotoKept(group: CullingGroup, keep: boolean): void {
    const photo = group.photos[this.lightboxIndex()];
    if (!photo) return;
    const map = new Map(this.selectionsMap());
    const kept = new Set(map.get(group.group_id) ?? []);
    if (keep) kept.add(photo.path); else kept.delete(photo.path);
    map.set(group.group_id, kept);
    this.selectionsMap.set(map);
  }

  /** True when the event originates from a text/slider control we must not hijack. */
  @HostListener('document:keydown.arrowup', ['$event'])
  protected onArrowUp(event: Event): void {
    const group = this.lightboxGroup();
    if (group) {
      event.preventDefault();
      this.setCurrentLightboxPhotoKept(group, true);
      return;
    }
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.selectedGroupIndex.update(i => this.clampIndex(i - 1, this.visibleGroups().length));
  }

  @HostListener('document:keydown.arrowdown', ['$event'])
  protected onArrowDown(event: Event): void {
    const group = this.lightboxGroup();
    if (group) {
      event.preventDefault();
      this.setCurrentLightboxPhotoKept(group, false);
      return;
    }
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.selectedGroupIndex.update(i => this.clampIndex(i + 1, this.visibleGroups().length));
  }

  @HostListener('document:keydown.enter', ['$event'])
  protected onEnter(event: Event): void {
    if (this.lightboxGroup()) return;
    if (isTypingContext(event)) return;
    const group = this.visibleGroups()[this.selectedGroupIndex()];
    if (!group) return;
    event.preventDefault();
    this.openLightbox(group, 0);
  }

  /** Next visible, not-yet-confirmed group after the given one (for darkroom auto-advance). */
  private nextUnconfirmedGroupAfter(group: CullingGroup): CullingGroup | null {
    const groups = this.visibleGroups();
    const confirmed = this.confirmedGroups();
    const startIdx = groups.findIndex(g => this.groupKey(g) === this.groupKey(group));
    for (let i = startIdx + 1; i < groups.length; i++) {
      if (!confirmed.has(this.groupKey(groups[i]))) return groups[i];
    }
    return null;
  }

  @HostListener('document:keydown.space', ['$event'])
  protected onSpace(event: Event): void {
    const group = this.lightboxGroup();
    if (group) {
      // Darkroom: confirm the open group and jump into the next one.
      event.preventDefault();
      const next = this.nextUnconfirmedGroupAfter(group);
      this.confirmGroup(group);
      if (next) {
        this.openLightbox(next, 0);
        this.lightboxDialog()?.nativeElement.focus();
      } else {
        this.closeLightbox();
      }
      return;
    }
    // List: confirm the selected group and move the selection to the next one.
    if (isTypingContext(event)) return;
    const selected = this.visibleGroups()[this.selectedGroupIndex()];
    if (!selected) return;
    event.preventDefault();
    const next = this.nextUnconfirmedGroupAfter(selected);
    void this.confirmGroup(selected);
    if (next) {
      const gi = this.visibleGroups().findIndex(g => this.groupKey(g) === this.groupKey(next));
      if (gi >= 0) this.selectedGroupIndex.set(gi);
    } else {
      this.selectedGroupIndex.update(i => this.clampIndex(i + 1, this.visibleGroups().length));
    }
  }

  @HostListener('document:keydown.escape', ['$event'])
  protected onEscape(event: Event): void {
    if (this.autoCullPreview()) {
      event.preventDefault();
      this.cancelAutoCull();
      return;
    }
    if (this.lightboxGroup()) {
      event.preventDefault();
      this.closeLightbox();
    }
  }

  // --- Auto-cull (one-button cull under a keeper budget) ---

  /** Request body for POST /culling/auto, reusing the page's scope + strictness. */
  private autoCullBody(dryRun: boolean, highlightsAlbum: string): Record<string, unknown> {
    const body: Record<string, unknown> = {
      group_by: this.groupBy(),
      strictness: this.strictness(),
      dry_run: dryRun,
      highlights_album: highlightsAlbum,
    };
    const profile = this.selectedProfile();
    if (profile) body['profile'] = profile;
    const album = this.scopeAlbum();
    if (album) body['album_id'] = Number(album);
    const from = this.scopeFrom();
    if (from) body['date_from'] = from;
    const to = this.scopeTo();
    if (to) body['date_to'] = to;
    return body;
  }

  /** Deterministic Highlights album name for the current scope and day. */
  private highlightsAlbumName(): string {
    const scope = this.scopeLabel() ?? this.i18n.t(I18N.culling.scope_whole_library);
    const day = new Date().toISOString().slice(0, 10);
    return `${this.i18n.t(I18N.culling.auto_cull.highlights_name)} — ${scope} ${day}`;
  }

  /** Dry-run the auto-cull for the current scope and open the confirm dialog. */
  protected async openAutoCull(): Promise<void> {
    this.autoCullLoading.set(true);
    try {
      const preview = await firstValueFrom(this.api.post<AutoCullResponse>(
        '/culling/auto', this.autoCullBody(true, this.highlightsAlbumName()),
      ));
      this.autoCullPreview.set(preview);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.culling.auto_cull.error), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.autoCullLoading.set(false);
    }
  }

  protected cancelAutoCull(): void {
    this.autoCullPreview.set(null);
  }

  /** Apply the previewed auto-cull (dry_run=false), then refresh the feed. */
  protected async confirmAutoCull(): Promise<void> {
    this.autoCullLoading.set(true);
    try {
      const album = this.autoCullHighlights() ? this.highlightsAlbumName() : '';
      const result = await firstValueFrom(this.api.post<AutoCullResponse>(
        '/culling/auto', this.autoCullBody(false, album),
      ));
      this.autoCullPreview.set(null);
      this.snackBar.open(
        this.i18n.t(I18N.culling.auto_cull.applied, { kept: result.kept, rejected: result.rejected }),
        '', { duration: 3000, horizontalPosition: 'right', verticalPosition: 'bottom' },
      );
      this.selectedGroupIndex.set(0);
      this.resetForReload();
      void this.refreshComparisonStats();
      void this.refreshRankerStatus();
    } catch {
      this.snackBar.open(this.i18n.t(I18N.culling.auto_cull.error), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.autoCullLoading.set(false);
    }
  }

  protected toggleSelection(path: string, group: CullingGroup): void {
    const map = new Map(this.selectionsMap());
    const kept = new Set(map.get(group.group_id) ?? []);

    if (kept.has(path)) {
      kept.delete(path);
    } else {
      kept.add(path);
    }
    map.set(group.group_id, kept);
    this.selectionsMap.set(map);
  }

  protected selectExclusive(path: string, group: CullingGroup): void {
    this.updateMapSignal(this.selectionsMap, group.group_id, new Set([path]));
  }

  protected confirmGroup(group: CullingGroup): void {
    const kept = this.selectionsMap().get(group.group_id);
    if (!kept || kept.size === 0) return;

    // Grey the group and start the cancellable cooldown; the commit + close only
    // happen when it elapses, so Cancel within the window fully reverts it.
    const key = this.groupKey(group);
    const keepPaths = [...kept];
    this.addToSetSignal(this.confirmedGroups, key);
    this.startCountdown(key, () => {
      void firstValueFrom(this.api.post('/culling-groups/confirm', {
        group_id: group.group_id,
        type: group.type,
        paths: group.photos.map(p => p.path),
        keep_paths: keepPaths,
      }))
        .then(() => { void this.refreshComparisonStats(); void this.refreshRankerStatus(); })
        .catch(() => {
          this.unconfirmGroup(key);
          this.snackBar.open(this.i18n.t(I18N.culling.error_confirming), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
        });
      this.addToSetSignal(this.hiddenGroups, key);
    }, true);
  }

  private unconfirmGroup(key: string): void {
    this.confirmedGroups.update(s => {
      const next = new Set(s);
      next.delete(key);
      return next;
    });
  }

  /** Fetch per-category comparison counts + threshold for the weight-tuning chip. */
  private async refreshComparisonStats(): Promise<void> {
    try {
      const stats = await firstValueFrom(this.api.get<ComparisonStatsLite>('/comparison/stats'));
      this.comparisonStats.set(stats);
    } catch {
      // Best-effort: the chip simply stays hidden if stats are unavailable.
    }
  }

  /**
   * Shared 7s cooldown: a per-second countdown in passingGroups plus a one-shot
   * timer that runs onElapsed (hide for skip; commit + hide for confirm). Cancel
   * via cancelPass before it fires fully reverts the action.
   */
  private startCountdown(key: string, onElapsed: () => void, commit = false): void {
    this.clearPassTimer(key);
    this.updateMapSignal(this.passingGroups, key, this.passCountdownSeconds);

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
      onElapsed();
    }, this.passCountdownSeconds * 1000);

    this.passTimers.set(key, { timeoutId, intervalId, onElapsed, commit });
  }

  protected skipGroup(group: CullingGroup): void {
    const key = this.groupKey(group);
    this.startCountdown(key, () => this.addToSetSignal(this.hiddenGroups, key));
  }

  protected cancelPass(group: CullingGroup): void {
    const key = this.groupKey(group);
    this.clearPassTimer(key);
    this.unconfirmGroup(key);
  }

  private clearPassTimer(key: string): void {
    const timers = this.passTimers.get(key);
    if (timers) {
      clearTimeout(timers.timeoutId);
      clearInterval(timers.intervalId);
      this.passTimers.delete(key);
    }
    this.deleteMapKey(this.passingGroups, key);
  }

  private clearAllPassTimers(): void {
    // A confirm defers its server commit into the cooldown timer; cancelling
    // that timer on teardown/reload without running it would silently drop the
    // user's keep/reject decision. So flush pending confirm commits here (skip
    // timers only hide a group, nothing to persist). Explicit cancelPass goes
    // through clearPassTimer and is unaffected — an abort still aborts.
    const pendingCommits: (() => void)[] = [];
    for (const { timeoutId, intervalId, onElapsed, commit } of this.passTimers.values()) {
      clearTimeout(timeoutId);
      clearInterval(intervalId);
      if (commit) pendingCommits.push(onElapsed);
    }
    this.passTimers.clear();
    this.passingGroups.set(new Map());
    this.hiddenGroups.set(new Set());
    for (const commit of pendingCommits) commit();
  }

  protected async confirmAllRemaining(): Promise<void> {
    this.confirming.set(true);
    try {
      const confirmed = this.confirmedGroups();
      const remaining = this.visibleGroups().filter(g => !confirmed.has(this.groupKey(g)));
      const toConfirm = remaining.filter(g => {
        const kept = this.selectionsMap().get(g.group_id);
        return kept && kept.size > 0;
      });

      // Process in batches of 5 to avoid overwhelming the server
      const batchSize = 5;
      for (let i = 0; i < toConfirm.length; i += batchSize) {
        const batch = toConfirm.slice(i, i + batchSize);
        await Promise.all(batch.map(g => {
          const kept = this.selectionsMap().get(g.group_id)!;
          return firstValueFrom(this.api.post('/culling-groups/confirm', {
            group_id: g.group_id,
            type: g.type,
            paths: g.photos.map(p => p.path),
            keep_paths: [...kept],
          }));
        }));
      }

      this.confirmedGroups.update(s => {
        const next = new Set(s);
        for (const g of remaining) next.add(this.groupKey(g));
        return next;
      });
      this.snackBar.open(this.i18n.t(I18N.culling.confirmed), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.culling.error_auto_select), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.confirming.set(false);
    }
  }
}
