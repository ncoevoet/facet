import { Component, inject, signal, computed, effect, OnInit, HostListener, DestroyRef, ElementRef, viewChild, ChangeDetectionStrategy } from '@angular/core';
import { Location } from '@angular/common';
import { ActivatedRoute, Router, NavigationStart } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom, skip, finalize } from 'rxjs';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AssistantChangeBatch, AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { MetricRankComponent } from '../../shared/components/metric-rank/metric-rank.component';
import { Photo, KeeperHint, PhotoSet, normalisePhotoFlags } from '../../shared/models/photo.model';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { PhotoDetailBase } from '../../shared/directives/photo-detail-base.directive';
import { ZoomPanDirective } from '../../shared/directives/zoom-pan.directive';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { CategoryLabelPipe } from '../gallery/photo-tooltip.component';
import { DownloadIconPipe } from '../../shared/pipes/download-icon.pipe';
import { PhotoSetKindIconPipe, PhotoSetKindLabelPipe } from '../../shared/pipes/photo-set-kind.pipe';
import { SEQUENCE_KINDS_KEPT_WHOLE } from '../../shared/pipes/sequence-kind.pipe';
import { EvOffsetPipe } from '../gallery/burst-culling.pipes';
import {
  HISTOGRAM_PANEL_HEIGHT,
} from '../../shared/components/histogram/histogram.component';
import { PhotoMetricsTabsComponent } from '../../shared/components/photo-metrics-tabs/photo-metrics-tabs.component';
import { HistogramMode, isHistogramMode } from '../../shared/utils/histogram';
import { ComparisonCategoryExplainerComponent } from '../comparison/comparison-category-explainer.component';
import { DownloadOption } from '../../core/api/types';
import { downloadAll } from '../../shared/utils/download';
import { GalleryStore } from '../gallery/gallery.store';
import { setScopePatch } from '../gallery/gallery-filters.util';
import * as L from 'leaflet';
import { createLeafletMap } from '../../shared/leaflet';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { isPageShortcutBlocked, isTypingContext } from '../../shared/utils/keyboard';
import { KeyboardMappingService } from '../../core/services/keyboard-mapping.service';
import type { CategoryOverrideResult } from './category-override-dialog.component';
import { StackNavigatorComponent } from './stack-navigator.component';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { PhotoFaceLayerComponent } from './photo-face-layer.component';
import { PersonFaceMenuComponent } from '../persons/person-face-menu.component';
import {
  FaceBoxMode, FACE_BOX_MODE_ICONS, FACE_BOX_MODE_LABELS, nextFaceBoxMode, readFaceBoxMode, writeFaceBoxMode,
} from './face-box-mode';

const SOCIAL_SOURCE_KEYS: Record<string, string> = {
  saliency: I18N.social_export.source.saliency,
  faces: I18N.social_export.source.faces,
  center: I18N.social_export.source.center,
};


