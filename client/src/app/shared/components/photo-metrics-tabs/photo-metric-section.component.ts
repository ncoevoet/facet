import { SORT_ICONS } from '../../pipes/sort-option-icon.pipe';
import { I18N } from '../../../core/i18n/keys';
import { MatIconModule } from '@angular/material/icon';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { Photo } from '../../models/photo.model';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { IsLensNamePipe } from '../../pipes/is-lens-name.pipe';
import { ShutterSpeedPipe } from '../../pipes/shutter-speed.pipe';
import { ThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../pipes/translate.pipe';
import type { HistogramSurface } from '../../../core/services/histogram-preferences.service';
import type { MetricsTab } from '../../../core/services/metrics-tab-state.service';
import type { HistogramMode } from '../../utils/histogram';
import type { MetricDistribution } from '../../utils/metric-distribution';
import { ExtendedQualityComponent } from '../extended-quality/extended-quality.component';
import { HistogramComponent } from '../histogram/histogram.component';
import { MetricScoreRowComponent } from '../metric-score-row/metric-score-row.component';

/** Shared measurement bodies, independent of tabs or collapsible section chrome. */
@Component({
 selector:'app-photo-metric-section',
 imports:[MatIconModule, FixedPipe, IsLensNamePipe, ShutterSpeedPipe, ThumbnailUrlPipe, TranslatePipe, ExtendedQualityComponent, HistogramComponent, MetricScoreRowComponent],
 changeDetection:ChangeDetectionStrategy.OnPush,
 host:{class:'block min-w-0'},
 template:`@let p = photo(); @switch(kind()) {@case('exif') {
        <div class="pt-3">
          <div class="flex flex-col gap-0.5">
            @if (p.camera_model) {
              <div class="flex justify-between items-center gap-2"><span class="inline-flex items-center gap-2 text-[var(--mat-sys-on-surface-variant)]"><mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base">photo_camera</mat-icon>{{ 'tooltip.camera' | translate }}</span><span class="val truncate">{{ p.camera_model }}</span></div>
            }
            @if (p.lens_model && (p.lens_model | isLensName)) {
              <div class="flex justify-between items-center gap-2"><span class="inline-flex items-center gap-2 text-[var(--mat-sys-on-surface-variant)]"><mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base">camera</mat-icon>{{ 'tooltip.lens' | translate }}</span><span class="val truncate">{{ p.lens_model }}</span></div>
            }
            @if (p.focal_length) {
              <div class="flex justify-between items-center gap-2"><span class="inline-flex items-center gap-2 text-[var(--mat-sys-on-surface-variant)]"><mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base">straighten</mat-icon>{{ 'tooltip.focal' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.focal_length }}mm</span></div>
            }
            @if (p.f_stop) {
              <div class="flex justify-between items-center gap-2"><span class="inline-flex items-center gap-2 text-[var(--mat-sys-on-surface-variant)]"><mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base">camera</mat-icon>{{ 'tooltip.aperture' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">f/{{ p.f_stop }}</span></div>
            }
            @if (p.shutter_speed) {
              <div class="flex justify-between items-center gap-2"><span class="inline-flex items-center gap-2 text-[var(--mat-sys-on-surface-variant)]"><mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base">shutter_speed</mat-icon>{{ 'tooltip.shutter' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.shutter_speed | shutterSpeed }}</span></div>
            }
            @if (p.iso) {
              <div class="flex justify-between items-center gap-2"><span class="inline-flex items-center gap-2 text-[var(--mat-sys-on-surface-variant)]"><mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base">iso</mat-icon>{{ 'tooltip.iso' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.iso }}</span></div>
            }
          </div>
        </div>
        }
@case('quality') {
      <div class="pt-3">
        <div class="flex flex-col gap-0.5">
          <app-metric-score-row [icon]="metricIcons['aesthetic']" [label]="'tooltip.aesthetic' | translate" [range]="ranges()['aesthetic']" [value]="p.aesthetic">{{ p.aesthetic | fixed:1 }}</app-metric-score-row>
          @if (p.quality_score !== null) {
            <app-metric-score-row [icon]="metricIcons['quality_score']" [label]="'tooltip.quality_score' | translate" [range]="ranges()['quality_score']" [value]="p.quality_score">{{ p.quality_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.topiq_score !== null) {
            <app-metric-score-row [icon]="metricIcons['topiq_score']" [label]="'tooltip.topiq_score' | translate" [range]="ranges()['topiq_score']" [value]="p.topiq_score">{{ p.topiq_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.tech_sharpness !== null) {
            <app-metric-score-row [icon]="metricIcons['tech_sharpness']" [label]="'tooltip.tech_sharpness' | translate" [range]="ranges()['tech_sharpness']" [value]="p.tech_sharpness">{{ p.tech_sharpness | fixed:1 }}</app-metric-score-row>
          }
          @if (p.face_count > 0 && p.face_quality !== null) {
            <app-metric-score-row [icon]="metricIcons['face_quality']" [label]="'tooltip.face_quality' | translate" [range]="ranges()['face_quality']" [value]="p.face_quality">{{ p.face_quality | fixed:1 }}</app-metric-score-row>
            <app-metric-score-row [icon]="metricIcons['face_count']" [label]="'tooltip.faces' | translate" [range]="ranges()['face_count']" [value]="p.face_count">{{ p.face_count }}</app-metric-score-row>
            @if (p.face_ratio) {
              <app-metric-score-row [icon]="metricIcons['face_ratio']" [label]="'tooltip.face_ratio' | translate" [range]="ranges()['face_ratio']" [value]="p.face_ratio" [percent]="true">{{ p.face_ratio * 100 | fixed:0 }}%</app-metric-score-row>
            }
            @if (p.face_sharpness !== null) {
              <app-metric-score-row [icon]="metricIcons['face_sharpness']" [label]="'tooltip.face_sharpness' | translate" [range]="ranges()['face_sharpness']" [value]="p.face_sharpness">{{ p.face_sharpness | fixed:1 }}</app-metric-score-row>
            }
            @if (p.eye_sharpness !== null) {
              <app-metric-score-row [icon]="metricIcons['eye_sharpness']" [label]="'tooltip.eye_sharpness' | translate" [range]="ranges()['eye_sharpness']" [value]="p.eye_sharpness">{{ p.eye_sharpness | fixed:1 }}</app-metric-score-row>
            }
            @if (p.face_confidence !== null && p.face_confidence !== undefined) {
              <app-metric-score-row [icon]="metricIcons['face_confidence']" [label]="'tooltip.face_confidence' | translate" [range]="ranges()['face_confidence']" [value]="p.face_confidence" [percent]="true">{{ p.face_confidence * 100 | fixed:0 }}%</app-metric-score-row>
            }
          }
          @if (p.aesthetic_iaa !== null) {
            <app-metric-score-row [icon]="metricIcons['aesthetic_iaa']" [label]="'tooltip.aesthetic_iaa' | translate" [range]="ranges()['aesthetic_iaa']" [value]="p.aesthetic_iaa">{{ p.aesthetic_iaa | fixed:1 }}</app-metric-score-row>
          }
          @if (p.face_quality_iqa !== null && p.face_quality_iqa !== undefined) {
            <app-metric-score-row [icon]="metricIcons['face_quality_iqa']" [label]="'tooltip.face_quality_iqa' | translate" [range]="ranges()['face_quality_iqa']" [value]="p.face_quality_iqa">{{ p.face_quality_iqa | fixed:1 }}</app-metric-score-row>
          } @else if (p.assessment_states?.face_quality_iqa === 'not_applicable') {
            <details data-face-iqa-decline>
              <summary class="flex min-h-9 cursor-pointer items-center justify-between gap-3 rounded py-1 text-xs focus-visible:outline-2">
                <span class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.tooltip.face_quality_iqa | translate }}</span>
                <span class="font-medium">{{ I18N.photo_detail.assessment.not_applicable | translate }}</span>
              </summary>
              <p class="m-0 pb-2 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.photo_detail.assessment.face_iqa_declined_help | translate }}</p>
            </details>
          }
          @if (p.liqe_score !== null) {
            <app-metric-score-row [icon]="metricIcons['liqe_score']" [label]="'tooltip.liqe_score' | translate" [range]="ranges()['liqe_score']" [value]="p.liqe_score">{{ p.liqe_score | fixed:1 }}</app-metric-score-row>
          }
          <app-extended-quality [photo]="p" [populated]="populated()" />
        </div>
      </div>
      }
@case('composition') {
      <div class="pt-3">
        <div class="flex flex-col gap-0.5">
          @if (p.composition_pattern) {
            <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.pattern' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ ('composition_patterns.' + p.composition_pattern) | translate }}</span></div>
          }
          @if (p.comp_score !== null) {
            <app-metric-score-row [icon]="metricIcons['comp_score']" [label]="'tooltip.composition' | translate" [range]="ranges()['comp_score']" [value]="p.comp_score">{{ p.comp_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.power_point_score !== null) {
            <app-metric-score-row [icon]="metricIcons['power_point_score']" [label]="'tooltip.power_points' | translate" [range]="ranges()['power_point_score']" [value]="p.power_point_score">{{ p.power_point_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.leading_lines_score !== null) {
            <app-metric-score-row [icon]="metricIcons['leading_lines_score']" [label]="'tooltip.leading_lines' | translate" [range]="ranges()['leading_lines_score']" [value]="p.leading_lines_score">{{ p.leading_lines_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.isolation_bonus !== null) {
            <app-metric-score-row [icon]="metricIcons['isolation_bonus']" [label]="'tooltip.isolation' | translate" [range]="ranges()['isolation_bonus']" [value]="p.isolation_bonus">{{ p.isolation_bonus | fixed:1 }}</app-metric-score-row>
          }
        </div>
      </div>

      <!-- Subject Saliency section -->
      @if (p.subject_sharpness !== null || p.subject_prominence !== null || p.subject_placement !== null || p.bg_separation !== null) {
        <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
          <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.saliency' | translate }}</div>
          <div class="flex flex-col gap-0.5">
            @if (p.subject_sharpness !== null) {
              <app-metric-score-row [icon]="metricIcons['subject_sharpness']" [label]="'tooltip.subject_sharpness' | translate" [range]="ranges()['subject_sharpness']" [value]="p.subject_sharpness">{{ p.subject_sharpness | fixed:1 }}</app-metric-score-row>
            }
            @if (p.subject_prominence !== null) {
              <app-metric-score-row [icon]="metricIcons['subject_prominence']" [label]="'tooltip.subject_prominence' | translate" [range]="ranges()['subject_prominence']" [value]="p.subject_prominence">{{ p.subject_prominence | fixed:1 }}</app-metric-score-row>
            }
            @if (p.subject_placement !== null) {
              <app-metric-score-row [icon]="metricIcons['subject_placement']" [label]="'tooltip.subject_placement' | translate" [range]="ranges()['subject_placement']" [value]="p.subject_placement">{{ p.subject_placement | fixed:1 }}</app-metric-score-row>
            }
            @if (p.bg_separation !== null) {
              <app-metric-score-row [icon]="metricIcons['bg_separation']" [label]="'tooltip.bg_separation' | translate" [range]="ranges()['bg_separation']" [value]="p.bg_separation">{{ p.bg_separation | fixed:1 }}</app-metric-score-row>
            }
          </div>
        </div>
      }
      @if (p.form_symmetry !== null || p.form_balance !== null || p.form_edge_entropy !== null || p.form_fractal !== null || p.color_harmony !== null) {
        <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
          <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'tooltip.form_section' | translate }}</div>
          <div class="flex flex-col gap-0.5">
            @if (p.form_symmetry !== null) {
              <app-metric-score-row [icon]="metricIcons['form_symmetry']" [label]="'tooltip.form_symmetry' | translate" [range]="ranges()['form_symmetry']" [value]="p.form_symmetry">{{ p.form_symmetry | fixed:1 }}</app-metric-score-row>
            }
            @if (p.form_balance !== null) {
              <app-metric-score-row [icon]="metricIcons['form_balance']" [label]="'tooltip.form_balance' | translate" [range]="ranges()['form_balance']" [value]="p.form_balance">{{ p.form_balance | fixed:1 }}</app-metric-score-row>
            }
            @if (p.form_edge_entropy !== null) {
              <app-metric-score-row [icon]="metricIcons['form_edge_entropy']" [label]="'tooltip.form_edge_entropy' | translate" [range]="ranges()['form_edge_entropy']" [value]="p.form_edge_entropy">{{ p.form_edge_entropy | fixed:1 }}</app-metric-score-row>
            }
            @if (p.form_fractal !== null) {
              <app-metric-score-row [icon]="metricIcons['form_fractal']" [label]="'tooltip.form_fractal' | translate" [range]="ranges()['form_fractal']" [value]="p.form_fractal">{{ p.form_fractal | fixed:1 }}</app-metric-score-row>
            }
            @if (p.color_harmony !== null) {
              <app-metric-score-row [icon]="metricIcons['color_harmony']" [label]="'tooltip.color_harmony' | translate" [range]="ranges()['color_harmony']" [value]="p.color_harmony">{{ p.color_harmony | fixed:1 }}</app-metric-score-row>
            }
          </div>
        </div>
      }
      }
@case('technical') {
      <div class="pt-3">
        <div class="flex flex-col gap-0.5">
          @if (p.exposure_score !== null) {
            <app-metric-score-row icon="exposure" [label]="'tooltip.exposure' | translate" [range]="ranges()['exposure_score']" [value]="p.exposure_score">{{ p.exposure_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.color_score !== null) {
            <app-metric-score-row icon="palette" [label]="'tooltip.color' | translate" [range]="ranges()['color_score']" [value]="p.color_score">{{ p.color_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.contrast_score !== null) {
            <app-metric-score-row icon="contrast" [label]="'tooltip.contrast' | translate" [range]="ranges()['contrast_score']" [value]="p.contrast_score">{{ p.contrast_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.dynamic_range_stops !== null) {
            <app-metric-score-row icon="dynamic_range" [label]="'tooltip.dynamic_range' | translate" [range]="ranges()['dynamic_range_stops']" [value]="p.dynamic_range_stops">{{ p.dynamic_range_stops | fixed:1 }}</app-metric-score-row>
          }
          @if (p.mean_saturation !== null && p.mean_saturation !== undefined) {
            <app-metric-score-row icon="invert_colors" [label]="'tooltip.saturation' | translate" [range]="ranges()['mean_saturation']" [value]="p.mean_saturation" [percent]="true">{{ (p.mean_saturation * 100) | fixed:0 }}%</app-metric-score-row>
          }
          @if (p.noise_sigma !== null) {
            <app-metric-score-row icon="grain" [label]="'tooltip.noise' | translate" [range]="ranges()['noise_sigma']" [value]="p.noise_sigma">{{ p.noise_sigma | fixed:1 }}</app-metric-score-row>
          }
          @if (p.mean_luminance !== null && p.mean_luminance !== undefined) {
            <app-metric-score-row icon="brightness_6" [label]="'tooltip.luminance' | translate" [range]="ranges()['mean_luminance']" [value]="p.mean_luminance" [percent]="true">{{ p.mean_luminance * 100 | fixed:0 }}%</app-metric-score-row>
          }
          @if (p.histogram_spread !== null) {
            <app-metric-score-row icon="equalizer" [label]="'tooltip.histogram_spread' | translate" [range]="ranges()['histogram_spread']" [value]="p.histogram_spread">{{ p.histogram_spread | fixed:1 }}</app-metric-score-row>
          }
        </div>
      </div>

      }
@case('histogram') {
        <div class="pt-3">
          <app-histogram [path]="p.path" [src]="p.path | thumbnailUrl:histogramSrcSize():p.preview_revision" [monochrome]="!!p.is_monochrome"
                         [height]="histogramHeight()" [showModeToggle]="true"
                         [surface]="histogramSurface()"
                         [defaultMode]="histogramDefaultMode()"
                         [indicatorPercent]="indicatorPercent()" />
        </div>
      } }`,
})
export class PhotoMetricSectionComponent {
 protected readonly I18N = I18N;
 protected readonly metricIcons = SORT_ICONS;
 readonly kind = input.required<MetricsTab>();
 readonly photo = input.required<Photo>();
 readonly ranges = input<Record<string, MetricDistribution>>({});
 readonly populated = input<readonly string[] | undefined>(undefined);
 readonly histogramSrcSize = input(640);
 readonly histogramHeight = input.required<number>();
 readonly histogramSurface = input<HistogramSurface>('detail');
 readonly histogramDefaultMode = input<HistogramMode>('luma');
 readonly indicatorPercent = input(1);
}
