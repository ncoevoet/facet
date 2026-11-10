import { closeDetailsOnEscape } from '../../shared/utils/overlays';
import { DarkroomRenditions } from './darkroom-renditions';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { SEQUENCE_KINDS_KEPT_WHOLE, SEQUENCE_KIND_LABELS } from '../../shared/pipes/sequence-kind.pipe';
import { Component, DestroyRef, inject, signal, linkedSignal, computed, effect, untracked, viewChild, ElementRef, OnDestroy, HostListener, TemplateRef, ChangeDetectionStrategy } from '@angular/core';
import { NavigationStart, NavigationEnd, NavigationCancel, NavigationCancellationCode, NavigationError, NavigationSkipped, NavigationExtras, Router, ActivatedRoute } from '@angular/router';
import { ViewActionRegistry } from '../../core/agent/view-action-registry.service';
import { UiToolError } from '../../core/agent/ui-tool.types';
import { HttpErrorResponse } from '@angular/common/http';
import { CdkTrapFocus } from '@angular/cdk/a11y';
import { DecimalPipe, NgClass, NgTemplateOutlet, PercentPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatSliderModule } from '@angular/material/slider';
import { MatDialog } from '@angular/material/dialog';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService, Album } from '../../core/services/album.service';
import { GalleryStore } from './gallery.store';
import { SceneDatePipe, MomentLabelPipe, MomentUncertainPipe } from '../scenes/scenes.pipes';
import { sceneCullParams } from '../scenes/scene-cull-link';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { AssessmentValuePipe } from '../../shared/pipes/assessment-value.pipe';
import { PhotoAssessmentComponent } from '../../shared/components/photo-assessment/photo-assessment.component';
import { ThumbnailUrlPipe, FaceThumbnailUrlPipe, ImageUrlPipe, STORED_THUMBNAIL_EDGE, RENDERED_THUMBNAIL_EDGE } from '../../shared/pipes/thumbnail-url.pipe';
import { assignComparisonSlot } from './comparison-slots.util';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { SwipeDecisionDirective } from '../../shared/directives/swipe-decision.directive';
import { I18nService } from '../../core/services/i18n.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { isControlActivation, isTypingContext } from '../../shared/utils/keyboard';
import { toIsoDateString } from '../../shared/utils/date-format';
import { MOBILE_DOCKED_BAR_ROW, TOUCH_ICON_BUTTON, TOUCH_TEXT_BUTTON, XL_LABEL_BUTTON } from '../../shared/utils/mobile-bar';
import { CULL_DATE_PRESETS, presetRange, type CullDatePresetId } from './culling-date-range';
import { isBracketLadderRejection } from '../../shared/utils/sequence-ladder';
import { createLoupeState } from '../../shared/utils/loupe-state';
import { useCoarsePointerSignal } from '../../shared/utils/media-query';
import { SyncedZoomComponent, ZoomState, FIT_ZOOM, linkedZoomFrames } from './synced-zoom.component';
import { RenditionReadoutComponent } from '../../shared/components/rendition-readout/rendition-readout.component';
import { CompareFiltersService } from '../comparison/compare-filters.service';
import { PanoramaSettingsService } from '../comparison/panorama-settings.service';
import { SequenceOverrideService, SequenceKind } from '../../core/services/sequence-override.service';
import { UndoService } from '../../core/services/undo.service';
import { StackActionsService } from './stack-actions.service';
import { stackEditorReturnUrl } from './stack-editor-history';
import { stackDialogConfig } from './stack-dialog.config';
import { SequenceKindLabelPipe, SUPPRESSED_OVERRIDE } from '../../shared/pipes/sequence-kind.pipe';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { PageContextService, registerPageContext } from '../../core/agent/page-context.service';
import { AssistantCullPlanService, type CullPlanPin } from '../../core/agent/assistant-cull-plan.service';
import { firstValueFrom } from 'rxjs';
import { DARKROOM_SHORTCUTS, STACK_DARKROOM_SHORTCUTS } from './culling-shortcuts';
import { CullingStore, GroupBy, GROUP_BY_VALUES, CULL_GROUP_BY_KEY, CULL_SORT_KEY, CULL_SORT_DIR_KEY } from './culling.store';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import {
  CullGroupKeyPipe, CullPlanGroupReasonPipe, PlanDiffersPipe, PlanRejectCountPipe,
  PlanSuggestionPipe, PlanAcceptedPipe, PlanGroupNotePipe, CullDateRangePipe, ScopeDatePipe,
  IsKeptPipe, IsDecidedPipe, IsConfirmedPipe, IsPassingPipe, PassCountdownPipe,
  CullReasonPipe, FacesForPathPipe, FacePoorExpressionPipe, FaceRingClassPipe,
  FaceDimmedPipe, WeightRemainingPipe, CullGroupIconPipe, CullGroupLabelPipe, LookalikeSignalsPipe,
  SortIconPipe, CategoryIconPipe, CullProfileIconPipe,
  SubjectForPathPipe, SubjectRingClassPipe, EvOffsetPipe, GroupOverridePipe,
  GroupOverridePendingPipe, PeakingOverlayPipe, FrameViewBoxPipe, GridLinesPipe,
  KeySubjectForPathPipe, IsKeyFacePipe, CanMarkBracketPipe, CanStackGroupPipe, canStackGroup,
  GRID_MODES, KEY_SUBJECT_COORDINATE_SPACE,
  CullingGroup, CullingPhoto, CullingFace, CullingSubject, FaceThresholds, CullStyle,
  GridMode, KeySubject,
} from './burst-culling.pipes';
import { MarkTonePipe } from '../../shared/pipes/mark-tone.pipe';

// Per-user culling toolbar preferences, persisted so the page reopens the way
// the user left it. The URL query param (deep links / "Cull this scene") still
// overrides the stored granularity.
const CULL_CATEGORY_KEY = 'facet_culling_category';
const CULL_FACE_EYES_KEY = 'facet_culling_face_eyes_min';
const CULL_FACE_SMILE_KEY = 'facet_culling_face_smile_min';
const CULL_FACE_SIZE_KEY = 'facet_culling_face_size';
const CULL_LEGEND_KEY = 'facet_culling_legend';
const CULL_DARKROOM_LOUPE_KEY = 'facet_culling_darkroom_loupe';
const CULL_SWIPE_HINT_KEY = 'facet_culling_swipe_hint';

/** The gallery payload is JSON of string-valued API filters, independent of its return URL. */
function parseStackReviewFilters(raw: string | null): Record<string, string> {
  const filters: unknown = raw ? JSON.parse(raw) : null;
  if (!filters || typeof filters !== 'object' || Array.isArray(filters)
    || Object.entries(filters).some(([key, value]) => !key || typeof value !== 'string')) throw new Error('Invalid stack scope');
  return filters as Record<string, string>;
}

/** Stored face-panel slider value (0-10); 0 = highlight filter off. */
function readStoredFaceMin(key: string): number {
  const v = Number(localStorage.getItem(key));
  return Number.isFinite(v) && v >= 0 && v <= 10 ? v : 0;
}

/** Face close-up thumbnail display size, in CSS px. Stored thumbnails are
 *  640px, so the top of the range stays sharp when upscaled. */
const FACE_SIZE_MIN_PX = 64;
const FACE_SIZE_MAX_PX = 256;
const FACE_SIZE_STEP_PX = 16;
const FACE_SIZE_DEFAULT_PX = 112;

/** Stored face close-up size (px); falls back to the default on anything
 *  not on the slider's step grid within [min, max]. */
function readStoredFaceSize(): number {
  const v = Number(localStorage.getItem(CULL_FACE_SIZE_KEY));
  const onStep = (v - FACE_SIZE_MIN_PX) % FACE_SIZE_STEP_PX === 0;
  return Number.isFinite(v) && v >= FACE_SIZE_MIN_PX && v <= FACE_SIZE_MAX_PX && onStep
    ? v
    : FACE_SIZE_DEFAULT_PX;
}
/** Edge of the render the darkroom's fit view asks `/thumbnail` for. The pane
 *  shows the stored 640 px thumbnail first and swaps to this once it has
 *  loaded; peaking measures a PEAKING_FIT_EDGE downscale of the same render. */
const DARKROOM_THUMB_SIZE = RENDERED_THUMBNAIL_EDGE;
/** Stored thumbnail edge: the grid cards' image and the darkroom's placeholder.
 *  Read through a module-level const, not straight into a class field: Vite's test
 *  transform snapshots an imported binding used as a field initializer before a
 *  lazily-initialised shared chunk sets it. */
const STORED_EDGE = STORED_THUMBNAIL_EDGE;
/** All rejects, including frames hidden by the gallery defaults. */
const ALL_REJECTS_SCOPE = {
  show_rejected: '1', type: '', hide_blinks: 'false', hide_bursts: 'false',
  hide_duplicates: 'false', hide_brackets: 'false', hide_panoramas: 'false',
};

/** Label of what an auto-cull would do to a photo that already carries a decision. */
const PROPOSED_LABEL_KEYS: Record<'keep' | 'reject' | 'unchanged', string> = {
  keep: I18N.review.kept,
  reject: I18N.review.rejected,
  unchanged: I18N.culling.auto_cull.unchanged,
};

/** The set kind a group is kept whole under, from its own type or its sequence kind, or null. */
function wholeKindOf(group: CullingGroup): string | null {
  if (SEQUENCE_KINDS_KEPT_WHOLE.includes(group.type)) return group.type;
  if (group.sequence_kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(group.sequence_kind)) return group.sequence_kind;
  return null;
}

/** What the page remembers of a group's frames: the fields a sequence correction can change. */
function photoSignature(group: CullingGroup): string {
  return JSON.stringify(group.photos.map(photo => [photo.path, photo.sequence_kind, photo.sequence_override, photo.sequence_override_pending]));
}

/** Lightweight scene shape for the album→scene scope cascade (GET /scenes?summary=true). */
interface SceneSummary {
  scene_id: number;
  start: string | null;
  end: string | null;
  count: number;
  moment?: string | null;
}

