import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18N } from '../../core/i18n/keys';
import { I18nService } from '../../core/services/i18n.service';

/** A missing measurement is never a zero or an empty score badge. */
@Pipe({ name: 'assessmentValue', pure: false })
export class AssessmentValuePipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(value: number | null | undefined): string {
    return typeof value === 'number' && Number.isFinite(value)
      ? value.toFixed(1)
      : this.i18n.t(I18N.photo_detail.assessment.unavailable);
  }
}