@Component({
  selector: 'app-photo-detail',
  imports: [
    StackNavigatorComponent,
    ZoomPanDirective,
    MetricRankComponent,
    PhotoMetricsTabsComponent,
    PhotoFaceLayerComponent,
    PersonFaceMenuComponent,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatMenuModule,
    MatDialogModule,
    MatFormFieldModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    FixedPipe,
    TranslatePipe,
    ThumbnailUrlPipe,
    PersonThumbnailUrlPipe,
    CategoryLabelPipe,
    DownloadIconPipe,
    PhotoSetKindIconPipe,
    PhotoSetKindLabelPipe,
    EvOffsetPipe,
    ComparisonCategoryExplainerComponent,
  ],
  template: `
    @if (photo(); as p) {
      <!-- Header bar -->
      <div class="flex items-center gap-2 px-2 py-1 border-b border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)]">
        <button mat-icon-button (click)="goBack()" [matTooltip]="I18N.photo_detail.back | translate" [attr.aria-label]="I18N.photo_detail.back | translate">
          <mat-icon>arrow_back</mat-icon>
        </button>
        <span class="min-w-0 flex-1 truncate font-medium">{{ p.filename }}</span>
        @if (auth.isEdition()) {
          <button mat-icon-button class="max-md:!hidden" (click)="refreshPhoto(p)" [matTooltip]="I18N.photo_refresh.title | translate" [attr.aria-label]="I18N.photo_refresh.title | translate"><mat-icon>refresh</mat-icon></button>
        }


        @if (store.config()?.features?.show_similar_button) {
          <button mat-icon-button class="max-md:!hidden" [matMenuTriggerFor]="similarMenu"
            [matTooltip]="I18N.similar.find_similar | translate" [attr.aria-label]="I18N.similar.find_similar | translate">
            <mat-icon>image_search</mat-icon>
          </button>
        }

        @if (store.config()?.features?.show_critique) {
          <button mat-icon-button (click)="openCritique(p)"
            [matTooltip]="I18N.critique.title | translate" [attr.aria-label]="I18N.critique.title | translate">
            <mat-icon>analytics</mat-icon>
          </button>
        }

        @if (auth.isEdition() && store.config()?.cull?.trash_available) {
          <button mat-icon-button class="max-md:!hidden" (click)="deletePhoto()"
            [matTooltip]="I18N.photo_detail.delete.button_label | translate" [attr.aria-label]="I18N.photo_detail.delete.button_label | translate">
            <mat-icon>delete</mat-icon>
          </button>
        }

        @if (auth.isEdition()) {
          <button mat-icon-button class="max-md:!hidden" [matMenuTriggerFor]="categoryOverrideMenu"
            [matTooltip]="I18N.photo.category_override.menu_tooltip | translate" [attr.aria-label]="I18N.photo.category_override.menu_tooltip | translate">
            <mat-icon>category</mat-icon>
          </button>
        }

        <button mat-icon-button (click)="cycleFaceBoxMode()"
          data-face-box-mode
          [matTooltip]="faceBoxModeLabel() | translate"
          [attr.aria-label]="faceBoxModeLabel() | translate">
          <mat-icon>{{ faceBoxModeIcon() }}</mat-icon>
        </button>

        @if (auth.isEdition()) {
          <button mat-icon-button class="max-md:!hidden" (click)="openManualFaces(p)"
            [matTooltip]="I18N.manual_faces.title | translate" [attr.aria-label]="I18N.manual_faces.title | translate">
            <mat-icon>crop_free</mat-icon>
          </button>
        }

        @if (auth.isEdition() && p.unassigned_faces > 0) {
          <button mat-icon-button class="max-md:!hidden" (click)="openAddPerson(p)"
            [matTooltip]="I18N.manage_persons.assign_face | translate" [attr.aria-label]="I18N.manage_persons.assign_face | translate">
            <mat-icon>person_add</mat-icon>
          </button>
        }

        @if (downloadOptions().length > 1) {
          <button mat-icon-button [matMenuTriggerFor]="downloadMenu" [disabled]="downloading()" [matTooltip]="I18N.photo_detail.download | translate"
            [attr.aria-label]="(downloading() ? I18N.photo_detail.downloading : I18N.photo_detail.download) | translate">
            @if (downloading()) { <mat-spinner diameter="18" class="!inline-block" aria-hidden="true" /> } @else { <mat-icon>download</mat-icon> }
          </button>
          <mat-menu #downloadMenu="matMenu">
            @for (opt of downloadOptions(); track opt.type + (opt.profile ?? '')) {
              <button mat-menu-item (click)="download(p.path, opt.type, opt.profile ?? undefined)">
                <mat-icon>{{ opt.type | downloadIcon }}</mat-icon>
                @if (opt.type === 'darktable') {
                  {{ opt.profile }}
                } @else {
                  {{ ('download.type_' + opt.type) | translate }}
                }
              </button>
            }
          </mat-menu>
        } @else {
          <button mat-icon-button (click)="download(p.path)" [disabled]="downloading()" [matTooltip]="I18N.photo_detail.download | translate"
            [attr.aria-label]="(downloading() ? I18N.photo_detail.downloading : I18N.photo_detail.download) | translate">
            @if (downloading()) { <mat-spinner diameter="18" class="!inline-block" aria-hidden="true" /> } @else { <mat-icon>download</mat-icon> }
          </button>
        }

        @if (socialExportEnabled()) {
          <button mat-icon-button class="max-md:!hidden" [matMenuTriggerFor]="socialMenu" [disabled]="downloading()"
            [matTooltip]="(socialCropTooltipKey() | translate)" [attr.aria-label]="I18N.photo_detail.social_crop | translate">
            <mat-icon>crop</mat-icon>
          </button>
        }

        <!-- Declared outside their @if so both the inline buttons and the overflow menu can target them. -->
        <mat-menu #similarMenu="matMenu">
          <button mat-menu-item (click)="openSimilar(p, 'visual')">
            <mat-icon>image_search</mat-icon> {{ I18N.similar.mode_visual | translate }}
          </button>
          <button mat-menu-item (click)="openSimilar(p, 'color')">
            <mat-icon>palette</mat-icon> {{ I18N.similar.mode_color | translate }}
          </button>
          <button mat-menu-item (click)="openSimilar(p, 'person')">
            <mat-icon>person_search</mat-icon> {{ I18N.similar.mode_person | translate }}
          </button>
        </mat-menu>
        <mat-menu #categoryOverrideMenu="matMenu">
          <button mat-menu-item (click)="openCategoryOverride(p)">
            <mat-icon>edit</mat-icon> {{ I18N.photo.category_override.set_action | translate }}
          </button>
          <button mat-menu-item (click)="clearCategoryOverride(p)">
            <mat-icon>restart_alt</mat-icon> {{ I18N.photo.category_override.clear_action | translate }}
          </button>
        </mat-menu>
        <mat-menu #socialMenu="matMenu">
          @for (preset of socialPresets(); track preset.key) {
            <button mat-menu-item (click)="downloadSocialCrop(p.path, preset.key)">
              <mat-icon>crop</mat-icon>
              {{ preset.label_key | translate }}
            </button>
          }
        </mat-menu>

        <!-- Below md the secondary actions fold into this menu so the filename keeps its room;
             back, critique and download stay in the row. Same handlers and conditions as the inline buttons. -->
        @if (auth.isEdition() || store.config()?.features?.show_similar_button || socialExportEnabled()) {
          <button mat-icon-button class="md:!hidden" [matMenuTriggerFor]="moreActionsMenu"
            [matTooltip]="I18N.nav.more | translate" [attr.aria-label]="I18N.nav.more | translate">
            <mat-icon>more_vert</mat-icon>
          </button>
          <mat-menu #moreActionsMenu="matMenu">
            @if (auth.isEdition()) {
              <button mat-menu-item (click)="refreshPhoto(p)"><mat-icon>refresh</mat-icon> {{ I18N.photo_refresh.title | translate }}</button>
            }
            @if (store.config()?.features?.show_similar_button) {
              <button mat-menu-item [matMenuTriggerFor]="similarMenu"><mat-icon>image_search</mat-icon> {{ I18N.similar.find_similar | translate }}</button>
            }
            @if (auth.isEdition() && store.config()?.cull?.trash_available) {
              <button mat-menu-item (click)="deletePhoto()"><mat-icon>delete</mat-icon> {{ I18N.photo_detail.delete.button_label | translate }}</button>
            }
            @if (auth.isEdition()) {
              <button mat-menu-item [matMenuTriggerFor]="categoryOverrideMenu"><mat-icon>category</mat-icon> {{ I18N.photo.category_override.menu_tooltip | translate }}</button>
              <button mat-menu-item (click)="openManualFaces(p)"><mat-icon>crop_free</mat-icon> {{ I18N.manual_faces.title | translate }}</button>
            }
            @if (auth.isEdition() && p.unassigned_faces > 0) {
              <button mat-menu-item (click)="openAddPerson(p)"><mat-icon>person_add</mat-icon> {{ I18N.manage_persons.assign_face | translate }}</button>
            }
            @if (socialExportEnabled()) {
              <button mat-menu-item [matMenuTriggerFor]="socialMenu" [disabled]="downloading()"><mat-icon>crop</mat-icon> {{ I18N.photo_detail.social_crop | translate }}</button>
            }
          </mat-menu>
        }
      </div>

      <app-stack-navigator [path]="p.path" [allowedPaths]="store.pinnedPaths()" [stacked]="!!p.stack_id"
        (memberOpened)="openSetMember($event)" />

      <!-- Main content: image + info -->
      <div class="flex flex-col lg:flex-row lg:flex-1 lg:min-h-0 lg:overflow-hidden">
        <!-- Image panel -->
        <div appZoomPan #zoom="zoomPan" class="group/photo shrink-0 lg:h-auto lg:flex-1 flex items-center justify-center bg-black lg:min-h-0 relative overflow-hidden cursor-grab">
          <img
            [src]="p.path | thumbnailUrl:640:p.preview_revision"
            [alt]="p.filename"
            class="w-full lg:max-w-full lg:max-h-full object-contain transition-opacity duration-300 pointer-events-none select-none"
            [class.opacity-0]="fullImageLoaded()"
            [style.transform]="zoom.transform()"
          />
          <img
            [src]="fullImageUrl()"
            [alt]="p.filename"
            class="absolute inset-0 w-full h-full object-contain transition-opacity duration-300 pointer-events-none select-none"
            [class.opacity-0]="!fullImageLoaded()"
            (load)="onFullImageLoad()"
            [style.transform]="zoom.transform()"
          />
          <app-photo-face-layer
            [path]="p.path"
            [imageWidth]="p.image_width"
            [imageHeight]="p.image_height"
            [transform]="zoom.transform()"
            [canEdit]="auth.isEdition()"
            [mode]="faceBoxMode()"
            [focusPersonIds]="focusPersonIds()"
            (changed)="refreshPeople(p.path)" />
          <app-person-face-menu [path]="p.path" [canEdit]="auth.isEdition()" (changed)="onPersonMenuChanged(p.path)" />
        </div>

        <!-- Info panel -->
        <div class="lg:w-[380px] lg:shrink-0 lg:overflow-y-auto p-4 space-y-4 text-sm text-[var(--mat-sys-on-surface)]">
          <!-- Filename + Date + Category + Aggregate -->
          <div class="mb-2">
            <div class="font-semibold text-lg">{{ p.filename }}</div>
            @if (p.date_taken || auth.isEdition()) {
              <div class="flex items-center gap-1 text-[var(--mat-sys-on-surface-variant)] text-xs">
                @if (auth.isEdition()) {
                  <button mat-icon-button class="!w-7 !h-7 !min-w-0 !p-0 -ml-1.5 !inline-flex items-center justify-center" (click)="editCaptureDate(p)"
                          [matTooltip]="I18N.capture_date.title | translate"
                          [attr.aria-label]="I18N.capture_date.title | translate">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">edit_calendar</mat-icon>
                  </button>
                }
                @if (p.date_taken) {
                  <span class="leading-4">{{ p.date_taken }}</span>
                }
              </div>
            }
            <div class="flex items-center gap-2 mt-1">
              @if (p.category || auth.isEdition()) {
                <span class="inline-flex items-center gap-0.5 px-2 py-0.5 bg-[var(--mat-sys-primary-container)] text-[var(--mat-sys-on-primary-container)] rounded-full text-xs font-medium">
                  @if (p.category) { {{ p.category | categoryLabel }} }
                  <!-- Category explainer toggle: "why isn't this photo classified as X?" — kept for an uncategorized photo too. -->
                  @if (auth.isEdition()) {
                    <button type="button" class="w-6 h-6 -my-1 -mr-1.5 inline-flex items-center justify-center rounded-full cursor-pointer hover:bg-black/15"
                            data-explainer-toggle
                            (click)="toggleExplainer()"
                            [attr.aria-expanded]="explainerOpen()"
                            [matTooltip]="I18N.photo.category_override.explainer_toggle | translate"
                            [attr.aria-label]="I18N.photo.category_override.explainer_toggle | translate">
                      <mat-icon class="!text-base !w-4 !h-4 !leading-4" aria-hidden="true">{{ explainerOpen() ? 'expand_less' : 'expand_more' }}</mat-icon>
                    </button>
                  }
                </span>
              }
              @if (keeperHint()?.has_better) {
                <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-black/60 text-amber-300 rounded-full text-xs font-medium"
                      [attr.aria-label]="I18N.culling.reason.better_shot | translate">
                  <mat-icon class="!text-sm !w-4 !h-4 !leading-4" aria-hidden="true">arrow_circle_up</mat-icon>
                  {{ I18N.culling.reason.better_shot | translate }}
                </span>
              }
              <span class="ml-auto flex items-center gap-2">
                @if (store.metricRangesByColumn()['aggregate']; as range) {<app-metric-rank class="w-28" [range]="range" [value]="p.aggregate" />}
                <span class="text-[var(--mat-sys-primary)] font-semibold">{{ p.aggregate | fixed:1 }}</span>
              </span>
            </div>
          </div>

          <!-- Category explainer: the target-category select and its explanation -->
          @if (auth.isEdition() && explainerOpen()) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <mat-form-field class="w-full" subscriptSizing="dynamic">
                <mat-label>{{ I18N.photo.category_override.target_category_label | translate }}</mat-label>
                <mat-select [value]="explainerTargetCategory()" (selectionChange)="explainerTargetCategory.set($event.value)">
                  @for (name of explainerCategories(); track name) {
                    <mat-option [value]="name">{{ name | categoryLabel }}</mat-option>
                  }
                </mat-select>
                <mat-hint>{{ I18N.photo.category_override.target_category_hint | translate }}</mat-hint>
              </mat-form-field>
              @if (explainerTargetCategory(); as target) {
                <app-category-explainer [path]="p.path" [targetCategory]="target" />
              }
            </div>
          }

          <!-- Rating controls (edition only) -->
          @if (auth.isEdition()) {
            <div class="flex items-center border-t border-[var(--mat-sys-outline-variant)] pt-1 mb-1">
              <!-- Star rating -->
              @for (star of stars; track star) {
                <button class="w-8 h-8 rounded-full inline-flex items-center justify-center hover:bg-[var(--mat-sys-surface-container-high)] transition-colors cursor-pointer" (click)="setRating(p.path, star)">
                  <mat-icon class="!text-xl !w-5 !h-5 !leading-5 !text-yellow-400">{{ p.star_rating !== null && star <= p.star_rating! ? 'star' : 'star_border' }}</mat-icon>
                </button>
              }
              <div class="flex-1"></div>
              <!-- Favorite -->
              <button mat-icon-button (click)="toggleFavorite(p.path)"
                [matTooltip]="(p.is_favorite ? I18N.rating.remove_favorite : I18N.rating.add_favorite) | translate"
                [attr.aria-label]="(p.is_favorite ? I18N.rating.remove_favorite : I18N.rating.add_favorite) | translate"
                [attr.aria-pressed]="!!p.is_favorite">
                <mat-icon class="!text-red-400">{{ p.is_favorite ? 'favorite' : 'favorite_border' }}</mat-icon>
              </button>
              <!-- Review decisions -->
              <button mat-icon-button (click)="reviewPhoto(p.is_kept ? 'undecided' : 'kept')" [class.text-green-400]="p.is_kept"
                [matTooltip]="I18N.review.keep | translate"
                [attr.aria-label]="I18N.review.keep | translate"
                [attr.aria-pressed]="!!p.is_kept">
                <mat-icon>{{ p.is_kept ? 'check_circle' : 'check_circle_outline' }}</mat-icon>
              </button>
              <button mat-icon-button (click)="reviewPhoto('undecided')"
                [matTooltip]="I18N.review.reset | translate"
                [attr.aria-label]="I18N.review.reset | translate">
                <mat-icon>restart_alt</mat-icon>
              </button>
              <button mat-icon-button (click)="toggleRejected(p.path)" [class.text-orange-400]="p.is_rejected"
                [matTooltip]="(p.is_rejected ? I18N.rating.unmark_rejected : I18N.rating.mark_rejected) | translate"
                [attr.aria-label]="(p.is_rejected ? I18N.rating.unmark_rejected : I18N.rating.mark_rejected) | translate"
                [attr.aria-pressed]="!!p.is_rejected">
                <mat-icon>{{ p.is_rejected ? 'thumb_down' : 'thumb_down_off_alt' }}</mat-icon>
              </button>
            </div>
          }

          <!-- Caption -->
          <div>
            <div class="flex items-center justify-between mb-1">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)]">{{ I18N.photo_detail.caption | translate }}</div>
              @if (auth.isEdition()) {
                <div class="flex gap-1">
                  @if (!p.caption && store.config()?.features?.show_captions) {
                    <button mat-icon-button class="!w-7 !h-7 !p-0" (click)="generateCaption(p.path)" [disabled]="generatingCaption()" [matTooltip]="I18N.photo_detail.generate_caption | translate" [attr.aria-label]="I18N.photo_detail.generate_caption | translate">
                      @if (generatingCaption()) {
                        <mat-spinner diameter="16" [attr.aria-label]="I18N.ui.labels.loading | translate" />
                      } @else {
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4">auto_fix_high</mat-icon>
                      }
                    </button>
                  }
                  <button mat-icon-button class="!w-7 !h-7 !p-0" (click)="editCaption(p)" [matTooltip]="I18N.photo_detail.edit_caption | translate" [attr.aria-label]="I18N.photo_detail.edit_caption | translate">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">edit</mat-icon>
                  </button>
                </div>
              }
            </div>
            @if (translatingCaption()) {
              <p class="text-[var(--mat-sys-on-surface-variant)] opacity-60 italic text-xs">{{ I18N.photo_detail.translating_caption | translate }}</p>
            } @else if (displayCaption()) {
              <p class="text-[var(--mat-sys-on-surface-variant)]">{{ displayCaption() }}</p>
            } @else {
              <p class="text-[var(--mat-sys-on-surface-variant)] opacity-40 italic text-xs">&mdash;</p>
            }
          </div>

          <!-- Metric tabs: EXIF | Quality | Composition | Technical | Histogram -->
          <app-photo-metrics-tabs [photo]="p" [ranges]="store.metricRangesByColumn()"
                                  [populated]="store.config()?.populated_scores"
                                  [histogramHeight]="HISTOGRAM_PANEL_HEIGHT"
                                  [histogramDefaultMode]="histogramDefaultMode()"
                                  [indicatorPercent]="clippingIndicatorPercent()" />


          <!-- Location -->
          @if (p.gps_latitude !== null && p.gps_longitude !== null) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3 mb-2">
              <div class="flex items-center justify-between mb-2">
                <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)]">{{ I18N.photo_detail.location | translate }}</div>
                @if (auth.isEdition()) {
                  <button mat-icon-button class="!w-7 !h-7 !p-0" (click)="editGps(p)" [matTooltip]="I18N.photo_detail.edit_location | translate" [attr.aria-label]="I18N.photo_detail.edit_location | translate">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">edit_location</mat-icon>
                  </button>
                }
              </div>
              @if (locationName()) {
                <div class="text-sm font-medium mb-1">{{ locationName() }}</div>
              }
              <div class="text-xs text-[var(--mat-sys-on-surface-variant)] mb-2">{{ p.gps_latitude | fixed:6 }}, {{ p.gps_longitude | fixed:6 }}</div>
              <div #locationMapContainer class="w-full h-40 rounded-lg overflow-hidden"></div>
            </div>
          } @else if (auth.isEdition()) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3 mb-2">
              <div class="flex items-center justify-between">
                <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)]">{{ I18N.photo_detail.location | translate }}</div>
                <button mat-icon-button class="!w-7 !h-7 !p-0" (click)="editGps(p)" [matTooltip]="I18N.photo_detail.add_location | translate" [attr.aria-label]="I18N.photo_detail.add_location | translate">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">add_location</mat-icon>
                </button>
              </div>
              <p class="text-[var(--mat-sys-on-surface-variant)] opacity-40 italic text-xs">&mdash;</p>
            </div>
          }

          <!-- Tags section: AI chips, then manual chips (marked, removable for editors) -->
          @if (p.tags_list.length || p.manual_tags.length || auth.isEdition()) {
            <div data-testid="tags-section">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ I18N.photo_detail.tags | translate }}</div>
              <div class="flex gap-1.5 flex-wrap items-center">
                @for (tag of p.tags_list; track tag) {
                  <span data-testid="ai-tag-chip" class="inline-flex">
                    <button class="px-2 py-0.5 bg-[var(--facet-accent-badge)] text-[var(--facet-accent-text)] rounded-full text-xs cursor-pointer hover:opacity-80 transition-opacity"
                            (click)="navigateToGallery('tag', tag)">{{ tag }}</button>
                  </span>
                }
                @for (tag of p.manual_tags; track tag) {
                  <span data-testid="manual-tag-chip"
                        class="inline-flex items-center rounded-full border border-dashed border-[var(--facet-accent-text)] text-[var(--facet-accent-text)] text-xs">
                    <button class="inline-flex items-center gap-1 pl-2 pr-2 py-0.5 cursor-pointer hover:opacity-80 transition-opacity"
                            [attr.title]="I18N.manual_tags.manual | translate"
                            (click)="navigateToGallery('tag', tag)">
                      <mat-icon class="!text-xs !w-3 !h-3 !leading-3" aria-hidden="true">sell</mat-icon>
                      <span class="sr-only">{{ I18N.manual_tags.manual | translate }}:</span>
                      {{ tag }}
                    </button>
                    @if (auth.isEdition()) {
                      <button data-testid="manual-tag-remove"
                              class="inline-flex items-center justify-center min-w-6 min-h-6 -my-1.5 -ml-1 cursor-pointer hover:opacity-80"
                              [attr.aria-label]="I18N.manual_tags.remove_tag | translate:{ tag: tag }"
                              (click)="removeManualTag(p, tag)">
                        <mat-icon class="!text-xs !w-3 !h-3 !leading-3" aria-hidden="true">close</mat-icon>
                      </button>
                    }
                  </span>
                }
              </div>
              @if (auth.isEdition()) {
                <div class="flex items-center gap-1 mt-2" data-testid="manual-tag-add">
                  <input type="text" maxlength="64"
                         class="min-w-0 flex-1 px-2 py-1 text-xs rounded border border-[var(--mat-sys-outline-variant)] bg-transparent"
                         [value]="newTag()"
                         [attr.aria-label]="I18N.manual_tags.add | translate"
                         [placeholder]="I18N.manual_tags.add | translate"
                         (input)="onNewTagInput($event)"
                         (keydown.enter)="addManualTag(p, newTag())" />
                  <button mat-icon-button class="!w-7 !h-7 !p-0 !inline-flex !items-center !justify-center shrink-0" (click)="addManualTag(p, newTag())"
                          [disabled]="!newTag().trim()"
                          [matTooltip]="I18N.manual_tags.add | translate" [attr.aria-label]="I18N.manual_tags.add | translate">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">add</mat-icon>
                  </button>
                </div>
              }
            </div>
          }

          <!-- Persons section -->
          @if (p.persons.length) {
            <div class="pt-1">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ I18N.photo_detail.persons | translate }}</div>
              <div class="flex gap-3 flex-wrap">
                @for (person of p.persons; track person.id) {
                  <button class="flex flex-col items-center gap-1 cursor-pointer hover:opacity-80 transition-opacity"
                          data-person-avatar aria-haspopup="menu"
                          (click)="openPersonMenu(person, $event)">
                    <img
                      [src]="person.id | personThumbnailUrl"
                      [alt]="person.name"
                      class="w-10 h-10 rounded-full object-cover bg-[var(--mat-sys-surface-container)]"
                    />
                    <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ person.name }}</span>
                  </button>
                }
              </div>
            </div>
          }

          <!-- Set section (bracket/panorama/hdr_panorama/burst/duplicate) -->
          @if (photoSet(); as set) {
            @if (set.kind) {
              <div class="pt-1">
                <div class="flex items-center gap-2 flex-wrap mb-2 text-sm">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-70">{{ set.kind | photoSetKindIcon }}</mat-icon>
                  <span class="font-medium">{{ set.kind | photoSetKindLabel | translate }}</span>
                  <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.capsules.photos_count | translate:{ count: set.count } }}</span>
                  @if (set.ev_span !== null) {
                    <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.photo_detail.set.ev_span | translate }}: {{ set.ev_span | fixed:1 }} EV</span>
                  }
                  <button mat-icon-button class="!w-7 !h-7 !p-0 !inline-flex !items-center !justify-center ml-auto" (click)="openSetInGallery()"
                          [matTooltip]="I18N.photo_detail.set.open_in_gallery | translate" [attr.aria-label]="I18N.photo_detail.set.open_in_gallery | translate">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">photo_library</mat-icon>
                  </button>
                </div>
                <div class="flex gap-2 flex-wrap">
                  @for (member of set.members; track member.path) {
                    <button class="relative rounded-lg overflow-hidden w-16 h-16 shrink-0 cursor-pointer hover:opacity-80 transition-opacity ring-[var(--mat-sys-primary)]"
                            [class.ring-2]="member.path === p.path"
                            [attr.aria-label]="(I18N.photo_detail.set.member_position | translate:{ position: $index + 1, count: set.members.length }) + (member.ev_offset !== null ? ', ' + (member.ev_offset | evOffset) : '')"
                            (click)="openSetMember(member.path)">
                      <img [src]="member.path | thumbnailUrl:96:member.preview_revision" alt="" class="w-full h-full object-cover" />
                      @if (member.ev_offset !== null) {
                        <span class="absolute bottom-0 inset-x-0 text-center text-[0.625rem] leading-4 bg-black/60 text-white">{{ member.ev_offset | evOffset }}</span>
                      }
                    </button>
                  }
                </div>
              </div>
            }
          }
        </div>
      </div>
    } @else if (photoMissing()) {
      <div class="flex flex-col items-center justify-center gap-2 h-full text-[var(--mat-sys-on-surface-variant)]">
        <mat-icon class="!text-4xl">image_not_supported</mat-icon>
        {{ I18N.errors.photo_not_found | translate }}
        <button mat-button (click)="goBack()">
          <mat-icon>arrow_back</mat-icon>
          {{ I18N.photo_detail.back | translate }}
        </button>
      </div>
    } @else {
      <div class="flex items-center justify-center h-full">
        <mat-icon class="!text-4xl text-[var(--mat-sys-on-surface-variant)]">hourglass_empty</mat-icon>
      </div>
    }
  `,
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'flex flex-col h-full overflow-y-auto lg:overflow-y-hidden' },
})
export class PhotoDetailComponent extends PhotoDetailBase implements OnInit {
  protected readonly I18N = i18nKeys();
  private readonly location = inject(Location);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  protected readonly auth = inject(AuthService);
  protected readonly store = inject(GalleryStore);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  private readonly staleness = inject(StalenessGuardFactory);
  private readonly assistantChanges = inject(AssistantChangesService);
  private readonly photoActions = inject(PhotoActionsService);
  private readonly journal = inject(UserActivityJournal);
  private readonly keymap = inject(KeyboardMappingService);
  private readonly stacks = inject(PhotoStackService);
  private readonly stackNavigator = viewChild(StackNavigatorComponent);
  private readonly faceLayer = viewChild(PhotoFaceLayerComponent);
  private readonly personMenu = viewChild(PersonFaceMenuComponent);
  private memberRequest = 0;
  private memberPhoto: { photo: Photo; owner: string } | null = null;
  private readonly viewerOwner = this.auth.identity();