@Component({
  selector: 'app-burst-culling',
  imports: [MarkTonePipe,
    AssessmentValuePipe, PhotoAssessmentComponent, RenditionReadoutComponent, FilenamePipe,
    DecimalPipe,
    PercentPipe,
    NgClass,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatDatepickerModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatSliderModule,
    TranslatePipe,
    SceneDatePipe,
    MomentLabelPipe,
    MomentUncertainPipe,
    LoupeDirective,
    SwipeDecisionDirective,
    ThumbnailUrlPipe,
    FaceThumbnailUrlPipe,
    ImageUrlPipe,
    SyncedZoomComponent,
    CullGroupKeyPipe,
    CullDateRangePipe,
    ScopeDatePipe,
    CullPlanGroupReasonPipe,
    PlanDiffersPipe,
    PlanRejectCountPipe,
    PlanSuggestionPipe,
    PlanAcceptedPipe,
    PlanGroupNotePipe,
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
    LookalikeSignalsPipe,
    SortIconPipe,
    CategoryIconPipe,
    CullProfileIconPipe,
    SubjectForPathPipe,
    SubjectRingClassPipe,
    EvOffsetPipe,
    GroupOverridePipe,
    GroupOverridePendingPipe,
    PeakingOverlayPipe,
    FrameViewBoxPipe,
    GridLinesPipe,
    KeySubjectForPathPipe,
    IsKeyFacePipe,
    CanMarkBracketPipe,
    CanStackGroupPipe,
    SequenceKindLabelPipe,
    InfiniteScrollDirective,
    NgTemplateOutlet,
    CdkTrapFocus,
  ],
  template: `
    <div #cullingPage class="px-2 pt-2 md:px-3 md:pt-3 w-full h-full flex flex-col">
      <!-- Header (sticky: only the group list below scrolls) -->
      <!-- The toolbar projects into the global header on lg+ (HeaderSlotService) and
           renders as a fixed bottom bar on small screens (same #cullToolbar template).
           When scoped, the back button is its first element (see below). -->
      <h1 class="sr-only">{{ (stacksMode() ? I18N.stacks.suggestions : I18N.culling.title) | translate }}</h1>
      <div class="lg:hidden">
        <ng-container [ngTemplateOutlet]="cullToolbar" />
      </div>
      <ng-template #cullToolbar>
        @if (stacksMode()) {
          <div class="flex flex-wrap items-center gap-2 py-2" data-testid="stack-review-header">
            <button class="${TOUCH_TEXT_BUTTON}" mat-button (click)="backToGallery()"><mat-icon>arrow_back</mat-icon>{{ I18N.stacks.back_gallery | translate }}</button>
            <span>{{ I18N.stacks.loaded | translate:{ count: visibleGroups().length } }}</span>
            @if (cull.batchFull()) { <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stacks.more_may_follow | translate }}</span> }
            <button class="${TOUCH_TEXT_BUTTON}" mat-button (click)="cull.resetForReload()">{{ I18N.stacks.suggestions_reload | translate }}</button>
          </div>
        } @else {
        <div #cullBar data-culling-bar [class]="barRow"
             class="flex lg:items-center lg:gap-4 min-w-0 max-lg:flex-wrap
                    max-lg:fixed max-lg:bottom-0 max-lg:left-0 max-lg:right-0 max-lg:z-50
                    max-lg:bg-[var(--mat-sys-surface-container)] max-lg:border-t max-lg:border-[var(--mat-sys-outline-variant)]
                    max-lg:shadow-lg safe-area-pb">
          <!-- Secondary controls scroll; the actions after this row stay pinned, so no
               viewport can push the primary action out of reach or paint it over the
               shell controls the toolbar is projected next to.
               py-1.5 / pr-1.5 leave room for the icon buttons' 48px touch targets: they
               overhang the 36px buttons, and in a scrolling row that overhang alone
               produced a scrollbar on a header with plenty of free width.
               Below lg this group dissolves into the bar, so the filters and the pinned
               actions wrap as one row of controls, each line centred on its own. -->
          <div class="flex flex-wrap lg:flex-nowrap items-center max-lg:contents lg:gap-4 min-w-0 flex-1 lg:overflow-x-auto lg:py-1.5 lg:pr-1.5">
            @if (scoped()) {
              <button class="${TOUCH_ICON_BUTTON}" mat-icon-button (click)="exitScope()"
                      [matTooltip]="I18N.culling.exit_scene | translate"
                      [attr.aria-label]="I18N.culling.exit_scene | translate">
                <mat-icon>arrow_back</mat-icon>
              </button>
            }
            <!-- Filters ordered by impact: scope → granularity → sort → category →
                 thresholds. The actions live in the pinned cluster below. -->
            @if (cull.albums().length > 0) {
              <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="scopeMenu"
                      [class.!text-[var(--mat-sys-primary)]]="albumScoped()"
                      [matTooltip]="cull.albumScopeLabel() ?? (I18N.culling.scope_whole_library | translate)"
                      [attr.aria-label]="cull.albumScopeLabel() ?? (I18N.culling.scope_whole_library | translate)">
                <mat-icon>filter_alt</mat-icon>
              </button>
              <mat-menu #scopeMenu="matMenu">
                <button mat-menu-item (click)="scopeWholeLibrary()">
                  <mat-icon>photo_library</mat-icon>
                  <span>{{ I18N.culling.scope_whole_library | translate }}</span>
                </button>
                @for (a of cull.albums(); track a.id) {
                  <button mat-menu-item [matMenuTriggerFor]="sceneMenu" (menuOpened)="loadAlbumScenes(a)">
                    <mat-icon>photo_album</mat-icon>
                    <span>{{ a.name }}</span>
                  </button>
                }
              </mat-menu>
              <mat-menu #sceneMenu="matMenu">
                <button mat-menu-item (click)="scopeAlbumWhole()">
                  <mat-icon>photo_album</mat-icon>
                  <span>{{ I18N.culling.scope_whole_album | translate }}</span>
                </button>
                @if (loadingScenes()) {
                  <div class="flex justify-center px-4 py-2"><mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate" /></div>
                } @else {
                  @for (s of expandedScenes(); track s.scene_id) {
                    <button mat-menu-item (click)="scopeAlbumScene(s)">
                      <mat-icon>movie_filter</mat-icon>
                      <span>{{ s.start | sceneDate }} · {{ s.count }}@if (s.moment | momentLabel; as ml) { · {{ ml }}}</span>
                    </button>
                  }
                }
              </mat-menu>
            }
            <!-- Not behind the albums check: a date window needs no album. The range input is an invisible
                 anchor for the custom picker's popup; it never takes focus or pointer events. -->
            <div class="relative inline-flex shrink-0">
              <button mat-button class="${TOUCH_TEXT_BUTTON} !min-w-0 !px-3 shrink-0 ${XL_LABEL_BUTTON}" data-testid="cull-date-range" [matMenuTriggerFor]="dateRangeMenu"
                      [class.!text-[var(--mat-sys-primary)]]="cull.dateRangeActive()"
                      [matTooltip]="cull.dateRangeActive() ? (cull.scopeFrom() | cullDateRange: cull.scopeTo()) : (I18N.culling.date_range.label | translate)"
                      [attr.aria-label]="(I18N.culling.date_range.label | translate) + (cull.dateRangeActive() ? ': ' + (cull.scopeFrom() | cullDateRange: cull.scopeTo()) : '')">
                <mat-icon>date_range</mat-icon>
                <span class="hidden xl:inline text-sm">{{ cull.dateRangeActive() ? (cull.scopeFrom() | cullDateRange: cull.scopeTo()) : (I18N.culling.date_range.label | translate) }}</span>
              </button>
              <mat-date-range-input #rangeInput [rangePicker]="rangePicker" aria-hidden="true"
                                    class="absolute inset-0 overflow-hidden opacity-0 pointer-events-none">
                <input matStartDate tabindex="-1"
                       [attr.aria-label]="I18N.culling.date_range.start | translate"
                       [value]="cull.scopeFrom() | scopeDate" />
                <input matEndDate tabindex="-1"
                       [attr.aria-label]="I18N.culling.date_range.end | translate"
                       [value]="cull.scopeTo() | scopeDate"
                       (dateChange)="onCustomRangeEnd(rangeInput.value?.start ?? null, $event.value)" />
              </mat-date-range-input>
              <mat-date-range-picker #rangePicker />
            </div>
            <mat-menu #dateRangeMenu="matMenu">
              @for (preset of datePresets; track preset.id) {
                <button mat-menu-item (click)="onDatePreset(preset.id)">
                  <mat-icon>{{ preset.icon }}</mat-icon>
                  <span>{{ preset.labelKey | translate }}</span>
                </button>
              }
              <button mat-menu-item (click)="rangePicker.open()">
                <mat-icon>edit_calendar</mat-icon>
                <span>{{ I18N.culling.date_range.custom | translate }}</span>
              </button>
              <div role="separator" class="my-1 border-t border-[var(--mat-sys-outline-variant)]"></div>
              <button mat-menu-item [disabled]="!cull.dateRangeActive()" (click)="onDateRange(null, null)">
                <mat-icon>all_inclusive</mat-icon>
                <span>{{ I18N.culling.date_range.all_dates | translate }}</span>
              </button>
            </mat-menu>
            <button mat-button class="${TOUCH_TEXT_BUTTON} !min-w-0 !px-3 shrink-0" data-testid="cull-group-by" [matMenuTriggerFor]="cullGroupByMenu"
                    [class.!text-[var(--mat-sys-primary)]]="cull.groupBy() !== 'all'"
                    [matTooltip]="I18N.culling.group_by.label | translate"
                    [attr.aria-label]="(I18N.culling.group_by.label | translate) + ': ' + (cull.groupBy() | cullGroupLabel | translate)">
              <mat-icon>{{ cull.groupBy() | cullGroupIcon }}</mat-icon>
              <span class="text-sm">{{ cull.groupBy() | cullGroupLabel | translate }}</span>
            </button>
            <mat-menu #cullGroupByMenu="matMenu">
              <button mat-menu-item (click)="onGroupByChange('all')">
                <mat-icon>{{ 'all' | cullGroupIcon }}</mat-icon>
                <span [class.font-bold]="cull.groupBy() === 'all'">{{ I18N.culling.group_by.all | translate }}</span>
              </button>
              <button mat-menu-item (click)="onGroupByChange('burst')">
                <mat-icon>{{ 'burst' | cullGroupIcon }}</mat-icon>
                <span [class.font-bold]="cull.groupBy() === 'burst'">{{ I18N.culling.group_by.bursts | translate }}</span>
              </button>
              <button mat-menu-item (click)="onGroupByChange('similar')">
                <mat-icon>{{ 'similar' | cullGroupIcon }}</mat-icon>
                <span [class.font-bold]="cull.groupBy() === 'similar'">{{ I18N.culling.group_by.similar | translate }}</span>
              </button>
              <button mat-menu-item (click)="onGroupByChange('lookalike')">
                <mat-icon>{{ 'lookalike' | cullGroupIcon }}</mat-icon>
                <span [class.font-bold]="cull.groupBy() === 'lookalike'">{{ I18N.culling.group_by.lookalikes | translate }}</span>
              </button>
              @if (store.config()?.features?.show_scenes || cull.groupBy() === 'scene') {
                <button mat-menu-item (click)="onGroupByChange('scene')">
                  <mat-icon>{{ 'scene' | cullGroupIcon }}</mat-icon>
                  <span [class.font-bold]="cull.groupBy() === 'scene'">{{ I18N.culling.group_by.scenes | translate }}</span>
                </button>
              }
              <button mat-menu-item (click)="onGroupByChange('bracket')">
                <mat-icon>{{ 'bracket' | cullGroupIcon }}</mat-icon>
                <span [class.font-bold]="cull.groupBy() === 'bracket'">{{ I18N.culling.group_by.brackets | translate }}</span>
              </button>
              <button mat-menu-item (click)="onGroupByChange('panorama')">
                <mat-icon>{{ 'panorama' | cullGroupIcon }}</mat-icon>
                <span [class.font-bold]="cull.groupBy() === 'panorama'">{{ I18N.culling.group_by.panoramas | translate }}</span>
              </button>
              <button mat-menu-item (click)="onGroupByChange('hdr_panorama')">
                <mat-icon>{{ 'hdr_panorama' | cullGroupIcon }}</mat-icon>
                <span [class.font-bold]="cull.groupBy() === 'hdr_panorama'">{{ I18N.culling.group_by.hdr_panoramas | translate }}</span>
              </button>
            </mat-menu>
            @if (cull.groupBy() !== 'scene' && cull.groupBy() !== 'lookalike') {
              <button mat-button class="${TOUCH_TEXT_BUTTON} !min-w-0 !px-3 shrink-0 ${XL_LABEL_BUTTON}" [matMenuTriggerFor]="cullSortMenu" [disabled]="cull.planActive()"
                      [class.!text-[var(--mat-sys-primary)]]="cull.sortMode() !== 'easiest'"
                      [matTooltip]="'culling.sort.' + cull.sortMode() | translate"
                      [attr.aria-label]="'culling.sort.' + cull.sortMode() | translate">
                <mat-icon>{{ cull.sortMode() | sortIcon }}</mat-icon>
                <span class="hidden xl:inline text-sm">{{ 'culling.sort.' + cull.sortMode() | translate }}</span>
              </button>
              <mat-menu #cullSortMenu="matMenu">
                @for (m of sortModes; track m) {
                  <button mat-menu-item (click)="onSortChange(m)">
                    <mat-icon>{{ m | sortIcon }}</mat-icon>
                    <span [class.font-bold]="cull.sortMode() === m">{{ 'culling.sort.' + m | translate }}</span>
                  </button>
                }
              </mat-menu>
              <button class="${TOUCH_ICON_BUTTON}" mat-icon-button (click)="toggleSortDirection()" [disabled]="cull.planActive()"
                      [class.!text-[var(--mat-sys-primary)]]="cull.sortDirection() !== ''"
                      [matTooltip]="(sortAscending() ? I18N.culling.sort.ascending : I18N.culling.sort.descending) | translate"
                      [attr.aria-label]="(sortAscending() ? I18N.culling.sort.ascending : I18N.culling.sort.descending) | translate">
                <mat-icon>{{ sortAscending() ? 'arrow_upward' : 'arrow_downward' }}</mat-icon>
              </button>
            }
            @if (categoryOptions().length > 0) {
              <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="cullCategoryMenu"
                      [class.!text-[var(--mat-sys-primary)]]="categoryFilter() !== ''"
                      [matTooltip]="categoryFilter() ? (('category_names.' + categoryFilter()) | translate) : (I18N.culling.filter_category | translate)"
                      [attr.aria-label]="categoryFilter() ? (('category_names.' + categoryFilter()) | translate) : (I18N.culling.filter_category | translate)">
                <mat-icon>{{ categoryFilter() | categoryIcon }}</mat-icon>
              </button>
              <mat-menu #cullCategoryMenu="matMenu">
                <button mat-menu-item (click)="onCategoryFilterChange('')">
                  <mat-icon>category</mat-icon>
                  <span [class.font-bold]="categoryFilter() === ''">{{ I18N.culling.all_categories | translate }}</span>
                </button>
                @for (c of categoryOptions(); track c) {
                  <button mat-menu-item (click)="onCategoryFilterChange(c)">
                    <mat-icon>{{ c | categoryIcon }}</mat-icon>
                    <span [class.font-bold]="categoryFilter() === c">{{ 'category_names.' + c | translate }}</span>
                  </button>
                }
              </mat-menu>
            }
            @if (cull.groupBy() === 'similar' || cull.groupBy() === 'all') {
              <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="thresholdMenu" [disabled]="cull.planActive()"
                      [matTooltip]="(I18N.culling.threshold | translate) + ' · ' + cull.similarityThreshold() + '%'"
                      [attr.aria-label]="I18N.culling.threshold | translate">
                <mat-icon>compare</mat-icon>
              </button>
              <mat-menu #thresholdMenu="matMenu">
                <div class="flex flex-col gap-1 px-4 py-3" tabindex="-1" (click)="$event.stopPropagation()" (keydown)="$event.stopPropagation()">
                  <div class="flex items-center gap-2">
                    <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.culling.threshold | translate }}</span>
                    <mat-slider class="!w-28 !min-w-0" [min]="70" [max]="95" [step]="5" [discrete]="true">
                      <input matSliderThumb [value]="cull.similarityThreshold()" (valueChange)="onThresholdChange($event)" [attr.aria-label]="I18N.culling.threshold | translate" />
                    </mat-slider>
                    <span class="text-xs font-medium w-8">{{ cull.similarityThreshold() }}%</span>
                  </div>
                  <p class="m-0 max-w-64 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.culling.threshold_hint | translate }}</p>
                </div>
              </mat-menu>
            }
            @if (cull.cullProfiles().length > 0) {
              <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="profileMenu" [disabled]="cull.planActive()"
                      [class.!text-[var(--mat-sys-primary)]]="cull.selectedProfile() !== ''"
                      [matTooltip]="selectedProfileLabel() | translate"
                      [attr.aria-label]="selectedProfileLabel() | translate">
                <mat-icon>{{ cull.selectedProfile() | cullProfileIcon }}</mat-icon>
              </button>
              <mat-menu #profileMenu="matMenu">
                @for (p of cull.cullProfiles(); track p.id) {
                  <button mat-menu-item (click)="cull.applyProfile(p)">
                    <mat-icon>{{ p.id | cullProfileIcon }}</mat-icon>
                    <span [class.font-bold]="cull.selectedProfile() === p.id">{{ p.label_key | translate }}</span>
                  </button>
                }
              </mat-menu>
            }
            <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="strictnessMenu"
                    [matTooltip]="(I18N.culling.strictness_tooltip | translate) + ' · ' + cull.strictness() + '%'"
                    [attr.aria-label]="I18N.culling.strictness | translate">
              <mat-icon>tune</mat-icon>
            </button>
            <mat-menu #strictnessMenu="matMenu">
              <div class="flex items-center gap-2 px-4 py-3" tabindex="-1" (click)="$event.stopPropagation()" (keydown)="$event.stopPropagation()">
                <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.culling.strictness | translate }}</span>
                <mat-slider class="!w-28 !min-w-0" [min]="0" [max]="100" [step]="5" [discrete]="true">
                  <input matSliderThumb [value]="cull.strictness()" (valueChange)="onStrictnessChange($event)" [attr.aria-label]="I18N.culling.strictness | translate" />
                </mat-slider>
                <span class="text-xs font-medium w-8">{{ cull.strictness() }}%</span>
              </div>
            </mat-menu>
          </div>
          <!-- Exclude-rejected and the loupe act on the photos rather than
               selecting which ones the feed serves, so they are pinned with the
               other actions instead of scrolling away with the filters. -->
          <button mat-icon-button class="${TOUCH_ICON_BUTTON} shrink-0 max-lg:ml-auto" (click)="onExcludeRejectedChange(!cull.excludeRejected())"
                  [class.!text-[var(--mat-sys-primary)]]="cull.excludeRejected()"
                  [attr.aria-pressed]="cull.excludeRejected()"
                  [matTooltip]="I18N.culling.exclude_rejected | translate"
                  [attr.aria-label]="I18N.culling.exclude_rejected | translate">
            <mat-icon>{{ cull.excludeRejected() ? 'visibility_off' : 'visibility' }}</mat-icon>
          </button>
          <button mat-icon-button class="${TOUCH_ICON_BUTTON} shrink-0" (click)="loupeActive.set(!loupeActive())"
                  [class.!text-[var(--mat-sys-primary)]]="loupeActive()"
                  [attr.aria-pressed]="loupeActive()"
                  [matTooltip]="I18N.culling.loupe_hint | translate"
                  [attr.aria-label]="I18N.culling.loupe | translate">
            <mat-icon>{{ loupeActive() ? 'zoom_in' : 'search' }}</mat-icon>
          </button>
          @if (auth.isEdition() && !keepWholeGranularity() && cull.groupBy() !== 'lookalike') {
            <button mat-icon-button class="${TOUCH_ICON_BUTTON} shrink-0" (click)="cull.openAutoCull()" [disabled]="cull.autoCullBusy()"
                    [matTooltip]="I18N.culling.auto_cull.tooltip | translate"
                    [attr.aria-label]="I18N.culling.auto_cull.button | translate">
              <mat-icon>auto_fix_high</mat-icon>
            </button>
          }
          @if (auth.isEdition() && store.config()?.cull?.trash_available) {
            <button mat-icon-button class="${TOUCH_ICON_BUTTON} shrink-0" (click)="openTrashRejects()"
                    [matTooltip]="I18N.cull.trash_all_rejects | translate"
                    [attr.aria-label]="I18N.cull.trash_all_rejects | translate">
              <mat-icon>delete_sweep</mat-icon>
            </button>
          }
          @if (!stacksMode() && unconfirmedCount() > 0) {
            <button mat-flat-button (click)="confirmAllRemaining()" [disabled]="cull.confirming() || cull.replanning()" class="!rounded-md shrink-0 max-lg:basis-full max-lg:order-last max-lg:!h-11">
              <mat-icon>done_all</mat-icon>
              {{ I18N.culling.confirm_all | translate }} ({{ unconfirmedCount() }})
            </button>
          }
          @if (loupeActive()) {
            <div class="flex shrink-0 items-center gap-2 max-lg:basis-full">
            <span class="text-xs whitespace-nowrap">{{ I18N.gallery.compare.inspection.magnification | translate }}: {{ loupeZoom() }}×</span>
            <mat-slider data-culling-loupe-slider class="!w-28 !min-w-0 flex-1 max-lg:!mx-0" [min]="2" [max]="8" [step]="1" [discrete]="true">
              <input matSliderThumb [value]="loupeZoom()" (valueChange)="loupeZoom.set($event)"
                     [attr.aria-label]="I18N.gallery.compare.inspection.magnification | translate" />
            </mat-slider>
            </div>
          }
        </div>
        }
      </ng-template>


      @if (stackNotice()) {
        <p role="status" data-testid="stack-scope-notice">{{ I18N.stacks.invalid_scope | translate }}</p>
      }
      <!-- Corrections change nothing until the detector runs again, and that run
           is a whole-library batch pass -- far too expensive to fire once per
           click. So they accumulate and the run is offered here, once. -->
      @if (!stacksMode() && cull.rerunNeeded() > 0) {
        <div class="shrink-0 flex flex-wrap items-center gap-3 p-3 mb-3 rounded-lg bg-[var(--mat-sys-surface-container)]" role="status">
          <mat-icon class="!text-base !w-5 !h-5 !leading-5 text-amber-500" aria-hidden="true">schedule</mat-icon>
          <span class="text-sm">{{ I18N.culling.panorama.rerun_banner | translate:{ count: cull.rerunNeeded() } }}</span>
          <button mat-stroked-button class="!h-8 !text-sm !rounded-md" [disabled]="detecting()"
                  (click)="rerunDetection()"
                  [matTooltip]="I18N.panorama.settings.redetect_tooltip | translate">
            <mat-icon>refresh</mat-icon>{{ I18N.panorama.settings.redetect | translate }}
          </button>
          @if (detecting()) { <mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate" /> }
          @if (detectMessage(); as m) {
            <span class="text-sm opacity-80" [class.text-red-500]="detectFailed()">{{ m | translate }}</span>
          }
        </div>
      }

      @if (cull.pendingReload()) {
        <div role="status" data-testid="assistant-reload-banner" class="flex items-center justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 mb-2 text-sm">
          <span>{{ I18N.culling.assistant_changed | translate }}</span>
          <button mat-stroked-button type="button" (click)="cull.resetForReload()">{{ I18N.pwa.reload | translate }}</button>
        </div>
      }

      @if (!stacksMode() && cull.planActive()) {
        <div role="status" data-testid="cull-plan-banner" class="shrink-0 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--mat-sys-primary)]/40 bg-[var(--mat-sys-primary)]/10 px-4 py-2 mb-2 text-sm">
          <mat-icon class="!text-base !w-5 !h-5 !leading-5 text-[var(--mat-sys-primary)]" aria-hidden="true">smart_toy</mat-icon>
          <span class="font-medium">{{ I18N.culling.plan.banner | translate:{ confirmed: cull.confirmedGroups().size, total: cull.totalGroups() } }}</span>
          @if (cull.planOversize() > 0) {
            <span data-testid="cull-plan-oversize" class="opacity-80">{{ I18N.culling.plan.oversize | translate:{ count: cull.planOversize() } }}</span>
          }
          <button mat-stroked-button type="button" data-testid="cull-plan-exit" class="ml-auto" (click)="exitPlan()">{{ I18N.culling.plan.exit | translate }}</button>
        </div>
      }

      <!-- Scrollable group list; the header above stays fixed -->
      <div class="flex-1 min-h-0 overflow-y-auto -mx-2 px-2 md:-mx-3 md:px-3 pb-4 max-lg:pb-[calc(var(--cull-bar-h)+1rem)]" data-culling-scroll
           [style.--cull-bar-h]="barHeight() + 'px'">
      <!-- Content -->
      @if (cull.loading()) {
        <!-- The page-load spinner the albums, persons, timeline, folders and stats pages show;
             the status text announces it, so the spinner itself stays out of the reading order. -->
        <div data-culling-loading class="flex justify-center py-16" role="status">
          <span class="sr-only">{{ I18N.ui.labels.loading | translate }}</span>
          <mat-spinner diameter="48" aria-hidden="true" />
        </div>
      } @else if (visibleGroups().length === 0) {
        <p class="text-center py-20 text-[var(--mat-sys-on-surface-variant)]">{{ emptyKey() | translate }}</p>
      } @else {
        <div class="space-y-3 pb-4">
          @for (group of visibleGroups(); track group.group_id + '_' + group.type; let i = $index) {
            @let groupKey = group | cullGroupKey;
            <div class="rounded-xl border-2 overflow-hidden transition-colors duration-300"
                 [attr.data-gidx]="i" [attr.data-culling-group-key]="groupKey" tabindex="-1"
                 [ngClass]="i === selectedGroupIndex()
                   ? 'bg-[var(--mat-sys-surface-container-high)] border-[var(--mat-sys-surface-container-high)]'
                   : 'bg-[var(--mat-sys-surface-container)] border-[var(--mat-sys-surface-container)]'">
              @if (!stacksMode() && group.plan; as plan) {
                <div data-testid="cull-plan-chip" class="flex flex-wrap items-center gap-2 px-4 pt-2 text-xs">
                  <span class="font-bold">#{{ plan.number }}</span>
                  @if (group | cullPlanGroupReason; as reason) {
                    <span class="opacity-80">{{ reason.key | translate:reason.params }}</span>
                  }
                  <span class="opacity-80">{{ I18N.culling.plan.suggestion | translate:{ keep: plan.keep_paths.length, reject: group | planRejectCount } }}</span>
                  @if (group | planGroupNote:cull.suggestions().notes; as note) {
                    <span data-testid="cull-plan-note"
                          class="max-w-[40ch] truncate rounded-full bg-sky-500/20 px-2 py-0.5 text-sky-800 dark:text-sky-200"
                          [matTooltip]="note">{{ note }}</span>
                  }
                </div>
              }
              @if (group.start) {
                <div class="flex items-center gap-2 px-4 pt-2 text-xs">
                  <mat-icon class="!text-base text-[var(--mat-sys-primary)]">schedule</mat-icon>
                  <span class="opacity-80">{{ group.start | sceneDate }}</span>
                  @if (group.moment | momentLabel; as ml) {
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[var(--mat-sys-primary)]/12 text-[var(--mat-sys-primary)]"
                          [class.!opacity-50]="group.moment_confidence | momentUncertain:momentConfidenceMin()">
                      <mat-icon class="!text-sm !w-4 !h-4 !leading-4" [class]="'moment' | markTone">✦</mat-icon>{{ ml }}@if (group.moment_confidence | momentUncertain:momentConfidenceMin()) { <span class="opacity-80">({{ I18N.moments.uncertain | translate }})</span> }
                    </span>
                  }
                </div>
              }
              <!-- One subject at several exposures, not competing takes: say so
                   rather than let the user hunt for the "best" of a bracket. -->
              @if (group.sequence_kind === 'bracket') {
                <div class="flex items-center gap-2 px-4 pt-2 text-xs">
                  <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-600 dark:text-amber-400">
                    <mat-icon class="!text-sm !w-4 !h-4 !leading-4">{{ 'bracket' | cullGroupIcon }}</mat-icon>{{ I18N.culling.bracket.label | translate }}
                  </span>
                  <span class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.culling.bracket.hint | translate }}</span>
                </div>
              }
              <!-- A pan has no best frame: every one covers a different part of
                   the scene and the set only means anything whole. -->
              @if (group.sequence_kind === 'panorama' || group.sequence_kind === 'hdr_panorama') {
                <div class="flex flex-wrap items-center gap-2 px-4 pt-2 text-xs">
                  <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-sky-500/20 text-sky-600 dark:text-sky-400">
                    <mat-icon class="!text-sm !w-4 !h-4 !leading-4">{{ group.sequence_kind | cullGroupIcon }}</mat-icon>{{ group.sequence_kind | sequenceKindLabel | translate }}
                  </span>
                  <span class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.culling.panorama.hint | translate }}</span>
                </div>
              }
              <!-- The pending/corrected chip renders for ANY group carrying a
                   sequence_override, not only a panorama-kind one: a plain
                   burst group with a pending bracket correction has no
                   sequence_kind yet (the correction has not applied), which is
                   exactly when the chip matters most. The detector still owns
                   the label above until it runs again, so a saved correction
                   can only ever read as pending here -- saying otherwise would
                   claim a set had changed while the feed still groups it the
                   old way. -->
              @if (!stacksMode() && (group | groupOverridePending); as pending) {
                <div class="flex flex-wrap items-center gap-2 px-4 pt-2 text-xs">
                  <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-700 dark:text-amber-300"
                        [matTooltip]="I18N.culling.panorama.pending_tooltip | translate">
                    <mat-icon class="!text-sm !w-4 !h-4 !leading-4" aria-hidden="true">schedule</mat-icon>{{ I18N.culling.panorama.pending | translate }}
                    <span class="opacity-80">({{ (pending === 'suppressed' ? I18N.culling.panorama.not_a_panorama : (pending | sequenceKindLabel)) | translate }})</span>
                  </span>
                </div>
              }
              <!-- Photos. Frames are sized by width, not by a fitted row: up to
                   four sit in one flex row of equal-width tiles (stacked
                   below sm), and a larger group switches to a wrapping
                   auto-fill grid of 14rem+ columns. Neither layout scrolls
                   horizontally; each image keeps its aspect ratio inside its
                   tile and is capped in height. aspect-ratio auto 3/2 holds a
                   3:2 box until the thumbnail loads (the feed carries no pixel
                   size), so the row does not jump when it arrives. -->
              <div class="px-2 py-3 transition-opacity duration-300"
                   [class]="group.photos.length > 4 ? 'grid max-sm:grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-2 md:gap-3' : 'flex max-sm:flex-col gap-2 md:gap-3'"
                   [class.pointer-events-none]="(group | isConfirmed:cull.confirmedGroups())"
                   [class.opacity-40]="(group | isConfirmed:cull.confirmedGroups())">
                @for (photo of group.photos; track photo.path; let pIdx = $index) {
                  <div #tile class="group/photo relative block cursor-pointer rounded-lg overflow-hidden border-2 transition-colors min-w-0 sm:flex-1 sm:basis-0"
                       [attr.data-pidx]="pIdx"
                       [ngClass]="i === selectedGroupIndex() && pIdx === selectedPhotoIndex()
                         ? 'ring-4 ring-[var(--mat-sys-primary)] ring-offset-2 ring-offset-[var(--mat-sys-surface-container-high)]'
                         : ''"
                       [class.border-green-500]="photo.path | isKept:cull.selectionsMap():groupKey"
                       [class.border-red-500]="!(photo.path | isKept:cull.selectionsMap():groupKey) && (photo.path | isDecided:cull.selectionsMap():groupKey:cull.touchedGroups().has(groupKey))"
                       [class.border-transparent]="!(photo.path | isDecided:cull.selectionsMap():groupKey:cull.touchedGroups().has(groupKey))"
                       role="button"
                       tabindex="0"
                       [attr.aria-label]="stacksMode() ? photo.filename : photo.filename + ', ' + (
                         (photo.path | isKept:cull.selectionsMap():groupKey)
                           ? (I18N.culling.lightbox.kept | translate)
                           : (photo.path | isDecided:cull.selectionsMap():groupKey:cull.touchedGroups().has(groupKey))
                             ? (I18N.culling.lightbox.rejected | translate)
                             : (I18N.culling.lightbox.undecided | translate))"
                       [attr.aria-pressed]="stacksMode() ? null : (photo.path | isKept:cull.selectionsMap():groupKey)"
                       (click)="stacksMode() ? openLightbox(group, pIdx) : cull.tileClick(photo.path, group)"
                       (keydown.enter)="stacksMode() ? openLightbox(group, pIdx) : cull.toggleSelection(photo.path, group); $event.stopPropagation()"
                       data-culling-image-tile
                       (keydown.space)="onTileContinue($event, group, pIdx); $event.stopPropagation()"
                       (dblclick)="stacksMode() ? openLightbox(group, pIdx) : cull.tileDoubleClick(photo.path, group); $event.stopPropagation()">
                    <img [src]="photo.path | thumbnailUrl:storedEdge:photo.preview_revision"
                         [appLoupe]="photo.path | imageUrl:true:photo.preview_revision"
                         [loupeActive]="loupeActive()"
                         [loupeZoom]="loupeZoom()"
                         loupeFit="contain"
                         class="block w-full h-auto aspect-[auto_3/2] object-contain max-sm:max-h-[60dvh] sm:max-h-[min(24rem,calc(100dvh-20rem))]" [alt]="photo.filename" loading="lazy" />
                    @if (!stacksMode()) {
                      @if (photo.path === group.best_path) {
                        <div class="absolute top-2 left-2 px-2 py-0.5 rounded bg-green-700 text-white text-xs font-bold">
                          {{ I18N.photo_detail.assessment.group_pick | translate }}
                        </div>
                      } @else if (photo.cull_reason; as reason) {
                        <div class="absolute top-2 left-2 px-2 py-0.5 rounded bg-black/70 text-white text-xs font-medium max-w-[160px] truncate">
                          {{ reason | cullReason }}
                        </div>
                      }
                      @if (photo.path | isKept:cull.selectionsMap():groupKey) {
                        <div class="absolute top-2 right-2 w-7 h-7 rounded-full bg-green-600 inline-flex items-center justify-center">
                          <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-white">check</mat-icon>
                        </div>
                      } @else if (photo.path | isDecided:cull.selectionsMap():groupKey:cull.touchedGroups().has(groupKey)) {
                        <div class="absolute top-2 right-2 w-7 h-7 rounded-full bg-red-600 inline-flex items-center justify-center">
                          <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-white">close</mat-icon>
                        </div>
                      }
                    }
                    @if (photo.path | planDiffers:group:cull.selectionsMap()) {
                      @let accepted = photo.path | planAccepted:group:cull.selectionsMap():cull.suggestions().photos;
                      <span data-testid="plan-differs-dot"
                            class="absolute top-2 right-11 w-3 h-3 rounded-full bg-amber-400 ring-2 ring-black/60"
                            [matTooltip]="(accepted ? I18N.culling.plan.accepted : I18N.culling.plan.differs) | translate"
                            [attr.aria-label]="(accepted ? I18N.culling.plan.accepted : I18N.culling.plan.differs) | translate"></span>
                    }
                    @if (photo.path | planSuggestion:group:cull.selectionsMap():cull.suggestions().photos:cull.closedGroupKeys(); as suggestion) {
                      <!-- A native button: Enter and Space become a click that accepts. Every event the tile
                           or the document also handles stops here, or accepting would toggle the tile too. -->
                      <button type="button" data-testid="plan-suggestion-badge"
                              class="absolute top-10 left-2 inline-flex items-center gap-1 rounded border border-dashed px-2 py-0.5 text-xs font-medium max-w-[160px]"
                              [ngClass]="suggestion.action === 'keep'
                                ? 'border-green-300 bg-green-900/80 text-green-100'
                                : 'border-red-300 bg-red-900/80 text-red-100'"
                              [matTooltip]="suggestion.reason"
                              [attr.aria-label]="((suggestion.action === 'keep' ? I18N.culling.plan.suggest_keep : I18N.culling.plan.suggest_reject) | translate) + '. ' + ((suggestion.action === 'keep' ? I18N.culling.plan.accept_keep : I18N.culling.plan.accept_reject) | translate:{ reason: suggestion.reason })"
                              (click)="cull.acceptSuggestion(group, photo.path, suggestion.action); tile.focus(); $event.stopPropagation()"
                              (dblclick)="$event.stopPropagation()"
                              (keydown.enter)="$event.stopPropagation()"
                              (keydown.space)="$event.stopPropagation()">
                        <mat-icon class="!text-sm !w-4 !h-4 !leading-4" aria-hidden="true">{{ suggestion.action === 'keep' ? 'check' : 'close' }}</mat-icon>
                        <span class="truncate">{{ (suggestion.action === 'keep' ? I18N.culling.plan.suggest_keep : I18N.culling.plan.suggest_reject) | translate }}</span>
                      </button>
                    }
                    <div class="absolute bottom-2 left-2 flex items-center gap-1">
                      <span class="px-2 py-0.5 rounded bg-black/60 text-white text-xs font-medium">
                        {{ I18N.photo_detail.assessment.score | translate }} {{ photo.aggregate | assessmentValue }}
                      </span>
                      @if (!stacksMode()) {
                        @if (photo.is_rejected) {
                          <span data-testid="reject-marker" class="px-2 py-0.5 rounded bg-red-700 text-white text-xs font-bold">
                            {{ I18N.rating.rejected_badge | translate }}
                          </span>
                        } @else if (photo.is_kept) {
                          <span data-testid="kept-marker" class="px-2 py-0.5 rounded bg-green-700 text-white text-xs font-bold">
                            {{ I18N.review.kept | translate }}
                          </span>
                        }
                      }
                      @if (photo.sequence_kind === 'bracket') {
                        <span class="px-2 py-0.5 rounded bg-amber-600 text-white text-xs font-bold">
                          {{ photo.sequence_ev_offset | evOffset }}
                        </span>
                      }
                    </div>
                    @if (photo.is_blink) {
                      <div class="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-yellow-600 text-white text-xs font-bold">
                        {{ I18N.ui.badges.blink | translate }}
                      </div>
                    }
                    @if (!(photo.path | isKept:cull.selectionsMap():groupKey)) {
                      <button class="absolute top-2 right-2 w-7 h-7 rounded-full bg-black/60 inline-flex items-center justify-center opacity-0 group-hover/photo:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100 pointer-coarse:after:absolute pointer-coarse:after:-inset-2 pointer-coarse:after:content-[''] transition-opacity cursor-pointer"
                              [matTooltip]="I18N.culling.view_detail | translate"
                              [attr.aria-label]="I18N.culling.view_detail | translate"
                              (click)="openDetail($event, photo.path)">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-white">info</mat-icon>
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
                <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">
                  @if (group.count > group.photos.length) { {{ I18N.culling.photos_shown_of | translate:{ shown: group.photos.length, count: group.count } }} }
                  @else { {{ group.count }} {{ I18N.culling.photos | translate }} }
                  @if (group.lookalike) {
                    @for (signal of group.lookalike | lookalikeSignals; track signal.key) { · {{ signal.key | translate:signal.params }} }
                  } @else if (group.similarity_percent; as percent) { · {{ I18N.culling.group_reason.similar_percent | translate:{ percent } }} }
                </span>
                @if (stacksMode()) {
                  @if (cull.stackDrafts()[groupKey].excludedCount; as count) { <span data-stack-excluded role="status" class="text-xs">{{ I18N.stacks.reject_count | translate:{ count } }}</span> }
                  <div class="flex flex-wrap gap-2 ml-auto">
                    <button data-culling-open class="${TOUCH_TEXT_BUTTON}" mat-button (click)="openLightbox(group, 0)">{{ I18N.culling.darkroom | translate }}</button>
                    <button class="${TOUCH_TEXT_BUTTON}" mat-button [disabled]="cull.stackBusy()" (click)="editSuggestion(group)">{{ I18N.stacks.suggestion_edit_members | translate }}</button>
                    <button class="${TOUCH_TEXT_BUTTON}" mat-button [disabled]="cull.stackBusy()" (click)="skipStackSuggestion(group)">{{ I18N.stacks.suggestion_skip | translate }}</button>
                    <button mat-flat-button [disabled]="cull.stackBusy() || cull.stackDrafts()[groupKey].paths.length < 2" (click)="stackGroup(group)">{{ I18N.stacks.stack_cover | translate }}</button>
                  </div>
                } @else {
                @if (group.category; as category) {
                  @if (cull.comparisonStats(); as stats) {
                    @if ((category | weightRemaining:stats); as remaining) {
                      <button class="inline-flex items-center justify-center w-6 h-6 pointer-coarse:w-11 pointer-coarse:h-11 rounded hover:bg-[var(--mat-sys-surface-container-high)] transition-colors cursor-pointer"
                              (click)="tuneCategory(category)"
                              [matTooltip]="I18N.culling.weight_remaining | translate:{ count: remaining }"
                              [attr.aria-label]="I18N.culling.weight_remaining | translate:{ count: remaining }">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-60">tune</mat-icon>
                      </button>
                    } @else {
                      <button class="inline-flex items-center justify-center w-6 h-6 pointer-coarse:w-11 pointer-coarse:h-11 rounded hover:bg-[var(--mat-sys-surface-container-high)] transition-colors cursor-pointer"
                              (click)="tuneCategory(category)"
                              [matTooltip]="I18N.culling.weight_ready | translate"
                              [attr.aria-label]="I18N.culling.weight_ready | translate">
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-[var(--facet-positive)]">tune</mat-icon>
                      </button>
                    }
                  }
                  <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ 'category_names.' + category | translate }}</span>
                }
                @if ((group | isConfirmed:cull.confirmedGroups())) {
                  <span class="inline-flex items-center gap-1 text-xs text-[var(--facet-positive)] font-medium">
                    <mat-icon class="inline-flex !text-sm !w-4 !h-4 !leading-4">check_circle</mat-icon>
                    {{ I18N.culling.confirmed_badge | translate }}
                  </span>
                }
                <div class="flex gap-2 ml-auto">
                  @if (group | isPassing:cull.passingGroups()) {
                    <div class="relative overflow-hidden rounded-md">
                      <button mat-stroked-button data-culling-cancel (click)="cancelGroupPass(group, $event)" class="!h-8 max-sm:!h-11 pointer-coarse:!h-11 !text-sm !rounded-md relative z-10"
                              [matTooltip]="I18N.culling.cancel_restore | translate">
                        {{ I18N.culling.cancel_pass | translate }} ({{ group | passCountdown:cull.passingGroups() }}s)
                      </button>
                      <div class="absolute inset-0 bg-[var(--mat-sys-outline-variant)] opacity-30 origin-right transition-transform duration-1000 ease-linear"
                           [style.transform]="'scaleX(' + ((group | passCountdown:cull.passingGroups()) / cull.passCountdownSeconds) + ')'"></div>
                    </div>
                  } @else {
                    <!-- Geometry cannot recover intent, so a residual error rate
                         is inherent and this is where it is corrected. Only on
                         panorama sets: a bracket is identified from EXIF, not
                         from a measurement that can read a subject-tracking pan
                         as a sweep. -->
                    @if (auth.isEdition() && (group.sequence_kind === 'panorama' || group.sequence_kind === 'hdr_panorama')) {
                      <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="correctMenu"
                              [matTooltip]="I18N.culling.panorama.correct_tooltip | translate"
                              [attr.aria-label]="I18N.culling.panorama.correct | translate">
                        <mat-icon>edit_note</mat-icon>
                      </button>
                      <mat-menu #correctMenu="matMenu">
                        <button mat-menu-item (click)="correctSequence(group)">
                          <mat-icon>wrong_location</mat-icon>{{ I18N.culling.panorama.not_a_panorama | translate }}
                        </button>
                        @if (group.sequence_kind !== 'panorama') {
                          <button mat-menu-item (click)="correctSequence(group, 'panorama')">
                            <mat-icon>{{ 'panorama' | cullGroupIcon }}</mat-icon>{{ I18N.culling.panorama.relabel_plain | translate }}
                          </button>
                        }
                        @if (group.sequence_kind !== 'hdr_panorama') {
                          <button mat-menu-item (click)="correctSequence(group, 'hdr_panorama')">
                            <mat-icon>{{ 'hdr_panorama' | cullGroupIcon }}</mat-icon>{{ I18N.culling.panorama.relabel_hdr | translate }}
                          </button>
                        }
                        @if (group | groupOverride) {
                          <button mat-menu-item (click)="clearCorrection(group)">
                            <mat-icon>undo</mat-icon>{{ I18N.culling.panorama.clear_correction | translate }}
                          </button>
                        }
                      </mat-menu>
                    }
                    <!-- A plain burst group has no set of its own to relabel or
                         suppress -- the only correction that applies to it is
                         naming a missed bracket, so this trigger offers just
                         that one action rather than reusing the panorama
                         menu's shape. -->
                    @if (auth.isEdition() && (group | canMarkBracket)) {
                      <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="bracketMenu"
                              [matTooltip]="I18N.culling.bracket.correct_tooltip | translate"
                              [attr.aria-label]="I18N.culling.panorama.correct | translate">
                        <mat-icon>edit_note</mat-icon>
                      </button>
                      <mat-menu #bracketMenu="matMenu">
                        <button mat-menu-item (click)="correctSequence(group, 'bracket')">
                          <mat-icon>{{ 'bracket' | cullGroupIcon }}</mat-icon>{{ I18N.culling.bracket.mark_action | translate }}
                        </button>
                      </mat-menu>
                    }
                    <!-- A bracket-kind group's own membership was named by this
                         correction (detected or forced alike) -- offer to drop
                         it back to the detector, mirroring the panorama menu's
                         own "Clear correction" entry. -->
                    @if (auth.isEdition() && group.sequence_kind === 'bracket' && (group | groupOverride)) {
                      <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="bracketClearMenu"
                              [matTooltip]="I18N.culling.panorama.correct | translate"
                              [attr.aria-label]="I18N.culling.panorama.correct | translate">
                        <mat-icon>edit_note</mat-icon>
                      </button>
                      <mat-menu #bracketClearMenu="matMenu">
                        <button mat-menu-item (click)="clearCorrection(group)">
                          <mat-icon>undo</mat-icon>{{ I18N.culling.panorama.clear_correction | translate }}
                        </button>
                      </mat-menu>
                    }
                    <button data-culling-open class="${TOUCH_ICON_BUTTON}" mat-icon-button (click)="openLightbox(group, 0)"
                            [matTooltip]="I18N.culling.darkroom_tooltip | translate"
                            [attr.aria-label]="I18N.culling.darkroom | translate">
                      <mat-icon>fullscreen</mat-icon>
                    </button>
                    <button class="${TOUCH_ICON_BUTTON}" mat-icon-button (click)="cull.skipGroup(group)" [disabled]="cull.replanning()"
                            [matTooltip]="I18N.culling.skip_tooltip | translate"
                            [attr.aria-label]="I18N.culling.skip | translate">
                      <mat-icon>skip_next</mat-icon>
                    </button>
                    <button class="${TOUCH_ICON_BUTTON}" mat-icon-button (click)="rejectEntireGroup(group)" [disabled]="cull.replanning() || cull.confirming()"
                            [matTooltip]="I18N.culling.workspace.reject_all | translate" [attr.aria-label]="I18N.culling.workspace.reject_all | translate"><mat-icon>remove_done</mat-icon></button>
                    <button data-culling-confirm class="${TOUCH_ICON_BUTTON}" mat-icon-button (click)="confirmGroupFromRow(group, $event)" [disabled]="cull.confirming() || cull.replanning() || !(cull.selectionsMap().get(groupKey)?.size)"
                            [attr.aria-describedby]="cull.selectionsMap().get(groupKey)?.size ? null : 'culling-keeper-required-' + i"
                            [matTooltip]="(cull.selectionsMap().get(groupKey)?.size ? I18N.culling.confirm_tooltip : I18N.culling.keep_required) | translate"
                            [attr.aria-label]="I18N.culling.confirm | translate">
                      <mat-icon>check_circle</mat-icon>
                    </button>
                  }
                </div>
                }
                @if (!stacksMode() && !(group | isPassing:cull.passingGroups()) && !(cull.selectionsMap().get(groupKey)?.size)) {
                  <p [id]="'culling-keeper-required-' + i" class="m-0 basis-full text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.culling.keep_required | translate }}</p>
                }
              </div>
            </div>
          }

          <!-- Infinite scroll sentinel -->
          @if (cull.hasMore()) {
            <div appInfiniteScroll scrollRoot="[data-culling-scroll]" (scrollReached)="onScrollReached()" class="flex justify-center py-6">
              @if (cull.loadingMore()) {
                <mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" />
              }
            </div>
          }
        </div>
      }
      </div>
    </div>

    <!-- Lightbox overlay -->
    @if (lightboxGroup(); as lbGroup) {
      @let lbKey = lbGroup | cullGroupKey;
      <!-- cdkTrapFocus without auto-capture: the effect below focuses the container
           itself, so Space/arrows reach the darkroom shortcuts instead of whichever
           toolbar button auto-capture would have landed on. -->
      <div #lightboxDialog class="fixed inset-0 z-[100] bg-[var(--facet-image-canvas)] flex flex-col"
           role="dialog"
           [attr.aria-label]="I18N.culling.darkroom | translate"
           aria-modal="true"
           data-undo-surface
           tabindex="-1"
           cdkTrapFocus
           (click)="closeLightbox()"
           (keydown)="onDarkroomKeydown($event)">
        <!-- Escape reaches this binding only from the container itself: every
             inner region shields the page from the darkroom's keys, so each one
             acts on Escape through onDarkroomKeydown() instead. -->
        <!-- Header. Opaque, not a tint: at bg-black/70 the gallery toolbar behind
             it stayed legible through the darkroom's own controls. -->
        <div data-darkroom-header class="flex min-w-0 shrink-0 flex-wrap items-center gap-1 border-b border-[var(--facet-image-rule)] px-2 py-1 text-[var(--facet-image-ink)] text-sm bg-[var(--facet-image-chrome)]">
          <div class="opacity-80 shrink-0 tabular-nums text-xs">
            {{ effectiveLightboxIndex() + 1 }} / {{ lbGroup.photos.length }}
          </div>
          @if (legendVisible() && !cleanComparison()) {
            <div class="order-last flex w-full max-h-24 flex-wrap items-center gap-x-4 gap-y-1.5 overflow-y-auto py-2 text-sm">
              @for (row of darkroomShortcuts(); track row.labelKey) {
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
          }
          <div [class.hidden]="cleanComparison()" class="flex min-w-0 flex-1 flex-wrap items-center gap-1 [&>button]:shrink-0" role="presentation"
               (click)="$event.stopPropagation()" (keydown)="onDarkroomKeydown($event)">
            <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [class.!text-white]="compareMode() !== 'single'"
                    [class.!text-[var(--mat-sys-primary)]]="compareMode() === 'single'"
                    [matTooltip]="I18N.culling.compare.single | translate"
                    [attr.aria-label]="I18N.culling.compare.single | translate"
                    [attr.aria-pressed]="compareMode() === 'single'"
                    (click)="setCompareMode('single')"><mat-icon>crop_original</mat-icon></button>
            <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [class.!text-white]="compareMode() !== '2up'"
                    [class.!text-[var(--mat-sys-primary)]]="compareMode() === '2up'"
                    [matTooltip]="I18N.culling.compare['2up'] | translate"
                    [attr.aria-label]="I18N.culling.compare['2up'] | translate"
                    [attr.aria-pressed]="compareMode() === '2up'"
                    (click)="setCompareMode('2up')"><mat-icon>splitscreen</mat-icon></button>
            <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [class.!text-white]="compareMode() !== '4up'"
                    [class.!text-[var(--mat-sys-primary)]]="compareMode() === '4up'"
                    [matTooltip]="I18N.culling.compare['4up'] | translate"
                    [attr.aria-label]="I18N.culling.compare['4up'] | translate"
                    [attr.aria-pressed]="compareMode() === '4up'"
                    (click)="setCompareMode('4up')"><mat-icon>grid_view</mat-icon></button>
            <details #darkroomTools class="relative shrink-0" data-darkroom-tools
                     (keydown.escape)="onRenditionHelpEscape($event, darkroomTools, darkroomToolsSummary)">
              <summary #darkroomToolsSummary class="flex h-11 min-w-11 cursor-pointer list-none items-center justify-center gap-2 rounded px-2 hover:bg-white/10"
                       (keydown.enter)="$event.stopPropagation()" (keydown.space)="$event.stopPropagation()"
                       [attr.aria-label]="I18N.gallery.compare.inspection.title | translate">
                <mat-icon aria-hidden="true">tune</mat-icon><span class="hidden sm:inline">{{ I18N.gallery.compare.inspection.title | translate }}</span>
              </summary>
              <div class="fixed top-14 left-2 right-2 z-[120] flex max-h-[70dvh] flex-wrap items-center gap-2 overflow-y-auto rounded border border-[var(--facet-image-rule)] bg-[var(--facet-image-chrome)] p-3 text-[var(--facet-image-ink)] sm:left-auto sm:right-28 sm:max-w-lg">
                <button class="${TOUCH_TEXT_BUTTON}" mat-button [attr.aria-pressed]="filmstripVisible()" (click)="toggleFilmstrip()">{{ I18N.culling.workspace.filmstrip | translate }}</button>
                <button class="${TOUCH_TEXT_BUTTON}" mat-button [attr.aria-pressed]="inspectionStripsVisible()" (click)="toggleInspectionStrips()">{{ I18N.culling.workspace.closeups | translate }}</button>
                <button mat-button class="${TOUCH_TEXT_BUTTON} sm:!hidden" (click)="toggleFullscreen()"><mat-icon>fullscreen</mat-icon>{{ I18N.slideshow.fullscreen | translate }}</button>
                <button class="${TOUCH_TEXT_BUTTON}" mat-button data-darkroom-link [attr.aria-pressed]="darkroomLinked()" (click)="toggleDarkroomLink()"><mat-icon>{{ darkroomLinked() ? 'link' : 'link_off' }}</mat-icon>{{ I18N.culling.workspace.link | translate }}</button>
                @if (!stacksMode()) {
                  <button class="${TOUCH_TEXT_BUTTON}" mat-button data-reject-entire-group (click)="rejectEntireGroup(lbGroup)" [disabled]="cull.replanning() || cull.confirming()">{{ I18N.culling.workspace.reject_all | translate }}</button>
                }
                <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [class.!text-white]="!legendVisible()"
                        [class.!text-[var(--mat-sys-primary)]]="legendVisible()"
                        [attr.aria-pressed]="legendVisible()"
                        [matTooltip]="I18N.culling.legend.tooltip | translate"
                        [attr.aria-label]="I18N.culling.legend.label | translate"
                        (click)="toggleLegend()"><mat-icon>keyboard</mat-icon></button>
            <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [class.!text-white]="!peakingActive()"
                    [class.!text-[var(--mat-sys-primary)]]="peakingActive()"
                    [attr.aria-pressed]="peakingActive()"
                    [matTooltip]="I18N.culling.peaking.tooltip | translate"
                    [attr.aria-label]="I18N.culling.peaking.label | translate"
                    aria-describedby="darkroom-peaking-help"
                    (click)="togglePeaking()"><mat-icon>filter_center_focus</mat-icon></button>
            <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [class.!text-white]="gridMode() === ''"
                    [class.!text-[var(--mat-sys-primary)]]="gridMode() !== ''"
                    [attr.aria-pressed]="gridMode() !== ''"
                    [matTooltip]="I18N.culling.grid.tooltip | translate"
                    [attr.aria-label]="gridModeLabel() | translate"
                    (click)="cycleGrid()"><mat-icon>grid_3x3</mat-icon></button>
            <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [class.!text-white]="!darkroomLoupeActive()"
                    [class.!text-[var(--mat-sys-primary)]]="darkroomLoupeActive()"
                    [attr.aria-pressed]="darkroomLoupeActive()"
                    [matTooltip]="I18N.culling.darkroom_loupe_hint | translate"
                    [attr.aria-label]="I18N.culling.darkroom_loupe | translate"
                    (click)="toggleDarkroomLoupe()">
              <mat-icon>{{ darkroomLoupeActive() ? 'zoom_in' : 'search' }}</mat-icon>
            </button>
            <details #renditionHelp data-rendition-help class="shrink-0" (keydown)="$event.key !== 'Escape' && $event.stopPropagation()" (keydown.escape)="onRenditionHelpEscape($event, renditionHelp, renditionHelpSummary)">
              <summary #renditionHelpSummary class="flex h-10 w-10 cursor-pointer items-center justify-center rounded-full hover:bg-white/15" [attr.aria-label]="I18N.gallery.compare.rendition.sources | translate"><mat-icon aria-hidden="true">info</mat-icon></summary>
              <div class="fixed inset-x-2 top-14 z-[120] flex max-h-40 gap-2 overflow-y-auto rounded border border-white/30 bg-neutral-900 p-3 text-xs text-white">
                <div class="min-w-0 flex-1 space-y-2">
                  <p class="m-0">{{ I18N.photo_detail.rendition.note | translate }}</p>
                  <p id="darkroom-peaking-help" class="m-0">{{ I18N.culling.peaking.help | translate }}</p>
                </div>
                <button type="button" data-rendition-help-close class="min-h-11 min-w-11 self-start" [attr.aria-label]="I18N.dialog.close | translate"
                        (click)="renditionHelp.open = false; renditionHelpSummary.focus()"><mat-icon>close</mat-icon></button>
              </div>
            </details>
            @if (auth.isEdition() && (stacksMode() || (lbGroup | canStackGroup))) {
              <button mat-icon-button class="${TOUCH_ICON_BUTTON} !text-white" aria-keyshortcuts="S" [disabled]="stacksMode() && (cull.stackBusy() || cull.stackDrafts()[lbKey].paths.length < 2)"
                      [matTooltip]="I18N.culling.stack_group | translate"
                      [attr.aria-label]="I18N.culling.stack_group | translate"
                      (click)="stackGroup(lbGroup)"><mat-icon>layers</mat-icon></button>
            }
            @if (stacksMode()) {
              <button mat-icon-button data-stack-reject class="${TOUCH_ICON_BUTTON} !text-white" aria-keyshortcuts="R" [disabled]="cull.stackBusy() || !!cull.stackExcluded()[lbGroup.photos[effectiveLightboxIndex()]?.path ?? '']"
                      [matTooltip]="I18N.stacks.reject_focused | translate" [attr.aria-label]="I18N.stacks.reject_focused | translate" (click)="rejectStackPhoto(lbGroup)"><mat-icon aria-hidden="true">block</mat-icon></button>
              <button mat-button class="${TOUCH_TEXT_BUTTON} !text-white" [disabled]="cull.stackBusy()" (click)="editSuggestion(lbGroup)">{{ I18N.stacks.suggestion_edit_members | translate }}</button>
              <button mat-button class="${TOUCH_TEXT_BUTTON} !text-white" [disabled]="cull.stackBusy()" (click)="skipStackSuggestion(lbGroup)">{{ I18N.stacks.suggestion_skip | translate }}</button>
            }
            @if (!stacksMode() && cullStyleCapable() && compareMode() === 'single') {
              <button class="${TOUCH_ICON_BUTTON}" mat-icon-button [matMenuTriggerFor]="cullStyleMenu"
                      [class.!text-white]="renditions.activeStyle() === ''"
                      [class.!text-[var(--mat-sys-primary)]]="renditions.activeStyle() !== ''"
                      [matTooltip]="I18N.culling.cull_style.tooltip | translate"
                      [attr.aria-label]="I18N.culling.cull_style.tooltip | translate">
                <mat-icon>palette</mat-icon>
              </button>
              <mat-menu #cullStyleMenu="matMenu">
                <button mat-menu-item (click)="renditions.selectCullStyle('')">
                  <span [class.font-bold]="renditions.activeStyle() === ''">{{ I18N.photo_detail.rendition.base_render | translate }}</span>
                </button>
                @for (s of cullStyles(); track s.name) {
                  <button mat-menu-item (click)="renditions.selectCullStyle(s.name)">
                    <span [class.font-bold]="renditions.activeStyle() === s.name">{{ s.label_key | translate }}</span>
                  </button>
                }
              </mat-menu>
            }
              </div>
            </details>
          </div>
          <button mat-icon-button data-clean-comparison [attr.aria-pressed]="cleanComparison()"
                  [matTooltip]="(cleanComparison() ? I18N.culling.workspace.restore : I18N.culling.workspace.clean) | translate" [attr.aria-label]="(cleanComparison() ? I18N.culling.workspace.restore : I18N.culling.workspace.clean) | translate"
                  (click)="toggleCleanComparison(); $event.stopPropagation()" class="${TOUCH_ICON_BUTTON} !text-white shrink-0 ml-auto"><mat-icon>{{ cleanComparison() ? 'visibility' : 'hide_source' }}</mat-icon></button>
          <button mat-icon-button
                  [matTooltip]="I18N.slideshow.fullscreen | translate"
                  [attr.aria-label]="I18N.slideshow.fullscreen | translate"
                  (click)="toggleFullscreen(); $event.stopPropagation()" class="${TOUCH_ICON_BUTTON} !text-white shrink-0 !hidden sm:!inline-flex">
            <mat-icon>{{ isFullscreen() ? 'fullscreen_exit' : 'fullscreen' }}</mat-icon>
          </button>
          <button mat-icon-button data-darkroom-close
                  [attr.aria-label]="I18N.dialog.cancel | translate"
                  (click)="closeLightbox(); $event.stopPropagation()" class="${TOUCH_ICON_BUTTON} !text-white shrink-0">
            <mat-icon>close</mat-icon>
          </button>
        </div>
        <!-- Per-pane overlays: the peaking edge map rides the image's own
             transform, the composition grid stays fixed to the frame box. -->
        <ng-template #frameOverlays let-path="path">
          @if (path | peakingOverlay:renditions.peakingOverlays(); as overlay) {
            <img [src]="overlay" alt="" aria-hidden="true"
                 class="absolute inset-0 w-full h-full object-contain origin-center
                        pointer-events-none opacity-60 will-change-transform"
                 [style.transform]="frameTransforms().get(path)" />
          }
          @if (gridMode(); as grid) {
            @if (path | frameViewBox:renditions.frameSizes(); as viewBox) {
              <svg class="absolute inset-0 w-full h-full pointer-events-none"
                   [attr.viewBox]="viewBox" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
                @for (line of grid | gridLines; track line) {
                  <line [attr.x1]="line" y1="0%" [attr.x2]="line" y2="100%"
                        stroke="white" stroke-opacity="0.45" stroke-width="1"
                        vector-effect="non-scaling-stroke" />
                  <line x1="0%" [attr.y1]="line" x2="100%" [attr.y2]="line"
                        stroke="white" stroke-opacity="0.45" stroke-width="1"
                        vector-effect="non-scaling-stroke" />
                }
              </svg>
            }
          }
        </ng-template>
        <!-- Kept / rejected, in the tile grid's own idiom: a solid circle with a
             white glyph, which survives any frame under it. The bare tinted icon
             this replaced was unreadable over a busy photo. -->
        <ng-template #frameState let-kept="kept" let-decided="decided">
          @if (!stacksMode()) {
            @if (kept) {
              <div class="absolute top-2 right-2 w-7 h-7 rounded-full bg-green-600 inline-flex items-center justify-center shadow"
                   [attr.aria-label]="I18N.culling.lightbox.kept | translate">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-white">check</mat-icon>
              </div>
            } @else if (decided) {
              <div class="absolute top-2 right-2 w-7 h-7 rounded-full bg-red-600 inline-flex items-center justify-center shadow"
                   [attr.aria-label]="I18N.culling.lightbox.rejected | translate">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-white">close</mat-icon>
              </div>
            }
          }
        </ng-template>
        <!-- Image -->
        @if (lbGroup.photos[effectiveLightboxIndex()]; as lbPhoto) {
          <div class="shrink-0 px-4 text-white bg-neutral-950" role="presentation"
               (click)="$event.stopPropagation()" (keydown)="$event.stopPropagation()" (keydown.escape)="closeLightbox()">
            <app-photo-assessment [photo]="lbPhoto" [groupPick]="lbPhoto.path === lbGroup.best_path" />
          </div>
          @if (compareMode() === 'single') {
            <!-- overflow-hidden: the peaking overlay rides the zoom transform as a
                 sibling of the zoom pane, so only this box keeps it off the chrome. -->
            <div class="relative flex-1 min-h-0 overflow-hidden"
                 role="presentation"
                 #swipe="appSwipeDecision"
                 [appSwipeDecision]="swipeEnabled()"
                 (swipeKeep)="onSwipeDecision(lbGroup, true)"
                 (swipeReject)="onSwipeDecision(lbGroup, false)"
                 (click)="$event.stopPropagation()"
                 (keydown)="onDarkroomKeydown($event)">
              <app-synced-zoom #singlePane class="w-full h-full"
                               [src]="(renditions.activeStyle() && !renditions.previewLoading()) ? renditions.developedPreviewUrl() : (lbPhoto.path | thumbnailUrl:darkroomThumbSize:lbPhoto.preview_revision)"
                               [placeholderSrc]="renditions.activeStyle() ? null : (lbPhoto.path | thumbnailUrl:storedEdge:lbPhoto.preview_revision)"
                               [frameKey]="lbPhoto.path"
                               [loadedSources]="renditions.loadedRenders"
                               (sharpLoaded)="renditions.onSharpLoaded($event)"
                               (sharpFailed)="renditions.onSharpFailed($event)"
                               (sharpPending)="renditions.onSharpPending($event)"
                               [fullResSrc]="renditions.activeStyle() ? null : (lbPhoto.path | imageUrl:false:lbPhoto.preview_revision)"
                               [zoom]="zoom()"
                               [focusPoint]="(lbPhoto.path | keySubjectForPath:keySubjectMap())?.center ?? null"
                               (zoomChange)="onDarkroomZoom($event)"
                               [loupeSrc]="renditions.activeStyle() && !renditions.previewLoading() ? renditions.developedPreviewUrl() : (lbPhoto.path | imageUrl:false:lbPhoto.preview_revision)"
                               [loupeActive]="darkroomLoupeEffective()"
                               [loupeZoom]="darkroomLoupeZoom()"
                               [alt]="lbPhoto.filename"
                               (renditionChange)="renditions.onDisplayedRendition($event, lbPhoto.path, renditions.activeStyle())" />
              <div class="absolute inset-x-2 bottom-2 z-10 rounded bg-black/80 px-2 py-1 text-white" role="presentation" (click)="$event.stopPropagation()" (pointerdown)="$event.stopPropagation()" (keydown)="onDarkroomKeydown($event)">
                <app-rendition-readout [state]="renditions.displayedRenditions().get(lbPhoto.path) ?? renditions.RENDITION_PENDING" [edited]="!!renditions.activeStyle() && !renditions.previewLoading()" [pending]="renditions.previewLoading() || renditions.pendingRenderPaths().has(lbPhoto.path)" [attemptFailed]="renditions.failedRenderPaths().has(lbPhoto.path) || renditions.developedFailure()?.path === lbPhoto.path" [failureLabel]="renditions.developedFailure()?.path === lbPhoto.path ? I18N.photo_detail.rendition.edited_failed : I18N.gallery.compare.rendition.fallback" (retry)="renditions.retryDarkroomPane(singlePane)" [scale]="zoom().scale" (zoomStep)="stepDarkroomZoom($event)" (fit)="fitDarkroom()" />
              </div>
              <ng-container [ngTemplateOutlet]="frameOverlays"
                            [ngTemplateOutletContext]="{ path: lbPhoto.path }" />
              <!-- Inset to the rendered photo, not to the pane: object-contain
                   letterboxes, so the pane's corner can be far off the image. -->
              <div class="absolute pointer-events-none"
                   [style.top.px]="singlePane.fitInsetY()" [style.bottom.px]="singlePane.fitInsetY()"
                   [style.left.px]="singlePane.fitInsetX()" [style.right.px]="singlePane.fitInsetX()">
                <ng-container [ngTemplateOutlet]="frameState"
                              [ngTemplateOutletContext]="{
                                kept: (lbPhoto.path | isKept:cull.selectionsMap():lbKey),
                                decided: (lbPhoto.path | isDecided:cull.selectionsMap():lbKey:cull.touchedGroups().has(lbKey)) }" />
              </div>
              @if (renditions.previewLoading()) {
                <div class="absolute inset-0 flex items-center justify-center bg-black/40 pointer-events-none"
                     [attr.aria-label]="I18N.culling.cull_style.loading | translate">
                  <mat-spinner diameter="40" [attr.aria-label]="I18N.ui.labels.loading | translate" />
                </div>
              }
              <!-- Swipe feedback. Rendered inside the element the gesture moves,
                   so the tint and the verdict travel with the frame; aria-hidden
                   because the footer status below already says what was decided. -->
              @if (swipeEnabled()) {
                <div class="absolute inset-0 pointer-events-none bg-green-500/30"
                     aria-hidden="true" [style.opacity]="swipe.keepProgress()"></div>
                <div class="absolute inset-0 pointer-events-none bg-red-600/30"
                     aria-hidden="true" [style.opacity]="swipe.rejectProgress()"></div>
                <div class="absolute inset-0 flex items-center justify-between px-6 pointer-events-none"
                     aria-hidden="true">
                  <span class="inline-flex items-center gap-1.5 rounded-full bg-red-600 px-4 py-2
                               text-white text-sm font-bold uppercase tracking-wide"
                        [style.opacity]="swipe.rejectProgress()">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">close</mat-icon>
                    {{ I18N.culling.swipe.reject | translate }}
                  </span>
                  <span class="inline-flex items-center gap-1.5 rounded-full bg-green-600 px-4 py-2
                               text-white text-sm font-bold uppercase tracking-wide"
                        [style.opacity]="swipe.keepProgress()">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">check</mat-icon>
                    {{ I18N.culling.swipe.keep | translate }}
                  </span>
                </div>
              }
            </div>
          } @else {
            <div class="flex-1 min-h-0 grid grid-cols-1 sm:grid-cols-2 gap-1 overflow-hidden p-1"
                 [class.!grid-cols-2]="compareMode() === '4up'"
                 [class.max-sm:grid-rows-2]="compareMode() === '2up'"
                 [class.grid-rows-2]="compareMode() === '4up'"
                 role="presentation"
                 (click)="$event.stopPropagation()"
                 (keydown)="onDarkroomKeydown($event)">
              @for (photo of compareFrames(); track photo.path; let paneIndex = $index) {
                <div data-darkroom-pane [attr.data-path]="photo.path" class="@container/cullpane relative flex w-full h-full min-h-0 flex-col rounded overflow-hidden">
                  <div class="flex shrink-0 min-w-0 items-center bg-[var(--facet-image-chrome)] text-[var(--facet-image-ink)]">
                    <button type="button" data-comparison-slot class="flex min-h-11 min-w-0 flex-1 items-center gap-1 px-1 text-left text-xs focus-visible:outline-2 @[400px]/cullpane:gap-2 @[400px]/cullpane:px-2"
                            [class.bg-[var(--mat-sys-secondary-container)]]="comparisonSlot() === paneIndex" [class.text-[var(--mat-sys-on-secondary-container)]]="comparisonSlot() === paneIndex"
                            [attr.aria-pressed]="comparisonSlot() === paneIndex" [attr.aria-label]="I18N.culling.comparison.choose_pane | translate:{ pane: comparisonSlotLabels[paneIndex], name: photo.filename }" [title]="photo.filename" (click)="selectComparisonSlot(paneIndex)">
                      <span class="font-semibold shrink-0">{{ comparisonSlotLabels[paneIndex] }}</span><span data-culling-pane-name class="min-w-0 flex-1 truncate @max-[200px]/cullpane:sr-only" [title]="photo.filename">{{ photo.filename | filename:28 }}</span>
                      <mat-icon aria-hidden="true" class="@max-[400px]/cullpane:!hidden ml-auto !text-base !w-4 !h-4 shrink-0">{{ comparisonSlot() === paneIndex ? 'check_circle' : 'radio_button_unchecked' }}</mat-icon>
                    </button>
                    @if (!stacksMode()) {
                      <div class="flex shrink-0 min-w-0 items-center">
                        <span class="sr-only @[400px]/cullpane:not-sr-only @[400px]/cullpane:px-2 @[400px]/cullpane:text-xs">@if ((photo.path | isKept:cull.selectionsMap():lbKey) || (photo.path | isDecided:cull.selectionsMap():lbKey:cull.touchedGroups().has(lbKey))) { {{ ((photo.path | isKept:cull.selectionsMap():lbKey) ? I18N.culling.lightbox.kept : I18N.culling.lightbox.rejected) | translate }} }</span>
                        <button type="button" class="min-w-11 min-h-11 rounded inline-flex items-center justify-center hover:bg-white/10 disabled:opacity-40"
                                [class.bg-emerald-800]="photo.path | isKept:cull.selectionsMap():lbKey"
                                [class.text-white]="photo.path | isKept:cull.selectionsMap():lbKey"
                                [attr.aria-pressed]="photo.path | isKept:cull.selectionsMap():lbKey" [disabled]="lightboxDecisionLocked()"
                                [matTooltip]="I18N.culling.lightbox.keep | translate"
                                [attr.aria-label]="photo.filename + ', ' + (I18N.culling.lightbox.keep | translate)"
                                (click)="cull.setPhotoKept(lbGroup, photo.path, true)">
                          <mat-icon class="!text-base !w-4 !h-4 !leading-4">check</mat-icon>
                        </button>
                        <button type="button" class="min-w-11 min-h-11 rounded inline-flex items-center justify-center hover:bg-white/10 disabled:opacity-40"
                                [class.bg-red-700]="(photo.path | isDecided:cull.selectionsMap():lbKey:cull.touchedGroups().has(lbKey)) && !(photo.path | isKept:cull.selectionsMap():lbKey)"
                                [class.text-white]="(photo.path | isDecided:cull.selectionsMap():lbKey:cull.touchedGroups().has(lbKey)) && !(photo.path | isKept:cull.selectionsMap():lbKey)"
                                [attr.aria-pressed]="(photo.path | isDecided:cull.selectionsMap():lbKey:cull.touchedGroups().has(lbKey)) && !(photo.path | isKept:cull.selectionsMap():lbKey)" [disabled]="lightboxDecisionLocked()"
                                [matTooltip]="I18N.culling.lightbox.reject | translate"
                                [attr.aria-label]="photo.filename + ', ' + (I18N.culling.lightbox.reject | translate)"
                                (click)="cull.setPhotoKept(lbGroup, photo.path, false)">
                          <mat-icon class="!text-base !w-4 !h-4 !leading-4">close</mat-icon>
                        </button>
                      </div>
                    }
                  </div>
                  <div class="relative min-h-0 flex-1">
                  <app-synced-zoom #pane class="w-full h-full min-h-0"
                                   [src]="photo.path | thumbnailUrl:darkroomThumbSize:photo.preview_revision"
                                   [placeholderSrc]="photo.path | thumbnailUrl:storedEdge:photo.preview_revision"
                                   [frameKey]="photo.path"
                                   [loadedSources]="renditions.loadedRenders"
                                   (sharpLoaded)="renditions.onSharpLoaded($event, photo.path)"
                                   (sharpFailed)="renditions.onSharpFailed($event, photo.path)"
                                   (sharpPending)="renditions.onSharpPending($event, photo.path)"
                                   [fullResSrc]="photo.path | imageUrl:false:photo.preview_revision"
                                   [zoom]="paneFrames().get(photo.path) ?? FIT_ZOOM"
                                   [focusPoint]="(photo.path | keySubjectForPath:keySubjectMap())?.center ?? null"
                                   (zoomChange)="onDarkroomZoom($event, photo.path)"
                                   [loupeSrc]="photo.path | imageUrl:false:photo.preview_revision"
                                   [loupeActive]="darkroomLoupeActive() && (paneFrames().get(photo.path)?.scale ?? 1) <= 1"
                                   [loupeZoom]="darkroomLoupeZoom()"
                                   [alt]="photo.filename"
                                   (renditionChange)="renditions.onDisplayedRendition($event, photo.path, '')" />
                  <ng-container [ngTemplateOutlet]="frameOverlays"
                                [ngTemplateOutletContext]="{ path: photo.path }" />
                  <!-- Every per-frame mark traces the rendered photo, not the
                       cell: a letterboxed pane put them up to 90px off the image,
                       where they read as chrome about the pair rather than about
                       this frame. The focus ring follows for the same reason. -->
                  <div class="absolute pointer-events-none"
                       [style.top.px]="pane.fitInsetY()" [style.bottom.px]="pane.fitInsetY()"
                       [style.left.px]="pane.fitInsetX()" [style.right.px]="pane.fitInsetX()"
                       [class.ring-2]="photo.path === lbPhoto.path"
                       [class.ring-inset]="photo.path === lbPhoto.path"
                       [class.ring-amber-400]="photo.path === lbPhoto.path">
                  </div>
                  </div>
                  <div class="shrink-0 bg-neutral-950 p-1 text-white" role="presentation" (click)="$event.stopPropagation()" (pointerdown)="$event.stopPropagation()" (keydown)="onDarkroomKeydown($event)">
                    @if (!cleanComparison()) {
                    <app-rendition-readout [state]="renditions.displayedRenditions().get(photo.path) ?? renditions.RENDITION_PENDING" [pending]="renditions.pendingRenderPaths().has(photo.path)" [attemptFailed]="renditions.failedRenderPaths().has(photo.path)" [failureLabel]="I18N.gallery.compare.rendition.fallback" (retry)="renditions.retryDarkroomPane(pane)" [scale]="paneFrames().get(photo.path)?.scale ?? 1" (zoomStep)="stepDarkroomZoom($event, photo.path)" (fit)="fitDarkroom(photo.path)" />
                    }
                  </div>
                </div>
              }
            </div>
          }
          @if (stacksMode()) {
            @if (cull.stackDrafts()[lbKey].excludedCount; as count) {
              <p data-stack-excluded role="status" class="shrink-0 text-white text-sm px-3 py-1">{{ I18N.stacks.reject_count | translate:{ count } }} @if (cull.stackDrafts()[lbKey].paths.length < 2) { {{ I18N.stacks.regroup_minimum | translate }} }</p>
            }
          }
          @if (compareMode() !== 'single' && filmstripVisible() && !cleanComparison()) {
            <p data-comparison-assignment class="m-0 shrink-0 px-3 pt-2 text-xs text-white/70" [class.max-sm:sr-only]="compareMode() === '4up'">{{ I18N.culling.comparison.assign_hint | translate:{ pane: comparisonSlotLabels[comparisonSlot()] } }}</p>
          }
            @if (filmstripVisible() && !cleanComparison()) {
            <div class="shrink-0 flex gap-2 overflow-x-auto border-t border-white/10 px-3 py-1" data-stack-filmstrip
                 role="presentation" (click)="$event.stopPropagation()" (keydown)="onDarkroomKeydown($event)">
              @for (photo of lbGroup.photos; track photo.path; let index = $index) {
                <button type="button" class="relative min-w-11 min-h-11 shrink-0 rounded border-2 border-transparent overflow-hidden cursor-pointer"
                        [class.!border-amber-400]="index === effectiveLightboxIndex()" [class.opacity-40]="cull.stackExcluded()[photo.path]"
                        [attr.aria-current]="index === effectiveLightboxIndex() ? 'true' : null"
                        [attr.aria-label]="compareMode() === 'single' ? photo.filename : (I18N.culling.comparison.assign_photo | translate:{ pane: comparisonSlotLabels[comparisonSlot()], name: photo.filename })" (click)="focusPhotoInLightbox(index)">
                  <img class="h-12 w-auto max-w-24 object-contain" [class.max-sm:!h-8]="compareMode() === '4up'" loading="lazy"
                       [src]="photo.path | thumbnailUrl:storedEdge:photo.preview_revision" [alt]="photo.filename" />
                  @if (compareMode() !== 'single') {
                    @for (frame of compareFrames(); track frame.path; let slot = $index) {
                      @if (frame.path === photo.path) {
                        <span data-filmstrip-pane-badge aria-hidden="true" class="absolute left-0 top-0 min-w-4 rounded-br bg-black/85 px-1 text-center text-xs font-bold leading-4 text-white">{{ comparisonSlotLabels[slot] }}</span>
                      }
                    }
                  }
                  @if (cull.stackExcluded()[photo.path]) { <span class="text-xs text-white block">{{ I18N.rating.rejected_badge | translate }}</span> }
                </button>
              }
            </div>
            }
          @if (!stacksMode() && !cleanComparison()) {
          <!-- Footer status -->
          <div class="shrink-0 flex flex-wrap items-center justify-center gap-2 px-3 py-2 text-center"
               role="presentation"
               (click)="$event.stopPropagation()"
               (keydown)="onDarkroomKeydown($event)">
            <span data-darkroom-filename class="min-w-0 basis-full break-all text-xs text-white/80" [class.max-sm:sr-only]="compareMode() === '4up'" [title]="lbPhoto.filename">{{ lbPhoto.filename | filename:54 }}</span>
            @if (compareMode() === 'single') {
              <div class="inline-flex items-center gap-1" role="group" [attr.aria-label]="I18N.gallery.sidebar.tabs.review | translate">
                <button mat-button data-darkroom-keep class="${TOUCH_TEXT_BUTTON} !min-h-11 !text-white" [class.!bg-[var(--facet-review-kept)]]="lbPhoto.path | isKept:cull.selectionsMap():lbKey" [attr.aria-pressed]="lbPhoto.path | isKept:cull.selectionsMap():lbKey" [disabled]="lightboxDecisionLocked()" (click)="cull.setPhotoKept(lbGroup, lbPhoto.path, true)"><mat-icon>check</mat-icon>{{ I18N.culling.lightbox.keep | translate }}</button>
                <button mat-button data-darkroom-reject class="${TOUCH_TEXT_BUTTON} !min-h-11 !text-white" [class.!bg-red-700]="(lbPhoto.path | isDecided:cull.selectionsMap():lbKey:cull.touchedGroups().has(lbKey)) && !(lbPhoto.path | isKept:cull.selectionsMap():lbKey)" [attr.aria-pressed]="(lbPhoto.path | isDecided:cull.selectionsMap():lbKey:cull.touchedGroups().has(lbKey)) && !(lbPhoto.path | isKept:cull.selectionsMap():lbKey)" [disabled]="lightboxDecisionLocked()" (click)="cull.setPhotoKept(lbGroup, lbPhoto.path, false)"><mat-icon>close</mat-icon>{{ I18N.culling.lightbox.reject | translate }}</button>
              </div>
            }
            <span role="status" class="sr-only">
            @if (lbPhoto.path | isKept:cull.selectionsMap():lbKey) {
              <span class="inline-flex items-center gap-1 text-green-400 text-sm">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">check</mat-icon>
                {{ I18N.culling.lightbox.kept | translate }}
              </span>
            } @else if (lbPhoto.path | isDecided:cull.selectionsMap():lbKey:cull.touchedGroups().has(lbKey)) {
              <span class="inline-flex items-center gap-1 text-red-400 text-sm">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">close</mat-icon>
                {{ I18N.culling.lightbox.rejected | translate }}
              </span>
            } @else {
              <span class="text-white/40 text-sm">{{ I18N.culling.lightbox.undecided | translate }}</span>
            }
            </span>
            @if (lbGroup | isPassing:cull.passingGroups()) {
              <span data-darkroom-pending role="status" class="text-xs text-white/80">{{ I18N.culling.confirmed_badge | translate }}</span>
              <button mat-stroked-button data-darkroom-cancel class="!min-h-11 !text-white !border-white/40" [matTooltip]="I18N.culling.cancel_restore | translate" (click)="cancelGroupPass(lbGroup, $event, true)">{{ I18N.culling.cancel_pass | translate }} ({{ lbGroup | passCountdown:cull.passingGroups() }}s)</button>
            }
            <button mat-flat-button data-darkroom-confirm class="!min-h-11 disabled:!text-white/60 disabled:!bg-white/10" [disabled]="lightboxDecisionLocked() || lightboxKeptCount() === 0" [attr.aria-describedby]="lightboxKeptCount() === 0 ? 'culling-keeper-required' : null" (click)="continueCullingGroup($event)"><mat-icon>check_circle</mat-icon>{{ I18N.culling.confirm | translate }}</button>
            @if (lightboxKeptCount() === 0) { <p id="culling-keeper-required" role="status" class="m-0 basis-full text-xs text-white/80">{{ I18N.culling.keep_required | translate }}</p> }
            @if (swipeEnabled() && !swipeHintDismissed()) {
              <div class="flex items-center justify-center gap-2 pt-2 text-white/60 text-xs">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4" aria-hidden="true">swipe</mat-icon>
                <span>{{ I18N.culling.swipe.hint | translate }}</span>
                <button mat-button class="${TOUCH_TEXT_BUTTON} !min-w-0 !px-2 !text-xs !text-white/80"
                        (click)="dismissSwipeHint()">
                  {{ I18N.culling.swipe.hint_dismiss | translate }}
                </button>
              </div>
            }
          </div>
          }
        }

        <!-- Face / expression close-up grid -->
        @if (!stacksMode() && inspectionStripsVisible() && !cleanComparison() && faceGridHasFaces()) {
          <div class="border-t border-white/10 px-4 py-3 overflow-x-auto"
               role="presentation"
               (click)="$event.stopPropagation()"
               (keydown)="onDarkroomKeydown($event)">
            <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2">
              <div class="text-white/50 text-xs">{{ I18N.culling.face_grid_title | translate }}</div>
              <div class="flex items-center gap-2"
                   [matTooltip]="'culling.face_eyes_min_tooltip' | translate">
                <span class="text-white/50 text-xs">{{ 'culling.face_eyes_min' | translate }}</span>
                <mat-slider class="!w-24 !min-w-0" [min]="0" [max]="10" [step]="1" [discrete]="true">
                  <input matSliderThumb [value]="faceEyesMin()" (valueChange)="onFaceEyesMinChange($event)"
                         (dragEnd)="releaseSliderFocus()"
                         [attr.aria-label]="'culling.face_eyes_min' | translate" />
                </mat-slider>
                <span class="text-white/70 text-xs font-medium w-4">{{ faceEyesMin() }}</span>
              </div>
              <div class="flex items-center gap-2"
                   [matTooltip]="'culling.face_smile_min_tooltip' | translate">
                <span class="text-white/50 text-xs">{{ 'culling.face_smile_min' | translate }}</span>
                <mat-slider class="!w-24 !min-w-0" [min]="0" [max]="10" [step]="1" [discrete]="true">
                  <input matSliderThumb [value]="faceSmileMin()" (valueChange)="onFaceSmileMinChange($event)"
                         (dragEnd)="releaseSliderFocus()"
                         [attr.aria-label]="'culling.face_smile_min' | translate" />
                </mat-slider>
                <span class="text-white/70 text-xs font-medium w-4">{{ faceSmileMin() }}</span>
              </div>
              <div class="flex items-center gap-2"
                   [matTooltip]="'culling.face_size_tooltip' | translate">
                <span class="text-white/50 text-xs">{{ 'culling.face_size' | translate }}</span>
                <mat-slider class="!w-24 !min-w-0" [min]="faceSizeMinPx" [max]="faceSizeMaxPx"
                            [step]="faceSizeStepPx" [discrete]="true">
                  <input matSliderThumb [value]="faceSize()" (valueChange)="onFaceSizeChange($event)"
                         (dragEnd)="releaseSliderFocus()"
                         [attr.aria-label]="'culling.face_size' | translate" />
                </mat-slider>
                <span class="text-white/70 text-xs font-medium w-8">{{ faceSize() }}</span>
              </div>
            </div>
            <div class="flex gap-3 items-start">
              @for (photo of lbGroup.photos; track photo.path; let pIdx = $index) {
                @if ((photo.path | facesForPath:faceMap()).length > 0) {
                  <!-- The face rings carry quality colours, so the current frame
                       is outlined around its whole column instead. -->
                  <div class="flex flex-col items-center gap-1 flex-shrink-0 rounded outline-offset-2"
                       [attr.data-face-frame]="pIdx"
                       [class.outline-2]="photo.path === lbGroup.photos[effectiveLightboxIndex()]?.path"
                       [class.outline-amber-400]="photo.path === lbGroup.photos[effectiveLightboxIndex()]?.path">
                    <div class="flex gap-1">
                      @for (face of photo.path | facesForPath:faceMap(); track face.id) {
                        <div class="relative">
                          <img [src]="face.id | faceThumbnailUrl"
                               class="rounded object-cover ring-2 ring-inset transition-opacity"
                               [style.width.px]="faceSize()" [style.height.px]="faceSize()"
                               [ngClass]="face | faceRingClass:faceThresholds()"
                               [class.opacity-40]="face | faceDimmed:faceEyesMin():faceSmileMin()"
                               [appLoupe]="face.id | faceThumbnailUrl"
                               [loupeActive]="darkroomLoupeActive()"
                               [loupeZoom]="darkroomLoupeZoom()"
                               loupeFit="cover"
                               [alt]="photo.filename" loading="lazy" />
                          @if (face.confidence !== null && face.confidence !== undefined) {
                            <div class="absolute top-0 right-0 bg-black/60 text-white/80 text-[9px] leading-none px-1 py-0.5 rounded-bl">
                              {{ face.confidence | number:'1.0-2' }}
                            </div>
                          }
                          <!-- Key person: top-left, because the bottom edge carries the
                               blink / expression bar and the frame number. Shown only
                               when the winning face has a name to put on it. -->
                          @if (photo.path | keySubjectForPath:keySubjectMap(); as keySubject) {
                            @if ((face | isKeyFace:keySubject) && keySubject.person_name; as keyPersonName) {
                              <!-- A button, not a bare div: the explanation lives only in
                                   matTooltip, which a keyboard or screen-reader user can only
                                   reach through a focusable host (same pattern as the "My
                                   Taste" badge in app.html). The sr-only span also folds that
                                   explanation in, so it reaches assistive tech regardless of
                                   focus/hover. -->
                              <button type="button"
                                      class="absolute top-0 left-0 max-w-full truncate rounded-br bg-amber-500/90 px-1 py-0.5 text-[9px] leading-none font-bold text-black"
                                      [matTooltip]="I18N.culling.key_person_tooltip | translate">
                                <span class="sr-only">{{ I18N.culling.key_person | translate }}: {{ I18N.culling.key_person_tooltip | translate }}</span>&ngsp;{{ keyPersonName }}
                              </button>
                            }
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
                      <span class="text-green-400 text-[10px] font-bold">{{ I18N.photo_detail.assessment.group_pick | translate }}</span>
                    } @else if (!stacksMode() && photo.cull_reason; as reason) {
                      <span class="text-white/60 text-[10px] truncate" [style.max-width.px]="faceSize()">{{ reason | cullReason }}</span>
                    }
                  </div>
                }
              }
            </div>
          </div>
        }

        <!-- Subject close-up grid (non-face groups with a saliency subject box) -->
        @if (!stacksMode() && inspectionStripsVisible() && !cleanComparison() && subjectStripVisible()) {
          <div class="border-t border-white/10 px-4 py-3 overflow-x-auto"
               role="presentation"
               (click)="$event.stopPropagation()"
               (keydown)="onDarkroomKeydown($event)">
            <div class="text-white/50 text-xs mb-2">{{ I18N.culling.subject_grid_title | translate }}</div>
            <div class="flex gap-3 items-start">
              @for (photo of lbGroup.photos; track photo.path; let pIdx = $index) {
                @if (photo.path | subjectForPath:subjectMap(); as subject) {
                  @if (subject.has_subject) {
                    <button type="button"
                            class="flex flex-col items-center gap-1 flex-shrink-0 cursor-zoom-in"
                            [matTooltip]="I18N.culling.subject_sharpness | translate"
                            (click)="focusPhotoInLightbox(pIdx)">
                      <div class="relative">
                        <img [src]="subject.crop"
                             class="w-24 h-24 rounded object-cover ring-2 ring-inset"
                             [ngClass]="subject | subjectRingClass"
                             [class.!ring-amber-400]="photo.path === lbGroup.photos[effectiveLightboxIndex()]?.path"
                             [alt]="photo.filename" loading="lazy" />
                        @if (subject.crop_sharpness_score !== null) {
                          <div class="absolute top-0 right-0 bg-black/60 text-white/80 text-[9px] leading-none px-1 py-0.5 rounded-bl">
                            {{ subject.crop_sharpness_score | number:'1.0-1' }}
                          </div>
                        }
                        <div class="absolute bottom-1 right-1 px-1 py-0.5 rounded bg-black/70 text-white text-[10px] leading-none">{{ pIdx + 1 }}</div>
                      </div>
                      @if (photo.path === lbGroup.best_path) {
                        <span class="text-green-400 text-[10px] font-bold">{{ I18N.photo_detail.assessment.group_pick | translate }}</span>
                      } @else if (!stacksMode() && photo.cull_reason; as reason) {
                        <span class="text-white/60 text-[10px] max-w-[96px] truncate">{{ reason | cullReason }}</span>
                      }
                    </button>
                  }
                }
              }
            </div>
          </div>
        }
      </div>
    }

    <!-- Auto-cull preview / confirm dialog -->
    @if (cull.autoCullPreview(); as ac) {
      <div class="fixed inset-0 z-[110] bg-black/50 flex items-center justify-center p-4"
           role="presentation"
           (click)="cull.cancelAutoCull()"
           (keydown.escape)="cull.cancelAutoCull()">
        <!-- Escape is handled here, not only on the backdrop: the blanket keydown
             shield below (which keeps the page's cull shortcuts from firing behind
             the modal) stops the event before any ancestor or document handler. -->
        <div #autoCullDialog class="rounded-xl bg-[var(--mat-sys-surface-container-high)] p-4 md:p-6 w-full max-w-2xl max-h-[90dvh] overflow-auto space-y-4"
             role="dialog"
             aria-modal="true"
             aria-labelledby="autoCullTitle"
             tabindex="-1"
             cdkTrapFocus
             [cdkTrapFocusAutoCapture]="true"
             (click)="$event.stopPropagation()"
             (keydown.escape)="cull.cancelAutoCull()"
             (keydown)="$event.stopPropagation()">
          <h2 id="autoCullTitle" class="text-lg font-semibold">{{ I18N.culling.auto_cull.title | translate }}</h2>
          <fieldset class="m-0 flex flex-wrap gap-x-5 gap-y-2 border-0 p-0" [disabled]="cull.autoCullBusy()">
            <legend class="mb-1 text-sm font-medium">{{ I18N.culling.auto_cull.policy_label | translate }}</legend>
            <label class="inline-flex min-h-11 items-center gap-2 text-sm"><input type="radio" name="autoCullPolicy" value="preserve" [checked]="cull.autoCullDecisionPolicy() === 'preserve'" (change)="cull.onAutoCullPolicyChange('preserve')" />{{ I18N.culling.auto_cull.preserve | translate }}</label>
            <label class="inline-flex min-h-11 items-center gap-2 text-sm"><input type="radio" name="autoCullPolicy" value="replace" [checked]="cull.autoCullDecisionPolicy() === 'replace'" (change)="cull.onAutoCullPolicyChange('replace')" />{{ I18N.culling.auto_cull.replace | translate }}</label>
          </fieldset>
          <details class="text-xs"><summary class="cursor-pointer py-1">{{ I18N.nav.help | translate }}</summary><p class="py-1">{{ I18N.culling.auto_cull.policy_help | translate }}</p></details>
          <p class="text-xs" role="status">{{ I18N.culling.auto_cull.existing_summary | translate:{ count: (ac.existing_labels_count ?? 0), preserved: (ac.preserved_labels_count ?? 0) } }}</p>
          @if (cull.autoCullIssue(); as issue) {
            <p role="alert" class="text-sm text-[var(--mat-sys-error)]">{{ (issue === 'changed' ? I18N.culling.auto_cull.preview_changed : I18N.culling.auto_cull.apply_uncertain) | translate }}</p>
          }

          @if (cull.autoCullRequest()?.profile; as profile) {
            <p class="flex items-center gap-1.5 text-sm opacity-80">
              <mat-icon class="!text-base !w-4 !h-4 !leading-4">{{ profile | cullProfileIcon }}</mat-icon>
              {{ autoCullProfileLabel() | translate }}
              @if (suggestedProfileActive() && cull.autoCullRequest()?.profile === cull.selectedProfile() && cull.autoCullRequest()?.strictness === cull.strictness()) {
                <!-- A button, not a bare span: same reasoning as the "My Taste" badge in
                     app.html -- the explanation lives only in matTooltip, unreachable by
                     keyboard/AT users without a focusable host. -->
                <button type="button"
                        class="px-2 py-0.5 rounded-full text-xs bg-[var(--mat-sys-primary)]/12 text-[var(--mat-sys-primary)]"
                        [matTooltip]="I18N.culling.auto_cull.suggested_tooltip | translate">
                  {{ I18N.culling.auto_cull.suggested | translate }}
                  @if (cull.profileSuggestion(); as suggestion) {
                    <span class="sr-only">: {{ suggestion.confidence | percent }}</span>
                  }
                </button>
              }
            </p>
          }
          <label class="flex items-center gap-2 text-sm cursor-pointer"
                 [matTooltip]="I18N.culling.auto_cull.trim_brackets_hint | translate">
            <input type="checkbox" class="accent-[var(--mat-sys-primary)]"
                   [checked]="cull.trimBrackets()" [disabled]="cull.autoCullBusy()"
                   (change)="cull.onTrimBracketsChange(!cull.trimBrackets())" />
            {{ I18N.culling.auto_cull.trim_brackets | translate }}
          </label>
          <!-- A cold suggest+preview takes seconds, during which the counts below are
               last run's. Say so rather than let them read as this run's answer. -->
          @if (cull.autoCullBusy()) {
            <p class="flex items-center gap-2 text-sm opacity-80" role="status">
              <mat-spinner diameter="16" [attr.aria-label]="I18N.ui.labels.loading | translate" />
              {{ I18N.culling.auto_cull.updating | translate }}
            </p>
          }
          @if (cull.autoCullSuggestionNotice(); as suggested) {
            <p class="text-xs text-[var(--mat-sys-primary)]" role="status">
              {{ I18N.culling.auto_cull.preview_updated | translate:{ profile: suggested } }}
            </p>
          }
          @if (cull.trimBracketsUnchanged()) {
            <p class="text-xs text-[var(--mat-sys-on-surface-variant)]" role="status">{{ I18N.culling.auto_cull.trim_brackets_none | translate }}</p>
          }
          @if (ac.groups_processed === 0) {
            <p class="text-sm opacity-80">{{ I18N.culling.auto_cull.empty | translate }}</p>
          } @else {
            <p class="text-sm opacity-80">
              {{ I18N.culling.auto_cull.summary | translate:{ groups: ac.groups_processed, kept: ac.kept, rejected: ac.rejected } }}
            </p>
            <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.culling.strictness | translate }} · {{ cull.autoCullRequest()?.strictness }}%</p>
            @if (ac.groups_processed > 0) {
              <label class="flex min-h-11 items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" class="accent-[var(--mat-sys-primary)]"
                       [checked]="cull.autoCullHighlights()" [disabled]="cull.autoCullBusy()"
                       (change)="cull.onAutoCullHighlightsChange(!cull.autoCullHighlights())" />
                {{ I18N.culling.auto_cull.highlights_option | translate }} @if (cull.autoCullHighlights()) { <span>({{ ac.highlights_added }})</span> }
              </label>
            }
          }

          <details class="border-t border-[var(--mat-sys-outline-variant)] pt-2" data-auto-consequences>
            <summary class="cursor-pointer py-2 font-medium">{{ I18N.culling.auto_cull.consequences | translate }}</summary>
            <ul class="m-0 list-none space-y-2 p-0 text-xs">
              @for (label of ac.existing_labels ?? []; track label.path) {
                <li class="break-words border-b border-[var(--mat-sys-outline-variant)] py-2"><strong>{{ label.path | filename }}</strong> · ★ {{ label.star_rating }}
                  @if (label.is_favorite) { · {{ I18N.rating.favorite | translate }} }
                  @if (label.is_kept) { · {{ I18N.review.kept | translate }} }
                  @if (label.is_rejected) { · {{ I18N.review.rejected | translate }} }
                  → {{ proposedLabelKeys[label.proposed] | translate }}
                </li>
              }
            </ul>
            @if (ac.existing_labels_truncated) { <p class="text-xs">{{ I18N.culling.auto_cull.existing_overflow | translate:{ shown: (ac.existing_labels?.length ?? 0), count: (ac.existing_labels_count ?? 0) } }}</p> }
            @for (group of ac.preview; track group.number) {
              <details class="border-b border-[var(--mat-sys-outline-variant)] py-2 text-xs">
                <summary class="cursor-pointer py-1">{{ I18N.culling.auto_cull.group_plan | translate:{ number: group.number, kept: group.keep_paths.length, rejected: group.reject_paths.length } }}</summary>
                <p>{{ I18N.culling.auto_cull.group_existing | translate:{ count: (group.existing_labels_count ?? 0) } }}</p>
                <ul class="m-0 list-none p-0">
                  @for (path of group.keep_paths; track path) { <li class="break-words py-1">{{ I18N.review.kept | translate }} · {{ path | filename }}</li> }
                  @for (path of group.reject_paths; track path) { <li class="break-words py-1">{{ I18N.review.rejected | translate }} · {{ path | filename }}</li> }
                </ul>
              </details>
            }
            @if (ac.next_cursor !== null && ac.next_cursor !== undefined) { <button mat-stroked-button class="mt-2" (click)="cull.loadAutoCullPage()" [disabled]="cull.autoCullBusy() || !!cull.autoCullIssue()">{{ I18N.ui.buttons.load_more | translate }}</button> }
          </details>
          <div class="flex flex-wrap justify-end gap-2">
            <button mat-stroked-button (click)="cull.openAutoCull()" [disabled]="cull.autoCullBusy()">{{ I18N.culling.auto_cull.refresh_preview | translate }}</button>
            <button mat-stroked-button (click)="cull.cancelAutoCull()" [disabled]="cull.autoCullApplying()">{{ I18N.dialog.cancel | translate }}</button>
            @if (ac.groups_processed > 0) {
              <button mat-flat-button (click)="confirmAutoCull()" [disabled]="cull.autoCullBusy() || !!cull.autoCullIssue()">
                {{ I18N.culling.auto_cull.apply | translate:{ rejected: ac.rejected } }}
              </button>
            }
          </div>
        </div>
      </div>
    }
  `,
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'block h-full' },
  providers: [CullingStore],
})
export class BurstCullingComponent implements OnDestroy {
  protected readonly I18N = i18nKeys();
  protected readonly proposedLabelKeys = PROPOSED_LABEL_KEYS;
  private readonly api = inject(ApiService);
  private readonly element = viewChild<ElementRef<HTMLElement>>('cullingPage');
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly albumService = inject(AlbumService);
  private readonly compareFilters = inject(CompareFiltersService);
  private readonly sequenceOverrides = inject(SequenceOverrideService);
  private readonly panoramaSettings = inject(PanoramaSettingsService);
  private readonly undoService = inject(UndoService);
  private readonly stackActions = inject(StackActionsService);
  private stacking = false;
  protected readonly auth = inject(AuthService);
  protected readonly store = inject(GalleryStore);
  private readonly dialog = inject(MatDialog);
  private readonly pageContext = inject(PageContextService);
  private readonly destroyRef = inject(DestroyRef);
  private trashOpening = false;
  private trashNavigation = 0;
  private readonly sceneDate = new SceneDatePipe();
  /** Data state + API calls; provided per component, so it lives one darkroom visit. */
  protected readonly cull = inject(CullingStore);
  private readonly journal = inject(UserActivityJournal);
  private readonly assistantChanges = inject(AssistantChangesService);
  private readonly planService = inject(AssistantCullPlanService);

