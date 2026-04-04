import { Component, inject, signal, computed, effect, OnInit, HostListener, DestroyRef, ElementRef, viewChild, afterNextRender } from '@angular/core';
import { Location } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { Photo } from '../../shared/models/photo.model';
import { AuthService } from '../../core/services/auth.service';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { PhotoDetailBase } from '../../shared/directives/photo-detail-base.directive';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../shared/pipes/shutter-speed.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { CategoryLabelPipe } from '../gallery/photo-tooltip.component';
import { IsLensNamePipe } from '../../shared/pipes/is-lens-name.pipe';
import { DownloadIconPipe } from '../../shared/pipes/download-icon.pipe';
import { DownloadOption } from '../../shared/models/download.model';
import { downloadAll } from '../../shared/utils/download';
import { GalleryStore } from '../gallery/gallery.store';
import * as L from 'leaflet';
import { createLeafletMap } from '../../shared/leaflet';

@Component({
  selector: 'app-photo-detail',
  imports: [
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatMenuModule,
    MatDialogModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    FixedPipe,
    ShutterSpeedPipe,
    TranslatePipe,
    ThumbnailUrlPipe,
    PersonThumbnailUrlPipe,
    CategoryLabelPipe,
    IsLensNamePipe,
    DownloadIconPipe,
  ],
  template: `
    @if (photo(); as p) {
      <!-- Header bar -->
      <div class="flex items-center gap-2 px-1 py-1 border-b border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)]">
        <button mat-icon-button (click)="goBack()" [matTooltip]="'photo_detail.back' | translate">
          <mat-icon>arrow_back</mat-icon>
        </button>
        <span class="flex-1 truncate font-medium">{{ p.filename }}</span>

        @if (store.config()?.features?.show_similar_button) {
          <button mat-icon-button [matMenuTriggerFor]="similarMenu"
            [matTooltip]="'similar.find_similar' | translate">
            <mat-icon>image_search</mat-icon>
          </button>
          <mat-menu #similarMenu="matMenu">
            <button mat-menu-item (click)="openSimilar(p, 'visual')">
              <mat-icon>image_search</mat-icon> {{ 'similar.mode_visual' | translate }}
            </button>
            <button mat-menu-item (click)="openSimilar(p, 'color')">
              <mat-icon>palette</mat-icon> {{ 'similar.mode_color' | translate }}
            </button>
            <button mat-menu-item (click)="openSimilar(p, 'person')">
              <mat-icon>person_search</mat-icon> {{ 'similar.mode_person' | translate }}
            </button>
          </mat-menu>
        }

        @if (store.config()?.features?.show_critique) {
          <button mat-icon-button (click)="openCritique(p)"
            [matTooltip]="'critique.title' | translate">
            <mat-icon>analytics</mat-icon>
          </button>
        }

        @if (auth.isEdition() && p.unassigned_faces > 0) {
          <button mat-icon-button (click)="openAddPerson(p)"
            [matTooltip]="'manage_persons.assign_face' | translate">
            <mat-icon>person_add</mat-icon>
          </button>
        }

        @if (downloadOptions().length > 1) {
          <button mat-button [matMenuTriggerFor]="downloadMenu" [disabled]="downloading()" [matTooltip]="'photo_detail.download' | translate">
            @if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline" /> } @else { <mat-icon>download</mat-icon> }
            {{ downloading() ? ('photo_detail.downloading' | translate) : ('photo_detail.download' | translate) }}
          </button>
          <mat-menu #downloadMenu="matMenu">
            @for (opt of downloadOptions(); track opt.type + (opt.profile ?? '')) {
              <button mat-menu-item (click)="download(p.path, opt.type, opt.profile)">
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
          <button mat-button (click)="download(p.path)" [disabled]="downloading()" [matTooltip]="'photo_detail.download' | translate">
            @if (downloading()) { <mat-spinner diameter="18" class="!inline-block !align-baseline" /> } @else { <mat-icon>download</mat-icon> }
            {{ downloading() ? ('photo_detail.downloading' | translate) : ('photo_detail.download' | translate) }}
          </button>
        }
      </div>

      <!-- Main content: image + info -->
      <div class="flex flex-col lg:flex-row lg:h-[calc(100%-49px)] lg:overflow-hidden">
        <!-- Image panel -->
        <div #imagePanel class="shrink-0 lg:h-auto lg:flex-1 flex items-center justify-center bg-black lg:min-h-0 relative overflow-hidden cursor-grab"
          [class.cursor-grabbing]="isPanning()"
          (dblclick)="resetZoom()"
          (pointerdown)="onPanStart($event)"
          (pointermove)="onPanMove($event)"
          (pointerup)="onPanEnd($event)"
          (pointercancel)="onPanEnd($event)"
          (touchstart)="onTouchStart($event)"
          (touchend)="onTouchEnd()">
          <img
            [src]="p.path | thumbnailUrl:640"
            [alt]="p.filename"
            class="w-full lg:max-w-full lg:max-h-full object-contain transition-opacity duration-300 pointer-events-none select-none"
            [class.opacity-0]="fullImageLoaded()"
            [style.transform]="zoomTransform()"
          />
          <img
            [src]="fullImageUrl()"
            [alt]="p.filename"
            class="absolute inset-0 w-full h-full object-contain transition-opacity duration-300 pointer-events-none select-none"
            [class.opacity-0]="!fullImageLoaded()"
            (load)="onFullImageLoad()"
            [style.transform]="zoomTransform()"
          />
        </div>

        <!-- Info panel -->
        <div class="lg:w-[380px] lg:shrink-0 lg:overflow-y-auto p-4 space-y-4 text-sm text-[var(--mat-sys-on-surface)]">
          <!-- Filename + Date + Category + Aggregate -->
          <div>
            <div class="font-semibold text-lg">{{ p.filename }}</div>
            @if (p.date_taken) {
              <div class="text-[var(--mat-sys-on-surface-variant)] text-xs">{{ p.date_taken }}</div>
            }
            <div class="flex items-center gap-2 mt-1">
              @if (p.category) {
                <span class="px-2 py-0.5 bg-[var(--mat-sys-primary-container)] text-[var(--mat-sys-on-primary-container)] rounded-full text-xs font-medium">{{ p.category | categoryLabel }}</span>
              }
              <span class="text-[var(--mat-sys-primary)] font-semibold ml-auto">{{ p.aggregate | fixed:1 }}</span>
            </div>
          </div>

          <!-- Rating controls (edition only) -->
          @if (auth.isEdition()) {
            <div class="flex items-center border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <!-- Star rating -->
              @for (star of stars; track star) {
                <button class="w-8 h-8 rounded-full inline-flex items-center justify-center hover:bg-[var(--mat-sys-surface-container-high)] transition-colors cursor-pointer" (click)="setRating(p.path, star)">
                  <mat-icon class="!text-xl !w-5 !h-5 !leading-5 !text-yellow-400">{{ p.star_rating !== null && star <= p.star_rating! ? 'star' : 'star_border' }}</mat-icon>
                </button>
              }
              <div class="flex-1"></div>
              <!-- Favorite -->
              <button mat-icon-button (click)="toggleFavorite(p.path)" [matTooltip]="'photo_detail.favorite' | translate">
                <mat-icon class="!text-red-400">{{ p.is_favorite ? 'favorite' : 'favorite_border' }}</mat-icon>
              </button>
              <!-- Reject -->
              <button mat-icon-button (click)="toggleRejected(p.path)" [class.text-orange-400]="p.is_rejected" [matTooltip]="'photo_detail.rejected' | translate">
                <mat-icon>{{ p.is_rejected ? 'thumb_down' : 'thumb_down_off_alt' }}</mat-icon>
              </button>
            </div>
          }

          <!-- Caption -->
          <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
            <div class="flex items-center justify-between mb-2">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)]">{{ 'photo_detail.caption' | translate }}</div>
              @if (auth.isEdition()) {
                <div class="flex gap-1">
                  @if (!p.caption) {
                    <button mat-icon-button class="!w-7 !h-7 !p-0" (click)="generateCaption(p.path)" [disabled]="generatingCaption()" [matTooltip]="'photo_detail.generate_caption' | translate">
                      @if (generatingCaption()) {
                        <mat-spinner diameter="16" />
                      } @else {
                        <mat-icon class="!text-base !w-4 !h-4 !leading-4">auto_fix_high</mat-icon>
                      }
                    </button>
                  }
                  <button mat-icon-button class="!w-7 !h-7 !p-0" (click)="editCaption(p)" [matTooltip]="'photo_detail.edit_caption' | translate">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">edit</mat-icon>
                  </button>
                </div>
              }
            </div>
            @if (translatingCaption()) {
              <p class="text-[var(--mat-sys-on-surface-variant)] opacity-60 italic text-xs">{{ 'photo_detail.translating_caption' | translate }}</p>
            } @else if (displayCaption()) {
              <p class="text-[var(--mat-sys-on-surface-variant)]">{{ displayCaption() }}</p>
            } @else {
              <p class="text-[var(--mat-sys-on-surface-variant)] opacity-40 italic text-xs">&mdash;</p>
            }
          </div>

          <!-- Quality section -->
          <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
            <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.quality' | translate }}</div>
            <div class="flex flex-col gap-0.5">
              <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.aesthetic' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic | fixed:1 }}</span></div>
              @if (p.quality_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.quality_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.quality_score | fixed:1 }}</span></div>
              }
              @if (p.topiq_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.topiq_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.topiq_score | fixed:1 }}</span></div>
              }
              @if (p.tech_sharpness !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.tech_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.tech_sharpness | fixed:1 }}</span></div>
              }
              @if (p.face_count > 0 && p.face_quality !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_quality' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality | fixed:1 }}</span></div>
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.faces' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_count }}</span></div>
                @if (p.face_ratio) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_ratio' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_ratio * 100 | fixed:0 }}%</span></div>
                }
                @if (p.face_sharpness !== null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_sharpness | fixed:1 }}</span></div>
                }
                @if (p.eye_sharpness !== null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.eye_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.eye_sharpness | fixed:1 }}</span></div>
                }
                @if (p.face_confidence !== null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_confidence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_confidence * 100 | fixed:0 }}%</span></div>
                }
              }
              @if (p.aesthetic_iaa !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.aesthetic_iaa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic_iaa | fixed:1 }}</span></div>
              }
              @if (p.face_quality_iqa !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_quality_iqa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality_iqa | fixed:1 }}</span></div>
              }
              @if (p.liqe_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.liqe_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.liqe_score | fixed:1 }}</span></div>
              }
            </div>
          </div>

          <!-- Composition section -->
          <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
            <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.composition' | translate }}</div>
            <div class="flex flex-col gap-0.5">
              @if (p.comp_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.composition' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.comp_score | fixed:1 }}</span></div>
              }
              @if (p.composition_pattern) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.pattern' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ ('composition_patterns.' + p.composition_pattern) | translate }}</span></div>
              }
              @if (p.power_point_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.power_points' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.power_point_score | fixed:1 }}</span></div>
              }
              @if (p.leading_lines_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.leading_lines' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.leading_lines_score | fixed:1 }}</span></div>
              }
              @if (p.isolation_bonus !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.isolation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.isolation_bonus | fixed:1 }}</span></div>
              }
            </div>
          </div>

          <!-- Subject Saliency section -->
          @if (p.subject_sharpness !== null || p.subject_prominence !== null || p.subject_placement !== null || p.bg_separation !== null) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.saliency' | translate }}</div>
              <div class="flex flex-col gap-0.5">
                @if (p.subject_sharpness !== null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.subject_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_sharpness | fixed:1 }}</span></div>
                }
                @if (p.subject_prominence !== null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.subject_prominence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_prominence | fixed:1 }}</span></div>
                }
                @if (p.subject_placement !== null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.subject_placement' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_placement | fixed:1 }}</span></div>
                }
                @if (p.bg_separation !== null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.bg_separation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.bg_separation | fixed:1 }}</span></div>
                }
              </div>
            </div>
          }

          <!-- Technical section -->
          <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
            <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.technical' | translate }}</div>
            <div class="flex flex-col gap-0.5">
              @if (p.exposure_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.exposure' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.exposure_score | fixed:1 }}</span></div>
              }
              @if (p.color_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.color' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.color_score | fixed:1 }}</span></div>
              }
              @if (p.contrast_score !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.contrast' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.contrast_score | fixed:1 }}</span></div>
              }
              @if (p.dynamic_range_stops !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.dynamic_range' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.dynamic_range_stops | fixed:1 }}</span></div>
              }
              @if (p.mean_saturation !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.saturation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ (p.mean_saturation * 100) | fixed:0 }}%</span></div>
              }
              @if (p.noise_sigma !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.noise' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.noise_sigma | fixed:1 }}</span></div>
              }
              @if (p.mean_luminance !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.luminance' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.mean_luminance * 100 | fixed:0 }}%</span></div>
              }
              @if (p.histogram_spread !== null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.histogram_spread' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.histogram_spread | fixed:1 }}</span></div>
              }
            </div>
          </div>

          <!-- EXIF section -->
          @if (hasExif()) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.exif' | translate }}</div>
              <div class="flex flex-col gap-0.5">
                @if (p.camera_model) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.camera' | translate }}</span><span class="val truncate">{{ p.camera_model }}</span></div>
                }
                @if (p.lens_model && (p.lens_model | isLensName)) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.lens' | translate }}</span><span class="val truncate">{{ p.lens_model }}</span></div>
                }
                @if (p.focal_length) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.focal' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.focal_length }}mm</span></div>
                }
                @if (p.f_stop) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.aperture' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">f/{{ p.f_stop }}</span></div>
                }
                @if (p.shutter_speed) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.shutter' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.shutter_speed | shutterSpeed }}</span></div>
                }
                @if (p.iso) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.iso' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.iso }}</span></div>
                }
              </div>
            </div>
          }

          <!-- Location -->
          @if (p.gps_latitude !== null && p.gps_longitude !== null) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="flex items-center justify-between mb-2">
                <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)]">{{ 'photo_detail.location' | translate }}</div>
                @if (auth.isEdition()) {
                  <button mat-icon-button class="!w-7 !h-7 !p-0" (click)="editGps(p)" [matTooltip]="'photo_detail.edit_location' | translate">
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
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="flex items-center justify-between">
                <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)]">{{ 'photo_detail.location' | translate }}</div>
                <button mat-icon-button class="!w-7 !h-7 !p-0" (click)="editGps(p)" [matTooltip]="'photo_detail.add_location' | translate">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">add_location</mat-icon>
                </button>
              </div>
              <p class="text-[var(--mat-sys-on-surface-variant)] opacity-40 italic text-xs">&mdash;</p>
            </div>
          }

          <!-- Tags section -->
          @if (p.tags_list.length) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.tags' | translate }}</div>
              <div class="flex gap-1.5 flex-wrap">
                @for (tag of p.tags_list; track tag) {
                  <button class="px-2 py-0.5 bg-[var(--facet-accent-badge)] text-[var(--facet-accent-text)] rounded-full text-xs cursor-pointer hover:opacity-80 transition-opacity"
                          (click)="navigateToGallery('tag', tag)">{{ tag }}</button>
                }
              </div>
            </div>
          }

          <!-- Persons section -->
          @if (p.persons.length) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.persons' | translate }}</div>
              <div class="flex gap-3 flex-wrap">
                @for (person of p.persons; track person.id) {
                  <button class="flex flex-col items-center gap-1 cursor-pointer hover:opacity-80 transition-opacity"
                          (click)="navigateToGallery('person_id', person.id)">
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
        </div>
      </div>
    } @else {
      <div class="flex items-center justify-center h-full">
        <mat-icon class="!text-4xl text-[var(--mat-sys-on-surface-variant)]">hourglass_empty</mat-icon>
      </div>
    }
  `,
  host: { class: 'block h-full overflow-y-auto lg:overflow-y-hidden' },
})
export class PhotoDetailComponent extends PhotoDetailBase implements OnInit {
  private readonly location = inject(Location);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  protected readonly auth = inject(AuthService);
  protected readonly store = inject(GalleryStore);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  private readonly photoActions = inject(PhotoActionsService);

