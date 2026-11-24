import {ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, signal} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import type { components } from '../../core/api/schema';

export type PhotoObject = components['schemas']['PhotoObject'];

/**
 * User-marked objects drawn over the photo: a thin blue box with its label.
 * The SVG's viewBox is the photo's pixel frame, so it letterboxes like the
 * object-contain image and takes the same zoom transform. It never takes the
 * pointer, so panning and anything under it behave as if it were not there.
 */
@Component({
  selector: 'app-photo-object-layer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'absolute inset-0 pointer-events-none' },
  template: `
    @if (objects().length && imageWidth() && imageHeight()) {
      <svg class="w-full h-full" [attr.viewBox]="'0 0 ' + imageWidth() + ' ' + imageHeight()"
        preserveAspectRatio="xMidYMid meet" [style.transform]="transform()" aria-hidden="true">
        @for (o of objects(); track o.id) {
          <g>
            <rect [attr.x]="o.box[0] * imageWidth()!" [attr.y]="o.box[1] * imageHeight()!"
              [attr.width]="(o.box[2] - o.box[0]) * imageWidth()!" [attr.height]="(o.box[3] - o.box[1]) * imageHeight()!"
              fill="none" stroke="#38bdf8" stroke-width="2" vector-effect="non-scaling-stroke" />
            <text [attr.x]="o.box[0] * imageWidth()!" [attr.y]="o.box[1] * imageHeight()!" dy="-0.3em"
              [attr.font-size]="imageWidth()! / 60" fill="#38bdf8" stroke="black" stroke-width="3"
              paint-order="stroke" vector-effect="non-scaling-stroke">{{ o.label }}</text>
          </g>
        }
      </svg>
    }
  `,
})
export class PhotoObjectLayerComponent {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly path = input.required<string>();
  readonly imageWidth = input<number | null | undefined>();
  readonly imageHeight = input<number | null | undefined>();
  readonly transform = input<string>('');
  /** Bump to re-read the objects after the editor changed them. */
  readonly revision = input(0);
  readonly objects = signal<PhotoObject[]>([]);
  readonly canRetry = signal(false);
  private generation = 0;
  private shownPath = '';

  constructor() {
    effect((onCleanup) => {
      const path = this.path();
      this.revision();
      void this.load(path);
      onCleanup(() => { this.generation++; });
    });
  }

  retry(): Promise<void> {
    return this.load(this.path());
  }

  /** One objects read; the retry chip and the effect both land here. */
  private load(path: string): Promise<void> {
    const token = ++this.generation;
    // A reread of the same photo (after an object edit, or Retry) keeps the
    // boxes until it lands; only a new photo blanks the previous one's.
    if (path !== this.shownPath) this.objects.set([]);
    this.shownPath = path;
    this.canRetry.set(false);
    return firstValueFrom(
      this.api.get<components['schemas']['PhotoObjectsResponse']>('/photo/objects', { path }))
      .then((res) => {
        if (!this.destroyRef.destroyed && token === this.generation && path === this.path()) {
          this.canRetry.set(false);
          this.objects.set(res?.objects ?? []);
        }
      })
      .catch(() => {
        // The user asked for object boxes (mode on): a failed read must say
        // so instead of silently dropping every box they were shown.
        if (!this.destroyRef.destroyed && token === this.generation && path === this.path()) {
          this.objects.set([]);
          this.canRetry.set(true);
        }
      });
  }
}