  /** Min posterior below which a moment label is shown dimmed + "(uncertain)". */
  protected readonly momentConfidenceMin = computed(
    () => this.store.config()?.moment_confidence_min ?? 0,
  );

  protected readonly scoped = computed(
    () => !!(this.cull.scopeAlbum() || this.cull.scopeFrom() || this.cull.scopeTo()),
  );
  /** An album or a scene narrows the feed (dates alone do not light the album button). */
  protected readonly albumScoped = computed(() => !!(this.cull.scopeAlbum() || this.cull.scopeScene()));
  protected readonly datePresets = CULL_DATE_PRESETS;
  /** Why the feed is empty: the wording follows what narrowed it. */
  protected readonly emptyKey = computed(() => {
    if (this.stacksMode()) return this.I18N.stacks.suggestions_empty;
    const dated = this.cull.dateRangeActive();
    // Only a feed or plan that loaded no group at all: one whose groups were all confirmed or hidden is "done".
    const loadedNone = this.cull.groups().length === 0;
    if (this.cull.planActive() && dated && loadedNone) return this.I18N.culling.date_range.plan_empty;
    if (dated && loadedNone && !this.cull.scopeScene()) return this.I18N.culling.date_range.empty;
    return this.scoped() ? this.I18N.culling.scene_complete : this.I18N.culling.no_bursts;
  });
  /**
   * A cull opened from /scenes ("Cull this scene") whose every group is decided and accepted by the
   * server: the cue to open the next scene. A scene that arrived with nothing left to review has
   * written no confirm here, so landing on one never skips onwards by itself.
   */
  protected readonly sceneCulled = computed(() => {
    const cull = this.cull;
    if (this.stacksMode() || cull.planActive() || cull.groupBy() !== 'scene' || !cull.scopeScene() || !cull.scopeTo()) return false;
    if (cull.loading() || cull.hasMore() || cull.confirming() || !cull.commitsSettled() || cull.passingGroups().size > 0
      || cull.committedConfirms() === 0) return false;
    const closed = cull.closedGroupKeys();
    return cull.groups().every(group => closed.has(cull.groupKey(group)));
  });
  protected readonly expandedAlbumId = signal<number | null>(null);
  protected readonly expandedScenes = signal<SceneSummary[]>([]);
  protected readonly loadingScenes = signal(false);

