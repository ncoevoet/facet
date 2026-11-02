import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
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
  readonly path = input.required<string>();
  readonly imageWidth = input<number | null | undefined>();
  readonly imageHeight = input<number | null | undefined>();
  readonly transform = input<string>('');
  /** Bump to re-read the objects after the editor changed them. */
  readonly revision = input(0);
  readonly objects = signal<PhotoObject[]>([]);

  constructor() {
    effect((onCleanup) => {
      const path = this.path();
      this.revision();
      let live = true;
      onCleanup(() => { live = false; });
      firstValueFrom(this.api.get<components['schemas']['PhotoObjectsResponse']>('/photo/objects', { path }))
        .then((res) => { if (live) this.objects.set(res?.objects ?? []); })
        .catch(() => { if (live) this.objects.set([]); });
    });
  }
}