  readonly photo = signal<Photo | null>(null);
  protected readonly photoMissing = signal(false);
  protected readonly downloading = signal(false);
  protected readonly downloadOptions = signal<DownloadOption[]>([]);
  protected readonly generatingCaption = signal(false);
  protected readonly stars: readonly number[] = [1, 2, 3, 4, 5];

  // Category explainer ("why isn't this photo classified as X?")
  protected readonly explainerOpen = signal(false);
  protected readonly explainerCategories = signal<string[]>([]);
  protected readonly explainerTargetCategory = signal<string | null>(null);

  // Face boxes: off, on hover, or always shown. Remembered per browser.
  protected readonly faceBoxMode = signal<FaceBoxMode>(readFaceBoxMode());
  protected readonly faceBoxModeIcon = computed(() => FACE_BOX_MODE_ICONS[this.faceBoxMode()]);
  protected readonly faceBoxModeLabel = computed(() => FACE_BOX_MODE_LABELS[this.faceBoxMode()]);
  /** The gallery's person filter: those persons' faces stay boxed while browsing them. */
  protected readonly focusPersonIds = computed(() =>
    (this.store.filters().person_id || '').split(',').map(Number).filter((n) => Number.isInteger(n) && n > 0));

  /** Hover, then always, then off, then hover again. */
  protected cycleFaceBoxMode(): void {
    const next = nextFaceBoxMode(this.faceBoxMode());
    this.faceBoxMode.set(next);
    writeFaceBoxMode(next);
  }