  // Photo-Mechanic-style hover loupe over the group tiles (Z toggles; zoom slider).
  private readonly loupe = createLoupeState();
  protected readonly loupeActive = this.loupe.loupeActive;
  protected readonly loupeZoom = this.loupe.loupeZoom;

  /** Label of the preset the auto-cull ran with, or "Custom" when it ran with none. */
  protected readonly autoCullProfileLabel = computed(() => this.cull.cullProfiles().find(profile => profile.id === this.cull.autoCullRequest()?.profile)?.label_key ?? I18N.culling.profiles.custom);

  /** Label of the active preset, or "Custom" when none matches the current knobs. */
  protected readonly selectedProfileLabel = computed(() => {
    const p = this.cull.cullProfiles().find(x => x.id === this.cull.selectedProfile());
    return p ? p.label_key : I18N.culling.profiles.custom;
  });

  /** True when the active preset is the suggested one and the user never chose
   *  it — the only case where the dialog claims a suggestion. */
  protected readonly suggestedProfileActive = computed(() => {
    const suggested = this.cull.profileSuggestion()?.profile;
    return !!suggested && !this.cull.profileChosen() && this.cull.selectedProfile() === suggested;
  });

  /**
   * True in a granularity whose sets are kept whole.
   *
   * Auto-cull picks one frame per group, which is meaningless for a bracket or a
   * pan and is why the server accepts no such scope. Hidden rather than
   * disabled: a control that can never apply here is noise, and leaving it
   * enabled produced a bare 422 behind a generic failure message.
   */
  protected readonly keepWholeGranularity = computed(
    () => SEQUENCE_KINDS_KEPT_WHOLE.includes(this.cull.groupBy()),
  );
  /** True while a re-detection subprocess runs (spawned here or elsewhere). */
  protected readonly detecting = signal(false);
  protected readonly detectMessage = signal('');
  protected readonly detectFailed = signal(false);
  private detectPollTimer: ReturnType<typeof setInterval> | null = null;