  readonly photo = signal<Photo | null>(null);
  protected readonly downloading = signal(false);
  protected readonly downloadOptions = signal<DownloadOption[]>([]);
  protected readonly generatingCaption = signal(false);
  protected readonly stars: readonly number[] = [1, 2, 3, 4, 5];

  // Zoom & pan state
  private readonly imagePanel = viewChild<ElementRef<HTMLDivElement>>('imagePanel');
  protected readonly zoomScale = signal(1);
  protected readonly panX = signal(0);
  protected readonly panY = signal(0);
  protected readonly isPanning = signal(false);
  protected readonly zoomTransform = computed(() => {
    const s = this.zoomScale();
    const x = this.panX();
    const y = this.panY();
    return s === 1 && x === 0 && y === 0 ? '' : `scale(${s}) translate(${x}px, ${y}px)`;
  });
  private panStartX = 0;
  private panStartY = 0;
  private panOriginX = 0;
  private panOriginY = 0;
  private lastPinchDist = 0;

  // Download options
  private downloadOptionsEffect = effect(() => {
    const p = this.photo();
    if (!p) { this.downloadOptions.set([]); return; }
    if (!this.auth.downloadProfiles().length) {
      this.downloadOptions.set([{ type: 'original', label: 'original' }]);
      return;
    }
    firstValueFrom(this.api.get<{ options: DownloadOption[] }>('/download/options', { path: p.path }))
      .then(res => this.downloadOptions.set(res.options))
      .catch(() => this.downloadOptions.set([{ type: 'original', label: 'original' }]));
  });

