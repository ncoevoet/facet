import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
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
  imports: [MetricRankComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block py-1.5' },
  template: `
    <span class="block truncate text-[var(--mat-sys-on-surface-variant)]">{{ label() }}</span>
    <div class="flex items-center gap-4 mt-1 pl-2 pr-1">
      <span class="shrink-0 font-semibold leading-tight tabular-nums" [class.w-12]="available()" [class.text-lg]="available()" [class.text-[var(--mat-sys-primary)]]="available()">@if (available()) { <ng-content /> } @else { {{ I18N.photo_detail.assessment.unavailable | translate }} }</span>
      @if (available() && range(); as range) {
        <app-metric-rank class="min-w-0 flex-1" [range]="range" [value]="value()" [percent]="percent()" />
      }
    </div>
  `,
})
export class MetricScoreRowComponent {
  protected readonly I18N = I18N;
  readonly label = input.required<string>();
  readonly range = input<MetricDistribution | undefined>(undefined);
  readonly value = input<number | null | undefined>(undefined);
  protected readonly available = computed(() => typeof this.value() === 'number' && Number.isFinite(this.value()));
  /** The metric is a 0-1 fraction shown as a percentage; its range is described the same way. */
  readonly percent = input(false);
}