  /** Lightbox state — group being viewed, and current photo index inside it. */
  protected readonly lightboxGroupId = signal<string | null>(null);
  protected readonly lightboxIndex = signal(0);
  protected readonly lightboxGroup = computed<CullingGroup | null>(() => {
    const key = this.lightboxGroupId();
    if (!key) return null;
    return this.cull.groups().find(g => this.cull.groupKey(g) === key) ?? null;
  });
  protected readonly lightboxDecisionLocked = computed(() => !this.auth.isEdition() || this.cull.confirming()
    || this.cull.replanning() || this.cull.closedGroupKeys().has(this.lightboxGroupId() ?? ''));
  protected readonly lightboxKeptCount = computed(() => this.cull.selectionsMap().get(this.lightboxGroupId() ?? '')?.size ?? 0);

  /** Compare mode for the darkroom: single view, or a synced 2-up / 4-up grid. */
  protected readonly compareMode = signal<'single' | '2up' | '4up'>('single');
  /** Focused frame transform; per-path framing survives independent inspection. */
  protected readonly zoom = computed(() => this.paneFrames().get(this.currentPath() ?? '') ?? FIT_ZOOM);
  protected readonly FIT_ZOOM = FIT_ZOOM;
  protected readonly paneFrames = signal(new Map<string, ZoomState>());
  protected readonly darkroomLinked = signal(true);
  protected readonly cleanComparison = signal(false);
  protected readonly filmstripVisible = signal(true);
  protected readonly inspectionStripsVisible = signal(false);

  protected toggleCleanComparison(): void {
    this.cleanComparison.update(value => !value);
    this.lightboxDialog()?.nativeElement.focus();
  }

  protected toggleFilmstrip(): void { this.filmstripVisible.update(value => !value); }
  protected toggleInspectionStrips(): void { this.inspectionStripsVisible.update(value => !value); }
  protected toggleDarkroomLink(): void { this.darkroomLinked.update(value => !value); }

  protected async rejectEntireGroup(group: CullingGroup): Promise<void> {
    if (this.stacksMode() || !this.auth.isEdition() || this.pageNavigating || !this.pageAlive || this.cull.replanning()
      || this.cull.confirmedGroups().has(this.cull.groupKey(group)) || this.dialog.openDialogs.length) return;
    const captured = structuredClone(group);
    const owner = this.auth.identity(), status = this.auth.status(), token = this.auth.token, epoch = this.pageEpoch;
    const current = () => this.pageAlive && !this.pageNavigating && this.pageEpoch === epoch && this.auth.isEdition()
      && this.auth.identity() === owner && this.auth.status() === status && this.auth.token === token
      && !this.cull.replanning() && !this.cull.confirmedGroups().has(this.cull.groupKey(captured))
      && this.visibleGroups().some(item => this.cull.groupKey(item) === this.cull.groupKey(captured)
        && item.sequence_kind === captured.sequence_kind
        && photoSignature(item) === photoSignature(captured));
    const { ConfirmDialogComponent } = await import('../../shared/components/confirm-dialog/confirm-dialog.component');
    if (!current()) return;
    const wholeKind = wholeKindOf(captured);
    const memberKinds = captured.photos.flatMap(photo => photo.sequence_kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(photo.sequence_kind) ? [photo.sequence_kind] : []);
    const sequenceCount = wholeKind ? captured.photos.length : memberKinds.length;
    const sequence = sequenceCount > 0;
    const kinds = [...new Set(wholeKind ? [wholeKind] : memberKinds)].sort().map(kind => this.i18n.t(SEQUENCE_KIND_LABELS[kind])).join(', ');
    const ref = this.dialog.open(ConfirmDialogComponent, { width: '95vw', maxWidth: '30rem', data: {
      title: this.i18n.t(sequence ? I18N.culling.workspace.reject_sequence_title : I18N.culling.workspace.reject_all_title),
      message: sequence
        ? this.i18n.t(I18N.culling.workspace.reject_sequence_body, { count: captured.photos.length, sequence_count: sequenceCount, kinds })
        : this.i18n.t(I18N.culling.workspace.reject_all_body, { count: captured.photos.length }),
      confirmLabel: this.i18n.t(sequence ? I18N.culling.workspace.reject_sequence_confirm : I18N.culling.workspace.reject_all),
    } });
    if (!await firstValueFrom(ref.afterClosed()) || !current()) return;
    if (this.cull.rejectEntireGroup(captured) && this.lightboxGroup()) {
      const next = this.nextUnconfirmedGroupAfter(captured);
      if (next) this.openLightbox(next, 0); else this.closeLightbox();
    }
  }

  protected onTileContinue(event: Event, group: CullingGroup, indexInGroup: number): void {
    const key = event as KeyboardEvent;
    if (this.shortcutsBlocked(event) || key.repeat || key.isComposing || key.keyCode === 229 || key.ctrlKey || key.metaKey || key.altKey) return;
    if (this.stacksMode()) { this.openLightbox(group, indexInGroup); event.preventDefault(); return; }
    const index = this.visibleGroups().findIndex(item => this.cull.groupKey(item) === this.cull.groupKey(group));
    if (index >= 0) this.selectedGroupIndex.set(index);
    this.continueCullingGroup(event);
  }

  private readonly coarsePointer = useCoarsePointerSignal();

  /**
   * Whether swipe-to-decide is live on the open frame.
   *
   * Three gates, each closing a way the gesture would fight another one:
   * a coarse pointer, because a mouse has the ↑ / ↓ keys and cannot swipe;
   * single view, because a compare grid has no one frame a swipe would be
   * about; and the fit scale, because past it the very same drag is the pane's
   * pan — `SyncedZoomComponent` ignores pointerdown at fit and captures the
   * pointer above it, so this flag is what keeps exactly one handler reading
   * any given drag.
   */
  protected readonly swipeEnabled = computed(
    () => !this.stacksMode() && this.coarsePointer.isCoarsePointer()
      && this.compareMode() === 'single'
      && this.zoom().scale <= SyncedZoomComponent.MIN_SCALE,
  );

