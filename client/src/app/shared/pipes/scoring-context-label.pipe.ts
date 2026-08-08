import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';

export interface LabeledScoringContext {
  name: string;
  label_key: string;
}

export function resolveScoringContextLabel(context: LabeledScoringContext, translated: string): string {
  return translated === context.label_key ? context.name : translated;
}

@Pipe({ name: 'scoringContextLabel', pure: false })
export class ScoringContextLabelPipe implements PipeTransform {
  private i18n = inject(I18nService);

  transform(context: LabeledScoringContext): string {
    return resolveScoringContextLabel(context, this.i18n.t(context.label_key));
  }
}
