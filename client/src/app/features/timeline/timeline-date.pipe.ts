import { inject, Pipe, PipeTransform } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';

/** Formats timeline group dates: day → fullDate, week → "Week 46, 2025", month → "November 2025" */
@Pipe({ name: 'timelineDate', standalone: true, pure: false })
export class TimelineDatePipe implements PipeTransform {
  private readonly i18n = inject(I18nService);
  transform(dateStr: string): string {
    if (!dateStr) return '';
    // Week format: "2025-W46"
    const weekMatch = dateStr.match(/^(\d{4})-W(\d{2})$/);
    if (weekMatch) return this.i18n.t(I18N.capsules.week_title, { week: +weekMatch[2], year: weekMatch[1] });
    // Month format: "2025-11"
    if (/^\d{4}-\d{2}$/.test(dateStr)) {
      return new Intl.DateTimeFormat(this.i18n.locale(), { month: 'long', year: 'numeric' }).format(new Date(dateStr + '-15T12:00:00'));
    }
    // Day format
    return new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'full' }).format(new Date(dateStr + 'T12:00:00'));
  }
}
