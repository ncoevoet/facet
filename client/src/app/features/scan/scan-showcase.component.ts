import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

/** Photos the showcase lays out: the newest large, the next four beside it. */
export const SHOWCASE_PHOTOS = 5;

/**
 * Something quiet to watch while a long scan runs: placeholder tiles that the photos the
 * scan has added to the library fill one by one, the newest large and drifting slowly.
 * Decorative only: the launcher's text, progress bar and live region carry the status,
 * and everything holds still under reduced motion.
 */
@Component({
  selector: 'app-scan-showcase',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ThumbnailUrlPipe],
  host: { class: 'block', 'aria-hidden': 'true' },
  template: `
    <div class="grid h-52 grid-cols-4 grid-rows-2 gap-2">
      @for (slot of slots(); track slot.key; let first = $first) {
        <div class="overflow-hidden rounded-xl bg-[var(--mat-sys-surface-container-high)] motion-reduce:animate-none"
             [class.col-span-2]="first" [class.row-span-2]="first" [class.animate-pulse]="!slot.path">
          @if (slot.path; as path) {
            <!-- Two elements: an element runs one animation class, and the hero both fades in and drifts. -->
            <div class="size-full motion-reduce:animate-none" [class.animate-scan-drift]="first">
              <img class="size-full object-cover animate-scan-photo-in motion-reduce:animate-none"
                   [src]="path | thumbnailUrl:(first ? 640 : 320)" alt="" decoding="async" />
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class ScanShowcaseComponent {
  /** Newest first; only the first SHOWCASE_PHOTOS are laid out. */
  readonly photos = input.required<readonly { path: string }[]>();

  /** Always SHOWCASE_PHOTOS tiles, so the panel keeps its shape while it fills. */
  protected readonly slots = computed(() => Array.from({ length: SHOWCASE_PHOTOS }, (_, i) => {
    const path = this.photos()[i]?.path ?? null;
    return { key: path ?? `empty-${i}`, path };
  }));
}
