import {
  Component,
  Pipe,
  PipeTransform,
  inject,
  computed,
  signal,
  OnInit,
  OnDestroy,
  ElementRef,
  viewChild,
  afterNextRender,
  effect,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { MatSelectModule } from '@angular/material/select';
import { MatSliderModule } from '@angular/material/slider';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { GalleryStore, Photo } from './gallery.store';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../shared/pipes/shutter-speed.pipe';
import { StarArrayPipe, IsStarFilledPipe } from '../../shared/pipes/star-rating.pipe';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { FaceSelectorDialogComponent } from './face-selector-dialog.component';
import { PersonSelectorDialogComponent } from './person-selector-dialog.component';
import { SimilarPhotosDialogComponent } from './similar-photos-dialog.component';
import { ConfirmDialogComponent } from '../persons/manage-persons.component';
import { SlideshowComponent } from './slideshow.component';

@Pipe({ name: 'scoreClass', standalone: true, pure: true })
export class ScoreClassPipe implements PipeTransform {
  transform(score: number, config: { quality_thresholds?: { excellent: number; great: number; good: number } } | null): string {
    const thresholds = config?.quality_thresholds;
    if (thresholds) {
      if (score >= thresholds.excellent) return 'bg-green-600 text-white';
      if (score >= thresholds.great) return 'bg-yellow-600 text-white';
      if (score >= thresholds.good) return 'bg-orange-600 text-white';
      return 'bg-red-600 text-white';
    }
    if (score >= 8) return 'bg-green-600 text-white';
    if (score >= 6) return 'bg-yellow-600 text-white';
    if (score >= 4) return 'bg-orange-600 text-white';
    return 'bg-red-600 text-white';
  }
}

/** Return the score value for the current sort column (falls back to aggregate). */
@Pipe({ name: 'sortScore', standalone: true, pure: true })
export class SortScorePipe implements PipeTransform {
  transform(photo: Photo, sort: string): number {
    const val = (photo as unknown as Record<string, unknown>)[sort];
    return typeof val === 'number' ? val : photo.aggregate;
  }
}

@Pipe({ name: 'isSelected', standalone: true, pure: true })
export class IsSelectedPipe implements PipeTransform {
  transform(path: string, selectedPaths: Set<string>): boolean {
    return selectedPaths.has(path);
  }
}

@Component({
  selector: 'app-gallery',
  imports: [
    FormsModule,
    MatSidenavModule,
    MatSelectModule,
    MatSliderModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatFormFieldModule,
    MatCheckboxModule,
    MatInputModule,
    MatDialogModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    PersonThumbnailUrlPipe,
    FixedPipe,
    ShutterSpeedPipe,
    ScoreClassPipe,
    SortScorePipe,
    IsSelectedPipe,
    StarArrayPipe,
    IsStarFilledPipe,
    MatSnackBarModule,
    PhotoTooltipComponent,
    SlideshowComponent,
  ],
  template: `
    <mat-sidenav-container class="h-full">
      <!-- Filter sidebar -->
      <mat-sidenav #filterDrawer disableClose="false" mode="side" position="end" class="w-[min(320px,100vw)] p-0"
        (openedChange)="onFilterDrawerChange($event)">
        <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--mat-sys-outline-variant)]">
          <span class="text-base font-medium">{{ 'gallery.filters' | translate }}</span>
          <button mat-icon-button (click)="store.filterDrawerOpen.set(false)">
            <mat-icon>close</mat-icon>
          </button>
        </div>

        <div #filterScrollArea class="overflow-y-auto p-4 flex flex-col gap-1 max-h-[calc(100vh-120px)]">
          <!-- Display Options -->
          <details open class="group/section">
            <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
              {{ 'gallery.sidebar.display' | translate }}
              <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
            </summary>
            <div class="flex flex-col gap-2 pb-2">
              <mat-checkbox
                [checked]="store.filters().hide_details"
                (change)="store.updateFilter('hide_details', $event.checked)"
              >{{ 'gallery.hide_details' | translate }}</mat-checkbox>
              <mat-checkbox
                [checked]="store.filters().hide_blinks"
                (change)="store.updateFilter('hide_blinks', $event.checked)"
              >{{ 'gallery.hide_blinks' | translate }}</mat-checkbox>
              <mat-checkbox
                [checked]="store.filters().hide_bursts"
                (change)="store.updateFilter('hide_bursts', $event.checked)"
              >{{ 'gallery.hide_bursts' | translate }}</mat-checkbox>
              <mat-checkbox
                [checked]="store.filters().hide_duplicates"
                (change)="store.updateFilter('hide_duplicates', $event.checked)"
              >{{ 'gallery.hide_duplicates' | translate }}</mat-checkbox>
              <mat-checkbox
                [checked]="store.filters().hide_rejected"
                (change)="store.updateFilter('hide_rejected', $event.checked)"
              >{{ 'gallery.hide_rejected' | translate }}</mat-checkbox>
              <mat-checkbox
                [checked]="store.filters().favorites_only"
                (change)="store.updateFilter('favorites_only', $event.checked)"
              >{{ 'gallery.favorites_only' | translate }}</mat-checkbox>
              <mat-checkbox
                [checked]="store.filters().is_monochrome"
                (change)="store.updateFilter('is_monochrome', $event.checked)"
              >{{ 'gallery.monochrome_only' | translate }}</mat-checkbox>
            </div>
          </details>

          <!-- Equipment -->
          @if (store.cameras().length || store.lenses().length) {
            <details open class="group/section">
              <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
                {{ 'gallery.sidebar.equipment' | translate }}
                <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
              </summary>
              <div class="flex flex-col gap-2 pb-2">
                @if (store.cameras().length) {
                  <mat-form-field subscriptSizing="dynamic" class="w-full">
                    <mat-label>{{ 'gallery.camera' | translate }}</mat-label>
                    <mat-select [value]="store.filters().camera" (selectionChange)="store.updateFilter('camera', $event.value)">
                      <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                      @for (c of store.cameras(); track c.value) {
                        <mat-option [value]="c.value">{{ c.value }} ({{ c.count }})</mat-option>
                      }
                    </mat-select>
                  </mat-form-field>
                }
                @if (store.lenses().length) {
                  <mat-form-field subscriptSizing="dynamic" class="w-full">
                    <mat-label>{{ 'gallery.lens' | translate }}</mat-label>
                    <mat-select [value]="store.filters().lens" (selectionChange)="store.updateFilter('lens', $event.value)">
                      <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                      @for (l of store.lenses(); track l.value) {
                        <mat-option [value]="l.value">{{ l.value }} ({{ l.count }})</mat-option>
                      }
                    </mat-select>
                  </mat-form-field>
                }
              </div>
            </details>
          }

          <!-- Content -->
          @if (store.tags().length || store.patterns().length) {
            <details open class="group/section">
              <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
                {{ 'gallery.sidebar.content' | translate }}
                <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
              </summary>
              <div class="flex flex-col gap-2 pb-2">
                @if (store.tags().length) {
                  <mat-form-field subscriptSizing="dynamic" class="w-full">
                    <mat-label>{{ 'gallery.tag' | translate }}</mat-label>
                    <mat-select [value]="store.filters().tag" (selectionChange)="store.updateFilter('tag', $event.value)">
                      <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                      @for (t of store.tags(); track t.value) {
                        <mat-option [value]="t.value">{{ t.value }} ({{ t.count }})</mat-option>
                      }
                    </mat-select>
                  </mat-form-field>
                }
                @if (store.patterns().length) {
                  <mat-form-field subscriptSizing="dynamic" class="w-full">
                    <mat-label>{{ 'gallery.composition_pattern' | translate }}</mat-label>
                    <mat-select [value]="store.filters().composition_pattern" (selectionChange)="store.updateFilter('composition_pattern', $event.value)">
                      <mat-option value="">{{ 'gallery.all' | translate }}</mat-option>
                      @for (p of store.patterns(); track p.value) {
                        <mat-option [value]="p.value">{{ ('composition_patterns.' + p.value) | translate }} ({{ p.count }})</mat-option>
                      }
                    </mat-select>
                  </mat-form-field>
                }
              </div>
            </details>
          }

          <!-- Date Range -->
          <details class="group/section">
            <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
              {{ 'gallery.sidebar.date' | translate }}
              <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
            </summary>
            <div class="flex flex-col gap-2 pb-2">
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ 'gallery.date_from' | translate }}</mat-label>
                <input matInput type="date" [value]="store.filters().date_from" (change)="onDateChange('date_from', $event)" />
              </mat-form-field>
              <mat-form-field subscriptSizing="dynamic" class="w-full">
                <mat-label>{{ 'gallery.date_to' | translate }}</mat-label>
                <input matInput type="date" [value]="store.filters().date_to" (change)="onDateChange('date_to', $event)" />
              </mat-form-field>
            </div>
          </details>

          <!-- Quality -->
          <details open class="group/section">
            <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
              {{ 'gallery.sidebar.quality' | translate }}
              <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
            </summary>
            <div class="flex flex-col gap-2 pb-2">
              <!-- Aggregate -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.score_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_score ? +store.filters().min_score : 0" (valueChange)="onRangeChange('min_score', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_score ? +store.filters().max_score : 10" (valueChange)="onRangeChange('max_score', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_score || '0' }}-{{ store.filters().max_score || '10' }}</span>
                </div>
              </div>
              <!-- Aesthetic -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.aesthetic_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_aesthetic ? +store.filters().min_aesthetic : 0" (valueChange)="onRangeChange('min_aesthetic', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_aesthetic ? +store.filters().max_aesthetic : 10" (valueChange)="onRangeChange('max_aesthetic', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_aesthetic || '0' }}-{{ store.filters().max_aesthetic || '10' }}</span>
                </div>
              </div>
              <!-- Quality Score -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.quality_score_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_quality_score ? +store.filters().min_quality_score : 0" (valueChange)="onRangeChange('min_quality_score', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_quality_score ? +store.filters().max_quality_score : 10" (valueChange)="onRangeChange('max_quality_score', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_quality_score || '0' }}-{{ store.filters().max_quality_score || '10' }}</span>
                </div>
              </div>
            </div>
          </details>

          <!-- Face Metrics -->
          <details class="group/section">
            <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
              {{ 'gallery.sidebar.face' | translate }}
              <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
            </summary>
            <div class="flex flex-col gap-2 pb-2">
              <!-- Face Count -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.face_count_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="20" step="1" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_face_count ? +store.filters().min_face_count : 0" (valueChange)="onExifRangeChange('min_face_count', $event, 0)" />
                    <input matSliderEndThumb [value]="store.filters().max_face_count ? +store.filters().max_face_count : 20" (valueChange)="onExifRangeChange('max_face_count', $event, 20)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_face_count || '0' }}-{{ store.filters().max_face_count || '20' }}</span>
                </div>
              </div>
              <!-- Face Quality -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.face_quality_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_face_quality ? +store.filters().min_face_quality : 0" (valueChange)="onRangeChange('min_face_quality', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_face_quality ? +store.filters().max_face_quality : 10" (valueChange)="onRangeChange('max_face_quality', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_face_quality || '0' }}-{{ store.filters().max_face_quality || '10' }}</span>
                </div>
              </div>
              <!-- Eye Sharpness -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.eye_sharpness_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_eye_sharpness ? +store.filters().min_eye_sharpness : 0" (valueChange)="onRangeChange('min_eye_sharpness', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_eye_sharpness ? +store.filters().max_eye_sharpness : 10" (valueChange)="onRangeChange('max_eye_sharpness', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_eye_sharpness || '0' }}-{{ store.filters().max_eye_sharpness || '10' }}</span>
                </div>
              </div>
              <!-- Face Sharpness -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.face_sharpness_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_face_sharpness ? +store.filters().min_face_sharpness : 0" (valueChange)="onRangeChange('min_face_sharpness', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_face_sharpness ? +store.filters().max_face_sharpness : 10" (valueChange)="onRangeChange('max_face_sharpness', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_face_sharpness || '0' }}-{{ store.filters().max_face_sharpness || '10' }}</span>
                </div>
              </div>
              <!-- Face Ratio -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.face_ratio_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="1" step="0.01" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_face_ratio ? +store.filters().min_face_ratio : 0" (valueChange)="onExifRangeChange('min_face_ratio', $event, 0)" />
                    <input matSliderEndThumb [value]="store.filters().max_face_ratio ? +store.filters().max_face_ratio : 1" (valueChange)="onExifRangeChange('max_face_ratio', $event, 1)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_face_ratio || '0' }}-{{ store.filters().max_face_ratio || '1' }}</span>
                </div>
              </div>
              <!-- Face Confidence -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.face_confidence_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="1" step="0.01" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_face_confidence ? +store.filters().min_face_confidence : 0" (valueChange)="onExifRangeChange('min_face_confidence', $event, 0)" />
                    <input matSliderEndThumb [value]="store.filters().max_face_confidence ? +store.filters().max_face_confidence : 1" (valueChange)="onExifRangeChange('max_face_confidence', $event, 1)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_face_confidence || '0' }}-{{ store.filters().max_face_confidence || '1' }}</span>
                </div>
              </div>
            </div>
          </details>

          <!-- Composition -->
          <details class="group/section">
            <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
              {{ 'gallery.sidebar.composition' | translate }}
              <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
            </summary>
            <div class="flex flex-col gap-2 pb-2">
              <!-- Composition Score -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.composition_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_composition ? +store.filters().min_composition : 0" (valueChange)="onRangeChange('min_composition', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_composition ? +store.filters().max_composition : 10" (valueChange)="onRangeChange('max_composition', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_composition || '0' }}-{{ store.filters().max_composition || '10' }}</span>
                </div>
              </div>
              <!-- Power Points -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.power_point_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_power_point ? +store.filters().min_power_point : 0" (valueChange)="onRangeChange('min_power_point', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_power_point ? +store.filters().max_power_point : 10" (valueChange)="onRangeChange('max_power_point', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_power_point || '0' }}-{{ store.filters().max_power_point || '10' }}</span>
                </div>
              </div>
              <!-- Leading Lines -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.leading_lines_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_leading_lines ? +store.filters().min_leading_lines : 0" (valueChange)="onRangeChange('min_leading_lines', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_leading_lines ? +store.filters().max_leading_lines : 10" (valueChange)="onRangeChange('max_leading_lines', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_leading_lines || '0' }}-{{ store.filters().max_leading_lines || '10' }}</span>
                </div>
              </div>
              <!-- Isolation -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.isolation_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_isolation ? +store.filters().min_isolation : 0" (valueChange)="onRangeChange('min_isolation', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_isolation ? +store.filters().max_isolation : 10" (valueChange)="onRangeChange('max_isolation', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_isolation || '0' }}-{{ store.filters().max_isolation || '10' }}</span>
                </div>
              </div>
            </div>
          </details>

          <!-- Technical -->
          <details class="group/section">
            <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
              {{ 'gallery.sidebar.technical' | translate }}
              <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
            </summary>
            <div class="flex flex-col gap-2 pb-2">
              <!-- Sharpness -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.sharpness_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_sharpness ? +store.filters().min_sharpness : 0" (valueChange)="onRangeChange('min_sharpness', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_sharpness ? +store.filters().max_sharpness : 10" (valueChange)="onRangeChange('max_sharpness', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_sharpness || '0' }}-{{ store.filters().max_sharpness || '10' }}</span>
                </div>
              </div>
              <!-- Exposure -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.exposure_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_exposure ? +store.filters().min_exposure : 0" (valueChange)="onRangeChange('min_exposure', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_exposure ? +store.filters().max_exposure : 10" (valueChange)="onRangeChange('max_exposure', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_exposure || '0' }}-{{ store.filters().max_exposure || '10' }}</span>
                </div>
              </div>
              <!-- Color -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.color_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_color ? +store.filters().min_color : 0" (valueChange)="onRangeChange('min_color', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_color ? +store.filters().max_color : 10" (valueChange)="onRangeChange('max_color', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_color || '0' }}-{{ store.filters().max_color || '10' }}</span>
                </div>
              </div>
              <!-- Contrast -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.contrast_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_contrast ? +store.filters().min_contrast : 0" (valueChange)="onRangeChange('min_contrast', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_contrast ? +store.filters().max_contrast : 10" (valueChange)="onRangeChange('max_contrast', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_contrast || '0' }}-{{ store.filters().max_contrast || '10' }}</span>
                </div>
              </div>
              <!-- Saturation -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.saturation_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="1" step="0.01" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_saturation ? +store.filters().min_saturation : 0" (valueChange)="onExifRangeChange('min_saturation', $event, 0)" />
                    <input matSliderEndThumb [value]="store.filters().max_saturation ? +store.filters().max_saturation : 1" (valueChange)="onExifRangeChange('max_saturation', $event, 1)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_saturation || '0' }}-{{ store.filters().max_saturation || '1' }}</span>
                </div>
              </div>
              <!-- Noise -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.noise_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="20" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_noise ? +store.filters().min_noise : 0" (valueChange)="onExifRangeChange('min_noise', $event, 0)" />
                    <input matSliderEndThumb [value]="store.filters().max_noise ? +store.filters().max_noise : 20" (valueChange)="onExifRangeChange('max_noise', $event, 20)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_noise || '0' }}-{{ store.filters().max_noise || '20' }}</span>
                </div>
              </div>
            </div>
          </details>

          <!-- Exposure & Range -->
          <details class="group/section">
            <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
              {{ 'gallery.sidebar.exposure_range' | translate }}
              <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
            </summary>
            <div class="flex flex-col gap-2 pb-2">
              <!-- Dynamic Range -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.dynamic_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="15" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_dynamic_range ? +store.filters().min_dynamic_range : 0" (valueChange)="onExifRangeChange('min_dynamic_range', $event, 0)" />
                    <input matSliderEndThumb [value]="store.filters().max_dynamic_range ? +store.filters().max_dynamic_range : 15" (valueChange)="onExifRangeChange('max_dynamic_range', $event, 15)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_dynamic_range || '0' }}-{{ store.filters().max_dynamic_range || '15' }} EV</span>
                </div>
              </div>
              <!-- Luminance -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.luminance_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="1" step="0.01" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_luminance ? +store.filters().min_luminance : 0" (valueChange)="onExifRangeChange('min_luminance', $event, 0)" />
                    <input matSliderEndThumb [value]="store.filters().max_luminance ? +store.filters().max_luminance : 1" (valueChange)="onExifRangeChange('max_luminance', $event, 1)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_luminance || '0' }}-{{ store.filters().max_luminance || '1' }}</span>
                </div>
              </div>
              <!-- Histogram Spread -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.histogram_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="10" step="0.5" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_histogram_spread ? +store.filters().min_histogram_spread : 0" (valueChange)="onRangeChange('min_histogram_spread', $event)" />
                    <input matSliderEndThumb [value]="store.filters().max_histogram_spread ? +store.filters().max_histogram_spread : 10" (valueChange)="onRangeChange('max_histogram_spread', $event)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_histogram_spread || '0' }}-{{ store.filters().max_histogram_spread || '10' }}</span>
                </div>
              </div>
              <!-- ISO -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.iso_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="50" max="25600" step="50" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_iso ? +store.filters().min_iso : 50" (valueChange)="onExifRangeChange('min_iso', $event, 50)" />
                    <input matSliderEndThumb [value]="store.filters().max_iso ? +store.filters().max_iso : 25600" (valueChange)="onExifRangeChange('max_iso', $event, 25600)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-20 text-right">{{ store.filters().min_iso || '50' }}-{{ store.filters().max_iso || '25600' }}</span>
                </div>
              </div>
              <!-- Aperture -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.aperture_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0.7" max="64" step="0.1" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_aperture ? +store.filters().min_aperture : 0.7" (valueChange)="onExifRangeChange('min_aperture', $event, 0.7)" />
                    <input matSliderEndThumb [value]="store.filters().max_aperture ? +store.filters().max_aperture : 64" (valueChange)="onExifRangeChange('max_aperture', $event, 64)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-20 text-right">f/{{ store.filters().min_aperture || '0.7' }}-{{ store.filters().max_aperture || '64' }}</span>
                </div>
              </div>
              <!-- Focal Length -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.focal_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="1" max="1200" step="1" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_focal_length ? +store.filters().min_focal_length : 1" (valueChange)="onExifRangeChange('min_focal_length', $event, 1)" />
                    <input matSliderEndThumb [value]="store.filters().max_focal_length ? +store.filters().max_focal_length : 1200" (valueChange)="onExifRangeChange('max_focal_length', $event, 1200)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-24 text-right">{{ store.filters().min_focal_length || '1' }}-{{ store.filters().max_focal_length || '1200' }}mm</span>
                </div>
              </div>
            </div>
          </details>

          <!-- User Ratings -->
          <details class="group/section">
            <summary class="flex items-center justify-between py-2.5 text-xs font-medium uppercase tracking-wider opacity-70 cursor-pointer select-none [list-style:none] [&::-webkit-details-marker]:hidden">
              {{ 'gallery.sidebar.ratings' | translate }}
              <mat-icon class="!text-xl transition-transform group-open/section:rotate-180">expand_more</mat-icon>
            </summary>
            <div class="flex flex-col gap-2 pb-2">
              <!-- Star Rating -->
              <div class="flex flex-col gap-1">
                <label class="text-sm opacity-70">{{ 'gallery.star_rating_range' | translate }}</label>
                <div class="flex items-center gap-2">
                  <mat-slider min="0" max="5" step="1" class="flex-1">
                    <input matSliderStartThumb [value]="store.filters().min_star_rating ? +store.filters().min_star_rating : 0" (valueChange)="onExifRangeChange('min_star_rating', $event, 0)" />
                    <input matSliderEndThumb [value]="store.filters().max_star_rating ? +store.filters().max_star_rating : 5" (valueChange)="onExifRangeChange('max_star_rating', $event, 5)" />
                  </mat-slider>
                  <span class="text-xs opacity-60 w-16 text-right">{{ store.filters().min_star_rating || '0' }}-{{ store.filters().max_star_rating || '5' }}</span>
                </div>
              </div>
            </div>
          </details>

          <!-- Reset -->
          <div class="pt-2">
            <button mat-stroked-button class="w-full" (click)="store.resetFilters(); store.filterDrawerOpen.set(false)">
              <mat-icon>restart_alt</mat-icon>
              {{ 'gallery.reset_filters' | translate }}
            </button>
          </div>
        </div>
      </mat-sidenav>

      <!-- Main content -->
      <mat-sidenav-content>
        <!-- Photo grid -->
        @if (store.photos().length) {
          <div
            class="grid grid-cols-1 gap-2 p-2 md:p-4 gallery-grid"
            [style.--gallery-cols]="'repeat(auto-fill, minmax(' + cardWidth() + 'px, 1fr))'"
          >
            @for (photo of store.photos(); track photo.path) {
              <div
                class="relative rounded-lg overflow-hidden cursor-pointer bg-neutral-900 transition-all"
                [class.md:aspect-square]="store.filters().hide_details"
                [class.ring-2]="photo.path | isSelected:selectedPaths()"
                [class.ring-[var(--mat-sys-primary)]]="photo.path | isSelected:selectedPaths()"
                [class.hover:ring-2]="!(photo.path | isSelected:selectedPaths())"
                [class.hover:ring-[var(--mat-sys-outline-variant)]]="!(photo.path | isSelected:selectedPaths())"
                (click)="toggleSelection(photo)"
                (mouseenter)="showTooltip($event, photo)"
                (mouseleave)="hideTooltip(); clearHoverStar(photo.path)"
              >
                <!-- Image wrapper with hover overlay scoped to image only -->
                <div class="group/img relative"
                     [class.md:h-full]="store.filters().hide_details">
                  <img
                    [src]="photo.path | thumbnailUrl:thumbSize()"
                    [alt]="photo.filename"
                    loading="lazy"
                    class="w-full"
                    [class.md:h-full]="store.filters().hide_details"
                    [class.md:object-cover]="store.filters().hide_details"
                  />

                  <!-- Persistent favorite star (visible without hover) -->
                  @if (photo.is_favorite) {
                    <div class="absolute top-1.5 left-1.5 z-20 pointer-events-none group-hover/img:opacity-0 transition-opacity">
                      <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-yellow-400 drop-shadow-md">star</mat-icon>
                    </div>
                  }

                  <!-- Hover overlay (image area only) -->
                  <div class="absolute inset-0 bg-black/50 opacity-0 group-hover/img:opacity-100 transition-opacity flex flex-col justify-between pointer-events-none group-hover/img:pointer-events-auto z-10">
                    <!-- Top row: action buttons + star badge -->
                    <div class="flex justify-end items-center gap-1 p-1.5">
                      @if (photo.star_rating && store.config()?.features?.show_rating_badge) {
                        <div class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-black/60 text-yellow-400 text-xs leading-none mr-auto">
                          <mat-icon class="!text-xs !w-3 !h-3 !leading-3">star</mat-icon>
                          <span class="font-medium">{{ photo.star_rating }}</span>
                        </div>
                      }
                      @if (store.config()?.features?.show_similar_button) {
                        <button
                          class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                          [matTooltip]="'similar.find_similar' | translate"
                          (click)="openSimilar(photo); $event.stopPropagation()">
                          <mat-icon class="!text-base !w-4 !h-4 !leading-4">image_search</mat-icon>
                        </button>
                      }
                      @if (auth.isEdition() && photo.unassigned_faces > 0) {
                        <button
                          class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                          [matTooltip]="'manage_persons.assign_face' | translate"
                          (click)="openAddPerson(photo); $event.stopPropagation()">
                          <mat-icon class="!text-base !w-4 !h-4 !leading-4">person_add</mat-icon>
                        </button>
                      }
                      @if (auth.isEdition()) {
                        <button
                          class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors"
                          [class.text-yellow-400]="photo.is_favorite"
                          [class.text-white]="!photo.is_favorite"
                          [matTooltip]="(photo.is_favorite ? 'rating.remove_favorite' : 'rating.add_favorite') | translate"
                          (click)="store.toggleFavorite(photo.path); $event.stopPropagation()">
                          <mat-icon class="!text-base !w-4 !h-4 !leading-4">{{ photo.is_favorite ? 'star' : 'star_border' }}</mat-icon>
                        </button>
                        @if (!photo.star_rating) {
                          <button
                            class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors"
                            [class.text-red-400]="photo.is_rejected"
                            [class.text-white]="!photo.is_rejected"
                            [matTooltip]="(photo.is_rejected ? 'rating.unmark_rejected' : 'rating.mark_rejected') | translate"
                            (click)="store.toggleRejected(photo.path); $event.stopPropagation()">
                            <mat-icon class="!text-base !w-4 !h-4 !leading-4">{{ photo.is_rejected ? 'thumb_down' : 'thumb_down_off_alt' }}</mat-icon>
                          </button>
                        }
                      }
                    </div>

                    <!-- Bottom row: star rating -->
                    @if (store.config()?.features?.show_rating_controls && auth.isEdition()) {
                      <div class="flex justify-center gap-0.5 p-1.5">
                        @for (star of 0 | starArray; track star) {
                          <button
                            class="text-yellow-400 hover:scale-110 transition-transform"
                            (mouseenter)="setHoverStar(photo.path, star)"
                            (mouseleave)="clearHoverStar(photo.path)"
                            (click)="onStarClick(photo, star); $event.stopPropagation()">
                            <mat-icon class="!text-xl !w-5 !h-5">{{
                              (star | isStarFilled:photo.star_rating:hoverStars()[photo.path]) ? 'star' : 'star_border'
                            }}</mat-icon>
                          </button>
                        }
                      </div>
                    }
                  </div>

                  <!-- Selection checkmark -->
                  @if (photo.path | isSelected:selectedPaths()) {
                    <div class="absolute top-1.5 left-1.5 w-6 h-6 rounded-full bg-[var(--mat-sys-primary)] flex items-center justify-center z-20">
                      <mat-icon class="!text-base !w-4 !h-4 text-white">check</mat-icon>
                    </div>
                  }
                </div>

                <!-- Details below photo -->
                @if (!store.filters().hide_details) {
                  <div class="pt-1 text-xs text-neutral-300 leading-snug">
                    <div class="flex items-center gap-1">
                      <span class="font-medium text-neutral-200 truncate">{{ photo.filename }}</span>
                      <span class="ml-auto flex items-center gap-1 shrink-0">
                        @if (photo.is_best_of_burst) {
                          <span class="px-1 py-0.5 rounded text-[10px] font-bold bg-green-700 text-white">{{ 'ui.badges.best' | translate }}</span>
                        }
                        @if (store.filters().sort !== 'aggregate') {
                          <span class="text-neutral-400 font-medium" [matTooltip]="'gallery.aggregate_score' | translate">{{ photo.aggregate | fixed:1 }}</span>
                        }
                        <span
                          class="px-1 py-0.5 rounded text-xs font-bold"
                          [class]="(photo | sortScore:store.filters().sort) | scoreClass:store.config()"
                          [matTooltip]="(store.filters().sort === 'aggregate' ? ('gallery.aggregate_score' | translate) : ('gallery.sort_score' | translate) + ' (' + store.filters().sort + ')')"
                        >{{ (photo | sortScore:store.filters().sort) | fixed:1 }}</span>
                      </span>
                    </div>
                    @if (photo.date_taken) {
                      <div class="text-neutral-500">{{ photo.date_taken }}</div>
                    }
                    <div class="text-neutral-500">
                      @if (photo.focal_length) { {{ photo.focal_length }}mm }
                      @if (photo.f_stop) { f/{{ photo.f_stop }} }
                      @if (photo.shutter_speed) { {{ photo.shutter_speed | shutterSpeed }} }
                      @if (photo.iso) { ISO {{ photo.iso }} }
                    </div>
                    @if (photo.tags_list.length) {
                      <div class="flex gap-0.5 flex-wrap mt-0.5">
                        @for (tag of photo.tags_list; track tag) {
                          <span class="px-1.5 py-0.5 bg-green-900/60 text-green-400 rounded text-[11px] cursor-pointer hover:bg-green-800/60 transition-colors"
                                (click)="store.updateFilter('tag', tag); $event.stopPropagation()">
                            {{ tag }}
                          </span>
                        }
                      </div>
                    }
                    <!-- Person avatars in details -->
                    @if (photo.persons.length) {
                      <div class="flex items-center gap-1 mt-0.5">
                        @for (person of photo.persons; track person.id) {
                          @if (auth.isEdition() && store.filters().person_id === '' + person.id) {
                            <button
                              class="w-8 h-8 rounded-full bg-red-900/60 inline-flex items-center justify-center hover:bg-red-800 transition-colors"
                              [matTooltip]="('ui.buttons.remove' | translate) + ': ' + person.name"
                              (click)="removePerson(photo, person.id); $event.stopPropagation()">
                              <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-red-300">close</mat-icon>
                            </button>
                          } @else {
                            <img [src]="person.id | personThumbnailUrl"
                                 class="w-8 h-8 rounded-full border border-neutral-700 object-cover cursor-pointer"
                                 [matTooltip]="person.name"
                                 (click)="filterByPerson(person.id); $event.stopPropagation()" />
                          }
                        }
                      </div>
                    }
                  </div>
                }
              </div>
            }
          </div>
        }

        <!-- Loading spinner -->
        @if (store.loading()) {
          <div class="flex justify-center p-8">
            <mat-spinner diameter="40"></mat-spinner>
          </div>
        }

        <!-- Empty state -->
        @if (!store.loading() && store.photos().length === 0 && store.total() === 0) {
          <div class="flex flex-col items-center justify-center gap-4 p-16 opacity-60">
            <mat-icon class="!text-6xl !w-16 !h-16">photo_library</mat-icon>
            <p class="text-lg">{{ 'gallery.no_photos' | translate }}</p>
            @if (store.activeFilterCount()) {
              <button mat-stroked-button (click)="store.resetFilters()">
                {{ 'gallery.reset_filters' | translate }}
              </button>
            }
          </div>
        }

        <!-- Infinite scroll sentinel -->
        <div #scrollSentinel class="h-1"></div>
      </mat-sidenav-content>
    </mat-sidenav-container>

    <!-- Slideshow overlay -->
    @if (store.slideshowActive()) {
      <app-slideshow
        [photos]="store.photos()"
        [hasMore]="store.hasMore()"
        [loading]="store.loading()"
      />
    }

    <!-- Photo details tooltip (single instance, repositioned on hover, hidden on touch devices) -->
    @if (!isTouchDevice()) {
      <app-photo-tooltip
        [photo]="tooltipPhoto()"
        [x]="tooltipX()"
        [y]="tooltipY()"
      />
    }

    <!-- Selection action bar -->
    @if (selectionCount()) {
      <div class="fixed bottom-14 lg:bottom-0 left-0 right-0 z-50 flex flex-col lg:flex-row items-center justify-center gap-2 lg:gap-3 px-4 lg:px-6 py-2 lg:py-3 bg-[var(--mat-sys-surface-container-high)] border-t border-[var(--mat-sys-outline-variant)] shadow-lg">
        <span class="text-sm font-medium">{{ 'gallery.selection.count' | translate:{ count: selectionCount() } }}</span>
        <div class="flex items-center gap-2">
          <button mat-button (click)="clearSelection()">
            <mat-icon>close</mat-icon>
            {{ 'gallery.selection.clear' | translate }}
          </button>
          <button mat-button (click)="copyPaths()">
            <mat-icon>content_copy</mat-icon>
            {{ 'gallery.selection.copy_filenames' | translate }}
          </button>
          <button mat-flat-button (click)="downloadSelected()">
            <mat-icon>download</mat-icon>
            {{ 'gallery.selection.download' | translate }}
          </button>
        </div>
      </div>
    }
  `,
  host: { class: 'block h-full' },
})
export class GalleryComponent implements OnInit, OnDestroy {
  store = inject(GalleryStore);
  api = inject(ApiService);
  auth = inject(AuthService);
  private snackBar = inject(MatSnackBar);
  private i18n = inject(I18nService);
  private dialog = inject(MatDialog);

  private observer: IntersectionObserver | null = null;
  readonly scrollSentinel = viewChild<ElementRef<HTMLDivElement>>('scrollSentinel');
  private readonly filterDrawer = viewChild<MatSidenav>('filterDrawer');
  private readonly filterScrollArea = viewChild<ElementRef<HTMLDivElement>>('filterScrollArea');

  // Sidebar state preservation
  private savedFilterScroll = 0;
  private savedDetailStates: boolean[] = [];

  // Tooltip state
  readonly tooltipPhoto = signal<Photo | null>(null);
  readonly tooltipX = signal(0);
  readonly tooltipY = signal(0);

  // Selection state
  readonly selectedPaths = signal<Set<string>>(new Set());
  readonly selectionCount = computed(() => this.selectedPaths().size);

  /** True when the device has no hover capability (touch device) */
  readonly isTouchDevice = signal(false);

  /** Thumbnail request size derived from config (2x for retina, capped at 640). Returns 640 on mobile (full-width cards). */
  readonly thumbSize = computed(() => {
    if (this.isTouchDevice()) return 640;
    const imgWidth = this.store.config()?.display?.image_width_px ?? 160;
    return Math.min(imgWidth * 2, 640);
  });

  /** Card min-width from config for the responsive grid */
  readonly cardWidth = computed(() => {
    return this.store.config()?.display?.card_width_px ?? 168;
  });

  private isBrowser = false;

  constructor() {
    afterNextRender(() => {
      this.isBrowser = true;
      this.isTouchDevice.set(window.matchMedia('(hover: none)').matches);
      this.setupIntersectionObserver();
    });

    // Sync store.filterDrawerOpen signal → mat-sidenav
    effect(() => {
      const open = this.store.filterDrawerOpen();
      const drawer = this.filterDrawer();
      if (!drawer) return;
      if (open) drawer.open();
      else drawer.close();
    });

    // Re-check sentinel whenever photos change (filter change, page load, etc.)
    effect(() => {
      this.store.photos(); // track dependency
      this.recheckSentinel();
    });
  }

  async ngOnInit(): Promise<void> {
    await this.store.loadConfig();
    await Promise.all([this.store.loadFilterOptions(), this.store.loadTypeCounts()]);
    await this.store.loadPhotos();
    this.recheckSentinel();
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }

  /** Handle 0-10 score range slider changes; clear filter when at boundary */
  onRangeChange(key: string, value: number): void {
    const isMin = key.startsWith('min');
    const filterValue = (isMin && value === 0) || (!isMin && value === 10) ? '' : String(value);
    this.store.updateFilter(key as 'min_score', filterValue);
  }

  /** Handle EXIF range slider changes with custom min/max boundaries */
  onExifRangeChange(key: string, value: number, boundary: number): void {
    const filterValue = value === boundary ? '' : String(value);
    this.store.updateFilter(key as 'min_score', filterValue);
  }

  /** Save/restore sidebar state on drawer open/close */
  onFilterDrawerChange(open: boolean): void {
    this.store.filterDrawerOpen.set(open);
    const scrollEl = this.filterScrollArea()?.nativeElement;
    if (!scrollEl) return;

    if (!open) {
      // Save scroll position and details open states
      this.savedFilterScroll = scrollEl.scrollTop;
      this.savedDetailStates = Array.from(scrollEl.querySelectorAll('details')).map(d => d.open);
    } else {
      // Restore after a microtask (DOM needs to render)
      queueMicrotask(() => {
        const details = scrollEl.querySelectorAll('details');
        this.savedDetailStates.forEach((wasOpen, i) => {
          if (details[i]) details[i].open = wasOpen;
        });
        scrollEl.scrollTop = this.savedFilterScroll;
      });
    }
  }

  /** Handle date input changes */
  onDateChange(key: 'date_from' | 'date_to', event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.store.updateFilter(key, value);
  }

  toggleSelection(photo: Photo): void {
    const current = this.selectedPaths();
    const next = new Set(current);
    if (next.has(photo.path)) {
      next.delete(photo.path);
    } else {
      next.add(photo.path);
    }
    this.selectedPaths.set(next);
  }

  clearSelection(): void {
    this.selectedPaths.set(new Set());
  }

  copyPaths(): void {
    const filenames = [...this.selectedPaths()]
      .map(p => p.split(/[\\/]/).pop() ?? p)
      .join('\n');
    navigator.clipboard.writeText(filenames).then(() => {
      this.snackBar.open(this.i18n.t('gallery.selection.copied'), '', { duration: 2000 });
    });
  }

  async downloadSelected(): Promise<void> {
    const paths = [...this.selectedPaths()];
    for (const path of paths) {
      const url = `/api/download?path=${encodeURIComponent(path)}`;
      const a = document.createElement('a');
      a.href = url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // Small delay between downloads to avoid browser throttling
      if (paths.length > 1) {
        await new Promise(resolve => setTimeout(resolve, 300));
      }
    }
  }

  showTooltip(event: MouseEvent, photo: Photo): void {
    if (this.isTouchDevice()) return;
    const card = event.currentTarget as HTMLElement;
    const rect = card.getBoundingClientRect();
    const padding = 16;
    const isLandscape = photo.image_width > photo.image_height;
    const vh = window.innerHeight;
    const vw = window.innerWidth;

    // Use the gallery card's loaded thumbnail for aspect ratio — more accurate than
    // photo.image_width/height which may differ due to EXIF rotation (thumbnail stored
    // as raw sensor data while photo dimensions are EXIF-corrected).
    const thumbImg = (card.querySelector('img') as HTMLImageElement | null);
    const tnw = thumbImg?.naturalWidth || photo.image_width || 4;
    const tnh = thumbImg?.naturalHeight || photo.image_height || 3;
    const thumbAspect = tnw / tnh;
    // Natural height of the 640px tooltip thumbnail (max 640px on longest side)
    const tooltipNatH = thumbAspect > 1 ? 640 / thumbAspect : 640;

    // Estimate tooltip dimensions using the tooltip thumbnail's actual pixel aspect ratio.
    let tooltipWidth: number;
    let tooltipHeight: number;
    if (isLandscape) {
      // flex-col layout: image capped at max-h-[35vh]
      const imgH = Math.min(tooltipNatH, vh * 0.35);
      const imgW = imgH * thumbAspect;
      tooltipWidth = Math.ceil(imgW) + 24; // p-2.5 padding both sides
      tooltipHeight = Math.ceil(imgH) + 140;
    } else {
      // flex-row layout: image capped at max-h-[50vh], details panel 260px wide
      const imgH = Math.min(tooltipNatH, vh * 0.5);
      const imgW = imgH * thumbAspect;
      tooltipWidth = Math.ceil(imgW) + 260 + 12 + 24; // image + gap-3 + details + padding
      tooltipHeight = Math.max(Math.ceil(imgH), 300) + 24;
    }

    // Position to the right of the card, or left if it would overflow.
    // When flipping left, never clamp to screen edge — it's better to go off-screen than
    // to overlap the hovered card.
    const wouldOverflowRight = rect.right + padding + tooltipWidth > vw - padding;
    let x: number;
    if (wouldOverflowRight) {
      // Place to the LEFT of the card — may go off-screen, that's acceptable
      x = rect.left - tooltipWidth - padding;
    } else {
      x = rect.right + padding;
    }

    // Vertically center on the card, clamped to viewport
    let y = rect.top + rect.height / 2 - tooltipHeight / 2;
    y = Math.max(padding, Math.min(y, vh - tooltipHeight - padding));

    this.tooltipX.set(x);
    this.tooltipY.set(y);
    this.tooltipPhoto.set(photo);

    // Post-render correction: re-run placement with actual rendered dimensions.
    // Same rule: never clamp when going left, to avoid covering the card.
    setTimeout(() => {
      if (this.tooltipPhoto() !== photo) return;
      const el = document.querySelector('app-photo-tooltip > div') as HTMLElement | null;
      if (!el) return;
      const { width: actualWidth } = el.getBoundingClientRect();
      const wouldOverflowRightActual = rect.right + padding + actualWidth > vw - padding;
      const newX = wouldOverflowRightActual
        ? rect.left - actualWidth - padding   // left — may go off-screen, never clamp
        : rect.right + padding;
      if (Math.abs(newX - this.tooltipX()) > 1) this.tooltipX.set(newX);
    }, 0);
  }

  hideTooltip(): void {
    this.tooltipPhoto.set(null);
  }

  // --- Hover star state ---
  readonly hoverStars = signal<Record<string, number | null>>({});

  setHoverStar(path: string, star: number): void {
    this.hoverStars.update(s => ({ ...s, [path]: star }));
  }

  clearHoverStar(path: string): void {
    this.hoverStars.update(s => {
      const next = { ...s };
      delete next[path];
      return next;
    });
  }

  onStarClick(photo: Photo, star: number): void {
    const newRating = photo.star_rating === star ? 0 : star;
    this.store.setRating(photo.path, newRating);
  }

  // --- Card action handlers ---

  openSimilar(photo: Photo): void {
    this.dialog.open(SimilarPhotosDialogComponent, {
      data: {
        photoPath: photo.path,
        selectedPaths: this.selectedPaths,
        togglePath: (path: string) => {
          const next = new Set(this.selectedPaths());
          if (next.has(path)) next.delete(path); else next.add(path);
          this.selectedPaths.set(next);
        },
      },
      width: '95vw',
      maxWidth: '640px',
    });
  }

  openAddPerson(photo: Photo): void {
    const faceRef = this.dialog.open(FaceSelectorDialogComponent, {
      data: { photoPath: photo.path },
      width: '95vw',
      maxWidth: '400px',
    });
    faceRef.afterClosed().subscribe(face => {
      if (!face) return;
      const persons = this.store.persons().filter(p => p.name);
      const personRef = this.dialog.open(PersonSelectorDialogComponent, {
        data: persons,
        width: '95vw',
        maxWidth: '400px',
      });
      personRef.afterClosed().subscribe(async selected => {
        if (selected) {
          await this.store.assignFace(face.id, selected.id, photo.path, selected.name);
          this.snackBar.open(this.i18n.t('notifications.faces_assigned'), '', { duration: 2000 });
        }
      });
    });
  }

  removePerson(photo: Photo, personId: number): void {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t('manage_persons.remove_person_title'),
        message: this.i18n.t('manage_persons.confirm_remove_person'),
      },
    });
    ref.afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.store.unassignPerson(photo.path, personId);
      }
    });
  }

  filterByPerson(personId: number): void {
    this.store.updateFilter('person_id', String(personId));
  }

  private setupIntersectionObserver(): void {
    const sentinel = this.scrollSentinel();
    if (!sentinel) return;

    this.observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting && this.store.hasMore() && !this.store.loading()) {
          this.store.nextPage().then(() => this.recheckSentinel());
        }
      },
      { rootMargin: '200px' },
    );
    this.observer.observe(sentinel.nativeElement);
  }

  /** Re-observe sentinel to trigger another load if it's still visible after content change */
  private recheckSentinel(): void {
    if (!this.isBrowser || !this.observer) return;
    const sentinel = this.scrollSentinel();
    if (!sentinel) return;
    this.observer.unobserve(sentinel.nativeElement);
    this.observer.observe(sentinel.nativeElement);
  }
}