  // Download options
  private downloadOptionsEffect = effect(() => {
    const p = this.photo();
    if (!p) { this.downloadOptions.set([]); return; }
    if (!this.auth.downloadProfiles().length) {
      this.downloadOptions.set([{ type: 'original', label: 'original' }]);
      return;
    }
    const requestedPath = p.path;
    firstValueFrom(this.api.get<{ options: DownloadOption[] }>('/download/options', { path: requestedPath }))
      .then(res => { if (this.photo()?.path === requestedPath) this.downloadOptions.set(res.options); })
      .catch(() => { if (this.photo()?.path === requestedPath) this.downloadOptions.set([{ type: 'original', label: 'original' }]); });
  });

  // Social-export crop presets (from viewer config) + which signal frames the crop
  protected readonly HISTOGRAM_PANEL_HEIGHT = HISTOGRAM_PANEL_HEIGHT;
  /** House default for the histogram's channels, until the user picks one.
   *  A stale/unrecognised config value degrades to 'rgb' rather than the
   *  widget rendering nothing. */
  protected readonly histogramDefaultMode = computed<HistogramMode>(() => {
    const configured = this.store.config()?.clipping?.histogram_mode;
    return isHistogramMode(configured) ? configured : 'rgb';
  });
  protected readonly clippingIndicatorPercent = computed(
    () => this.store.config()?.clipping?.indicator_percent ?? 1);

