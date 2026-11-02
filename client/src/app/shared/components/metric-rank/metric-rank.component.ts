import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { I18nService } from '../../../core/services/i18n.service';
import { MetricDistribution, topPercentOf } from '../../utils/metric-distribution';
import { MetricSparklineComponent } from '../metric-sparkline/metric-sparkline.component';

/**
 * A value placed in its library-wide distribution: the distribution's bars with
 * the value's bar lit. Hovering or focusing it says the rank and range in words.
 */
@Component({
  selector: 'app-metric-rank',
  imports: [MatIconModule, MatTooltipModule, MetricSparklineComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' },
  template: `
    <span tabindex="0" role="img"
          class="block rounded-sm outline-none focus-visible:ring-1 focus-visible:ring-[var(--mat-sys-primary)]"
          [attr.aria-label]="summary()" [matTooltip]="summary()">
      @if (compact()) { <mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base !leading-none">info_outline</mat-icon> }
      @else { <app-metric-sparkline class="!h-5 [&>div]:!px-0" [range]="range()" [value]="value()" /> }
    </span>
  `,
})
export class MetricRankComponent {
  readonly range = input.required<MetricDistribution>();
  readonly value = input<number | null | undefined>(undefined);
  /** The metric is a 0-1 fraction its row shows as a percentage; the range is shown the same way. */
  readonly percent = input(false);
  readonly compact = input(false);

  private readonly i18n = inject(I18nService);

  protected readonly summary = computed(() => {
    this.i18n.translations();
    const top = topPercentOf(this.range(), this.value());
    const { min, max } = this.range();
    const bound = (v: number) => this.percent() ? `${Math.round(v * 100)}%` : formatBound(v);
    const bounds = { min: bound(min), max: bound(max) };
    return top === null
      ? this.i18n.t('photo_detail.distribution.range', bounds)
      : this.i18n.t('photo_detail.distribution.top_in_range', { pct: top, ...bounds });
  });
}

function formatBound(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
