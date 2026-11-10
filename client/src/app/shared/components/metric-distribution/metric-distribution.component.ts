import { ChangeDetectionStrategy, Component, computed, effect, inject, Injector, input, signal, viewChild } from '@angular/core';
import { ControlPopoverComponent } from '../control-popover/control-popover.component';
import { MetricRankComponent } from '../metric-rank/metric-rank.component';
import { ApiService } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { I18N } from '../../../core/i18n/keys';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { PluralKeyPipe } from '../../pipes/plural-key.pipe';
import { CategoryNamePipe } from '../../pipes/category-name.pipe';
import { MetricDistribution } from '../../utils/metric-distribution';

@Component({
  selector: 'app-metric-distribution',
  imports: [ControlPopoverComponent, MetricRankComponent, TranslatePipe, PluralKeyPipe, CategoryNamePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block shrink-0' },
  template: `
    <app-control-popover #popover icon="bar_chart" [compact]="true" [label]="I18N.photo_detail.distribution.open | translate:{ metric: label() }" [content]="chart" />
    <ng-template #chart>
      <div class="flex gap-2 mb-3" role="group" [attr.aria-label]="I18N.photo_detail.distribution.scope | translate">
        <button type="button" class="min-h-11 flex-1 rounded border border-[var(--mat-sys-outline-variant)] px-2 text-xs"
                [class.bg-[var(--mat-sys-secondary-container)]]="effectiveScope() === 'library'" [attr.aria-pressed]="effectiveScope() === 'library'"
                (click)="scope.set('library')">{{ I18N.photo_detail.distribution.library | translate }}</button>
        <button type="button" class="min-h-11 flex-1 rounded border border-[var(--mat-sys-outline-variant)] px-2 text-xs disabled:opacity-50"
                [disabled]="!category()" [class.bg-[var(--mat-sys-secondary-container)]]="effectiveScope() === 'category'"
                [attr.aria-pressed]="effectiveScope() === 'category'" (click)="scope.set('category')">{{ category() ? (category() | categoryName) : (I18N.photo_detail.distribution.category | translate) }}</button>
      </div>
      @if (loading()) { <p role="status" class="text-xs">{{ I18N.ui.labels.loading | translate }}</p> }
      @else if (failed()) {
        <p role="alert" class="text-xs">{{ I18N.errors.action_failed | translate }}</p>
        <button type="button" class="min-h-11 underline text-xs" (click)="retry.set(retry() + 1)">{{ I18N.gallery.load_error.retry | translate }}</button>
      } @else if (range(); as range) {
        <app-metric-rank class="block [&_app-metric-sparkline]:!h-16" [range]="range" [value]="value()" [percent]="percent()" [scopeLabel]="effectiveScope() === 'category' && category() ? (category() | categoryName) : (I18N.photo_detail.distribution.library | translate)" />
        <p class="mb-0 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ count() | pluralKey:I18N.gallery.photo_count_one:I18N.gallery.photo_count | translate:{count: count()} }}</p>
      } @else { <p class="text-xs">{{ I18N.photo_detail.assessment.unavailable | translate }}</p> }
    </ng-template>
  `,
})
export class MetricDistributionComponent {
  protected readonly I18N = I18N;
  readonly column = input.required<string>();
  readonly label = input.required<string>();
  readonly category = input<string | null>(null);
  readonly value = input<number | null | undefined>(undefined);
  readonly percent = input(false);
  protected readonly scope = signal<'library' | 'category'>('library');
  protected readonly effectiveScope = computed(() => this.scope() === 'category' && this.category() ? 'category' : 'library');
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  protected readonly range = signal<MetricDistribution | null>(null);
  protected readonly count = signal(0);
  protected readonly retry = signal(0);
  private readonly popover = viewChild(ControlPopoverComponent);
  private readonly injector = inject(Injector);

  constructor() {
    effect(onCleanup => {
      if (!this.popover()?.open()) return;
      this.retry();
      const auth = this.injector.get(AuthService);
      const owner = auth.identity();
      const column = this.column();
      const category = this.effectiveScope() === 'category' ? this.category() : null;
      this.range.set(null);
      this.failed.set(false);
      this.loading.set(true);
      let current = true;
      const request = this.injector.get(ApiService).get<{distribution: MetricDistribution | null; count: number}>(
        '/stats/metric_distribution', { column, ...(category ? {category} : {}) }).subscribe({
          next: response => {
            if (!current || auth.identity() !== owner) return;
            this.range.set(response.distribution);
            this.count.set(response.count);
            this.loading.set(false);
          },
          error: () => { if (current && auth.identity() === owner) { this.failed.set(true); this.loading.set(false); } },
        });
      onCleanup(() => { current = false; request.unsubscribe(); });
    });
  }
}
