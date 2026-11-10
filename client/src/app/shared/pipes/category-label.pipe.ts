import { Pipe, PipeTransform } from '@angular/core';
import { TitleCasePipe } from '@angular/common';

/** Replace underscores with spaces for display (e.g. "rule_of_thirds" → "Rule Of Thirds"). */
@Pipe({ name: 'categoryLabel', standalone: true, pure: true })
export class CategoryLabelPipe implements PipeTransform {
  private titleCase = new TitleCasePipe();
  transform(value: string | null): string {
    if (!value) return '';
    return this.titleCase.transform(value.replace(/_/g, ' '));
  }
}
