import { PhotoMetricSectionComponent } from './photo-metric-section.component';
import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Photo, hasExifFields } from '../../models/photo.model';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { FEATURE_MARK, MarkTonePipe } from '../../pipes/mark-tone.pipe';
import { HistogramSurface } from '../../../core/services/histogram-preferences.service';
import { METRICS_TABS, MetricsTab, MetricsTabState } from '../../../core/services/metrics-tab-state.service';
import { HistogramMode } from '../../utils/histogram';
import { MetricDistribution } from '../../utils/metric-distribution';
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
    MatIconModule, MatTabsModule, MatTooltipModule,
    TranslatePipe, MarkTonePipe, PhotoAssessmentComponent, PhotoMetricSectionComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' },
  template: `
    @let p = photo();
    <app-photo-assessment [photo]="p" [range]="ranges()['aggregate']" [explainable]="explainable()" (explain)="explain.emit()" />
    <!-- One group per tab set: when the EXIF tab comes or goes under an unchanged
         index, a kept group reselects whichever tab was active instead of the remembered one. -->
    @for (withExif of [hasExif()]; track withExif) {
      <mat-tab-group class="min-w-0 [&_.mdc-tab]:!min-w-0 [&_.mdc-tab]:!px-2 [&_.mdc-tab--active_mat-icon]:!text-[var(--mat-sys-primary)]" mat-stretch-tabs="true"
                     animationDuration="0ms" [selectedIndex]="metricsTabIndex()" (selectedIndexChange)="selectMetricsTab($event)">
      <!-- EXIF section -->
      @if (hasExif()) {
        <mat-tab [aria-label]="'photo_detail.exif' | translate">
          <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'photo_detail.exif' | translate">photo_camera</mat-icon></ng-template><app-photo-metric-section kind="exif" [photo]="p" [populated]="populated()" [histogramSrcSize]="histogramSrcSize()" [histogramHeight]="histogramHeight()" [histogramSurface]="histogramSurface()" [histogramDefaultMode]="histogramDefaultMode()" [indicatorPercent]="indicatorPercent()" /></mat-tab>
      }

      <mat-tab [aria-label]="'photo_detail.quality' | translate">
        <ng-template mat-tab-label><span aria-hidden="true" class="text-xl" [class]="'quality' | markTone" [matTooltip]="'photo_detail.quality' | translate">{{ featureMark }}</span></ng-template><app-photo-metric-section kind="quality" [photo]="p" [populated]="populated()" [histogramSrcSize]="histogramSrcSize()" [histogramHeight]="histogramHeight()" [histogramSurface]="histogramSurface()" [histogramDefaultMode]="histogramDefaultMode()" [indicatorPercent]="indicatorPercent()" /></mat-tab>

      <!-- Composition section -->
      <mat-tab [aria-label]="'photo_detail.composition' | translate">
        <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'photo_detail.composition' | translate">grid_on</mat-icon></ng-template><app-photo-metric-section kind="composition" [photo]="p" [populated]="populated()" [histogramSrcSize]="histogramSrcSize()" [histogramHeight]="histogramHeight()" [histogramSurface]="histogramSurface()" [histogramDefaultMode]="histogramDefaultMode()" [indicatorPercent]="indicatorPercent()" /></mat-tab>

      <!-- Technical section -->
      <mat-tab [aria-label]="'photo_detail.technical' | translate">
        <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'photo_detail.technical' | translate">tune</mat-icon></ng-template><app-photo-metric-section kind="technical" [photo]="p" [populated]="populated()" [histogramSrcSize]="histogramSrcSize()" [histogramHeight]="histogramHeight()" [histogramSurface]="histogramSurface()" [histogramDefaultMode]="histogramDefaultMode()" [indicatorPercent]="indicatorPercent()" /></mat-tab>
      <mat-tab [aria-label]="'tooltip.histogram' | translate">
        <ng-template mat-tab-label><mat-icon aria-hidden="true" [matTooltip]="'tooltip.histogram' | translate">equalizer</mat-icon></ng-template><app-photo-metric-section kind="histogram" [photo]="p" [populated]="populated()" [histogramSrcSize]="histogramSrcSize()" [histogramHeight]="histogramHeight()" [histogramSurface]="histogramSurface()" [histogramDefaultMode]="histogramDefaultMode()" [indicatorPercent]="indicatorPercent()" /></mat-tab>
      </mat-tab-group>
    }
  `,
})
export class PhotoMetricsTabsComponent {
  protected readonly featureMark = FEATURE_MARK;
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
  /** Opt-in "Why this score?" button on the assessment line. */
  readonly explainable = input(false);
  readonly explain = output<void>();

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
