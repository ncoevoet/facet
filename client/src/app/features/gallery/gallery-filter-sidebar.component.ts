import { Component, inject, ElementRef, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatSelectModule } from '@angular/material/select';
import { MatSliderModule } from '@angular/material/slider';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatInputModule } from '@angular/material/input';
import { GalleryStore } from './gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Component({
  selector: 'app-gallery-filter-sidebar',
  standalone: true,
  imports: [
    FormsModule,
    MatSelectModule,
    MatSliderModule,
    MatIconModule,
    MatButtonModule,
    MatFormFieldModule,
    MatCheckboxModule,
    MatInputModule,
    TranslatePipe,
  ],
  template: `
    <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--mat-sys-outline-variant)]">
      <span class="text-base font-medium">{{ 'gallery.filters' | translate }}</span>
      <button mat-icon-button (click)="store.filterDrawerOpen.set(false)">
        <mat-icon>close</mat-icon>
      </button>
    </div>

    <div #filterScrollArea data-scroll class="overflow-y-auto p-4 flex flex-col gap-1 max-h-[calc(100vh-120px)]">
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
  `,
})
export class GalleryFilterSidebarComponent {
  readonly store = inject(GalleryStore);
  readonly filterScrollArea = viewChild<ElementRef<HTMLDivElement>>('filterScrollArea');

  onRangeChange(key: string, value: number): void {
    const isMin = key.startsWith('min');
    const filterValue = (isMin && value === 0) || (!isMin && value === 10) ? '' : String(value);
    this.store.updateFilter(key as 'min_score', filterValue);
  }

  onExifRangeChange(key: string, value: number, boundary: number): void {
    const filterValue = value === boundary ? '' : String(value);
    this.store.updateFilter(key as 'min_score', filterValue);
  }

  onDateChange(key: 'date_from' | 'date_to', event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.store.updateFilter(key, value);
  }
}