  protected readonly socialPresets = computed(() => this.store.config()?.social_export?.presets ?? []);
  protected readonly socialExportEnabled = computed(() =>
    this.auth.isEdition() && !!this.store.config()?.features?.show_social_export && this.socialPresets().length > 0,
  );
  protected readonly socialCropSource = signal<string | null>(null);
  protected readonly socialCropTooltipKey = computed(() => {
    const source = this.socialCropSource();
    const key = source ? (SOCIAL_SOURCE_KEYS[source] ?? null) : null;
    return key ?? I18N.photo_detail.social_crop;
  });
  private socialCropSourceEffect = effect(() => {
    const p = this.photo();
    const presets = this.socialPresets();
    if (!p || !this.socialExportEnabled()) {
      this.socialCropSource.set(null);
      return;
    }
    const requestedPath = p.path;
    firstValueFrom(this.api.get<{ source: string }>('/photo/social_crop/preview', { path: requestedPath, preset: presets[0].key }))
      .then(res => { if (this.photo()?.path === requestedPath) this.socialCropSource.set(res.source); })
      .catch(() => { if (this.photo()?.path === requestedPath) this.socialCropSource.set(null); });
  });

  protected readonly keeperHint = signal<KeeperHint | null>(null);
  private keeperHintEffect = effect(() => {
    const p = this.photo();
    this.keeperHint.set(null);
    if (!p) return;
    const requestedPath = p.path;
    firstValueFrom(this.api.post<Record<string, KeeperHint>>('/photos/keeper_hints', { paths: [requestedPath] }))
      .then(hints => { if (this.photo()?.path === requestedPath) this.keeperHint.set(hints[requestedPath] ?? null); })
      .catch(() => { if (this.photo()?.path === requestedPath) this.keeperHint.set(null); });
  });

  // Set membership (bracket/panorama/hdr_panorama/burst/duplicate)
  protected readonly photoSet = signal<PhotoSet | null>(null);
  private photoSetEffect = effect(() => {
    const p = this.photo();
    this.photoSet.set(null);
    if (!p) return;
    const requestedPath = p.path;
    firstValueFrom(this.api.get<PhotoSet>('/photo/set', { path: requestedPath }))
      .then(res => { if (this.photo()?.path === requestedPath) this.photoSet.set(res); })
      .catch(() => { if (this.photo()?.path === requestedPath) this.photoSet.set(null); });
  });

  // Location
  protected readonly locationName = signal('');
  private locationNameEffect = effect(() => {
    const p = this.photo();
    if (!p || p.gps_latitude == null || p.gps_longitude == null) {
      this.locationName.set('');
      return;
    }
    const requestedPath = p.path;
    firstValueFrom(this.api.get<{ display_name: string }>('/filter_options/location_name', {
      lat: String(p.gps_latitude), lng: String(p.gps_longitude),
    }))
      .then(res => { if (this.photo()?.path === requestedPath) this.locationName.set(res.display_name || ''); })
      .catch(() => { if (this.photo()?.path === requestedPath) this.locationName.set(''); });
  });

  private readonly locationMapContainer = viewChild<ElementRef<HTMLDivElement>>('locationMapContainer');
  private locationMap: L.Map | null = null;
  private locationMapTimeout: ReturnType<typeof setTimeout> | null = null;

  private locationMapEffect = effect(() => {
    const container = this.locationMapContainer();
    const p = this.photo();
    if (!container || !p || p.gps_latitude == null || p.gps_longitude == null) return;

    if (this.locationMapTimeout !== null) {
      clearTimeout(this.locationMapTimeout);
      this.locationMapTimeout = null;
    }
    if (this.locationMap) {
      this.locationMap.remove();
      this.locationMap = null;
    }

    this.locationMapTimeout = setTimeout(() => {
      this.locationMapTimeout = null;
      const map = createLeafletMap(container.nativeElement, {
        zoomControl: false,
        attributionControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        touchZoom: false,
      }).setView([p.gps_latitude!, p.gps_longitude!], 13);

      L.marker([p.gps_latitude!, p.gps_longitude!]).addTo(map);
      this.locationMap = map;
    }, 0);
  });

