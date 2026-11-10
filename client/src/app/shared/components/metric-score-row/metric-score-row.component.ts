import { MetricDistributionComponent } from '../metric-distribution/metric-distribution.component';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { I18N } from '../../../core/i18n/keys';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { MetricDistribution } from '../../utils/metric-distribution';
import { MetricRankComponent } from '../metric-rank/metric-rank.component';

/**
 * One score as a stat: its name on a first line, then the value large (projected,
 * so each row keeps its own formatting) beside the library distribution with the
 * value's bar lit. Without a distribution, the name and the value only.
 */
@Component({
  selector: 'app-metric-score-row',
  imports: [MetricDistributionComponent, MatIconModule, MetricRankComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex min-h-8 items-center gap-3 py-0.5' },
  template: `
    <span class="flex min-w-0 flex-1 items-center gap-2 text-[var(--mat-sys-on-surface-variant)]"><mat-icon aria-hidden="true" class="!h-4 !w-4 !text-base !leading-none">{{ icon() }}</mat-icon><span class="truncate">{{ label() }}</span></span>
    <span class="shrink-0 font-semibold tabular-nums" [class.text-[var(--mat-sys-primary)]]="available()">@if (available()) { <ng-content /> } @else { {{ I18N.photo_detail.assessment.unavailable | translate }} }</span>
    @if (available() && column()) {
      <app-metric-distribution [column]="column()" [label]="label()" [category]="category()" [value]="value()" [percent]="percent()" />
    } @else if (available() && range(); as range) {
      <app-metric-rank class="shrink-0" [compact]="true" [range]="range" [value]="value()" [percent]="percent()" />
    }
  `,
})
export class MetricScoreRowComponent {
  protected readonly I18N = I18N;
  readonly column = input('');
  readonly category = input<string | null>(null);
  readonly icon = input('analytics');
  readonly label = input.required<string>();
  readonly range = input<MetricDistribution | undefined>(undefined);
  readonly value = input<number | null | undefined>(undefined);
  protected readonly available = computed(() => typeof this.value() === 'number' && Number.isFinite(this.value()));
  /** The metric is a 0-1 fraction shown as a percentage; its range is described the same way. */
  readonly percent = input(false);
}
