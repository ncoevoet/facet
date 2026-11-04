import { ChangeDetectionStrategy, Component, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Component({
  selector: 'app-timeline-load-failure',
  imports: [MatButtonModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex flex-wrap items-center gap-2 text-sm' },
  template: `
    <p role="alert" class="m-0">{{ I18N.timeline.load_failed | translate }}</p>
    <button mat-button (click)="retry.emit()">{{ I18N.timeline.retry | translate }}</button>
  `,
})
export class TimelineLoadFailureComponent {
  protected readonly I18N = I18N;
  readonly retry = output<void>();
}