  constructor() {
    super();
    this.destroyRef.onDestroy(() => {
      if (this.locationMapTimeout !== null) clearTimeout(this.locationMapTimeout);
      if (this.locationMap) { this.locationMap.remove(); this.locationMap = null; }
    });
    this.assistantChanges.batch$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(batch => void this.refreshAfterAssistant(batch));
    this.store.organizationRestored$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => void this.refreshAfterRestore());
  }

  /** An Organization history restore may have rewritten this photo; a newer local edit wins over the reply. */
  private async refreshAfterRestore(): Promise<void> {
    const previous = this.photo();
    if (!previous) return;
    const fresh = await this.fetchPhoto(previous.path).catch(() => undefined);
    if (fresh && this.photo() === previous) this.photo.set(fresh);
  }

  /** An assistant write touched this page's photo (or an unenumerable scope): refetch the full detail row. */
  private async refreshAfterAssistant(batch: AssistantChangeBatch): Promise<void> {
    const path = this.photo()?.path;
    if (!path || (batch.paths !== null && !batch.paths.includes(path))) return;
    try {
      const fresh = await this.fetchPhoto(path);
      // The user moved to another photo (ArrowRight) while this was in flight.
      if (this.photo()?.path === path) this.photo.set(fresh);
    } catch (err) {
      if (this.photo()?.path !== path) return;
      // Only a missing photo has no page left; any other failure keeps the page the user is on.
      if ((err as { status?: number }).status === 404) this.goBack();
      else this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  async ngOnInit(): Promise<void> {
    void this.store.ensureMetricRanges();
    // Back/Forward between two photos reuses this component instead of creating a new one.
    this.route.queryParamMap.pipe(skip(1), takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      const path = params.get('path');
      if (path && path !== this.photo()?.path) void this.showPhotoAt(path);
    });

    // Try router state (passed from gallery via navigate(..., { state }))
    const statePhoto = history.state?.['photo'] as Photo | undefined;

    if (statePhoto) {
      this.photo.set(statePhoto);
    } else {
      // Fallback: load from API using query param
      const path = this.route.snapshot.queryParamMap.get('path');
      if (path) {
        // The user may leave, or Back may move the address, while this loads; replacing keeps a dead entry out of history.
        const photo = await this.fetchPhoto(path).catch(() => undefined);
        if (this.destroyRef.destroyed || this.viewerOwner !== this.auth.identity() || this.route.snapshot.queryParamMap.get('path') !== path) return;
        if (photo) this.photo.set(photo);
        else this.router.navigate(['/'], { replaceUrl: true });
      } else {
        this.router.navigate(['/'], { replaceUrl: true });
      }
    }
  }

  private async fetchPhoto(path: string): Promise<Photo> {
    const photo = normalisePhotoFlags(
      await firstValueFrom(this.api.get<Photo>('/photo', { path })));
    if (!photo.tags_list) {
      photo.tags_list = photo.tags ? photo.tags.split(',').map(t => t.trim()) : [];
    }
    if (!photo.manual_tags) {
      photo.manual_tags = [];
    }
    if (!photo.persons) {
      photo.persons = [];
    }
    return photo;
  }

  private async showPhotoAt(path: string): Promise<void> {
    if (this.viewerOwner !== this.auth.identity() || (this.memberPhoto?.photo.path === path && !this.memberAllowed(path))) return;
    // Store copy carries edits made since; history.state is the photo as opened.
    const context = this.stacks.context();
    const photo = (this.memberPhoto?.owner === this.auth.identity() && this.memberPhoto.photo.path === path ? this.memberPhoto.photo : null) ?? this.store.photos().find(p => p.path === path) ?? await this.fetchPhoto(path).catch(() => undefined);
    if (this.destroyRef.destroyed || !context() || this.route.snapshot.queryParamMap.get('path') !== path) return;
    if (!photo) {
      // Say so rather than keep the previous photo under this address (e.g. Forward to one deleted since).
      this.photo.set(null);
      this.photoMissing.set(true);
      return;
    }
    this.photoMissing.set(false);
    this.photo.set(photo);
    this.fullImageLoaded.set(false);
  }

  private memberAllowed(path: string): boolean {
    const pinned = this.store.pinnedPaths();
    return pinned === null || pinned.includes(path);
  }

  protected async openSetMember(path: string): Promise<void> {
    if (this.viewerOwner !== this.auth.identity() || !this.memberAllowed(path) || this.photo()?.path === path) return;
    const sequence = ++this.memberRequest;
    const currentPath = this.photo()?.path;
    const context = this.stacks.context();
    const current = () => !this.destroyRef.destroyed && context() && sequence === this.memberRequest && this.photo()?.path === currentPath && this.memberAllowed(path);
    try {
      const photo = await this.fetchPhoto(path);
      if (!current()) return;
      this.memberPhoto = { photo, owner: this.auth.identity() };
      try {
        await this.stacks.navigateMember(path, photo, () => this.memberAllowed(path), true);
      } finally { this.memberPhoto = null; }
    } catch {
      if (!current()) return;
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  protected openSetInGallery(): void {
    const set = this.photoSet();
    if (!set?.kind || set.group_id == null) return;
    const groupId = String(set.group_id);
    const updates = setScopePatch(
      set.kind === 'burst' || set.kind === 'duplicate' ? set.kind : 'sequence', groupId, set.kind,
    );
    // Carried via router navigation state, never the URL or a post-navigate
    // updateFilters() call: the gallery route re-initialises its filters from
    // config + localStorage + URL on activation, which either overwrites a
    // post-navigate update or discards it as arriving too late. `state` is
    // read by GalleryComponent.ngOnInit before its first load. See
    // GalleryComponent.consumeSetScopeState for why it is also never
    // bookmarkable: sequence_group_id is renumbered on every detection pass.
    this.router.navigate(['/'], { state: { setScope: updates } });
  }

  private shortcutBlocked(event: Event): boolean {
    return event.defaultPrevented || isPageShortcutBlocked(event as KeyboardEvent) || this.store.slideshowActive();
  }

  @HostListener('document:keydown.escape', ['$event'])
  protected goBack(event?: Event): void {
    if (event && this.shortcutBlocked(event)) return;
    this.location.back();
  }

  @HostListener('document:keydown.arrowleft', ['$event'])
  protected prevPhoto(event: Event): void {
    if (this.shortcutBlocked(event)) return;
    event.preventDefault();
    void this.navigateAdjacentPhoto(-1);
  }

  @HostListener('document:keydown.arrowright', ['$event'])
  protected nextPhoto(event: Event): void {
    if (this.shortcutBlocked(event)) return;
    event.preventDefault();
    void this.navigateAdjacentPhoto(1);
  }

  /** The mapped rating keys act on the open photo — the same keys the grid's
   *  focused card answers, so a reviewer never has to reach for the panel.
   *  Gated the same way the rating buttons are (edition mode + the
   *  rating-controls feature flag); typing contexts and open dialogs bow out
   *  first. No auto-advance: a single-photo view has no "next" contract with
   *  the filters it came from. */
  @HostListener('document:keydown', ['$event'])
  protected onRatingShortcut(event: KeyboardEvent): void {
    if (isPageShortcutBlocked(event)) return;
    if (!this.auth.isEdition() || !this.store.config()?.features?.show_rating_controls) return;
    const p = this.photo();
    if (!p) return;
    if (event.key >= '1' && event.key <= '5') {
      event.preventDefault();
      void this.setRating(p.path, Number(event.key));
    } else if (this.keymap.matches(event, 'favourite')) {
      event.preventDefault();
      void this.toggleFavorite(p.path);
    } else if (event.key === '0' || this.keymap.matches(event, 'reject')) {
      event.preventDefault();
      void this.toggleRejected(p.path);
    }
  }

  private async navigateAdjacentPhoto(delta: number): Promise<void> {
    // Match the visible stack buttons; its members already respect an exact list.
    if (this.stackNavigator()?.step(delta)) return;
    const current = this.photo();
    if (!current) return;
    const indexOf = () => this.store.photos().findIndex(p => p.path === current.path);
    let idx = indexOf();
    if (idx === -1) return;
    // The store only holds the pages the grid has scrolled through, so stepping past the last one fetches the next.
    if (idx + delta >= this.store.photos().length && this.store.hasMore()) {
      await this.store.nextPage(undefined, { whileParked: true });
      // Back between two photos reuses this component, so the URL is checked as well as destroyed.
      if (this.destroyRef.destroyed || this.photo()?.path !== current.path
        || this.route.snapshot.queryParamMap.get('path') !== current.path) return;
      idx = indexOf();
      if (idx === -1) return;
    }
    const next = this.store.photos()[idx + delta];
    if (!next) return;
    // Replace, so Escape (history back) leaves the photo page instead of stepping back through every photo.
    this.router.navigate(['/photo'], {
      queryParams: { path: next.path },
      state: { photo: next },
      replaceUrl: true,
    });
    this.photo.set(next);
    this.fullImageLoaded.set(false);
  }

  protected async download(path: string, type = 'original', profile?: string): Promise<void> {
    this.downloading.set(true);
    try {
      await downloadAll(
        [path],
        p => this.api.downloadUrl(p, type, profile),
        url => this.api.getRaw(url),
      );
    } finally {
      this.downloading.set(false);
    }
  }

  protected async downloadSocialCrop(path: string, preset: string): Promise<void> {
    this.downloading.set(true);
    try {
      await downloadAll(
        [path],
        p => `/api/photo/social_crop?path=${encodeURIComponent(p)}&preset=${encodeURIComponent(preset)}`,
        url => this.api.getRaw(url),
      );
    } finally {
      this.downloading.set(false);
    }
  }

  /**
   * Apply the fields the server has confirmed to the open photo and to the
   * gallery's copy of it.
   *
   * The store write is what makes an edit outlive the lightbox: the grid
   * renders from `GalleryStore.photos()`, so a mutation that only reached
   * this component's own signal was shown back at its pre-edit value the
   * moment the user returned, and looked discarded even though the server
   * had accepted it.
   *
   * One partial feeds both, so the two views cannot be given different
   * fields — which matters most where the server couples them: a reject that
   * also clears the stars and the favorite flag has to carry all three, and
   * the store used to receive none of them.
   *
   * Only ever called with state the server has already acknowledged, so a
   * failed call leaves both the signal and the store untouched — the same
   * pessimistic shape every handler here already had, and one that needs no
   * revert path.
   */
  protected async openManualFaces(p: Photo): Promise<void> {
    const path = p.path;
    const { ManualFaceDialogComponent } = await import('./manual-face-dialog.component');
    if (this.destroyRef.destroyed || this.photo()?.path !== path) return;
    this.dialog.open(ManualFaceDialogComponent, {
      width: '800px', maxWidth: '96vw',
      data: { path, filename: p.filename, onCommitted: () => this.onPersonMenuChanged(path) },
    });
  }

  /**
   * Re-read a photo's people from the server after a face changed hands, from the
   * manual-face editor or the face layer. The server's answer replaces the store's
   * optimistic patch, which cannot know whether a moved face emptied its old person.
   */
  protected async refreshPeople(path: string): Promise<void> {
    try {
      const actual = await firstValueFrom(this.api.get<Photo>('/photo', { path }));
      const patch = { persons: actual.persons, unassigned_faces: actual.unassigned_faces };
      this.store.patchPhoto(path, patch);
      if (!this.destroyRef.destroyed && this.photo()?.path === path) {
        this.photo.update(current => current ? { ...current, ...patch } : current);
      }
      await this.store.reloadPersonOptions();
      if (this.store.filters().person_id || this.store.filters().manual_faces_need_review || this.store.filters().faces_need_names) {
        await this.store.refreshPaths([path]);
      }
    } catch {
      // The edit itself is saved; a failed re-read leaves the optimistic state until the next load.
    }
  }

  private applyConfirmed(p: Photo, confirmed: Partial<Photo>): void {
    void this.store.loadReviewProgress();
    this.store.patchPhoto(p.path, confirmed);
    // The page may have moved on, or taken another edit, since p was read.
    const current = this.photo();
    if (!this.destroyRef.destroyed && current?.path === p.path) {
      this.photo.set({ ...current, ...confirmed });
    }
  }

  protected async setRating(path: string, rating: number): Promise<void> {
    const p = this.photo();
    if (!p) return;
    const newRating = p.star_rating === rating ? 0 : rating;
    try {
      await firstValueFrom(this.api.post('/photo/set_rating', { photo_path: path, rating: newRating }));
      this.applyConfirmed(p, { star_rating: newRating });
      this.journal.record('rating', [path], newRating);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  @HostListener('document:keydown', ['$event'])
  protected onReviewKey(event: KeyboardEvent): void {
    if (this.dialog.openDialogs.length || isTypingContext(event) || event.ctrlKey || event.metaKey || event.altKey || !this.keymap.matches(event, 'keep') || !this.auth.isEdition()) return;
    event.preventDefault();
    void this.reviewPhoto('kept');
  }

  protected async reviewPhoto(decision: 'kept' | 'undecided'): Promise<void> {
    const p = this.photo();
    if (!p || this.reviewSaving) return;
    this.reviewSaving = true;
    const isOrigin = this.store.captureReviewView();
    const identity = this.auth.identity();
    const photos = this.store.photos();
    const index = photos.findIndex(photo => photo.path === p.path);
    const next = photos[index + 1];
    try {
      await firstValueFrom(this.api.post('/photos/batch_review', { photo_paths: [p.path], decision }));
      if (identity !== this.auth.identity()) return;
      this.applyConfirmed(p, { is_kept: decision === 'kept', is_rejected: false });
      this.journal.record('review', [p.path], decision);
      if (isOrigin()) await this.advanceAfterReview(p, index, next);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    } finally { this.reviewSaving = false; }
  }

  private reviewSaving = false;

  private async advanceAfterReview(previous: Photo, index: number, next?: Photo): Promise<void> {
    if (!this.store.filters().review_status) return;
    let navigated = false;
    const navigation = this.router.events.subscribe(event => {
      if (event instanceof NavigationStart) navigated = true;
    });
    try {
      await this.store.refreshReviewResults(false, { whileParked: true });
      if (navigated || this.destroyRef.destroyed || this.photo()?.path !== previous.path) return;
      const target = this.store.photos().find(photo => photo.path === next?.path) ?? this.store.photos()[index] ?? this.store.photos()[0];
      if (!target) { this.router.navigate(['/']); return; }
      this.router.navigate(['/photo'], { queryParams: { path: target.path }, state: { photo: target }, replaceUrl: true });
      this.photo.set(target);
      this.fullImageLoaded.set(false);
    } finally { navigation.unsubscribe(); }
  }

  protected async toggleFavorite(path: string): Promise<void> {
    const p = this.photo();
    if (!p) return;
    try {
      const res = await firstValueFrom(this.api.post<{ is_favorite: boolean; is_rejected: boolean | null }>('/photo/toggle_favorite', { photo_path: path }));
      const confirmed: Partial<Photo> = { is_favorite: res.is_favorite };
      // null means "the server did not touch this one": leave both readers on
      // the value they hold rather than writing this view's belief over the
      // store's, which may be the fresher of the two.
      if (res.is_rejected !== null) confirmed.is_rejected = res.is_rejected;
      this.applyConfirmed(p, confirmed);
      this.journal.record('favorite', [path], res.is_favorite);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  protected async toggleRejected(path: string): Promise<void> {
    const p = this.photo();
    if (!p) return;
    const isOrigin = this.store.captureReviewView();
    const identity = this.auth.identity();
    const photos = this.store.photos();
    const index = photos.findIndex(photo => photo.path === p.path);
    const next = photos[index + 1];
    try {
      const res = await firstValueFrom(this.api.post<{ is_rejected: boolean; is_favorite: boolean | null; star_rating: number | null }>('/photo/toggle_rejected', { photo_path: path }));
      const confirmed: Partial<Photo> = { is_rejected: res.is_rejected, is_kept: false };
      if (res.is_favorite !== null) confirmed.is_favorite = res.is_favorite;
      if (res.star_rating !== null) confirmed.star_rating = res.star_rating;
      // The write landed: only another principal's view must not see it.
      if (identity !== this.auth.identity()) return;
      this.applyConfirmed(p, confirmed);
      this.journal.record('reject', [path], res.is_rejected);
      if (isOrigin()) await this.advanceAfterReview(p, index, next);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  protected async generateCaption(path: string): Promise<void> {
    this.generatingCaption.set(true);
    try {
      const res = await firstValueFrom(this.api.post<{ caption: string }>('/caption', { path }));
      const p = this.photo();
      // Generation is slow enough to outlive the photo that started it, and the
      // store write now carries a mis-targeted apply out to the grid as well --
      // so confirm the open photo is still the one this call asked about.
      if (p?.path === path) {
        this.translatedCaption.set(null);
        this.applyConfirmed(p, { caption: res.caption, caption_translated: undefined });
      }
    } catch {
      this.snackBar.open(this.i18n.t(I18N.photo_detail.caption_error), '', { duration: 3000 });
      // A failed request resolves an 'auto' VRAM profile, so the config can now hide the button.
      await this.store.refreshConfig();
    } finally {
      this.generatingCaption.set(false);
    }
  }

  /**
   * The Persons list opens the same menu as the photo's faces, on this photo's face
   * of that person (its largest when several), so it works with the boxes off too.
   */
  protected openPersonMenu(person: { id: number; name: string | null }, event: Event): void {
    const face = this.faceLayer()?.faceOf(person.id) ?? null;
    this.personMenu()?.openBelow({ person: { id: person.id, name: person.name }, face }, event.currentTarget as HTMLElement);
  }

  protected async onPersonMenuChanged(path: string): Promise<void> {
    if (!this.destroyRef.destroyed && this.photo()?.path === path) {
      await this.faceLayer()?.load(path);
    }
    await this.refreshPeople(path);
  }

  protected navigateToGallery(filter: string, value: string | number): void {
    this.router.navigate(['/'], { queryParams: { [filter]: String(value) } });
  }

  protected readonly newTag = signal('');

  protected onNewTagInput(event: Event): void {
    this.newTag.set((event.target as HTMLInputElement).value);
  }

  /**
   * Pessimistic: the signal and the store change only once the server accepted the tag.
   * The merge reads the CURRENT photo when the response lands, so overlapping edits compose.
   */
  protected async addManualTag(p: Photo, raw: string): Promise<void> {
    const tag = raw.trim();
    if (!tag) return;
    try {
      const res = await firstValueFrom(
        this.api.put<{ tag: string; skipped_existing: boolean }>('/photo/manual_tags', { path: p.path, tag }));
      this.newTag.set('');
      if (res.skipped_existing) {
        // Nothing was stored: the tag already exists, as a manual tag or as an AI tag.
        this.snackBar.open(this.i18n.t(I18N.manual_tags.already_present), '', { duration: 3000 });
        return;
      }
      this.updateManualTags(p, tags => (tags.includes(res.tag) ? tags : [...tags, res.tag].sort()));
      this.journal.record('tags', [p.path], { action: 'add', tag: res.tag });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  protected async removeManualTag(p: Photo, tag: string): Promise<void> {
    try {
      await firstValueFrom(this.api.delete('/photo/manual_tags', { path: p.path, tag }));
      this.updateManualTags(p, tags => tags.filter(t => t !== tag));
      this.journal.record('tags', [p.path], { action: 'remove', tag });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  /** Applies `change` to the photo's manual tags as they are NOW, not as the caller captured them. */
  private updateManualTags(p: Photo, change: (tags: string[]) => string[]): void {
    const current = this.photo();
    if (current?.path === p.path) {
      this.applyConfirmed(current, { manual_tags: change(current.manual_tags) });
      return;
    }
    // The view moved on to another photo: keep the grid's row right without touching the signal.
    const row = this.store.photos().find(r => r.path === p.path);
    this.store.patchPhoto(p.path, { manual_tags: change(row?.manual_tags ?? p.manual_tags) });
  }

  protected editCaption(p: Photo): void {
    import('./caption-edit-dialog.component').then(m => {
      const ref = this.dialog.open(m.CaptionEditDialogComponent, {
        width: '95vw',
        maxWidth: '500px',
        data: { path: p.path, filename: p.filename, caption: p.caption || '' },
      });
      ref.afterClosed().subscribe(result => {
        if (result !== undefined) {
          this.translatedCaption.set(null);
          this.applyConfirmed(p, { caption: result || null, caption_translated: undefined });
        }
      });
    });
  }

  protected openSimilar(photo: Photo, mode: 'visual' | 'color' | 'person'): void {
    this.router.navigate(['/'], {
      queryParams: { similar_to: photo.path, similarity_mode: mode, min_similarity: '70' },
    });
  }

  protected openCritique(photo: Photo): void {
    this.photoActions.openCritique(photo);
  }

  /**
   * Open the delete confirm dialog and, on confirm, call
   * `PhotoActionsService.deletePhotos` for the single open photo.
   *
   * `hasSiblings`/`hasBracketLead` are read off the already-fetched
   * `photoSet()` rather than a fresh request: a bracket/panorama/hdr_panorama
   * set with more than one member offers the sibling checkbox, and this
   * photo being that set's own bracket-kind lead frame is exactly the
   * condition the endpoint refuses without `includeSequenceSiblings`
   * (decision 7) -- known precisely here, unlike the gallery's bulk
   * selection, which has no per-path lead signal client-side.
   */
  protected deletePhoto(): void {
    const p = this.photo();
    if (!p) return;
    const set = this.photoSet();
    const hasSiblings = !!set?.kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(set.kind) && set.count > 1;
    const hasBracketLead = set?.kind === 'bracket'
      && (set.members.find(m => m.path === p.path)?.is_lead ?? false);
    import('../../shared/components/photo-delete-dialog/photo-delete-dialog.component').then(m => {
      const ref = this.dialog.open(m.PhotoDeleteDialogComponent, {
        width: '95vw',
        maxWidth: '28rem',
        data: {
          surface: 'photo_detail',
          paths: [p.path],
          count: 1,
          hasCompanion: true,
          hasSiblings,
          hasBracketLead,
        },
      });
      ref.afterClosed().subscribe(async result => {
        if (!result) return;
        const res = await this.photoActions.deletePhotos([p.path], result);
        if (!res) return;
        // `removed_missing` counts as deleted for this surface: the row is
        // gone either way, which is all the photo page can observe.
        const gone = res.deleted.includes(p.path) || res.removed_missing.includes(p.path);
        if (gone) {
          this.store.removePhotos([p.path]);
          this.snackBar.open(this.i18n.t(I18N.photo_detail.delete.success), '', { duration: 2000 });
          this.goBack();
        } else {
          this.snackBar.open(this.i18n.t(I18N.photo_detail.delete.error), '', { duration: 3000 });
        }
      });
    });
  }

  protected openCategoryOverride(p: Photo): void {
    import('./category-override-dialog.component').then(m => {
      const ref = this.dialog.open(m.CategoryOverrideDialogComponent, {
        width: '95vw',
        maxWidth: '24rem',
        data: { path: p.path, currentCategory: p.category },
      });
      ref.afterClosed().subscribe((result: CategoryOverrideResult | undefined) => {
        if (result) this.applyConfirmed(p, { category: result.category, aggregate: result.aggregate });
      });
    });
  }

  protected async clearCategoryOverride(p: Photo): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.post<{ new_category: string; aggregate: number }>('/comparison/clear_category_override', { path: p.path }),
      );
      this.applyConfirmed(p, { category: res.new_category, aggregate: res.aggregate });
      this.snackBar.open(this.i18n.t(I18N.photo.category_override.cleared), '', { duration: 3000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  protected toggleExplainer(): void {
    const next = !this.explainerOpen();
    this.explainerOpen.set(next);
    if (next && this.explainerCategories().length === 0) {
      firstValueFrom(this.api.get<{ categories: { name: string }[] }>('/config/category_priorities'))
        .then(res => this.explainerCategories.set(res.categories.map(c => c.name)))
        .catch(() => this.explainerCategories.set([]));
    }
  }

  protected async refreshPhoto(p: Photo): Promise<void> {
    const { current, dispose } = this.staleness.create(this.destroyRef, { valid: () => this.photo()?.path === p.path });
    try {
      const refreshed = await this.photoActions.refreshPhotos([p.path]);
      if (!current() || !refreshed.includes(p.path)) return;
      const photo = await this.fetchPhoto(p.path);
      if (current()) { this.fullImageLoaded.set(false); this.photo.set(photo); }
    } finally { dispose(); }
  }

  protected openAddPerson(photo: Photo): void {
    this.photoActions.openAddPerson(photo, () => {
      this.photo.update(p => p?.path === photo.path ? { ...p, unassigned_faces: Math.max(0, p.unassigned_faces - 1) } : p);
    });
  }

  protected loadCaptureDateDialog() { return import('./capture-date-dialog.component'); }

  protected async editCaptureDate(p: Photo): Promise<void> {
    let opened = false;
    const { current, dispose } = this.staleness.create(this.destroyRef, { valid: () => this.photo()?.path === p.path });
    try {
      const m = await this.loadCaptureDateDialog();
      if (!current()) return;
      const data = { paths: [p.path], count: 1, manuallySet: p.date_manually_set === 1, reference: p.date_taken ? { path: p.path, date: p.date_taken } : null };
      const ref = this.dialog.open(m.CaptureDateDialogComponent, { width: '95vw', maxWidth: '760px', data });
      opened = true;
      ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef), finalize(dispose)).subscribe((result: import('./capture-date-dialog.component').CaptureDateResult | undefined) => {
        if (current() && result !== undefined) this.applyConfirmed(p, result);
      });
    } finally {
      if (!opened) dispose();
    }
  }

  protected loadGpsDialog() { return import('./gps-edit-dialog.component'); }

  protected async editGps(p: Photo): Promise<void> {
    let opened = false;
    const { current, dispose } = this.staleness.create(this.destroyRef, { valid: () => this.photo()?.path === p.path });
    try {
      const m = await this.loadGpsDialog();
      if (!current()) return;
      const ref = this.dialog.open(m.GpsEditDialogComponent, {
        width: '95vw',
        maxWidth: '640px',
        data: {
          path: p.path,
          filename: p.filename,
          lat: p.gps_latitude ?? null,
          lng: p.gps_longitude ?? null,
          manuallySet: p.gps_manually_set === 1,
        },
      });
      opened = true;
      ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef), finalize(dispose)).subscribe((result: { gps_latitude: number | null; gps_longitude: number | null; gps_manually_set?: number } | undefined) => {
        if (current() && result !== undefined) {
          this.applyConfirmed(p, { gps_latitude: result.gps_latitude, gps_longitude: result.gps_longitude, gps_manually_set: result.gps_manually_set ?? 1 });
          if (this.photo()?.path === p.path) this.locationName.set('');
        }
      });
    } finally {
      if (!opened) dispose();
    }
  }
}
