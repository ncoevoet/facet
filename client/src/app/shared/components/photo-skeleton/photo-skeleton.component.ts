import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** Animated placeholder card shown while gallery pages load. */
@Component({
  selector: 'app-photo-skeleton',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="animate-pulse rounded-lg bg-[var(--mat-sys-surface-container-high)] w-full"
      [style.height.px]="height()"
      aria-hidden="true"
    ></div>
  `,
  host: { class: 'block' },
})
export class PhotoSkeletonComponent {
  readonly height = input(168);
}
