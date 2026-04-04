import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';

@Pipe({ name: 'translate', pure: true })
export class TranslatePipe implements PipeTransform {
  private i18n = inject(I18nService);

  transform(key: string, vars?: Record<string, string | number>): string {
    // Reading locale() creates a signal dependency — pipe re-evaluates on locale change
    void this.i18n.locale();
    return this.i18n.t(key, vars);
  }
}
