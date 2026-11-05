import { ContextHelpComponent } from '../context-help/context-help.component';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { I18N } from '../../../core/i18n/keys';
import { AssessmentValuePipe } from '../../pipes/assessment-value.pipe';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { MetricDistribution } from '../../utils/metric-distribution';
import { MetricRankComponent } from '../metric-rank/metric-rank.component';

export interface AssessmentPhoto {
  aggregate: number | null;
  aesthetic?: number | null;
  tech_sharpness?: number | null;
  comp_score?: number | null;
  face_quality?: number | null;
  face_quality_iqa?: number | null;
  assessment_states?: { face_quality_iqa?: 'not_applicable' } | null;
}

const MEASUREMENTS = [
  ['aesthetic', I18N.tooltip.aesthetic],
  ['tech_sharpness', I18N.tooltip.tech_sharpness],
  ['comp_score', I18N.tooltip.composition],
  ['face_quality', I18N.tooltip.face_quality],
  ['face_quality_iqa', I18N.tooltip.face_quality_iqa],
] as const;

/** Common evidence summary for full photo rows and the smaller darkroom feed.
 * Omitted feed fields are not treated as observations; null is unavailable,
 * without inferring a cause that the API does not supply. */
@Component({
  selector: 'app-photo-assessment',
  imports: [ContextHelpComponent,AssessmentValuePipe, TranslatePipe, MetricRankComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0 text-xs' },
  template: `
    <details data-photo-assessment class="min-w-0">
      <summary class="max-sm:min-h-11 pointer-coarse:min-h-11 cursor-pointer py-1.5">
        <span class="font-medium">{{ I18N.photo_detail.assessment.score | translate }} {{ photo().aggregate | assessmentValue }}</span>
        <span class="ml-2 opacity-75">{{ I18N.photo_detail.assessment.measurements | translate:{ available: availableCount(), total: measurements().length } }}</span>
      </summary>
      <div class="max-h-48 overflow-y-auto rounded border border-current/20 p-2">

        @if (aggregateAvailable() && range(); as range) { <app-metric-rank class="mb-2" [range]="range" [value]="photo().aggregate" /> }
        <dl class="m-0 grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1">
          @for (metric of measurements(); track metric.key) {
            <dt class="min-w-0">{{ metric.label | translate }}</dt><dd class="m-0 tabular-nums">@if (metric.notApplicable) {
              <span [title]="I18N.photo_detail.assessment.face_iqa_declined_help | translate">{{ I18N.photo_detail.assessment.not_applicable | translate }}</span>
            } @else { {{ metric.value | assessmentValue }} }</dd>
          }
        </dl>
        @if (groupPick()) { <p class="m-0 mt-2">{{ I18N.photo_detail.assessment.group_pick_help | translate }}</p> }
        <app-context-help [label]="I18N.photo_detail.assessment.help" [keys]="[I18N.photo_detail.assessment.explanation, I18N.photo_detail.assessment.unavailable_help, I18N.photo_detail.assessment.face_iqa_declined_help]" />
      </div>
    </details>
  `,
})
export class PhotoAssessmentComponent {
  protected readonly I18N = I18N;
  readonly photo = input.required<AssessmentPhoto>();
  readonly groupPick = input(false);
  readonly range = input<MetricDistribution | undefined>(undefined);
  protected readonly aggregateAvailable = computed(() => typeof this.photo().aggregate === 'number' && Number.isFinite(this.photo().aggregate));
  protected readonly measurements = computed(() => {
    const photo = this.photo();
    return MEASUREMENTS.filter(([key]) => Object.hasOwn(photo, key)).map(([key, label]) => ({ key, label, value: photo[key], notApplicable: key === 'face_quality_iqa' && photo[key] == null && photo.assessment_states?.face_quality_iqa === 'not_applicable' }));
  });
  protected readonly availableCount = computed(() => this.measurements().filter(({ value }) => typeof value === 'number' && Number.isFinite(value)).length);
}
