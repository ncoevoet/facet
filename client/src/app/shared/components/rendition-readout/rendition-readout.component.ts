import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { I18N } from '../../../core/i18n/keys';
import type { DisplayedRendition } from '../../../features/gallery/synced-zoom.component';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { FixedPipe } from '../../pipes/fixed.pipe';

/** Reports decoded display pixels; background attempts never imply readiness. */
@Component({
  selector: 'app-rendition-readout',
  imports: [TranslatePipe, FixedPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0 text-xs' },
  template: `
    <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1" data-rendition-readout>
      <span role="status">
        {{ (edited() ? I18N.photo_detail.rendition.edited : state().kind === 'source' ? I18N.gallery.compare.rendition.source : state().kind === 'thumbnail' ? I18N.gallery.compare.rendition.thumbnail : I18N.gallery.compare.rendition.preview) | translate }}
        · {{ (state().phase === 'ready' ? I18N.gallery.compare.rendition.ready : state().phase === 'failed' ? I18N.gallery.compare.rendition.failed : I18N.gallery.compare.rendition.loading) | translate }}
        @if (state().phase === 'ready' && state().width && state().height) { {{ state().width }} × {{ state().height }} }
      </span>
      @if (pending()) { <span>{{ I18N.photo_detail.rendition.pending | translate }}</span> }
      @if (state().phase === 'failed' || attemptFailed()) {
        <span class="inline-flex min-w-0 items-center gap-2">
          @if (attemptFailed()) { <span>{{ failureLabel() | translate }}</span> }
          <button type="button" data-rendition-retry class="min-h-9 shrink-0 cursor-pointer rounded border border-current/40 px-2 font-medium hover:bg-white/15 focus-visible:outline-2" (click)="retry.emit()">{{ I18N.gallery.load_error.retry | translate }}</button>
        </span>
      }
      @if (scale(); as scale) {
        <div class="ml-auto flex shrink-0 items-center gap-1">
          <button type="button" class="min-h-9 min-w-9 cursor-pointer rounded hover:bg-white/15 disabled:opacity-40" [disabled]="scale <= 1" [attr.aria-label]="I18N.gallery.compare.rendition.zoom_out | translate" (click)="zoomStep.emit(-1)">−</button>
          <button type="button" data-rendition-fit class="min-h-9 min-w-9 cursor-pointer rounded px-1 hover:bg-white/15" [attr.aria-label]="I18N.gallery.compare.rendition.fit | translate" (click)="fit.emit()">@if (scale === 1) { {{ I18N.gallery.compare.rendition.fit | translate }} } @else { {{ scale | fixed:1 }}× }</button>
          <button type="button" class="min-h-9 min-w-9 cursor-pointer rounded hover:bg-white/15 disabled:opacity-40" [disabled]="scale >= 8" [attr.aria-label]="I18N.gallery.compare.rendition.zoom_in | translate" (click)="zoomStep.emit(1)">+</button>
        </div>
      }
    </div>
  `,
})
export class RenditionReadoutComponent {
  protected readonly I18N = I18N;
  readonly state = input.required<DisplayedRendition>();
  readonly pending = input(false);
  readonly attemptFailed = input(false);
  readonly failureLabel = input<string>(I18N.photo_detail.rendition.attempt_failed);
  readonly edited = input(false);
  readonly scale = input<number | null>(null);
  readonly retry = output<void>();
  readonly zoomStep = output<number>();
  readonly fit = output<void>();
}
