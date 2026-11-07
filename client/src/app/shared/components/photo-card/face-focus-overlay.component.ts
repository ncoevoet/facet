import { AuthService } from '../../../core/services/auth.service';
import { FaceOutlinePreferences } from '../../../core/services/face-outline-preferences.service';
import { personOutlineColors, selectedPersonIds } from '../../utils/person-outline-colors';
import { Component, inject, input, signal, computed, effect, ChangeDetectionStrategy } from '@angular/core';
import { PersonFaceBoxesService } from './person-face-boxes.service';

/** A face to outline, in the photo's pixel frame (the SVG's viewBox). */
export interface FocusRect {
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
}

/**
 * Color-matched outlines on the faces of selected people, drawn over
 * a gallery thumbnail so a cluster's photos show which face it is about. The
 * SVG's viewBox is the photo's own pixel frame and its aspect handling copies
 * the thumbnail's (``meet`` for a whole image, ``slice`` for an ``object-cover``
 * crop), so the outline lands on the face with no measuring. Boxes come from
 * :class:`PersonFaceBoxesService`, which batches every tile into one request.
 */
@Component({
  selector: 'app-face-focus-overlay',
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'contents' },
  template: `
    @if (viewBox(); as vb) {
      <svg class="absolute inset-0 w-full h-full pointer-events-none z-10"
           [attr.viewBox]="vb"
           [attr.preserveAspectRatio]="cover() ? 'xMidYMid slice' : 'xMidYMid meet'"
           aria-hidden="true">
        @for (r of rects(); track $index) {
          <rect [attr.x]="r.x" [attr.y]="r.y" [attr.width]="r.w" [attr.height]="r.h"
                fill="transparent" [attr.stroke]="r.color" stroke-width="3" vector-effect="non-scaling-stroke" />
        }
      </svg>
    }
  `,
})
export class FaceFocusOverlayComponent {
  private readonly faceBoxes = inject(PersonFaceBoxesService);
  private readonly auth = inject(AuthService);
  private readonly preferences = inject(FaceOutlinePreferences);

  readonly path = input.required<string>();
  /** The gallery's comma-separated person IDs, or empty for none. */
  readonly personId = input('');
  readonly imageWidth = input<number | null>(null);
  readonly imageHeight = input<number | null>(null);
  /** True when the thumbnail is cropped to fill its tile (``object-cover``). */
  readonly cover = input(false);

  /** Selected people's normalised boxes in this photo. */
  private readonly boxes = signal<{id: number; box: number[]}[]>([]);

  private readonly focusIds = computed(() => this.preferences.enabled() ? selectedPersonIds(this.personId()) : []);
  private readonly colors = computed(() => personOutlineColors(this.personId()));

  readonly rects = computed<FocusRect[]>(() => {
    const ids = this.focusIds();
    const w = this.imageWidth();
    const h = this.imageHeight();
    if (!ids.length || !w || !h || !Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return [];
    return this.boxes()
      .filter(({ box }) => Array.isArray(box) && box.length === 4 && box.every(Number.isFinite) && box[0] >= 0 && box[1] >= 0 && box[2] <= 1 && box[3] <= 1 && box[2] > box[0] && box[3] > box[1])
      .map(({id, box: [x1, y1, x2, y2]}) => ({ x: x1 * w, y: y1 * h, w: (x2 - x1) * w, h: (y2 - y1) * h, color: this.colors().get(id)! }));
  });

  protected readonly viewBox = computed(() => {
    const w = this.imageWidth();
    const h = this.imageHeight();
    return w && h && this.rects().length > 0 ? `0 0 ${w} ${h}` : null;
  });

  constructor() {
    effect(onCleanup => {
      this.faceBoxes.revision();
      const path = this.path();
      const ids = this.focusIds();
      const owner = this.auth.identity();
      this.boxes.set([]);
      let current = true;
      if (ids.length) void Promise.all(ids.map(async id => ({id, boxes: await this.faceBoxes.boxes(id, path)}))).then(results => {
        if (current && owner === this.auth.identity()) this.boxes.set(results.flatMap(({id, boxes}) => boxes.map(box => ({id, box}))));
      });
      onCleanup(() => { current = false; });
    });
  }
}