  /** One-line swipe hint, shown until the user says they have read it. */
  protected readonly swipeHintDismissed = signal(localStorage.getItem(CULL_SWIPE_HINT_KEY) === 'true');

  protected dismissSwipeHint(): void {
    localStorage.setItem(CULL_SWIPE_HINT_KEY, 'true');
    this.swipeHintDismissed.set(true);
  }
  /** True while the darkroom dialog is the document's fullscreen element. */
  protected readonly isFullscreen = signal(false);

  /** Named darktable styles for the edited-look preview (empty = feature hidden). */
  protected readonly cullStyles = computed<CullStyle[]>(
    () => (this.store.config()?.['cull_styles'] as CullStyle[] | undefined) ?? [],
  );
  /** Whether to expose the style selector: edition rights + at least one style. */
  protected readonly cullStyleCapable = computed(
    () => this.auth.isEdition() && this.cullStyles().length > 0,
  );

  /** Keyboard-shortcut legend in the darkroom header. Hidden by default (it was
   *  permanent chrome noise, and the French labels reflowed to two rows at
   *  1280-1440px); persisted like the rest of the toolbar prefs above. */
  protected readonly legendVisible = signal(localStorage.getItem(CULL_LEGEND_KEY) === 'true');

  /** Focus peaking over the darkroom frames (P). Session-only, like the compare
   *  mode and the style preview; legend and loupe preferences are remembered. */
  protected readonly peakingActive = signal(false);
  /** Hover loupe over the darkroom's single/compare panes and face strip. ON
   *  by default (unlike the grid's own loupe toggle, which defaults off) and
   *  persisted, unlike the rest of the darkroom's session-only view toggles —
   *  it's a pixel-peeking aid a culler wants to keep set the way they left it. */
  protected readonly darkroomLoupeActive = signal(localStorage.getItem(CULL_DARKROOM_LOUPE_KEY) !== 'false');
  /** Shared zoom level for every darkroom loupe instance (single pane, compare
   *  panes, face strip) — same signal the spec calls for, from the same
   *  createLoupeState() the grid uses. */
  private readonly darkroomLoupe = createLoupeState();
  protected readonly darkroomLoupeZoom = this.darkroomLoupe.loupeZoom;
  /** The loupe must never show while the frame is zoomed past fit: dragging
   *  to pan a magnified image and a lens fighting for the same cursor makes
   *  neither usable. */
  protected readonly darkroomLoupeEffective = computed(() =>
    this.darkroomLoupeActive() && this.zoom().scale <= SyncedZoomComponent.MIN_SCALE);
  protected toggleDarkroomLoupe(): void {
    const next = !this.darkroomLoupeActive();
    this.darkroomLoupeActive.set(next);
    localStorage.setItem(CULL_DARKROOM_LOUPE_KEY, String(next));
  }
  /** Composition grid: off → rule of thirds → golden ratio (G). Session-only. */
  protected readonly gridMode = signal<GridMode>('');

  protected readonly darkroomThumbSize = DARKROOM_THUMB_SIZE;
  protected readonly storedEdge = STORED_EDGE;


  protected stepDarkroomZoom(direction: number, path = this.currentPath() ?? ''): void {
    const current = this.paneFrames().get(path) ?? FIT_ZOOM;
    this.onDarkroomZoom({ ...current, scale: Math.max(1, Math.min(8, current.scale * (direction > 0 ? 1.5 : 1 / 1.5))) }, path);
  }

  protected onDarkroomZoom(state: ZoomState, path = this.currentPath() ?? ''): void {
    if (!this.canEditPage()
      || !this.darkroomFramePaths().includes(path) || ![state.scale, state.tx, state.ty].every(Number.isFinite)
      || state.scale < 1 || state.scale > 8) return;
    const frames = this.paneFrames();
    if (!this.darkroomLinked()) {
      this.paneFrames.set(new Map(frames).set(path, { ...state }));
    } else {
      this.paneFrames.set(linkedZoomFrames(frames, this.darkroomFramePaths(), path, state));
    }
  }

  protected fitDarkroom(path = this.currentPath() ?? ''): void {
    if (!this.darkroomFramePaths().includes(path) || !this.canEditPage()) return;
    const frames = new Map(this.paneFrames());
    for (const member of this.darkroomLinked() ? this.darkroomFramePaths() : [path]) frames.set(member, { ...FIT_ZOOM });
    this.paneFrames.set(frames);
  }


  protected readonly onRenditionHelpEscape = closeDetailsOnEscape;

  /** Path of the frame the single pane shows. A string, so a new group object
   *  holding the same frame does not notify the prefetch effects. */
  private readonly currentPath = computed(() => this.lightboxGroup()?.photos[this.effectiveLightboxIndex()]?.path);

  /** The image transform of every pane, shared with the peaking overlay so the
   *  edge map pans and zooms with the frame instead of being recomputed. */
  protected readonly frameTransforms = computed(() => new Map([...this.paneFrames()].map(([path, z]) =>
    [path, `translate(${z.tx}px, ${z.ty}px) scale(${z.scale})`])));

  /** Whether any pane is zoomed beyond fit; panning alone does not retrigger peaking. */
  private readonly darkroomHiRes = computed(() => this.darkroomFramePaths().some(path => (this.paneFrames().get(path)?.scale ?? 1) > SyncedZoomComponent.MIN_SCALE));

  protected readonly gridModeLabel = computed(() => {
    const mode = this.gridMode();
    if (mode === 'thirds') return I18N.culling.grid.thirds;
    return mode === 'golden' ? I18N.culling.grid.golden : I18N.culling.grid.off;
  });

  /** The frames the darkroom is showing right now: the focused one in single
   *  view, the whole tiled set in compare mode (where peaking earns its keep). */
  protected readonly darkroomFramePaths = computed<string[]>(() => {
    const group = this.lightboxGroup();
    if (!group) return [];
    if (this.compareMode() !== 'single') return this.compareFrames().map(p => p.path);
    const photo = group.photos[this.effectiveLightboxIndex()];
    return photo ? [photo.path] : [];
  });

  /** The active pane's group index, or the single-view index. */
  protected readonly effectiveLightboxIndex = computed(() => {
    const group = this.lightboxGroup();
    if (group && this.compareMode() !== 'single' && this.comparisonPaths().length) {
      const path = this.compareFrames()[this.comparisonSlot()]?.path;
      const index = group.photos.findIndex(photo => photo.path === path);
      if (index >= 0) return index;
    }
    return this.lightboxIndex();
  });
  protected readonly comparisonSlotLabels = ['A', 'B', 'C', 'D'];
  private readonly comparisonSlotIndex = signal(0);
  protected readonly comparisonSlot = computed(() => Math.min(this.comparisonSlotIndex(), Math.max(0, this.compareFrames().length - 1)));
  private readonly comparisonPaths = signal<string[]>([]);
  protected readonly compareFrames = computed(() => {
    const group = this.lightboxGroup();
    if (!group) return [];
    const count = this.compareMode() === '4up' ? 4 : 2;
    const start = Math.min(this.lightboxIndex(), Math.max(0, group.photos.length - count));
    const byPath = new Map(group.photos.map(photo => [photo.path, photo]));
    const order = [...this.comparisonPaths(), ...group.photos.slice(start).map(photo => photo.path), ...group.photos.map(photo => photo.path)];
    return [...new Set(order)].filter(path => byPath.has(path)).slice(0, count).map(path => byPath.get(path)!);
  });

  protected setCompareMode(mode: 'single' | '2up' | '4up'): void {
    const previous = this.compareMode();
    const focusedIndex = this.effectiveLightboxIndex();
    if (mode !== previous) {
      // Single/compare recreate their panes; 2-up/4-up retain shared panes.
      this.renditions.resetPaneReadiness(mode === 'single' || previous === 'single');
      const frames = previous === 'single' ? [] : this.compareFrames().map(photo => photo.path);
      const focusedPath = this.lightboxGroup()?.photos[focusedIndex]?.path;
      const count = mode === '4up' ? 4 : 2;
      if (previous !== 'single' && mode !== 'single' && focusedPath && !frames.slice(0, count).includes(focusedPath)) {
        const old = frames.indexOf(focusedPath);
        if (old >= 0) frames.splice(old, 1);
        frames.unshift(focusedPath);
      }
      this.comparisonPaths.set(frames);
      this.lightboxIndex.set(focusedIndex);
      this.compareMode.set(mode);
      if (mode !== 'single') {
        const paths = this.compareFrames().map(photo => photo.path);
        this.comparisonPaths.set(paths);
        this.comparisonSlotIndex.set(Math.max(0, focusedPath ? paths.indexOf(focusedPath) : 0));
      } else this.comparisonSlotIndex.set(0);
    }
  }

  // --- Darkroom overlays (focus peaking + composition grid) ---


  protected togglePeaking(): void {
    this.peakingActive.set(!this.peakingActive());
  }

  protected toggleLegend(): void {
    const next = !this.legendVisible();
    this.legendVisible.set(next);
    localStorage.setItem(CULL_LEGEND_KEY, String(next));
  }