  // Location
  protected readonly locationName = signal('');
  private locationNameEffect = effect(() => {
    const p = this.photo();
    if (!p || p.gps_latitude == null || p.gps_longitude == null) {
      this.locationName.set('');
      return;
    }
    firstValueFrom(this.api.get<{ display_name: string }>('/filter_options/location_name', {
      lat: String(p.gps_latitude), lng: String(p.gps_longitude),
    }))
      .then(res => this.locationName.set(res.display_name || ''))
      .catch(() => this.locationName.set(''));
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
    // Register wheel and touchmove as non-passive so preventDefault() works
    afterNextRender(() => {
      const el = this.imagePanel()?.nativeElement;
      if (!el) return;
      el.addEventListener('wheel', (e: WheelEvent) => this.onWheel(e), { passive: false });
      el.addEventListener('touchmove', (e: TouchEvent) => this.onTouchMove(e), { passive: false });
    });
  }

  async ngOnInit(): Promise<void> {
    // Try router state (passed from gallery via navigate(..., { state }))
    const statePhoto = history.state?.['photo'] as Photo | undefined;

    if (statePhoto) {
      this.photo.set(statePhoto);
    } else {
      // Fallback: load from API using query param
      const path = this.route.snapshot.queryParamMap.get('path');
      if (path) {
        try {
          const photo = await firstValueFrom(this.api.get<Photo>('/photo', { path }));
          // Ensure tags_list exists
          if (!photo.tags_list) {
            photo.tags_list = photo.tags ? photo.tags.split(',').map(t => t.trim()) : [];
          }
          if (!photo.persons) {
            photo.persons = [];
          }
          this.photo.set(photo);
        } catch {
          this.router.navigate(['/']);
        }
      } else {
        this.router.navigate(['/']);
      }
    }
  }

  @HostListener('document:keydown.escape')
  protected goBack(): void {
    this.location.back();
  }

  @HostListener('document:keydown.arrowleft')
  protected prevPhoto(): void {
    this.navigateAdjacentPhoto(-1);
  }

  @HostListener('document:keydown.arrowright')
  protected nextPhoto(): void {
    this.navigateAdjacentPhoto(1);
  }

  private navigateAdjacentPhoto(delta: number): void {
    const current = this.photo();
    if (!current) return;
    const photos = this.store.photos();
    if (photos.length === 0) return;
    const idx = photos.findIndex(p => p.path === current.path);
    if (idx === -1) return;
    const nextIdx = idx + delta;
    if (nextIdx < 0 || nextIdx >= photos.length) return;
    const next = photos[nextIdx];
    this.router.navigate(['/photo'], {
      queryParams: { path: next.path },
      state: { photo: next },
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

  protected async setRating(path: string, rating: number): Promise<void> {
    const p = this.photo();
    if (!p) return;
    const newRating = p.star_rating === rating ? 0 : rating;
    await firstValueFrom(this.api.post('/photo/set_rating', { photo_path: path, rating: newRating }));
    this.photo.set({ ...p, star_rating: newRating });
  }

  protected async toggleFavorite(path: string): Promise<void> {
    const p = this.photo();
    if (!p) return;
    const res = await firstValueFrom(this.api.post<{ is_favorite: boolean; is_rejected: boolean | null }>('/photo/toggle_favorite', { photo_path: path }));
    this.photo.set({ ...p, is_favorite: res.is_favorite, is_rejected: res.is_rejected === null ? p.is_rejected : res.is_rejected });
  }

  protected async toggleRejected(path: string): Promise<void> {
    const p = this.photo();
    if (!p) return;
    const res = await firstValueFrom(this.api.post<{ is_rejected: boolean; is_favorite: boolean | null }>('/photo/toggle_rejected', { photo_path: path }));
    this.photo.set({ ...p, is_rejected: res.is_rejected, is_favorite: res.is_favorite === null ? p.is_favorite : res.is_favorite });
  }

  protected async generateCaption(path: string): Promise<void> {
    this.generatingCaption.set(true);
    try {
      const res = await firstValueFrom(this.api.get<{ caption: string }>('/caption', { path }));
      const p = this.photo();
      if (p) {
        this.translatedCaption.set(null);
        this.photo.set({ ...p, caption: res.caption, caption_translated: undefined });
      }
    } catch {
      this.snackBar.open(this.i18n.t('photo_detail.caption_error'), '', { duration: 3000 });
    } finally {
      this.generatingCaption.set(false);
    }
  }

  protected navigateToGallery(filter: string, value: string | number): void {
    this.router.navigate(['/'], { queryParams: { [filter]: String(value) } });
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
          this.photo.set({ ...p, caption: result || null, caption_translated: undefined });
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

  protected openAddPerson(photo: Photo): void {
    this.photoActions.openAddPerson(photo, () => {
      this.photo.update(p => p ? { ...p, unassigned_faces: Math.max(0, p.unassigned_faces - 1) } : p);
    });
  }

  protected editGps(p: Photo): void {
    import('./gps-edit-dialog.component').then(m => {
      const ref = this.dialog.open(m.GpsEditDialogComponent, {
        width: '95vw',
        maxWidth: '500px',
        data: {
          path: p.path,
          filename: p.filename,
          lat: p.gps_latitude ?? null,
          lng: p.gps_longitude ?? null,
        },
      });
      ref.afterClosed().subscribe((result: { gps_latitude: number | null; gps_longitude: number | null } | undefined) => {
        if (result !== undefined) {
          this.photo.set({ ...p, gps_latitude: result.gps_latitude ?? undefined, gps_longitude: result.gps_longitude ?? undefined });
          this.locationName.set('');
        }
      });
    });
  }

  // Zoom & pan

  private applyZoom(raw: number): void {
    const clamped = Math.min(5, Math.max(0.5, raw));
    if (clamped === 1) { this.panX.set(0); this.panY.set(0); }
    this.zoomScale.set(clamped);
  }

  protected onWheel(e: WheelEvent): void {
    e.preventDefault();
    this.applyZoom(this.zoomScale() + (e.deltaY > 0 ? -0.15 : 0.15));
  }

  protected resetZoom(): void {
    this.zoomScale.set(1);
    this.panX.set(0);
    this.panY.set(0);
  }

  protected onPanStart(e: PointerEvent): void {
    if (this.zoomScale() <= 1) return;
    this.isPanning.set(true);
    this.panStartX = e.clientX;
    this.panStartY = e.clientY;
    this.panOriginX = this.panX();
    this.panOriginY = this.panY();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }

  protected onPanMove(e: PointerEvent): void {
    if (!this.isPanning()) return;
    const scale = this.zoomScale();
    const rawX = this.panOriginX + (e.clientX - this.panStartX) / scale;
    const rawY = this.panOriginY + (e.clientY - this.panStartY) / scale;
    // Clamp pan so the image can't be dragged entirely off-screen
    const el = this.imagePanel()?.nativeElement;
    if (el) {
      const limit = Math.max(el.clientWidth, el.clientHeight) / (2 * scale);
      this.panX.set(Math.max(-limit, Math.min(limit, rawX)));
      this.panY.set(Math.max(-limit, Math.min(limit, rawY)));
    } else {
      this.panX.set(rawX);
      this.panY.set(rawY);
    }
  }

  protected onPanEnd(e: PointerEvent): void {
    if (!this.isPanning()) return;
    this.isPanning.set(false);
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
  }

  protected onTouchStart(e: TouchEvent): void {
    if (e.touches.length === 2) {
      this.lastPinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
    }
  }

  protected onTouchMove(e: TouchEvent): void {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
      if (this.lastPinchDist > 0) {
        this.applyZoom(this.zoomScale() * (dist / this.lastPinchDist));
      }
      this.lastPinchDist = dist;
    }
  }

  protected onTouchEnd(): void {
    this.lastPinchDist = 0;
  }
}
