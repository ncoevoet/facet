import { MetricDistributionComponent } from '../metric-distribution/metric-distribution.component';
import { Component, computed, input } from '@angular/core';
import { I18N } from '../../../core/i18n/keys';
import { Photo } from '../../models/photo.model';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { TranslatePipe } from '../../pipes/translate.pipe';

type ExtendedQuality = Pick<Photo, 'aesthetic_v25' | 'qrealign_score' | 'deqa_score'>;

const METRIC_LABELS = {
  aesthetic_v25: I18N.tooltip.aesthetic_v25,
  qrealign_score: I18N.tooltip.qrealign_score,
  deqa_score: I18N.tooltip.deqa_score,
} as const;

interface Metric {
  key: keyof typeof METRIC_LABELS;
  label: string;
  value: number | null;
}

const METRIC_KEYS = Object.keys(METRIC_LABELS) as (keyof typeof METRIC_LABELS)[];

/**
 * Omitted API fields stay hidden. A finite score always shows; a present null
 * reads "Not computed" only when the metric is populated somewhere in the library
 * (`populated`), otherwise the row is hidden. Non-finite values hide the row.
 */
@Component({
  selector: 'app-extended-quality',
  imports: [FixedPipe, TranslatePipe, MetricDistributionComponent],
  host: { class: 'block' },
  template: `
    @for (metric of metrics(); track metric.key) {
      <div class="flex justify-between items-baseline gap-2" [attr.data-testid]="metric.key + '-row'">
        <span [style.color]="tooltip() ? 'var(--facet-tooltip-text-secondary)' : 'var(--mat-sys-on-surface-variant)'">{{ metric.label | translate }}</span>
        <span class="text-[var(--mat-sys-primary)] font-medium" [attr.data-testid]="metric.key + '-score'">@if (metric.value !== null) {
          {{ metric.value | fixed:1 }}
        } @else {
          {{ I18N.tooltip.not_computed | translate }}
        }</span>
        @if (distributions() && metric.value !== null) { <app-metric-distribution [column]="metric.key" [label]="metric.label | translate" [value]="metric.value" [category]="category()" /> }
      </div>
    }
  `,
})
export class ExtendedQualityComponent {
  protected readonly I18N = I18N;
  photo = input.required<ExtendedQuality>();
  tooltip = input(false);
  readonly distributions = input(false);
  readonly category = input<string | null>(null);
  /** Score columns whose model has run on this library (`/api/config` `populated_scores`). */
  populated = input<readonly string[] | undefined>(undefined);
  metrics = computed(() => {
    const photo = this.photo();
    const populated = this.populated() ?? [];
    return METRIC_KEYS.flatMap((key): Metric[] => {
      const value: unknown = photo[key];
      if (!Object.hasOwn(photo, key) || value === undefined) return []; // Older schemas may omit the field.
      if (value === null) return populated.includes(key) ? [{ key, label: METRIC_LABELS[key], value: null }] : [];
      return typeof value === 'number' && Number.isFinite(value) ? [{ key, label: METRIC_LABELS[key], value }] : [];
    });
  });
}