  /** Cycle the composition grid: off → rule of thirds → golden ratio. */
  protected cycleGrid(): void {
    this.gridMode.set(GRID_MODES[(GRID_MODES.indexOf(this.gridMode()) + 1) % GRID_MODES.length]);
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
  private readonly cullBar = viewChild<ElementRef<HTMLElement>>('cullBar');
  protected readonly barRow = MOBILE_DOCKED_BAR_ROW;
  /** Height of the fixed bottom bar, which wraps to a variable number of rows; the list pads by it. */
  protected readonly barHeight = signal(0);

  /** The single-view zoom pane, so the Z key runs the pane's own focus-aware
   *  zoom math (which needs the pane rect) rather than a second copy of it. */
  private readonly zoomPane = viewChild(SyncedZoomComponent);

  /** photo path -> detected faces, loaded lazily when a lightbox group opens. */
  protected readonly faceMap = signal<Map<string, CullingFace[]>>(new Map());

  /** Config-driven face-signal cutoffs from the faces response (ring colors + badges). */
  protected readonly faceThresholds = signal<FaceThresholds | null>(null);

  /** photo path -> subject close-up crop, loaded lazily for non-face groups. */
  protected readonly subjectMap = signal<Map<string, CullingSubject>>(new Map());

  /** photo path -> who/what the frame is about, loaded for every focused group.
   *  Drives the darkroom's zoom target and the key-person badge. */
  protected readonly keySubjectMap = signal<Map<string, KeySubject>>(new Map());

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

  /** Face close-up display size (px), persisted browser preference. */
  protected readonly faceSize = signal(readStoredFaceSize());
  protected readonly faceSizeMinPx = FACE_SIZE_MIN_PX;
  protected readonly faceSizeMaxPx = FACE_SIZE_MAX_PX;
  protected readonly faceSizeStepPx = FACE_SIZE_STEP_PX;

  protected onFaceSizeChange(value: number): void {
    this.faceSize.set(value);
    localStorage.setItem(CULL_FACE_SIZE_KEY, String(value));
  }

  /** A pointer drag (or a plain click) on a face-strip slider leaves the thumb
   *  focused, so the next arrow key adjusts the slider instead of reaching the
   *  darkroom's document-level nav/keep/reject handlers. Return focus to the
   *  dialog so keyboard navigation resumes. Keyboard-only interaction (Tab then
   *  arrow keys) never fires `dragEnd`, so that a11y path keeps native
   *  slider focus untouched. */
  protected releaseSliderFocus(): void {
    this.lightboxDialog()?.nativeElement.focus();
  }

  /** True when at least one photo in the focused group has loaded faces. */
  protected readonly faceGridHasFaces = computed(() => {
    const group = this.lightboxGroup();
    if (!group) return false;
    const map = this.faceMap();
    return group.photos.some(p => (map.get(p.path)?.length ?? 0) > 0);
  });

  /** True when at least one photo in the focused group has a subject close-up. */
  protected readonly subjectGridHasSubjects = computed(() => {
    const group = this.lightboxGroup();
    if (!group) return false;
    const map = this.subjectMap();
    return group.photos.some(p => map.get(p.path)?.has_subject === true);
  });

  /** Show the subject close-up strip only for groups with subjects but no faces,
   *  so face groups get the face strip and non-face subject groups get this one. */
  protected readonly subjectStripVisible = computed(
    () => !this.faceGridHasFaces() && this.subjectGridHasSubjects(),
  );

  /** Groups visible in the UI (excludes hidden groups + honors the category filter). */
  protected readonly visibleGroups = computed(() => {
    const hidden = this.cull.hiddenGroups();
    const cat = this.stacksMode() ? '' : this.categoryFilter();
    return this.cull.groups().filter(g => !hidden.has(this.cull.groupKey(g)) && (!cat || g.category === cat));
  });

  protected readonly unconfirmedCount = computed(() => {
    const confirmed = this.cull.confirmedGroups();
    return this.visibleGroups().filter(g => !confirmed.has(this.cull.groupKey(g))
      && (this.cull.selectionsMap().get(this.cull.groupKey(g))?.size ?? 0) > 0).length;
  });

  /** Index of the keyboard-selected group (page-level nav when the lightbox is closed). */
  protected readonly selectedGroupIndex = signal(0);
  /** The list view's photo cursor: ← / → move it; Space confirms the group. */
  protected readonly selectedPhotoIndex = linkedSignal({ source: this.selectedGroupIndex, computation: () => 0 });

  protected readonly sortModes = ['easiest', 'redundant', 'best', 'recent', 'needs_comparisons', 'chronological'] as const;

  /** Whether the active mode currently runs oldest/smallest-first. */
  protected readonly sortAscending = computed(() => {
    const explicit = this.cull.sortDirection();
    if (explicit) return explicit === 'asc';
    return this.cull.sortMode() === 'chronological';
  });

  /** Content-category to cull ('' = all). Filters the visible group list client-side. Persisted. */
  protected readonly categoryFilter = signal(localStorage.getItem(CULL_CATEGORY_KEY) ?? '');

  /** Distinct categories among loaded groups, for the header filter select. */
  protected readonly availableCategories = computed<string[]>(() => {
    const set = new Set<string>();
    for (const g of this.cull.groups()) if (g.category) set.add(g.category);
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

  protected readonly stacksMode = computed(() => this.cull.mode() === 'stacks');
  protected readonly darkroomShortcuts = computed(() => this.stacksMode() ? STACK_DARKROOM_SHORTCUTS : DARKROOM_SHORTCUTS);
  protected readonly stackNotice = signal(false);
  private stackReturnUrl = '/';
  private pageEpoch = 0;
  private pageAlive = true;
  private pageNavigating = false;
  private pageOwner = this.auth.identity();

  private canEditPage(): boolean {
    return this.pageAlive && !this.pageNavigating && this.auth.identity() === this.pageOwner && this.auth.isEdition();
  }
  private secondaryEditor: { close: () => void } | null = null;
  private stackNavigationSource: { owner: string; filters: Record<string, string> | null } | null = null;
  private detectionGeneration = 0;

  private clearStackView(): void {
    this.secondaryEditor?.close();
    this.secondaryEditor = null;
    this.closeLightbox();
    this.faceMap.set(new Map());
    this.subjectMap.set(new Map());
    this.keySubjectMap.set(new Map());
    this.renditions.resetStackView();
  }

  private setStackReturnUrl(target: string): void {
    this.stackReturnUrl = stackEditorReturnUrl(this.router, target);
  }

  private loadCullingAuxiliaryState(): void {
    void this.loadAlbums();
    void this.cull.loadCullProfiles();
    void this.cull.refreshComparisonStats();
    void this.cull.refreshRankerStatus();
  }

  /** A cancelled visit has a new root navigation context; old decisions and Undo must stay expired. */
  private recoverStackVisit(): void {
    const source = this.stackNavigationSource;
    this.stackNavigationSource = null;
    if (!source || !this.pageAlive || this.destroyRef.destroyed) return;
    const tree = this.router.parseUrl(this.router.url);
    const segments = tree.root.children['primary']?.segments;
    if (segments?.length !== 1 || segments[0].path !== 'culling') return;
    if (tree.queryParamMap.get('mode') !== 'stacks' && source.filters === null) return;
    if (this.auth.identity() !== source.owner || !this.auth.isEdition()) { this.leaveStacks(); return; }
    if (tree.queryParamMap.get('mode') !== 'stacks') {
      this.cull.leaveStackMode();
      if (!this.planService.pin()) void this.cull.loadGroups();
      this.loadCullingAuxiliaryState();
      return;
    }
    try {
      const filters = parseStackReviewFilters(tree.queryParamMap.get('filters'));
      this.stopDetectionPolling();
      this.clearStackView();
      this.cull.enterStackMode(filters);
      this.setStackReturnUrl(tree.queryParamMap.get('return') ?? '/');
      void this.cull.loadGroups();
    } catch { this.leaveStacks(); }
  }

  private pageSession(): () => boolean {
    const epoch = this.pageEpoch;
    const owner = this.auth.identity();
    const mode = this.cull.mode();
    return () => this.pageAlive && !this.pageNavigating && !this.destroyRef.destroyed && epoch === this.pageEpoch
      && this.auth.identity() === this.pageOwner
      && this.auth.identity() === owner && this.auth.isEdition() && this.cull.mode() === mode;
  }

  private leaveStacks(): void {
    this.pageEpoch++;
    this.stopDetectionPolling();
    this.stackNavigationSource = null;
    this.clearStackView();
    this.cull.leaveStackMode();
    this.pageOwner = this.auth.identity();
    this.stackNotice.set(true);
    void this.router.navigate(['/culling'], { replaceUrl: true });
    void this.cull.loadGroups();
    this.loadCullingAuxiliaryState();
  }

  protected backToGallery(): void { void this.router.navigateByUrl(this.stackReturnUrl); }


  readonly renditions = new DarkroomRenditions({
    group: () => this.lightboxGroup(),
    focusedIndex: () => this.effectiveLightboxIndex(),
    compareMode: () => this.compareMode(),
    visiblePaths: () => this.darkroomFramePaths(),
    highResolution: () => this.darkroomHiRes(),
    peakingActive: () => this.peakingActive(),
    gridActive: () => !!this.gridMode(),
    current: () => this.canEditPage(),
    epoch: () => this.pageEpoch,
    captureSession: () => this.pageSession(),
  });

  constructor() {
    const qp = this.route.snapshot.queryParamMap;
    if (qp.get('mode') === 'stacks') {
      try {
        if (!this.auth.isEdition()) throw new Error('Invalid stack session');
        this.cull.enterStackMode(parseStackReviewFilters(qp.get('filters')));
        this.setStackReturnUrl(qp.get('return') ?? '/');
      } catch {
        this.stackNotice.set(true);
        void this.router.navigate(['/culling'], { replaceUrl: true });
      }
    }
    const owner = this.auth.identity();
    effect(() => {
      const identity = this.auth.identity();
      const edition = this.auth.isEdition();
      const invalid = this.cull.stackScopeInvalid();
      if (this.stacksMode() && (identity !== owner || !edition || invalid)) untracked(() => this.leaveStacks());
    });
    registerPageContext('culling', () => ({ mode: this.cull.mode() }));
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) {
        this.pageNavigating = true;
        this.trashNavigation++;
        this.pageEpoch++;
        this.stackNavigationSource ??= { owner: this.pageOwner, filters: this.stacksMode() ? { ...this.cull.stackFilters() } : null };
        if (this.stacksMode()) {
          this.clearStackView();
          // Invalidate the old visit without ever enabling cull writes beneath a stack URL.
          this.cull.enterStackMode(this.stackNavigationSource.filters ?? {});
          this.cull.loading.set(true);
        } else this.secondaryEditor?.close();
      } else if (event instanceof NavigationEnd || event instanceof NavigationCancel
        || event instanceof NavigationError || event instanceof NavigationSkipped) {
        if (event instanceof NavigationCancel && (event.code === NavigationCancellationCode.Redirect
          || event.code === NavigationCancellationCode.SupersededByNewNavigation)) return;
        this.pageNavigating = false;
        this.recoverStackVisit();
      }
    });
    effect(() => this.pageHelp.setDescription(this.stacksMode() ? this.I18N.stacks.review_help : this.I18N.culling.help_text));
    // The help dialog's My Taste line: how many comparisons the ranker has.
    effect(() => {
      if (this.stacksMode()) { this.pageHelp.note.set(null); return; }
      const count = this.cull.rankerComparisons();
      const key = this.cull.rankerTrained() ? this.I18N.culling.my_taste_trained : this.I18N.culling.my_taste_learning;
      this.pageHelp.note.set(count === null ? null : { key, params: { count } });
    });
    this.cull.notice$.pipe(takeUntilDestroyed()).subscribe(notice => {
      const text = notice.params ? this.i18n.t(notice.key, notice.params) : this.i18n.t(notice.key);
      this.snackBar.open(text, '', { duration: notice.duration, horizontalPosition: 'right', verticalPosition: 'bottom' });
    });
    this.assistantChanges.batch$.pipe(takeUntilDestroyed()).subscribe(batch => {
      void this.cull.applyExternalChanges(batch.paths, { lightboxOpen: this.lightboxGroupId() !== null, count: batch.count });
    });
    // Mirror the lightbox photo for `ui_get_context`; no lightbox, or leaving the page, means none.
    effect(() => {
      this.journal.darkroomFocus.set(this.lightboxGroup()?.photos[this.effectiveLightboxIndex()]?.path ?? null);
    });
    inject(DestroyRef).onDestroy(() => this.journal.darkroomFocus.set(null));
    // The auto-cull confirm is a custom modal MatDialog cannot see; the lightbox is the page's working surface and is not one.
    const pageContext = this.pageContext;
    effect(onCleanup => {
      if (this.cull.autoCullPreview()) onCleanup(pageContext.registerOverlay('dialog'));
    });
    // A photo an assistant moved or deleted can vanish from the group the darkroom is showing.
    effect(() => {
      const group = this.lightboxGroup();
      if (group === null) return;
      untracked(() => {
        if (group.photos.length === 0) this.lightboxGroupId.set(null);
        else if (this.effectiveLightboxIndex() >= group.photos.length) this.lightboxIndex.set(group.photos.length - 1);
      });
    });
    this.coarsePointer.setup();
    inject(DestroyRef).onDestroy(
      inject(ViewActionRegistry).register('ui_show_culling_group', args => this.showGroupForAgent(args)),
    );
    this.cull.scopeAlbum.set(qp.get('album'));
    this.cull.scopeFrom.set(qp.get('from'));
    this.cull.scopeTo.set(qp.get('to'));
    this.cull.scopeScene.set(qp.get('scene'));
    // The URL tells the truth about the scope: any change (a date range, a plan's own window, a failed
    // re-plan restoring the previous one) is written back, the other params (group_by) kept.
    effect(() => {
      const album = this.cull.scopeAlbum();
      const from = this.cull.scopeFrom();
      const to = this.cull.scopeTo();
      const scene = this.cull.scopeScene();
      if (!this.stacksMode() && !this.pageNavigating) untracked(() => this.mirrorScopeToUrl(album, from, to, scene));
    });
    effect(() => {
      if (this.sceneCulled()) untracked(() => { void this.advanceToNextScene(); });
    });
    const gb = qp.get('group_by');
    // Validated against the shared list, not a repeated literal union: the
    // hand-written one silently dropped every granularity added after it.
    if (gb && (GROUP_BY_VALUES as readonly string[]).includes(gb)) this.cull.groupBy.set(gb as GroupBy);
    // A held plan wins over the URL-driven feed: the effect below enters it with its own scope and granularity.
    if (this.stacksMode() || !this.planService.pin()) void this.cull.loadGroups();
    effect(() => {
      const pin = this.planService.pin();
      if (pin && !this.stacksMode() && !this.pageNavigating) untracked(() => { void this.followPin(pin); });
    });
    if (!this.stacksMode()) {
      this.loadCullingAuxiliaryState();
    }
    // Keep the keyboard selection in bounds as groups load / get hidden, preserving
    // the identity of the highlighted group when an earlier one drops out of the list.
    let previousVisibleKeys: string[] = [];
    effect(() => {
      const groups = this.visibleGroups();
      const count = groups.length;
      if (count === 0) { previousVisibleKeys = []; return; }
      const idx = this.selectedGroupIndex();
      const currentKeys = groups.map(g => this.cull.groupKey(g));
      const groupsChanged = currentKeys.length !== previousVisibleKeys.length
        || currentKeys.some((k, i) => k !== previousVisibleKeys[i]);
      if (groupsChanged && previousVisibleKeys[idx] !== undefined) {
        const newIdx = currentKeys.indexOf(previousVisibleKeys[idx]);
        if (newIdx >= 0 && newIdx !== idx) {
          previousVisibleKeys = currentKeys;
          this.selectedGroupIndex.set(newIdx);
          return;
        }
      }
      previousVisibleKeys = currentKeys;
      const clamped = Math.min(idx, count - 1);
      if (clamped !== idx) this.selectedGroupIndex.set(clamped);
    });
    // Scroll the keyboard-selected group into view (mirrors gallery.focusCard).
    effect(() => {
      if (this.lightboxGroup()) return;
      const idx = this.selectedGroupIndex();
      const pIdx = this.selectedPhotoIndex();
      queueMicrotask(() => {
        document.querySelector(`[data-gidx="${idx}"]`)?.scrollIntoView({ block: 'nearest' });
        document.querySelector(`[data-gidx="${idx}"] [data-pidx="${pIdx}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
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
      if (this.cull.autoCullPreview()) this.autoCullDialog()?.nativeElement.focus();
    });
    effect(onCleanup => {
      const bar = this.cullBar()?.nativeElement;
      if (!bar || typeof ResizeObserver === 'undefined') { untracked(() => this.barHeight.set(0)); return; }
      const observer = new ResizeObserver(entries => {
        const entry = entries[entries.length - 1];
        this.barHeight.set(Math.ceil(entry?.borderBoxSize?.[0]?.blockSize ?? bar.getBoundingClientRect().height));
      });
      observer.observe(bar);
      onCleanup(() => observer.disconnect());
    });
    // Project the toolbar into the global header on lg+ (the page renders it in
    // its own bottom bar on small screens — see the #cullToolbar template).
    effect(() => {
      const tpl = this.cullToolbar();
      if (tpl) this.headerSlot.set(tpl);
    });
    this.renditions.connect();
  }


  ngOnDestroy(): void {
    this.pageAlive = false; this.pageEpoch++; this.secondaryEditor?.close();
    this.pageHelp.setDescription(null);
    this.coarsePointer.cleanup();
    this.cull.clearAllPassTimers();
    this.stopDetectionPolling();
    this.renditions.dispose();
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    }
    const tpl = this.cullToolbar();
    if (tpl) this.headerSlot.clear(tpl);
  }

  /** Enter the assistant's plan when the pin is a new one, then land on the group it asked for. */
  private async followPin(pin: CullPlanPin): Promise<void> {
    if (this.stacksMode()) return;
    if (this.cull.planDigest() !== pin.digest) {
      this.selectedGroupIndex.set(0);
      if (await this.cull.enterPlan(pin) !== 'landed') return;
    }
    if (pin.focusNumber !== undefined) await this.focusPlanGroup(pin.focusNumber);
  }

  /** Move the keyboard selection onto plan group `number`, paging more groups in if it is not shown yet. */
  private async focusPlanGroup(number: number): Promise<void> {
    const find = () => this.cull.groups().find(g => g.plan?.number === number);
    while (!find() && this.cull.hasMore()) {
      const before = this.cull.currentPage();
      await this.cull.loadMore();
      if (this.cull.currentPage() === before) break;
    }
    const group = find();
    if (!group) return;
    const index = this.visibleGroups().findIndex(g => this.cull.groupKey(g) === this.cull.groupKey(group));
    if (index >= 0) this.selectedGroupIndex.set(index);
  }

  /** Leave the assistant's plan for the manual feed. */
  protected exitPlan(): void {
    this.selectedGroupIndex.set(0);
    this.cull.resetForReload();
  }

  /** Clear the scene/album scope and return to the full unreviewed feed. */
  protected exitScope(): void {
    this.cull.scopeAlbum.set(null);
    this.cull.scopeFrom.set(null);
    this.cull.scopeTo.set(null);
    this.cull.scopeScene.set(null);
    void this.router.navigate(['/culling']);
    this.cull.resetForReload();
  }

  /** Non-smart albums for the scope cascade's first level (best-effort). */
  private async loadAlbums(): Promise<void> {
    try {
      this.cull.albums.set(await firstValueFrom(this.albumService.listNonSmart()));
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
    this.enterScope(album, from, to, scene, {
      queryParams: { album: album ?? null, from: from ?? null, to: to ?? null, scene: scene ?? null },
      queryParamsHandling: 'merge',
    });
  }

  /** Every scope change is a push navigation; the feed, its decisions and its cooldowns start over. */
  private enterScope(album: string | null, from: string | null, to: string | null, scene: string | null, navigation: NavigationExtras): void {
    this.cull.resetProfileSuggestion();
    this.cull.scopeAlbum.set(album);
    this.cull.scopeFrom.set(from);
    this.cull.scopeTo.set(to);
    this.cull.scopeScene.set(scene);
    void this.router.navigate(['/culling'], navigation);
    this.selectedGroupIndex.set(0);
    this.cull.resetForReload();
  }

  private advancingScene = false;

  /** Open the next scene in /scenes order with the URL /scenes builds, or return to /scenes after the last one. */
  private async advanceToNextScene(): Promise<void> {
    const album = this.cull.scopeAlbum();
    const to = this.cull.scopeTo();
    if (this.advancingScene || to === null || !this.canEditPage()) return;
    this.advancingScene = true;
    const epoch = this.pageEpoch;
    const scope = () => [this.cull.scopeAlbum(), this.cull.scopeFrom(), this.cull.scopeTo(), this.cull.scopeScene()].join('\n');
    const culledScope = scope();
    const unchanged = () => epoch === this.pageEpoch && this.canEditPage() && scope() === culledScope && this.sceneCulled();
    try {
      const next = await this.nextSceneAfter(album, to);
      if (!unchanged()) return;
      if (next === null) {
        this.snackBar.open(this.i18n.t(I18N.culling.last_scene), '', { duration: 3000 });
        void this.router.navigate(['/scenes'], { queryParams: { album } });
        return;
      }
      const params = sceneCullParams(next, album);
      if (this.lightboxGroupId() !== null) this.closeLightbox();
      this.enterScope(album, next.start, next.end, params.scene, { queryParams: params });
      this.snackBar.open(this.i18n.t(I18N.culling.next_scene, { scene: params.scene }), '', { duration: 3000 });
    } catch {
      if (unchanged()) this.snackBar.open(this.i18n.t(I18N.scenes.load_error), '', { duration: 3000 });
    } finally {
      this.advancingScene = false;
    }
  }

  /**
   * The first scene of /scenes (same album, same story order) ending after the culled window.
   * Not "starting after": /scenes leaves rejected photos out and re-cuts its scenes once they are
   * gone, so what remains of the culled scene can merge into the next, and that scene must not be skipped.
   */
  private async nextSceneAfter(album: string | null, to: string): Promise<SceneSummary | null> {
    for (let page = 1, pages = 1; page <= pages; page++) {
      const data = await firstValueFrom(this.api.get<{ scenes: SceneSummary[]; total_pages: number }>(
        '/scenes', { page, per_page: 100, summary: true, ...(album ? { album_id: album } : {}) },
      ));
      const next = data.scenes.find(scene => scene.end !== null && scene.end > to);
      if (next) return next;
      pages = data.total_pages;
    }
    return null;
  }

  /** Write the scope into the query string unless it already says so (applyScope's own navigation lands first). */
  private mirrorScopeToUrl(album: string | null, from: string | null, to: string | null, scene: string | null): void {
    const current = this.router.parseUrl(this.router.url).queryParams;
    if ((current['album'] ?? null) === album && (current['from'] ?? null) === from
      && (current['to'] ?? null) === to && (current['scene'] ?? null) === scene) return;
    void this.router.navigate([], {
      queryParams: { album, from, to, scene },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  protected onDatePreset(id: CullDatePresetId): void {
    const { from, to } = presetRange(id, new Date());
    this.onDateRange(from, to);
  }

  /** The picker fires with the start alone while the user is mid-selection: apply only a complete range. */
  protected onCustomRangeEnd(start: Date | null, end: Date | null): void {
    if (start && end) this.onDateRange(toIsoDateString(start), toIsoDateString(end));
  }

  /** In plan mode the old plan stays on screen until the re-plan lands, so the selection must not jump early. */
  protected onDateRange(from: string | null, to: string | null): void {
    this.cull.setDateRange(from, to);
    if (!this.cull.planActive()) this.selectedGroupIndex.set(0);
  }

  /** A window picked on the date button survives an album pick; only a scene's own window (or All dates) drops it. */
  private currentWindow(): [string | null, string | null] {
    return this.cull.scopeScene() ? [null, null] : [this.cull.scopeFrom(), this.cull.scopeTo()];
  }

  protected scopeWholeLibrary(): void {
    this.applyScope(null, ...this.currentWindow(), null);
  }

  protected scopeAlbumWhole(): void {
    const id = this.expandedAlbumId();
    if (id === null) return;
    this.applyScope(id.toString(), ...this.currentWindow(), null);
  }

  protected scopeAlbumScene(scene: SceneSummary): void {
    const id = this.expandedAlbumId();
    if (id === null) return;
    this.applyScope(id.toString(), scene.start, scene.end, this.sceneDate.transform(scene.start));
  }

  protected onThresholdChange(value: number): void {
    this.cull.similarityThreshold.set(value);
    this.cull.profileChosen.set(true);
    this.cull.clearProfileSelection();
    this.cull.resetForReload();
  }

  /** Stores the value; in plan mode the plan is recomputed once the slider settles, else the preset label goes and the keepers are re-derived. */
  protected onStrictnessChange(value: number): void {
    this.cull.setStrictness(value);
    this.cull.profileChosen.set(true);
    if (this.cull.planActive()) {
      // The plan keeps its preset: the strictness overrides the preset's own, the preset's other knobs stay.
      this.cull.scheduleReplan();
    } else {
      this.cull.clearProfileSelection();
      this.cull.reselectFromStrictness();
    }
  }

  // --- Genre culling profiles and auto-cull: the state and requests live in CullingStore ---

  /** Apply the previewed auto-cull, then reset the keyboard selection and reload the feed. */
  protected confirmAutoCull(): Promise<void> {
    return this.cull.confirmAutoCull(() => {
      this.selectedGroupIndex.set(0);
      this.cull.resetForReload();
    });
  }

  /** Trash files while retaining the decisions used to train My Taste. */
  protected async openTrashRejects(): Promise<void> {
    if (this.trashOpening || this.dialog.openDialogs.length || !this.auth.isEdition()
      || !this.store.config()?.cull?.trash_available) return;
    const owner = this.auth.identity();
    const url = this.router.url;
    const navigation = this.trashNavigation;
    this.trashOpening = true;
    try {
      const { CullDialogComponent } = await import('./cull-dialog.component');
      if (this.destroyRef.destroyed || owner !== this.auth.identity() || !this.auth.isEdition()
        || url !== this.router.url || navigation !== this.trashNavigation
        || !this.store.config()?.cull?.trash_available || this.dialog.openDialogs.length) return;
      this.dialog.open(CullDialogComponent, {
        closeOnNavigation: false,
        width: '48rem',
        maxWidth: '95vw',
        data: { paths: [], filters: ALL_REJECTS_SCOPE, trashAvailable: true, action: 'trash_rejects', allRejects: true },
      });
    } finally {
      this.trashOpening = false;
    }
  }

  protected onExcludeRejectedChange(value: boolean): void {
    this.cull.excludeRejected.set(value);
    this.cull.resetForReload();
  }

  protected onCategoryFilterChange(value: string): void {
    this.categoryFilter.set(value);
    localStorage.setItem(CULL_CATEGORY_KEY, value);
    this.selectedGroupIndex.set(0);
  }

  protected onSortChange(value: string): void {
    this.cull.sortMode.set(value);
    localStorage.setItem(CULL_SORT_KEY, value);
    this.selectedGroupIndex.set(0);
    this.cull.resetForReload();
  }

  /** Flip the active sort. Writes an explicit direction rather than a "reversed"
   *  flag, so switching mode afterwards keeps the direction the user asked for. */
  protected toggleSortDirection(): void {
    const next = this.sortAscending() ? 'desc' : 'asc';
    this.cull.sortDirection.set(next);
    localStorage.setItem(CULL_SORT_DIR_KEY, next);
    this.selectedGroupIndex.set(0);
    this.cull.resetForReload();
  }

  /** Switch the feed granularity (all | burst | similar | scene); reloads from page 1. */
  protected onGroupByChange(value: GroupBy): void {
    if (value === this.cull.groupBy()) return;
    this.cull.groupBy.set(value);
    localStorage.setItem(CULL_GROUP_BY_KEY, value);
    this.selectedGroupIndex.set(0);
    void this.router.navigate([], { queryParams: { group_by: value }, queryParamsHandling: 'merge' });
    this.cull.resetForReload();
  }

  protected onScrollReached(): void {
    if (this.cull.hasMore() && !this.cull.loadingMore()) {
      this.cull.loadMore();
    }
  }

  protected openDetail(event: Event, path: string): void {
    event.stopPropagation();
    this.router.navigate(['/photo'], { queryParams: { path }, state: { photoOrigin: 'in-app' } });
  }

  /** Open Comparison scoped to a group's category so its weights can be tuned. */
  protected tuneCategory(category: string): void {
    this.compareFilters.selectedCategory.set(category);
    void this.router.navigate(['/compare']);
  }

  /** `ui_show_culling_group`: open the lightbox on the group identified by (type, group_id), paging in more groups if needed. */
  private async showGroupForAgent(args: Record<string, unknown>): Promise<unknown> {
    const current = this.pageSession();
    if (this.stacksMode()) throw new UiToolError('stack_mode_active', 'Suggested stacks is active.');
    if (!current()) throw new UiToolError('no_active_view', 'The darkroom session changed.');
    const type = args['type'];
    const groupId = args['group_id'];
    const find = () => this.cull.groups().find(g => g.type === type && g.group_id === groupId);
    const deadline = Date.now() + 10_000;
    // Wait out a feed or scroll load already in flight, then page in until found; a page that fails
    // does not advance, so stop there rather than re-request it (each attempt raises a snackbar).
    while ((this.cull.loading() || this.cull.loadingMore()) && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    while (!find() && this.cull.hasMore() && Date.now() < deadline) {
      const before = this.cull.currentPage();
      await this.cull.loadMore();
      if (this.cull.currentPage() === before) break;
    }
    if (this.stacksMode()) throw new UiToolError('stack_mode_active', 'Suggested stacks is active.');
    if (!current()) throw new UiToolError('no_active_view', 'The darkroom session changed.');
    const group = find();
    if (!group) throw new UiToolError('not_found', `No ${String(type)} group ${String(groupId)} in the darkroom's current scope.`);
    this.openLightbox(group, 0);
    return { type: group.type, group_id: group.group_id, photo_count: group.photos?.length ?? null };
  }

  // --- Lightbox handlers ---

  protected openLightbox(group: CullingGroup, index: number): void {
    this.comparisonPaths.set([]); this.comparisonSlotIndex.set(0);
    this.renditions.resetEvidence();
    this.paneFrames.set(new Map()); // never inherit another group's framing
    this.renditions.selectCullStyle('');  // each darkroom session starts on the flat Original
    this.lightboxGroupId.set(this.cull.groupKey(group));
    this.lightboxIndex.set(index);
    if (this.compareMode() !== 'single') {
      const focusedPath = group.photos[index]?.path;
      const paths = this.compareFrames().map(photo => photo.path);
      this.comparisonPaths.set(paths);
      this.comparisonSlotIndex.set(Math.max(0, focusedPath ? paths.indexOf(focusedPath) : 0));
    }
    const gi = this.visibleGroups().findIndex(g => this.cull.groupKey(g) === this.cull.groupKey(group));
    if (gi >= 0) this.selectedGroupIndex.set(gi);
    if (!this.stacksMode()) void this.loadCloseupsForGroup(group);
  }

  /** Jump the darkroom's main view to a group photo (subject-strip click). */
  protected focusPhotoInLightbox(index: number): void {
    const group = this.lightboxGroup();
    if (!group?.photos.length || !this.canEditPage()) return;
    const target = this.clampIndex(index, group.photos.length);
    if (this.compareMode() !== 'single') {
      this.comparisonPaths.set(assignComparisonSlot(this.compareFrames().map(photo => photo.path), this.comparisonSlot(), group.photos[target].path));
    }
    this.lightboxIndex.set(target);
  }

  protected selectComparisonSlot(slot: number): void {
    const frames = this.compareFrames();
    const photo = frames[slot];
    const group = this.lightboxGroup();
    if (!photo || !group || !this.canEditPage()) return;
    this.comparisonPaths.set(frames.map(frame => frame.path));
    this.comparisonSlotIndex.set(slot);
    this.lightboxIndex.set(group.photos.findIndex(frame => frame.path === photo.path));
  }

  /**
   * Keydown shield for everything inside the darkroom.
   *
   * The page's own cull shortcuts must not fire behind the open darkroom, so
   * every inner region stops keys from reaching the document — which also
   * stopped the Escape that closes it, from any control the user was focused
   * on. Escape is therefore acted on here, on the shield itself, exactly the way
   * the auto-cull dialog handles its own.
   */
  protected onDarkroomKeydown(event: KeyboardEvent): void {
    event.stopPropagation();
    if (!this.stacksMode() && event.key === 'Enter' && !isTypingContext(event) && !isControlActivation(event)) {
      this.continueCullingGroup(event);
      return;
    }
    if (!this.stacksMode() && event.key === ' ' && !isTypingContext(event)
      && (!isControlActivation(event) || !!(event.target as HTMLElement | null)?.closest('[data-stack-filmstrip]'))) {
      this.onSpace(event);
      return;
    }
    if (this.stacksMode()) {
      if (this.shortcutsBlocked(event)) return;
      if (event.key === 'Enter' && isControlActivation(event)) return;
      if (event.key === ' ' && !isControlActivation(event) && !isTypingContext(event)) event.preventDefault();
      if (event.key === 's' || event.key === 'S' || event.key === 'Enter') this.onStackKey(event);
      else if (event.key === 'x' || event.key === 'X') this.onSkipSuggestionKey(event);
      else if (event.key.toLowerCase() === 'r') this.onRejectStackKey(event);
      else if (event.key === 'ArrowLeft') this.onArrowLeft(event);
      else if (event.key === 'ArrowRight') this.onArrowRight(event);
      else if (event.key.toLowerCase() === 'z') this.onZoomToggle(event);
      else if (event.key.toLowerCase() === 'p') this.onPeakingKey(event);
      else if (event.key.toLowerCase() === 'g') this.onGridKey(event);
      else if (event.key.toLowerCase() === 'f') this.onFullscreenToggle(event);
    } else if (!isTypingContext(event) && !event.ctrlKey && !event.metaKey && !event.altKey
      && !(event.target as HTMLElement | null)?.closest('[role="slider"], [role="radiogroup"], [data-darkroom-tools][open]')) {
      if (event.key === 'ArrowLeft') this.onArrowLeft(event);
      else if (event.key === 'ArrowRight') this.onArrowRight(event);
      else if (event.key === 'ArrowUp') this.onArrowUp(event);
      else if (event.key === 'ArrowDown') this.onArrowDown(event);
      else if (event.key === 's' || event.key === 'S') this.onStackKey(event);
      else if (event.key.toLowerCase() === 'z') this.onZoomToggle(event);
      else if (event.key.toLowerCase() === 'p') this.onPeakingKey(event);
      else if (event.key.toLowerCase() === 'g') this.onGridKey(event);
      else if (event.key.toLowerCase() === 'f') this.onFullscreenToggle(event);
    }
    if (event.key === 'Escape') this.closeLightbox();
  }

  private groupRow(key: string): HTMLElement | undefined {
    return Array.from(this.element()?.nativeElement.querySelectorAll<HTMLElement>('[data-culling-group-key]') ?? [])
      .find(element => element.dataset['cullingGroupKey'] === key);
  }

  protected confirmGroupFromRow(group: CullingGroup, event: Event): void {
    const origin = event.currentTarget as HTMLElement | null;
    const identity = this.auth.identity();
    const key = this.cull.groupKey(group);
    if (!this.cull.confirmGroup(group)) return;
    setTimeout(() => {
      if (!this.pageAlive || this.pageNavigating || this.lightboxGroup() || this.dialog.openDialogs.length
        || this.auth.identity() !== identity || !this.cull.passingGroups().has(key)
        || document.activeElement !== document.body && document.activeElement !== origin) return;
      const row = this.groupRow(key);
      row?.querySelector<HTMLButtonElement>('[data-culling-cancel]')?.focus();
    });
  }

  protected cancelGroupPass(group: CullingGroup, event: Event, darkroom = false): void {
    const origin = event.currentTarget as HTMLElement | null;
    const overlay = origin?.closest<HTMLElement>('[role="dialog"]');
    const identity = this.auth.identity();
    const key = this.cull.groupKey(group);
    this.cull.cancelPass(group);
    setTimeout(() => {
      if (!this.pageAlive || this.pageNavigating || this.auth.identity() !== identity || this.dialog.openDialogs.length
        || document.activeElement !== document.body && document.activeElement !== origin) return;
      if (darkroom) {
        if (this.lightboxGroupId() !== key) return;
        overlay?.querySelector<HTMLButtonElement>('[data-darkroom-confirm]:not(:disabled)')?.focus();
      } else {
        if (this.lightboxGroup()) return;
        const row = this.groupRow(key);
        (row?.querySelector<HTMLButtonElement>('[data-culling-confirm]:not(:disabled)') ?? row)?.focus();
      }
    });
  }

  protected closeLightbox(): void {
    this.renditions.resetEvidence();
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    }
    // Leave the page focused on the group just reviewed in the darkroom, so its
    // keep/reject choices (already written to the shared selectionsMap) are the
    // ones highlighted and scrolled into view on exit.
    const group = this.lightboxGroup();
    if (group) {
      const gi = this.visibleGroups().findIndex(g => this.cull.groupKey(g) === this.cull.groupKey(group));
      if (gi >= 0) this.selectedGroupIndex.set(gi);
    }
    this.lightboxGroupId.set(null);
    const identity = this.auth.identity();
    const groupKey = group ? this.cull.groupKey(group) : null;
    if (groupKey) setTimeout(() => {
      if (!this.pageAlive || this.pageNavigating || this.lightboxGroup() || this.dialog.openDialogs.length
        || this.auth.identity() !== identity) return;
      const row = this.groupRow(groupKey);
      (row?.querySelector<HTMLElement>('[data-culling-cancel]') ?? row?.querySelector<HTMLElement>('[data-culling-open]') ?? row)?.focus();
    });
  }

  /**
   * Lazily fetch detected faces for the focused group in a single batch call,
   * enriched with per-face eyes-open/expression/confidence/is_blink so the
   * lightbox can tile face crops with per-face badges. Results are cached in
   * faceMap; already-loaded paths are skipped.
   */
  private async loadFacesForGroup(group: CullingGroup): Promise<void> {
    const current = this.pageSession();
    if (this.stacksMode() || !current()) return;
    const missing = group.photos.filter(p => !this.faceMap().has(p.path));
    if (missing.length === 0) return;
    try {
      const data = await firstValueFrom(
        this.api.post<{ faces_by_path: Record<string, CullingFace[]>; thresholds?: FaceThresholds }>(
          '/culling-group/faces', { paths: missing.map(p => p.path), profile: this.cull.selectedProfile() || undefined },
        ),
      );
      if (!current()) return;
      if (data.thresholds) this.faceThresholds.set(data.thresholds);
      const byPath = data.faces_by_path ?? {};
      this.faceMap.update(m => {
        const next = new Map(m);
        for (const photo of missing) next.set(photo.path, byPath[photo.path] ?? []);
        return next;
      });
    } catch {
      if (!current()) return;
      // Best-effort: record empty results so we don't refetch on every open.
      this.faceMap.update(m => {
        const next = new Map(m);
        for (const photo of missing) next.set(photo.path, []);
        return next;
      });
    }
  }

  /**
   * Load the close-up strips for a group: faces first, then — only when the
   * group has no faces — the subject close-ups, so a wildlife/macro/product
   * burst gets a subject strip while portrait groups keep the face strip and
   * face-heavy groups never pay for subject crops.
   *
   * The key subjects are fetched for every group, face or not: unlike the
   * crops they are not a strip but the zoom target, and a wildlife burst wants
   * one as much as a portrait does.
   */
  private async loadCloseupsForGroup(group: CullingGroup): Promise<void> {
    const current = this.pageSession();
    if (this.stacksMode() || !current()) return;
    await this.loadFacesForGroup(group);
    if (!current()) return;
    await this.loadKeySubjectsForGroup(group);
    if (!current()) return;
    const hasFaces = group.photos.some(p => (this.faceMap().get(p.path)?.length ?? 0) > 0);
    if (!hasFaces) await this.loadSubjectsForGroup(group);
  }

  /**
   * Resolve who / what each frame of the focused group is about, in one batch
   * call rather than a per-photo fan-out. The answer gives the darkroom its
   * zoom target (the pane centres on `center` past the fit scale) and tells the
   * face strip which crop to badge. Cached in keySubjectMap; already-resolved
   * paths are skipped, and a failure records unresolved entries so a broken
   * call is not retried on every open.
   */
  private async loadKeySubjectsForGroup(group: CullingGroup): Promise<void> {
    const current = this.pageSession();
    if (this.stacksMode() || !current()) return;
    const missing = group.photos.filter(p => !this.keySubjectMap().has(p.path));
    if (missing.length === 0) return;
    try {
      const data = await firstValueFrom(
        this.api.post<{ key_subjects_by_path: Record<string, KeySubject> }>(
          '/photos/key_subjects', { paths: missing.map(p => p.path) },
        ),
      );
      if (!current()) return;
      this.applyKeySubjects(missing, data.key_subjects_by_path ?? {});
    } catch {
      if (current()) this.applyKeySubjects(missing);
    }
  }

  /** An unresolved key subject: nothing to zoom at, nothing to badge. */
  private emptyKeySubject(path: string): KeySubject {
    return {
      path, kind: 'none', coordinate_space: KEY_SUBJECT_COORDINATE_SPACE,
      image_width: null, image_height: null, bbox: null, center: null,
      area_ratio: null, centrality: null, score: null,
      face_id: null, face_index: null, person_id: null, person_name: null,
      subject_sharpness: null, subject_prominence: null,
      subject_placement: null, bg_separation: null,
    };
  }

  /** Merge resolved key subjects, filling unreturned paths with an empty entry. */
  private applyKeySubjects(missing: CullingPhoto[], byPath: Record<string, KeySubject> = {}): void {
    this.keySubjectMap.update(m => {
      const next = new Map(m);
      for (const photo of missing) {
        next.set(photo.path, byPath[photo.path] ?? this.emptyKeySubject(photo.path));
      }
      return next;
    });
  }

  /**
   * Lazily fetch subject close-up crops for the focused group in one batch call.
   * Each crop is the stored thumbnail cut to the persisted BiRefNet subject box
   * with a group-normalized sharpness score. Cached in subjectMap; already-loaded
   * paths are skipped. Degrades silently: photos without a subject box just don't
   * appear in the strip.
   */
  private async loadSubjectsForGroup(group: CullingGroup): Promise<void> {
    const current = this.pageSession();
    if (this.stacksMode() || !current()) return;
    const missing = group.photos.filter(p => !this.subjectMap().has(p.path));
    if (missing.length === 0) return;
    try {
      const data = await firstValueFrom(
        this.api.post<{ subjects_by_path: Record<string, CullingSubject> }>(
          '/culling-group/subjects', { paths: missing.map(p => p.path) },
        ),
      );
      if (!current()) return;
      this.applySubjects(missing, data.subjects_by_path ?? {});
    } catch {
      if (current()) this.applySubjects(missing);
    }
  }

  /** A subject entry with no crop, so a photo without a subject box stays out of the strip. */
  private emptySubject(path: string): CullingSubject {
    return { path, has_subject: false, crop: null,
      subject_sharpness: null, subject_prominence: null,
      crop_sharpness: null, crop_sharpness_score: null };
  }

  /** Merge fetched subject crops into subjectMap, filling unreturned paths with an empty entry. */
  private applySubjects(missing: CullingPhoto[], byPath: Record<string, CullingSubject> = {}): void {
    this.subjectMap.update(m => {
      const next = new Map(m);
      for (const photo of missing) {
        next.set(photo.path, byPath[photo.path] ?? this.emptySubject(photo.path));
      }
      return next;
    });
  }

  private clampIndex(value: number, max: number): number {
    if (max <= 0) return 0;
    return Math.max(0, Math.min(max - 1, value));
  }

  /** Step the active darkroom frame for arrow keys and committed swipes. */
  private stepLightbox(group: CullingGroup, delta: number): void {
    this.focusPhotoInLightbox(this.clampIndex(this.effectiveLightboxIndex() + delta, group.photos.length));
  }

  private shortcutsBlocked(event: Event): boolean {
    const key = event as KeyboardEvent;
    if (event.defaultPrevented || this.dialog.openDialogs.length > 0 || isTypingContext(event)
      || key.ctrlKey || key.metaKey || key.altKey) return true;
    if (!this.stacksMode()) return false;
    return this.pageNavigating || this.cull.stackBusy() || isTypingContext(event) || key.shiftKey || key.ctrlKey || key.metaKey || key.altKey
      || key.isComposing || key.keyCode === 229 || key.repeat || this.pageContext.overlays().length > 0
      || !!(event.target instanceof HTMLElement ? event.target : null)?.closest('[role="slider"], [role="radiogroup"]');
  }

  @HostListener('document:keydown.arrowleft', ['$event'])
  protected onArrowLeft(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    const group = this.lightboxGroup();
    if (group) {
      event.preventDefault();
      this.stepLightbox(group, -1);
      return;
    }
    this.stepPhotoCursor(event, -1);
  }

  @HostListener('document:keydown.arrowright', ['$event'])
  protected onArrowRight(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    const group = this.lightboxGroup();
    if (group) {
      event.preventDefault();
      this.stepLightbox(group, 1);
      return;
    }
    this.stepPhotoCursor(event, 1);
  }

  /** List view: move the photo cursor within the selected group, stopping at its edges. */
  private stepPhotoCursor(event: Event, delta: number): void {
    if (isTypingContext(event)) return;
    const group = this.visibleGroups()[this.selectedGroupIndex()];
    if (!group) return;
    event.preventDefault();
    this.selectedPhotoIndex.update(i => this.clampIndex(i + delta, group.photos.length));
  }

  /** Z toggles the darkroom zoom (fit ↔ 2×) when open, else the grid hover loupe.
   *  In single view the pane does it, so the key subject is what lands under the
   *  loupe; the compare grid has no single frame to aim at and stays centred. */
  @HostListener('document:keydown.z', ['$event'])
  protected onZoomToggle(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    if (isTypingContext(event)) return;
    if (!this.lightboxGroup()) {
      this.loupeActive.set(!this.loupeActive());
      return;
    }
    event.preventDefault();
    const pane = this.compareMode() === 'single' ? this.zoomPane() : undefined;
    if (pane) {
      pane.toggleZoom();
      return;
    }
    this.onDarkroomZoom(this.zoom().scale > SyncedZoomComponent.MIN_SCALE
      ? FIT_ZOOM
      : { scale: SyncedZoomComponent.TOGGLE_SCALE, tx: 0, ty: 0 });
  }

  /** P toggles focus peaking over the open darkroom's frames. */
  @HostListener('document:keydown.p', ['$event'])
  protected onPeakingKey(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    if (!this.lightboxGroup()) return;
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.togglePeaking();
  }

  /** G cycles the open darkroom's composition grid. */
  @HostListener('document:keydown.g', ['$event'])
  protected onGridKey(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    if (!this.lightboxGroup()) return;
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.cycleGrid();
  }

  /** F toggles true fullscreen on the open darkroom (mirrors the slideshow's F key). */
  @HostListener('document:keydown.f', ['$event'])
  protected onFullscreenToggle(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
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
    const photo = group.photos[this.effectiveLightboxIndex()];
    if (!photo) return;
    this.cull.setPhotoKept(group, photo.path, keep);
  }

  /**
   * Commit a swipe on the focused frame: exactly the state ↑ / ↓ write, then
   * exactly the step → takes.
   *
   * The Undo is the part the keyboard does not need. A mis-keyed ↑ is undone by
   * pressing ↓, but a mis-flicked thumb has already moved on to the next frame
   * and has no opposite gesture to reach for, so the decision *and* the frame it
   * was made on are both restored from the snackbar.
   */
  protected onSwipeDecision(group: CullingGroup, keep: boolean): void {
    if (this.stacksMode()) return;
    const photo = group.photos[this.effectiveLightboxIndex()];
    if (!photo) return;
    const previousKept = new Set(this.cull.selectionsMap().get(this.cull.groupKey(group)) ?? []);
    const previousIndex = this.effectiveLightboxIndex();
    this.setCurrentLightboxPhotoKept(group, keep);
    this.stepLightbox(group, 1);
    this.undoService.register({
      labelKey: keep ? I18N.culling.swipe.kept : I18N.culling.swipe.rejected,
      labelParams: { filename: photo.filename },
      undo: () => {
        this.cull.restoreSelection(group, previousKept);
        this.lightboxIndex.set(previousIndex);
        return Promise.resolve();
      },
    });
  }

  /** S stacks the open group with the focused frame as cover; culling decisions are untouched.
   *  Bracket and panorama sets are left out, as Suggested stacks leaves them out: their frames
   *  are meant to be merged, and the gallery already folds them behind one frame. */
  @HostListener('document:keydown.s', ['$event'])
  protected onStackKey(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    const group = this.lightboxGroup() ?? (this.stacksMode() ? this.visibleGroups()[this.selectedGroupIndex()] : null);
    if (!group || isTypingContext(event)) return;
    event.preventDefault();
    void this.stackGroup(group);
  }

  protected async stackGroup(group: CullingGroup): Promise<void> {
    const cover = this.stacksMode() && this.lightboxGroupId() !== this.cull.groupKey(group) ? group.best_path : group.photos[this.effectiveLightboxIndex()]?.path;
    if (this.stacksMode()) {
      if (cover && await this.cull.stackSuggestion(group, cover)) this.afterSuggestion(group);
      return;
    }
    if (!cover || !canStackGroup(group) || !this.auth.isEdition() || this.stacking) return;
    this.stacking = true;
    try {
      await this.stackActions.create(group.photos.map(p => p.path), cover);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.stacks.stack_failed), '',
                         { duration: 4000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    } finally {
      this.stacking = false;
    }
  }

  private afterSuggestion(group: CullingGroup): void {
    if (this.lightboxGroupId() !== this.cull.groupKey(group)) return;
    const next = this.visibleGroups()[this.selectedGroupIndex()] ?? this.visibleGroups()[0];
    if (next) this.openLightbox(next, 0); else this.closeLightbox();
  }

  @HostListener('document:keydown.r', ['$event'])
  protected onRejectStackKey(event: Event): void {
    if (!this.stacksMode() || this.shortcutsBlocked(event)) return;
    const group = this.lightboxGroup();
    if (!group) return;
    event.preventDefault(); void this.rejectStackPhoto(group);
  }

  protected async rejectStackPhoto(group: CullingGroup): Promise<void> {
    const current = this.pageSession();
    if (!this.stacksMode() || !current() || this.cull.stackBusy() || this.lightboxGroupId() !== this.cull.groupKey(group)) return;
    const index = this.effectiveLightboxIndex(); const path = group.photos[index]?.path;
    if (!path) return;
    if (await this.cull.rejectStackPhoto(group, path) && current() && this.lightboxGroupId() === this.cull.groupKey(group)
      && this.lightboxGroup()?.photos[this.effectiveLightboxIndex()]?.path === path) {
      const next = group.photos.slice(index + 1).find(photo => !this.cull.stackExcluded()[photo.path])
        ?? group.photos.slice(0, index).reverse().find(photo => !this.cull.stackExcluded()[photo.path]);
      if (next) this.focusPhotoInLightbox(group.photos.indexOf(next));
    }
  }

  protected async skipStackSuggestion(group: CullingGroup): Promise<void> {
    if (!this.stacksMode()) return;
    if (await this.cull.skipSuggestion(group)) this.afterSuggestion(group);
  }

  @HostListener('document:keydown.x', ['$event'])
  protected onSkipSuggestionKey(event: Event): void {
    if (!this.stacksMode() || this.shortcutsBlocked(event) || isTypingContext(event)) return;
    const group = this.lightboxGroup() ?? this.visibleGroups()[this.selectedGroupIndex()];
    if (!group) return;
    event.preventDefault();
    void this.skipStackSuggestion(group);
  }

  protected async editSuggestion(group: CullingGroup): Promise<void> {
    if (!this.stacksMode() || this.cull.stackBusy() || !this.auth.isEdition() || this.secondaryEditor || !this.cull.groups().includes(group)) return;
    const current = this.pageSession();
    const { StackDialogComponent } = await import('./stack-dialog.component');
    const { SKIP_SUGGESTION } = await import('./stack-editor-host');
    if (!current() || this.dialog.openDialogs.length || !this.cull.groups().includes(group)) return;
    const focused = this.lightboxGroupId() === this.cull.groupKey(group)
      ? group.photos[this.effectiveLightboxIndex()]?.path : group.photos[this.selectedPhotoIndex()]?.path;
    const onUndone = () => { if (current()) this.cull.restoreStackSuggestion(group); };
    const ref = this.dialog.open(StackDialogComponent, stackDialogConfig({
      paths: group.photos.map(photo => photo.path), reviewDraft: this.cull.reviewDraft(group), activePath: focused, skippable: true, onUndone,
    }));
    this.secondaryEditor = ref;
    const result = await firstValueFrom(ref.afterClosed());
    if (this.secondaryEditor === ref) this.secondaryEditor = null;
    if (!current()) return;
    if (result === SKIP_SUGGESTION) await this.skipStackSuggestion(group);
    else if (result === true && this.cull.completeStackSuggestion(group)) this.afterSuggestion(group);
  }

  /** True when the event originates from a text/slider control we must not hijack. */
  @HostListener('document:keydown.arrowup', ['$event'])
  protected onArrowUp(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    const group = this.lightboxGroup();
    if (group) {
      event.preventDefault();
      if (!this.stacksMode()) this.setCurrentLightboxPhotoKept(group, true);
      return;
    }
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.selectedGroupIndex.update(i => this.clampIndex(i - 1, this.visibleGroups().length));
  }

  @HostListener('document:keydown.arrowdown', ['$event'])
  protected onArrowDown(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    const group = this.lightboxGroup();
    if (group) {
      event.preventDefault();
      if (!this.stacksMode()) this.setCurrentLightboxPhotoKept(group, false);
      return;
    }
    if (isTypingContext(event)) return;
    event.preventDefault();
    this.selectedGroupIndex.update(i => this.clampIndex(i + 1, this.visibleGroups().length));
  }

  @HostListener('document:keydown.enter', ['$event'])
  protected onEnter(event: Event): void {
    if (this.shortcutsBlocked(event) || isTypingContext(event) || isControlActivation(event)) return;
    if (this.lightboxGroup()) {
      if (this.stacksMode()) this.onStackKey(event);
      return;
    }
    const group = this.visibleGroups()[this.selectedGroupIndex()];
    if (!group) return;
    event.preventDefault();
    this.openLightbox(group, 0);
  }

  /** Next visible, not-yet-confirmed group after the given one (for darkroom auto-advance). */
  private nextUnconfirmedGroupAfter(group: CullingGroup): CullingGroup | null {
    const groups = this.visibleGroups();
    const confirmed = this.cull.confirmedGroups();
    const startIdx = groups.findIndex(g => this.cull.groupKey(g) === this.cull.groupKey(group));
    for (let i = startIdx + 1; i < groups.length; i++) {
      if (!confirmed.has(this.cull.groupKey(groups[i]))) return groups[i];
    }
    return null;
  }

  @HostListener('document:keydown.space', ['$event'])
  protected onSpace(event: Event): void {
    if (this.stacksMode()) {
      if (!this.shortcutsBlocked(event) && !isControlActivation(event)) event.preventDefault();
      return;
    }
    if ((event as KeyboardEvent).shiftKey || this.shortcutsBlocked(event) || isTypingContext(event)) return;
    if (!this.lightboxGroup() && isControlActivation(event)) return;
    this.continueCullingGroup(event);
  }

  private confirmGroupFromShortcut(group: CullingGroup): boolean {
    if (this.cull.closedGroupKeys().has(this.cull.groupKey(group)) || !this.auth.isEdition()
      || this.cull.replanning() || this.cull.confirming()) return false;
    if (!(this.cull.selectionsMap().get(this.cull.groupKey(group))?.size)) {
      this.snackBar.open(this.i18n.t(I18N.culling.keep_required), '', { duration: 3000 });
      return false;
    }
    return this.cull.confirmGroup(group);
  }

  protected continueCullingGroup(event: Event): void {
    const key = event as KeyboardEvent;
    if (this.shortcutsBlocked(event) || isTypingContext(event) || key.repeat || key.isComposing || key.keyCode === 229
      || key.ctrlKey || key.altKey || key.metaKey || this.pageNavigating || !this.pageAlive) return;
    const group = this.lightboxGroup();
    if (group) {
      // Darkroom: confirm the open group and jump into the next one.
      event.preventDefault();
      if (!this.confirmGroupFromShortcut(group)) return;
      const next = this.nextUnconfirmedGroupAfter(group);
      if (next) {
        this.openLightbox(next, 0);
        this.lightboxDialog()?.nativeElement.focus();
      } else {
        this.closeLightbox();
      }
      return;
    }
    const selected = this.visibleGroups()[this.selectedGroupIndex()];
    if (!selected) return;
    event.preventDefault();
    if (!this.confirmGroupFromShortcut(selected)) return;
    const next = this.nextUnconfirmedGroupAfter(selected);
    if (next) this.selectedGroupIndex.set(this.visibleGroups().indexOf(next));
    // The old tile remains in the countdown. Do not leave keyboard focus there
    // so the next Space targets a just-confirmed group instead of the new cursor.
    if (event.target instanceof HTMLElement && event.target.closest('[data-culling-image-tile]')) event.target.blur();
  }

  /** List: confirm the selected group and move the selection to the next one. */
  @HostListener('document:keydown.shift.space', ['$event'])
  protected onShiftSpace(event: Event): void {
    if (this.stacksMode()) {
      if (!this.shortcutsBlocked(event) && !isControlActivation(event)) event.preventDefault();
      return;
    }
    if (this.shortcutsBlocked(event)) return;
    if (this.lightboxGroup()) return;
    if (isTypingContext(event) || isControlActivation(event)) return;
    const selected = this.visibleGroups()[this.selectedGroupIndex()];
    if (!selected) return;
    event.preventDefault();
    if (!this.confirmGroupFromShortcut(selected)) return;
    const next = this.nextUnconfirmedGroupAfter(selected);
    if (next) {
      const gi = this.visibleGroups().findIndex(g => this.cull.groupKey(g) === this.cull.groupKey(next));
      if (gi >= 0) this.selectedGroupIndex.set(gi);
    } else {
      this.selectedGroupIndex.update(i => this.clampIndex(i + 1, this.visibleGroups().length));
    }
  }

  @HostListener('document:keydown.escape', ['$event'])
  protected onEscape(event: Event): void {
    if (this.shortcutsBlocked(event)) return;
    if (this.cull.autoCullPreview()) {
      event.preventDefault();
      this.cull.cancelAutoCull();
      return;
    }
    if (this.lightboxGroup()) {
      event.preventDefault();
      this.closeLightbox();
    }
  }

  /**
   * Record what this set really is: not a panorama (no `kind`), or the kind it
   * should have been given.
   *
   * Offered as Undo rather than the 7-second cooldown the confirm uses: the
   * correction only takes effect at the next detection run, so blocking for
   * seven seconds would buy nothing, and the group must stay on screen —
   * a suppressed set is still served here until that run.
   */
  protected async correctSequence(group: CullingGroup, kind?: SequenceKind): Promise<void> {
    const current = this.pageSession();
    if (this.stacksMode() || !current()) return;
    const paths = group.photos.map(p => p.path);
    const previous = new Map(group.photos.map(p => [p.path, p.sequence_override ?? null]));
    try {
      await this.sequenceOverrides.setAsync(paths, kind);
    } catch (error) {
      if (!current()) return;
      const notALadder = isBracketLadderRejection(kind, error);
      this.snackBar.open(
        this.i18n.t(notALadder ? I18N.culling.bracket.not_a_ladder : I18N.culling.panorama.correction_failed),
        '', { duration: 3000, horizontalPosition: 'right', verticalPosition: 'bottom' },
      );
      return;
    }
    if (!current()) return;
    this.cull.patchOverrides(paths, kind ?? 'suppressed');
    this.undoService.register({
      labelKey: I18N.culling.panorama.corrected,
      undo: async () => {
        if (!current()) return;
        await this.restoreOverridesOnServer(previous, current);
        if (current()) this.cull.restoreOverrides(previous);
      },
    });
  }

  /**
   * Put the stored overrides back where `previous` says they were.
   *
   * Clearing alone would not undo a re-labelling, it would delete it: a set the
   * user had already corrected once carries an override before this call, so
   * dropping the row discards that earlier decision — and the detector would
   * then re-apply the very misread they had fixed, while the badge still
   * claimed a correction the server no longer held.
   */
  private async restoreOverridesOnServer(previous: Map<string, string | null>, current = this.pageSession()): Promise<void> {
    if (this.stacksMode() || !current()) return;
    const byValue = new Map<string | null, string[]>();
    for (const [path, value] of previous) {
      const bucket = byValue.get(value);
      if (bucket) bucket.push(path); else byValue.set(value, [path]);
    }
    for (const [value, paths] of byValue) {
      if (!current()) return;
      if (value === null) await this.sequenceOverrides.clearAsync(paths);
      else if (value === SUPPRESSED_OVERRIDE) await this.sequenceOverrides.setAsync(paths);
      else await this.sequenceOverrides.setAsync(paths, value as SequenceKind);
    }
  }

  /** Hand this set back to the detector, dropping the pending correction. */
  protected async clearCorrection(group: CullingGroup): Promise<void> {
    const current = this.pageSession();
    if (this.stacksMode() || !current()) return;
    const paths = group.photos.map(p => p.path);
    // An already-applied correction left the forced set in `photos`; dropping
    // it here only clears the override row, so the re-run banner must be told
    // by hand -- `pendingCorrectionKeys` sees no pending row left to count.
    const hadApplied = group.photos.some(p => p.sequence_override && !p.sequence_override_pending);
    try {
      await this.sequenceOverrides.clearAsync(paths);
    } catch {
      if (!current()) return;
      this.snackBar.open(this.i18n.t(I18N.culling.panorama.correction_failed), '',
                         { duration: 3000, horizontalPosition: 'right', verticalPosition: 'bottom' });
      return;
    }
    if (!current()) return;
    this.cull.patchOverrides(paths, null);
    if (hadApplied) {
      const key = this.cull.groupKey(group);
      this.cull.droppedApplied.update(keys => new Set(keys).add(key));
    }
  }

  /**
   * Spawn the whole-library detection run the pending corrections need.
   *
   * Polls the shared job status rather than assuming success: the run is a
   * background subprocess holding the library lock, and a 409 means another job
   * already holds it.
   */
  protected async rerunDetection(): Promise<void> {
    if (this.stacksMode() || !this.pageSession()() || this.detecting()) return;
    const owner = this.auth.identity();
    const generation = ++this.detectionGeneration;
    // The whole-library start survives cancelled navigation, but never a new owner or stack visit.
    const current = () => this.pageAlive && !this.destroyRef.destroyed && generation === this.detectionGeneration
      && this.auth.identity() === owner && owner === this.pageOwner && this.auth.isEdition() && !this.stacksMode();
    this.detecting.set(true);
    this.detectFailed.set(false);
    this.detectMessage.set('');
    try {
      await firstValueFrom(this.panoramaSettings.redetect());
    } catch (error: unknown) {
      if (!current()) return;
      this.detecting.set(false);
      this.detectFailed.set(true);
      const busy = error instanceof HttpErrorResponse && error.status === 409;
      this.detectMessage.set(busy ? I18N.culling.panorama.rerun_busy : I18N.culling.panorama.rerun_failed);
      return;
    }
    if (!current()) return;
    this.detectMessage.set(I18N.culling.panorama.rerun_running);
    this.detectPollTimer = setInterval(() => void this.pollDetection(), 2000);
  }

  private async pollDetection(): Promise<void> {
    const current = this.pageSession();
    if (this.stacksMode() || !current()) return;
    try {
      const status = await firstValueFrom(
        this.api.get<{ running: boolean; kind: string | null; exit_code: number | null }>(
          '/scan/recompute_status'));
      if (!current() || status.running) return;
      this.stopDetectionPolling();
      const failed = status.exit_code !== 0 && status.exit_code !== null;
      this.detectFailed.set(failed);
      this.detectMessage.set(failed ? I18N.culling.panorama.rerun_failed : I18N.culling.panorama.rerun_done);
      // A completed run has re-applied or dropped every correction the feed
      // held, so the applied-drops this session no longer need a re-run.
      if (!failed) this.cull.droppedApplied.set(new Set());
    } catch {
      if (!current()) return;
      this.stopDetectionPolling();
      this.detectFailed.set(true);
      this.detectMessage.set(I18N.culling.panorama.rerun_failed);
    }
  }

  private stopDetectionPolling(): void {
    this.detectionGeneration++;
    this.detecting.set(false);
    if (this.detectPollTimer !== null) {
      clearInterval(this.detectPollTimer);
      this.detectPollTimer = null;
    }
  }

  protected confirmAllRemaining(): Promise<void> {
    return this.cull.confirmAllRemaining(this.visibleGroups());
  }
}
