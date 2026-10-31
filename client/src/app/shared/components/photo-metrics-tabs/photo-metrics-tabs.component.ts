import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Photo, hasExifFields } from '../../models/photo.model';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { IsLensNamePipe } from '../../pipes/is-lens-name.pipe';
import { ShutterSpeedPipe } from '../../pipes/shutter-speed.pipe';
import { ThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { HistogramSurface } from '../../../core/services/histogram-preferences.service';
import { METRICS_TABS, MetricsTab, MetricsTabState } from '../../../core/services/metrics-tab-state.service';
import { HistogramMode } from '../../utils/histogram';
import { MetricDistribution } from '../../utils/metric-distribution';
import { ExtendedQualityComponent } from '../extended-quality/extended-quality.component';
import { HistogramComponent } from '../histogram/histogram.component';
import { MetricScoreRowComponent } from '../metric-score-row/metric-score-row.component';
import { PhotoAssessmentComponent } from '../photo-assessment/photo-assessment.component';

/**
 * A photo's metrics in icon tabs (EXIF, Quality, Composition, Technical,
 * Histogram), each score placed in its library distribution. Shared by photo
 * detail and the gallery's docked details panel, which also share the
 * remembered tab, so choosing Technical in one opens Technical in the other.
 *
 * Literal i18n keys rather than `I18N`: the gallery's photo tooltip renders
 * this, and that tooltip's spec cannot read the `I18N` binding (see
 * scripts/migrate-i18n.mjs).
 */
@Component({
  selector: 'app-photo-metrics-tabs',
  imports: [
    MatIconModule, MatTabsModule, MatTooltipModule, FixedPipe, IsLensNamePipe, ShutterSpeedPipe,
    ThumbnailUrlPipe, TranslatePipe, ExtendedQualityComponent, HistogramComponent, MetricScoreRowComponent, PhotoAssessmentComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' },
  template: `
    @let p = photo();
    <app-photo-assessment [photo]="p" [range]="ranges()['aggregate']" />
    <!-- One group per tab set: when the EXIF tab comes or goes under an unchanged
         index, a kept group reselects whichever tab was active instead of the remembered one. -->
    @for (withExif of [hasExif()]; track withExif) {
      <mat-tab-group class="min-w-0 [&_.mdc-tab]:!min-w-0 [&_.mdc-tab]:!px-2 [&_.mdc-tab--active_mat-icon]:!text-[var(--mat-sys-primary)]" mat-stretch-tabs="true"
                     animationDuration="0ms" [selectedIndex]="metricsTabIndex()" (selectedIndexChange)="selectMetricsTab($event)">
      <!-- EXIF section -->
      @if (hasExif()) {
        <mat-tab [aria-label]="'photo_detail.exif' | translate">
          <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'photo_detail.exif' | translate">photo_camera</mat-icon></ng-template>
        <div class="pt-3">
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
        </mat-tab>
      }

      <mat-tab [aria-label]="'photo_detail.quality' | translate">
        <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'photo_detail.quality' | translate">auto_awesome</mat-icon></ng-template>
      <div class="pt-3">
        <div class="flex flex-col gap-0.5">
          <app-metric-score-row [label]="'tooltip.aesthetic' | translate" [range]="ranges()['aesthetic']" [value]="p.aesthetic">{{ p.aesthetic | fixed:1 }}</app-metric-score-row>
          @if (p.quality_score !== null) {
            <app-metric-score-row [label]="'tooltip.quality_score' | translate" [range]="ranges()['quality_score']" [value]="p.quality_score">{{ p.quality_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.topiq_score !== null) {
            <app-metric-score-row [label]="'tooltip.topiq_score' | translate" [range]="ranges()['topiq_score']" [value]="p.topiq_score">{{ p.topiq_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.tech_sharpness !== null) {
            <app-metric-score-row [label]="'tooltip.tech_sharpness' | translate" [range]="ranges()['tech_sharpness']" [value]="p.tech_sharpness">{{ p.tech_sharpness | fixed:1 }}</app-metric-score-row>
          }
          @if (p.face_count > 0 && p.face_quality !== null) {
            <app-metric-score-row [label]="'tooltip.face_quality' | translate" [range]="ranges()['face_quality']" [value]="p.face_quality">{{ p.face_quality | fixed:1 }}</app-metric-score-row>
            <app-metric-score-row [label]="'tooltip.faces' | translate" [range]="ranges()['face_count']" [value]="p.face_count">{{ p.face_count }}</app-metric-score-row>
            @if (p.face_ratio) {
              <app-metric-score-row [label]="'tooltip.face_ratio' | translate" [range]="ranges()['face_ratio']" [value]="p.face_ratio" [percent]="true">{{ p.face_ratio * 100 | fixed:0 }}%</app-metric-score-row>
            }
            @if (p.face_sharpness !== null) {
              <app-metric-score-row [label]="'tooltip.face_sharpness' | translate" [range]="ranges()['face_sharpness']" [value]="p.face_sharpness">{{ p.face_sharpness | fixed:1 }}</app-metric-score-row>
            }
            @if (p.eye_sharpness !== null) {
              <app-metric-score-row [label]="'tooltip.eye_sharpness' | translate" [range]="ranges()['eye_sharpness']" [value]="p.eye_sharpness">{{ p.eye_sharpness | fixed:1 }}</app-metric-score-row>
            }
            @if (p.face_confidence !== null && p.face_confidence !== undefined) {
              <app-metric-score-row [label]="'tooltip.face_confidence' | translate" [range]="ranges()['face_confidence']" [value]="p.face_confidence" [percent]="true">{{ p.face_confidence * 100 | fixed:0 }}%</app-metric-score-row>
            }
          }
          @if (p.aesthetic_iaa !== null) {
            <app-metric-score-row [label]="'tooltip.aesthetic_iaa' | translate" [range]="ranges()['aesthetic_iaa']" [value]="p.aesthetic_iaa">{{ p.aesthetic_iaa | fixed:1 }}</app-metric-score-row>
          }
          @if (p.face_quality_iqa !== null) {
            <app-metric-score-row [label]="'tooltip.face_quality_iqa' | translate" [range]="ranges()['face_quality_iqa']" [value]="p.face_quality_iqa">{{ p.face_quality_iqa | fixed:1 }}</app-metric-score-row>
          }
          @if (p.liqe_score !== null) {
            <app-metric-score-row [label]="'tooltip.liqe_score' | translate" [range]="ranges()['liqe_score']" [value]="p.liqe_score">{{ p.liqe_score | fixed:1 }}</app-metric-score-row>
          }
          <app-extended-quality [photo]="p" [populated]="populated()" />
        </div>
      </div>
      </mat-tab>

      <!-- Composition section -->
      <mat-tab [aria-label]="'photo_detail.composition' | translate">
        <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'photo_detail.composition' | translate">grid_on</mat-icon></ng-template>
      <div class="pt-3">
        <div class="flex flex-col gap-0.5">
          @if (p.composition_pattern) {
            <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.pattern' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ ('composition_patterns.' + p.composition_pattern) | translate }}</span></div>
          }
          @if (p.comp_score !== null) {
            <app-metric-score-row [label]="'tooltip.composition' | translate" [range]="ranges()['comp_score']" [value]="p.comp_score">{{ p.comp_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.power_point_score !== null) {
            <app-metric-score-row [label]="'tooltip.power_points' | translate" [range]="ranges()['power_point_score']" [value]="p.power_point_score">{{ p.power_point_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.leading_lines_score !== null) {
            <app-metric-score-row [label]="'tooltip.leading_lines' | translate" [range]="ranges()['leading_lines_score']" [value]="p.leading_lines_score">{{ p.leading_lines_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.isolation_bonus !== null) {
            <app-metric-score-row [label]="'tooltip.isolation' | translate" [range]="ranges()['isolation_bonus']" [value]="p.isolation_bonus">{{ p.isolation_bonus | fixed:1 }}</app-metric-score-row>
          }
        </div>
      </div>

      <!-- Subject Saliency section -->
      @if (p.subject_sharpness !== null || p.subject_prominence !== null || p.subject_placement !== null || p.bg_separation !== null) {
        <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
          <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.saliency' | translate }}</div>
          <div class="flex flex-col gap-0.5">
            @if (p.subject_sharpness !== null) {
              <app-metric-score-row [label]="'tooltip.subject_sharpness' | translate" [range]="ranges()['subject_sharpness']" [value]="p.subject_sharpness">{{ p.subject_sharpness | fixed:1 }}</app-metric-score-row>
            }
            @if (p.subject_prominence !== null) {
              <app-metric-score-row [label]="'tooltip.subject_prominence' | translate" [range]="ranges()['subject_prominence']" [value]="p.subject_prominence">{{ p.subject_prominence | fixed:1 }}</app-metric-score-row>
            }
            @if (p.subject_placement !== null) {
              <app-metric-score-row [label]="'tooltip.subject_placement' | translate" [range]="ranges()['subject_placement']" [value]="p.subject_placement">{{ p.subject_placement | fixed:1 }}</app-metric-score-row>
            }
            @if (p.bg_separation !== null) {
              <app-metric-score-row [label]="'tooltip.bg_separation' | translate" [range]="ranges()['bg_separation']" [value]="p.bg_separation">{{ p.bg_separation | fixed:1 }}</app-metric-score-row>
            }
          </div>
        </div>
      }
      @if (p.form_symmetry !== null || p.form_balance !== null || p.form_edge_entropy !== null || p.form_fractal !== null || p.color_harmony !== null) {
        <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
          <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'tooltip.form_section' | translate }}</div>
          <div class="flex flex-col gap-0.5">
            @if (p.form_symmetry !== null) {
              <app-metric-score-row [label]="'tooltip.form_symmetry' | translate" [range]="ranges()['form_symmetry']" [value]="p.form_symmetry">{{ p.form_symmetry | fixed:1 }}</app-metric-score-row>
            }
            @if (p.form_balance !== null) {
              <app-metric-score-row [label]="'tooltip.form_balance' | translate" [range]="ranges()['form_balance']" [value]="p.form_balance">{{ p.form_balance | fixed:1 }}</app-metric-score-row>
            }
            @if (p.form_edge_entropy !== null) {
              <app-metric-score-row [label]="'tooltip.form_edge_entropy' | translate" [range]="ranges()['form_edge_entropy']" [value]="p.form_edge_entropy">{{ p.form_edge_entropy | fixed:1 }}</app-metric-score-row>
            }
            @if (p.form_fractal !== null) {
              <app-metric-score-row [label]="'tooltip.form_fractal' | translate" [range]="ranges()['form_fractal']" [value]="p.form_fractal">{{ p.form_fractal | fixed:1 }}</app-metric-score-row>
            }
            @if (p.color_harmony !== null) {
              <app-metric-score-row [label]="'tooltip.color_harmony' | translate" [range]="ranges()['color_harmony']" [value]="p.color_harmony">{{ p.color_harmony | fixed:1 }}</app-metric-score-row>
            }
          </div>
        </div>
      }
      </mat-tab>

      <!-- Technical section -->
      <mat-tab [aria-label]="'photo_detail.technical' | translate">
        <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'photo_detail.technical' | translate">tune</mat-icon></ng-template>
      <div class="pt-3">
        <div class="flex flex-col gap-0.5">
          @if (p.exposure_score !== null) {
            <app-metric-score-row [label]="'tooltip.exposure' | translate" [range]="ranges()['exposure_score']" [value]="p.exposure_score">{{ p.exposure_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.color_score !== null) {
            <app-metric-score-row [label]="'tooltip.color' | translate" [range]="ranges()['color_score']" [value]="p.color_score">{{ p.color_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.contrast_score !== null) {
            <app-metric-score-row [label]="'tooltip.contrast' | translate" [range]="ranges()['contrast_score']" [value]="p.contrast_score">{{ p.contrast_score | fixed:1 }}</app-metric-score-row>
          }
          @if (p.dynamic_range_stops !== null) {
            <app-metric-score-row [label]="'tooltip.dynamic_range' | translate" [range]="ranges()['dynamic_range_stops']" [value]="p.dynamic_range_stops">{{ p.dynamic_range_stops | fixed:1 }}</app-metric-score-row>
          }
          @if (p.mean_saturation !== null && p.mean_saturation !== undefined) {
            <app-metric-score-row [label]="'tooltip.saturation' | translate" [range]="ranges()['mean_saturation']" [value]="p.mean_saturation" [percent]="true">{{ (p.mean_saturation * 100) | fixed:0 }}%</app-metric-score-row>
          }
          @if (p.noise_sigma !== null) {
            <app-metric-score-row [label]="'tooltip.noise' | translate" [range]="ranges()['noise_sigma']" [value]="p.noise_sigma">{{ p.noise_sigma | fixed:1 }}</app-metric-score-row>
          }
          @if (p.mean_luminance !== null && p.mean_luminance !== undefined) {
            <app-metric-score-row [label]="'tooltip.luminance' | translate" [range]="ranges()['mean_luminance']" [value]="p.mean_luminance" [percent]="true">{{ p.mean_luminance * 100 | fixed:0 }}%</app-metric-score-row>
          }
          @if (p.histogram_spread !== null) {
            <app-metric-score-row [label]="'tooltip.histogram_spread' | translate" [range]="ranges()['histogram_spread']" [value]="p.histogram_spread">{{ p.histogram_spread | fixed:1 }}</app-metric-score-row>
          }
        </div>
      </div>

      </mat-tab>
      <mat-tab [aria-label]="'tooltip.histogram' | translate">
        <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'tooltip.histogram' | translate">equalizer</mat-icon></ng-template>
        <div class="pt-3">
          <app-histogram [path]="p.path" [src]="p.path | thumbnailUrl:histogramSrcSize():p.preview_revision" [monochrome]="!!p.is_monochrome"
                         [height]="histogramHeight()" [showModeToggle]="true"
                         [surface]="histogramSurface()"
                         [defaultMode]="histogramDefaultMode()"
                         [indicatorPercent]="indicatorPercent()" />
        </div>
      </mat-tab>
      </mat-tab-group>
    }
  `,
})
export class PhotoMetricsTabsComponent {
  readonly photo = input.required<Photo>();
  /** Library distributions keyed by photo column; a score without one shows its value only. */
  readonly ranges = input<Record<string, MetricDistribution>>({});
  /** Score columns whose model has run on this library (`/api/config` `populated_scores`). */
  readonly populated = input<readonly string[] | undefined>(undefined);
  readonly histogramSrcSize = input(640);
  readonly histogramHeight = input.required<number>();
  /** Which surface's persisted histogram channel mode to use. */
  readonly histogramSurface = input<HistogramSurface>('detail');
  readonly histogramDefaultMode = input<HistogramMode>('luma');
  readonly indicatorPercent = input(1);

  protected readonly hasExif = computed(() => hasExifFields(this.photo()));

  /**
   * The open tab, by name rather than index: a photo without EXIF has one tab
   * fewer, and the stored choice must still mean the same tab afterwards.
   */
  private readonly tabState = inject(MetricsTabState);
  private readonly metricsTabs = computed<MetricsTab[]>(() =>
    this.hasExif() ? [...METRICS_TABS] : METRICS_TABS.filter(tab => tab !== 'exif'));
  protected readonly metricsTabIndex = computed(() => Math.max(0, this.metricsTabs().indexOf(this.tabState.tab())));

  protected selectMetricsTab(index: number): void {
    const tabs = this.metricsTabs();
    // The group echoes back the index a missing remembered tab (EXIF, on a photo
    // without any) was clamped to; that is not the user's choice, so keep it.
    if (!tabs.includes(this.tabState.tab()) && index === this.metricsTabIndex()) return;
    const tab = tabs[index];
    if (tab) this.tabState.select(tab);
  }
}
