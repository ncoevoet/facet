import { Component, inject, input, output, signal, computed, effect, viewChild, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { FaceBoxMode } from './face-box-mode';
import { PersonFaceMenuComponent } from '../persons/person-face-menu.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../core/i18n/keys';

/** One row of ``GET /api/photo/faces``. */
export interface PhotoFaceRow {
  id: number;
  face_index: number;
  person_id?: number | null;
  person_name?: string | null;
  box?: number[] | null;
}

/** A face as drawn: its box in the photo's own pixel space, the SVG's viewBox. */
export interface DrawnFace {
  id: number;
  personId: number | null;
  name: string | null;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Label baseline, just above the box, or inside it when the box touches the top edge. */
  labelY: number;
  /** The face of a person the page is focused on (the gallery's person filter). */
  focus: boolean;
}

/** Label size as a fraction of the frame's longer edge, so it reads the same at any resolution. */
const LABEL_SCALE = 0.022;
/** A press that travels this far (CSS px) is a pan, not a click on the face. */
export const FACE_CLICK_SLOP_PX = 5;
/**
 * How long a still click waits before opening the face menu. The menu's backdrop
 * would swallow the second click of a double-click, so the open waits long enough
 * for a double-click (the zoom reset) to cancel it.
 */
export const FACE_MENU_DELAY_MS = 250;

/** Where and with what the current press on a face started. */
interface FacePress {
  x: number;
  y: number;
  touch: boolean;
}

/**
 * Faces drawn over the photo-detail image: boxes appear while the pointer is over
 * the photo (or always, in ``always`` mode; a focused person's always; none in ``off``), red while unnamed, a face's name on hovering that face, and clicking a face (edition
 * mode) opens a menu to change its person, take it off its person, or find more
 * faces like that person. Any face in a cluster, named or not, also offers its
 * cluster's photos, in read-only mode too; an unnamed face there says that naming
 * needs edition mode, so the click is never silent.
 *
 * The SVG's viewBox is the photo's own pixel frame, so it letterboxes exactly
 * like the ``object-contain`` image beneath it and shares its zoom transform:
 * boxes land on the faces with no measuring. Boxes come pre-normalised from the
 * server, which drops any whose stored dimensions cannot be trusted.
 *
 * Each face is a focusable button (Enter or Space opens its menu). Pointer
 * presses bubble to the zoom directive, so panning and the double-click reset
 * work when started on a face; only a click that stayed within
 * ``FACE_CLICK_SLOP_PX`` opens the menu. A finger cannot hover, so on touch a
 * tap opens the menu only when the box is visible (``always`` mode or a focused person).
 */
@Component({
  selector: 'app-photo-face-layer',
  imports: [PersonFaceMenuComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'contents' },
  template: `
    @if (viewBox(); as vb) {
      <svg
        class="absolute inset-0 w-full h-full pointer-events-none"
        [attr.viewBox]="vb"
        preserveAspectRatio="xMidYMid meet"
        [style.transform]="transform()">
        @for (f of faces(); track f.id) {
          <!-- Pointer gestures are left to bubble, so a pan or a double-click reset
               started on a face still reaches the zoom directive; only a click that
               did not move opens the menu. -->
          <g
            class="group/face pointer-events-auto cursor-pointer outline-none"
            role="button"
            tabindex="0"
            [attr.aria-label]="f.name || (I18N.photo_faces.unknown | translate)"
            (pointerdown)="onFacePointerDown($event)"
            (click)="onFaceClick(f, $event)"
            (dblclick)="cancelPendingOpen()"
            (keydown.enter)="onFaceKey(f, $event)"
            (keydown.space)="onFaceKey(f, $event)">
            <title>{{ f.name || (I18N.photo_faces.unknown | translate) }}</title>
            <!-- Dark outline under the coloured stroke, so it reads on any background. -->
            <rect
              [attr.x]="f.x" [attr.y]="f.y" [attr.width]="f.w" [attr.height]="f.h"
              fill="transparent"
              stroke="black"
              stroke-opacity="0.7"
              [attr.stroke-width]="(f.focus ? 4 : 2) + 2"
              vector-effect="non-scaling-stroke"
              class="transition-opacity group-hover/face:opacity-100 group-focus-visible/face:opacity-100 group-focus-visible/face:stroke-[length:10px]"
              [class.opacity-0]="!showAll() && !f.focus"
              [class.group-hover/photo:opacity-60]="!showAll() && !f.focus"
              [class.opacity-100]="showAll() || f.focus" />
            <!-- Unnamed faces are dashed as well as red, so colour is not the only cue.
                 Keyboard focus thickens the stroke and turns it blue, a cue that holds
                 even when the box is already fully shown. -->
            <rect
              data-face
              [attr.x]="f.x" [attr.y]="f.y" [attr.width]="f.w" [attr.height]="f.h"
              fill="transparent"
              [attr.stroke]="f.name ? 'white' : '#ef4444'"
              [attr.stroke-width]="f.focus ? 4 : 2"
              [attr.stroke-dasharray]="f.name ? null : '6 4'"
              vector-effect="non-scaling-stroke"
              class="transition-opacity group-hover/face:opacity-100 group-focus-visible/face:opacity-100 group-focus-visible/face:stroke-[length:6px] group-focus-visible/face:stroke-sky-400"
              [class.opacity-0]="!showAll() && !f.focus"
              [class.group-hover/photo:opacity-60]="!showAll() && !f.focus"
              [class.opacity-100]="showAll() || f.focus" />
            <text
              [attr.x]="f.x"
              [attr.y]="f.labelY"
              [attr.font-size]="labelSize()"
              fill="white"
              stroke="black"
              [attr.stroke-width]="labelSize() / 6"
              paint-order="stroke"
              font-family="sans-serif"
              font-weight="600"
              aria-hidden="true"
              class="transition-opacity select-none group-hover/face:opacity-100 group-focus-visible/face:opacity-100"
              [class.opacity-0]="!showAll() && !f.focus"
              [class.opacity-100]="showAll() || f.focus">
              {{ f.name || (I18N.photo_faces.unknown | translate) }}
            </text>
          </g>
        }
      </svg>
    }
    <app-person-face-menu [path]="path()" [canEdit]="canEdit()" (changed)="afterChange()" />
  `,
})
export class PhotoFaceLayerComponent {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);

  readonly path = input.required<string>();
  readonly imageWidth = input<number | null>(null);
  readonly imageHeight = input<number | null>(null);
  /** The image's zoom/pan transform, so the boxes stay on the faces. */
  readonly transform = input('');
  readonly canEdit = input(false);
  /**
   * ``hover`` (default) shows boxes under the pointer or focus, ``always`` keeps every
   * box and name shown, ``off`` draws nothing, so the layer is inert: no hover, no
   * menu, nothing in the tab order.
   */
  readonly mode = input<FaceBoxMode>('hover');
  protected readonly showAll = computed(() => this.mode() === 'always');
  /** Persons whose faces stay boxed (thicker) and named, e.g. the gallery's person filter. */
  readonly focusPersonIds = input<readonly number[]>([]);
  /** Emitted after a face changed person, so the page can refresh the photo's people. */
  readonly changed = output<void>();

  private readonly menu = viewChild.required(PersonFaceMenuComponent);
  private readonly rows = signal<PhotoFaceRow[]>([]);
  private press: FacePress | null = null;
  private pendingOpen: ReturnType<typeof setTimeout> | null = null;

  protected readonly viewBox = computed(() => {
    const w = this.imageWidth();
    const h = this.imageHeight();
    return this.mode() !== 'off' && w && h && this.faces().length > 0 ? `0 0 ${w} ${h}` : null;
  });

  protected readonly labelSize = computed(() =>
    Math.max(this.imageWidth() ?? 0, this.imageHeight() ?? 0) * LABEL_SCALE);


  readonly faces = computed<DrawnFace[]>(() => {
    const w = this.imageWidth();
    const h = this.imageHeight();
    if (!w || !h) return [];
    const label = this.labelSize();
    const focus = new Set(this.focusPersonIds());
    return this.rows()
      .filter((r): r is PhotoFaceRow & { box: number[] } => Array.isArray(r.box) && r.box.length === 4)
      .map((r) => {
        const [x1, y1, x2, y2] = r.box;
        const y = y1 * h;
        return {
          id: r.id,
          personId: r.person_id ?? null,
          name: r.person_name ?? null,
          x: x1 * w,
          y,
          w: (x2 - x1) * w,
          h: (y2 - y1) * h,
          labelY: y - label * 0.4 > label ? y - label * 0.4 : y + label * 1.1,
          focus: r.person_id != null && focus.has(r.person_id),
        };
      });
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => this.cancelPendingOpen());
    effect(() => {
      if (this.mode() === 'off') this.cancelPendingOpen();
    });
    effect(() => {
      const path = this.path();
      void this.load(path);
    });
  }

  async load(path: string = this.path()): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.get<{ faces: PhotoFaceRow[] }>('/photo/faces', { path }));
      if (path === this.path()) this.rows.set(res.faces ?? []);
    } catch {
      if (path === this.path()) this.rows.set([]);
    }
  }

  onFacePointerDown(event: PointerEvent): void {
    // Not stopped: the zoom directive needs it to start a pan.
    this.press = {
      x: event.clientX,
      y: event.clientY,
      touch: event.pointerType === 'touch' || (!event.pointerType && hoverless()),
    };
  }

  onFaceClick(face: DrawnFace, event: MouseEvent): void {
    const press = this.press;
    this.press = null;
    if (press) {
      if (Math.hypot(event.clientX - press.x, event.clientY - press.y) >= FACE_CLICK_SLOP_PX) return;
      // A tap on a box the user cannot see is a tap on the photo.
      if (press.touch && !this.showAll() && !face.focus) return;
    }
    event.stopPropagation();
    this.cancelPendingOpen();
    // The second click of a double-click: leave it to the zoom reset.
    if (event.detail > 1) return;
    const { clientX, clientY } = event;
    this.pendingOpen = setTimeout(() => {
      this.pendingOpen = null;
      this.openMenuAt(face, clientX, clientY);
    }, FACE_MENU_DELAY_MS);
  }

  /** Drop a still click's menu open that has not fired yet. Not stopped: the zoom directive resets on dblclick. */
  cancelPendingOpen(): void {
    if (this.pendingOpen !== null) clearTimeout(this.pendingOpen);
    this.pendingOpen = null;
  }

  onFaceKey(face: DrawnFace, event: Event): void {
    event.preventDefault();
    this.cancelPendingOpen();
    const el = event.currentTarget as HTMLElement | SVGElement | null;
    const rect = el?.getBoundingClientRect();
    this.openMenuAt(face, rect ? rect.left + rect.width / 2 : 0, rect ? rect.top + rect.height / 2 : 0, el);
  }

  private openMenuAt(face: DrawnFace, x: number, y: number, origin: HTMLElement | SVGElement | null = null): void {
    this.menu().open({
      person: face.personId === null ? null : { id: face.personId, name: face.name },
      face: { id: face.id },
    }, x, y, origin);
  }

  /** The photo's face of ``personId``, the largest box when it has several; null when it has none. */
  faceOf(personId: number): { id: number } | null {
    let best: PhotoFaceRow | null = null;
    let bestArea = -1;
    for (const r of this.rows()) {
      if (r.person_id !== personId) continue;
      const area = Array.isArray(r.box) && r.box.length === 4 ? (r.box[2] - r.box[0]) * (r.box[3] - r.box[1]) : 0;
      if (area > bestArea) {
        best = r;
        bestArea = area;
      }
    }
    return best ? { id: best.id } : null;
  }

  protected async afterChange(): Promise<void> {
    await this.load();
    this.changed.emit();
  }
}

/** True on a device whose primary pointer cannot hover (a phone or tablet). */
function hoverless(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(hover: none)').matches;
}
